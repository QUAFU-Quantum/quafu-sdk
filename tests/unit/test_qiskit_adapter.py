# -*- coding: utf-8 -*-
"""Qiskit 适配（quafu.qiskit）：状态映射、Target 装配、bind、run 一律建任务组与结果装回、sweep。没装 qiskit 时整个文件跳过。
端到端用例在 contract/test_core_contract.py。"""
import pytest

pytest.importorskip('qiskit')

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, qasm2  # noqa: E402
from qiskit.circuit import Parameter, ParameterVector  # noqa: E402
from qiskit.providers import JobStatus  # noqa: E402

from quafu.errors import JobFailed  # noqa: E402
from quafu.qiskit import QuafuProvider, bind, build_target, job_status, sweep, to_qasm  # noqa: E402

from ..helpers import job_status as job_state, task_detail  # noqa: E402

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py

SIM_MD = (200, {'name': 'sim', 'device': 'sim', 'n_qubits': 24, 'basis_gates': [], 'coupling_map': [],
                'simulator': True})


def _x0():
    qc = QuantumCircuit(2, 2)
    qc.x(0)
    qc.measure([0, 1], [0, 1])
    return qc


def _job(fake, n, status='Finished'):
    """登记一个任务组：POST /jobs 受理 n 条，GET /jobs/J/status 给状态。"""
    fake.route('POST', '/jobs', (202, {'job_id': 'J', 'mode': 'single' if n == 1 else 'collection',
                                       'status': 'Queued', 'open': False,
                                       'task_ids': ['J-%d' % i for i in range(n)], 'n_tasks': n}))
    done = n if status == 'Finished' else 0
    fake.route('GET', '/jobs/J/status', job_state(status, total=n, finished=done,
                                                  failed=n if status == 'Failed' else 0, job_id='J'))


def _results(fake, rows):
    """rows：[(status, counts, error)]，按 seq 排：登记每条任务的详情。"""
    for i, (st, counts, err) in enumerate(rows):
        fake.route('GET', '/jobs/J/tasks/%d?include=counts,executed' % i,
                   task_detail(i, st, counts=counts, error=err, job_id='J'))


def test_task_and_job_states_map_to_job_status():
    assert [job_status(s) for s in ('Queued', 'Running', 'Finished', 'Failed', 'Cancelled', 'PartiallyFinished')] == [
        JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED, JobStatus.ERROR]
    assert job_status('SomethingNew') == JobStatus.QUEUED


def test_target_for_chip_without_topology_warns(caplog):
    t = build_target({'name': 'Dongling', 'n_qubits': 5, 'basis_gates': ['h', 'rx', 'ry', 'rz', 'cz', 'fsim_x'],
                      'coupling_map': [], 'simulator': False})
    assert t.num_qubits == 5 and {'cz', 'rz', 'measure'} <= set(t.operation_names) and 'fsim_x' not in t.operation_names
    assert '拓扑' in caplog.text


def test_target_with_coupling_map():
    t = build_target({'name': 'X', 'n_qubits': 3, 'basis_gates': ['cz', 'rz'], 'coupling_map': [[0, 1], [1, 2]]})
    assert set(t.build_coupling_map().get_edges()) == {(0, 1), (1, 2)}


def test_target_for_ideal_simulator(caplog):
    t = build_target(SIM_MD[1])
    assert t.num_qubits == 24 and {'cx', 'h', 'measure'} <= set(t.operation_names) and '拓扑' not in caplog.text


JD_MD = {'name': 'Baihua-sim-jiuding', 'device': 'Baihua', 'n_qubits': 4, 'basis_gates': ['cz', 'rz', 'sx', 'x'],
         'coupling_map': [[0, 1], [1, 2], [2, 3]], 'simulator': True, 'noise': 'none', 'max_qubits': 30,
         'status': 'online'}


def test_target_for_jiuding_simulator_follows_the_chip_graph(caplog):
    t = build_target(JD_MD)
    assert t.num_qubits == 4 and set(t.build_coupling_map().get_edges()) == {(0, 1), (1, 2), (2, 3)}
    assert {'cz', 'rz', 'measure'} <= set(t.operation_names) and 'cx' not in t.operation_names
    assert '拓扑' not in caplog.text
    build_target(dict(JD_MD, name='Shenglian-sim-jiuding', coupling_map=[]))
    assert '拓扑' in caplog.text                     # 按真机图转译的后端缺拓扑要提示，即使它是模拟器


def test_jiuding_simulator_backend_transpiles_and_submits_by_name(fake, make_client, clock):
    from qiskit import transpile
    fake.route('GET', '/backends/Baihua-sim-jiuding/metadata', (200, JD_MD))
    _job(fake, 1)
    _results(fake, [('Finished', {'11': 8}, None)])
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    be = QuafuProvider(client=make_client()).get_backend('Baihua-sim-jiuding')
    tqc = transpile(qc, be)
    assert set(tqc.count_ops()) <= {'cz', 'rz', 'sx', 'x', 'measure', 'barrier'}
    job = be.run(tqc, shots=8)
    (post,) = fake.posts()
    assert post['body']['target'] == 'Baihua-sim-jiuding'
    assert job.result().get_counts() == {'11': 8}


def test_bind_keeps_qiskit_names_and_orders_columns_like_qc_parameters():
    theta, vec = Parameter('θ'), ParameterVector('phi', 2)
    qc = QuantumCircuit(1, 1)
    qc.rx(theta, 0)
    qc.ry(vec[0], 0)
    qc.rz(vec[1], 0)
    qc.measure(0, 0)
    names = [p.name for p in qc.parameters]
    parameters, circuits = bind(qc, [[0.1, 0.2, 0.3], [1, 2, 3]])
    assert [p['name'] for p in parameters] == names and all(p['unit'] == 'rad' for p in parameters)
    assert 'symbol' not in parameters[0]
    assert circuits[1]['parameter_values'] == dict(zip(names, [1.0, 2.0, 3.0]))
    assert 'rx' in circuits[0]['qasm'] and 'θ' not in circuits[0]['qasm']
    parameters, _ = bind(qc, [[0, 0, 0]], names=['a', 'b', 'c'], unit='1')
    assert parameters[0] == {'name': 'a', 'unit': '1', 'symbol': names[0]}


def test_to_qasm_sorts_the_trailing_measures_by_clbit():
    qc = QuantumCircuit(3, 3)
    qc.h(0)
    qc.measure([2, 0, 1], [2, 0, 1])
    text = to_qasm(qc)
    assert [ln for ln in text.splitlines() if ln.startswith('measure')] == [
        'measure q[0] -> c[0];', 'measure q[1] -> c[1];', 'measure q[2] -> c[2];']
    assert 'h q[0];' in text and len(qc.data) == 4          # 原线路不动
    assert to_qasm(_x0()) == qasm2.dumps(_x0())             # 已经升序的原样导出


def test_to_qasm_reordered_export_runs_the_same_on_aer(caplog):
    aer = pytest.importorskip('qiskit_aer')
    qc = QuantumCircuit(2, 2)
    qc.x(0)                                     # 不对称夹具：映射错了就不是 '01'
    qc.measure([1, 0], [1, 0])
    with caplog.at_level('DEBUG', logger='quafu'):
        text = to_qasm(qc)
    assert text.index('measure q[0] -> c[0];') < text.index('measure q[1] -> c[1];')
    assert 'ascending clbit order' in caplog.text
    big = QuantumCircuit(3, 3)
    big.x(0)
    big.x(2)
    big.measure([1, 2, 0], [1, 2, 0])
    sim = aer.AerSimulator()
    for original in (qc, big):
        exported = qasm2.loads(to_qasm(original))
        counts = [sim.run(c, shots=200).result().get_counts() for c in (original, exported)]
        assert counts[0] == counts[1] and len(counts[0]) == 1


def test_to_qasm_leaves_repeated_bits_alone(caplog):
    same_qubit = QuantumCircuit(2, 2)
    same_qubit.measure(1, 1)
    same_qubit.measure(0, 0)
    same_qubit.measure(0, 1)                    # 比特 0 测两次
    same_clbit = QuantumCircuit(3, 2)
    same_clbit.measure(1, 1)
    same_clbit.measure(2, 0)
    same_clbit.measure(0, 1)                    # 经典位 1 写两次
    with caplog.at_level('DEBUG', logger='quafu'):
        for qc in (same_qubit, same_clbit):
            assert to_qasm(qc) == qasm2.dumps(qc)
    assert 'ascending clbit order' not in caplog.text


def test_to_qasm_leaves_measures_before_other_gates_alone():
    qc = QuantumCircuit(2, 2)
    qc.measure(1, 1)
    qc.h(0)
    qc.measure(0, 0)
    assert to_qasm(qc) == qasm2.dumps(qc)


def test_bind_sorts_trailing_measures_too():
    theta = Parameter('theta')
    qc = QuantumCircuit(2, 2)
    qc.rx(theta, 0)
    qc.measure([1, 0], [1, 0])
    _, circuits = bind(qc, [0.5])
    assert circuits[0]['qasm'].index('-> c[0]') < circuits[0]['qasm'].index('-> c[1]')


def test_bind_rejects_shape_mismatches():
    qc = QuantumCircuit(1, 1)
    qc.rx(Parameter('theta'), 0)
    qc.measure(0, 0)
    assert len(bind(qc, [0.0, 0.5, 1.0])[1]) == 3          # 单参数时每行可以是单个数
    with pytest.raises(ValueError):
        bind(qc, [[0.0, 1.0]])
    with pytest.raises(ValueError):
        bind(qc, [[0.0]], names=['a', 'b'])
    with pytest.raises(ValueError):
        bind(_x0(), [[0.0]])


def test_provider_lists_chip_and_noisy_backends(fake, make_client):
    fake.route('GET', '/devices', (200, {'simulator': {'name': 'sim', 'max_qubits': 24, 'status': 'online'},
                                         'devices': [{'name': 'Baihua', 'simulator_available': True},
                                                     {'name': 'Dongling', 'simulator_available': True}]}))
    names = [b.name for b in QuafuProvider(client=make_client()).backends()]
    assert names == ['sim', 'Baihua', 'Dongling', 'Baihua-sim', 'Dongling-sim']


def test_provider_lists_jiuding_simulators(fake, make_client):
    fake.route('GET', '/devices', (200, {'simulator': {'name': 'sim', 'max_qubits': 24, 'status': 'online'},
                                         'devices': [{'name': 'Baihua'}],
                                         'simulated_chips': [{'name': 'Baihua-sim-jiuding', 'status': 'online',
                                                              'n_qubits': 156, 'max_qubits': 30}]}))
    names = [b.name for b in QuafuProvider(client=make_client()).backends()]
    assert names == ['sim', 'Baihua', 'Baihua-sim-jiuding']


def test_run_submits_one_collection_job_and_collects_counts(fake, make_client, clock):
    fake.route('GET', '/backends/sim/metadata', SIM_MD)
    _job(fake, 2)
    _results(fake, [('Finished', {'01': 10}, None), ('Finished', {'10': 10}, None)])
    qc1 = _x0()
    a, b = ClassicalRegister(1, 'a'), ClassicalRegister(1, 'b')
    qc2 = QuantumCircuit(QuantumRegister(2, 'q'), a, b)
    qc2.x(1)
    qc2.measure(0, a[0])
    qc2.measure(1, b[0])

    be = QuafuProvider(client=make_client()).get_backend('sim')
    job = be.run([qc1, qc2], shots=10)
    (post,) = fake.posts()
    body = dict(post['body'])
    body.pop('client_ref')
    assert post['path'] == '/jobs' and body == {
        'mode': 'collection', 'target': 'sim', 'shots': 10, 'circuit_level': 'logical',
        'circuits': [{'qasm': qasm2.dumps(qc1)}, {'qasm': qasm2.dumps(qc2)}]}
    assert job.job_id() == 'J' and job.status() == JobStatus.DONE
    res = job.result()
    assert res.get_counts(0) == {'01': 10} and res.get_counts(1) == {'1 0': 10}
    assert res.results[0].header['task_id'] == 'J-0'


def test_a_single_circuit_is_a_single_job(fake, make_client, clock):
    fake.route('GET', '/backends/sim/metadata', SIM_MD)
    _job(fake, 1)
    _results(fake, [('Finished', {'01': 10}, None)])
    job = QuafuProvider(client=make_client()).get_backend('sim').run(_x0(), shots=10)
    assert fake.posts()[0]['body']['mode'] == 'single'
    assert job.result().get_counts() == {'01': 10}
    assert not any(c['path'].startswith('/tasks') for c in fake.calls)


def test_cancel_cancels_the_job(fake, make_client):
    fake.route('GET', '/backends/sim/metadata', SIM_MD)
    _job(fake, 2, status='Running')
    fake.route('POST', '/jobs/J/cancel', (200, {'job_id': 'J', 'status': 'Cancelled', 'open': False,
                                                'cancelled_now': 2, 'cancel_requested': 0}))
    job = QuafuProvider(client=make_client()).get_backend('sim').run([_x0(), _x0()], shots=10)
    job.cancel()
    assert [c['path'] for c in fake.posts()][-1] == '/jobs/J/cancel'


def test_run_default_shots_and_rejects_unknown_options(fake, make_client):
    fake.route('GET', '/backends/sim/metadata', SIM_MD)
    _job(fake, 1)
    be = QuafuProvider(client=make_client()).get_backend('sim')
    with pytest.raises(TypeError):
        be.run(_x0(), memory=True)
    assert fake.posts() == []
    be.run(_x0())
    assert fake.posts()[0]['body']['shots'] == 1024


def test_all_failed_surfaces_from_job_result(fake, make_client, clock):
    fake.route('GET', '/backends/sim/metadata', SIM_MD)
    _job(fake, 1, status='Failed')
    _results(fake, [('Failed', None, {'category': 'runtime.internal', 'stage': 'dispatcher', 'retryable': True,
                                     'detail': 'x', 'vars': {}})])
    job = QuafuProvider(client=make_client()).get_backend('sim').run(_x0(), shots=10)
    assert job.status() == JobStatus.ERROR
    with pytest.raises(JobFailed):
        job.result()


def test_sweep_binds_locally_and_submits_one_collection_with_declared_parameters(fake, make_client):
    qc = QuantumCircuit(1, 1)
    qc.rx(Parameter('theta'), 0)
    qc.measure(0, 0)
    _job(fake, 3)
    job = sweep(qc, [0.0, 0.5, 1.0], 'sim', shots=64, name='扫 theta', client=make_client())
    body = fake.posts('/jobs')[0]['body']
    assert body['mode'] == 'collection' and body['parameters'] == [{'name': 'theta', 'unit': 'rad'}]
    assert [c['parameter_values'] for c in body['circuits']] == [{'theta': 0.0}, {'theta': 0.5}, {'theta': 1.0}]
    assert body['name'] == '扫 theta' and body['shots'] == 64 and job.n_tasks == 3
