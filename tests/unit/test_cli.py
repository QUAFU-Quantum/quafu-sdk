# -*- coding: utf-8 -*-
"""命令行 quafu login / logout / whoami 与退出码。传输层用假的。"""
import io
import json
import subprocess
import sys
from datetime import timedelta

import pytest

import quafu
from quafu import cli, credentials, oauth
from quafu.credentials import Credential

from ..helpers import BASE, KEY, ME, SUBPROCESS_TIMEOUT, TOKEN, TOKEN_OK, UNAUTHORIZED

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py


@pytest.fixture
def run(fake, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_transport', fake)

    def run(*argv, stdin=None):
        monkeypatch.setattr(sys, 'stdin', io.StringIO(stdin or ''))
        code = cli.main(list(argv))
        out, err = capsys.readouterr()
        return code, out, err
    return run


def test_version_matches_the_package():
    assert cli.VERSION == quafu.__version__


def test_login_api_key_from_stdin_saves_and_shows_only_the_mask(run, fake):
    fake.route('GET', '/auth/me', ME)
    code, out, err = run('login', '--api-key', '-', stdin=KEY + '\n')
    assert code == 0 and KEY not in out + err and 'u7f3a9c2b' in out and '不过期' in out
    assert credentials.saved(BASE).mask == KEY[:11] + '...'


def test_login_api_key_rejected_exits_1_without_a_traceback(run, fake):
    fake.route('GET', '/auth/me', UNAUTHORIZED)
    code, out, err = run('login', '--api-key', '-', stdin=KEY + '\n')
    assert code == 1 and err.startswith('错误：') and 'Traceback' not in err
    assert credentials.saved(BASE) is None


def test_login_web_flow_with_no_browser_flag(run, fake, monkeypatch):
    """--no-browser 只打印链接；这里由测试代替人去「点」本机回调。"""
    import http.client
    import threading
    from urllib.parse import parse_qs, urlsplit
    monkeypatch.setattr(oauth, 'default_reader', lambda: None)
    fake.route('POST', '/oauth/token', TOKEN_OK)
    fake.route('GET', '/auth/me', ME)
    opened = []
    monkeypatch.setattr(oauth, 'launch_browser', lambda url: opened.append(url) or True)
    real_run = oauth.run

    def run_and_click(*a, **kw):
        out = kw['out'] = io.StringIO()

        def click():
            import time
            for _ in range(100):
                text = out.getvalue()
                if 'https://' in text:
                    break
                time.sleep(0.02)
            url = text[text.index('https://'):].split()[0]
            q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
            port = urlsplit(q['redirect_uri']).port
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            c.request('GET', '/callback?code=X&state=%s' % q['state'])
            c.getresponse().read()
        threading.Thread(target=click, daemon=True).start()
        return real_run(*a, **kw)
    monkeypatch.setattr(oauth, 'run', run_and_click)
    code, out, err = run('login', '--no-browser')
    assert code == 0, err
    assert opened == [] and '网页登录' in out and credentials.saved(BASE).kind == 'oauth'
    assert out.count('已登录') == 1, out            # 曾经连打两行「已登录」


def test_logout_messages(run, fake):
    fake.route('POST', '/oauth/revoke', (200, {}))
    exp = (credentials.now() + timedelta(days=30)).isoformat(timespec='seconds')
    credentials.save(BASE, Credential(TOKEN, 'oauth', 'saved', expires_at=exp))
    code, out, err = run('logout')
    assert code == 0 and '已退出登录' in out and '撤销' in out
    code, out, err = run('logout')
    assert code == 0 and '未保存' in out


def test_whoami_text_and_json(run, fake, monkeypatch):
    monkeypatch.setenv('QUAFU_API_KEY', KEY)
    fake.route('GET', '/auth/me', ME)
    code, out, err = run('whoami')
    assert code == 0 and '甲（u7f3a9c2b）' in out and '环境变量 QUAFU_API_KEY' in out and KEY not in out
    code, out, err = run('whoami', '--json')
    assert json.loads(out)['source'] == 'env'


def test_not_logged_in_exits_1_with_a_hint_on_stdout_and_a_log_record(run, caplog):
    """不能交互又没登录：说明（含 quafu login 与 QUAFU_API_KEY）打到 stdout，logger quafu 记一条 WARNING，退出码 1。
    计划任务、后台脚本常常只收 stdout，所以不只写 stderr。"""
    with caplog.at_level('WARNING', logger='quafu'):
        code, out, err = run('whoami')
    assert code == 1 and 'Traceback' not in out + err
    assert out.startswith('错误：未登录 QUAFU（%s）' % BASE) and 'quafu login' in out and 'QUAFU_API_KEY' in out
    assert [(r.levelname, r.getMessage()) for r in caplog.records if r.name == 'quafu'] == [
        ('WARNING', '未登录 QUAFU（%s）；当前无法交互，未发起网页登录' % BASE)]


def test_expired_login_without_a_terminal_also_goes_to_stdout(run):
    credentials.save(BASE, Credential(TOKEN, 'oauth', 'saved', expires_at='2020-01-01T00:00:00+00:00'))
    code, out, err = run('whoami')
    assert code == 1 and 'quafu login' in out and '过期' in out


def test_base_url_flag(run, fake, monkeypatch):
    monkeypatch.setenv('QUAFU_API_KEY', KEY)
    fake.route('GET', '/auth/me', ME)
    code, out, err = run('--base-url', 'https://other.test', 'whoami')
    assert code == 0 and fake.calls[0]['url'] == 'https://other.test/api/v1/auth/me'
    code, out, err = run('--base-url', 'http://plain.test', 'whoami')
    assert code == 1 and 'https' in err


def test_no_command_prints_help(run):
    code, out, err = run()
    assert code == 2 and 'login' in out


def test_console_entry_point_and_module_run():
    r = subprocess.run([sys.executable, '-m', 'quafu', '--version'], capture_output=True, text=True,
                       timeout=SUBPROCESS_TIMEOUT)
    assert r.returncode == 0 and r.stdout.strip() == 'quafu-sdk %s' % quafu.__version__


@pytest.mark.parametrize('argv', [['--help'], ['whoami'], ['config', 'set', 'language', 'xx']])
def test_redirected_output_in_an_encoding_without_chinese_never_crashes(argv, tmp_path):
    """英文版 Windows 把界面切成中文后重定向到文件或管道，Python 按 cp1252 写中文，曾直接 UnicodeEncodeError
    甩出 Python 栈。这里用 PYTHONIOENCODING=cp1252 模拟：stdout（帮助）与 stderr（报错）都写得出、退出码照常。"""
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith('QUAFU_')}
    env.update(QUAFU_LANG='zh', PYTHONIOENCODING='cp1252', QUAFU_CONFIG_DIR=str(tmp_path))
    # 标准输入给一个已关闭的空管道，不用 DEVNULL：Windows 上 NUL 的 isatty() 为真，whoami 会进网页登录等待
    r = subprocess.run([sys.executable, '-m', 'quafu'] + argv, capture_output=True, env=env,
                       input=b'', timeout=SUBPROCESS_TIMEOUT)
    out, err = r.stdout.decode('cp1252'), r.stderr.decode('cp1252')
    assert 'Traceback' not in err and 'UnicodeEncodeError' not in err, err
    assert r.returncode == (0 if argv == ['--help'] else 1), err
    assert '?' in (err if argv[0] == 'config' else out)        # 未登录的说明打在 stdout
