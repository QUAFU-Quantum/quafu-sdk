# -*- coding: utf-8 -*-
"""U12 平台地址：参数 > QUAFU_BASE_URL > 内置默认值；非 https（回环除外）拒绝；凭证按地址分开。"""
import pytest

import quafu
from quafu import config, credentials
from quafu.errors import QuafuError

from ..helpers import BASE, KEY, KEY2, ME

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py


def test_default_is_the_public_platform(monkeypatch):
    monkeypatch.delenv('QUAFU_BASE_URL')
    assert config.DEFAULT_BASE_URL == quafu.DEFAULT_BASE_URL == 'https://quafu.com.cn'
    assert config.resolve_base_url() == 'https://quafu.com.cn'
    assert quafu.Client().api == 'https://quafu.com.cn/api/v1'


def test_argument_beats_env_beats_default(monkeypatch):
    monkeypatch.setenv('QUAFU_BASE_URL', 'https://env.test')
    assert config.resolve_base_url() == 'https://env.test'
    assert config.resolve_base_url('https://arg.test/') == 'https://arg.test'
    assert quafu.Client(base_url='https://arg.test').base_url == 'https://arg.test'
    monkeypatch.setenv('QUAFU_BASE_URL', '  ')
    assert config.resolve_base_url() == config.DEFAULT_BASE_URL


@pytest.mark.parametrize('url, expected', [
    ('https://Quafu.COM.cn', 'https://quafu.com.cn'),
    ('https://quafu.com.cn:443/', 'https://quafu.com.cn'),
    ('https://quafu.com.cn:8443', 'https://quafu.com.cn:8443'),
    ('http://127.0.0.1:8080', 'http://127.0.0.1:8080'),
    ('http://localhost:5', 'http://localhost:5'),
    ('http://[::1]:9000', 'http://[::1]:9000'),
])
def test_accepted_addresses_are_normalized(url, expected):
    assert config.check_base_url(url) == expected


@pytest.mark.parametrize('url, words', [
    ('http://quafu.com.cn', 'https'),
    ('ftp://quafu.com.cn', 'https://'),
    ('https://quafu.com.cn/api/v1', '不带路径'),
    ('https://quafu.com.cn?x=1', '不带路径'),
    ('https://user:pw@quafu.com.cn', '用户名'),
    ('quafu.com.cn', 'https://'),
    ('https://quafu.com.cn:99999', '格式不正确'),
    ('', '空'),
])
def test_rejected_addresses_say_why(url, words):
    with pytest.raises(QuafuError) as e:
        config.check_base_url(url)
    assert words in str(e.value)


def test_bad_env_names_the_variable(monkeypatch):
    monkeypatch.setenv('QUAFU_BASE_URL', 'http://evil.test')
    with pytest.raises(QuafuError) as e:
        quafu.Client()
    assert 'QUAFU_BASE_URL' in str(e.value)


def test_credentials_are_kept_per_base_url(fake, monkeypatch):
    fake.route('GET', '/auth/me', ME)
    quafu.login(api_key=KEY, base_url=BASE)
    quafu.login(api_key=KEY2, base_url='https://other.test')
    assert credentials.saved(BASE).mask == credentials.mask(KEY)
    assert credentials.saved('https://other.test').mask == credentials.mask(KEY2)
    assert quafu.Client(base_url='https://other.test').credential.mask == credentials.mask(KEY2)
    quafu.logout(base_url='https://other.test')
    assert credentials.saved('https://other.test') is None and credentials.saved(BASE) is not None
