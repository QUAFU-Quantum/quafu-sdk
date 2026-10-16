# -*- coding: utf-8 -*-
"""同名包冲突（第 6.4 节）的本地部分：不联网，用假的发行包元数据与目录模拟。真装一次的 D7–D9 在 tests/deps/。"""
import os
import pathlib
import subprocess
import sys

import quafu
from quafu import _conflict

from ..helpers import SUBPROCESS_TIMEOUT

PKG = pathlib.Path(quafu.__file__).resolve().parent
SRC_ROOT = PKG.parent


def _fake_dist(site, name, version='0.4.5', record=True):
    d = site / ('%s-%s.dist-info' % (name, version))
    d.mkdir(parents=True)
    (d / 'METADATA').write_text('Metadata-Version: 2.1\nName: %s\nVersion: %s\n' % (name, version))
    if record:
        (d / 'RECORD').write_text('quafu/__init__.py,,\nquafu/thing.py,,\n%s/RECORD,,\n' % d.name)
    else:
        (d / 'top_level.txt').write_text('quafu\n')


def _run(code, site, cwd):
    env = {k: v for k, v in os.environ.items() if not k.startswith('QUAFU_')}
    env['PYTHONPATH'] = os.pathsep.join([str(site), str(SRC_ROOT)])
    return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, cwd=str(cwd),
                          timeout=SUBPROCESS_TIMEOUT)


def test_own_entries_list_matches_the_package():
    shipped = {p.name[:-3] if p.name.endswith('.py') else p.name for p in PKG.iterdir()} - {'__pycache__'}
    assert shipped <= _conflict.OWN_ENTRIES
    assert _conflict.foreign_entries(str(PKG)) == []


def test_clean_environment_has_no_other_owner():
    assert _conflict.other_owners() == []


def test_another_distribution_providing_quafu_blocks_import(tmp_path):
    site = tmp_path / 'site'
    _fake_dist(site, 'someone-else')
    r = _run('import quafu', site, tmp_path)
    assert r.returncode != 0
    assert 'ConflictError' in r.stderr and 'Another package that uses the name quafu is installed in this Python environment (someone-else 0.4.5)' in r.stderr
    assert 'uv venv quafu-env' in r.stderr and 'uv pip install quafu-sdk' in r.stderr


def test_top_level_txt_is_enough_to_detect(tmp_path):
    site = tmp_path / 'site'
    _fake_dist(site, 'Old_Thing', record=False)
    r = _run('import quafu', site, tmp_path)
    assert r.returncode != 0 and 'Old_Thing 0.4.5' in r.stderr


def test_cli_reports_the_conflict_in_one_line_without_a_traceback(tmp_path):
    site = tmp_path / 'site'
    _fake_dist(site, 'someone-else')
    code = 'import sys; sys.argv[0] = "quafu"; import quafu'
    r = _run(code, site, tmp_path)
    assert r.returncode == 1 and r.stderr.startswith('Error: Another package') and 'Traceback' not in r.stderr


def test_cli_conflict_in_chinese_survives_an_encoding_without_chinese(tmp_path):
    """冲突报错走的是 __init__ 里那条路（早于 cli.main），stderr 重定向到 cp1252 时也不能崩。"""
    site = tmp_path / 'site'
    _fake_dist(site, 'someone-else')
    env = {k: v for k, v in os.environ.items() if not k.startswith('QUAFU_')}
    env.update(PYTHONPATH=os.pathsep.join([str(site), str(SRC_ROOT)]), QUAFU_LANG='zh', PYTHONIOENCODING='cp1252')
    r = subprocess.run([sys.executable, '-c', 'import sys; sys.argv[0] = "quafu"; import quafu'],
                       capture_output=True, env=env, cwd=str(tmp_path), timeout=SUBPROCESS_TIMEOUT)
    err = r.stderr.decode('cp1252')
    assert r.returncode == 1 and 'Traceback' not in err and 'uv venv quafu-env' in err, err


def test_cli_main_checks_before_importing_the_rest(tmp_path, monkeypatch, capsys):
    from quafu import cli
    monkeypatch.setattr(cli, 'check_conflict', lambda d: (_ for _ in ()).throw(_conflict.ConflictError('冲突')))
    assert cli.main(['whoami']) == 1
    assert capsys.readouterr().err == 'Error: 冲突\n'


def test_stray_files_in_the_package_directory_are_reported(tmp_path):
    fake_pkg = tmp_path / 'quafu'
    fake_pkg.mkdir()
    for n in ('__init__.py', 'client.py', 'circuits', 'users.py'):
        (fake_pkg / n).write_text('') if n.endswith('.py') else (fake_pkg / n).mkdir()
    assert _conflict.foreign_entries(str(fake_pkg)) == ['circuits', 'users.py']
    msg = _conflict.message([], ['circuits', 'users.py'])
    assert 'circuits' in msg and 'uv pip install quafu-sdk' in msg


def test_recovery_commands_can_be_pasted_as_is():
    """换干净环境的命令与默认装法 uv 一致，不调 python（macOS / Ubuntu 24.04 上没进环境时没有 python，
    只用 uv 装 Python 的 Windows 上返回 9009），每种终端一块、块里不混写别的终端。"""
    posix = _conflict.recovery_commands(windows=False)
    assert [ln.strip() for ln in posix.splitlines()] == [
        'uv venv quafu-env', 'source quafu-env/bin/activate', 'uv pip install quafu-sdk']
    win = _conflict.recovery_commands(windows=True)
    ps, cmd = win.split('  cmd:\n')
    assert ps.startswith('  PowerShell:\n') and 'Activate.ps1' in ps and 'activate.bat' not in ps
    assert 'Set-ExecutionPolicy Bypass -Scope Process' in ps
    assert [ln.strip() for ln in cmd.splitlines()] == [
        'uv venv quafu-env', 'quafu-env\\Scripts\\activate.bat', 'uv pip install quafu-sdk']
    assert 'python' not in posix + win
    assert 'source' not in win and '\\' not in posix


def test_message_shows_only_the_current_os_commands():
    msg = _conflict.message([('old', '1.0')], [])
    assert msg.endswith(_conflict.recovery_commands(os.name == 'nt'))
    assert _conflict.message([('old', '1.0')], [], windows=False).endswith('uv pip install quafu-sdk')
    assert 'PowerShell' not in _conflict.message([('old', '1.0')], [], windows=False)
    assert 'source' not in _conflict.message([('old', '1.0')], [], windows=True)
