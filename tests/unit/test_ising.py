# -*- coding: utf-8 -*-
"""伊辛问题：本地构造与校验、能量口径、提交体、契约版本门控、本地上限、结果分派、设备目录、错误映射。

平台的响应形状照异构算力统一架构设计稿 §3（契约 0.3.0）：设备目录顶层 ising_devices、POST /jobs 的 problems[]、
任务详情的 program 段与 result.type = "samples"。平台端点还没实现，这里全部用假传输层编排。"""
import itertools
import random
import uuid

import pytest

import quafu
from quafu import ising
from quafu.errors import BadRequest, JobFailed, NotLoggedIn, PrecheckError, ServerUnavailable
from quafu.ising import Problem, Samples

from ..helpers import BELL, JID, KEY, accepted, dispatcher_error, job_status, task_detail

TARGET = 'Ising-1'
HEALTH = (200, {'ok': True, 'version': '0.3.0', 'contract_version': '0.3.0'})
TRIANGLE_J = {(0, 1): 1.0, (1, 2): 1.0, (0, 2): 1.0}
TRIANGLE_PAYLOAD = {'type': 'ising', 'num_variables': 3, 'quadratic': [[0, 1, 1.0], [0, 2, 1.0], [1, 2, 1.0]],
                    'linear': [[0, 0.5]], 'offset': 0.0}


def ising_limits(**kw):
    d = {'max_variables': 1000, 'max_terms': 500500, 'max_problems_per_job': 5, 'method': 'hardware'}
    d.update(kw)
    return d


def ising_md(**kw):
    return (200, {'name': TARGET, 'paradigm': 'ising', 'technology': 'photonic', 'limits': ising_limits(**kw)})


def ising_detail(seq=0, status='Finished', samples=None, ptype='ising', error=None, job_id=JID, result=True):
    """伊辛任务的详情（§3.3、§3.4）：没有 circuit 段，有 program 段；result.type 为 samples。"""
    if samples is None:
        samples = [{'values': [-1, 1, -1], 'energy': -1.5, 'occurrences': 1},
                   {'values': [1, -1, 1], 'energy': -0.5, 'occurrences': 2}]
    res = None
    if status == 'Finished' and result:
        res = {'type': 'samples', 'variable_type': 'spin' if ptype == 'ising' else 'binary', 'samples': samples,
               'best_energy': min(s['energy'] for s in samples) if samples else None,
               'energy_trace': [0.5, -0.5, -1.5], 'device_time_us': 100000}
    return (200, {
        'schema_version': '1', 'included': [], 'task_id': '%s-%d' % (job_id, seq), 'status': status, 'kind': 'real',
        'target': TARGET, 'chip': TARGET, 'name': 'triangle',
        'job': {'job_id': job_id, 'mode': 'single', 'seq': seq, 'n_tasks': 1},
        'program': {'paradigm': 'ising', 'type': ptype, 'num_variables': 3, 'num_terms': 4,
                    'fingerprint': 'sha256:00'},
        'result': res,
        'progress': {'stage': status.lower(), 'stage_at': 't', 'blocker': None, 'detail': None},
        'error': error if status == 'Failed' else {'category': None, 'stage': None, 'detail': None,
                                                   'retryable': None, 'vars': None}})


@pytest.fixture(autouse=True)
def fresh_contract_cache():
    ising.clear_cache()
    yield
    ising.clear_cache()


@pytest.fixture
def c(make_client):
    return make_client()


@pytest.fixture
def platform(fake):
    """一个 0.3.0 的平台：healthz、伊辛机的 metadata 与受理都已登记。"""
    fake.route('GET', '/healthz', HEALTH)
    fake.route('GET', '/backends/%s/metadata' % TARGET, ising_md())
    fake.route('POST', '/jobs', accepted())
    return fake


def brute_energy(kind, n, matrix_terms, h=(), offset=0.0):
    """§3.2 的定义逐字照算：每一项只算一次，对角项也照乘（x·x、s·s），不做任何合并。"""
    domain = (-1, 1) if kind == 'ising' else (0, 1)
    for v in itertools.product(domain, repeat=n):
        e = offset + sum(w * v[i] for i, w in h) + sum(w * v[i] * v[j] for i, j, w in matrix_terms)
        yield list(v), e


# ── 三种输入形状 → 同一份 payload ───────────────────────────────────

def test_dict_dense_list_and_terms_give_the_same_payload():
    dense = [[0, 0.5, 0.25], [0.5, 0, 1.0], [0.75, 0, 0]]        # 不对称也行：(i, j) 与 (j, i) 是同一项
    shapes = [Problem.from_ising(TRIANGLE_J, h=[0.5, 0, 0]),
              Problem.from_ising(dense, h={0: 0.5}),
              Problem.from_ising({(1, 0): 0.25, (0, 1): 0.75, (2, 1): 1.0, (0, 2): 1.0}, h=[[0, 0.5]]),
              Problem.from_terms('ising', 3, [(0, 1, 1.0), (1, 2, 1.0), (2, 0, 1.0)], [(0, 0.5)]),
              Problem.from_terms('ising', 3, {(0, 1): 1.0, (1, 2): 1.0, (0, 2): 1.0}, [0.5, 0, 0])]
    assert all(p.to_payload() == TRIANGLE_PAYLOAD for p in shapes)
    assert repr(shapes[0]) == "Problem(type='ising', num_variables=3, num_terms=4)"


def test_numpy_arrays_and_tolist_objects_are_accepted_without_importing_numpy_in_the_package():
    np = pytest.importorskip('numpy')
    a = Problem.from_ising(np.array([[0, 1.0, 1.0], [0, 0, 1.0], [0, 0, 0]]), h=np.array([0.5, 0, 0]))
    assert a.to_payload() == TRIANGLE_PAYLOAD
    q = Problem.from_qubo(np.array([[1, 2], [0, -3]]), offset=1)
    for v in itertools.product((0, 1), repeat=2):
        x = np.array(v)
        assert q.energy(np.array(v)) == pytest.approx(1 + x @ np.array([[1, 2], [0, -3]]) @ x)
    dict_keys = Problem.from_qubo({(np.int64(0), np.int64(1)): np.float64(2.0)})
    assert dict_keys.to_payload()['quadratic'] == [[0, 1, 2.0]]


def test_terms_given_as_a_float_array_of_triples_take_integral_indices():
    p = Problem.from_terms('qubo', 2, [[0.0, 1.0, 3.0]])
    assert p.quadratic == [(0, 1, 3.0)]
    with pytest.raises(TypeError):
        Problem.from_terms('qubo', 2, [[0.5, 1, 3.0]])


def test_payload_lists_only_non_zero_terms_and_folds_repeats():
    p = Problem.from_terms('qubo', 4, [(0, 1, 1.0), (1, 0, -1.0), (2, 3, 0.5), (2, 3, 0.25), (3, 2, 0.25)],
                           [(1, 0.0), (2, 1.0), (2, 1.0)], offset=2)
    assert p.to_payload() == {'type': 'qubo', 'num_variables': 4, 'quadratic': [[2, 3, 1.0]], 'linear': [[2, 2.0]],
                              'offset': 2.0}
    assert p.num_terms == 2 and p.variable_type == 'binary'
    named = Problem.from_qubo([[1]], name='one')
    assert named.to_payload()['name'] == 'one' and 'name' not in p.to_payload()


# ── 能量口径（§3.2） ─────────────────────────────────────────────────

def test_qubo_diagonal_is_a_linear_term_and_ising_diagonal_is_a_constant():
    q = Problem.from_qubo([[3, 0], [0, -2]])
    assert q.linear == [(0, 3.0), (1, -2.0)] and q.quadratic == [] and q.offset == 0.0
    s = Problem.from_ising([[3, 0], [0, -2]], h=[1, 0])
    assert s.linear == [(0, 1.0)] and s.quadratic == [] and s.offset == 1.0


@pytest.mark.parametrize('kind', ['ising', 'qubo'])
def test_energy_matches_the_definition_term_by_term_for_every_assignment(kind):
    rnd = random.Random(7)
    n = 4
    dense = [[rnd.choice([0, 0, rnd.uniform(-2, 2)]) for _ in range(n)] for _ in range(n)]
    extra = [(0, 1, 0.5), (1, 0, 0.5), (2, 2, -1.25), (3, 1, 2.0)]       # 重复项、反序项、对角项
    h = [(0, 0.75), (2, -0.5), (2, 0.25)]
    as_terms = [(i, j, w) for i in range(n) for j in range(n) for w in [dense[i][j]] if w] + extra
    q = {}
    for i, j, w in as_terms:
        q[(i, j)] = q.get((i, j), 0.0) + w
    if kind == 'ising':
        p = Problem.from_ising(q, h=dict((i, sum(w for k, w in h if k == i)) for i, _ in h), offset=1.5,
                               num_variables=n)
    else:
        p = Problem.from_terms('qubo', n, as_terms, h, offset=1.5)
    for v, e in brute_energy(kind, n, as_terms, h, 1.5):
        assert p.energy(v) == pytest.approx(e, abs=1e-12), v


def test_energy_of_the_contract_example():
    p = Problem.from_terms('ising', 3, [[0, 1, 1.0], [1, 2, 1.0], [0, 2, 1.0]], [[0, 0.5]])
    assert p.energy([-1, 1, -1]) == -1.5 and p.energy([1, -1, 1]) == -0.5


def test_energy_rejects_wrong_length_or_values_outside_the_domain():
    p = Problem.from_ising(TRIANGLE_J)
    with pytest.raises(ValueError):
        p.energy([1, 1])
    with pytest.raises(ValueError):
        p.energy([0, 1, 1])                     # 自旋只取 ±1
    with pytest.raises(ValueError):
        Problem.from_qubo(TRIANGLE_J).energy([-1, 0, 1])
    assert Problem.from_qubo(TRIANGLE_J).energy([True, True, False]) == 1.0


# ── 本地校验 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('build, exc', [
    (lambda: Problem.from_qubo([[0, 1], [1]]), ValueError),                         # 不是方阵
    (lambda: Problem.from_qubo([1, 2]), TypeError),                                 # 一维
    (lambda: Problem.from_qubo([]), ValueError),                                    # 0 个变量
    (lambda: Problem.from_qubo({}), ValueError),
    (lambda: Problem.from_qubo({(0, 1): float('nan')}), ValueError),
    (lambda: Problem.from_qubo({(0, 1): float('inf')}), ValueError),
    (lambda: Problem.from_qubo([[0, float('-inf')], [0, 0]]), ValueError),
    (lambda: Problem.from_qubo({(0, 1): '1.5'}), TypeError),                       # 字符串不当数
    (lambda: Problem.from_qubo({(0, 1): True}), TypeError),
    (lambda: Problem.from_qubo({(0, 1): None}), TypeError),
    (lambda: Problem.from_qubo({0: 1.0}), TypeError),                              # 键不是 (i, j)
    (lambda: Problem.from_qubo({(0, 1, 2): 1.0}), TypeError),
    (lambda: Problem.from_qubo({(0, True): 1.0}), TypeError),
    (lambda: Problem.from_qubo({(-1, 1): 1.0}), ValueError),                       # 下标为负
    (lambda: Problem.from_qubo({(0, 5): 1.0}, num_variables=3), ValueError),       # 下标越界
    (lambda: Problem.from_qubo({(0, 1): 1.0}, num_variables=0), ValueError),
    (lambda: Problem.from_qubo({(0, 1): 1.0}, num_variables=2.5), TypeError),
    (lambda: Problem.from_qubo('Q'), TypeError),
    (lambda: Problem.from_ising([[0, 1], [1, 0]], h=[1, 2, 3]), ValueError),        # J 与 h 的变量数不一致
    (lambda: Problem.from_ising([[0, 1], [1, 0]], h={2: 1.0}), ValueError),
    (lambda: Problem.from_ising(TRIANGLE_J, h=[float('nan'), 0, 0]), ValueError),
    (lambda: Problem.from_ising(TRIANGLE_J, h='h'), TypeError),
    (lambda: Problem.from_ising(TRIANGLE_J, offset=float('nan')), ValueError),
    (lambda: Problem.from_terms('maxcut', 2, [(0, 1, 1.0)]), ValueError),
    (lambda: Problem.from_terms('qubo', 2, [(0, 1)]), TypeError),                  # 三元组少一项
    (lambda: Problem.from_terms('qubo', 2, 5), TypeError),
    (lambda: Problem.from_terms('qubo', 2, [(0, 2, 1.0)]), ValueError),
    (lambda: Problem.from_terms('qubo', 2, [], [(3, 1.0)]), ValueError),
    (lambda: Problem.from_qubo([[1]], name=5), TypeError),
])
def test_invalid_problems_are_rejected_locally(build, exc):
    with pytest.raises(exc):
        build()


def test_messages_name_the_offending_entry(monkeypatch):
    with pytest.raises(ValueError) as e:
        Problem.from_qubo([[0, 1], [float('nan'), 0]])
    assert 'Q[1][0]' in str(e.value)
    with pytest.raises(ValueError) as e:
        Problem.from_qubo({(0, 7): 1.0}, num_variables=3)
    assert '7' in str(e.value) and '0..2' in str(e.value)
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    with pytest.raises(ValueError) as e:
        Problem.from_qubo([[0, 1], [1]])
    assert '方阵' in str(e.value)


def test_invalid_inputs_send_nothing(fake, c):
    with pytest.raises(ValueError):
        c.solve_qubo({(0, 1): float('nan')}, TARGET)
    with pytest.raises(BadRequest):
        c.solve_ising(TRIANGLE_J)                                  # 没给 target
    with pytest.raises(ValueError):
        c.submit_problems([], TARGET)
    with pytest.raises(TypeError):
        c.submit_problems([TRIANGLE_PAYLOAD], TARGET)              # 要 Problem，不收裸 dict
    assert fake.calls == []


# ── 提交体（§3.2） ───────────────────────────────────────────────────

def test_solve_ising_posts_problems_without_shots_or_circuit_level(platform, c):
    job = c.solve_ising(TRIANGLE_J, h=[0.5, 0, 0], target=TARGET, name='maxcut-demo')
    post = platform.posts('/jobs')[0]
    body = post['body']
    assert set(body) == {'mode', 'target', 'problems', 'name', 'client_ref'}
    assert body['mode'] == 'single' and body['target'] == TARGET and body['name'] == 'maxcut-demo'
    assert body['problems'] == [TRIANGLE_PAYLOAD] and uuid.UUID(body['client_ref']).version == 4
    assert post['headers']['Authorization'] == 'Bearer ' + KEY
    assert (job.id, job.n_tasks, job.paradigm, job.target) == (JID, 1, 'ising', TARGET)
    assert platform.paths() == ['/healthz', '/backends/%s/metadata' % TARGET, '/jobs']


def test_solve_qubo_and_top_level_functions(platform, monkeypatch):
    monkeypatch.setenv('QUAFU_API_KEY', KEY)
    quafu.solve_qubo([[1, 2], [0, -3]], TARGET, offset=1)
    quafu.solve_ising([[0, 1], [1, 0]], None, TARGET)
    quafu.submit_problems(Problem.from_qubo([[1]]), TARGET)
    bodies = [p['body'] for p in platform.posts('/jobs')]
    assert bodies[0]['problems'] == [{'type': 'qubo', 'num_variables': 2, 'quadratic': [[0, 1, 2.0]],
                                      'linear': [[0, 1.0], [1, -3.0]], 'offset': 1.0}]
    assert bodies[1]['problems'][0]['quadratic'] == [[0, 1, 2.0]] and bodies[1]['problems'][0]['type'] == 'ising'
    assert [b['mode'] for b in bodies] == ['single', 'single', 'single']
    assert all('shots' not in b and 'circuit_level' not in b and 'name' not in b for b in bodies)


def test_a_list_of_problems_is_one_collection_in_order(platform, c):
    platform.route('POST', '/jobs', accepted(3, 'collection'))
    ps = [Problem.from_qubo([[i + 1]], name='p%d' % i) for i in range(3)]
    job = c.submit_problems(ps, TARGET)
    body = platform.posts('/jobs')[0]['body']
    assert body['mode'] == 'collection' and [p['name'] for p in body['problems']] == ['p0', 'p1', 'p2']
    assert job.n_tasks == 3 and job.paradigm == 'ising'


def test_not_logged_in_is_reported_before_any_request(fake):
    with pytest.raises(NotLoggedIn):
        quafu.Client().solve_ising(TRIANGLE_J, target=TARGET)
    assert fake.calls == []


# ── 契约版本门控（§3.5） ─────────────────────────────────────────────

@pytest.mark.parametrize('health', [
    (200, {'ok': True, 'version': '0.2.0', 'contract_version': '0.2.0'}),
    (200, {'ok': True}),                                        # 没报 contract_version
    (200, {'ok': True, 'contract_version': 'dev'}),
    (404, {'detail': 'Not Found'}),                             # 连 /v1/healthz 都没有
])
def test_older_platform_is_refused_locally_without_submitting(fake, c, health):
    fake.route('GET', '/healthz', health)
    fake.route('POST', '/jobs', accepted())
    with pytest.raises(ServerUnavailable) as e:
        c.solve_ising(TRIANGLE_J, target=TARGET)
    assert e.value.sent is False and not fake.posts('/jobs')
    assert '0.3.0' in str(e.value) and 'https://quafu.test' in str(e.value)
    if health[0] == 200 and health[1].get('contract_version') == '0.2.0':
        assert '0.2.0' in str(e.value)


def test_older_platform_message_in_chinese(fake, c, monkeypatch):
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    fake.route('GET', '/healthz', (200, {'contract_version': '0.2.0'}))
    with pytest.raises(ServerUnavailable) as e:
        c.solve_ising(TRIANGLE_J, target=TARGET)
    assert '还不收伊辛问题' in str(e.value) and '0.2.0' in str(e.value)


@pytest.mark.parametrize('v', ['0.3.0', '0.3.1', '0.4.0', '1.0.0', '0.10'])
def test_newer_contract_versions_pass(platform, c, v):
    platform.route('GET', '/healthz', (200, {'contract_version': v}))
    c.solve_ising(TRIANGLE_J, target=TARGET)
    assert len(platform.posts('/jobs')) == 1


def test_contract_version_is_fetched_once_per_platform(platform, c):
    for _ in range(3):
        c.solve_ising(TRIANGLE_J, target=TARGET)
    assert platform.paths().count('/healthz') == 1 and len(platform.posts('/jobs')) == 3
    assert platform.calls[0]['headers'].get('Authorization') is None       # healthz 是公开端点，不带凭证


def test_an_old_platform_is_asked_again_after_a_short_while(fake, c, monkeypatch):
    class Clock(object):
        now = 0.0

        def monotonic(self):
            return self.now
    clock = Clock()
    monkeypatch.setattr(ising, 'time', clock)
    fake.route('GET', '/healthz', (200, {'contract_version': '0.2.0'}), HEALTH)
    fake.route('GET', '/backends/%s/metadata' % TARGET, ising_md())
    fake.route('POST', '/jobs', accepted())
    with pytest.raises(ServerUnavailable):
        c.solve_ising(TRIANGLE_J, target=TARGET)
    with pytest.raises(ServerUnavailable):
        c.solve_ising(TRIANGLE_J, target=TARGET)              # 还在短缓存里：不再问
    assert fake.paths().count('/healthz') == 1
    clock.now = ising.RECHECK_S + 1
    c.solve_ising(TRIANGLE_J, target=TARGET)                  # 平台升级了
    assert fake.paths().count('/healthz') == 2 and len(fake.posts('/jobs')) == 1


# ── 本地上限（GET /backends/{target}/metadata 的 limits） ───────────

def test_too_many_variables_is_refused_locally(platform, c):
    platform.route('GET', '/backends/%s/metadata' % TARGET, ising_md(max_variables=3))
    c.solve_ising(TRIANGLE_J, target=TARGET)                  # 恰好 3 个：放行
    with pytest.raises(PrecheckError) as e:
        c.solve_qubo({(0, 3): 1.0}, TARGET)
    assert len(platform.posts('/jobs')) == 1
    v = e.value.vars
    assert e.value.category == 'precheck.problemInvalid' and v['local'] is True
    assert (v['num_variables'], v['max_variables']) == (4, 3)
    assert v['limits_url'] == 'https://quafu.test/api/v1/backends/%s/metadata' % TARGET
    assert v['limits_url'] in str(e.value)


def test_too_many_terms_is_counted_after_merging(platform, c):
    platform.route('GET', '/backends/%s/metadata' % TARGET, ising_md(max_terms=3))
    full = [[1.0] * 3 for _ in range(3)]                       # 9 个非零元 → 合并后 3 个二次项、对角并成常数
    c.solve_ising(full, target=TARGET)
    with pytest.raises(PrecheckError) as e:
        c.solve_ising(full, h=[1, 0, 0], target=TARGET)          # 3 + 1 = 4 项
    assert e.value.category == 'precheck.problemTooLarge'
    assert (e.value.vars['num_terms'], e.value.vars['max_terms']) == (4, 3)
    assert len(platform.posts('/jobs')) == 1


def test_too_many_problems_per_job_is_refused_locally(platform, c):
    platform.route('GET', '/backends/%s/metadata' % TARGET, ising_md(max_problems_per_job=2))
    with pytest.raises(PrecheckError) as e:
        c.submit_problems([Problem.from_qubo([[1]])] * 3, TARGET)
    assert e.value.category == 'precheck.problemTooLarge' and e.value.vars['n_problems'] == 3
    assert not platform.posts('/jobs')


def test_which_problem_is_too_large_is_named(platform, c):
    platform.route('GET', '/backends/%s/metadata' % TARGET, ising_md(max_variables=2))
    with pytest.raises(PrecheckError) as e:
        c.submit_problems([Problem.from_qubo([[1]]), Problem.from_qubo([[1] * 3] * 3)], TARGET)
    assert e.value.vars['task_index'] == 1 and '#1' in str(e.value)


def test_unreadable_limits_leave_the_decision_to_the_platform(fake, c):
    fake.route('GET', '/healthz', HEALTH)
    fake.route('GET', '/backends/%s/metadata' % TARGET, (503, {'error': 'x', 'code': 'runtime.unavailable'}))
    fake.route('POST', '/jobs', accepted())
    c.solve_qubo([[1] * 5] * 5, TARGET)
    assert len(fake.posts('/jobs')) == 1


# ── 结果分派（§3.4） ─────────────────────────────────────────────────

def test_result_of_an_ising_job_is_samples(platform, c, clock):
    platform.route('GET', '/jobs/%s/status' % JID, job_status('Running', running=1), job_status('Finished', finished=1))
    platform.route('GET', '/jobs/%s/tasks/0' % JID, ising_detail())
    job = c.solve_ising(TRIANGLE_J, h=[0.5, 0, 0], target=TARGET)
    r = job.result()
    assert isinstance(r, Samples) and r.ok and r.status == 'Finished'
    assert r.best == ([-1, 1, -1], -1.5, 1) and r.best.values == [-1, 1, -1] and r.best.energy == -1.5
    assert [s.occurrences for s in r.samples] == [1, 2] and r.energies == [-1.5, -0.5]
    assert r.energy_trace == [0.5, -0.5, -1.5] and r.device_time_us == 100000
    assert r.variable_type == 'spin' and r.problem_type == 'ising' and r.num_variables == 3
    assert r.task_id == JID + '-0' and r.name == 'triangle' and r.target == TARGET and r.raw['program']
    assert repr(r) == "Samples(task_id='%s-0', best_energy=-1.5, n_samples=2)" % JID
    assert '/jobs/%s/tasks/0' % JID in platform.paths()
    assert not [p for p in platform.paths() if 'include=' in p]          # 伊辛任务不要 counts、executed


def test_platform_energies_agree_with_problem_energy(platform, c, clock):
    platform.route('GET', '/jobs/%s/status' % JID, job_status('Finished', finished=1))
    platform.route('GET', '/jobs/%s/tasks/0' % JID, ising_detail())
    p = Problem.from_ising(TRIANGLE_J, h=[0.5, 0, 0])
    r = c.submit_problems(p, TARGET).result()
    assert all(p.energy(s.values) == s.energy for s in r.samples)


def test_best_is_the_lowest_energy_even_if_unsorted_and_values_come_back_as_ints(platform, c, clock):
    rows = [{'values': [1.0, 0.0], 'energy': 2.0}, {'values': [0.0, 1.0], 'energy': -3.0, 'occurrences': 4}]
    platform.route('GET', '/jobs/%s/status' % JID, job_status('Finished', finished=1))
    platform.route('GET', '/jobs/%s/tasks/0' % JID, ising_detail(samples=rows, ptype='qubo'))
    r = c.solve_qubo([[1, 0], [0, 1]], TARGET).result()
    assert r.best == ([0, 1], -3.0, 4) and type(r.best.values[0]) is int
    assert r.samples[0].occurrences == 1 and r.variable_type == 'binary'


def test_failed_ising_task_raises_job_failed(platform, c, clock):
    err = {'category': 'runtime.hardwareError', 'stage': 'hardware', 'retryable': True, 'detail': 'machine error',
           'vars': None}
    platform.route('GET', '/jobs/%s/status' % JID, job_status('Failed', failed=1))
    platform.route('GET', '/jobs/%s/tasks/0' % JID, ising_detail(status='Failed', error=err))
    job = c.solve_ising(TRIANGLE_J, target=TARGET)
    with pytest.raises(JobFailed) as e:
        job.result()
    assert e.value.category == 'runtime.hardwareError' and e.value.task_id == JID + '-0'
    r = job.results()[0]
    assert isinstance(r, Samples) and r.samples is None and r.best is None and r.energies is None
    assert repr(r) == "Samples(task_id='%s-0', status='Failed', error='runtime.hardwareError')" % JID


def test_results_of_several_problems_are_aligned(platform, c, clock):
    platform.route('POST', '/jobs', accepted(2, 'collection'))
    platform.route('GET', '/jobs/%s/status' % JID, job_status('Finished', total=2, finished=2))
    platform.route('GET', '/jobs/%s/tasks/0' % JID, ising_detail(0))
    platform.route('GET', '/jobs/%s/tasks/1' % JID, ising_detail(1, samples=[{'values': [1, 1, 1], 'energy': 3.0}]))
    job = c.submit_problems([Problem.from_ising(TRIANGLE_J), Problem.from_ising(TRIANGLE_J)], TARGET)
    rs = job.results()
    assert [r.seq for r in rs] == [0, 1] and [r.best.energy for r in rs] == [-1.5, 3.0]
    with pytest.raises(ValueError) as e:
        job.result()
    assert 'problems' in str(e.value)


def test_a_reattached_ising_job_dispatches_on_the_detail(fake, c, clock):
    """quafu.job(号) 接回时不知道范式：第一次照旧带 include 取，看到 samples 后改不带。"""
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Finished', total=2, finished=1, failed=1))
    fake.route('GET', '/jobs/%s/tasks/0?include=counts,executed' % JID, ising_detail(0))
    fake.route('GET', '/jobs/%s/tasks/1' % JID, ising_detail(1, status='Failed', error={'category': 'x'}))
    job = c.job(JID)
    assert job.paradigm is None
    rs = job.results()
    assert all(isinstance(r, Samples) for r in rs) and job.paradigm == 'ising'
    assert rs[1].status == 'Failed'                      # 失败的伊辛任务没有 result，按 program.paradigm 认


def test_gate_path_is_unchanged(fake, c, clock):
    fake.route('GET', '/backends/sim/metadata', (404, {'detail': 'Not Found'}))
    fake.route('POST', '/jobs', accepted())
    fake.route('GET', '/jobs/%s/status' % JID, job_status('Finished', finished=1))
    status, detail = task_detail()
    detail = dict(detail, program={'paradigm': 'gate'}, result=dict(detail['result'], type='counts'))
    fake.route('GET', '/jobs/%s/tasks/0?include=counts,executed' % JID, (status, detail))
    job = c.submit(BELL, target='sim', shots=100)
    r = job.result()
    assert type(r) is quafu.Result and r.counts == {'00': 60, '11': 40} and job.paradigm is None
    body = fake.posts('/jobs')[0]['body']
    assert 'problems' not in body and body['shots'] == 100
    assert '/healthz' not in fake.paths()                # 门电路提交不查契约版本


def test_a_gate_result_without_type_is_still_a_result():
    assert not ising.is_samples(task_detail()[1])
    assert ising.is_samples(ising_detail()[1]) and ising.is_samples(ising_detail(status='Running')[1])


# ── 设备目录（§3.1） ─────────────────────────────────────────────────

def test_devices_merge_ising_devices_and_mark_every_row_with_its_paradigm(fake):
    lim = ising_limits()
    fake.route('GET', '/devices', (200, {
        'simulator': {'name': 'sim', 'max_qubits': 24, 'status': 'online'},
        'devices': [{'name': 'Dongling', 'status': 'online', 'n_qubits': 84, 'queue': 3, 'simulator_available': True,
                     'technology': 'superconducting', 'paradigm': 'gate'}],
        'simulated_chips': [{'name': 'Dongling-sim-jiuding', 'status': 'standby', 'n_qubits': 84, 'max_qubits': 30}],
        'ising_devices': [{'name': TARGET, 'paradigm': 'ising', 'technology': 'photonic', 'status': 'online',
                           'max_variables': 1000, 'variable_types': ['spin', 'binary'], 'queue': 0, 'limits': lim},
                          {'status': 'online'}, 'garbage'],
        'quantum_annealers': [{'name': 'future'}],          # 不认识的新顶层数组：不崩，也不列
        'fetched_at': 't'}))
    ds = quafu.devices()
    assert [d['name'] for d in ds] == ['sim', 'Dongling', 'Dongling-sim', 'Dongling-sim-jiuding', TARGET]
    assert [d['paradigm'] for d in ds] == ['gate', 'gate', 'gate', 'gate', 'ising']
    assert ds[-1] == {'name': TARGET, 'kind': 'ising', 'paradigm': 'ising', 'status': 'online', 'n_qubits': None,
                      'queue': 0, 'limits': lim, 'technology': 'photonic', 'max_variables': 1000,
                      'variable_types': ['spin', 'binary']}


def test_devices_from_an_older_platform_get_paradigm_gate(fake):
    fake.route('GET', '/devices', (200, {'simulator': {'name': 'sim', 'max_qubits': 24, 'status': 'online'},
                                         'devices': [{'name': 'Baihua', 'status': 'online', 'n_qubits': 156}]}))
    assert [(d['name'], d['kind'], d['paradigm']) for d in quafu.devices()] == [('sim', 'sim', 'gate'),
                                                                               ('Baihua', 'real', 'gate')]


def test_qiskit_provider_does_not_list_ising_machines(fake, make_client):
    pytest.importorskip('qiskit')
    from quafu.qiskit import QuafuProvider
    fake.route('GET', '/devices', (200, {'simulator': {'name': 'sim', 'status': 'online'}, 'devices': [],
                                         'ising_devices': [{'name': TARGET, 'status': 'online'}]}))
    assert [b.name for b in QuafuProvider(client=make_client()).backends()] == ['sim']


# ── 错误映射（§3.2 规则表） ──────────────────────────────────────────

@pytest.mark.parametrize('code, vars_, words', [
    ('job.paradigmMismatch', {}, ['Ising machines', 'paradigm']),
    ('job.problemsConflict', {}, ['not both']),
    ('job.fieldNotApplicable', {'field': 'shots'}, ['shots']),
])
def test_job_shape_rejections_are_bad_requests_with_our_own_text(platform, c, code, vars_, words):
    platform.route('POST', '/jobs', (422, dict(dispatcher_error(code, '平台原文'), vars=vars_)))
    with pytest.raises(BadRequest) as e:
        c.solve_ising(TRIANGLE_J, target=TARGET)
    assert e.value.code == code and e.value.status == 422 and code in str(e.value)
    assert all(w in str(e.value) for w in words) and '平台原文' not in str(e.value)


def test_paradigm_mismatch_in_chinese(platform, c, monkeypatch):
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    platform.route('POST', '/jobs', (422, dispatcher_error('job.paradigmMismatch', 'x')))
    with pytest.raises(BadRequest) as e:
        c.solve_ising(TRIANGLE_J, target=TARGET)
    assert '伊辛机' in str(e.value)


@pytest.mark.parametrize('code', ['precheck.problemInvalid', 'precheck.problemTooLarge'])
def test_problem_prechecks_are_precheck_errors(platform, c, code):
    platform.route('POST', '/jobs', (422, dispatcher_error(code, '第 0 个问题不合规', task_index=0, field='quadratic')))
    with pytest.raises(PrecheckError) as e:
        c.solve_ising(TRIANGLE_J, target=TARGET)
    assert e.value.category == code and e.value.vars['task_index'] == 0 and not e.value.vars.get('local')


def test_the_ising_module_imports_neither_numpy_nor_qiskit():
    import subprocess
    import sys
    from ..helpers import SUBPROCESS_TIMEOUT
    code = ('import sys, quafu, quafu.ising\n'
            'p = quafu.Problem.from_qubo([[1, 2], [0, 3]])\n'
            'bad = [m for m in sys.modules if m.split(".")[0] in ("numpy", "qiskit")]\n'
            'assert not bad, bad\n')
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    assert r.returncode == 0, r.stderr
