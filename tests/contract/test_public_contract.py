# -*- coding: utf-8 -*-
"""契约测试：公开任务。所有者交一条、等结果、设为公开；另一个人（另一把 Key，以及完全不登录）按公开 ID 与分享链接读，
看到的结果与所有者自己读到的一致，本机核对指纹通过；所有者取消公开后，再读抛 PublicTaskNotFound。"""
import pytest

import quafu
from quafu.errors import NotPublishable, PublicTaskNotFound

from .conftest import call

HEAD = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
BELL = HEAD + 'h q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n'


def test_publish_then_anyone_reads_the_same_result(client, issue, transport, base_url):
    job = client.submit(BELL, target='sim', shots=256, name='公开的贝尔态')
    mine = job.result(timeout=120)
    p = job.publish()
    assert p.published and p.public_id and p.url == base_url + '/public-tasks/' + p.public_id
    assert job.publish().public_id == p.public_id                     # 幂等

    for reader in (quafu.Client(api_key=issue()[1], _transport=transport),   # 另一个账号
                   quafu.Client(_transport=transport)):                      # 不登录
        for given in (p.public_id, p.url):
            pt = reader.public_task(given)
            r = pt.result
            assert pt.task_id == mine.task_id and pt.integrity == 'intact' and pt.verify()
            assert pt.executor == 'quafu_simulator'
            same = ('counts', 'bit_order', 'n_clbits', 'shots_requested', 'shots_returned', 'measurements',
                    'executed_qasm', 'compiler', 'calibration_id', 'target', 'backend', 'status')
            assert {k: getattr(r, k) for k in same} == {k: getattr(mine, k) for k in same}

    job.unpublish()
    with pytest.raises(PublicTaskNotFound):
        quafu.Client(_transport=transport).public_task(p.public_id)


def test_only_the_owner_and_not_demo_circuits(client, issue, transport, account, dispatcher_url):
    job = client.submit(BELL, target='sim', shots=64)
    tid = job.result(timeout=120).task_id
    other = quafu.Client(api_key=issue()[1], _transport=transport)
    with pytest.raises(quafu.TaskNotFound):
        other.publish(tid)
    assert client.publish(tid).published
    # 演示线路（平台预置的）不能公开
    status, body = call(dispatcher_url, 'POST', '/demo/runs', {'target': 'sim', 'demo': '贝尔态.qasm', 'shots': 32},
                        token=account[1])
    assert status == 202, body
    demo = quafu.Job(client, body['job_id'])
    demo.wait(timeout=120)
    with pytest.raises(NotPublishable) as e:
        demo.publish()
    assert e.value.reason == 'demo'
