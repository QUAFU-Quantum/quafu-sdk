# -*- coding: utf-8 -*-
"""界面语言（默认英文，可切中文）：消息表、优先级、quafu config、首次登录按 Z / E 切换。"""
import ast
import io
import json
import os
import pathlib
import re
import sys
import threading
import time
import types
from urllib.parse import parse_qs, urlsplit

import pytest

import quafu
from quafu import _conflict, _i18n, cli, errors, oauth
from quafu._messages import MESSAGES
from quafu.errors import LoginFailed

from ..helpers import BASE, KEY, ME

SRC = pathlib.Path(quafu.__file__).resolve().parent
SPEC = re.compile(r'%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?([diouxXeEfFgGcrsa%])')
KEY_LITERAL = re.compile(r'[a-z_]+(?:\.[a-z_]+)+\Z')
NOT_KEYS = {'config.json'}                               # 源码里长得像键、其实不是的字符串
DYNAMIC = {'cli.kind.api_key', 'cli.kind.oauth', 'cli.source.argument', 'cli.source.env', 'cli.source.saved'}


# ── 消息表 ───────────────────────────────────────────────────────────

def _source_strings():
    """包源码（消息表本身除外）里所有字符串常量。"""
    out = set()
    for path in SRC.rglob('*.py'):
        if path.name == '_messages.py':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value)
    return out


def test_every_message_has_both_languages():
    for key, pair in MESSAGES.items():
        assert isinstance(pair, tuple) and len(pair) == 2, key
        assert all(isinstance(s, str) and s for s in pair), key


def test_both_languages_take_the_same_arguments():
    for key, (en, zh) in MESSAGES.items():
        assert SPEC.findall(en) == SPEC.findall(zh), key


def test_every_message_formats_in_both_languages():
    for key, pair in MESSAGES.items():
        args = tuple(1 if c in 'dg' else 'x' for c in SPEC.findall(pair[0]))
        for text in pair:
            text % args if args else text


def test_every_key_the_code_uses_exists_and_none_is_dead():
    """缺键：代码里写了 'errors.xxx' 这样的键而表里没有，测试失败（不等到哪天走到那条路才 KeyError）。"""
    prefixes = {k.split('.')[0] for k in MESSAGES if '.' in k}
    strings = _source_strings()
    used = {s for s in strings if KEY_LITERAL.match(s) and s.split('.')[0] in prefixes} - NOT_KEYS
    assert sorted(used - set(MESSAGES)) == []
    assert sorted(k for k in MESSAGES if k not in strings | DYNAMIC) == []


def test_no_chinese_left_in_code_outside_the_message_table():
    cjk = re.compile(r'[一-鿿]')
    for path in SRC.rglob('*.py'):
        if path.name == '_messages.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                assert not cjk.search(node.value), '%s:%d %r' % (path.name, node.lineno, node.value)


# ── 优先级 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw, code', [('en', 'en'), ('zh', 'zh'), ('ZH', 'zh'), ('zh_CN', 'zh'), ('zh-CN', 'zh'),
                                       ('zh_CN.UTF-8', 'zh'), ('zh-Hans', 'zh'), ('en_US', 'en'), (' en-GB ', 'en'),
                                       ('fr', None), ('', None), ('C', None), (None, None)])
def test_normalize(raw, code):
    assert _i18n.normalize(raw) == code


def test_default_is_english_and_ignores_the_system_locale(monkeypatch):
    monkeypatch.setenv('LANG', 'zh_CN.UTF-8')
    monkeypatch.setenv('LC_ALL', 'zh_CN.UTF-8')
    assert _i18n.resolve() == ('en', 'default') and quafu.get_language() == 'en'


def test_precedence_process_then_env_then_saved_then_default(monkeypatch):
    _i18n.save_language('zh')
    assert _i18n.resolve() == ('zh', 'saved')
    monkeypatch.setenv('QUAFU_LANG', 'en_US')
    assert _i18n.resolve() == ('en', 'env')
    quafu.set_language('zh')
    assert _i18n.resolve() == ('zh', 'process')
    quafu.set_language(None)
    assert _i18n.resolve() == ('en', 'env')
    monkeypatch.setenv('QUAFU_LANG', 'klingon')          # 认不出的值当没设
    assert _i18n.resolve() == ('zh', 'saved')


def test_set_language_is_not_saved_and_rejects_unknown_values():
    quafu.set_language('zh')
    assert not os.path.exists(_i18n.settings_path())
    with pytest.raises(ValueError):
        quafu.set_language('fr')


def test_settings_live_apart_from_credentials_and_follow_quafu_config_dir(monkeypatch, tmp_path):
    from quafu import credentials
    assert os.path.dirname(_i18n.settings_path()) == os.path.dirname(credentials.credentials_path())
    assert _i18n.settings_path() != credentials.credentials_path()
    monkeypatch.setenv('QUAFU_CONFIG_DIR', str(tmp_path / 'cfg'))
    path = _i18n.save_language('zh')
    assert path == str(tmp_path / 'cfg' / 'config.json')
    assert json.loads(open(path, encoding='utf-8').read()) == {'version': 1, 'language': 'zh'}


def test_a_broken_settings_file_falls_back_to_the_default():
    os.makedirs(os.path.dirname(_i18n.settings_path()), exist_ok=True)
    with open(_i18n.settings_path(), 'w') as f:
        f.write('{not json')
    assert _i18n.resolve() == ('en', 'default')


def test_messages_follow_the_language_at_raise_time(monkeypatch):
    body = {'error': 'x', 'code': 'not_found'}
    assert str(errors.from_response('job', 404, body, job_id='J1', who='k')).startswith("Job J1 doesn't exist")
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    assert str(errors.from_response('job', 404, body, job_id='J1', who='k')).startswith('任务组 J1 不存在')


def test_conflict_message_in_both_languages(monkeypatch):
    assert _conflict.message([('old', '1.0')], []).startswith('Another package that uses the name quafu')
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    assert '另一个占用 quafu 名字的包（old 1.0）' in _conflict.message([('old', '1.0')], [])


# ── 命令行 ───────────────────────────────────────────────────────────

@pytest.fixture
def run(fake, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_transport', fake)

    def run(*argv, stdin=None):
        monkeypatch.setattr(sys, 'stdin', io.StringIO(stdin or ''))
        try:
            code = cli.main(list(argv))
        except SystemExit as e:                     # argparse 的 --help / 用法错误
            code = e.code
        out, err = capsys.readouterr()
        return code, out, err
    return run


def test_help_is_english_by_default_and_chinese_with_quafu_lang(run, monkeypatch):
    code, out, err = run('--help')
    assert code == 0 and 'Log in' in out and 'Show this help message and exit' in out and 'config' in out
    assert not re.search(r'[一-鿿]', out)
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    code, out, err = run('--help')
    assert code == 0 and '登录' in out and '显示帮助并退出' in out


def test_not_logged_in_error_in_both_languages(run, monkeypatch):
    code, out, err = run('whoami')
    assert code == 1 and out.startswith('Error: Not logged in to QUAFU (%s)' % BASE) and 'quafu login' in out
    monkeypatch.setenv('QUAFU_LANG', 'zh_CN')
    code, out, err = run('whoami')
    assert code == 1 and out.startswith('错误：未登录 QUAFU（%s）' % BASE)


def test_whoami_snapshot_english(run, fake, monkeypatch):
    monkeypatch.setenv('QUAFU_API_KEY', KEY)
    fake.route('GET', '/auth/me', ME)
    code, out, err = run('whoami')
    assert code == 0 and out.splitlines() == [
        'Account     甲 (u7f3a9c2b)',
        'Platform    %s' % BASE,
        'Credential  API key %s (from environment variable QUAFU_API_KEY)' % (KEY[:11] + '...'),
        'Expires     never']


def test_login_api_key_english(run, fake):
    fake.route('GET', '/auth/me', ME)
    code, out, err = run('login', '--api-key', '-', stdin=KEY + '\n')
    assert code == 0 and out.startswith('Logged in as 甲 (u7f3a9c2b)  API key  expires: never\n')


def test_config_set_get_language(run, fake, monkeypatch):
    code, out, err = run('config', 'get', 'language')
    assert (code, out) == (0, 'en\n')
    code, out, err = run('config', 'set', 'language', 'zh_CN')
    assert code == 0 and out == '显示语言已设为中文。\n'
    assert json.load(open(_i18n.settings_path(), encoding='utf-8'))['language'] == 'zh'
    code, out, err = run('config', 'get', 'language')
    assert (code, out) == (0, 'zh\n')
    code, out, err = run('whoami')
    assert code == 1 and out.startswith('错误：未登录')
    code, out, err = run('config', 'set', 'language', 'en')
    assert code == 0 and out == 'Display language set to English.\n'


def test_config_env_overrides_saved_value(run, monkeypatch):
    monkeypatch.setenv('QUAFU_LANG', 'en')
    code, out, err = run('config', 'set', 'language', 'zh')
    assert code == 0 and out == '' and 'QUAFU_LANG=en' in err
    code, out, err = run('config', 'get', 'language')
    assert out == 'en\n' and 'takes precedence' in err


def test_config_errors(run):
    code, out, err = run('config', 'set', 'language', 'fr')
    assert code == 1 and err == "Error: Unsupported language 'fr'. Use en or zh.\n"
    code, out, err = run('config', 'get', 'color')
    assert code == 1 and 'Unknown setting' in err
    code, out, err = run('config')
    assert code == 2 and 'get' in out and 'set' in out


# ── 首次登录按 Z / E 切换 ───────────────────────────────────────────

def _login(reader_lines, out):
    """oauth.run 走粘贴那一路：reader 依次返回 reader_lines（'{state}' 换成本次的 state），记下每次的提示。"""
    holder, prompts, seen = {}, [], {}
    lines = list(reader_lines)

    def browser(url):
        holder['state'] = parse_qs(urlsplit(url).query)['state'][0]
        return False

    def reader(prompt, stop, deadline):
        prompts.append(prompt)
        return lines.pop(0).replace('{state}', holder['state'])

    def exchange(code, redirect_uri, verifier):
        seen['code'] = code
        return {}
    oauth.run(BASE, exchange, reader=reader, out=out, browser=browser, timeout=5)
    return prompts, seen


def test_first_login_prompt_is_english_with_a_chinese_switch_line():
    out = io.StringIO()
    prompts, seen = _login(['CODE#{state}'], out)
    text = out.getvalue()
    assert text.startswith('Open this link in your browser to log in to QUAFU:\n  https://')
    assert text.endswith('paste it below and press Enter.)\n使用中文请按 Z 并回车。\n')
    assert prompts == ['Authorization code: '] and seen['code'] == 'CODE'


def test_pressing_z_switches_saves_reprints_and_keeps_waiting():
    out = io.StringIO()
    prompts, seen = _login([' z \n', 'CODE#{state}'], out)
    text = out.getvalue()
    english, chinese = text.split('使用中文请按 Z 并回车。\n')
    assert 'Open this link' in english
    assert chinese.startswith('\n请在浏览器中打开以下链接登录 QUAFU：')
    assert chinese.endswith('Press E then Enter to set English as display language.\n')
    assert prompts == ['Authorization code: ', '授权码：'] and seen['code'] == 'CODE'
    assert _i18n.saved_language() == 'zh' and quafu.get_language() == 'zh'


def test_pressing_e_switches_back():
    out = io.StringIO()
    prompts, seen = _login(['Z', 'E', 'CODE#{state}'], out)
    assert prompts == ['Authorization code: ', '授权码：', 'Authorization code: ']
    assert _i18n.saved_language() == 'en' and out.getvalue().count('使用中文请按 Z 并回车。') == 2


def test_no_switch_line_once_a_language_is_chosen(monkeypatch):
    _i18n.save_language('en')
    out = io.StringIO()
    _login(['CODE#{state}'], out)
    assert '使用中文' not in out.getvalue()
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    out = io.StringIO()
    _login(['CODE#{state}'], out)
    assert 'Press E' not in out.getvalue() and '请在浏览器中打开' in out.getvalue()


def test_other_single_letters_are_treated_as_a_bad_code():
    assert oauth.language_key('x') is None and oauth.language_key('ZE') is None
    assert oauth.language_key('Zx3f#abc') is None and oauth.language_key('e') == 'en'
    with pytest.raises(LoginFailed):
        _login(['x'], io.StringIO())


def test_non_interactive_login_shows_no_switch_line():
    out = io.StringIO()
    with pytest.raises(LoginFailed):
        oauth.run(BASE, lambda *a: {}, reader=None, out=out, browser=lambda url: False, timeout=0.3)
    assert out.getvalue().startswith('Open this link in a browser on this machine')
    assert '使用中文' not in out.getvalue()


def test_language_key_pressed_during_web_login_applies_to_later_messages(fake, monkeypatch):
    """quafu.login() 里按了 Z：登录成功那句也是中文。"""
    from quafu import client as client_mod
    fake.route('POST', '/oauth/token', (200, {'access_token': 'qf_' + 'a' * 40, 'token_type': 'Bearer',
                                              'expires_in': 7776000}))
    fake.route('GET', '/auth/me', ME)
    holder = {}

    def browser(url):
        holder['state'] = parse_qs(urlsplit(url).query)['state'][0]
        return False
    lines = ['z', None]

    def reader(prompt, stop, deadline):
        line = lines.pop(0)
        return line if line else 'C#' + holder['state']
    out = io.StringIO()
    client_mod.web_login(quafu.Client(), reader=reader, out=out, browser=browser, timeout=5)
    assert out.getvalue().endswith('已登录：甲（u7f3a9c2b），有效期至 %s\n' % client_mod._date(
        quafu.credentials.saved(BASE).expires_at))


# ── Windows 逐字符读法 ──────────────────────────────────────────────

class FakeConsole(object):
    """假 msvcrt：events 是 (到达时刻偏移秒, 字符) 列表；kbhit 只看已经「到达」的字符。"""

    def __init__(self, events):
        self.t0 = time.monotonic()
        self.events = list(events)

    def kbhit(self):
        return bool(self.events) and time.monotonic() - self.t0 >= self.events[0][0]

    def getwche(self):
        return self.events.pop(0)[1]


@pytest.fixture
def console(monkeypatch):
    def install(events):
        fake = FakeConsole(events)
        monkeypatch.setitem(sys.modules, 'msvcrt', types.SimpleNamespace(kbhit=fake.kbhit, getwche=fake.getwche))
        monkeypatch.setattr(sys, 'stdout', io.StringIO())
        return fake
    return install


def test_windows_lone_z_switches_without_enter(console):
    console([(0, 'Z')])
    assert oauth._read_msvcrt('> ', threading.Event(), time.monotonic() + 2) == 'Z'


def test_windows_pasted_code_starting_with_z_is_not_a_switch(console):
    console([(0, ch) for ch in 'Zx3f#st'] + [(0, '\r')])
    assert oauth._read_msvcrt('> ', threading.Event(), time.monotonic() + 2) == 'Zx3f#st'


def test_windows_z_after_other_characters_is_just_input(console):
    console([(0, 'a'), (0.2, 'z'), (0.4, '\r')])
    assert oauth._read_msvcrt('> ', threading.Event(), time.monotonic() + 2) == 'az'


def test_windows_backspace_then_z_counts_as_lone(console):
    console([(0, 'a'), (0, '\x08'), (0.2, 'e')])
    assert oauth._read_msvcrt('> ', threading.Event(), time.monotonic() + 2) == 'e'


def test_windows_lone_key_then_enter_is_an_ignored_empty_line(console):
    """切换后用户习惯性再按回车：下一次读到的空行被忽略，接着等粘贴。"""
    console([(0, 'z'), (0.3, '\r'), (0.4, 'C'), (0.4, '#'), (0.4, 's'), (0.4, '\r')])
    stop = threading.Event()
    assert oauth._read_msvcrt('> ', stop, time.monotonic() + 2) == 'z'
    assert oauth._read_msvcrt('> ', stop, time.monotonic() + 2) == 'C#s'


def test_jiuding_simulator_unavailable_is_rewritten_in_both_languages(monkeypatch):
    body = {'error': '九鼎模拟 Baihua 暂时不可用，请稍后重试', 'code': 'runtime.deviceUnavailable',
            'error_category': 'runtime.deviceUnavailable',
            'vars': {'device': 'Baihua-sim-jiuding', 'device_status': 'offline'}}
    e = errors.from_response('submit', 503, body)
    assert isinstance(e, errors.DeviceUnavailable) and e.vars['device_status'] == 'offline'
    assert 'Jiuding simulator Baihua-sim-jiuding' in str(e) and '九鼎' not in str(e)
    monkeypatch.setenv('QUAFU_LANG', 'zh')
    assert '九鼎模拟 Baihua-sim-jiuding 此刻没有就绪的模拟器' in str(errors.from_response('submit', 503, body))
