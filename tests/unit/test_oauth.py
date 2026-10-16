# -*- coding: utf-8 -*-
"""网页登录的客户端一半：PKCE 与 state（U2）、本机回环回调（U3）、粘贴授权码（U4）、两条路竞争。"""
import base64
import hashlib
import http.client
import io
import re
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from quafu import oauth
from quafu.errors import LoginFailed

from ..helpers import BASE

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py

URLSAFE = re.compile(r'[A-Za-z0-9\-._~]+\Z')


def get(port, path):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    c.request('GET', path)
    r = c.getresponse()
    body = r.read().decode('utf-8')
    c.close()
    return r.status, body


def refused(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(('127.0.0.1', port))
        return False
    except OSError:
        return True
    finally:
        s.close()


# ── U2 PKCE 与 state ───────────────────────────────────────────────

def test_pkce_verifier_and_s256_challenge():
    seen = set()
    for _ in range(20):
        verifier, challenge = oauth.pkce_pair()
        assert 43 <= len(verifier) <= 128 and URLSAFE.match(verifier)
        digest = hashlib.sha256(verifier.encode('ascii')).digest()
        assert challenge == base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
        assert '=' not in challenge
        seen.add(verifier)
    assert len(seen) == 20


def test_rfc7636_appendix_b_vector():
    assert oauth.s256('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk') == 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'


def test_state_is_fresh_and_at_least_128_bits():
    states = {oauth.new_state() for _ in range(50)}
    assert len(states) == 50
    for s in states:
        assert len(base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))) * 8 >= 128


def test_authorize_url_carries_every_parameter():
    url = oauth.authorize_url(BASE, 'http://127.0.0.1:5/callback', 'chal', 'st', 'my-pc')
    u = urlsplit(url)
    assert url.startswith(BASE + '/oauth/authorize?')
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q == {'response_type': 'code', 'client_id': 'quafu-sdk', 'redirect_uri': 'http://127.0.0.1:5/callback',
                 'code_challenge': 'chal', 'code_challenge_method': 'S256', 'state': 'st', 'device_name': 'my-pc'}
    assert oauth.manual_redirect_uri(BASE) == BASE + '/oauth/code'


def test_device_name_is_printable_and_short(monkeypatch):
    monkeypatch.setattr(socket, 'gethostname', lambda: 'pc\x1b[31m' + 'x' * 100)
    name = oauth.device_name()
    assert len(name) == 64 and '\x1b' not in name


# ── U3 本机回环回调 ─────────────────────────────────────────────────

def test_loopback_binds_127_0_0_1_on_a_random_port():
    a, b = oauth.LoopbackReceiver('s1'), oauth.LoopbackReceiver('s2')
    try:
        assert a.httpd.server_address[0] == '127.0.0.1' and a.port > 0 and a.port != b.port
        assert a.redirect_uri == 'http://127.0.0.1:%d/callback' % a.port
    finally:
        a.close()
        b.close()


def test_wrong_state_is_400_and_does_not_count_then_one_good_callback_wins():
    r = oauth.LoopbackReceiver('good').start()
    try:
        status, body = get(r.port, '/callback?code=evil&state=bad')
        assert status == 400 and not r.done.is_set() and r.result is None
        assert get(r.port, '/elsewhere')[0] == 404
        status, body = get(r.port, '/callback?code=C0DE&state=good')
        assert status == 200 and '登录成功' in body
        assert r.done.wait(2) and r.result == ('code', 'C0DE')                # 回调先回 200 再 done.set()，这里等一下，不赶在它前面查
        assert get(r.port, '/callback?code=again&state=good')[0] == 400       # 只接受一次
        assert r.result == ('code', 'C0DE')
    finally:
        r.close()
    assert refused(r.port)                                                     # 完成后端口关闭


def test_denied_is_reported_as_an_error_result():
    r = oauth.LoopbackReceiver('s').start()
    try:
        get(r.port, '/callback?error=access_denied&state=s')
        assert r.result == ('error', 'access_denied')
    finally:
        r.close()


def test_code_never_reaches_stderr(capfd):
    r = oauth.LoopbackReceiver('s').start()
    try:
        get(r.port, '/callback?code=SECRETCODE123&state=s')
    finally:
        r.close()
    out, err = capfd.readouterr()
    assert 'SECRETCODE123' not in out + err


def test_port_is_closed_after_timeout():
    r = oauth.LoopbackReceiver('s').start()
    with pytest.raises(LoginFailed) as e:
        oauth.wait_for_code(r, None, 's', 0.3, io.StringIO())
    assert '分钟' in str(e.value) and 'QUAFU_API_KEY' in str(e.value)
    r.close()
    assert refused(r.port)


# ── U4 粘贴 ─────────────────────────────────────────────────────────

def test_pasted_code_hash_state():
    assert oauth.parse_pasted('  abc123#st \n', 'st') == 'abc123'
    assert oauth.parse_pasted(BASE + '/oauth/code?code=abc123&state=st', 'st') == 'abc123'


@pytest.mark.parametrize('text', ['abc123', '#st', 'abc123#', '', 'abc123#other'])
def test_bad_paste_is_login_failed(text):
    with pytest.raises(LoginFailed):
        oauth.parse_pasted(text, 'st')


# ── 两条路竞争 ───────────────────────────────────────────────────────

def test_paste_wins_when_it_arrives_first():
    r = oauth.LoopbackReceiver('st').start()
    try:
        code, redirect = oauth.wait_for_code(r, lambda prompt, stop, deadline: 'PASTED#st\n', 'st', 5, io.StringIO())
    finally:
        r.close()
    assert (code, redirect) == ('PASTED', None)


def test_loopback_wins_and_stops_the_reader():
    r = oauth.LoopbackReceiver('st').start()
    stopped = []

    def reader(prompt, stop, deadline):
        threading.Thread(target=lambda: (time.sleep(0.2), get(r.port, '/callback?code=LOOP&state=st')),
                         daemon=True).start()
        stopped.append(stop.wait(5))
        return None
    out = io.StringIO()
    try:
        code, redirect = oauth.wait_for_code(r, reader, 'st', 10, out)
    finally:
        r.close()
    assert stopped == [True] and (code, redirect) == ('LOOP', r.redirect_uri)
    assert '已在浏览器中完成授权' in out.getvalue()


def test_bad_paste_fails_instead_of_waiting():
    r = oauth.LoopbackReceiver('st').start()
    try:
        with pytest.raises(LoginFailed):
            oauth.wait_for_code(r, lambda p, s, d: 'x#wrong', 'st', 5, io.StringIO())
    finally:
        r.close()


def test_denied_in_browser_is_login_failed():
    r = oauth.LoopbackReceiver('st').start()

    def reader(prompt, stop, deadline):
        get(r.port, '/callback?error=access_denied&state=st')
        stop.wait(5)
        return None
    try:
        with pytest.raises(LoginFailed) as e:
            oauth.wait_for_code(r, reader, 'st', 10, io.StringIO())
    finally:
        r.close()
    assert '拒绝' in str(e.value)


def test_run_opens_the_loopback_url_and_prints_the_manual_one():
    opened, out = [], io.StringIO()
    seen = {}

    def browser(url):
        opened.append(url)
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        port = urlsplit(q['redirect_uri']).port
        threading.Thread(target=lambda: get(port, '/callback?code=OK&state=%s' % q['state']), daemon=True).start()
        return True

    def exchange(code, redirect_uri, verifier):
        seen.update(code=code, redirect_uri=redirect_uri, verifier=verifier)
        return {'access_token': 'x'}

    def reader(prompt, stop, deadline):
        stop.wait(5)
        return None
    token, device = oauth.run(BASE, exchange, reader=reader, out=out, browser=browser, timeout=10)
    q = {k: v[0] for k, v in parse_qs(urlsplit(opened[0]).query).items()}
    assert q['redirect_uri'].startswith('http://127.0.0.1:') and seen['redirect_uri'] == q['redirect_uri']
    assert seen['code'] == 'OK' and oauth.s256(seen['verifier']) == q['code_challenge']
    printed = re.search(r'https://\S+', out.getvalue()).group(0)
    pq = {k: v[0] for k, v in parse_qs(urlsplit(printed).query).items()}
    assert pq['redirect_uri'] == BASE + '/oauth/code' and pq['state'] == q['state']
    assert pq['code_challenge'] == q['code_challenge']
    assert seen['verifier'] not in out.getvalue()


def test_pasted_code_is_exchanged_with_the_manual_redirect_uri():
    seen = {}

    def exchange(code, redirect_uri, verifier):
        seen.update(code=code, redirect_uri=redirect_uri)
        return {}

    holder = {}

    def browser(url):
        holder['state'] = parse_qs(urlsplit(url).query)['state'][0]
        return False
    oauth.run(BASE, exchange, reader=lambda p, s, d: 'PASTE#' + holder['state'], out=io.StringIO(),
              browser=browser, timeout=5)
    assert seen == {'code': 'PASTE', 'redirect_uri': BASE + '/oauth/code'}


def test_interactive_detection(monkeypatch):
    class TTY(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    assert not oauth.interactive() and oauth.default_reader() is None
    # 只测「看不看 isatty()」：Windows 上另要真控制台（GitHub Actions 的 runner 没有），那一层由下面几条单独测
    monkeypatch.setattr(oauth, 'windows_console', lambda stream: True)
    monkeypatch.setattr(oauth, 'console_window_visible', lambda: True)
    monkeypatch.setattr('sys.stdin', TTY(''))
    assert oauth.interactive()
    monkeypatch.setattr('sys.stdin', None)
    assert not oauth.interactive()


def test_windows_nul_is_not_interactive(monkeypatch):
    """Windows 上空设备 NUL 是字符设备，isatty() 为真（DEVNULL、计划任务、< NUL 都是它）。只看 isatty() 会把它当终端，
    未登录时发起网页登录一直等授权码。所以 Windows 上还要 GetConsoleMode 成功（真的控制台）才算能交互。"""
    class NulLike(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr('sys.stdin', NulLike(''))
    monkeypatch.setattr(oauth, 'WINDOWS', True)
    monkeypatch.setattr(oauth, 'console_window_visible', lambda: True)
    monkeypatch.setattr(oauth, 'windows_console', lambda stream: False)       # NUL：GetConsoleMode 失败
    assert not oauth.interactive() and oauth.default_reader() is None
    monkeypatch.setattr(oauth, 'windows_console', lambda stream: True)        # 真控制台、窗口可见：行为不变
    assert oauth.interactive()
    monkeypatch.setattr(oauth, 'WINDOWS', False)                              # POSIX 只看 isatty()，不问控制台
    monkeypatch.setattr(oauth, 'windows_console', lambda stream: pytest.fail('POSIX 不该问控制台'))
    monkeypatch.setattr(oauth, 'console_window_visible', lambda: pytest.fail('POSIX 不该问窗口'))
    assert oauth.interactive()


def test_windows_hidden_or_windowless_console_is_not_interactive(monkeypatch):
    """窗口隐藏（Start-Process -WindowStyle Hidden）或没有窗口（CREATE_NO_WINDOW）的控制台，GetConsoleMode 照样成功，
    但没人能在里面敲字。Windows 上还要控制台窗口存在且可见才算能交互。"""
    class Console(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr('sys.stdin', Console(''))
    monkeypatch.setattr(oauth, 'WINDOWS', True)
    monkeypatch.setattr(oauth, 'windows_console', lambda stream: True)
    monkeypatch.setattr(oauth, 'console_window_visible', lambda: False)
    assert not oauth.interactive() and oauth.default_reader() is None


class FakeFn(object):
    """仿 ctypes 的函数对象：可以设 restype / argtypes，调用时返回给定值。"""
    def __init__(self, ret):
        self.ret, self.calls = ret, []

    def __call__(self, *args):
        self.calls.append(args)
        return self.ret


def fake_windll(monkeypatch, hwnd, visible):
    import ctypes
    k32 = type('K32', (), {'GetConsoleWindow': FakeFn(hwnd)})()
    u32 = type('U32', (), {'IsWindowVisible': FakeFn(visible)})()
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name: {'kernel32': k32, 'user32': u32}[name], raising=False)
    return k32, u32


@pytest.mark.parametrize('hwnd, visible, expect', [
    (0x1234, 1, True),        # 可见窗口（PowerShell、cmd、Windows Terminal 实测都是这样）
    (0x1234, 0, False),       # -WindowStyle Hidden：有窗口，看不见
    (None, 1, False),         # CREATE_NO_WINDOW：GetConsoleWindow() 返回空
    (0, 1, False),
])
def test_console_window_visible(monkeypatch, hwnd, visible, expect):
    k32, u32 = fake_windll(monkeypatch, hwnd, visible)
    assert oauth.console_window_visible() is expect
    if hwnd:
        assert u32.IsWindowVisible.calls == [(hwnd,)]
    else:
        assert u32.IsWindowVisible.calls == []           # 没有窗口就不再问可见性


def test_console_window_check_says_no_when_it_cannot_tell(monkeypatch):
    """查不了（不是 Windows 没有 WinDLL、加载失败、调用出错）一律当看不见：宁可报「未登录」，也不卡住等输入。"""
    import ctypes

    def boom(name):
        raise OSError('no such dll')
    monkeypatch.setattr(ctypes, 'WinDLL', boom, raising=False)
    assert oauth.console_window_visible() is False
    monkeypatch.delattr(ctypes, 'WinDLL', raising=False)
    assert oauth.console_window_visible() is False


def test_windows_console_check_says_no_when_it_cannot_tell():
    """查不了（没有 fileno、不是 Windows 没有 msvcrt）一律当不是控制台：宁可报「未登录」，也不卡住等输入。"""
    assert oauth.windows_console(io.StringIO('')) is False


def test_login_waits_one_hour_then_stops_with_a_hint(monkeypatch):
    """网页登录默认等一小时；到点自动结束，报 LoginFailed，说明等了多久、怎么重来、没浏览器时用 API Key。"""
    assert oauth.LOGIN_TIMEOUT == 3600
    import inspect
    assert inspect.signature(oauth.run).parameters['timeout'].default == 3600

    class NeverDone(object):                       # 回环一直没人回调；等的时长记下来，不真等
        waited = []
        result = None
        redirect_uri = None

        class done(object):
            @staticmethod
            def is_set():
                return False

            @staticmethod
            def wait(seconds):
                NeverDone.waited.append(seconds)
                return False
    with pytest.raises(LoginFailed) as e:
        oauth.wait_for_code(NeverDone, None, 'st', oauth.LOGIN_TIMEOUT, io.StringIO())
    assert 3590 < NeverDone.waited[0] <= 3600
    assert '60 分钟' in str(e.value) and 'quafu login' in str(e.value) and 'QUAFU_API_KEY' in str(e.value)


@pytest.mark.skipif(not hasattr(__import__('os'), 'pipe') or __import__('os').name != 'posix', reason='POSIX select')
def test_select_reader_reads_a_line_or_stops(monkeypatch):
    import os
    r, w = os.pipe()
    rf = os.fdopen(r, 'r')
    monkeypatch.setattr('sys.stdin', rf)
    monkeypatch.setattr('sys.stdout', io.StringIO())
    stop = threading.Event()
    os.write(w, b'CODE#st\n')
    assert oauth._read_select('授权码：', stop, time.monotonic() + 5) == 'CODE#st\n'
    threading.Timer(0.3, stop.set).start()
    t0 = time.monotonic()
    assert oauth._read_select('授权码：', stop, time.monotonic() + 5) is None
    assert time.monotonic() - t0 < 2
    os.close(w)
    rf.close()


def test_notebook_reader_is_interrupted_when_the_loopback_wins(monkeypatch):
    def blocking_input(prompt=''):
        while True:
            time.sleep(0.01)
    monkeypatch.setattr('builtins.input', blocking_input)
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    assert oauth._read_input('授权码：', stop, time.monotonic() + 5) is None
    monkeypatch.setattr('builtins.input', lambda prompt='': 'CODE#st')
    assert oauth._read_input('授权码：', threading.Event(), time.monotonic() + 5) == 'CODE#st'
    time.sleep(0.5)                                  # 看门线程已收手，不会再打断主线程


def test_notebook_reader_lets_a_real_ctrl_c_through(monkeypatch):
    def interrupted(prompt=''):
        raise KeyboardInterrupt
    monkeypatch.setattr('builtins.input', interrupted)
    with pytest.raises(KeyboardInterrupt):
        oauth._read_input('授权码：', threading.Event(), time.monotonic() + 5)


# ── 打开浏览器：WSL 交给 Windows 默认浏览器；任何系统都不让浏览器往终端写字──

OPENERS = (('wslview',), ('rundll32.exe', 'url.dll,FileProtocolHandler'))   # conftest 把它清空了，这里装回


def _fake_popen(calls):
    class P:
        def __init__(self, cmd, **kw):
            calls.append((cmd, kw))
    return P


def test_wsl_opens_the_windows_default_browser_quietly(monkeypatch):
    calls = []
    monkeypatch.setattr(oauth.sys, 'platform', 'linux')
    monkeypatch.setattr(oauth, 'is_wsl', lambda: True)
    monkeypatch.setattr(oauth, 'WSL_OPENERS', OPENERS)
    monkeypatch.setattr(oauth.shutil, 'which', lambda name: '/x/' + name if name == 'rundll32.exe' else None)
    monkeypatch.setattr(oauth.os.path, 'exists', lambda p: True)
    monkeypatch.setattr(oauth.subprocess, 'Popen', _fake_popen(calls))
    monkeypatch.setattr(oauth.webbrowser, 'open', lambda url: pytest.fail('should not use webbrowser in WSL'))
    url = 'https://quafu.com.cn/oauth/authorize?a=1&b=2'
    assert oauth.launch_browser(url) is True
    (cmd, kw), = calls
    assert cmd == ['/x/rundll32.exe', 'url.dll,FileProtocolHandler', url]      # 整条链接一个参数，& 不经 shell
    assert kw['stdout'] is oauth.subprocess.DEVNULL and kw['stderr'] is oauth.subprocess.DEVNULL


def test_wsl_prefers_wslview_when_installed(monkeypatch):
    calls = []
    monkeypatch.setattr(oauth.sys, 'platform', 'linux')
    monkeypatch.setattr(oauth, 'is_wsl', lambda: True)
    monkeypatch.setattr(oauth, 'WSL_OPENERS', OPENERS)
    monkeypatch.setattr(oauth.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(oauth.os.path, 'exists', lambda p: True)
    monkeypatch.setattr(oauth.subprocess, 'Popen', _fake_popen(calls))
    assert oauth.launch_browser('https://e/x') and calls[0][0] == ['/usr/bin/wslview', 'https://e/x']


def test_wsl_without_windows_interop_falls_back(monkeypatch):
    monkeypatch.setattr(oauth.sys, 'platform', 'linux')
    monkeypatch.setattr(oauth, 'is_wsl', lambda: True)
    monkeypatch.setattr(oauth, 'WSL_OPENERS', OPENERS)
    monkeypatch.setattr(oauth.shutil, 'which', lambda name: None)
    monkeypatch.setattr(oauth.os.path, 'exists', lambda p: False)
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.setattr(oauth.webbrowser, 'open', lambda url: False)
    assert oauth.launch_browser('https://e/x') is False


def test_linux_desktop_uses_xdg_open_quietly(monkeypatch):
    calls = []
    monkeypatch.setattr(oauth.sys, 'platform', 'linux')
    monkeypatch.setattr(oauth, 'is_wsl', lambda: False)
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setattr(oauth.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(oauth.os.path, 'exists', lambda p: True)
    monkeypatch.setattr(oauth.subprocess, 'Popen', _fake_popen(calls))
    assert oauth.launch_browser('https://e/x')
    (cmd, kw), = calls
    assert cmd == ['/usr/bin/xdg-open', 'https://e/x'] and kw['stderr'] is oauth.subprocess.DEVNULL


def test_macos_and_windows_keep_webbrowser(monkeypatch):
    for platform in ('darwin', 'win32'):
        monkeypatch.setattr(oauth.sys, 'platform', platform)
        monkeypatch.setattr(oauth.subprocess, 'Popen', lambda *a, **k: pytest.fail('no subprocess'))
        monkeypatch.setattr(oauth.webbrowser, 'open', lambda url: True)
        assert oauth.launch_browser('https://e/x') is True


def test_is_wsl_reads_env_or_kernel_release(monkeypatch, tmp_path):
    monkeypatch.setenv('WSL_DISTRO_NAME', 'Ubuntu')
    assert oauth.is_wsl()
    monkeypatch.delenv('WSL_DISTRO_NAME')
    real_open = open

    def fake_open(path, *a, **k):
        if path == '/proc/sys/kernel/osrelease':
            f = tmp_path / 'rel'
            f.write_text('6.6.87.2-microsoft-standard-WSL2')
            return real_open(f, *a, **k)
        return real_open(path, *a, **k)
    monkeypatch.setattr('builtins.open', fake_open)
    assert oauth.is_wsl()


# ── 等粘贴时自己管这一行：方向键整段丢掉、光标挪不进提示语、退格只删自己敲的字──

def _editor():
    shown = []
    return oauth.LineEditor(shown.append), shown


def test_editor_drops_arrow_keys_and_echoes_only_typed_text():
    ed, shown = _editor()
    assert ed.feed('\x1b[D\x1b[D\x1b[DAB') is None
    assert ed.feed('C#st\x1b[C\r') == 'ABC#st\n'
    assert '\x1b' not in ''.join(shown) and ''.join(shown).startswith('ABC#st')


def test_editor_backspace_never_reaches_the_prompt():
    ed, shown = _editor()
    ed.feed('ab\x7f\x7f\x7f\x7f')
    assert ''.join(shown) == 'ab' + '\b \b' * 2                    # 只退两格，多按的不动提示语
    assert ed.feed('Z\n') == 'Z\n'


def test_editor_escape_split_across_reads_and_ctrl_u_ctrl_d():
    ed, shown = _editor()
    assert ed.feed('x\x1b[') is None and ed.feed('Dy') is None    # 序列被切成两半也整段丢掉
    assert ed.buf == ['x', 'y']
    ed.feed('\x15')
    assert ed.buf == [] and ed.feed('\x04') == ''                 # 空行 Ctrl+D = EOF
    ed.feed('q')
    assert ed.feed('\x04') is None                                # 有字时 Ctrl+D 不算


@pytest.mark.skipif(not hasattr(__import__('os'), 'openpty'), reason='POSIX only')
def test_read_select_on_a_terminal_uses_raw_mode_and_restores_it(monkeypatch):
    import os
    import pty
    import termios
    master, slave = pty.openpty()
    stdin = os.fdopen(slave, 'r', buffering=1, closefd=True)
    out = io.StringIO()
    monkeypatch.setattr(oauth.sys, 'stdin', stdin)
    monkeypatch.setattr(oauth.sys, 'stdout', out)
    before = termios.tcgetattr(slave)
    seen = {}
    real_select = __import__('select').select

    def spy(*a):
        seen['lflag'] = termios.tcgetattr(slave)[3]
        return real_select(*a)
    monkeypatch.setattr('select.select', spy)
    os.write(master, b'\x1b[D\x1b[D\x1b[DABC#st\x1b[C\r')
    try:
        line = oauth._read_select('> ', threading.Event(), time.monotonic() + 5)
        assert line.strip() == 'ABC#st'
        assert not seen['lflag'] & (termios.ICANON | termios.ECHO)    # 等的时候终端不自己回显
        assert seen['lflag'] & termios.ISIG                          # Ctrl+C 照旧
        # PENDIN（「待重打输入」）由终端驱动自己置（macOS 上读完会带上），不是 _read_select 改的；比 lflag 时去掉这一位，其余逐项比
        pendin = getattr(termios, 'PENDIN', 0)
        after = termios.tcgetattr(slave)
        after[3] &= ~pendin
        before[3] &= ~pendin
        assert after == before                                       # 读完原样恢复
        assert '\x1b' not in out.getvalue() and 'ABC#st' in out.getvalue()
    finally:
        stdin.close()
        os.close(master)


def test_escape_sequences_are_removed():
    assert oauth.ESCAPE_SEQ.sub('', '\x1b[D\x1b[1;5CZ\x1bOA') == 'Z'
