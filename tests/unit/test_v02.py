# -*- coding: utf-8 -*-
"""v0.2 迁入的功能（不经网络）：扫参、迭代式任务组、列式结果表、结果工具、设备与校准、统计；
以及请求层的重试与时限（自旧包 quafu-portal 的同名用例迁来）。端到端在 contract/test_core_contract.py。"""
import uuid

import pytest

import quafu
from quafu.errors import BadRequest, JobClosed, LoginRevoked, ProtocolError, QuotaError, ServerUnavailable, Timeout

from ..helpers import BELL, JID, ME, Fail, accepted, dispatcher_error, job_status, task_detail

TEMPLATE = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nrx({{theta}}) q[0];\nmeasure q[0] -> c[0];\n'


@pytest.fixture
def c(make_client):
    return make_client()


# ── G1 扫参 ─────────────────────────────────────────────────────────

def test_sweep_body(fake, c):
    fake.route('POST', '/jobs', accepted(3, 'sweep'))
    job = c.sweep(TEMPLATE, [('theta', 'rad', 'θ')], [0.0, 0.5, 1.0], 'sim', shots=128, name='RX 扫描')
    body = fake.posts('/jobs')[0]['body']
    assert body['mode'] == 'sweep' and body['template_qasm'] == TEMPLATE and body['target'] == 'sim'
    assert body['parameters'] == [{'name': 'theta', 'unit': 'rad', 'symbol': 'θ'}]
    assert body['points'] == [[0.0], [0.5], [1.0]] and body['shots'] == 128 and body['name'] == 'RX 扫描'
    assert body['circuit_level'] == 'logical' and uuid.UUID(body['client_ref']) and job.n_tasks == 3


def test_sweep_accepts_numpy_points(fake, c):
    np = pytest.importorskip('numpy')
    fake.route('POST', '/jobs', accepted(2, 'sweep'))
    c.sweep(TEMPLATE, [{'name': 'theta', 'unit': 'rad'}], np.array([[0.1], [0.2]]), 'sim')
    assert fake.posts('/jobs')[0]['body']['points'] == [[0.1], [0.2]]


@pytest.mark.parametrize('kw', [dict(parameters=['theta']),                    # 缺 unit
                                dict(points=[[float('nan')]]),
                                dict(template='')])
def test_sweep_rejects_bad_input_before_sending(fake, c, kw):
    args = dict(template=TEMPLATE, parameters=[('theta', 'rad')], points=[[0.0]], target='sim')
    args.update(kw)
    with pytest.raises((TypeError, ValueError)):
        c.sweep(**args)
    assert fake.calls == []


def test_module_level_sweep(fake, monkeypatch):
    monkeypatch.setenv('QUAFU_API_KEY', 'qf_' + 'a' * 32)
    fake.route('POST', '/jobs', accepted(1, 'sweep'))
    assert quafu.sweep(TEMPLATE, [('theta', 'rad')], [[0.0]], 'sim').id == JID


def test_collection_with_parameter_values(fake, c):
    fake.route('POST', '/jobs', accepted(2, 'collection'))
    c.submit([{'qasm': BELL, 'parameter_values': {'t': 0.5}, 'name': 'a'}, {'qasm': BELL, 'parameter_values': {'t': 1}}],
             'sim', parameters=[('t', 'rad')])
    body = fake.posts('/jobs')[0]['body']
    assert body['parameters'] == [{'name': 't', 'unit': 'rad'}]
    assert body['circuits'][0] == {'qasm': BELL, 'parameter_values': {'t': 0.5}, 'name': 'a'}
    assert body['circuits'][1]['parameter_values'] == {'t': 1.0}
    with pytest.raises(TypeError):
        c.submit([{'qasm': BELL, 'label': 'x'}], 'sim')                         # 不认识的字段


# ── G2 迭代式任务组 ─────────────────────────────────────────────────

def test_open_append_wait_close(fake, c, clock):
    fake.route('POST', '/jobs', (202, {'job_id': JID, 'mode': 'iterative', 'status': 'Queued', 'open': True,
                                       'task_ids': [], 'n_tasks': 0}))
    job = c.open_job('sim', template=TEMPLATE, parameters=[('theta', 'rad')], shots=64, name='VQE')
    body = fake.posts('/jobs')[0]['body']
    assert body['mode'] == 'iterative' and body['template_qasm'] == TEMPLATE and 'points' not in body
    assert job.open is True and job.n_tasks == 0

    fake.route('POST', '/jobs/%s/tasks' % JID, (202, {'task_ids': [JID + '-0', JID + '-1']}))
    assert job.append(points=[[0.1], [0.2]], iteration=0) == [JID + '-0', JID + '-1']
    add = fake.posts('/jobs/%s/tasks' % JID)[0]['body']
    assert add['points'] == [[0.1], [0.2]] and add['iteration'] == 0 and uuid.UUID(add['client_ref'])
    assert job.n_tasks == 2

    open_status = dict(job_status('Running', total=2, running=1)[1], open=True)
    open_idle = dict(job_status('PartiallyFinished', total=2, finished=2)[1], open=True)
    fake.route('GET', '/jobs/%s/status' % JID, (200, open_status), (200, open_idle))
    assert job.wait() == 'PartiallyFinished' and clock.sleeps == [1.0]     # 开着的任务组：没有在跑的就返回

    fake.route('POST', '/jobs/%s/tasks' % JID, (202, {'task_ids': [JID + '-2']}))
    job.append(circuits=[BELL], iteration=1, evaluation_index=3)
    add = fake.posts('/jobs/%s/tasks' % JID)[1]['body']
    assert add['circuits'] == [{'qasm': BELL, 'iteration': 1, 'evaluation_index': 3}] and job.n_tasks == 3

    fake.route('POST', '/jobs/%s/close' % JID, (200, {'job_id': JID, 'open': False, 'status': 'Finished'}))
    job.close()
    assert job.open is False


def test_append_rules(fake, c):
    job = quafu.Job(c, JID, n_tasks=0, open=True)
    with pytest.raises(TypeError):
        job.append()
    with pytest.raises(TypeError):
        job.append(circuits=[BELL], points=[[0.0]])
    with pytest.raises(ValueError):
        job.append(points=[[0.0]], iteration=-1)
    assert fake.calls == []
    fake.route('POST', '/jobs/%s/tasks' % JID, (409, {'error': '已关闭', 'code': 'job_closed'}))
    with pytest.raises(JobClosed):
        job.append(points=[[0.0]])


def test_append_replays_with_the_same_key_after_a_lost_response(fake, c, clock):
    job = quafu.Job(c, JID, n_tasks=0, open=True)
    fake.route('POST', '/jobs/%s/tasks' % JID, Fail(sent=True), (202, {'task_ids': [JID + '-0']}))
    job.append(points=[[0.0]])
    refs = {p['body']['client_ref'] for p in fake.posts('/jobs/%s/tasks' % JID)}
    assert len(fake.posts('/jobs/%s/tasks' % JID)) == 2 and len(refs) == 1


def test_results_of_an_open_job_only_fetch_new_or_unfinished_tasks(fake, c, clock):
    job = quafu.Job(c, JID, n_tasks=2, open=True)
    idle = dict(job_status('PartiallyFinished', total=2, finished=2)[1], open=True)
    fake.route('GET', '/jobs/%s/status' % JID, (200, idle))
    for i in range(3):
        fake.route('GET', '/jobs/%s/tasks/%d?include=counts,executed' % (JID, i), task_detail(i))
    assert len(job.results()) == 2
    idle3 = dict(job_status('PartiallyFinished', total=3, finished=3)[1], open=True)
    fake.route('GET', '/jobs/%s/status' % JID, (200, idle3))
    assert len(job.results()) == 3
    details = [p for p in fake.paths() if '/tasks/' in p]
    assert details == ['/jobs/%s/tasks/%d?include=counts,executed' % (JID, i) for i in (0, 1, 2)]


# ── 列式结果表 ──────────────────────────────────────────────────────

def _page(seqs, total):
    return (200, {'job_id': JID, 'bit_order': 'c0_rightmost', 'parameters': [{'name': 'theta', 'unit': 'rad'}],
                  'seq': seqs, 'task_ids': ['%s-%d' % (JID, s) for s in seqs], 'points': [[s / 10] for s in seqs],
                  'status': ['Finished'] * len(seqs), 'counts': [{'0': 1}] * len(seqs),
                  'shots_returned': [1] * len(seqs), 'n_clbits': [1] * len(seqs), 'total': total})


def test_table_pages_through_and_lines_up_by_seq(fake, c, clock):
    from quafu.tables import RESULT_PAGE
    job = quafu.Job(c, JID, n_tasks=3)
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Finished', total=3, finished=3))
    fake.route('GET', '/jobs/%s/results?offset=0&limit=%d&fields=counts' % (JID, RESULT_PAGE), _page([0, 1], 3))
    fake.route('GET', '/jobs/%s/results?offset=2&limit=%d&fields=counts' % (JID, RESULT_PAGE), _page([2], 3))
    t = job.table()
    assert isinstance(t, quafu.ResultTable) and len(t) == 3
    assert t.column('theta') == [0.0, 0.1, 0.2] and t.complete and t.counts == [{'0': 1}] * 3


def test_table_without_wait_is_a_snapshot(fake, c):
    from quafu.tables import RESULT_PAGE
    job = quafu.Job(c, JID, n_tasks=1, open=True)
    fake.route('GET', '/jobs/%s/results?offset=0&limit=%d&fields=counts' % (JID, RESULT_PAGE), _page([0], 1))
    job.table(wait=False)
    assert not any(p.endswith('/status') for p in fake.paths())


# ── G6 结果工具 ─────────────────────────────────────────────────────

def test_result_bit_tools_and_parameter_values():
    d = task_detail(0, counts={'01': 75, '11': 25})[1]
    d['job'] = dict(d['job'], parameter_values={'theta': 0.5}, iteration=2, evaluation_index=1)
    r = quafu.Result(d)
    assert r.reorder('c0_leftmost') == {'10': 75, '11': 25}
    assert r.reorder([0]) == {'1': 100}
    assert r.expectation_z([0]) == -1.0 and r.expectation_z([1]) == 0.5
    assert (r.parameter_values, r.iteration, r.evaluation_index, r.seq) == ({'theta': 0.5}, 2, 1, 0)
    failed = quafu.Result(task_detail(0, 'Failed', error={'category': 'x'})[1])
    assert failed.reorder([0]) is None and failed.expectation_z([0]) is None
    nobits = dict(task_detail(0)[1])
    nobits['result'] = dict(nobits['result'], bit_order=None)
    with pytest.raises(ValueError):
        quafu.Result(nobits).reorder([0])


def test_bit_helpers_are_exported():
    assert quafu.reorder_counts({'01': 1}, 'c0_leftmost', 'c0_rightmost') == {'10': 1}
    assert quafu.probabilities({'0': 1, '1': 3}) == {'0': 0.25, '1': 0.75}


# ── G4 设备与校准、G5 统计 ──────────────────────────────────────────

def test_device_and_calibration_are_public(fake, monkeypatch):
    fake.route('GET', '/devices/Dongling', (200, {'name': 'Dongling', 'status': 'online', 'n_qubits': 84,
                                                  'queue': 0, 'calibration_id': 'cal1'}))
    fake.route('GET', '/devices/Dongling/calibration', (200, {'id': 'cal1', 'chip': 'Dongling',
                                                              'qubits': [{'index': 5, 't1_us': 30.0}],
                                                              'couplers': [{'qubits': [5, 6], 'cz_fidelity': 0.98}],
                                                              'measured': {'qubits': [{'index': 5,
                                                                                       'readout_status': 'ok'}]}}))
    fake.route('GET', '/calibrations/cal1', (200, {'id': 'cal1', 'chip': 'Dongling', 'qubits': []}))
    d = quafu.device('Dongling')
    assert (d.name, d.status, d.n_qubits, d.calibration_id) == ('Dongling', 'online', 84, 'cal1')
    cal = d.calibration()
    assert cal.qubit(5)['t1_us'] == 30.0 and cal.coupler(6, 5)['cz_fidelity'] == 0.98
    assert cal.measured_qubit(5)['readout_status'] == 'ok' and cal.qubit(9) is None
    assert quafu.calibration('cal1').id == 'cal1'
    assert all('Authorization' not in x['headers'] for x in fake.calls)
    fake.route('GET', '/devices/Nope', (404, {'error': 'unknown device', 'code': 'unknown_device'}))
    with pytest.raises(BadRequest) as e:
        quafu.device('Nope')
    assert e.value.code == 'unknown_device'


def test_stats_needs_login(fake, c, monkeypatch):
    q = {'used': 512, 'limit': 500, 'hard_limit': 5000, 'remaining': 0, 'degraded': True,
         'resets_at': '2026-10-10T23:00:00+08:00'}
    fake.route('GET', '/stats/me?days=7', (200, {'quota': {'date': '2026-10-10', 'real': q}}))
    assert c.stats(days=7)['quota']['real'] == q         # 平台原样
    assert fake.calls[0]['headers']['Authorization'].startswith('Bearer qf_')


# ── 请求层：重试与时限 ──────────────────────────────────────────────

def test_reads_retry_5xx_and_network_then_succeed(fake, c, clock):
    fake.route('GET', '/auth/me', (502, b'bad gateway'), Fail(sent=True), ME)
    c.whoami()
    assert len([x for x in fake.calls if x['path'] == '/auth/me']) == 3
    assert len(clock.sleeps) == 2 and all(0.25 <= s <= 8.0 for s in clock.sleeps)


def test_reads_give_up_after_five_attempts(fake, c, clock):
    fake.route('GET', '/auth/me', Fail(sent=True))
    with pytest.raises(ServerUnavailable):
        c.whoami()
    assert len(fake.calls) == 5 and len(clock.sleeps) == 4 and max(clock.sleeps) <= 8.0


@pytest.mark.parametrize('resp,exc', [
    ((401, {'error': 'x', 'code': 'invalid_api_key'}), LoginRevoked),
    ((404, {'error': 'unknown backend', 'code': 'unknown_backend'}), BadRequest),
    ((429, dispatcher_error('runtime.quotaExhausted', days=1), {'Retry-After': '60'}), QuotaError),
])
def test_4xx_is_never_retried(resp, exc, fake, c, clock):
    fake.route('GET', '/jobs/X/status', resp)
    with pytest.raises(exc):
        c.job('X')
    assert len(fake.calls) == 1 and clock.sleeps == []


def test_deadline_caps_timeouts_and_backoff(fake, c, clock):
    fake.route('GET', '/jobs/%s/status' % JID, Fail(sent=True))
    start = clock.t
    with pytest.raises(Timeout) as e:
        quafu.Job(c, JID, n_tasks=1).wait(timeout=3)
    assert e.value.job_id == JID and clock.t - start <= 3.0 + 1e-9
    assert all(x['read_timeout'] <= 3.0 for x in fake.calls)


def test_nan_never_reaches_the_wire(fake, c):
    with pytest.raises(ValueError, match='NaN'):
        c._request('POST', '/jobs', body={'points': [[float('nan')]]})
    assert fake.calls == []


def test_non_object_json_and_redirects_are_protocol_errors(fake, c):
    fake.route('GET', '/stats/me?days=30', (200, ['x']))
    with pytest.raises(ProtocolError):
        c.stats()
    fake.route('GET', '/auth/me', (301, b'', {'Location': 'https://new.test/api/v1/auth/me'}))
    with pytest.raises(ProtocolError) as e:
        c.whoami()
    assert 'new.test' in str(e.value)
