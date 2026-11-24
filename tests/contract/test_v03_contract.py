# -*- coding: utf-8 -*-
"""契约测试（契约 0.3.0：伊辛问题，06 号契约 §3.18）：经真 HTTP 对着真任务分发器跑，夹具见 conftest.py。

这里起的任务分发器不配任何伊辛机的凭证，所以 ising_devices 是空表、没有能收伊辛问题的目标。测的是不需要伊辛机就能
对上的那一半：契约版本、设备目录的新列、提交时的拒绝（码、vars 与 SDK 的异常映射）、门电路任务详情与列式结果的新字段。
伊辛机从受理到出解的端到端由平台自己的测试对着假的算力方服务跑；本仓库是公开仓库，不写算力方的配置项与名字。
结果的解析（Samples）在 tests/unit/test_ising.py 里按契约 §3.18 的 JSON 形状测。"""
import pytest

import quafu
from quafu import ising
from quafu.errors import BadRequest, PrecheckError

HEAD = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
BELL = HEAD + 'h q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n'
TRIANGLE = {(0, 1): 1.0, (1, 2): 1.0, (0, 2): 1.0}


@pytest.fixture(autouse=True)
def fresh_contract_cache():
    ising.clear_cache()
    yield
    ising.clear_cache()


def jobs_total(client):
    return client._request('GET', '/jobs?limit=1')['total']


def test_platform_reports_a_contract_that_takes_ising_problems(client):
    v = ising.contract_version(client)
    assert ising._version(v) >= ising.CONTRACT_MIN, v


def test_devices_mark_every_row_and_list_no_ising_machine_without_credentials(client):
    raw = client._request('GET', '/devices', auth=False)
    assert raw['ising_devices'] == []                          # 没配伊辛机：空表，不是缺键
    assert all(row.get('paradigm') == 'gate' and row.get('technology') for row in raw['devices'])
    rows = client.devices()
    assert rows and all(r['paradigm'] == 'gate' for r in rows) and not [r for r in rows if r['kind'] == 'ising']


def test_ising_problems_to_a_gate_device_are_refused_with_what_it_takes(client, transport):
    before = jobs_total(client)
    with pytest.raises(PrecheckError) as e:
        client.solve_ising(TRIANGLE, linear=[0.5, 0, 0], target='sim')
    assert e.value.status == 422 and e.value.category == 'precheck.paradigmMismatch'
    assert e.value.vars == {'device': 'sim', 'paradigm': 'gate'}
    assert 'circuits only' in str(e.value)
    body = transport.posts('/jobs')[0]['body']
    assert set(body) == {'mode', 'target', 'problems', 'client_ref'}           # 不发 shots、circuit_level
    assert jobs_total(client) == before


def test_an_unknown_ising_machine_is_an_unknown_device(client):
    with pytest.raises(PrecheckError) as e:
        client.solve_qubo([[1, 2], [0, -3]], target='NoSuchIsingMachine')
    assert e.value.status == 422 and e.value.category == 'precheck.unknownDevice'
    assert e.value.vars.get('device') == 'NoSuchIsingMachine'


@pytest.mark.parametrize('extra, code, field', [
    ({'shots': 1024}, 'field_not_applicable', 'shots'),
    ({'circuit_level': 'logical'}, 'field_not_applicable', 'circuit_level'),
    ({'circuits': [{'qasm': BELL}]}, 'problems_conflict', 'circuits'),
    ({'mode': 'iterative'}, 'problems_conflict', 'mode'),
])
def test_body_shape_rejections_map_to_bad_request(client, extra, code, field):
    """SDK 自己不会发这几种请求体；直接发，核对平台的码与 vars.field 能被 SDK 的错误映射认出来。"""
    body = dict({'mode': 'single', 'target': 'sim', 'problems': [ising.Problem.from_ising(TRIANGLE).to_payload()]},
                **extra)
    with pytest.raises(BadRequest) as e:
        client._request('POST', '/jobs', body=body, endpoint='job', retry='none')
    assert e.value.status == 422 and e.value.code == code
    assert (e.value.body.get('vars') or {}).get('field') == field and field in str(e.value)


def test_circuits_still_run_and_gate_details_carry_the_new_fields(client):
    job = client.submit(BELL, target='sim', shots=256)
    r = job.result(timeout=120)
    assert type(r) is quafu.Result and r.counts and job.paradigm is None
    assert r.raw['program'] == {'paradigm': 'gate'} and r.raw['result']['type'] == 'counts'
    assert not ising.is_samples(r.raw)
    cols = client._request('GET', '/jobs/%s/results?fields=counts,samples' % job.id)
    assert cols['samples'] == [None] and cols['problem_type'] == [None]
    t = job.table()
    assert t.counts == [r.counts]                                # 门电路的列式表照旧
