# -*- coding: utf-8 -*-
"""交线路与取回：请求体（U10）、Qiskit 输入（U11）、任务组句柄、devices()。"""
import logging
import subprocess
import sys
import uuid

import pytest

import quafu
from quafu.errors import (BadRequest, JobCancelled, JobFailed, JobNotFound, PrecheckError, QuotaError, Timeout)

from ..helpers import (BELL, JID, KEY, SUBPROCESS_TIMEOUT, Fail, accepted, dispatcher_error, job_status,
                       task_detail)

BLOCK_QISKIT = '''
import sys
class _Block(object):
    def find_spec(self, name, path=None, target=None):
        if name == 'qiskit' or name.startswith('qiskit.'):
            raise ImportError('blocked ' + name)
sys.meta_path.insert(0, _Block())
'''


@pytest.fixture
def c(make_client):
    return make_client()


# ── U10 请求体 ──────────────────────────────────────────────────────

def test_one_circuit_is_a_single_job(fake, c):
    fake.route('POST', '/jobs', accepted())
    job = c.submit(BELL, target='sim', shots=256, name='贝尔态')
    body = fake.posts('/jobs')[0]['body']
    assert body['mode'] == 'single' and body['target'] == 'sim' and body['shots'] == 256
    assert body['name'] == '贝尔态' and body['circuits'] == [{'qasm': BELL}]
    assert body['circuit_level'] == 'logical' and uuid.UUID(body['client_ref']).version == 4
    assert fake.posts('/jobs')[0]['headers']['Authorization'] == 'Bearer ' + KEY
    assert (job.id, job.n_tasks) == (JID, 1)


def test_a_list_is_a_collection_in_order(fake, c):
    fake.route('POST', '/jobs', accepted(3, 'collection'))
    job = c.submit([BELL, BELL.replace('h q[0]', 'x q[0]'), BELL], target='Dongling')
    body = fake.posts('/jobs')[0]['body']
    assert body['mode'] == 'collection' and len(body['circuits']) == 3 and 'x q[0]' in body['circuits'][1]['qasm']
    assert body['shots'] == 1024 and 'name' not in body and job.n_tasks == 3


@pytest.mark.parametrize('compiler, level', [('qiskit', 'logical'), ('none', 'physical')])
def test_compiler_maps_to_circuit_level(fake, c, compiler, level):
    fake.route('POST', '/jobs', accepted())
    c.submit(BELL, target='Dongling', compiler=compiler)
    assert fake.posts('/jobs')[0]['body']['circuit_level'] == level


@pytest.mark.parametrize('kw', [dict(target=''), dict(target=None), dict(target='sim', compiler='qsteed'),
                                dict(target='sim', compiler=None)])
def test_bad_target_or_compiler_sends_nothing(fake, c, kw):
    with pytest.raises(BadRequest):
        c.submit(BELL, **kw)
    assert fake.calls == []


def test_bad_inputs_send_nothing(fake, c):
    with pytest.raises(ValueError):
        c.submit([], target='sim')
    with pytest.raises(ValueError):
        c.submit('   ', target='sim')
    with pytest.raises(TypeError):
        c.submit(BELL, target='sim', shots=1.5)
    assert fake.calls == []


def test_lost_response_is_replayed_with_the_same_client_ref(fake, c, clock):
    fake.route('POST', '/jobs', Fail(sent=True), (502, b'<html>bad gateway</html>'), accepted())
    assert c.submit(BELL, target='sim').id == JID
    refs = {p['body']['client_ref'] for p in fake.posts('/jobs')}
    assert len(fake.posts('/jobs')) == 3 and len(refs) == 1
    assert fake.posts('/jobs')[0]['read_timeout'] == 120.0


def test_two_submits_use_different_client_refs(fake, c):
    fake.route('POST', '/jobs', accepted())
    c.submit(BELL, target='sim')
    c.submit(BELL, target='sim')
    assert len({p['body']['client_ref'] for p in fake.posts('/jobs')}) == 2


def test_rejections_are_not_retried_and_keep_the_platform_reason(fake, c):
    fake.route('POST', '/jobs', (422, dispatcher_error('precheck.shotsOutOfRange', 'shots 须是 1024 的倍数')))
    with pytest.raises(PrecheckError) as e:
        c.submit(BELL, target='Dongling', shots=1000)
    assert e.value.category == 'precheck.shotsOutOfRange' and '1024' in str(e.value)
    fake.route('POST', '/jobs', (429, {'error': '今日额度已用完', 'code': 'quota_exceeded'}, {'Retry-After': '60'}))
    with pytest.raises(QuotaError) as e:
        c.submit(BELL, target='sim')
    assert e.value.retry_after == 60
    assert len(fake.posts('/jobs')) == 2


def test_module_level_submit_uses_the_default_client(fake, monkeypatch):
    monkeypatch.setenv('QUAFU_API_KEY', KEY)
    fake.route('POST', '/jobs', accepted())
    assert quafu.submit(BELL, 'sim').id == JID
    assert fake.posts()[0]['url'] == 'https://quafu.test/api/v1/jobs'


# ── U11 Qiskit 输入 ─────────────────────────────────────────────────

def test_qiskit_circuit_is_exported_as_openqasm2(fake, c):
    qiskit = pytest.importorskip('qiskit')
    qc = qiskit.QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure(1, 1)
    qc.measure(0, 0)
    fake.route('POST', '/jobs', accepted(2, 'collection'))
    c.submit([qc, BELL], target='sim')
    qasm = fake.posts('/jobs')[0]['body']['circuits'][0]['qasm']
    assert qasm.startswith('OPENQASM 2.0;') and 'cx q[0],q[1];' in qasm
    assert qasm.index('measure q[0] -> c[0]') < qasm.index('measure q[1] -> c[1]')   # 末尾测量按经典位升序


def test_unbound_parameters_are_refused_by_qiskit_before_sending(fake, c):
    qiskit = pytest.importorskip('qiskit')
    from qiskit.circuit import Parameter
    qc = qiskit.QuantumCircuit(1, 1)
    qc.rx(Parameter('t'), 0)
    qc.measure(0, 0)
    with pytest.raises(Exception):
        c.submit(qc, target='sim')
    assert fake.calls == []


def test_non_string_without_qiskit_is_a_type_error_with_the_install_hint():
    code = BLOCK_QISKIT + '\n'.join([
        'import quafu',
        'c = quafu.Client(api_key="qf_abc")',
        'try:',
        '    c.submit(object(), target="sim")',
        'except TypeError as e:',
        '    print("HINT" if \'pip install "quafu-sdk[qiskit]"\' in str(e) else str(e))',
        'assert not [m for m in sys.modules if m.split(".")[0] == "qiskit"]',
    ])
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    assert r.returncode == 0 and 'HINT' in r.stdout, r.stdout + r.stderr


# ── 任务组句柄 ──────────────────────────────────────────────────────

def test_result_waits_then_reads_counts_and_research_fields(fake, c, clock):
    fake.route('POST', '/jobs', accepted())
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Queued'), job_status('Running', running=1),
               job_status('Finished', finished=1))
    fake.route('GET', '/jobs/%s/tasks/0?include=counts,executed' % JID, task_detail())
    r = c.submit(BELL, target='sim').result()
    assert r.ok and r.counts == {'00': 60, '11': 40} and r.bit_order == 'c0_rightmost' and r.n_clbits == 2
    assert (r.shots_requested, r.shots_returned) == (100, 100) and r.probabilities() == {'00': 0.6, '11': 0.4}
    assert r.measurements[1]['physical_qubit'] == 1 and r.executed_qasm == BELL
    assert r.compiler['name'] == 'qiskit' and r.calibration_id is None and r.task_id == JID + '-0'
    assert r.counts_by_qubit([1]) == {'0': 60, '1': 40}
    assert clock.sleeps == [1.0, 1.0]


def test_results_are_aligned_and_failures_do_not_raise(fake, c, clock):
    fake.route('POST', '/jobs', accepted(3, 'collection'))
    fake.route('GET', '/jobs/%s/status' % JID, job_status('PartiallyFinished', total=3, finished=1, failed=1,
                                                         cancelled=1))
    err = {'category': 'precheck.edgeUnusable', 'stage': 'precheck', 'retryable': False, 'detail': '边不可用',
           'vars': {}}
    fake.route('GET', '/jobs/%s/tasks/0?include=counts,executed' % JID, task_detail(0))
    fake.route('GET', '/jobs/%s/tasks/1?include=counts,executed' % JID, task_detail(1, 'Failed', error=err))
    fake.route('GET', '/jobs/%s/tasks/2?include=counts,executed' % JID, task_detail(2, 'Cancelled'))
    job = c.submit([BELL] * 3, target='sim')
    rs = job.results()
    assert [r.status for r in rs] == ['Finished', 'Failed', 'Cancelled']
    assert [r.counts is None for r in rs] == [False, True, True]
    assert rs[1].error['category'] == 'precheck.edgeUnusable' and rs[2].error is None
    with pytest.raises(ValueError) as e:
        job.result()
    assert 'results()' in str(e.value)
    n = len(fake.paths())
    assert job.results()[0] is not None and len(fake.paths()) == n          # 结果缓存，不重复取


def test_failed_single_raises_job_failed_with_the_reason(fake, c, clock):
    fake.route('POST', '/jobs', accepted())
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Failed', failed=1))
    err = {'category': 'runtime.simTimeout', 'stage': 'hardware', 'retryable': True, 'detail': '模拟超时',
           'vars': {'limit_s': 600}}
    fake.route('GET', '/jobs/%s/tasks/0?include=counts,executed' % JID, task_detail(0, 'Failed', error=err))
    with pytest.raises(JobFailed) as e:
        c.submit(BELL, target='sim').result()
    v = e.value
    assert (v.category, v.error_stage, v.retryable, v.job_id) == ('runtime.simTimeout', 'hardware', True, JID)
    assert '600' in str(v) and v.task_id == JID + '-0'


def test_cancelled_single_raises_job_cancelled(fake, c, clock):
    fake.route('POST', '/jobs', accepted())
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Cancelled', cancelled=1))
    fake.route('GET', '/jobs/%s/tasks/0?include=counts,executed' % JID, task_detail(0, 'Cancelled'))
    with pytest.raises(JobCancelled):
        c.submit(BELL, target='sim').result()


def test_timeout_leaves_the_job_resumable(fake, c, clock):
    fake.route('POST', '/jobs', accepted())
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Queued'))
    job = c.submit(BELL, target='Dongling')
    with pytest.raises(Timeout) as e:
        job.result(timeout=10)
    assert e.value.job_id == JID and 'result()' in str(e.value)
    assert abs(sum(clock.sleeps) - 10) < 1e-9


def test_polling_slows_down(fake, c, clock):
    fake.route('POST', '/jobs', accepted())
    fake.route('GET', '/jobs/%s/status' % JID, *([job_status('Queued')] * 200 + [job_status('Finished', finished=1)]))
    c.submit(BELL, target='Dongling').wait()
    assert clock.sleeps[0] == 1.0 and 5.0 in clock.sleeps and clock.sleeps[-1] == 30.0


def test_ctrl_c_stops_waiting_but_not_the_job(fake, c, clock, caplog):
    fake.route('POST', '/jobs', accepted())
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Queued'))
    clock.interrupt_after = 2
    job = c.submit(BELL, target='sim')
    with caplog.at_level(logging.WARNING, logger='quafu'):
        with pytest.raises(KeyboardInterrupt):
            job.wait()
    assert JID in caplog.text and not fake.posts('/jobs/%s/cancel' % JID)


def test_status_and_cancel(fake, c):
    fake.route('POST', '/jobs', accepted())
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Running', running=1))
    fake.route('POST', '/jobs/%s/cancel' % JID, (200, {'job_id': JID, 'open': False, 'status': 'Cancelled',
                                                       'cancelled_now': 1, 'cancel_requested': 0}))
    job = c.submit(BELL, target='sim')
    assert job.status() == 'Running'
    assert job.cancel()['cancelled_now'] == 1


def test_job_reattaches_by_id_and_knows_its_size(fake, c, clock):
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Finished', total=2, finished=2))
    fake.route('GET', '/jobs/%s/tasks/0?include=counts,executed' % JID, task_detail(0))
    fake.route('GET', '/jobs/%s/tasks/1?include=counts,executed' % JID, task_detail(1))
    job = c.job(JID)
    assert job.n_tasks == 2 and len(job.results()) == 2


def test_unknown_job_is_job_not_found(fake, c):
    fake.route('GET', '/jobs/nope/status', (404, {'error': '任务组不存在', 'code': 'not_found'}))
    with pytest.raises(JobNotFound):
        c.job('nope')
    with pytest.raises(BadRequest):
        c.job('')


def test_job_id_is_escaped_in_paths(fake, c):
    fake.route('GET', '/jobs/a%2Fb/status', job_status('Queued'))
    c.job('a/b')
    assert fake.paths() == ['/jobs/a%2Fb/status']


# ── devices() ───────────────────────────────────────────────────────

def test_devices_lists_every_target_name(fake):
    # 每行的 limits 原样取自平台：理想模拟 simulator.limits，真机行 limits，带噪模拟取真机行的 sim_limits
    lim_sim, lim_real, lim_noisy = {'max_qubits': 'S'}, {'max_qubits': 'R'}, {'max_qubits': 'N'}
    fake.route('GET', '/devices', (200, {
        'simulator': {'name': 'sim', 'max_qubits': 24, 'status': 'online', 'limits': lim_sim},
        'devices': [{'name': 'Dongling', 'status': 'online', 'n_qubits': 84, 'queue': 3, 'simulator_available': True,
                     'calibration_id': 'x', 'limits': lim_real, 'sim_limits': lim_noisy},
                    {'name': 'Ling', 'status': 'calibrating', 'n_qubits': 112, 'queue': None,
                     'simulator_available': False}]}))
    ds = quafu.devices()
    assert ds == [{'name': 'sim', 'kind': 'sim', 'status': 'online', 'n_qubits': 24, 'queue': None, 'limits': lim_sim},
                  {'name': 'Dongling', 'kind': 'real', 'status': 'online', 'n_qubits': 84, 'queue': 3,
                   'limits': lim_real},
                  {'name': 'Ling', 'kind': 'real', 'status': 'calibrating', 'n_qubits': 112, 'queue': None,
                   'limits': None},
                  {'name': 'Dongling-sim', 'kind': 'sim', 'status': 'online', 'n_qubits': 84, 'queue': None,
                   'limits': lim_noisy}]


def test_devices_lists_jiuding_simulators_with_chip_size_and_qubit_limit(fake):
    fake.route('GET', '/devices', (200, {
        'simulator': {'name': 'sim', 'max_qubits': 24, 'status': 'online'},
        'devices': [{'name': 'Baihua', 'status': 'online', 'n_qubits': 156, 'queue': 0}],
        'simulated_chips': [{'name': 'Baihua-sim-jiuding', 'chip': 'Baihua', 'status': 'starting', 'noise': 'none',
                             'n_qubits': 156, 'max_qubits': 30, 'basis_gates': ['cz', 'rz'], 'calibration_id': 'c',
                             'queue': 2, 'running': 1, 'limits': {'max_qubits': 30}}]}))
    ds = quafu.devices()
    assert ds[-1] == {'name': 'Baihua-sim-jiuding', 'kind': 'sim', 'status': 'starting', 'n_qubits': 156,
                      'queue': 2, 'max_qubits': 30, 'limits': {'max_qubits': 30}}
    assert [d['name'] for d in ds] == ['sim', 'Baihua', 'Baihua-sim-jiuding']


def test_devices_without_jiuding_simulators_is_unchanged(fake):
    fake.route('GET', '/devices', (200, {'simulator': {'name': 'sim', 'max_qubits': 24, 'status': 'online'},
                                         'devices': [], 'simulated_chips': []}))
    assert quafu.devices() == [{'name': 'sim', 'kind': 'sim', 'status': 'online', 'n_qubits': 24, 'queue': None,
                                'limits': None}]
