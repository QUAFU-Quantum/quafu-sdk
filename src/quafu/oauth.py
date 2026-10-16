# -*- coding: utf-8 -*-
"""网页登录：OAuth 2.0 授权码 + PKCE（RFC 6749 / RFC 7636 / RFC 8252），公开客户端，没有 client_secret。

一次登录（照 Claude Code 的做法）：
  1. 生成 code_verifier、code_challenge（S256）与 state；在 127.0.0.1 的随机端口起一个只收一次回调的监听。
  2. 拼两个授权地址，参数相同、只有 redirect_uri 不同：
       自动地址 redirect_uri=http://127.0.0.1:<端口>/callback   —— 用 launch_browser 打开它
       手动地址 redirect_uri={BASE_URL}/oauth/code              —— 打印它；授权后网页显示「授权码#state」
  3. 本机回环回调与「把授权码粘回终端」两条路同时等，谁先到用谁，不判断自己是不是在 SSH / 容器 / WSL 里。
  4. 校验 state，用 code + code_verifier + 与授权时一致的 redirect_uri 换令牌。

授权码、verifier、令牌都不进日志：回环监听的访问日志整个关掉（请求行里就有授权码）。

等授权码时顺带可以切换界面语言：
  - 还没选过语言（没有 QUAFU_LANG、没有 set_language()、本机没存）且能交互时，提示末尾附一行另一种语言的切换提示：
    英文界面附「使用中文请按 Z 并回车。」，中文界面附「Press E then Enter to set English as display language.」。
  - 规则：输入去掉首尾空白后恰好是单个字母 Z / z（切中文）或 E / e（切英文）并回车，就切换语言、写进本机设置
    （同 quafu config set language）、用新语言重打提示并继续等。Windows 逐字符读法下，还没输入任何字符时单独按下
    该键（之后 SOLO_KEY_WAIT 秒内没有别的字符跟着，即不是粘贴进来的一串的开头）立即生效，不必回车。
  - 授权码是「授权码#校验码」或整条回调地址，不会是单个字母，所以不与粘贴冲突。
  - 不能交互（标准输入不是终端、不在 notebook）时根本不读输入，也不显示这一行。"""
import base64
import hashlib
import http.server
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlsplit

from . import _i18n
from ._i18n import t
from .errors import LoginFailed

log = logging.getLogger('quafu')

CLIENT_ID = 'quafu-sdk'
AUTHORIZE_PATH = '/oauth/authorize'          # 网站页面，挂在 BASE_URL 下
MANUAL_REDIRECT_PATH = '/oauth/code'         # 网站页面：显示「授权码#state」让用户复制
TOKEN_PATH = '/oauth/token'                  # 程序端，挂在 {BASE_URL}/api/v1 下
REVOKE_PATH = '/oauth/revoke'
LOGIN_TIMEOUT = 3600.0                       # 整个等待的上限（秒）：一小时，够在网页上操作完
REVOKE_TIMEOUT = 5.0
LOOPBACK_HOST = '127.0.0.1'                  # RFC 8252 §7.3：写字面回环地址，不写 localhost
CALLBACK_PATH = '/callback'
POLL = 0.2
SOLO_KEY_WAIT = 0.05                         # Windows：单独按键与粘贴开头的分界（粘贴的字符是连着到的）
LANG_KEYS = {'z': 'zh', 'e': 'en'}
DEVICE_NAME_MAX = 64

PAGE = '''<!doctype html><html lang="%s"><head><meta charset="utf-8"><title>QUAFU</title></head>
<body style="font-family:system-ui,sans-serif;margin:4em auto;max-width:32em;line-height:1.6">
<h1 style="font-size:1.4em">%s</h1><p>%s</p></body></html>'''


# ── PKCE 与 state ─────────────────────────────────────────────────────

def pkce_pair():
    """(code_verifier, code_challenge)。verifier 86 位，字符集 [A-Za-z0-9-_]（RFC 7636 §4.1 允许的子集）；
    challenge = BASE64URL(SHA256(verifier))，不带填充。"""
    verifier = secrets.token_urlsafe(64)
    return verifier, s256(verifier)


def s256(verifier):
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def new_state():
    """256 bit 随机串，每次登录一个。"""
    return secrets.token_urlsafe(32)


def device_name():
    """授权页与网站「已登录的设备」上显示的名字：主机名，去掉控制字符，最长 64 字。"""
    try:
        name = socket.gethostname()
    except OSError:
        name = ''
    name = ''.join(ch for ch in name if ch.isprintable()).strip()
    return (name or 'unknown')[:DEVICE_NAME_MAX]


def authorize_url(base_url, redirect_uri, challenge, state, device):
    q = {'response_type': 'code', 'client_id': CLIENT_ID, 'redirect_uri': redirect_uri,
         'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state, 'device_name': device}
    return base_url + AUTHORIZE_PATH + '?' + urlencode(q)


def manual_redirect_uri(base_url):
    return base_url + MANUAL_REDIRECT_PATH


# ── 本机回环回调 ─────────────────────────────────────────────────────

class LoopbackReceiver(object):
    """在 127.0.0.1 的系统分配端口上等一次 GET /callback?code=…&state=…（或 error=…）。

    state 不符回 400、不算数、继续等（别的网页往这个端口乱发请求不能打断登录）；收到一次有效回调就结束，
    之后的请求一律 400。result 是 ('code', 授权码) 或 ('error', 错误码)。close() 之后端口关闭。"""

    def __init__(self, state):
        self.state = state
        self.result = None
        self.done = threading.Event()
        self._stop = threading.Event()
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                receiver._handle(self)

            def log_message(self, *args):          # 请求行里有授权码：一个字都不记
                pass

        self.httpd = http.server.HTTPServer((LOOPBACK_HOST, 0), Handler)
        self.httpd.timeout = POLL
        self.port = self.httpd.server_address[1]
        self.redirect_uri = 'http://%s:%d%s' % (LOOPBACK_HOST, self.port, CALLBACK_PATH)
        self._thread = threading.Thread(target=self._serve, name='quafu-login-callback', daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _serve(self):
        while not self._stop.is_set():
            self.httpd.handle_request()

    def _reply(self, handler, status, title, text):
        body = (PAGE % (t('oauth.html_lang'), t(title), t(text))).encode('utf-8')
        handler.send_response(status)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Cache-Control', 'no-store')
        handler.end_headers()
        handler.wfile.write(body)

    def _handle(self, handler):
        u = urlsplit(handler.path)
        if u.path != CALLBACK_PATH:
            return self._reply(handler, 404, 'oauth.page.not_found.title', 'oauth.page.not_found.text')
        if self.done.is_set():
            return self._reply(handler, 400, 'oauth.page.done.title', 'oauth.page.done.text')
        q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        if not secrets.compare_digest(q.get('state', ''), self.state):
            return self._reply(handler, 400, 'oauth.page.failed.title', 'oauth.page.mismatch.text')
        if q.get('error'):
            self.result = ('error', q['error'])
            self._reply(handler, 200, 'oauth.page.denied.title', 'oauth.page.denied.text')
        elif q.get('code'):
            self.result = ('code', q['code'])
            self._reply(handler, 200, 'oauth.page.success.title', 'oauth.page.success.text')
        else:
            return self._reply(handler, 400, 'oauth.page.failed.title', 'oauth.page.no_code.text')
        self.done.set()

    def close(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(2 * POLL + 1)
        self.httpd.server_close()


# ── 粘贴授权码 ───────────────────────────────────────────────────────

def parse_pasted(text, state):
    """粘回来的「授权码#state」→ 授权码。也认整条回调地址（…?code=…&state=…）。
    缺一半或 state 不符抛 LoginFailed——不拿它去换令牌。"""
    text = (text or '').strip()
    if '?' in text and 'code=' in text:
        q = {k: v[0] for k, v in parse_qs(urlsplit(text).query).items()}
        code, got = q.get('code', ''), q.get('state', '')
    else:
        code, _, got = text.partition('#')
    code, got = code.strip(), got.strip()
    if not code or not got:
        raise LoginFailed(t('oauth.paste_incomplete'))
    if not secrets.compare_digest(got, state):
        raise LoginFailed(t('oauth.paste_mismatch'))
    return code


def language_key(line):
    """粘贴框里的输入是不是切换语言的按键：去掉首尾空白后恰好是单个 Z / E（不分大小写）→ 'zh' / 'en'，否则 None。"""
    s = (line or '').strip()
    return LANG_KEYS.get(s.lower()) if len(s) == 1 else None


def switch_language(lang, out):
    """切到 lang：本进程立即生效（盖过环境变量，按了键就该看到变化），并写进本机设置；写不进去只提示，不打断登录。"""
    _i18n.set_language(lang)
    try:
        _i18n.save_language(lang)
    except OSError as e:
        out.write(t('oauth.lang_save_failed', type(e).__name__))


def in_notebook():
    """是否在 IPython 内核里（Jupyter、JupyterLab、Colab 一类）。"""
    ipy = sys.modules.get('IPython')
    try:
        shell = ipy.get_ipython() if ipy is not None else None
    except Exception:
        return False
    return shell is not None and getattr(shell, 'kernel', None) is not None


def windows_console(stream):
    """Windows：stream 是不是真的控制台。

    为什么不能只看 isatty()：Windows 上它只问「是不是字符设备」，空设备 NUL 也是字符设备，于是标准输入接到 NUL
    （subprocess.DEVNULL、计划任务、后台脚本里的 < NUL）时 isatty() 为真，未登录就会发起网页登录、一直等授权码。
    GetConsoleMode 只对控制台句柄成功，对 NUL、文件、管道都失败，所以用它分辨。查不了（没有 fileno、句柄无效）一律当不是。"""
    try:
        import ctypes
        import msvcrt
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_ulong()
        return bool(ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)))
    except Exception:
        return False


def console_window_visible():
    """Windows：本进程的控制台有没有一个看得见的窗口。

    为什么还要问这个：GetConsoleMode 只分辨「是不是控制台」，分不出「控制台前面有没有人」。窗口被隐藏的控制台
    （Start-Process -WindowStyle Hidden、某些计划任务）和根本没有窗口的控制台（父进程用 CREATE_NO_WINDOW 启动）
    照样是真控制台句柄，没人能在里面敲字，未登录时会一直等授权码。所以再要求 GetConsoleWindow() 有窗口、
    且 IsWindowVisible 为真。最小化的窗口仍算可见；Windows Terminal 下拿到的伪窗口同样可见。
    查不了一律当看不见。"""
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32')        # 自己的实例：设返回类型不影响 ctypes.windll 的全局对象
        user32 = ctypes.WinDLL('user32')
        kernel32.GetConsoleWindow.restype = wintypes.HWND   # 句柄是指针宽度，默认的 int 在 64 位上会截断
        kernel32.GetConsoleWindow.argtypes = []
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        hwnd = kernel32.GetConsoleWindow()
        return bool(hwnd) and bool(user32.IsWindowVisible(hwnd))
    except Exception:
        return False


WINDOWS = os.name == 'nt'


def interactive():
    """当前进程能不能问人：标准输入是终端，或在 notebook 内核里。
    Windows 上终端还要是真的控制台（NUL 不算），且控制台窗口看得见（隐藏窗口、没有窗口的控制台不算）。
    CI、管道、后台任务、计划任务都不能。"""
    if in_notebook():
        return True
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    if not WINDOWS:
        return True
    return windows_console(sys.stdin) and console_window_visible()


ESCAPE_SEQ = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|O.|.)')   # 终端发来的方向键之类（ESC [ D …）
ESCAPE_TAIL = re.compile(r'\x1b(?:\[[0-?]*[ -/]*|O)?$')          # 被一次读切断的半截序列，留到下次读


class LineEditor:
    """等粘贴授权码时自己管这一行：只能在末尾敲字、粘贴、退格，光标挪不进提示语。

    为什么：终端自己的行编辑（ICANON + ECHO）会把方向键回显出来——
    在终端里点一下，终端发一串方向键想把光标挪到点击处，回显成「^[[D」后越点越多；改成原样回显又能把光标挪进
    提示语，打字就把提示语盖掉了。所以等粘贴时关掉终端的行编辑与回显（ISIG 保留，Ctrl+C 照旧），由这里自己回显：
    方向键等控制序列整段丢掉，退格只删自己敲的字，Ctrl+U 清空本行，回车提交，空行时 Ctrl+D 当 EOF。"""

    def __init__(self, write):
        self.write = write
        self.buf = []
        self.pending = ''

    def feed(self, text):
        """喂进一段输入；回车时返回这一行（不含换行），空行 Ctrl+D 返回 ''，否则返回 None。"""
        text = self.pending + text
        self.pending = ''
        m = ESCAPE_TAIL.search(text)
        if m:
            text, self.pending = text[:m.start()], text[m.start():]
        text = ESCAPE_SEQ.sub('', text)
        for ch in text:
            if ch in '\r\n':
                self.write('\r\n')
                line, self.buf = ''.join(self.buf), []
                return line + '\n'
            if ch in '\x7f\x08':
                if self.buf:
                    self.buf.pop()
                    self.write('\b \b')
            elif ch == '\x15':
                self.write('\b \b' * len(self.buf))
                self.buf = []
            elif ch == '\x04':
                if not self.buf:
                    return ''
            elif ch >= ' ':
                self.buf.append(ch)
                self.write(ch)
        return None


def _raw_mode():
    """关掉终端的行编辑与回显（保留 ISIG），返回恢复用的函数；不是终端时返回 None。"""
    try:
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = list(old)
        new[3] &= ~(termios.ICANON | termios.ECHO)
        new[6] = list(new[6])
        new[6][termios.VMIN], new[6][termios.VTIME] = 1, 0
        termios.tcsetattr(fd, termios.TCSANOW, new)
    except Exception:
        return None

    def restore():
        try:
            termios.tcsetattr(fd, termios.TCSANOW, old)
        except Exception:
            pass
    return restore


def _read_select(prompt, stop, deadline):
    """POSIX 终端：主线程上用 select 轮询标准输入，回环先到或到时限就不再等，不留读 stdin 的后台线程。
    是终端时用 LineEditor 自己管这一行；不是终端（测试里的管道）时按行读。"""
    import codecs
    import select
    sys.stdout.write(prompt)
    sys.stdout.flush()
    restore = _raw_mode()
    fd = sys.stdin.fileno()
    editor = LineEditor(lambda s: (sys.stdout.write(s), sys.stdout.flush()))
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    try:
        while not stop.is_set() and time.monotonic() < deadline:
            ready, _, _ = select.select([sys.stdin], [], [], POLL)
            if not ready:
                continue
            if restore is None:
                line = sys.stdin.readline()
            else:
                chunk = os.read(fd, 4096)
                line = editor.feed(decoder.decode(chunk)) if chunk else ''
                if line is None:
                    continue
            if line == '':                         # EOF（Ctrl-D）：不再从终端等，只等回环
                stop.wait(max(0.0, deadline - time.monotonic()))
                return None
            line = ESCAPE_SEQ.sub('', line)
            if line.strip():
                return line
        return None
    finally:
        if restore is not None:
            restore()


def _read_msvcrt(prompt, stop, deadline):
    """Windows 控制台：msvcrt 逐字符轮询，理由同上。"""
    import msvcrt
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf = []
    while not stop.is_set() and time.monotonic() < deadline:
        while msvcrt.kbhit():
            ch = msvcrt.getwche()
            if ch in ('\r', '\n'):
                sys.stdout.write('\n')
                if ''.join(buf).strip():
                    return ''.join(buf)
                buf = []
            elif ch == '\x03':
                raise KeyboardInterrupt
            elif ch == '\x08':
                if buf:
                    buf.pop()
                    sys.stdout.write(' \x08')
            elif not buf and ch.lower() in LANG_KEYS:
                time.sleep(SOLO_KEY_WAIT)          # 粘贴的一串会紧跟着到；单独按下的键后面没有字符
                if not msvcrt.kbhit():
                    sys.stdout.write('\n')
                    return ch
                buf.append(ch)
            else:
                buf.append(ch)
        time.sleep(0.05)
    return None


def _read_input(prompt, stop, deadline):
    """notebook：只能在主线程上 input()。回环先到或到时限时，由看门线程 interrupt_main 打断它；
    notebook 里那个输入框可能残留，提示可以忽略（不为此引入 ipywidgets）。"""
    import _thread
    lock = threading.Lock()
    state = {'finished': False, 'interrupted': False}

    def watch():
        while not stop.wait(POLL):
            if time.monotonic() >= deadline:
                break
        with lock:
            if not state['finished']:
                state['interrupted'] = True
                _thread.interrupt_main()

    threading.Thread(target=watch, name='quafu-login-watch', daemon=True).start()
    try:
        try:
            line = input(prompt)
        finally:
            with lock:
                state['finished'] = True
        return line
    except KeyboardInterrupt:
        if state['interrupted']:
            return None
        raise
    finally:
        stop.set()


def default_reader():
    """按环境挑读粘贴的方式；不能交互时为 None（只等回环）。"""
    if in_notebook():
        return _read_input
    if not interactive():
        return None
    if os.name == 'nt':
        return _read_msvcrt
    return _read_select


# ── 一次完整的网页登录 ───────────────────────────────────────────────

def wait_for_code(receiver, reader, state, timeout, out, show=None):
    """回环与粘贴竞争，返回 (授权码, 它对应的 redirect_uri)。
    reader 为 None 时只等回环。拒绝授权、超时、粘贴不对都抛 LoginFailed。
    读到切换语言的按键（language_key）时切换、调 show() 用新语言重打提示，然后接着等。"""
    deadline = time.monotonic() + timeout
    line = None
    if reader is not None:
        stop = threading.Event()

        def relay():                               # 回环先到就让读粘贴的那一路停下
            while not stop.is_set() and time.monotonic() < deadline:
                if receiver.done.wait(POLL):
                    stop.set()
        threading.Thread(target=relay, name='quafu-login-relay', daemon=True).start()
        while True:
            line = reader(t('oauth.code_prompt'), stop, deadline)
            lang = language_key(line)
            if lang is None:
                break
            switch_language(lang, out)
            if show is not None:
                show(switched=True)
        stop.set()
    if line is None and not receiver.done.is_set():
        receiver.done.wait(max(0.0, deadline - time.monotonic()))
    if receiver.done.is_set():
        if reader is not None and line is None:
            out.write(t('oauth.done_in_browser_notebook' if in_notebook() else 'oauth.done_in_browser'))
        kind, value = receiver.result
        if kind == 'error':
            if value == 'access_denied':
                raise LoginFailed(t('oauth.denied'))
            raise LoginFailed(t('oauth.failed', value))
        return value, receiver.redirect_uri
    if line is not None:
        return parse_pasted(line, state), None
    raise LoginFailed(t('oauth.timeout', round(timeout / 60)))


# ── 打开浏览器 ────────────────────────────────────────────────────────
# 原则：尽量符合用户习惯，但不为 WSL 搞复杂。
#   - WSL 里的人日常用的是 Windows 上的浏览器，QUAFU 也登录在那里；webbrowser 在 WSL 里会找到 WSL 自己装的
#     Linux 浏览器（经 WSLg），那里多半没登录，还把它的启动日志打进终端。所以检测到 WSL 就交给 Windows 默认浏览器。
#   - 不分 WSL 的网络模式：mirrored 下回环地址本来共用；NAT（默认）下 WSL 默认开着 localhostForwarding，Windows
#     访问 127.0.0.1 会转进 WSL。两种都到不了时，「把授权码粘回终端」那条路照样在等，不会卡住。
#   - 任何系统都不让浏览器往终端里写字：子进程的输出一律丢掉。
WSL_OPENERS = (('wslview',), ('rundll32.exe', 'url.dll,FileProtocolHandler'),
               ('/mnt/c/Windows/System32/rundll32.exe', 'url.dll,FileProtocolHandler'))


def is_wsl():
    if os.environ.get('WSL_DISTRO_NAME'):
        return True
    try:
        with open('/proc/sys/kernel/osrelease', encoding='ascii', errors='replace') as f:
            return 'microsoft' in f.read().lower()
    except OSError:
        return False


def _spawn(cmd):
    """后台起一个打开链接的进程，输入输出都接到空设备；起得来就算打开了。"""
    exe = cmd[0] if os.path.isabs(cmd[0]) else shutil.which(cmd[0])
    if not exe or not os.path.exists(exe):
        return False
    try:
        subprocess.Popen([exe, *cmd[1:]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def launch_browser(url):
    """在用户惯用的浏览器里打开 url，不往终端写任何东西。返回是否打开了。
    rundll32 直接收参数、不经 cmd 解析，链接里的 & 不用转义。"""
    if sys.platform.startswith('linux'):
        if is_wsl():
            for cmd in WSL_OPENERS:
                if _spawn([*cmd, url]):
                    return True
        if (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and _spawn(['xdg-open', url]):
            return True
    return webbrowser.open(url)


def run(base_url, exchange, open_browser=True, timeout=LOGIN_TIMEOUT, reader='auto', out=None, browser=None):
    """走一遍网页登录，返回令牌端点的响应（dict）。exchange(code, redirect_uri, verifier) 负责换令牌。

    reader='auto' 按环境挑（不能交互时只等回环）；测试可传入自己的读法。browser 默认 launch_browser。"""
    out = out or sys.stdout
    if reader == 'auto':
        reader = default_reader()
    verifier, challenge = pkce_pair()
    state = new_state()
    device = device_name()
    receiver = LoopbackReceiver(state).start()
    try:
        auto = authorize_url(base_url, receiver.redirect_uri, challenge, state, device)
        manual = authorize_url(base_url, manual_redirect_uri(base_url), challenge, state, device)
        opened = False
        if open_browser:
            try:
                opened = bool((browser or launch_browser)(auto))
            except Exception:
                opened = False
        hint = reader is not None and _i18n.resolve()[1] == 'default'     # 还没选过语言才附切换提示

        def show(switched=False):
            if reader is not None:
                if switched:
                    out.write('\n')
                out.write(t('oauth.open_link', manual))
                out.write(t('oauth.paste_hint_opened' if opened else 'oauth.paste_hint'))
                if hint or switched:
                    out.write(t('oauth.lang_hint'))
            else:
                out.write(t('oauth.open_link_local', round(timeout / 60), auto))
            out.flush()
        show()
        code, redirect_uri = wait_for_code(receiver, reader, state, timeout, out, show)
    finally:
        receiver.close()
    return exchange(code, redirect_uri or manual_redirect_uri(base_url), verifier), device
