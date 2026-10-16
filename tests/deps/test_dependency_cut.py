# -*- coding: utf-8 -*-
"""依赖切割：在干净的临时虚拟环境里真装一次，逐项断言。

D1 元数据      wheel 的 Requires-Dist：无条件依赖为空；extra == "qiskit" 只有 qiskit
D2 完整依赖树  「无 extra」与「[qiskit]」两种，uv pip compile 解出完整传递依赖：与禁用清单无交集、无 quark*、
               无非本包的 *quafu*
D3 真装一次    新建临时虚拟环境装 wheel（含与不含 [qiskit]），importlib.metadata 全量断言同上
D4 导入面      在 D3 的环境里 import quafu 并跑一次假登录与假提交：sys.modules 里没有禁用导入名，quafu 来自 quafu-sdk
D7 先装对方    临时环境先装那个占用 quafu 名字的旧包，再装本包：import quafu 抛 ImportError，文案带动态读出的发行名
D8 后装对方    顺序反过来：命令行 quafu whoami 非零退出、一句话说明，不出 Python 栈
D9 文件名      本包 wheel 的 quafu/ 文件清单与旧包最新 wheel 的清单除 __init__.py 外没有交集

要联网拉包（走 pyproject 里配的镜像），标 network；离线时跳过并打印「未验证依赖树」。
本文件与 tests/unit/test_boundary.py 是仅有的允许写出禁用名字的地方。"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

import pytest

from ..helpers import SUBPROCESS_TIMEOUT

pytestmark = pytest.mark.network

SDK_DIR = pathlib.Path(__file__).resolve().parents[2]
FORBIDDEN_DISTS = ('quarkstudio', 'srpc', 'quarkcircuit', 'pyquafu', 'qsteed', 'qos-tools')
FORBIDDEN_IMPORTS = ('quark', 'srpc', 'qsteed', 'qos_tools', 'pyquafu')
OLD = 'pyquafu'
OLD_INIT_DEPS = ('autograd', 'graphviz', 'ipython', 'matplotlib', 'networkx', 'numpy<2', 'ply', 'pybind11',
                 'requests', 'scipy')
PY = '3.11'                          # 旧包只有到 3.13 的二进制 wheel；三处环境用同一个版本
# 公共夹具会把 HOME 换成临时目录；uv 要用真 HOME 下的缓存与已装的 Python，否则会去网上重新下 Python
REAL_ENV = dict(os.environ)


def norm(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def bad_dists(names):
    out = []
    for n in map(norm, names):
        if n in FORBIDDEN_DISTS or n.startswith('quark') or ('quafu' in n and n != 'quafu-sdk'):
            out.append(n)
    return out


def uv(*args, check=True, cwd=SDK_DIR, **kw):
    """在 SDK 目录里跑 uv（读 pyproject 里配的包索引）；建虚拟环境时 cwd 给项目外的目录——
    在项目目录里 uv venv 会去对项目做解析，没必要还可能卡在网络上。"""
    exe = shutil.which('uv')
    if not exe:
        pytest.skip('没有 uv：未验证依赖树')
    env = {k: v for k, v in REAL_ENV.items() if not k.startswith(('QUAFU_', 'VIRTUAL_ENV'))}
    r = subprocess.run([exe] + list(args), cwd=str(cwd), capture_output=True, text=True, timeout=1200, env=env, **kw)
    if check and r.returncode != 0:
        if re.search(r'(?i)(network|dns|connect|timed out|failed to fetch|tls)', r.stderr):
            print('离线或连不上镜像：未验证依赖树')
            pytest.skip('离线：未验证依赖树（%s）' % r.stderr.strip().splitlines()[-1][:200])
        # 要装的包在本机平台上没有 wheel（比如 pyquafu 不出 linux aarch64 的）：装不上就验不了，跳过并写明平台。
        # uv 会把这句报错折行，「platform」和「tag」之间可能隔着换行
        m = re.search(r'no wheels with a matching platform\s+tag(?:\s*\(e\.g\.,\s*`([^`]+)`\))?', r.stderr)
        if m:
            print('%s 在本机平台没有 wheel：未验证' % args[-1])
            pytest.skip('%s 在本机平台（%s）没有 wheel：未验证' % (args[-1], m.group(1) or '见 uv 输出'))
        raise AssertionError('uv %s 失败：\n%s' % (' '.join(args), r.stderr[-3000:]))
    return r


@pytest.fixture(scope='module')
def work(tmp_path_factory):
    return tmp_path_factory.mktemp('deps')


@pytest.fixture(scope='module')
def wheel(work):
    uv('build', '--wheel', '--out-dir', str(work / 'dist'))
    found = sorted((work / 'dist').glob('quafu_sdk-*.whl'))
    assert len(found) == 1, found
    return found[0]


def venv_exe(d, name):
    """虚拟环境里的可执行文件：Windows 在 Scripts 下、带 .exe（uv 按路径找 --python 要真实文件名），其余平台在 bin 下。"""
    return d / 'Scripts' / (name + '.exe') if os.name == 'nt' else d / 'bin' / name


def venv(work, name):
    d = work / name
    uv('venv', '--python', PY, str(d), cwd=work)
    return d, venv_exe(d, 'python')


def install(py, *reqs):
    uv('pip', 'install', '--python', str(py), *reqs)


def run_py(py, code, **kw):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('QUAFU_', 'PYTHONPATH', 'VIRTUAL_ENV'))}
    env.update(kw.pop('env', {}))
    return subprocess.run([str(py), '-c', code], capture_output=True, text=True, env=env, cwd=str(kw.pop('cwd', '/')),
                          timeout=SUBPROCESS_TIMEOUT, **kw)


LIST_DISTS = 'from importlib import metadata\nprint("\\n".join(sorted(d.metadata["Name"] for d in metadata.distributions())))'


# ── D1 ────────────────────────────────────────────────────────────

def test_d1_metadata_has_no_runtime_dependencies(wheel):
    with zipfile.ZipFile(wheel) as z:
        meta = next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
        text = z.read(meta).decode('utf-8')
    reqs = re.findall(r'(?m)^Requires-Dist: (.+)$', text)
    unconditional = [r for r in reqs if 'extra ==' not in r]
    assert unconditional == []
    assert [re.split(r'[<>=;\s\[]', r)[0] for r in reqs] == ['qiskit']
    assert re.search(r"extra == ['\"]qiskit['\"]", reqs[0])
    assert re.search(r'(?m)^Name: quafu-sdk$', text) and re.search(r'(?m)^License-Expression: MIT$', text)


# ── D2 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('extra', ['', '[qiskit]'])
def test_d2_resolved_tree_has_no_old_components(wheel, work, extra):
    req = work / ('req%s.in' % ('-qiskit' if extra else ''))
    req.write_text('quafu-sdk%s @ %s\n' % (extra, wheel.as_uri()))
    out = uv('pip', 'compile', '--python-version', PY, '--no-header', '--no-annotate', str(req)).stdout
    names = [re.split(r'[<>=@\s\[]', line.strip())[0] for line in out.splitlines()
             if line.strip() and not line.startswith('#')]
    assert 'quafu-sdk' in map(norm, names)
    assert bad_dists(names) == [], names
    if not extra:
        assert list(map(norm, names)) == ['quafu-sdk']
    else:
        assert 'qiskit' in map(norm, names)


# ── D3、D4 ───────────────────────────────────────────────────────

FAKE_RUN = r'''
import json, sys
import quafu
from quafu import client, credentials
from quafu.transport import Response

class Fake(object):
    def request(self, method, url, headers, body, ct, rt):
        if url.endswith('/auth/me'):
            data = {'user': {'public_id': 'u1', 'name': 'x', 'email': 'x@y'}}
            return Response(200, {}, json.dumps(data).encode())
        if url.endswith('/jobs') and method == 'POST':
            data = {'job_id': 'u1-1-1', 'task_ids': ['u1-1-1-0'], 'status': 'Queued'}
            return Response(202, {}, json.dumps(data).encode())
        return Response(404, {}, b'{}')

client.HTTPTransport = lambda **kw: Fake()
quafu.login(api_key='qf_' + 'a' * 32)
job = quafu.submit('OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nmeasure q[0] -> c[0];\n', 'sim')
assert job.id == 'u1-1-1'
from importlib import metadata
files = {str(f).replace('\\', '/') for f in metadata.distribution('quafu-sdk').files}
own = 'quafu/__init__.py' in files and quafu.__file__.replace('\\', '/').endswith('quafu/__init__.py')
owners = getattr(metadata, 'packages_distributions', lambda: {'quafu': ['quafu-sdk']})().get('quafu')
print(json.dumps({'modules': sorted(sys.modules), 'own': own, 'owners': owners}))
'''


@pytest.mark.parametrize('extra', ['', '[qiskit]'])
def test_d3_d4_installed_environment_is_clean(wheel, work, extra, tmp_path):
    d, py = venv(work, 'clean%s' % ('-qiskit' if extra else ''))
    install(py, '%s%s' % (wheel, extra))
    dists = run_py(py, LIST_DISTS).stdout.split()
    assert 'quafu-sdk' in dists and bad_dists(dists) == [], dists
    if extra:
        assert 'qiskit' in dists
    else:
        assert set(map(norm, dists)) <= {'quafu-sdk', 'pip', 'setuptools', 'wheel'}, dists
    r = run_py(py, FAKE_RUN, env={'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path),
                                  'QUAFU_BASE_URL': 'https://quafu.test'})
    assert r.returncode == 0, r.stderr
    import json
    info = json.loads(r.stdout.strip().splitlines()[-1])
    tops = {m.split('.')[0] for m in info['modules']}
    assert not tops & set(FORBIDDEN_IMPORTS) and not any(t.startswith('quark') for t in tops)
    assert info['own'] and info['owners'] == ['quafu-sdk']
    assert 'qiskit' not in tops                     # 交的是字符串，核心路径不碰 qiskit


# ── D7、D8、D9：与占用同一导入名的旧包 ──────────────────────────────

def test_d7_old_package_first_then_ours_refuses_to_import(wheel, work):
    d, py = venv(work, 'old-first')
    install(py, '--no-deps', OLD)               # 冲突只看文件与元数据；后装的本包 __init__ 生效，旧包的依赖用不上
    install(py, str(wheel))
    r = run_py(py, 'import quafu')
    assert r.returncode != 0 and 'ConflictError' in r.stderr, r.stderr
    assert 'Another package that uses the name quafu' in r.stderr and OLD in r.stderr
    assert 'uv venv quafu-env' in r.stderr and 'python -m venv' not in r.stderr
    # 标准输入给已关闭的空管道（不继承终端，也不用 Windows 上 isatty() 为真的 NUL），万一走到登录也不会等输入
    r = subprocess.run([str(venv_exe(d, 'quafu')), 'whoami'], capture_output=True, text=True, input='',
                       timeout=SUBPROCESS_TIMEOUT)
    assert r.returncode == 1 and r.stderr.startswith('Error: Another package') and 'Traceback' not in r.stderr, r.stderr


def test_d8_ours_first_then_old_package_cli_still_explains(wheel, work):
    d, py = venv(work, 'ours-first')
    install(py, str(wheel))
    # 旧包后装，它的 __init__ 盖掉本包的；命令行入口要先 import 它，所以它 __init__ 用到的依赖得装上。
    # 只是不装 sparse：它拖进 numba / llvmlite（几十 MB），而旧包的 __init__ 用不到它（2026-10-08 实测）
    install(py, '--no-deps', OLD)
    install(py, *OLD_INIT_DEPS)
    # 同上：关闭的空管道作标准输入
    r = subprocess.run([str(venv_exe(d, 'quafu')), 'whoami'], capture_output=True, text=True, input='',
                       timeout=SUBPROCESS_TIMEOUT)
    assert r.returncode != 0, r.stdout
    assert 'Another package that uses the name quafu' in r.stderr and OLD in r.stderr, r.stderr
    assert 'Traceback' not in r.stderr, r.stderr


def test_d9_file_names_do_not_overlap(wheel, work):
    d, py = venv(work, 'old-files')
    install(py, '--no-deps', OLD)
    record = run_py(py, 'from importlib import metadata\nprint("\\n".join(str(f) for f in metadata.distribution(%r).files))'
                    % OLD).stdout
    theirs = {f.replace('\\', '/') for f in record.split()}
    theirs = {f for f in theirs if f.startswith('quafu/') and not f.endswith('.pyc')}
    with zipfile.ZipFile(wheel) as z:
        ours = {n for n in z.namelist() if n.startswith('quafu/')}
    assert ours and theirs
    assert ours & theirs == {'quafu/__init__.py'}, sorted(ours & theirs)
