# -*- coding: utf-8 -*-
"""公共夹具：每个用例一个干净的 HOME 与 QUAFU_* 环境变量，平台地址指向假地址；假传输层与假时钟。
默认不可交互（标准输入不是终端、不在 notebook 里）：没有凭证时不会发起网页登录。
界面语言默认英文（与发行时一致）；断言中文文案的模块用 pytestmark = pytest.mark.usefixtures('zh')。"""
import io
import sys

import pytest

import quafu
from quafu import _i18n, _limits, client as client_mod, credentials, jobs as jobs_mod, oauth

from .helpers import BASE, KEY, FakeTransport, FakeClock

ENV_VARS = ('QUAFU_API_KEY', 'QUAFU_BASE_URL', 'QUAFU_CONFIG_DIR', 'QUAFU_PROXY', 'QUAFU_CA_BUNDLE', 'QUAFU_LANG')


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    for v in ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv('QUAFU_BASE_URL', BASE)
    monkeypatch.setattr(client_mod, '_warned', set())
    monkeypatch.setattr(credentials, '_warned_dirs', set())
    monkeypatch.setattr(_i18n, '_override', None)
    _limits.clear_cache()                                     # 上限缓存是进程级的，用例之间不能串
    monkeypatch.setattr(sys, 'stdin', io.StringIO(''))        # 不是终端：没凭证时不会发起网页登录
    monkeypatch.setattr(oauth, 'WSL_OPENERS', ())             # 在 WSL 里跑测试也不弹出 Windows 浏览器
    monkeypatch.delenv('DISPLAY', raising=False)              # 不经 xdg-open 弹出桌面浏览器
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    return home


@pytest.fixture
def zh(monkeypatch):
    """界面语言切中文：这些用例断言的是中文文案。"""
    monkeypatch.setenv('QUAFU_LANG', 'zh')


@pytest.fixture
def fake(monkeypatch):
    """假传输层；同时让包里新建的 Client（含 quafu.submit 这类顶层函数）都用它。"""
    t = FakeTransport()
    monkeypatch.setattr(client_mod, 'HTTPTransport', lambda **kw: t)
    return t


@pytest.fixture
def make_client(fake):
    def make(api_key=KEY, **kw):
        return quafu.Client(api_key=api_key, **kw)
    return make


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    for mod in (client_mod, jobs_mod):
        monkeypatch.setattr(mod, 'time', c)
    return c
