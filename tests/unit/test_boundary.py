# -*- coding: utf-8 -*-
"""包的边界：依赖切割的源码扫描（D5）、核心不 import qiskit、地址与凭证前缀各只有一处、没有关 TLS / 走系统代理的后门、
不提旧平台、不出现硬件方的任务号字段与状态词。"""
import ast
import pathlib
import re
import subprocess
import sys

import quafu
from quafu import _conflict

from ..helpers import SUBPROCESS_TIMEOUT

SRC = pathlib.Path(quafu.__file__).resolve().parent
ROOT = SRC.parents[1]
ADDRESS = re.compile(r'https?://[\w\[]')

# 依赖切割。本文件与 tests/deps/ 是仅有的允许写出这些名字的地方
FORBIDDEN_IMPORTS = ('quark', 'srpc', 'qsteed', 'qos_tools', 'pyquafu')
FORBIDDEN_TEXT = ('quarkstudio', 'quarkcircuit', 'pyquafu', 'qsteed', 'qos-tools', 'qos_tools', 'srpc',
                  'quafu-sqc', 'baqis.ac.cn')

BLOCK_QISKIT = '''
import sys
class _Block(object):
    def find_spec(self, name, path=None, target=None):
        if name == 'qiskit' or name.startswith('qiskit.'):
            raise ImportError('blocked ' + name)
sys.meta_path.insert(0, _Block())
'''


def _sources():
    return {str(p.relative_to(SRC)): p.read_text(encoding='utf-8') for p in sorted(SRC.rglob('*.py'))}


def _shipped_text():
    files = dict(_sources())
    for n in ('README.md', 'CHANGELOG.md', 'pyproject.toml'):
        files[n] = (ROOT / n).read_text(encoding='utf-8')
    return files


def _imports(rel, text):
    """一个源文件里所有 import 的绝对模块名（相对导入按包结构解析）。"""
    pkg = ['quafu'] + list(pathlib.PurePath(rel).parent.parts)
    if rel.endswith('__init__.py'):
        pkg = ['quafu'] + list(pathlib.PurePath(rel).parent.parts)
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = pkg[:len(pkg) - (node.level - 1)] if node.level else []
            mod = '.'.join(base + ([node.module] if node.module else []))
            out.append(mod)
            out += ['%s.%s' % (mod, a.name) for a in node.names]
    return out


def test_d5_no_forbidden_imports():
    own = {e for e in _conflict.OWN_ENTRIES if not e.startswith('__')} | {'__init__'}
    for rel, text in _sources().items():
        for mod in _imports(rel, text):
            top = mod.split('.')[0]
            assert top not in FORBIDDEN_IMPORTS and not top.startswith('quark'), (rel, mod)
            if top == 'quafu' and '.' in mod:
                # quafu 只许是本包自己：quafu.<x> 的 x 必须是本包的模块，或从本包模块里取的名字
                assert mod.split('.')[1] in own or hasattr(quafu, mod.split('.')[1]), (rel, mod)


def test_d5_no_forbidden_strings_in_what_we_ship():
    for name, s in _shipped_text().items():
        low = s.lower()
        for word in FORBIDDEN_TEXT:
            assert word not in low, (name, word)


def test_core_never_imports_qiskit():
    r = subprocess.run([sys.executable, '-c', BLOCK_QISKIT + '\n'.join([
        'import quafu, quafu.cli, quafu.client, quafu.jobs, quafu.oauth, quafu.config, quafu._qasm',
        'import quafu.credentials, quafu.transport, quafu.errors, quafu.bits, quafu.tables, quafu.devices',
        'import quafu._inputs',
        'bad = [m for m in sys.modules if m.split(".")[0] == "qiskit" or m == "quafu.qiskit"]',
        'assert not bad, bad',
    ])], capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    assert r.returncode == 0, r.stderr


def test_qiskit_adapter_gives_the_install_hint_without_qiskit():
    r = subprocess.run([sys.executable, '-c', BLOCK_QISKIT + 'try:\n    import quafu.qiskit\n'
                        'except ImportError as e:\n    print(e)\n'], capture_output=True, text=True,
                       timeout=SUBPROCESS_TIMEOUT)
    assert r.returncode == 0 and 'pip install "quafu-sdk[qiskit]"' in r.stdout, r.stdout + r.stderr


def _code_strings(text):
    """源码里的字符串常量，不含文档字符串（文档字符串里的示例地址不算写死的地址）。"""
    tree = ast.parse(text)
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_the_only_address_literal_is_the_default_base_url():
    """平台地址只在 config.DEFAULT_BASE_URL 写一次（docs/base-url.md 第 4 节的例外）；回环地址的格式串不算。"""
    hits = {name: [v for v in _code_strings(s) if ADDRESS.match(v) or re.match(r'https?://', v)]
            for name, s in _sources().items()}
    hits = {k: v for k, v in hits.items() if v}
    assert hits == {'config.py': ['https://quafu.com.cn'], 'oauth.py': ['http://%s:%d%s']}, hits


def test_token_prefix_is_defined_once():
    hits = [(name, v) for name, s in _sources().items() for v in _code_strings(s) if v.startswith('qf_')]
    assert hits == [('credentials.py', 'qf_')]


def test_no_hardware_side_ids_or_status_words():
    banned = ('platform_tid', 'remote_tid', 'Transpil', 'Pending', 'Canceled')
    for name, s in _shipped_text().items():
        for word in banned:
            assert word not in s, (name, word)


def test_no_escape_hatches():
    banned = ('verify=False', 'CERT_NONE', '_create_unverified_context', 'check_hostname = False',
              'getproxies', 'urllib.request', 'urlopen', 'except BaseException', 'except:')
    for name, s in _sources().items():
        for bad in banned:
            assert bad not in s, (name, bad)


def test_no_module_file_names_from_other_quafu_packages():
    """第 6.4 节第 3 条：子模块文件名不与另一个占用 quafu 名字的包重名（真实清单的比对在 tests/deps/ D9）。"""
    common = {'circuits', 'tasks', 'users', 'backends', 'results', 'simulators', 'elements', 'algorithms',
              'exceptions', 'utils', 'visualisation', 'benchmark', 'qfasm', 'dagcircuits', 'synthesis', 'transpiler'}
    names = {p.name[:-3] if p.name.endswith('.py') else p.name for p in SRC.iterdir()}
    assert not names & common
