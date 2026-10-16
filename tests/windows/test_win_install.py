# -*- coding: utf-8 -*-
"""Windows：装进虚拟环境后 quafu 命令找不找得到（Windows 手工测试清单第 1 项里能自动化的部分）。

W1 打一个 wheel，装进路径带中文和空格的虚拟环境（uv venv + uv pip install，解释器版本与跑测试的相同）：
   Scripts\\quafu.exe 能直接跑；把 Scripts 放进 PATH 后，cmd 与 PowerShell 里敲 quafu 找得到；
   cmd 里 call activate.bat 之后 quafu 与 python 都指向这个环境

打 wheel 要从包索引取构建后端，标 network；没有 uv 或连不上镜像时跳过。只在 Windows 上跑，别的系统整个模块跳过。"""
import ast
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.skipif(sys.platform != 'win32', reason='只在 Windows 上跑'), pytest.mark.network]

SDK_DIR = pathlib.Path(__file__).resolve().parents[2]
# 公共夹具会把 HOME / USERPROFILE 换成临时目录；uv 要用真用户目录下的缓存与已装的 Python
REAL_ENV = dict(os.environ)


def uv(*args, cwd=SDK_DIR):
    """跑 uv；连不上镜像就跳过。摘自 tests/deps/test_dependency_cut.py 的 uv()，去掉了这里用不到的参数。"""
    exe = shutil.which('uv')
    if not exe:
        pytest.skip('没有 uv')
    env = {k: v for k, v in REAL_ENV.items() if not k.startswith(('QUAFU_', 'VIRTUAL_ENV'))}
    r = subprocess.run([exe] + list(args), cwd=str(cwd), capture_output=True, text=True, timeout=1200, env=env)
    if r.returncode != 0:
        if re.search(r'(?i)(network|dns|connect|timed out|failed to fetch|tls)', r.stderr):
            pytest.skip('连不上镜像（%s）' % r.stderr.strip().splitlines()[-1][:200])
        raise AssertionError('uv %s 失败：\n%s' % (' '.join(args), r.stderr[-3000:]))
    return r


@pytest.fixture(scope='module')
def installed(tmp_path_factory):
    """(虚拟环境目录, 版本号)。"""
    work = tmp_path_factory.mktemp('w1')
    uv('build', '--wheel', '--out-dir', str(work / 'dist'))
    wheels = sorted((work / 'dist').glob('quafu_sdk-*.whl'))
    assert len(wheels) == 1, wheels
    version = wheels[0].name.split('-')[1]
    venv = work / '量子 测试' / 'env'
    uv('venv', '--python', '%d.%d' % sys.version_info[:2], str(venv), cwd=work)
    uv('pip', 'install', '--python', str(venv / 'Scripts' / 'python.exe'), str(wheels[0]))
    return venv, version


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, **kw)


def env_with_scripts(venv):
    env = dict(os.environ)
    env['PATH'] = str(venv / 'Scripts') + os.pathsep + env.get('PATH', '')
    return env


def test_quafu_exe_runs_from_a_chinese_path_with_spaces(installed):
    venv, version = installed
    exe = venv / 'Scripts' / 'quafu.exe'
    assert exe.is_file()
    r = run([str(exe), '--version'])
    assert (r.returncode, r.stdout.strip()) == (0, 'quafu-sdk ' + version), r.stderr


def test_found_on_path_in_cmd_and_powershell(installed):
    venv, version = installed
    env = env_with_scripts(venv)
    found = shutil.which('quafu', path=env['PATH'])
    assert found and os.path.normcase(found) == os.path.normcase(str(venv / 'Scripts' / 'quafu.exe')), found
    for cmd in (['cmd', '/d', '/c', 'quafu', '--version'],
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', 'quafu --version']):
        r = run(cmd, env=env)
        assert (r.returncode, r.stdout.strip()) == (0, 'quafu-sdk ' + version), (cmd[0], r.stdout, r.stderr)


def test_activate_bat_in_cmd(installed):
    venv, version = installed
    activate = venv / 'Scripts' / 'activate.bat'
    # 照用户在 cmd 里的做法：先 activate 再敲命令。路径的打印用 ascii()，不受控制台代码页影响
    line = 'cmd /d /s /c "call "%s" && quafu --version && python -c "import sys; print(ascii(sys.prefix))""' % activate
    r = run(line, env=dict(os.environ))
    lines = r.stdout.strip().splitlines()
    assert r.returncode == 0 and lines[:1] == ['quafu-sdk ' + version], (r.stdout, r.stderr)
    assert os.path.normcase(ast.literal_eval(lines[-1])) == os.path.normcase(str(venv)), lines
