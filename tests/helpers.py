# -*- coding: utf-8 -*-
"""测试共用的假件：可编排的传输层、可拨的时钟、常量。响应形状照接口契约 06 号。"""
import json
from urllib.parse import parse_qsl, urlsplit

from quafu import credentials
from quafu.errors import ServerUnavailable
from quafu.transport import Response

# 测试里起的子进程一律带这个超时：现有这类用例在 Mac 上都不到 1 秒，Windows 冷启动解释器慢几倍，取 60 秒足够宽；
# 卡住（比如子进程误以为能交互、进了网页登录等待）就报失败，不让整套测试挂住
SUBPROCESS_TIMEOUT = 60

BASE = 'https://quafu.test'
API = BASE + '/api/v1'
KEY = credentials.TOKEN_PREFIX + 'a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6'
KEY2 = credentials.TOKEN_PREFIX + 'Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4'
TOKEN = credentials.TOKEN_PREFIX + 'T0k3nT0k3nT0k3nT0k3nT0k3nT0k3nT0'

USER = {'id': 7, 'email': 'a@b.test', 'name': '甲', 'org': '机构', 'is_admin': False, 'public_id': 'u7f3a9c2b'}
ME = (200, {'user': USER, 'auth_kind': 'api_key', 'api_key': {'id': 1, 'key_prefix': KEY[:11]}})
TOKEN_OK = (200, {'access_token': TOKEN, 'token_type': 'Bearer', 'expires_in': 90 * 86400, 'scope': 'jobs'})
UNAUTHORIZED = (401, {'error': '无效的凭证', 'code': 'invalid_api_key'})

JID = 'u7f3a9c2b-261008-153000'
BELL = ('OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\n'
        'measure q[0] -> c[0];\nmeasure q[1] -> c[1];\n')


def accepted(n=1, mode='single', job_id=JID):
    return (202, {'job_id': job_id, 'mode': mode, 'status': 'Queued', 'open': False,
                  'task_ids': ['%s-%d' % (job_id, i) for i in range(n)], 'n_tasks': n})


def job_status(status='Queued', total=1, finished=0, failed=0, cancelled=0, running=0, job_id=JID):
    queued = total - finished - failed - cancelled - running
    return (200, {'job_id': job_id, 'mode': 'single' if total == 1 else 'collection', 'status': status,
                  'open': False, 'counts': {'total': total, 'queued': queued, 'running': running,
                                            'finished': finished, 'failed': failed, 'cancelled': cancelled},
                  'finished_at': None, 'cancel_requested': False})


def task_detail(seq=0, status='Finished', counts=None, error=None, job_id=JID, kind='sim', target='sim', chip=None):
    """带 counts 与 executed 的任务详情（GET /jobs/{jid}/tasks/{seq}?include=counts,executed）。"""
    counts = {'00': 60, '11': 40} if counts is None and status == 'Finished' else counts
    result = None
    if status == 'Finished':
        result = {'bit_order': 'c0_rightmost', 'n_clbits': 2, 'classical_registers': [{'name': 'c', 'size': 2,
                  'offset': 0}], 'counts': counts, 'counts_origin': 'simulator_counts',
                  'shots_returned': sum(counts.values()), 'n_outcomes': len(counts), 'top_outcomes': []}
    return (200, {
        'schema_version': '1', 'included': ['counts', 'executed'], 'task_id': '%s-%d' % (job_id, seq),
        'status': status, 'kind': kind, 'target': target, 'chip': chip,
        'job': {'job_id': job_id, 'mode': 'single', 'seq': seq, 'n_tasks': 1},
        'circuit': {'submitted': {'format': 'openqasm2', 'fingerprint': 'fp', 'n_clbits': 2},
                    'executed': {'format': 'openqasm2', 'text': BELL if status == 'Finished' else None,
                                 'same_as_submitted': True, 'executed_source': 'gateway'},
                    'measurements': [{'cbit': 0, 'physical_qubit': 0, 'virtual_qubit': 0},
                                     {'cbit': 1, 'physical_qubit': 1, 'virtual_qubit': 1}]},
        'execution': {'shots_requested': 100, 'shots_returned': 100 if status == 'Finished' else None,
                      'compiler': {'name': 'qiskit', 'version': '2.1.0', 'optimization_level': 2, 'seed': None}},
        'calibration': {'id': None},
        'result': result,
        'progress': {'stage': status.lower(), 'stage_at': 't', 'blocker': None, 'detail': None},
        'error': error if status == 'Failed' else {'category': None, 'stage': None, 'detail': None,
                                                   'retryable': None, 'vars': None}})


class Fail(object):
    """编排进 FakeTransport 的一次网络失败；sent 为请求是否可能已发出。"""

    def __init__(self, sent=True):
        self.sent = sent


class FakeTransport(object):
    """按脚本回应的传输层。route(method, path, *items)：每次请求取队首，只剩一个时一直回它。
    path 是程序端入口 /api/v1 之后的部分（含查询串；任何主机都一样，url 里有完整地址）。item 是 (status, body[, headers])、Fail、
    或 callable(req) → 前两者之一。没登记的路径回 404 {'detail': 'Not Found'}（FastAPI 的默认形状）。
    req 里 body 是解析好的 JSON，form 是解析好的表单。"""

    def __init__(self):
        self.routes, self.calls = {}, []

    def route(self, method, path, *items):
        self.routes[(method, path)] = list(items)
        return self

    def posts(self, path=None):
        return [c for c in self.calls if c['method'] == 'POST' and (path is None or c['path'] == path)]

    def paths(self):
        return [c['path'] for c in self.calls]

    def request(self, method, url, headers, body, connect_timeout, read_timeout):
        u = urlsplit(url)
        path = u.path[len('/api/v1'):] if u.path.startswith('/api/v1/') else u.path
        path += '?' + u.query if u.query else ''
        ctype = headers.get('Content-Type', '')
        req = dict(method=method, url=url, path=path, headers=dict(headers),
                   body=json.loads(body) if body and ctype == 'application/json' else None,
                   form=dict(parse_qsl(body.decode('ascii'))) if body and 'urlencoded' in ctype else None,
                   connect_timeout=connect_timeout, read_timeout=read_timeout)
        self.calls.append(req)
        q = self.routes.get((method, path))
        item = (q.pop(0) if len(q) > 1 else q[0]) if q else (404, {'detail': 'Not Found'})
        if callable(item):
            item = item(req)
        if isinstance(item, Fail):
            raise ServerUnavailable('模拟网络失败', sent=item.sent)
        status_, payload = item[0], item[1]
        hdrs = item[2] if len(item) > 2 else {}
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
        return Response(status_, {k.lower(): v for k, v in hdrs.items()}, raw)


class FakeClock(object):
    """替换模块里的 time：sleep 只拨表不真睡；interrupt_after=n 时第 n 次 sleep 抛 Ctrl-C。"""

    def __init__(self):
        self.t = 1000.0
        self.sleeps = []
        self.interrupt_after = None

    def monotonic(self):
        return self.t

    time = monotonic

    def sleep(self, s):
        self.sleeps.append(s)
        if self.interrupt_after is not None and len(self.sleeps) >= self.interrupt_after:
            raise KeyboardInterrupt
        self.t += s


def dispatcher_error(category, detail='', **vars_):
    """任务分发器任务类错误体的形状（与 quafu_dispatcher.errors.payload 同形，不 import 任务分发器）。"""
    return {'error': detail, 'code': category, 'error_category': category, 'detail': detail, 'vars': vars_}
