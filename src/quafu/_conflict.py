# -*- coding: utf-8 -*-
"""导入名冲突检查：import quafu 与命令行 quafu 的第一件事。

PyPI 上另有发行包也用导入名 quafu。pip 不检查两个发行包是否写同一个目录，两者装进同一个 Python 环境时，
文件会装进同一个 site-packages/quafu/、互相覆盖，后装的赢；卸掉其中一个还会删掉另一个的同名文件。
混合体的行为不可预测，所以一检测到就报错、说明怎么办，而不是带着警告跑下去。

两道检查，都只用标准库、只读本地元数据，不联网：
  1. 当前环境里有没有别的发行包也提供顶层名 quafu（读各发行包的 RECORD / top_level.txt；
     冲突包的名字从元数据动态读出，源码里不写死任何旧组件的名字）
  2. 本包目录里有没有不属于本包的条目（别的发行包把文件装进了 quafu/，而它的元数据已经不在了）"""
import os
import re

from ._i18n import t

PACKAGE = 'quafu'
OWN_DISTRIBUTION = 'quafu-sdk'
# 本包目录下的全部顶层条目（模块去掉 .py）。新增模块时同步这里，tests/unit/test_conflict.py 会核对
OWN_ENTRIES = frozenset(('__init__', '__pycache__', '__main__', '_conflict', '_i18n', '_inputs', '_limits', '_messages',
                         '_qasm', 'bits', 'cli', 'client',
                         'config', 'credentials', 'devices', 'errors', 'jobs', 'oauth', 'qiskit', 'tables', 'transport',
                         'py.typed'))


class ConflictError(ImportError):
    """当前 Python 环境里还装了另一个占用 quafu 名字的包。"""


def normalize(name):
    return re.sub(r'[-_.]+', '-', name or '').lower()


def _provides(dist, package):
    """这个发行包是否往顶层名 package 下装文件。"""
    try:
        record = dist.read_text('RECORD')
    except Exception:
        record = None
    if record:
        return record.startswith(package + '/') or ('\n%s/' % package) in record
    try:
        top = dist.read_text('top_level.txt')
    except Exception:
        top = None
    return bool(top) and package in top.split()


def other_owners(package=PACKAGE):
    """除本包外、也提供顶层名 package 的发行包：[(名字, 版本)]，按名字排序。"""
    try:
        from importlib import metadata
    except ImportError:                      # pragma: no cover  Python < 3.8
        return []
    found = {}
    for dist in metadata.distributions():
        try:
            name = dist.metadata['Name'] or ''
        except Exception:
            continue
        if normalize(name) == OWN_DISTRIBUTION or not name:
            continue
        if _provides(dist, package):
            found[normalize(name)] = (name, dist.version or '?')
    return [found[k] for k in sorted(found)]


def foreign_entries(package_dir):
    """本包目录里不属于本包的顶层条目（排好序）。"""
    try:
        names = os.listdir(package_dir)
    except OSError:
        return []
    out = []
    for n in names:
        stem = n[:-3] if n.endswith('.py') else n
        if n.endswith('.pyc') or stem in OWN_ENTRIES:
            continue
        out.append(n)
    return sorted(out)


# 换干净环境的命令：与默认装法 uv 一致，每种终端一块、能整块照抄（没进虚拟环境时 macOS / Ubuntu 24.04 没有
# python 命令，只用 uv 装 Python 的 Windows 上 python 返回 9009；一块里混写两种终端也照抄不了）。只给当前系统那几块。
# PowerShell 默认执行策略会拦 Activate.ps1，所以先放开本进程的策略（只对这个窗口有效）。
_POSIX_COMMANDS = ('  uv venv quafu-env\n'
                   '  source quafu-env/bin/activate\n'
                   '  uv pip install quafu-sdk')
_WINDOWS_COMMANDS = ('  PowerShell:\n'
                     '    uv venv quafu-env\n'
                     '    Set-ExecutionPolicy Bypass -Scope Process -Force\n'
                     '    quafu-env\\Scripts\\Activate.ps1\n'
                     '    uv pip install quafu-sdk\n'
                     '  cmd:\n'
                     '    uv venv quafu-env\n'
                     '    quafu-env\\Scripts\\activate.bat\n'
                     '    uv pip install quafu-sdk')


def recovery_commands(windows=None):
    """当前系统上新建干净环境、装本包的命令块（缩进好，可直接接在说明后面）。"""
    if windows is None:
        windows = os.name == 'nt'
    return _WINDOWS_COMMANDS if windows else _POSIX_COMMANDS


def message(owners, entries, windows=None):
    sep = t('conflict.list_sep')
    if owners:
        what = sep.join('%s %s' % kv for kv in owners)
    else:
        what = t('conflict.foreign_files', sep.join(entries[:5]))
    return t('conflict.message', what, recovery_commands(windows))


def check(package_dir):
    """有冲突抛 ConflictError。"""
    owners = other_owners()
    entries = foreign_entries(package_dir)
    if owners or entries:
        raise ConflictError(message(owners, entries))
