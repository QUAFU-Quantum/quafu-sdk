# -*- coding: utf-8 -*-
"""凭证：形状校验与掩码（U6）、凭证文件的权限、原子替换与符号链接（U5）、优先级（U1 的存储一半）。"""
import json
import logging
import os
import stat

import pytest

from quafu import credentials
from quafu.credentials import Credential
from quafu.errors import CredentialsError

from ..helpers import BASE, KEY, KEY2, TOKEN

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py

posix_only = pytest.mark.skipif(os.name != 'posix', reason='POSIX 权限与符号链接')


def test_check_accepts_and_strips_whitespace():
    assert credentials.check_token('  %s\n' % KEY) == KEY


@pytest.mark.parametrize('bad', ['', '   ', 'sk_' + KEY[3:], KEY + ' x', KEY + '"', KEY[:3] + '-' + KEY[4:]])
def test_check_rejects_without_echoing_the_value(bad):
    with pytest.raises(CredentialsError) as e:
        credentials.check_token(bad)
    if len(bad.strip()) > 8:
        assert bad.strip() not in str(e.value) and bad.strip()[3:12] not in str(e.value)


def test_non_string_rejected():
    with pytest.raises(CredentialsError):
        credentials.check_token(123)


def test_mask_and_repr_never_show_the_token():
    c = Credential(TOKEN, 'oauth', 'saved', expires_at='2027-01-06T10:00:00+08:00')
    assert c.mask == TOKEN[:11] + '...'
    for text in (repr(c), str(c), c.mask):
        assert TOKEN not in text and TOKEN[11:] not in text
    assert c.authorization() == 'Bearer ' + TOKEN


def test_save_is_0600_in_a_0700_directory_and_roundtrips(clean_env):
    path = credentials.save(BASE, Credential(KEY, 'api_key', 'saved', created_at='2026-10-08T10:00:00+08:00'))
    assert path == str(clean_env / '.quafu-sdk' / 'credentials.json')
    if os.name == 'posix':
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    data = json.loads(open(path, encoding='utf-8').read())
    assert data['version'] == 1 and data['profiles'][BASE]['kind'] == 'api_key'
    got = credentials.saved(BASE)
    assert got.kind == 'api_key' and got.source == 'saved' and got.mask == credentials.mask(KEY)


def test_oauth_entry_keeps_expiry_user_and_device():
    c = Credential(TOKEN, 'oauth', 'saved', expires_at='2027-01-06T10:00:00+08:00',
                   user={'public_id': 'u1', 'name': '甲'}, device_name='lab-pc', created_at='2026-10-08T10:00:00+08:00')
    credentials.save(BASE, c)
    got = credentials.saved(BASE)
    assert (got.kind, got.expires_at, got.user, got.device_name) == ('oauth', c.expires_at, c.user, 'lab-pc')


def test_write_is_atomic_and_leaves_no_temp_file(clean_env):
    credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
    credentials.save('https://other.test', Credential(KEY2, 'api_key', 'saved'))
    d = clean_env / '.quafu-sdk'
    assert sorted(os.listdir(d)) == ['credentials.json']
    assert set(json.loads((d / 'credentials.json').read_text())['profiles']) == {BASE, 'https://other.test'}


def test_failed_write_keeps_the_old_file(clean_env, monkeypatch):
    credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
    real = os.replace

    def boom(a, b):
        raise OSError('disk full')
    monkeypatch.setattr(os, 'replace', boom)
    with pytest.raises(CredentialsError):
        credentials.save(BASE, Credential(KEY2, 'api_key', 'saved'))
    monkeypatch.setattr(os, 'replace', real)
    assert credentials.saved(BASE).mask == credentials.mask(KEY)
    assert os.listdir(clean_env / '.quafu-sdk') == ['credentials.json']


@posix_only
def test_symlinked_file_is_refused_for_read_and_write(clean_env, tmp_path):
    target = tmp_path / 'elsewhere.json'
    target.write_text(json.dumps({'version': 1, 'profiles': {}}))
    d = clean_env / '.quafu-sdk'
    d.mkdir(mode=0o700)
    (d / 'credentials.json').symlink_to(target)
    with pytest.raises(CredentialsError) as e:
        credentials.saved(BASE)
    assert '符号链接' in str(e.value)
    with pytest.raises(CredentialsError) as e:
        credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
    assert '符号链接' in str(e.value)
    assert json.loads(target.read_text()) == {'version': 1, 'profiles': {}}


def test_remove_returns_the_old_credential():
    credentials.save(BASE, Credential(TOKEN, 'oauth', 'saved', expires_at='2027-01-06T10:00:00+08:00'))
    old = credentials.remove(BASE)
    assert old.kind == 'oauth' and credentials.saved(BASE) is None
    assert credentials.remove(BASE) is None


@pytest.mark.parametrize('content', ['{', '[]', '{"version": 1}', '{"version": 9, "profiles": {}}',
                                     '{"version": 1, "profiles": {"%s": {"kind": "x", "token": "qf_a"}}}' % BASE,
                                     '{"version": 1, "profiles": {"%s": {"kind": "oauth", "token": "qf_a", '
                                     '"expires_at": "soon"}}}' % BASE])
def test_damaged_file_is_credentials_error_with_hint(clean_env, content):
    d = clean_env / '.quafu-sdk'
    d.mkdir()
    (d / 'credentials.json').write_text(content)
    with pytest.raises(CredentialsError) as e:
        credentials.saved(BASE)
    assert 'quafu login' in str(e.value) and 'QUAFU_CONFIG_DIR' in str(e.value)


def test_config_dir_env_and_warning_outside_home(monkeypatch, tmp_path, caplog):
    out = tmp_path / 'shared'
    monkeypatch.setenv('QUAFU_CONFIG_DIR', str(out))
    with caplog.at_level(logging.WARNING, logger='quafu'):
        credentials.config_dir()
        credentials.config_dir()
    assert credentials.credentials_path() == str(out / 'credentials.json')
    assert sum('主目录之外' in r.getMessage() for r in caplog.records) == 1


def test_resolve_priority_argument_env_saved(monkeypatch):
    credentials.save(BASE, Credential(TOKEN, 'oauth', 'saved', expires_at='2027-01-06T10:00:00+08:00'))
    assert credentials.resolve(None, BASE).source == 'saved'
    monkeypatch.setenv('QUAFU_API_KEY', KEY2)
    c = credentials.resolve(None, BASE)
    assert (c.source, c.kind, c.mask) == ('env', 'api_key', credentials.mask(KEY2))
    c = credentials.resolve(KEY, BASE)
    assert (c.source, c.mask) == ('argument', credentials.mask(KEY))
    assert credentials.resolve(None, 'https://nothing.test').source == 'env'
    monkeypatch.delenv('QUAFU_API_KEY')
    assert credentials.resolve(None, 'https://nothing.test') is None


def test_bad_env_key_names_the_variable_not_the_value(monkeypatch):
    monkeypatch.setenv('QUAFU_API_KEY', 'sk_live_secret_value')
    with pytest.raises(CredentialsError) as e:
        credentials.resolve(None, BASE)
    assert 'QUAFU_API_KEY' in str(e.value) and 'secret' not in str(e.value)


def test_expiry_helpers():
    c = Credential(TOKEN, 'oauth', 'saved', expires_at='2000-01-01T00:00:00+08:00')
    assert c.expired()
    assert not Credential(KEY, 'api_key', 'saved').expired()
