# -*- coding: utf-8 -*-
"""登录态：优先级与 whoami（U1）、不泄露（U6）、到期（U7）、不可交互（U8）、登出（U9），以及 login() 的几条路。"""
import logging
import os
import subprocess
import sys
import threading
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

import quafu
from quafu import credentials, oauth
from quafu.credentials import Credential
from quafu.errors import LoginExpired, LoginFailed, LoginRevoked, NotLoggedIn

from ..helpers import BASE, KEY, KEY2, ME, TOKEN, TOKEN_OK, UNAUTHORIZED

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py

TOKEN2 = credentials.TOKEN_PREFIX + 'N3wT0k3nN3wT0k3nN3wT0k3nN3wT0k3n'


def save_oauth(days_left=60, token=TOKEN):
    exp = (credentials.now() + timedelta(days=days_left)).isoformat(timespec='seconds')
    credentials.save(BASE, Credential(token, 'oauth', 'saved', expires_at=exp,
                                      user={'public_id': 'u7f3a9c2b', 'name': '甲'}, device_name='pc'))
    return exp


@pytest.fixture
def browser_login(monkeypatch):
    """把网页登录的「人点浏览器」换成：收到授权地址就直接回调本机端口；记下打开过的地址。"""
    opened = []

    def browser(url):
        opened.append(url)
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        port = urlsplit(q['redirect_uri']).port
        import http.client

        def hit():
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            c.request('GET', '/callback?code=AUTHCODE&state=%s' % q['state'])
            c.getresponse().read()
            c.close()
        threading.Thread(target=hit, daemon=True).start()
        return True
    monkeypatch.setattr(oauth, 'launch_browser', browser)
    return opened


# ── U1 优先级与 whoami ──────────────────────────────────────────────

def test_whoami_reports_who_which_kind_and_where_from(fake, monkeypatch):
    fake.route('GET', '/auth/me', ME)
    exp = save_oauth()
    info = quafu.whoami()
    assert info == {'public_id': 'u7f3a9c2b', 'name': '甲', 'email': 'a@b.test', 'kind': 'oauth', 'source': 'saved',
                    'expires_at': exp, 'base_url': BASE, 'credential': TOKEN[:11] + '...'}
    assert fake.calls[-1]['headers']['Authorization'] == 'Bearer ' + TOKEN
    monkeypatch.setenv('QUAFU_API_KEY', KEY2)
    info = quafu.whoami()
    assert (info['kind'], info['source'], info['expires_at']) == ('api_key', 'env', None)
    assert fake.calls[-1]['headers']['Authorization'] == 'Bearer ' + KEY2
    info = quafu.Client(api_key=KEY).whoami()
    assert (info['source'], info['credential']) == ('argument', KEY[:11] + '...')
    assert fake.calls[-1]['headers']['Authorization'] == 'Bearer ' + KEY


def test_no_credential_and_not_interactive_is_not_logged_in(fake):
    with pytest.raises(NotLoggedIn) as e:
        quafu.whoami()
    assert 'quafu login' in str(e.value) and 'QUAFU_API_KEY' in str(e.value)
    assert fake.calls == []


def test_public_data_needs_no_login_and_sends_no_credential(fake):
    fake.route('GET', '/devices', (200, {'devices': [], 'simulator': {'name': 'sim', 'max_qubits': 24,
                                                                       'status': 'online'}}))
    assert quafu.devices()[0]['name'] == 'sim'
    assert 'Authorization' not in fake.calls[0]['headers']


def test_interactive_first_use_starts_web_login_then_continues(fake, monkeypatch, browser_login, capsys):
    """U1 第 4 层：凭证都没有、可交互 → 当场网页登录，完成后继续原来的调用。"""
    monkeypatch.setattr(oauth, 'interactive', lambda: True)
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    fake.route('POST', '/oauth/token', TOKEN_OK)
    fake.route('GET', '/auth/me', ME)
    info = quafu.whoami()
    assert (info['kind'], info['source']) == ('oauth', 'saved') and len(browser_login) == 1
    form = fake.posts('/oauth/token')[0]['form']
    assert form['grant_type'] == 'authorization_code' and form['code'] == 'AUTHCODE'
    assert form['client_id'] == 'quafu-sdk' and form['redirect_uri'].startswith('http://127.0.0.1:')
    assert 'Authorization' not in fake.posts('/oauth/token')[0]['headers']
    saved = credentials.saved(BASE)
    assert saved.kind == 'oauth' and saved.user == {'public_id': 'u7f3a9c2b', 'name': '甲'}
    left = saved.expires() - credentials.now()
    assert timedelta(days=89, hours=23) < left <= timedelta(days=90)
    assert '已登录：甲（u7f3a9c2b）' in capsys.readouterr().out


# ── login() ────────────────────────────────────────────────────────

def test_login_with_api_key_verifies_then_saves(fake):
    fake.route('GET', '/auth/me', ME)
    info = quafu.login(api_key=KEY)
    assert info['kind'] == 'api_key' and info['expires_at'] is None and info['public_id'] == 'u7f3a9c2b'
    assert info['saved_to'] == credentials.credentials_path()
    assert credentials.saved(BASE).kind == 'api_key'


def test_login_does_not_save_a_rejected_key(fake):
    fake.route('GET', '/auth/me', UNAUTHORIZED)
    with pytest.raises(LoginRevoked):
        quafu.login(api_key=KEY)
    assert credentials.saved(BASE) is None


def test_login_rejects_a_malformed_key_before_any_request(fake):
    with pytest.raises(credentials.CredentialsError):
        quafu.login(api_key='not-a-key')
    assert fake.calls == []


def test_login_when_already_logged_in_returns_without_a_new_login(fake, browser_login):
    save_oauth(days_left=30)
    info = quafu.login()
    assert info['kind'] == 'oauth' and browser_login == [] and fake.calls == []


def test_login_force_and_near_expiry_log_in_again_and_revoke_the_old_token(fake, browser_login, monkeypatch):
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    fake.route('POST', '/oauth/token', (200, dict(TOKEN_OK[1], access_token=TOKEN2)))
    fake.route('GET', '/auth/me', ME)
    fake.route('POST', '/oauth/revoke', (200, {}))
    save_oauth(days_left=3)                                  # 7 天内到期：login() 直接重新登录
    quafu.login(open_browser=True)
    assert credentials.saved(BASE).mask == TOKEN2[:11] + '...'
    revoked = fake.posts('/oauth/revoke')
    assert [r['form']['token'] for r in revoked] == [TOKEN]
    assert revoked[0]['form']['token_type_hint'] == 'access_token'
    quafu.login(force=True)
    assert len(browser_login) == 2


def test_rejected_code_is_login_failed(fake, browser_login, monkeypatch):
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    fake.route('POST', '/oauth/token', (400, {'error': 'invalid_grant', 'error_description': 'used'}))
    with pytest.raises(LoginFailed) as e:
        quafu.login()
    assert '授权码' in str(e.value) and 'quafu login' in str(e.value)
    assert credentials.saved(BASE) is None


def test_login_warns_when_the_env_key_will_win(fake, monkeypatch, capsys):
    fake.route('GET', '/auth/me', ME)
    monkeypatch.setenv('QUAFU_API_KEY', KEY2)
    quafu.login(api_key=KEY)
    assert 'QUAFU_API_KEY' in capsys.readouterr().err


# ── U7 到期 ─────────────────────────────────────────────────────────

def test_expiring_within_seven_days_warns_once_per_process(fake, capsys):
    fake.route('GET', '/auth/me', ME)
    save_oauth(days_left=5)
    quafu.whoami()
    quafu.whoami()
    err = capsys.readouterr().err
    assert err.count('QUAFU 登录将于') == 1 and 'quafu login' in err


def test_not_close_to_expiry_is_quiet(fake, capsys):
    fake.route('GET', '/auth/me', ME)
    save_oauth(days_left=30)
    quafu.whoami()
    assert capsys.readouterr().err == ''


def test_expired_login_sends_nothing_and_says_so(fake):
    exp = save_oauth(days_left=-1)
    with pytest.raises(LoginExpired) as e:
        quafu.whoami()
    assert fake.calls == []
    assert e.value.expires_at == exp and '90 天' in str(e.value) and 'quafu login' in str(e.value)
    assert 'API Key' in str(e.value)


def test_expired_login_in_an_interactive_session_logs_in_again(fake, monkeypatch, browser_login):
    monkeypatch.setattr(oauth, 'interactive', lambda: True)
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    fake.route('POST', '/oauth/token', (200, dict(TOKEN_OK[1], access_token=TOKEN2)))
    fake.route('GET', '/auth/me', ME)
    fake.route('POST', '/oauth/revoke', (200, {}))
    save_oauth(days_left=-1)
    assert quafu.whoami()['credential'] == TOKEN2[:11] + '...'
    assert len(browser_login) == 1


def test_server_401_on_a_valid_oauth_login_is_login_revoked(fake):
    fake.route('GET', '/auth/me', UNAUTHORIZED)
    save_oauth(days_left=30)
    with pytest.raises(LoginRevoked) as e:
        quafu.whoami()
    assert '撤销' in str(e.value) and 'quafu login' in str(e.value)
    assert credentials.saved(BASE) is not None                # 不擅自删本机文件


def test_server_401_on_an_api_key_is_login_revoked_too(fake):
    fake.route('GET', '/auth/me', UNAUTHORIZED)
    with pytest.raises(LoginRevoked) as e:
        quafu.Client(api_key=KEY).whoami()
    assert '停用' in str(e.value)


# ── U8 不可交互 ─────────────────────────────────────────────────────

def test_no_tty_subprocess_fails_fast_without_reading_stdin(tmp_path):
    """真子进程：标准输入是管道且一直不关，无凭证 → 立刻 NotLoggedIn，不阻塞。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith('QUAFU_')}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), QUAFU_BASE_URL='https://127.0.0.1:9')
    code = ('import quafu\ntry:\n    quafu.submit("OPENQASM 2.0;", target="sim")\n'
            'except quafu.NotLoggedIn as e:\n    print("NOT_LOGGED_IN")\n')
    p = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env, text=True)
    try:
        out, err = p.communicate(timeout=5)
    finally:
        p.kill()
    assert 'NOT_LOGGED_IN' in out, err


# ── U9 登出 ─────────────────────────────────────────────────────────

def test_logout_revokes_then_deletes(fake):
    fake.route('POST', '/oauth/revoke', (200, {}))
    save_oauth()
    info = quafu.logout()
    assert info['removed'] and info['kind'] == 'oauth' and info['revoked'] is True
    assert fake.posts('/oauth/revoke')[0]['form'] == {'token': TOKEN, 'token_type_hint': 'access_token',
                                                     'client_id': 'quafu-sdk'}
    assert fake.posts('/oauth/revoke')[0]['read_timeout'] == 5.0
    assert credentials.saved(BASE) is None


@pytest.mark.parametrize('answer', [(500, {}), (404, {'detail': 'Not Found'})])
def test_logout_deletes_even_when_revoke_fails(fake, answer):
    from ..helpers import Fail
    fake.route('POST', '/oauth/revoke', answer, Fail(sent=False))
    save_oauth()
    info = quafu.logout()
    assert info['removed'] and info['revoked'] is False and '已登录的设备' in info['message']
    assert len(fake.posts('/oauth/revoke')) == 1                 # 不重试
    assert credentials.saved(BASE) is None


def test_logout_with_a_saved_api_key_does_not_call_revoke(fake):
    credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
    info = quafu.logout()
    assert info['kind'] == 'api_key' and fake.calls == [] and '仍然有效' in info['message']
    assert quafu.logout()['removed'] is False


# ── U6 不泄露 ───────────────────────────────────────────────────────

def test_tokens_never_in_logs_errors_repr_or_whoami(fake, monkeypatch, browser_login, caplog, capsys):
    monkeypatch.setattr(oauth, 'interactive', lambda: True)
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    fake.route('POST', '/oauth/token', TOKEN_OK)
    fake.route('GET', '/auth/me', ME, ME, UNAUTHORIZED)
    fake.route('POST', '/oauth/revoke', (500, {}))
    secrets_ = [TOKEN, TOKEN[11:], KEY, KEY[11:], 'AUTHCODE']
    texts = []
    with caplog.at_level(logging.DEBUG):
        c = quafu.Client()
        texts.append(repr(c.whoami()))
        texts += [repr(c), repr(c.credential), str(c.credential)]
        with pytest.raises(LoginRevoked) as e:
            c.whoami()
        texts.append(str(e.value))
        texts.append(quafu.logout()['message'])
        k = quafu.Client(api_key=KEY)
        texts += [repr(k), repr(k.credential)]
    out = capsys.readouterr()
    texts += [r.getMessage() for r in caplog.records] + [out.out, out.err]
    blob = '\n'.join(texts)
    for s in secrets_:
        assert s not in blob, s
