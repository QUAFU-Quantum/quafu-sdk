# -*- coding: utf-8 -*-
"""Windows：命令行的输出编码与连不上时的报错（Windows 手工测试清单第 7、9 项里能自动化的部分）。

W3 中文版 Windows 上输出被重定向（> 文件、| more、IDE 的输出窗口）时，Python 用 GBK 写管道：界面切中文后五条
   命令的输出都能按 GBK 严格解码，不出 Python 栈
W3 默认英文界面，用这台机器自己的管道编码（中文版 cp936、英文版 cp1252）：同样能解码、不出栈
W4 代理不通、直连不通：退出码 1，一句话说明经哪个代理 / 未经代理，不出栈；中文界面走 GBK 管道同样成立
W5 标准输入接到 NUL（subprocess.DEVNULL，与计划任务、< NUL 相同）时未登录：不发起网页登录、不等输入，
   说明打在 stdout，退出码 1

只在 Windows 上跑，别的系统整个模块跳过。"""
import subprocess
import sys

import pytest

from ..helpers import KEY
from .support import CLI, child_env, pipe_encoding, run_cli

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='只在 Windows 上跑')

COMMANDS = [('--help',), ('--version',), ('whoami',), ('login', '--help'), ('logout', '--help'),
            ('config', 'get', 'language')]
RC = {('whoami',): 1}                       # 未登录、不可交互：一句话说明两种登录方式，退出码 1；其余是 0


def has_cjk(text):
    return any('一' <= ch <= '鿿' for ch in text)


@pytest.mark.parametrize('args', COMMANDS, ids=' '.join)
def test_zh_output_through_a_gbk_pipe(args, tmp_path):
    r = run_cli(*args, cwd=tmp_path, QUAFU_LANG='zh', PYTHONIOENCODING='gbk')
    out, err = r.stdout.decode('gbk'), r.stderr.decode('gbk')          # 严格解码：有编不进 GBK 的字符就红
    assert b'Traceback' not in r.stderr, err
    assert r.returncode == RC.get(args, 0), err
    if args == ('--help',):
        assert has_cjk(out), out                                        # 确认界面真切成了中文
    if args == ('whoami',):
        assert 'quafu login' in out and 'QUAFU_API_KEY' in out, out


@pytest.mark.parametrize('args', COMMANDS, ids=' '.join)
def test_default_output_through_this_machines_pipe_encoding(args, tmp_path):
    enc = pipe_encoding(tmp_path)
    r = run_cli(*args, cwd=tmp_path)
    out, err = r.stdout.decode(enc), r.stderr.decode(enc)
    assert b'Traceback' not in r.stderr, err
    assert r.returncode == RC.get(args, 0), err
    if args == ('--version',):
        assert out.startswith('quafu-sdk '), out


@pytest.mark.parametrize('lang', ['en', 'zh'])
@pytest.mark.parametrize('route', ['proxy', 'direct'])
def test_unreachable_platform_is_one_sentence(route, lang, tmp_path):
    env = {'QUAFU_API_KEY': KEY}
    if route == 'proxy':
        env['QUAFU_PROXY'] = '127.0.0.1:9'                  # 本机 9 号端口没人听：代理连不上
    else:
        env['QUAFU_BASE_URL'] = 'https://127.0.0.1:9'       # 直连连不上
    if lang == 'zh':
        env.update(QUAFU_LANG='zh', PYTHONIOENCODING='gbk')
    enc = 'gbk' if lang == 'zh' else pipe_encoding(tmp_path)
    r = run_cli('whoami', cwd=tmp_path, **env)
    err = r.stderr.decode(enc)                              # 报错里带着 Windows 自己的错误说明（中文版是中文）
    assert b'Traceback' not in r.stderr, err
    assert r.returncode == 1, err
    assert len(err.strip().splitlines()) == 1, err
    if route == 'proxy':
        assert ('经代理 127.0.0.1:9' if lang == 'zh' else 'via proxy 127.0.0.1:9') in err, err
    else:
        assert ('未经代理' if lang == 'zh' else 'no proxy') in err, err
    assert KEY not in err


@pytest.mark.parametrize('lang', ['en', 'zh'])
def test_whoami_with_stdin_from_nul_exits_instead_of_waiting(lang, tmp_path):
    """NUL 的 isatty() 为真；SDK 另查 GetConsoleMode，NUL 不是控制台 → 不可交互 → 未登录直接退出。
    timeout 远小于网页登录的等待：卡住就是 TimeoutExpired。"""
    extra = {'QUAFU_LANG': lang, 'PYTHONIOENCODING': 'utf-8'}
    r = subprocess.run([sys.executable, '-c', CLI, 'whoami'], cwd=str(tmp_path), env=child_env(**extra),
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    out, err = r.stdout.decode('utf-8'), r.stderr.decode('utf-8')
    assert r.returncode == 1 and b'Traceback' not in r.stderr, err
    assert 'quafu login' in out and 'QUAFU_API_KEY' in out, out
    assert ('未登录' if lang == 'zh' else 'Not logged in') in out
    assert 'oauth/authorize' not in out + err                  # 没有打出登录链接
