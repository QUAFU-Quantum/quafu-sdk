# -*- coding: utf-8 -*-
"""异常层次与平台错误体的映射表。

包抛出的一切都是 QuafuError 的子类（Ctrl-C 的 KeyboardInterrupt 除外，照常穿透）。
平台的错误体都带 error（人话）与 code（机器码）；任务类另带 error_category / detail / vars。
同一个 HTTP 码在不同端点含义不同（/result 的 422 是任务失败，提交的 422 是预检没过），
所以映射键是 (端点类别, HTTP 码, code)。三个字段一律 .get，认不出的形状落 ProtocolError。"""
import json

from ._i18n import t


class QuafuError(Exception):
    """包内所有异常的基类。status / code / body 是平台给的原样信息，没有就是 None。"""

    def __init__(self, message='', status=None, code=None, body=None):
        super().__init__(message)
        self.status, self.code, self.body = status, code, body


class AuthError(QuafuError):
    """凭证不对或不够：key 无效或已吊销、这个操作只能在网站登录后做。不会自动删本地凭证文件。"""


class NotLoggedIn(AuthError):
    """哪里都没有凭证（参数、环境变量 QUAFU_API_KEY、本机保存的登录态），而当前进程不能交互，没法发起网页登录。"""


class LoginFailed(AuthError):
    """网页登录没有完成：在网页上拒绝了授权、等待超时、授权码无效或对不上这次登录。"""


class LoginExpired(AuthError):
    """本机保存的网页登录已过期（网页登录从授权起 90 天有效，不续期）。expires_at 是到期时刻（ISO 8601）。"""

    def __init__(self, message='', expires_at=None, **kw):
        super().__init__(message, **kw)
        self.expires_at = expires_at


class LoginRevoked(AuthError):
    """平台不认这份凭证：网页登录已在网站上撤销，或 API Key 已停用、已删除。"""


class CredentialsError(AuthError):
    """本地凭证文件读写失败，或凭证的形状不对（不发请求就能看出来的那种）。"""


class BadRequest(QuafuError):
    """请求本身不合法：字段缺失、类型不对、参数取值不认识。"""


class _Categorized(QuafuError):
    """带平台错误分类的异常：category（点分键，如 precheck.shotsOutOfRange）、detail、vars 原样带回。"""

    def __init__(self, message='', category=None, detail=None, vars=None, **kw):
        super().__init__(message, **kw)
        self.category, self.detail, self.vars = category, detail, dict(vars or {})


class PrecheckError(_Categorized):
    """平台预检没通过：线路、shots、模板或权限不满足目标后端的要求。任务组里是哪一条看 vars['task_index']。
    超出目标资源上限的，vars['limits_url'] 是查上限的地址；SDK 在提交前按 limits 本地拦下的，vars['local'] 为 True。"""


class DeviceUnavailable(_Categorized):
    """目标设备暂不可用（校准中、离线、实时状态未知）。平台不会悄悄换到别的设备。"""


class QuotaError(QuafuError):
    """额度用完或超上限：每日硬上限（runtime.quotaExhausted）、任务组内任务数（job_too_large）、请求体大小
    （payload_too_large）、同时开着的迭代任务组数（too_many_open_jobs）。SDK 不会自动拆分请求；上限在 vars。

    每天的额度分两档：超出正常额度（vars['limit']）的任务照收照跑，只是排在额度内的任务之后，不抛错；
    交到硬上限（vars['hard_limit']）才抛本异常。这时 vars 还有 used（这个配额日已交）、remaining（正常额度内剩余）、
    requested（本次要交几条）、resets_at（下次重置的时刻，北京时间 23:00）、wait_s（到重置的秒数；本次条数本身
    超过硬上限时为 None，要拆小再交）。
    retry_after 来自 Retry-After 头或体里的 retry_after（秒），没给是 None；resets_at 同 vars['resets_at']，没给是 None。"""

    def __init__(self, message='', retry_after=None, vars=None, **kw):
        super().__init__(message, **kw)
        self.retry_after = retry_after
        self.vars = dict(vars or {})
        self.resets_at = self.vars.get('resets_at')


class _TaskError(QuafuError):
    def __init__(self, message='', task_id=None, **kw):
        super().__init__(message, **kw)
        self.task_id = task_id


class TaskFailed(_TaskError):
    """任务以失败收尾。category / detail 是平台给的失败分类与原因；error_stage 是在哪一环失败
    （precheck / dispatch / hardware / collect / dispatcher），retryable 是同样的输入再提交有没有意义；
    vars 是该失败分类的参数原样（如 runtime.simTimeout 的 limit_s、runtime.simResourceExceeded 的 limit_mb），
    平台没给为 None。"""

    def __init__(self, message='', task_id=None, category=None, detail=None, error_stage=None, retryable=None,
                 vars=None, **kw):
        super().__init__(message, task_id=task_id, **kw)
        self.category, self.detail = category, detail
        self.error_stage, self.retryable = error_stage, retryable
        self.vars = vars


class TaskCancelled(_TaskError):
    """任务已被取消。"""


class NotCancellable(_TaskError):
    """任务已无法取消（not_cancellable）：已在取回结果（collecting），或已完成 / 已失败。不是网络错误，也不会重试。
    stage 是平台给的当前阶段（collecting / finished / failed，没给为 None）。
    已取消的任务再取消不会到这里：那是幂等的，照常返回 Cancelled。"""

    def __init__(self, message='', task_id=None, stage=None, **kw):
        super().__init__(message, task_id=task_id, **kw)
        self.stage = stage


class TaskNotFound(_TaskError):
    """任务不存在，或不属于当前账号（换了 key 就看不到原账号的任务）。"""


class NotReady(_TaskError):
    """任务还没到终态。task_status 是当时的状态词；Task.wait() 内部不会抛它。"""

    def __init__(self, message='', task_id=None, task_status=None, **kw):
        super().__init__(message, task_id=task_id, **kw)
        self.task_status = task_status


class Timeout(_TaskError):
    """等到了调用方给的时限。任务组仍在平台上，再调一次 result() / wait()，或 quafu.job(任务组号) 接回后续等。
    不叫 TimeoutError：3.10 起 socket.timeout 就是内置 TimeoutError，会混。"""

    def __init__(self, message='', task_id=None, job_id=None, **kw):
        super().__init__(message, task_id=task_id, **kw)
        self.job_id = job_id


class _JobError(QuafuError):
    def __init__(self, message='', job_id=None, **kw):
        super().__init__(message, **kw)
        self.job_id = job_id


class JobFailed(_JobError):
    """任务组里的线路没有跑成。category 是失败分类（点分键），error_stage 是在哪一环失败
    （precheck / dispatch / hardware / collect / dispatcher），retryable 是原样重交有没有意义；
    task_id 是失败的那一条，vars 是该失败分类的参数原样。"""

    def __init__(self, message='', job_id=None, task_id=None, category=None, detail=None, error_stage=None,
                 retryable=None, vars=None, **kw):
        super().__init__(message, job_id=job_id, **kw)
        self.task_id, self.category, self.detail = task_id, category, detail
        self.error_stage, self.retryable, self.vars = error_stage, retryable, vars


class JobCancelled(_JobError):
    """任务组（或要取结果的那一条）已被取消，没有结果。"""


class JobClosed(_JobError):
    """不能这样往任务组里追加：已关闭（job_closed）、不是迭代式（job_not_iterative）、没有模板却按参数点追加
    （job_has_no_template）。code 区分三者。"""


class JobNotFound(_JobError):
    """任务组不存在，或不属于当前账号。"""


class ServerUnavailable(QuafuError):
    """连不上平台、它没应答或回 5xx，或它的契约版本还不支持你要用的功能。sent 标明请求是否可能已经发出。"""

    def __init__(self, message='', sent=False, **kw):
        super().__init__(message, **kw)
        self.sent = sent


class SubmitUncertain(ServerUnavailable):
    """提交请求可能已到达平台但没收到回应。为免重复提交没有自动重试，请用 c.jobs() 自己认。"""
    maybe_submitted = True


class ProtocolError(QuafuError):
    """平台的响应认不出：不是 JSON、形状不对、跳转、端点不存在。"""


class ClientOutdated(QuafuError):
    """平台要求更新的 SDK：pip install -U quafu-sdk。"""


def snippet(raw, limit=200):
    """原始响应的前 limit 个字符（压成一行），给认不出的响应进异常文本。"""
    text = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else str(raw or '')
    return ' '.join(text.split())[:limit]


def _describe(body):
    """错误体里给人看的那句：error，其次 detail（列表转 JSON），再次 vars。"""
    for key in ('error', 'detail'):
        v = body.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, list) and v:
            return json.dumps(v, ensure_ascii=False)
    v = body.get('vars')
    return json.dumps(v, ensure_ascii=False) if v else ''


def _retry_after(headers, body):
    v = (headers or {}).get('retry-after')
    if v is None:
        v = body.get('retry_after')
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return None


# 文案都在 _messages.py，这里只记机器码 → 消息键；取文案在抛错那一刻，跟着当时的界面语言
_AUTH_TEXT = {
    'invalid_api_key': 'errors.auth.invalid_api_key',
    'session_required': 'errors.auth.session_required',
    'unauthenticated': 'errors.auth.unauthenticated',
}

_JOB_CONFLICT_TEXT = {
    'job_closed': 'errors.job.closed',
    'job_not_iterative': 'errors.job.not_iterative',
    'job_has_no_template': 'errors.job.no_template',
}

_NOT_CANCELLABLE_TEXT = {
    'collecting': 'errors.not_cancellable.collecting',
    'finished': 'errors.not_cancellable.finished',
    'failed': 'errors.not_cancellable.failed',
}

JIUDING_SIM_SUFFIX = '-sim-jiuding'
QUOTA_CODES = ('job_too_large', 'payload_too_large', 'too_many_open_jobs', 'too_many_jobs')


_FAILURE_LIMIT_TEXT = {
    'runtime.simTimeout': ('limit_s', 'errors.limit.sim_timeout'),
    'runtime.simResourceExceeded': ('limit_mb', 'errors.limit.sim_memory'),
}


def failure_note(category, vars_):
    """失败分类带的参数（契约 D134 的 error.vars）→ 文案尾巴；平台没给参数时为空串，文案照旧。"""
    key, msg = _FAILURE_LIMIT_TEXT.get(category, (None, None))
    if key and isinstance(vars_, dict) and vars_.get(key) is not None:
        return t('errors.paren', t(msg, vars_[key]))
    return ''


def _wait_text(seconds):
    if seconds < 60:
        return t('errors.quota.wait_s', max(1, seconds))
    if seconds < 3600:
        return t('errors.quota.wait_min', max(1, -(-seconds // 60)))
    return t('errors.quota.wait_h', '%.1f' % (seconds / 3600.0))


def daily_cap_text(vars_, retry_after=None):
    """碰每日硬上限的 429 → 文案（平台原文只有中文，按 vars 用界面语言重写）。超出正常额度本身不报错，只降级排队。"""
    hard = vars_.get('hard_limit')
    if isinstance(hard, int) and hard <= 0:
        return t('errors.quota.paused')
    wait = vars_.get('wait_s', retry_after)
    if wait is None and 'wait_s' in vars_:
        return t('errors.quota.too_many_at_once', vars_.get('requested', '?'), hard)
    reset = vars_.get('resets_at')
    reset = reset[11:16] if isinstance(reset, str) and len(reset) >= 16 else '23:00'
    msg = t('errors.quota.daily_cap', vars_.get('used', '?'), hard, vars_.get('limit', '?'), reset)
    if isinstance(wait, (int, float)) and wait > 0:
        return msg + t('errors.quota.reset_in', _wait_text(int(wait)))
    return msg + t('errors.quota.end')


def from_response(endpoint, status, body, headers=None, raw=b'', task_id=None, who='', job_id=None):
    """把一个非 2xx 响应翻成异常对象（调用方 raise）。

    endpoint：'submit'（提交）/ 'result'（取结果）/ 'task'（其他按任务号的端点）/ 'job'（任务组端点）/ 'other'。
    body：解析好的 JSON，不是 dict 就当认不出；raw：原始字节，认不出时截前 200 字进异常文本。
    who：当前 key 的掩码，鉴权与 TaskNotFound 的文本要它（不含 key 本身）。"""
    if not isinstance(body, dict):
        if status == 413:           # 反向代理先挡下的超大请求体，体是它的 HTML 页
            return QuotaError(t('errors.payload_413', t('errors.too_large_hint')), status=status,
                              code='payload_too_large')
        if status >= 500:
            return ServerUnavailable(t('errors.unavailable', status, snippet(raw)),
                                      status=status)
        return ProtocolError(t('errors.unrecognized', status, snippet(raw)), status=status)
    code = body.get('code') or body.get('error_category') or ''
    code = code if isinstance(code, str) else ''
    category = body.get('error_category') or (code if '.' in code else None)
    text = _describe(body)
    kw = dict(status=status, code=code or None, body=body)
    cat = dict(category=category, detail=body.get('detail'), vars=body.get('vars'))

    if status == 401:
        tmpl = _AUTH_TEXT.get(code)
        msg = t(tmpl, who) if tmpl else t('errors.auth.generic', who, text)
        if code == 'session_required':
            return AuthError(msg, **kw)
        return LoginRevoked(msg, **kw)
    if status == 426 or code == 'client_outdated':
        return ClientOutdated(t('errors.outdated', text), **kw)
    if endpoint == 'result' and status == 409:
        st = body.get('status')
        if code == 'task_cancelled' or st == 'Cancelled':
            return TaskCancelled(t('errors.task_cancelled', task_id), task_id=task_id, **kw)
        return NotReady(t('errors.not_ready', task_id, st or t('errors.not_terminal')), task_id=task_id,
                        task_status=st, **kw)
    if endpoint == 'result' and status == 422:
        vars_ = body.get('vars') if isinstance(body.get('vars'), dict) else None
        return TaskFailed(t('errors.task_failed', task_id, category, text, failure_note(category, vars_)),
                          task_id=task_id, category=category, detail=body.get('detail'), vars=vars_, **kw)
    if status == 404:
        if code == 'not_found' and endpoint in ('task', 'result'):
            return TaskNotFound(t('errors.task_not_found', task_id, who), task_id=task_id, **kw)
        if code == 'not_found' and endpoint == 'job':
            return JobNotFound(t('errors.job_not_found', job_id, who), job_id=job_id, **kw)
        if code:
            return BadRequest('%s [%s]' % (text or t('errors.no_such_object'), code), **kw)
        return ProtocolError(t('errors.no_endpoint'), **kw)
    if status == 409 and code == 'not_cancellable':
        stage = body['vars'].get('stage') if isinstance(body.get('vars'), dict) else None
        why = t(_NOT_CANCELLABLE_TEXT.get(stage, 'errors.not_cancellable.other'))
        return NotCancellable(t('errors.not_cancellable', task_id, why, text), task_id=task_id, stage=stage, **kw)
    if status == 409 and code in _JOB_CONFLICT_TEXT:
        return JobClosed(t(_JOB_CONFLICT_TEXT[code], job_id), job_id=job_id, **kw)
    if status in (413, 429) or code in QUOTA_CODES:
        ra = _retry_after(headers, body)
        vars_ = body.get('vars') or {}
        tail = ''
        if code in ('job_too_large', 'payload_too_large'):
            tail = t('errors.quota.limit_tail', vars_.get('max', t('errors.quota.see_docs')), t('errors.too_large_hint'))
        elif code == 'too_many_jobs':
            tail = t('errors.quota.too_many_jobs_tail', vars_.get('used', '?'), vars_.get('limit', '?'))
        elif isinstance(vars_, dict) and 'hard_limit' in vars_:
            text, tail = daily_cap_text(vars_, ra), ''
        elif ra:
            tail = t('errors.quota.retry_tail', ra)
        return QuotaError(t('errors.quota', code, text, tail), retry_after=ra, vars=vars_, **kw)
    if code.startswith('precheck.'):
        vars_ = body.get('vars') if isinstance(body.get('vars'), dict) else {}
        reason = vars_.get('reason')
        notes = [t('errors.precheck.reason', reason)] if reason else []
        if reason == 'unmeasured_clbit':
            notes.append(t('errors.precheck.unmeasured',
                           ', '.join(map(str, vars_.get('cbits') or [])) or t('errors.precheck.see_cbits')))
        elif reason == 'measurement_order':
            notes.append(t('errors.precheck.measurement_order'))
        if code == 'precheck.simTooLarge':
            n = vars_.get('n_qubits', vars_.get('n'))
            limit = vars_.get('limit_qubits', vars_.get('limit'))
            if vars_.get('estimate_mb') is not None:
                notes.append(t('errors.precheck.sim_estimate', n, vars_.get('method', '?'), vars_['estimate_mb'],
                               vars_.get('limit_mb', '?')))
            elif n is not None and limit is not None:
                # 比特上限两支：理想模拟按声明宽度、带噪模拟按活跃比特数，所以只说「比特数」。
                # 契约 v1.20 D129 定为 {n_qubits, limit_qubits}；任务分发器改完之前可能还是旧的 {n, limit}
                notes.append(t('errors.precheck.qubits', n, limit))
        if isinstance(vars_.get('limits_url'), str):
            notes.append(t('errors.precheck.limits_url', vars_['limits_url']))
        if vars_.get('missing'):
            notes.append(t('errors.precheck.missing_params'))
        if vars_.get('undeclared'):
            notes.append(t('errors.precheck.undeclared', ', '.join(map(str, vars_['undeclared']))))
        tail = t('errors.paren', t('errors.precheck.sep').join(notes)) if notes else ''
        return PrecheckError(t('errors.precheck', code, text, tail), **dict(kw, **cat))
    if status == 403:
        return AuthError(t('errors.forbidden', code, text), **kw)
    if code == 'runtime.deviceUnavailable':
        vars_ = body.get('vars') if isinstance(body.get('vars'), dict) else {}
        device = vars_.get('device')
        if isinstance(device, str) and device.endswith(JIUDING_SIM_SUFFIX):
            # 九鼎模拟此刻没有可用的模拟器：平台原文只有中文，按界面语言重写
            text = t('errors.device_unavailable.jiuding_sim', device)
        return DeviceUnavailable(t('errors.device_unavailable', text), **dict(kw, **cat))
    if status in (400, 409, 422):
        vars_ = body.get('vars') if isinstance(body.get('vars'), dict) else {}
        field = t('errors.field', vars_['field']) if vars_.get('field') else ''
        return BadRequest(t('errors.bad_request', code, text, field), **kw)
    if status >= 500:
        return ServerUnavailable(t('errors.server', status, code, text), **kw)
    return ProtocolError(t('errors.unrecognized', status, snippet(raw)), **kw)
