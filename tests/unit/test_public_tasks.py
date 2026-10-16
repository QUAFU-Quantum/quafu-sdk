# -*- coding: utf-8 -*-
"""公开任务（不经网络）：所有者设公开 / 取消公开 / 看状态，任何人按公开 ID 或分享链接读、在本机核对记录指纹。
端到端在 contract/test_public_contract.py。"""
import copy
import hashlib
import json

import pytest

import quafu
from quafu.errors import BadRequest, NotPublishable, PublicTaskNotFound

from ..helpers import BASE, BELL, JID, task_detail

PID = 'k7m2q9x4bt3w'
PUB_PATH = '/jobs/%s/tasks/0/publication' % JID
PUBLISHED = {'published': True, 'public_id': PID, 'share_path': '/public-tasks/' + PID,
             'published_at': '2026-10-16T22:30:00+08:00', 'record_sha256': None}


def _public_detail():
    """公开读到的详情：与本人详情同形，加 publication 段；record_sha256 按平台的规范化规则算。"""
    d = copy.deepcopy(task_detail()[1])
    d['circuit']['submitted']['text'] = BELL
    d['metadata'] = None
    record = {'schema': 'quafu-public-task/1', 'task_id': d['task_id'], 'job_id': JID, 'status': 'Finished',
              'executor': 'quafu_simulator', 'kind': 'sim', 'target': 'sim', 'chip': None,
              'circuit_sha256': hashlib.sha256(BELL.encode('utf-8')).hexdigest(), 'executed_circuit_sha256': None,
              'shots_requested': 100, 'shots_returned': 100, 'counts': d['result']['counts'], 'calibration_id': None,
              'created_at': 'a', 'hardware_finished_at': None, 'finished_at': 'b'}
    canon = json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    d['publication'] = {'public_id': PID, 'share_path': '/public-tasks/' + PID, 'published_at': 'c',
                        'attested_by': 'QUAFU', 'record': record, 'record_sha256': hashlib.sha256(canon).hexdigest(),
                        'integrity': 'intact'}
    return d


@pytest.fixture
def c(make_client):
    return make_client(base_url=BASE)


def test_publish_returns_public_id_and_share_url(fake, c):
    fake.route('POST', PUB_PATH, (200, PUBLISHED))
    p = quafu.Job(c, JID).publish()
    assert p.published and p.public_id == PID and p.url == BASE + '/public-tasks/' + PID
    assert p.task_id == JID + '-0'
    # 按任务号也行（result.task_id）
    p2 = c.publish(JID + '-0')
    assert p2.public_id == PID and [x['method'] for x in fake.calls] == ['POST', 'POST']


def test_unpublish_and_state(fake, c):
    off = {'published': False, 'public_id': None, 'share_path': None, 'published_at': None, 'record_sha256': None}
    fake.route('DELETE', PUB_PATH, (200, off))
    fake.route('GET', PUB_PATH, (200, off))
    p = c.unpublish(JID + '-0')
    assert p.published is False and p.public_id is None and p.url is None
    assert quafu.Job(c, JID).publication().published is False


def test_not_publishable_is_explained(fake, c, zh):
    fake.route('POST', PUB_PATH, (409, {'error': '只有已完成的任务才能公开', 'code': 'not_publishable',
                                        'vars': {'reason': 'not_finished', 'task_status': 'Running'}}))
    with pytest.raises(NotPublishable) as e:
        c.publish(JID + '-0')
    assert e.value.reason == 'not_finished' and e.value.task_status == 'Running' and '只有已完成' in str(e.value)


def test_bad_task_id_is_refused_before_sending(fake, c):
    with pytest.raises(BadRequest):
        c.publish('not-a-task')
    assert fake.calls == []


@pytest.mark.parametrize('given', [PID, PID.upper(), ' %s\n' % PID, BASE + '/public-tasks/' + PID,
                                   'https://quafu.com.cn/en/public-tasks/%s/?from=paper' % PID])
def test_public_task_reads_without_credentials(fake, make_client, given):
    fake.route('GET', '/public/tasks/' + PID, (200, _public_detail()))
    pt = make_client(api_key=None, base_url=BASE).public_task(given)
    req = fake.calls[-1]
    assert req['path'] == '/public/tasks/' + PID and 'Authorization' not in req['headers']
    assert pt.public_id == PID and pt.url == BASE + '/public-tasks/' + PID and pt.executor == 'quafu_simulator'
    assert pt.integrity == 'intact' and pt.verify() is True
    # 结果与所有者 job.result() 是同一个 Result 类、同一组字段
    assert isinstance(pt.result, quafu.Result) and pt.counts == {'00': 60, '11': 40} and pt.task_id == JID + '-0'


def test_verify_catches_a_changed_record_or_detail(fake, make_client):
    d = _public_detail()
    d['publication']['record']['counts'] = {'00': 100}            # 记录被改：指纹对不上
    fake.route('GET', '/public/tasks/' + PID, (200, d))
    assert make_client(api_key=None, base_url=BASE).public_task(PID).verify() is False
    d = _public_detail()
    d['result']['counts'] = {'00': 99, '11': 1}                   # 详情与记录不一致
    fake.route('GET', '/public/tasks/' + PID, (200, d))
    assert make_client(api_key=None, base_url=BASE).public_task(PID).verify() is False


def test_public_task_not_found(fake, make_client):
    fake.route('GET', '/public/tasks/' + PID, (404, {'error': 'not found', 'code': 'not_found'}))
    with pytest.raises(PublicTaskNotFound) as e:
        make_client(api_key=None, base_url=BASE).public_task(PID)
    assert e.value.public_id == PID


def test_public_task_retries_with_credentials_when_login_required(fake, c):
    fake.route('GET', '/public/tasks/' + PID, (401, {'error': '未登录', 'code': 'unauthenticated'}),
               (200, _public_detail()))
    pt = c.public_task(PID)
    assert pt.verify() and 'Authorization' not in fake.calls[0]['headers'] and 'Authorization' in fake.calls[1]['headers']


@pytest.mark.parametrize('bad', ['', 'u7f3a9c2b-261008-153000-0', 'k7m2q9x4bt30', 'https://x/public-tasks/abc'])
def test_unrecognized_public_id(fake, make_client, bad):
    with pytest.raises(BadRequest):
        make_client(api_key=None, base_url=BASE).public_task(bad)
    assert fake.calls == []
