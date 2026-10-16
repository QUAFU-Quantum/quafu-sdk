# -*- coding: utf-8 -*-
"""契约测试（v0.1 核心范围）：quafu.Client 经真 HTTP、经「门户地址 → /api/v1 → 任务分发器」对着本仓任务分发器跑。

C2  API Key：交 Bell 到 sim → 取回计数；一组线路、compiler='none'、接回、取消、devices、预检错误
C1  网页登录的服务器半程：用户会话 → 申请授权码 → SDK 换令牌 → 交 Bell 到 sim 拿回计数
C3  撤销后 SDK 抛 LoginRevoked
任务分发器还没有网页登录端点时，C1、C3 跳过并写明原因（服务器端由另一条工作线实现，合并后自动跑起来）。"""
import http.client
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

import quafu
from quafu import credentials, oauth
from quafu.errors import BadRequest, JobNotFound, LoginRevoked, PrecheckError

from .conftest import call

HEAD = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\n'
BELL = HEAD + 'h q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n'
X0 = HEAD + 'x q[0];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n'          # 不对称：位序错了就不是 '01'


# ── C2：API Key ─────────────────────────────────────────────────────

def test_c2_api_key_bell_on_sim(client, transport, account, base_url):
    me = client.whoami()
    assert me['email'] == account[0] and me['kind'] == 'api_key' and me['public_id']
    job = client.submit(BELL, target='sim', shots=256, name='贝尔态')
    post = transport.posts('/jobs')[0]
    assert post['body']['mode'] == 'single' and post['body']['circuit_level'] == 'logical'
    assert transport.calls[0]['headers']['Authorization'].startswith('Bearer qf_')
    assert job.id.startswith(me['public_id'] + '-')
    r = job.result(timeout=120)
    assert r.ok and sum(r.counts.values()) == 256 and set(r.counts) <= {'00', '11'}
    assert r.bit_order == 'c0_rightmost' and r.n_clbits == 2 and (r.shots_requested, r.shots_returned) == (256, 256)
    assert [m['cbit'] for m in r.measurements] == [0, 1]
    assert r.executed_qasm and 'OPENQASM 2.0' in r.executed_qasm
    assert isinstance(r.compiler, dict) and 'name' in r.compiler
    assert job.status() == 'Finished'


def test_c2_collection_keeps_order_and_bit_order(client):
    job = client.submit([X0, BELL, X0], target='sim', shots=64)
    rs = job.results(timeout=120)
    assert [r.counts for r in (rs[0], rs[2])] == [{'01': 64}, {'01': 64}]
    assert set(rs[1].counts) <= {'00', '11'} and job.n_tasks == 3
    with pytest.raises(ValueError):
        job.result()


def test_c2_reattach_from_another_client(client, account, transport):
    job = client.submit(X0, target='sim', shots=32)
    again = quafu.Client(api_key=account[1], _transport=transport).job(job.id)      # 像换了一个进程
    assert again.n_tasks == 1 and again.result(timeout=120).counts == {'01': 32}


def test_c2_foreign_or_missing_job_is_not_found(client, issue, transport):
    job = client.submit(X0, target='sim', shots=16)
    other = quafu.Client(api_key=issue()[1], _transport=transport)
    with pytest.raises(JobNotFound):
        other.job(job.id)
    with pytest.raises(JobNotFound):
        client.job('u00000000-260101-000000')


def test_c2_compiler_none_is_a_physical_circuit(client, transport):
    job = client.submit(X0, target='sim', shots=16, compiler='none')
    assert transport.posts('/jobs')[0]['body']['circuit_level'] == 'physical'
    assert job.result(timeout=120).counts == {'01': 16}


def test_c2_precheck_errors_come_back_with_the_reason(client):
    with pytest.raises(PrecheckError) as e:
        client.submit(HEAD + 'h q[0];\n', target='sim')                 # 没有测量
    assert e.value.category and e.value.category.startswith('precheck.')
    with pytest.raises((PrecheckError, BadRequest)):
        client.submit(BELL, target='NoSuchChip')


def test_c2_cancel_returns_the_platform_answer(client):
    job = client.submit(BELL, target='sim', shots=16)
    d = job.cancel()
    assert d['job_id'] == job.id and 'cancelled_now' in d


def test_c2_devices_list_target_names_without_login(transport, monkeypatch):
    monkeypatch.delenv('QUAFU_API_KEY', raising=False)
    ds = quafu.Client(_transport=transport).devices()
    assert ds[0]['name'] == 'sim' and ds[0]['kind'] == 'sim' and ds[0]['n_qubits']
    assert {d['kind'] for d in ds} <= {'sim', 'real'}
    assert all('Authorization' not in c['headers'] for c in transport.calls)


def test_c2_module_level_functions_use_the_env_key(account, transport, monkeypatch):
    monkeypatch.setenv('QUAFU_API_KEY', account[1])
    from quafu import client as client_mod
    monkeypatch.setattr(client_mod, 'HTTPTransport', lambda **kw: transport)
    assert quafu.whoami()['source'] == 'env'
    assert quafu.submit(X0, 'sim', shots=8).result(timeout=120).counts == {'01': 8}


# ── C1、C3：网页登录 ────────────────────────────────────────────────

@pytest.fixture
def oauth_ready(dispatcher_url):
    """任务分发器有没有网页登录的令牌端点：没有（404）就跳过。"""
    status, body = call(dispatcher_url, 'POST', '/oauth/token', {})
    if status == 404:
        pytest.skip('任务分发器还没有网页登录端点（/v1/oauth/token），等服务器端合并后自动跑')


def browser_as(dispatcher_url, session):
    """代替「浏览器里已登录的那个人」：拿授权地址里的参数，用本人会话向任务分发器申请授权码（网站授权页的服务端
    就是这么做的），再按 redirect_uri 回调本机端口。"""
    def open_(url):
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}

        def go():
            status, body = call(dispatcher_url, 'POST', '/oauth/codes', {
                'client_id': q['client_id'], 'redirect_uri': q['redirect_uri'], 'code_challenge': q['code_challenge'],
                'code_challenge_method': q['code_challenge_method'], 'device_name': q['device_name']},
                token=session)
            assert status in (200, 201), body
            port = urlsplit(q['redirect_uri']).port
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            c.request('GET', '/callback?code=%s&state=%s' % (body['code'], q['state']))
            c.getresponse().read()
            c.close()
        threading.Thread(target=go, daemon=True).start()
        return True
    return open_


def test_c1_web_login_then_bell_on_sim(oauth_ready, user, dispatcher_url, transport, monkeypatch, base_url):
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    monkeypatch.setattr(oauth, 'launch_browser', browser_as(dispatcher_url, user['session']))
    from quafu import client as client_mod
    monkeypatch.setattr(client_mod, 'HTTPTransport', lambda **kw: transport)
    info = quafu.login()
    assert info['kind'] == 'oauth' and info['expires_at']
    saved = credentials.saved(base_url)
    left = (saved.expires() - credentials.now()).total_seconds()
    assert 89.9 * 86400 < left <= 90 * 86400 + 60
    me = quafu.whoami()
    assert me['email'] == user['email'] and (me['kind'], me['source']) == ('oauth', 'saved')
    assert quafu.submit(BELL, 'sim', shots=64).result(timeout=120).shots_returned == 64


def test_c3_revoked_login_is_login_revoked(oauth_ready, user, dispatcher_url, transport, monkeypatch, base_url):
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    monkeypatch.setattr(oauth, 'launch_browser', browser_as(dispatcher_url, user['session']))
    from quafu import client as client_mod
    monkeypatch.setattr(client_mod, 'HTTPTransport', lambda **kw: transport)
    quafu.login()
    token = credentials.saved(base_url)._token
    r = transport.request('POST', base_url + '/api/v1/oauth/revoke',
                          {'Content-Type': 'application/x-www-form-urlencoded'},
                          ('token=%s&client_id=quafu-sdk' % token).encode('ascii'), 5, 10)
    assert r.status == 200
    with pytest.raises(LoginRevoked) as e:
        quafu.whoami()
    assert 'quafu login' in str(e.value) and token not in str(e.value)


def test_c3_logout_revokes_on_the_server(oauth_ready, user, dispatcher_url, transport, monkeypatch, base_url):
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    monkeypatch.setattr(oauth, 'launch_browser', browser_as(dispatcher_url, user['session']))
    from quafu import client as client_mod
    monkeypatch.setattr(client_mod, 'HTTPTransport', lambda **kw: transport)
    quafu.login()
    token = credentials.saved(base_url)._token
    assert quafu.logout()['revoked'] is True
    with pytest.raises(LoginRevoked):
        quafu.Client(api_key=token, _transport=transport).whoami()
