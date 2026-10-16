# -*- coding: utf-8 -*-
"""Client：拿着一份凭证对 {BASE_URL}/api/v1 发请求；以及包顶层的 login / logout / whoami / submit / job / devices。

    c = quafu.Client()                         # 凭证：参数 > QUAFU_API_KEY > 本机保存的登录态 > 发起网页登录（仅可交互时）
    c = quafu.Client(api_key='qf_…', base_url='https://quafu.com.cn')   # 显式身份，可同时持有多个
    job = c.submit(qasm, target='sim')

请求策略：
- 读请求连不上或 5xx 才重试，0.5→8 秒指数退避加抖动，最多 5 次；4xx 一律不重试。
- 提交带 client_ref 幂等键：回应丢失后用同一个键重放，平台回原来那个任务组，绝不双发。
- 调用方给了时限（result / wait 的 timeout）时，每次超时与退避都用剩余时限封顶。
- 凭证只在第一个需要登录的请求时才要；设备清单这类公开数据不带凭证。
- 提交前按目标的 limits（平台公开的资源上限）先在本地查比特数与 shots，明显超限的不发请求就报错；取不到 limits
  时跳过，交给平台判（见 _limits）。"""
import json
import logging
import operator
import os
import random
import sys
import threading
import time
import uuid
from urllib.parse import quote, urlencode

from . import _limits, config, credentials, oauth
from ._i18n import t
from ._inputs import normalize_circuit, normalize_parameters, normalize_points
from ._qasm import to_qasm
from .devices import Calibration, Device
from .errors import (QuafuError, BadRequest, CredentialsError, LoginExpired, LoginFailed, LoginRevoked, NotLoggedIn,
                     ProtocolError, QuotaError, ServerUnavailable, SubmitUncertain, Timeout, from_response, snippet)
from .jobs import Job
from .transport import HTTPTransport

log = logging.getLogger('quafu')

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
SUBMIT_READ_TIMEOUT = 120.0        # 提交要等平台同步预检；与对外入口反向代理的读超时同值
RETRY_MAX = 5
BACKOFF_FIRST, BACKOFF_MAX = 0.5, 8.0
EXPIRY_WARN_DAYS = 7
COMPILERS = {'qiskit': 'logical', 'none': 'physical'}
OAUTH_ERRORS = ('invalid_request', 'invalid_client', 'invalid_grant', 'unauthorized_client', 'unsupported_grant_type',
                'invalid_scope')               # RFC 6749 §5.2 的错误码：令牌端点的错误体里 error 是它们之一

_warned = set()
_warned_lock = threading.Lock()


def warn_once(key, msg, *args):
    with _warned_lock:
        if key in _warned:
            return
        _warned.add(key)
    log.warning(msg, *args)


def user_agent():
    from . import __version__
    return 'quafu-sdk/%s python/%d.%d' % (__version__, sys.version_info[0], sys.version_info[1])


def _date(iso):
    try:
        return credentials.parse_time(iso).astimezone().strftime('%Y-%m-%d')
    except (TypeError, ValueError, AttributeError):
        return str(iso)


def expired_text(cred):
    return t('client.login_expired', _date(cred.expires_at))


def not_logged_in_text(base_url):
    return t('client.not_logged_in', base_url, credentials.ENV_KEY)


class BaseClient(object):
    """请求、凭证与登录：Client 与过渡期的旧功能共用这一层。

    参数：api_key（显式身份）、base_url（平台地址，缺省读 QUAFU_BASE_URL，再缺省用内置默认值）、
    ca_bundle（自签 CA 的 PEM）、proxy（host:port 的 HTTP 代理）；后两者也可用环境变量 QUAFU_CA_BUNDLE /
    QUAFU_PROXY 给。不给 proxy 就不走任何代理（不读系统代理设置）。"""

    def __init__(self, api_key=None, base_url=None, ca_bundle=None, proxy=None, *, _transport=None):
        self.base_url = config.resolve_base_url(base_url)
        self.api = config.api_root(self.base_url)
        self._transport = _transport or HTTPTransport(
            ca_bundle=ca_bundle or os.environ.get('QUAFU_CA_BUNDLE') or None,
            proxy=proxy or os.environ.get('QUAFU_PROXY') or None)
        self._lock = threading.RLock()            # 可重入：登录过程中验身份的请求还会进 _require_creds
        self._creds = credentials.resolve(api_key, self.base_url)

    # ── 凭证 ─────────────────────────────────────────────────────────

    @property
    def credential(self):
        """当前用的凭证（repr 只显示掩码）；还没有时为 None。"""
        return self._creds

    def __repr__(self):
        return '%s(base_url=%r, credential=%r)' % (type(self).__name__, self.base_url,
                                                   self._creds.mask if self._creds else None)

    def _require_creds(self):
        """拿到能用的凭证。没有、或本机保存的网页登录已过期时：能交互就当场发起网页登录，否则记一条日志（logger quafu，
        WARNING）并抛错，不等输入——后台脚本、计划任务里等不到人。"""
        with self._lock:
            c = self._creds
            if c is not None and c.kind == 'oauth' and c.source == 'saved':
                if c.expired():
                    if not oauth.interactive():
                        log.warning(t('client.not_logged_in_log'), self.base_url)
                        raise LoginExpired(expired_text(c), expires_at=c.expires_at)
                    sys.stderr.write(expired_text(c) + t('client.relogin'))
                    c = None
                else:
                    warn_expiring(self.base_url, c)
            if c is None:
                if not oauth.interactive():
                    log.warning(t('client.not_logged_in_log'), self.base_url)
                    raise NotLoggedIn(not_logged_in_text(self.base_url))
                c = web_login(self)
            self._creds = c
            return c

    # ── 请求 ─────────────────────────────────────────────────────────

    def _request(self, method, path, body=None, form=None, endpoint='other', read_timeout=READ_TIMEOUT,
                 retry='read', deadline=None, task_id=None, job_id=None, auth=True, connect_timeout=None):
        """发一个请求，2xx 返回解析好的 JSON（dict），其余抛映射好的异常。
        body 发 JSON，form 发表单（OAuth 端点用）。retry：'read' 连不上或 5xx 都重试；'unsent' 只在请求确定
        没发出时重试；'none' 不重试。deadline 是 time.monotonic() 的截止时刻，到点抛 Timeout。
        auth=False 的是公开端点：不带凭证，也不要求登录。"""
        url = self.api + path
        headers = {'User-Agent': user_agent(), 'Accept': 'application/json'}
        cred = self._require_creds() if auth else None
        if cred is not None:
            headers['Authorization'] = cred.authorization()
        data = None
        if body is not None:
            try:
                data = json.dumps(body, allow_nan=False).encode('utf-8')
            except ValueError:
                raise ValueError(t('client.nan_body')) from None
            headers['Content-Type'] = 'application/json'
        elif form is not None:
            data = urlencode(form).encode('ascii')
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        attempt = 0
        while True:
            attempt += 1
            ct, rt = connect_timeout or CONNECT_TIMEOUT, read_timeout
            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise Timeout(t('client.deadline'), task_id=task_id, job_id=job_id)
                ct, rt = min(ct, left), min(rt, left)
            try:
                resp = self._transport.request(method, url, headers, data, ct, rt)
            except ServerUnavailable as e:
                if retry != 'none' and attempt < RETRY_MAX and (retry == 'read' or not e.sent):
                    self._backoff(attempt, deadline, task_id, job_id)
                    continue
                if retry == 'unsent' and e.sent:
                    raise SubmitUncertain(self._uncertain_text(e), sent=True) from e
                raise
            if 200 <= resp.status < 300:
                return self._json(resp)
            err = self._error(resp, endpoint, task_id, job_id, cred)
            if isinstance(err, ServerUnavailable):
                if retry == 'read' and attempt < RETRY_MAX:
                    self._backoff(attempt, deadline, task_id, job_id)
                    continue
                if retry == 'unsent':
                    raise SubmitUncertain(self._uncertain_text(err), sent=True, status=resp.status) from err
            raise err

    def _backoff(self, attempt, deadline, task_id, job_id):
        delay = min(BACKOFF_MAX, BACKOFF_FIRST * 2 ** (attempt - 1)) * random.uniform(0.5, 1.0)
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise Timeout(t('client.deadline'), task_id=task_id, job_id=job_id)
            delay = min(delay, left)
        time.sleep(delay)

    @staticmethod
    def _uncertain_text(e):
        return t('client.submit_uncertain', e)

    @staticmethod
    def _json(resp):
        try:
            d = json.loads(resp.body.decode('utf-8'))
        except ValueError as e:
            raise ProtocolError(t('client.not_json', resp.status, snippet(resp.body)),
                                status=resp.status) from e
        if not isinstance(d, dict):
            raise ProtocolError(t('client.json_not_object', resp.status, snippet(resp.body)),
                                status=resp.status)
        return d

    def _error(self, resp, endpoint, task_id, job_id, cred):
        if 300 <= resp.status < 400:
            return ProtocolError(t('client.redirect', resp.status, resp.headers.get('location', '?')),
                                 status=resp.status)
        try:
            body = json.loads(resp.body.decode('utf-8'))
        except ValueError:
            body = None
        err = from_response(endpoint, resp.status, body, resp.headers, resp.body, task_id=task_id,
                            who=cred.mask if cred else t('client.who_not_logged_in'), job_id=job_id)
        if isinstance(err, LoginRevoked) and cred is not None and cred.kind == 'oauth':
            err.args = (t('client.oauth_revoked', cred.mask),)
        return err

    def _me(self):
        return self._request('GET', '/auth/me')

    def whoami(self):
        """当前身份：{public_id, name, email, kind, source, expires_at, base_url, credential}。
        kind 是 api_key 或 oauth（网页登录），source 是凭证从哪来：argument（参数）/ env（环境变量
        QUAFU_API_KEY）/ saved（本机保存的登录态）。credential 是掩码，不是凭证本身。"""
        user = self._me().get('user') or {}
        c = self._creds
        return {'public_id': user.get('public_id') or None, 'name': user.get('name'), 'email': user.get('email'),
                'kind': c.kind, 'source': c.source, 'expires_at': c.expires_at, 'base_url': self.base_url,
                'credential': c.mask}


class Client(BaseClient):
    __doc__ = BaseClient.__doc__

    def devices(self):
        """能交到哪些目标：[{name, kind, status, n_qubits, queue, limits}, …]，name 就是 submit 的 target。

        kind 为 real（真机）或 sim（模拟器）：'sim' 是理想模拟，'<真机名>-sim' 是按该真机校准数据的带噪模拟，
        '<真机名>-sim-jiuding' 是九鼎模拟：无噪声，但比特编号、连接图与原生门集都照那台真机（需要登录才能提交）。
        九鼎模拟这几行另有 max_qubits：线路里实际参与计算的比特最多几个；n_qubits 仍是那台真机的比特数
        （比特编号的范围），status 为 online / standby / starting / offline：standby 是待命（没有人在用时模拟器不占算力，
        照常提交即可，提交后自动启动，第一条任务多等一会儿），starting 时也可以提交，任务排队等模拟器就绪。
        status 是平台口径的状态（online、calibrating、offline 等）；queue 是前面排着的任务数，不知道时为 None。
        limits 是这个目标的资源上限（比特数、shots 取值、深度、墙钟等），平台原样给出，与
        GET {BASE_URL}/api/v1/backends/<name>/metadata 的 limits 同源；平台没给时为 None。
        另有两种不指定某一台的目标：'all-race'（同时发给所有在线真机、取最先完成的）与 'all-redispatch'
        （先发一台，不可用自动换下一台）。公开数据，不需要登录。"""
        d = self._request('GET', '/devices', auth=False)
        out = []
        sim = d.get('simulator') or {}
        if sim:
            out.append({'name': sim.get('name') or 'sim', 'kind': 'sim', 'status': sim.get('status'),
                        'n_qubits': sim.get('max_qubits'), 'queue': None, 'limits': sim.get('limits')})
        chips = [row for row in d.get('devices') or [] if isinstance(row, dict) and row.get('name')]
        for row in chips:
            out.append({'name': row['name'], 'kind': 'real', 'status': row.get('status'),
                        'n_qubits': row.get('n_qubits'), 'queue': row.get('queue'), 'limits': row.get('limits')})
        for row in chips:
            if row.get('simulator_available'):
                out.append({'name': row['name'] + '-sim', 'kind': 'sim',
                            'status': sim.get('status') or 'online', 'n_qubits': row.get('n_qubits'),
                            'queue': None, 'limits': row.get('sim_limits')})
        # 九鼎模拟：n_qubits 取真机比特数而不是 max_qubits，因为线路按那台真机的编号写（物理线路的比特号可以大于
        # max_qubits），与 metadata 和 Qiskit Target 的 n_qubits 一致；参与计算的比特上限另给 max_qubits
        for row in d.get('simulated_chips') or []:
            if isinstance(row, dict) and row.get('name'):
                out.append({'name': row['name'], 'kind': 'sim', 'status': row.get('status'),
                            'n_qubits': row.get('n_qubits'), 'queue': row.get('queue'),
                            'max_qubits': row.get('max_qubits'), 'limits': row.get('limits')})
        return out

    def submit(self, circuits, target, shots=1024, compiler='qiskit', name=None, parameters=None):
        """交一条或一组线路，立刻返回任务组句柄（Job），不等结果。

        circuits  OpenQASM 2.0 文本，或 qiskit.QuantumCircuit；也可以是它们的列表（一次交多条，组成一个任务组）。
                  列表里的一项也可以写成 {"qasm", "shots", "name", "parameter_values", "metadata"}
        target    交到哪里：真机名（如 'Dongling'）| '<真机名>-sim' 按该真机的带噪模拟 | 'sim' 理想模拟 |
                  '<真机名>-sim-jiuding' 九鼎模拟（无噪声，按该真机的连接图与原生门集） |
                  'all-race' 同时发给所有在线真机、取最先完成的 | 'all-redispatch' 先发一台、不可用自动换。
                  可选的名字见 devices()
        shots     每条线路跑几次。取值范围与步长（真机要求某个数的整数倍）因目标而异，以
                  GET {BASE_URL}/api/v1/backends/<target>/metadata 的 limits 为准（devices() 每行的 limits 同源）
        compiler  'qiskit'（默认）：平台按目标芯片编译你的逻辑线路；
                  'none'：不编译，线路必须已经是这台芯片上的物理线路（比特号就是芯片上的编号）
        name      任务组名，可选，网站「我的任务」里显示它
        parameters 线路项带 parameter_values 时，声明这些参数的名字与单位：[{"name": "theta", "unit": "rad"}]

        线路或参数不合平台要求时抛 PrecheckError，超额度抛 QuotaError。比特数或 shots 超出这个目标的 limits 时，
        不发请求就在本地抛 PrecheckError（vars['local'] 为 True，vars['limits_url'] 是查询地址）。"""
        single = not isinstance(circuits, (list, tuple))
        items = [circuits] if single else list(circuits)
        if not items:
            raise ValueError(t('client.empty_circuits'))
        body = self._job_body('single' if single else 'collection', target, shots, compiler)
        body['circuits'] = [_circuit_item(c, t('client.where_circuit') if single else t('client.where_circuit_n', i)) for i, c in enumerate(items)]
        if parameters is not None:
            body['parameters'] = normalize_parameters(parameters)
        self._check_limits(body['target'], body['shots'], body['circuits'])
        return self._create_job(body, name, len(items))

    def sweep(self, template, parameters, points, target, shots=1024, compiler='qiskit', name=None):
        """扫参：交一个带参数占位的线路模板和一组参数点，平台逐点代入，每个点是任务组里的一个任务。

        template    OpenQASM 2.0 模板，门参数的位置写 {{参数名}}，如 rx({{theta}}) q[0];
        parameters  参数声明 [{"name": "theta", "unit": "rad"}]（或 [("theta", "rad")]），unit 必填，无量纲写 "1"
        points      参数点表，每行按 parameters 的顺序给值；可传 numpy 数组，只有一个参数时每行可以是单个数
        其余参数同 submit()。结果用 job.table()（按参数点对齐的列式表，可转 pandas）或 job.results()。
        Qiskit 参数化线路（Parameter）请用 quafu.qiskit.sweep。"""
        if not isinstance(template, str) or not template.strip():
            raise TypeError(t('client.template_type'))
        body = self._job_body('sweep', target, shots, compiler)
        body.update(template_qasm=template, parameters=normalize_parameters(parameters), points=normalize_points(points))
        self._check_limits(body['target'], body['shots'], template=template)
        return self._create_job(body, name, len(body['points']))

    def open_job(self, target, template=None, parameters=None, shots=1024, compiler='qiskit', name=None):
        """开一个迭代式任务组（VQE、QAOA 这类「看了结果再决定下一轮交什么」的循环），返回 Job，open 为真。
        之后每一轮 job.append(points=... 或 circuits=..., iteration=k)、job.wait()、job.table() 或 job.results()，
        结束时 job.close()。给了 template 与 parameters 才能按参数点追加；否则按线路追加。"""
        body = self._job_body('iterative', target, shots, compiler)
        if template is not None:
            body['template_qasm'] = template
        if parameters is not None:
            body['parameters'] = normalize_parameters(parameters)
        self._check_limits(body['target'], body['shots'], template=template)
        job = self._create_job(body, name, 0)
        job.open = True
        return job

    def _check_limits(self, target, shots, circuits=(), template=None):
        """提交前按目标的 limits 本地查比特数与 shots。先要凭证：没登录时先报没登录，不先为查上限跑一趟网络。"""
        self._require_creds()
        _limits.check(self, target, shots, circuits, template)

    def _job_body(self, mode, target, shots, compiler):
        if not isinstance(target, str) or not target.strip():
            raise BadRequest(t('client.target_required'))
        if compiler not in COMPILERS:
            raise BadRequest(t('client.compiler_invalid', ' / '.join(repr(k) for k in COMPILERS), compiler))
        return {'mode': mode, 'target': target.strip(), 'shots': operator.index(shots),
                'circuit_level': COMPILERS[compiler]}

    def _create_job(self, body, name, n_expected):
        """建任务组：自带幂等键 client_ref，回应丢失时同键重放，平台回原来那个任务组，不会重复建。"""
        if name is not None:
            body['name'] = name
        body['client_ref'] = str(uuid.uuid4())
        d = self._request('POST', '/jobs', body=body, endpoint='job', read_timeout=SUBMIT_READ_TIMEOUT, retry='read')
        if not d.get('job_id'):
            raise ProtocolError(t('client.missing_job_id', snippet(json.dumps(d, ensure_ascii=False))))
        n = len(d.get('task_ids') or []) or d.get('n_tasks') or n_expected
        return Job(self, d['job_id'], n_tasks=n, status=d.get('status'), open=d.get('open'), target=body['target'])

    def device(self, name):
        """一台设备（Device）：状态、比特数、排队数与当前校准标识；device.calibration() 取它当前的校准数据。
        名称不存在时抛 BadRequest（code 为 unknown_device）。公开数据，不需要登录。"""
        return Device(self, self._request('GET', '/devices/%s' % quote(name, safe=''), auth=False))

    def device_calibration(self, name):
        """该设备当前的校准数据（Calibration）。公开数据。"""
        return Calibration(self._request('GET', '/devices/%s/calibration' % quote(name, safe=''), auth=False))

    def calibration(self, calibration_id):
        """按标识取一份校准数据（Calibration），不可变、永久可取：Result.calibration_id 指向的就是它。公开数据。"""
        return Calibration(self._request('GET', '/calibrations/%s' % quote(calibration_id, safe=''), auth=False))

    def metadata(self, target):
        """一个目标的描述（n_qubits、basis_gates、coupling_map、limits…），Qiskit 后端据此装 Target。公开数据。
        limits 是这个目标的资源上限：max_qubits（按 qubit_count 数：declared 声明宽度 / active 被门碰过的比特）、
        min_shots / max_shots / shots_step、max_depth、wall_s、max_tasks_per_job 等，是平台唯一的口径。"""
        return self._request('GET', '/backends/%s/metadata' % quote(target, safe=''), auth=False)

    def stats(self, days=30):
        """本人的用量统计与这个配额日的额度（平台原样）：tasks、shots、jobs、daily、quota、durations。

        quota 是 {date, sim, noisy, real}：date 是配额日（北京时间 23:00 切换，不是零点）；每种后端一格
        {used 已交条数, limit 正常额度, hard_limit 每日硬上限, remaining 正常额度内剩余, degraded 之后交的任务会不会
        降级排队, resets_at 下次重置的时刻}。超出正常额度不报错，只排在额度内的任务之后；交到硬上限才抛 QuotaError。
        没有额度的格（游客的理想模拟）limit / hard_limit / remaining / resets_at 为 None。"""
        return self._request('GET', '/stats/me?' + urlencode({'days': operator.index(days)}))

    def job(self, job_id):
        """按任务组号接回（只能接回自己的）：不存在或不是自己的抛 JobNotFound。"""
        if not isinstance(job_id, str) or not job_id.strip():
            raise BadRequest(t('client.job_id_type'))
        j = Job(self, job_id.strip())
        j._refresh()
        return j


def _circuit_item(c, where):
    """submit 的一项：文本或 Qiskit 线路先按 where 报清楚的错，再规整成平台的线路项。"""
    if isinstance(c, dict):
        return normalize_circuit(c)
    return normalize_circuit(to_qasm(c, where))


# ── 登录、登出与到期提示 ─────────────────────────────────────────────

def warn_expiring(base_url, cred):
    """网页登录到期前 7 天内，每个进程第一次用它时在标准错误提示一次。"""
    exp = cred.expires()
    if exp is None:
        return
    left = exp - credentials.now()
    if left.total_seconds() <= EXPIRY_WARN_DAYS * 86400:
        with _warned_lock:
            if ('expiring', base_url) in _warned:
                return
            _warned.add(('expiring', base_url))
        sys.stderr.write(t('client.expiring', _date(cred.expires_at)))


def _exchange(client, code, redirect_uri, verifier):
    """授权码 → 令牌。错误按 RFC 6749 §5.2（error 是机器码），文案里不带授权码与令牌。"""
    form = {'grant_type': 'authorization_code', 'code': code, 'code_verifier': verifier,
            'redirect_uri': redirect_uri, 'client_id': oauth.CLIENT_ID}
    try:
        return client._request('POST', oauth.TOKEN_PATH, form=form, auth=False, retry='unsent')
    except (ServerUnavailable, QuotaError):
        raise
    except QuafuError as e:
        body = e.body if isinstance(e.body, dict) else {}
        code_ = body.get('error') if body.get('error') in OAUTH_ERRORS else e.code
        if code_ == 'invalid_grant':
            raise LoginFailed(t('client.invalid_grant'),
                              status=e.status, code=code_) from None
        raise LoginFailed(t('client.token_failed', e.status, code_ or t('client.unknown_error')),
                          status=e.status, code=code_) from None


def web_login(client, open_browser=True, timeout=None, reader='auto', out=None, browser=None, announce=True):
    """走一遍网页登录，验一次身份，存进本机，返回 Credential（source='saved'）。
    换掉的旧网页登录令牌尽力撤销。announce=False 时不打印「已登录」那一行（命令行自己打一行更全的）。"""
    token, device = oauth.run(client.base_url, lambda c, r, v: _exchange(client, c, r, v), open_browser=open_browser,
                              timeout=oauth.LOGIN_TIMEOUT if timeout is None else timeout, reader=reader,
                              out=out, browser=browser)
    access = token.get('access_token')
    if not isinstance(access, str) or (token.get('token_type') or 'Bearer').lower() != 'bearer':
        raise LoginFailed(t('client.token_bad_format'))
    created = credentials.now()
    if token.get('expires_at'):
        expires_at = credentials.parse_time(token['expires_at']).isoformat(timespec='seconds')
    else:
        try:
            expires_at = (created + _seconds(token.get('expires_in'))).isoformat(timespec='seconds')
        except (TypeError, ValueError):
            raise LoginFailed(t('client.token_no_expiry')) from None
    cred = credentials.Credential(access, 'oauth', 'saved', expires_at=expires_at, device_name=device,
                                  created_at=created.isoformat(timespec='seconds'))
    client._creds = cred
    user = client._me().get('user') or {}
    cred.user = {'public_id': user.get('public_id') or None, 'name': user.get('name')}
    _save_replacing(client, cred)
    if announce:
        (out or sys.stdout).write(t('client.web_logged_in', user.get('name') or '', user.get('public_id') or '',
                                    _date(expires_at)))
    return cred


def _seconds(v):
    from datetime import timedelta
    n = float(v)
    if not n > 0:
        raise ValueError(v)
    return timedelta(seconds=n)


def _save_replacing(client, cred):
    """存新凭证；本机原来那份若是网页登录令牌、且与新的不同，尽力在平台上撤销它（失败不影响登录）。"""
    try:
        old = credentials.saved(client.base_url)
    except CredentialsError:
        old = None
    path = credentials.save(client.base_url, cred)
    if old is not None and old.kind == 'oauth' and old._token != cred._token:
        revoke(client, old)
    return path


def revoke(client, cred):
    """在平台上撤销一个网页登录令牌（RFC 7009），5 秒超时、不重试。返回是否确认撤销。"""
    try:
        client._request('POST', oauth.REVOKE_PATH, form={'token': cred._token, 'token_type_hint': 'access_token',
                                                         'client_id': oauth.CLIENT_ID},
                        auth=False, retry='none', read_timeout=oauth.REVOKE_TIMEOUT,
                        connect_timeout=oauth.REVOKE_TIMEOUT)
        return True
    except QuafuError as e:
        log.info(t('client.revoke_failed_log'), type(e).__name__)
        return False


def login(api_key=None, *, force=False, open_browser=True, base_url=None, timeout=None, _transport=None,
          _announce=True):
    """登录 QUAFU，把登录态存在本机（按平台地址分开存），返回 whoami() 的内容另加 saved_to（文件路径）。

    login()                     网页登录：打印一个链接并尝试打开浏览器，在网页上登录、点「授权」即可；
                                网页上显示授权码时把它粘回来。已登录且离到期还有 7 天以上时直接返回，不重复登录
    login(force=True)           强制重新登录（换账号、提前续期）
    login(api_key='qf_…')       把一把 API Key 存进本机（先向平台验一次，验不过不存）
    login(open_browser=False)   只打印链接，不自动打开浏览器
    网页登录从授权起 90 天有效，到期重新登录；API Key 不过期。
    _announce 只给命令行用：它自己打印「已登录」，这里就不再打一遍。"""
    client = Client(base_url=base_url, _transport=_transport)
    if credentials.ENV_KEY in os.environ and os.environ[credentials.ENV_KEY].strip():
        sys.stderr.write(t('client.env_key_set', credentials.ENV_KEY))
    if api_key is not None:
        cred = credentials.Credential(api_key, 'api_key', 'argument')
        client._creds = cred
        user = client._me().get('user') or {}
        cred = credentials.Credential(api_key, 'api_key', 'saved', created_at=credentials.now().isoformat(
            timespec='seconds'), user={'public_id': user.get('public_id') or None, 'name': user.get('name')})
        path = _save_replacing(client, cred)
        client._creds = cred
        return dict(_saved_info(client, cred), saved_to=path)
    current = credentials.saved(client.base_url)
    if current is not None and not force:
        exp = current.expires()
        if exp is None or (exp - credentials.now()).total_seconds() > EXPIRY_WARN_DAYS * 86400:
            return dict(_saved_info(client, current), saved_to=credentials.credentials_path())
    cred = web_login(client, open_browser=open_browser, timeout=timeout, announce=_announce)
    return dict(_saved_info(client, cred), saved_to=credentials.credentials_path())


def _saved_info(client, cred):
    user = cred.user or {}
    return {'public_id': user.get('public_id'), 'name': user.get('name'), 'kind': cred.kind, 'source': 'saved',
            'expires_at': cred.expires_at, 'base_url': client.base_url, 'credential': cred.mask}


def logout(*, base_url=None, _transport=None):
    """删除本机保存的这个平台的登录态。网页登录令牌先在平台上撤销（5 秒超时），不论成败都删本机那一份；
    保存的是 API Key 时只删本机——Key 本身仍有效，要作废请到网站账户页停用或删除。
    返回 {removed, kind, revoked, message}。"""
    client = Client(base_url=base_url, _transport=_transport)
    old = credentials.remove(client.base_url)
    if old is None:
        msg = t('client.logout_none', client.base_url)
        info = {'removed': False, 'kind': None, 'revoked': None}
    elif old.kind == 'oauth':
        ok = revoke(client, old)
        msg = t('client.logout_oauth', t('client.logout_revoked' if ok else 'client.logout_revoke_failed'))
        info = {'removed': True, 'kind': 'oauth', 'revoked': ok}
    else:
        msg = t('client.logout_api_key')
        info = {'removed': True, 'kind': 'api_key', 'revoked': None}
    if os.environ.get(credentials.ENV_KEY, '').strip():
        msg += t('client.logout_env_note', credentials.ENV_KEY)
    info['message'] = msg
    return info


def whoami(*, base_url=None, _transport=None):
    """当前身份，见 Client.whoami()。"""
    return Client(base_url=base_url, _transport=_transport).whoami()


def submit(circuits, target, shots=1024, compiler='qiskit', name=None, parameters=None):
    """交一条或一组线路，返回任务组句柄。参数见 Client.submit()；身份与平台地址按默认规则取。"""
    return Client().submit(circuits, target, shots=shots, compiler=compiler, name=name, parameters=parameters)


def sweep(template, parameters, points, target, shots=1024, compiler='qiskit', name=None):
    """扫参：平台按参数点代入模板，见 Client.sweep()。"""
    return Client().sweep(template, parameters, points, target, shots=shots, compiler=compiler, name=name)


def open_job(target, template=None, parameters=None, shots=1024, compiler='qiskit', name=None):
    """开一个迭代式任务组，见 Client.open_job()。"""
    return Client().open_job(target, template=template, parameters=parameters, shots=shots, compiler=compiler,
                             name=name)


def device(name):
    """一台设备的详情与当前校准，见 Client.device()。"""
    return Client().device(name)


def calibration(calibration_id):
    """按标识取一份校准数据，见 Client.calibration()。"""
    return Client().calibration(calibration_id)


def stats(days=30):
    """本人的用量统计与这个配额日的额度，见 Client.stats()。"""
    return Client().stats(days)


def job(job_id):
    """按任务组号接回，见 Client.job()。"""
    return Client().job(job_id)


def devices():
    """能交到哪些目标，见 Client.devices()。"""
    return Client().devices()
