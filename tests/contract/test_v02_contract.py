# -*- coding: utf-8 -*-
"""契约测试（v0.2 迁入的功能）：扫参、迭代式任务组、列式结果表、设备与校准、带噪模拟、统计、Qiskit 适配。
经真 HTTP、经「门户地址 → /api/v1 → 任务分发器」对着本仓任务分发器跑，夹具见 conftest.py。
用例自旧包 quafu-portal 的契约测试迁来，改用 v0.1 的命名（submit / sweep / open_job / table / target / compiler）。"""
import math
import uuid

import pytest

import quafu
from quafu import tables as tables_mod
from quafu.errors import BadRequest, JobClosed, NotLoggedIn, PrecheckError, QuotaError

HEAD = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
BELL = HEAD + 'h q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n'
Q6 = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[6];\n'
ONE = Q6 + 'creg c[1];\nx q[5];\nmeasure q[5] -> c[0];\n'
X1 = Q6 + 'creg c[2];\nx q[1];\nmeasure q[1] -> c[0];\nmeasure q[2] -> c[1];\n'   # c[0]=1、c[1]=0 → '01'
TWO_CREGS = Q6 + 'creg a[1];\ncreg b[1];\nx q[5];\nmeasure q[5] -> a[0];\nmeasure q[4] -> b[0];\n'
TEMPLATE = Q6 + 'creg c[1];\nrx({{theta}}) q[5];\nmeasure q[5] -> c[0];\n'
THETA = [{'name': 'theta', 'unit': 'rad', 'symbol': 'θ'}]


def jobs_total(client):
    return client._request('GET', '/jobs?limit=1')['total']


# ── G1 扫参与线路集合 ───────────────────────────────────────────────

def test_sweep_with_server_binding(client, transport):
    job = client.sweep(TEMPLATE, THETA, [0.0, math.pi / 2, math.pi], 'sim', name='RX 扫描')
    body = transport.posts('/jobs')[0]['body']
    assert body['mode'] == 'sweep' and body['points'] == [[0.0], [math.pi / 2], [math.pi]] and 'circuits' not in body
    assert body['parameters'] == THETA and uuid.UUID(body['client_ref'])
    assert job.n_tasks == 3 and not job.open
    t = job.table(timeout=120)
    assert t.complete and t.parameter_names == ['theta'] and t.column('theta') == [0.0, math.pi / 2, math.pi]
    assert t.status == ['Finished'] * 3 and t.counts[0] == {'0': 1024} and t.counts[2] == {'1': 1024}
    z = t.expectation_z([0])
    assert z[0] == 1.0 and z[2] == -1.0 and abs(z[1]) < 0.2
    assert t.to_dict()['theta'][1] == math.pi / 2
    rs = job.results()
    assert [r.parameter_values for r in rs] == [{'theta': 0.0}, {'theta': math.pi / 2}, {'theta': math.pi}]
    assert rs[2].expectation_z([0]) == -1.0


def test_undeclared_placeholder_rejects_the_whole_job(client):
    before = jobs_total(client)
    with pytest.raises(PrecheckError) as e:
        client.sweep(TEMPLATE.replace('{{theta}}', '{{phi}}'), THETA, [[0.1]], 'sim')
    assert e.value.category == 'precheck.badTemplate' and e.value.vars['placeholder'] == 'phi'
    assert jobs_total(client) == before


def test_parameter_names_may_look_like_qiskit_names(client):
    template = TEMPLATE.replace('{{theta}}', '{{θ[0]}}')
    job = client.sweep(template, [{'name': 'θ[0]', 'unit': 'rad'}], [[0.5]], 'sim')
    assert job.table(timeout=60).column('θ[0]') == [0.5]


def test_parameter_values_need_declared_parameters(client):
    with pytest.raises(PrecheckError) as e:
        client.submit([{'qasm': ONE, 'parameter_values': {'theta': 0.1}}], 'sim')
    assert e.value.vars['missing'] is True and e.value.vars['undeclared'] == ['theta']


def test_collection_rows_keep_their_own_width(client, transport):
    job = client.submit([ONE, X1], 'sim')
    assert transport.posts('/jobs')[0]['body']['mode'] == 'collection'
    t = job.table(timeout=60)
    assert t.n_clbits == [1, 2] and t.counts == [{'1': 1024}, {'01': 1024}]
    assert t.reordered('c0_leftmost') == [{'1': 1024}, {'10': 1024}] and t.points == [None, None]


def test_table_snapshot_has_every_task(client):
    job = client.submit([ONE, X1, ONE], 'sim')
    snap = job.table(wait=False)
    assert len(snap) == 3 and snap.seq == [0, 1, 2]
    assert all(c is None for c, s in zip(snap.counts, snap.status) if s != 'Finished')
    assert job.table(timeout=60).complete


def test_job_submission_is_idempotent_across_a_lost_response(client, transport):
    before = jobs_total(client)
    transport.lose.add(('POST', '/jobs'))
    job = client.submit([X1, ONE], 'sim')
    posts = transport.posts('/jobs')
    assert len(posts) == 2 and posts[0]['body']['client_ref'] == posts[1]['body']['client_ref']
    assert jobs_total(client) == before + 1 and job.n_tasks == 2


def test_too_large_is_quota_error_and_never_split(client, transport):
    before = jobs_total(client)
    with pytest.raises(QuotaError) as e:
        client.submit([ONE] * 501, 'sim')
    assert e.value.code == 'job_too_large' and e.value.vars['max'] == 500 and "doesn't split" in str(e.value)
    assert len(transport.posts('/jobs')) == 1 and jobs_total(client) == before


def test_table_is_paged_transparently(client, transport, monkeypatch):
    monkeypatch.setattr(tables_mod, 'RESULT_PAGE', 2)
    job = client.submit([ONE] * 5, 'sim')
    t = job.table(timeout=60)
    assert t.seq == [0, 1, 2, 3, 4] and t.counts == [{'1': 1024}] * 5
    offsets = [c['query']['offset'] for c in transport.calls if c['path'] == '/jobs/%s/results' % job.id]
    assert offsets == ['0', '2', '4']


# ── G2 迭代式任务组 ─────────────────────────────────────────────────

def test_iterative_open_append_wait_close(client):
    job = client.open_job('sim', template=TEMPLATE, parameters=[('theta', 'rad')], name='VQE')
    assert job.open is True and job.n_tasks == 0
    first = job.append(points=[[0.1]], iteration=0)
    second = job.append(circuits=[{'qasm': ONE, 'parameter_values': {'theta': 0.2}}], iteration=1, evaluation_index=2)
    assert [first[0], second[0]] == [job.id + '-0', job.id + '-1'] and job.n_tasks == 2
    job.wait(timeout=60)                              # 还开着：当前没有排队或运行中的任务就返回
    t = job.table(wait=False)
    assert t.iterations == [0, 1] and t.evaluation_index == [0, 2] and t.column('theta') == [0.1, 0.2]
    rs = job.results()
    assert [r.iteration for r in rs] == [0, 1] and [r.parameter_values for r in rs] == [{'theta': 0.1},
                                                                                        {'theta': 0.2}]
    assert job.close()['open'] is False and job.status() == 'Finished'
    with pytest.raises(JobClosed) as e:
        job.append(points=[[0.3]])
    assert e.value.code == 'job_closed'


def test_points_append_carries_the_round_and_replays_after_a_lost_response(client, transport):
    job = client.open_job('sim', template=TEMPLATE, parameters=THETA)
    transport.lose.add(('POST', '/jobs/%s/tasks' % job.id))
    tids = job.append(points=[[0.1], [0.2]], iteration=3, evaluation_index=1)
    posts = transport.posts('/jobs/%s/tasks' % job.id)
    assert len(posts) == 2 and posts[0]['body']['client_ref'] == posts[1]['body']['client_ref']
    assert len(tids) == 2 and job.n_tasks == 2
    job.wait(timeout=60)
    t = job.table(wait=False)
    assert t.iterations == [3, 3] and t.evaluation_index == [1, 1]
    job.close()


def test_iterative_job_may_declare_parameters_without_a_template(client):
    job = client.open_job('sim', parameters=THETA)
    job.append(circuits=[{'qasm': ONE, 'parameter_values': {'theta': 0.3}}], iteration=0)
    job.wait(timeout=60)
    assert job.table(wait=False).column('theta') == [0.3]
    job.close()


def test_append_rules(client):
    sweep = client.sweep(TEMPLATE, THETA, [[0.0]], 'sim')
    with pytest.raises(JobClosed) as e:
        sweep.append(circuits=[ONE])
    assert e.value.code == 'job_not_iterative'
    bare = client.open_job('sim')
    with pytest.raises(JobClosed) as e:
        bare.append(points=[[0.1]])
    assert e.value.code == 'job_has_no_template'
    bare.close()


def test_reattached_iterative_job_knows_it_is_open(client, account, transport):
    job = client.open_job('sim', template=TEMPLATE, parameters=THETA)
    job.append(points=[[0.4]])
    again = quafu.Client(api_key=account[1], _transport=transport).job(job.id)
    assert again.open is True and again.n_tasks == 1
    again.close()
    assert client.job(job.id).open is False


# ── G4 设备与校准、带噪模拟 ─────────────────────────────────────────

def test_devices_and_calibrations_need_no_login(transport, monkeypatch):
    monkeypatch.delenv('QUAFU_API_KEY', raising=False)
    anon = quafu.Client(_transport=transport)
    name = next(d['name'] for d in anon.devices() if d['kind'] == 'real')
    dev = anon.device(name)
    cal = dev.calibration()
    assert cal.id == dev.calibration_id and cal.chip == dev.name and cal.qubits and cal.basis_gates
    q = cal.qubits[0]
    assert cal.qubit(q['index']) == q
    assert anon.calibration(cal.id).qubits == cal.qubits
    with pytest.raises(BadRequest) as e:
        anon.device('Nope')
    assert e.value.code == 'unknown_device'
    assert all('Authorization' not in c['headers'] for c in transport.calls)
    with pytest.raises(NotLoggedIn):
        anon.whoami()


def test_calibration_splits_public_values_from_platform_measurements(transport):
    anon = quafu.Client(_transport=transport)
    measured_somewhere = False
    for name in [d['name'] for d in anon.devices() if d['kind'] == 'real']:
        dev = anon.device(name)
        if not dev.calibration_id:
            continue
        cal = anon.calibration(dev.calibration_id)
        assert all('readout_source' not in q and 'readout_measured_at' not in q for q in cal.qubits)
        coords = [q['coordinate'] for q in cal.qubits if q.get('coordinate')]
        assert cal.grid == ({'rows': max(y for _, y in coords) + 1, 'cols': max(x for x, _ in coords) + 1}
                            if coords else None)
        m = cal.measured
        assert isinstance(m, dict) and {'census_date', 'readout_date', 'qubits', 'couplers'} <= set(m)
        for q in cal.qubits:
            mq = cal.measured_qubit(q['index'])
            assert mq['readout_status'] in ('measured', 'rejected', 'untested')
            if mq['readout_status'] == 'measured':
                assert 0 <= mq['readout_fidelity_0'] <= 1 and 0 <= mq['readout_fidelity_1'] <= 1
                measured_somewhere = True
            else:
                assert mq['readout_fidelity_0'] is None and mq['readout_fidelity_1'] is None
        for c in cal.couplers:
            census = cal.measured_coupler(*c['qubits'])['census']
            assert census in ('pass', 'edge', 'fail', None) and (m['census_date'] or census is None)
    assert measured_somewhere


def test_noisy_simulation_runs_against_a_calibration(client):
    dev = client.device('Baihua')
    # 已经编译好的物理线路：寄存器宽度等于芯片比特数、只用设备门集（没有 x，用 rx(pi)），compiler='none' 直通
    q = dev.calibration().qubits[0]['index']
    qasm = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[%d];\ncreg c[1];\nrx(pi) q[%d];\nmeasure q[%d] -> c[0];\n' % (
        dev.n_qubits, q, q)
    r = client.submit(qasm, 'Baihua-sim', shots=256, compiler='none').result(timeout=120)
    assert r.backend == 'Baihua-sim' and r.calibration_id and sum(r.counts.values()) == 256
    assert client.calibration(r.calibration_id).chip == 'Baihua'
    assert [m['physical_qubit'] for m in r.measurements] == [q]


def test_single_classical_register_on_noisy_but_not_on_ideal_sim(client):
    with pytest.raises(PrecheckError) as e:
        client.submit(TWO_CREGS, 'Baihua-sim', shots=64)
    assert e.value.category == 'precheck.multipleClassicalRegisters' and e.value.vars['n_cregs'] == 2
    assert client.submit(TWO_CREGS, 'sim', shots=64).result(timeout=60).counts == {'01': 64}


# ── G5 统计 ─────────────────────────────────────────────────────────

def test_stats(client):
    client.submit(ONE, 'sim', shots=8).wait(timeout=60)
    s = client.stats(days=7)
    assert s['quota']['sim']['used'] >= 1 and 'limit' in s['quota']['real']
    # 每日两档额度的读数：正常额度、硬上限、已用、剩余、是否降级、下次重置（北京时间 23:00）
    for kind in ('sim', 'noisy', 'real'):
        q = s['quota'][kind]
        assert {'used', 'limit', 'hard_limit', 'remaining', 'degraded', 'resets_at'} <= set(q)
        assert q['hard_limit'] >= q['limit'] and q['degraded'] is (q['used'] >= q['limit'])
        assert q['resets_at'][11:16] == '23:00'
    d = next(iter(s['durations'].values()))
    assert {'median_observed_execution_s', 'n_observed_execution'} <= set(d)


# ── G3 Qiskit 适配 ──────────────────────────────────────────────────

def test_qiskit_backend_on_sim(client):
    pytest.importorskip('qiskit')
    from qiskit import QuantumCircuit
    from quafu.qiskit import QuafuProvider
    provider = QuafuProvider(client=client)
    assert {'sim', 'Baihua', 'Baihua-sim'} <= {b.name for b in provider.backends()}
    be = provider.get_backend('sim')
    qc = QuantumCircuit(2, 2)
    qc.x(0)
    qc.measure([0, 1], [0, 1])
    job = be.run(qc, shots=100)
    assert job.result(timeout=60).get_counts() == {'01': 100}
    assert job.status().name == 'DONE'


def test_qiskit_run_many_circuits_as_one_collection_job(client, transport):
    pytest.importorskip('qiskit')
    from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
    from quafu.qiskit import QuafuProvider
    qc1 = QuantumCircuit(2, 2)
    qc1.x(0)
    qc1.measure([0, 1], [0, 1])
    a, b = ClassicalRegister(1, 'a'), ClassicalRegister(1, 'b')
    qc2 = QuantumCircuit(QuantumRegister(2, 'q'), a, b)
    qc2.x(1)
    qc2.measure(0, a[0])
    qc2.measure(1, b[0])
    job = QuafuProvider(client=client).get_backend('sim').run([qc1, qc2], shots=100)
    assert len(transport.posts('/jobs')) == 1
    res = job.result(timeout=60)
    assert res.success is True and res.get_counts(0) == {'01': 100} and res.get_counts(1) == {'1 0': 100}
    assert job.status().name == 'DONE'


def test_qiskit_sweep_submits_a_collection_with_qiskit_names(client, transport):
    pytest.importorskip('qiskit')
    from qiskit import QuantumCircuit
    from qiskit.circuit import Parameter, ParameterVector
    from quafu.qiskit import sweep
    theta, vec = Parameter('θ'), ParameterVector('phi', 2)
    qc = QuantumCircuit(6, 1)
    qc.rx(theta, 5)
    qc.ry(vec[0], 5)
    qc.rz(vec[1], 5)
    qc.measure(5, 0)
    names = [p.name for p in qc.parameters]
    job = sweep(qc, [[0.1, 0.2, 0.3], [1.0, 2.0, 3.0]], 'sim', name='扫', client=client)
    body = transport.posts('/jobs')[0]['body']
    assert body['mode'] == 'collection' and [p['name'] for p in body['parameters']] == names
    assert all(p['unit'] == 'rad' for p in body['parameters'])
    t = job.table(timeout=60)
    assert t.complete and t.parameter_names == names and t.column(names[0]) == [0.1, 1.0]


def test_qiskit_chip_backend_target_uses_the_served_topology(client):
    pytest.importorskip('qiskit')
    from quafu.qiskit import QuafuProvider
    be = QuafuProvider(client=client).get_backend('Baihua-sim')
    assert be.target.num_qubits > 1 and be.target.build_coupling_map().get_edges()


# ── 九鼎模拟（<真机名>-sim-jiuding）────────────────────────────────

def test_jiuding_simulators_are_listed_and_refuse_while_offline(client, transport):
    jd = [d for d in client.devices() if d['name'].endswith('-sim-jiuding')]
    assert [d['name'] for d in jd] == ['Baihua-sim-jiuding', 'Shenglian-sim-jiuding', 'Dongling-sim-jiuding']
    real = {d['name']: d for d in client.devices() if d['kind'] == 'real'}
    for d in jd:
        chip = d['name'][:-len('-sim-jiuding')]
        assert d['kind'] == 'sim' and d['status'] == 'offline' and d['max_qubits'] == 30
        assert d['n_qubits'] == real[chip]['n_qubits']
    md = client.metadata('Baihua-sim-jiuding')
    assert md['simulator'] is True and md['noise'] == 'none' and md['max_qubits'] == 30 and md['coupling_map']
    with pytest.raises(quafu.DeviceUnavailable) as e:
        client.submit(BELL, target='Baihua-sim-jiuding', shots=16)
    assert e.value.vars['device_status'] == 'offline' and 'Baihua-sim-jiuding' in str(e.value)


def test_jiuding_simulator_backend_builds_a_chip_target(client):
    pytest.importorskip('qiskit')
    from quafu.qiskit import QuafuProvider
    be = QuafuProvider(client=client).get_backend('Dongling-sim-jiuding')
    md = client.metadata('Dongling-sim-jiuding')
    assert be.target.num_qubits == md['n_qubits']
    assert set(be.target.build_coupling_map().get_edges()) >= {tuple(e) for e in md['coupling_map'][:3]}


# ── 资源上限 limits：唯一来源是平台的 metadata ────────────────────────

def test_every_target_carries_the_same_limits_as_its_metadata(client):
    for d in client.devices():
        if d['name'].startswith('all-'):
            continue
        assert d['limits'] == client.metadata(d['name'])['limits'], d['name']
        assert {'max_qubits', 'qubit_count', 'min_shots', 'max_shots', 'shots_step'} <= set(d['limits'])


def test_over_limit_submissions_are_stopped_locally_with_the_platform_numbers(client, transport):
    lim = client.metadata('sim')['limits']
    n = lim['max_qubits'] + 1
    wide = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[%d];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];\n' % n
    before = len(transport.posts('/jobs'))
    with pytest.raises(quafu.PrecheckError) as e:
        client.submit(wide, target='sim', shots=16)
    assert e.value.vars['local'] is True and e.value.vars['limit_qubits'] == lim['max_qubits']
    assert e.value.vars['limits_url'].endswith('/api/v1/backends/sim/metadata')
    with pytest.raises(quafu.PrecheckError) as e:
        client.submit(BELL, target='sim', shots=lim['max_shots'] + 1)
    assert e.value.category == 'precheck.shotsOutOfRange' and e.value.vars['local'] is True
    assert len(transport.posts('/jobs')) == before                 # 本地拦下，没发提交
