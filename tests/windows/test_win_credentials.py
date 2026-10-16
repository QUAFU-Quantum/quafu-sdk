# -*- coding: utf-8 -*-
"""Windows：凭证文件（Windows 手工测试清单第 6 项里能自动化的部分）。

W2 默认位置在用户目录下：目录与文件的 ACL 里没有 Everyone、Users、Authenticated Users 这类「别的用户也能进」的允许项。
   Windows 不看 0700 / 0600 的权限位，能不能被别人读全看 ACL，所以这里直接读 ACL（按 SID 比，不受系统语言影响）
W2 用户目录名、QUAFU_CONFIG_DIR 带中文和空格：存、取、命令行改设置都正常
W2 凭证文件被别的程序开着（杀毒、同步盘、编辑器）：替换会被系统拒绝；对方很快关掉时重试成功，一直不关时给一句
   能看懂的错误，旧文件原样保留、不留临时文件

只在 Windows 上跑，别的系统整个模块跳过。"""
import os
import shutil
import subprocess
import sys
import types
import uuid

import pytest

from quafu import credentials
from quafu.credentials import Credential
from quafu.errors import CredentialsError

from ..helpers import BASE, KEY, KEY2
from .support import child_env, run_cli

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='只在 Windows 上跑')

# 导入时记下真的用户目录：公共夹具随后会把 USERPROFILE 换成临时目录
REAL_PROFILE = os.environ.get('USERPROFILE')

# 出现在允许项里就意味着本机别的账号也能进
BROAD = {'S-1-1-0': 'Everyone', 'S-1-5-7': 'ANONYMOUS LOGON', 'S-1-5-11': 'Authenticated Users',
         'S-1-5-32-545': 'Users', 'S-1-5-32-546': 'Guests'}
PS_ACL = ("$ErrorActionPreference = 'Stop'; "
          "$acl = Get-Acl -LiteralPath $env:QF_ACL_PATH; "
          "foreach ($r in $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) "
          "{ '{0}|{1}|{2}' -f $r.IdentityReference.Value, $r.AccessControlType, $r.FileSystemRights }")


def acl(path):
    """[(SID, Allow/Deny, 权限), ...]，含继承来的项。路径经环境变量传，中文和空格不用转义。"""
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', PS_ACL],
                       env=child_env(QF_ACL_PATH=str(path)), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return [tuple(line.split('|', 2)) for line in r.stdout.splitlines() if line.strip()]


def test_default_location_is_closed_to_other_users(monkeypatch):
    if not REAL_PROFILE or not os.path.isdir(REAL_PROFILE):
        pytest.skip('没有 USERPROFILE')
    # 在真用户目录下建一个一次性目录当「~」：它照常继承用户目录的 ACL，与真实的 ~ 一样。
    # 不用 tempfile.mkdtemp / pytest 的 tmp_path：新版 Python 建它们时自带只给本人的 ACL，测不出继承来的权限
    base = os.path.join(REAL_PROFILE, 'quafu-sdk-test-%s' % uuid.uuid4().hex[:8])
    os.mkdir(base)
    try:
        for var in ('USERPROFILE', 'HOME'):              # 与公共夹具一样两个都换
            monkeypatch.setenv(var, base)
        path = credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
        assert path == os.path.join(base, '.quafu-sdk', 'credentials.json')
        assert credentials.saved(BASE).mask == credentials.mask(KEY)
        for what, p in (('目录', os.path.dirname(path)), ('文件', path)):
            rules = acl(p)
            print('%s %s 的 ACL：%s' % (what, p, rules))
            open_to = sorted({BROAD[sid] for sid, kind, _ in rules if kind == 'Allow' and sid in BROAD})
            assert not open_to, '凭证%s对 %s 开放：%s' % (what, '、'.join(open_to), rules)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_profile_with_chinese_and_spaces(monkeypatch, tmp_path):
    home = tmp_path / '张 三'
    home.mkdir()
    for var in ('USERPROFILE', 'HOME'):
        monkeypatch.setenv(var, str(home))
    path = credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
    assert path == str(home / '.quafu-sdk' / 'credentials.json')
    assert credentials.saved(BASE).mask == credentials.mask(KEY)
    # 命令行在子进程里拿到的是同一个目录（中文路径经环境块传过去）
    r = run_cli('config', 'set', 'language', 'zh', cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (home / '.quafu-sdk' / 'config.json').is_file()
    r = run_cli('config', 'get', 'language', cwd=tmp_path)
    assert (r.returncode, r.stdout.strip()) == (0, b'zh'), r.stderr


def test_config_dir_with_chinese_and_spaces(monkeypatch, clean_env):
    d = clean_env / '量子 配置'                                      # 放在用户目录下：不触发「目录在用户目录之外」的提醒
    monkeypatch.setenv('QUAFU_CONFIG_DIR', str(d))
    path = credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
    assert path == str(d / 'credentials.json')
    assert credentials.saved(BASE).mask == credentials.mask(KEY)


def test_brief_hold_is_retried(monkeypatch):
    path = credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
    held = open(path, 'rb')                 # 普通 open 不带 FILE_SHARE_DELETE：这时替换这个文件会被系统拒绝
    waits = []

    def sleep(s):                           # 等的这一下里对方把文件关了；不靠真计时，CI 上不抖
        waits.append(s)
        held.close()
    monkeypatch.setattr(credentials, 'time', types.SimpleNamespace(sleep=sleep))
    try:
        credentials.save(BASE, Credential(KEY2, 'api_key', 'saved'))
    finally:
        held.close()
    assert len(waits) == 1, '第一次替换没有被拒：文件开着也能替换，重试没用上'
    assert credentials.saved(BASE).mask == credentials.mask(KEY2)
    assert os.listdir(os.path.dirname(path)) == ['credentials.json']


def test_long_hold_gives_a_readable_error_and_keeps_the_old_file(monkeypatch):
    path = credentials.save(BASE, Credential(KEY, 'api_key', 'saved'))
    monkeypatch.setattr(credentials, 'time', types.SimpleNamespace(sleep=lambda s: None))
    with open(path, 'rb'):
        with pytest.raises(CredentialsError) as e:
            credentials.save(BASE, Credential(KEY2, 'api_key', 'saved'))
    msg = str(e.value)
    assert path in msg and "can't be written (PermissionError)" in msg and 'QUAFU_CONFIG_DIR' in msg, msg
    assert KEY2 not in msg and KEY2[3:12] not in msg
    assert credentials.saved(BASE).mask == credentials.mask(KEY)
    assert os.listdir(os.path.dirname(path)) == ['credentials.json']
