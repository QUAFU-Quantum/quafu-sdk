# -*- coding: utf-8 -*-
"""提交前按目标的 limits 本地检查：上限只从平台的 GET /backends/<target>/metadata 读，包里不另写数字。

用假 metadata 给出各种 limits，SDK 按那个数拒或放；取不到 limits 时不查、照常提交。
最后一条是守卫：src/quafu/ 里不得写死比特数或 shots 的上限。"""
import pathlib
import re

import pytest

import quafu
from quafu import _limits
from quafu.errors import PrecheckError

from ..helpers import BELL, JID, KEY, accepted, dispatcher_error


def limits(**kw):
    d = {'max_qubits': None, 'qubit_count': 'declared', 'guest_max_qubits': None, 'min_shots': 1, 'max_shots': 100,
         'shots_step': 1, 'guest_max_shots': None, 'max_depth': None, 'wall_s': None, 'max_tasks_per_job': 50,
         'method': 'statevector'}
    d.update(kw)
    return d


def md(target='sim', **kw):
    return (200, {'name': target, 'n_qubits': 99, 'limits': limits(**kw)})


def qasm(n, used=()):
    """声明 n 个比特，只在 used 上放门。"""
    gates = ''.join('x q[%d];\n' % i for i in used)
    return 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[%d];\ncreg c[%d];\n%s' % (n, n, gates)


@pytest.fixture
def c(make_client):
    return make_client()


# ── 比特数 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('limit, n, ok', [(3, 3, True), (3, 4, False), (7, 7, True), (7, 8, False)])
def test_declared_width_is_checked_against_the_published_limit(fake, c, limit, n, ok):
    fake.route('GET', '/backends/sim/metadata', md(max_qubits=limit))
    fake.route('POST', '/jobs', accepted())
    if ok:
        c.submit(qasm(n), 'sim', shots=10)
        assert len(fake.posts('/jobs')) == 1
        return
    with pytest.raises(PrecheckError) as e:
        c.submit(qasm(n), 'sim', shots=10)
    assert not fake.posts('/jobs')                       # 本地拦下，不发提交
    v = e.value.vars
    assert e.value.category == 'precheck.simTooLarge' and v['local'] is True
    assert v['n_qubits'] == n and v['limit_qubits'] == limit
    assert v['limits_url'] == 'https://quafu.test/api/v1/backends/sim/metadata'
    assert str(limit) in str(e.value) and v['limits_url'] in str(e.value)


def test_active_count_uses_qubits_touched_by_gates(fake, c):
    fake.route('GET', '/backends/Dongling-sim/metadata', md('Dongling-sim', max_qubits=2, qubit_count='active'))
    fake.route('POST', '/jobs', accepted())
    c.submit(qasm(80, used=(5, 70)), 'Dongling-sim', shots=10)      # 声明 80 个，只碰两个：放行
    with pytest.raises(PrecheckError) as e:
        c.submit(qasm(80, used=(5, 6, 70)), 'Dongling-sim', shots=10)
    assert e.value.vars['n_qubits'] == 3 and e.value.vars['qubit_count'] == 'active'
    assert len(fake.posts('/jobs')) == 1


def test_active_count_ignores_barrier_and_counts_whole_register_and_measure(fake, c):
    assert _limits.count_qubits(qasm(5, used=(1,)) + 'barrier q;\nmeasure q[3] -> c[3];\n') == (5, 2)
    assert _limits.count_qubits(qasm(4) + 'h q;\n') == (4, 4)
    two = 'OPENQASM 2.0;\nqreg a[2];\nqreg b[3];\ngate g(t) x, y { cx x, y; rz(t) y; }\ng(2*(-0.5)) a[0], b[2];\n'
    assert _limits.count_qubits(two) == (5, 2)
    assert _limits.count_qubits('u3({{theta}}, 0, pi/2) q[0];') is None          # 没有 qreg：数不出来
    assert _limits.count_qubits('OPENQASM 2.0;\nqreg q[2];\nfoo q[7];\n') is None


def test_unparsable_circuit_is_left_to_the_platform(fake, c):
    fake.route('GET', '/backends/sim/metadata', md(max_qubits=1))
    fake.route('POST', '/jobs', accepted())
    c.submit('OPENQASM 2.0;\nqreg q[3];\nweird{ q[0] };\n', 'sim', shots=10)
    assert len(fake.posts('/jobs')) == 1


# ── shots ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('lo, hi, step, shots, category', [
    (1, 100, 1, 100, None), (1, 100, 1, 101, 'precheck.shotsOutOfRange'), (5, 100, 1, 4, 'precheck.shotsOutOfRange'),
    (300, 2400, 300, 900, None), (300, 2400, 300, 1000, 'precheck.shotsGranularity'),
    (300, 2400, 300, 2700, 'precheck.shotsOutOfRange')])
def test_shots_follow_min_max_and_step(fake, c, lo, hi, step, shots, category):
    fake.route('GET', '/backends/Chip/metadata', md('Chip', min_shots=lo, max_shots=hi, shots_step=step))
    fake.route('POST', '/jobs', accepted())
    if category is None:
        c.submit(BELL, 'Chip', shots=shots)
        assert fake.posts('/jobs')[0]['body']['shots'] == shots
        return
    with pytest.raises(PrecheckError) as e:
        c.submit(BELL, 'Chip', shots=shots)
    assert e.value.category == category and not fake.posts('/jobs')
    assert str(hi if category.endswith('Range') else step) in str(e.value)


def test_per_circuit_shots_are_checked_and_named(fake, c, monkeypatch):
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    fake.route('GET', '/backends/sim/metadata', md(max_shots=50))
    with pytest.raises(PrecheckError) as e:
        c.submit([BELL, {'qasm': BELL, 'shots': 60}], 'sim', shots=10)
    assert '第 1 条线路' in str(e.value) and '50' in str(e.value)


# ── 其余提交入口 ───────────────────────────────────────────────────

TEMPLATE = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[3];\ncreg c[3];\nrx({{t}}) q[0];\n'


def test_sweep_and_open_job_check_shots_and_template_width(fake, c):
    fake.route('GET', '/backends/sim/metadata', md(max_qubits=2, max_shots=50))
    with pytest.raises(PrecheckError):
        c.sweep(TEMPLATE, [('t', 'rad')], [[0.1]], 'sim', shots=10)              # 模板声明 3 个比特
    with pytest.raises(PrecheckError):
        c.open_job('sim', shots=60)
    assert not fake.posts()


def test_append_checks_circuits_against_the_job_target(fake, c):
    fake.route('GET', '/backends/sim/metadata', md(max_qubits=2))
    fake.route('POST', '/jobs', (202, {'job_id': JID, 'mode': 'iterative', 'status': 'Queued', 'open': True,
                                       'task_ids': [], 'n_tasks': 0}))
    fake.route('POST', '/jobs/%s/tasks' % JID, (202, {'task_ids': [JID + '-0']}))
    job = c.open_job('sim', shots=10)
    assert job.target == 'sim'
    job.append(circuits=[qasm(2)])
    with pytest.raises(PrecheckError):
        job.append(circuits=[qasm(3)])
    assert len(fake.posts('/jobs/%s/tasks' % JID)) == 1


# ── 取不到 limits 时交给平台 ───────────────────────────────────────

@pytest.mark.parametrize('resp', [None, (200, {'name': 'sim', 'n_qubits': 24}), (503, {'error': 'x'})])
def test_no_limits_means_no_local_check(fake, c, resp):
    if resp is not None:
        fake.route('GET', '/backends/sim/metadata', resp)      # None：没登记，假传输层回 404
    fake.route('POST', '/jobs', accepted())
    c.submit(qasm(500), 'sim', shots=10 ** 6)
    assert len(fake.posts('/jobs')) == 1


def test_limits_are_cached_per_process(fake, make_client):
    fake.route('GET', '/backends/sim/metadata', md(max_qubits=5))
    fake.route('POST', '/jobs', accepted())
    make_client().submit(BELL, 'sim', shots=10)
    make_client().submit(BELL, 'sim', shots=10)
    assert fake.paths().count('/backends/sim/metadata') == 1


def test_not_logged_in_is_reported_before_fetching_limits(fake, make_client):
    with pytest.raises(quafu.NotLoggedIn):
        quafu.Client().submit(BELL, 'sim')
    assert fake.paths() == []


def test_platform_limit_rejection_shows_the_limits_url(fake, c):
    fake.route('POST', '/jobs', (422, dispatcher_error('precheck.simTooLarge', '理想模拟最多支持 24 个比特',
                                                       n_qubits=30, limit_qubits=24,
                                                       limits_url='/api/v1/backends/sim/metadata')))
    with pytest.raises(PrecheckError) as e:
        c.submit(BELL, 'sim', shots=10)
    assert '/api/v1/backends/sim/metadata' in str(e.value) and 'vars' not in str(e.value)


def test_qiskit_backend_run_is_checked_too(fake, c):
    qiskit = pytest.importorskip('qiskit')
    from quafu.qiskit import QuafuProvider
    fake.route('GET', '/backends/sim/metadata', (200, {'name': 'sim', 'n_qubits': 24, 'basis_gates': [],
                                                       'coupling_map': [], 'simulator': True,
                                                       'limits': limits(max_qubits=2)}))
    be = QuafuProvider(client=c).get_backend('sim')
    qc = qiskit.QuantumCircuit(3, 3)
    qc.h(0)
    qc.measure(range(3), range(3))
    with pytest.raises(PrecheckError):
        be.run(qc, shots=10)
    assert not fake.posts()


# ── 守卫：包里不写死上限 ───────────────────────────────────────────
#
# 上限的唯一来源是平台的 limits。判据（逐行，含注释、文档字符串与文案表）：
#   1. 8192（现行 shots 上限）在包里任何地方出现都算写死——它没有别的正当用途；
#   2. 同一行既有「比特 / qubit / shots / 上限 / limit / 最多 / at most / 整数倍 / multiple」这类词，又有现行或曾经的
#      上限数字（1024、30、24、20、16、12）——先去掉 shots=1024 这种默认值写法（默认值不是上限）；
#   3. 名字像上限的常量（MAX_QUBITS、SHOTS_MAX、SHOTS_STEP、MAX_SHOTS 之类）被赋成数字。

SRC = pathlib.Path(quafu.__file__).resolve().parent
LIMIT_WORDS = re.compile(r'qubit|比特|shots|上限|limit|最多|at most|整数倍|multiple', re.I)
LIMIT_NUMBERS = re.compile(r'(?<![\w.])(1024|30|24|20|16|12)(?![\w.])')
DEFAULT_SHOTS = re.compile(r'shots\s*=\s*1024\b')
LIMIT_CONST = re.compile(r'^\s*[A-Z_]*(MAX_QUBITS|QUBITS_MAX|SHOTS_MAX|MAX_SHOTS|SHOTS_MIN|MIN_SHOTS|SHOTS_STEP)'
                         r'[A-Z_]*\s*=\s*\d')


def offending_lines():
    out = []
    for path in sorted(SRC.rglob('*.py')):
        for no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            bare = DEFAULT_SHOTS.sub('', line)
            if ('8192' in line or LIMIT_CONST.match(line)
                    or (LIMIT_WORDS.search(bare) and LIMIT_NUMBERS.search(bare))):
                out.append('%s:%d: %s' % (path.relative_to(SRC), no, line.strip()))
    return out


def test_package_has_no_hardcoded_resource_limits():
    assert offending_lines() == []


def test_guard_catches_the_old_wording(tmp_path, monkeypatch):
    """守卫自己要能抓到：拿以前写过的说法试一遍。"""
    bad = tmp_path / 'quafu'
    bad.mkdir()
    (bad / 'x.py').write_text('# 真机要求 1024 的整数倍（1024–8192）\nSIM_MAX_QUBITS = 24\n'
                              '"""max_qubits（参与计算的比特上限，现为 30）"""\nok = f(shots=1024)\n', encoding='utf-8')
    monkeypatch.setattr(__import__(__name__, fromlist=['SRC']), 'SRC', bad)
    assert [x.split(':')[1] for x in offending_lines()] == ['1', '2', '3']
