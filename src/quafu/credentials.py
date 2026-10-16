# -*- coding: utf-8 -*-
"""凭证：形状校验与掩码、本机凭证文件、以及「这次用哪份凭证」的优先级。

两种凭证，平台上是同一种东西（qf_ 开头的一串），区别只在来历与有效期：
  api_key   在网站账户页建的 API Key，不过期，直到在网站上停用或删除
  oauth     网页登录（quafu.login()）换来的令牌，从授权那一刻起 90 天有效，不续期

优先级（高到低，先到先得，不合并）：参数 > 环境变量 QUAFU_API_KEY > 本机保存的登录态。
凭证不进日志、不进异常文本、不进 repr：读到就包进 Credential，对外只露掩码。

凭证文件 ~/.quafu-sdk/credentials.json（QUAFU_CONFIG_DIR 可改目录）：目录 0700、文件 0600，写时先写临时文件
再原子替换，读写都拒绝符号链接。按 BASE_URL 分 profile，每个地址一份，后存的覆盖先存的：
  {"version": 1, "profiles": {"https://quafu.com.cn": {"kind": "oauth", "token": "qf_…",
     "expires_at": "2027-01-06T10:00:00+08:00", "user": {"public_id": "…", "name": "…"},
     "device_name": "…", "created_at": "…"}}}"""
import errno
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from ._i18n import config_root, t
from .errors import CredentialsError

log = logging.getLogger('quafu')

TOKEN_PREFIX = 'qf_'                # 平台 API Key 与网页登录令牌同形：qf_ + base62
MASK_VISIBLE = 8                    # 掩码露出随机段的前几位：与网站 Key 列表显示的前缀同口径
_TOKEN_BODY = re.compile(r'[0-9A-Za-z]+\Z')

ENV_KEY = 'QUAFU_API_KEY'
ENV_CONFIG_DIR = 'QUAFU_CONFIG_DIR'
DIR_NAME = '.quafu-sdk'
FILE_NAME = 'credentials.json'
FILE_VERSION = 1
KINDS = ('api_key', 'oauth')
SOURCES = ('argument', 'env', 'saved')
_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)

_warned_dirs = set()


def check_token(value, what=None):
    """离线校验形状，返回去掉首尾空白的值；不对抛 CredentialsError（文本不含值本身）。
    只查前缀与字母表，不查总长：长度由平台判。what 是文案里怎么称呼它，缺省「API Key」。"""
    what = what or t('cred.what.api_key')
    if not isinstance(value, str):
        raise CredentialsError(t('cred.not_str', what))
    token = value.strip()
    if not token:
        raise CredentialsError(t('cred.empty', what))
    if not token.startswith(TOKEN_PREFIX):
        raise CredentialsError(t('cred.prefix', what, TOKEN_PREFIX))
    if not _TOKEN_BODY.match(token[len(TOKEN_PREFIX):]):
        raise CredentialsError(t('cred.charset', what, TOKEN_PREFIX))
    return token


def mask(token):
    """前缀 + 随机段前 8 位 + '...'：网站的 Key 列表显示同一串，对得上是哪一把。"""
    return token[:len(TOKEN_PREFIX) + MASK_VISIBLE] + '...'


def now():
    """带时区的当前时刻（测试替换它来拨钟）。"""
    return datetime.now(timezone.utc).astimezone()


def parse_time(value):
    """ISO 8601 → 带时区的 datetime；None 原样返回；认不出抛 ValueError。"""
    if value is None:
        return None
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class Credential(object):
    """一份通过了离线校验的凭证。repr / str 只显示掩码。

    kind        api_key / oauth（从参数、环境变量来的一律按 api_key 看：SDK 只知道它是一串 Key）
    source      argument / env / saved
    expires_at  网页登录的到期时刻（ISO 8601），API Key 为 None
    user        保存时记下的 {public_id, name}，参数与环境变量来的为 None"""
    __slots__ = ('_token', 'kind', 'source', 'expires_at', 'user', 'device_name', 'created_at')

    def __init__(self, token, kind='api_key', source='argument', expires_at=None, user=None, device_name=None,
                 created_at=None):
        if kind not in KINDS:
            raise CredentialsError(t('cred.unknown_kind', kind))
        self._token = check_token(token, t('cred.what.oauth' if kind == 'oauth' else 'cred.what.api_key'))
        self.kind, self.source = kind, source
        self.expires_at, self.user = expires_at, user
        self.device_name, self.created_at = device_name, created_at

    @property
    def mask(self):
        return mask(self._token)

    def authorization(self):
        """Authorization 请求头的值。"""
        return 'Bearer ' + self._token

    def expires(self):
        """到期时刻（datetime），不过期的为 None。"""
        return parse_time(self.expires_at) if self.expires_at else None

    def expired(self, at=None):
        exp = self.expires()
        return exp is not None and (at or now()) >= exp

    def entry(self):
        """凭证文件里的一项。"""
        return {'kind': self.kind, 'token': self._token, 'expires_at': self.expires_at, 'user': self.user,
                'device_name': self.device_name, 'created_at': self.created_at}

    def __repr__(self):
        return 'Credential(kind=%r, source=%r, token=%r, expires_at=%r)' % (
            self.kind, self.source, self.mask, self.expires_at)

    __str__ = __repr__


def config_dir():
    """凭证目录：QUAFU_CONFIG_DIR，缺省 ~/.quafu-sdk（解析在 _i18n.config_root，界面语言的设置文件也放这里）。
    指到用户主目录之外时 warning 一次（可能多人可读）。"""
    d = config_root()
    if not os.environ.get(ENV_CONFIG_DIR):
        return d
    home = os.path.abspath(os.path.expanduser('~'))
    if d != home and not d.startswith(home.rstrip(os.sep) + os.sep) and d not in _warned_dirs:
        _warned_dirs.add(d)
        log.warning(t('cred.dir_outside_home'), d)
    return d


def credentials_path():
    return os.path.join(config_dir(), FILE_NAME)


def _hint(path, what):
    return t('cred.hint', path, what, ENV_CONFIG_DIR)


def _empty():
    return {'version': FILE_VERSION, 'profiles': {}}


def _load(path):
    """读凭证文件，返回 {'version': 1, 'profiles': {...}}；文件不存在返回空结构。
    路径是符号链接时拒绝（O_NOFOLLOW）。坏 JSON、缺字段、版本不认、读不了，一律 CredentialsError。"""
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    except FileNotFoundError:
        return _empty()
    except OSError as e:
        if e.errno == errno.ELOOP or os.path.islink(path):
            raise CredentialsError(_hint(path, t('cred.symlink_read'))) from None
        raise CredentialsError(_hint(path, t('cred.unreadable', type(e).__name__))) from None
    if not _NOFOLLOW and os.path.islink(path):            # 没有 O_NOFOLLOW 的平台（Windows）补一道
        os.close(fd)
        raise CredentialsError(_hint(path, t('cred.symlink_read')))
    try:
        with os.fdopen(fd, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise CredentialsError(_hint(path, t('cred.unreadable', type(e).__name__))) from None
    if not isinstance(data, dict) or not isinstance(data.get('profiles'), dict):
        raise CredentialsError(_hint(path, t('cred.bad_format')))
    if data.get('version') != FILE_VERSION:
        raise CredentialsError(_hint(path, t('cred.bad_version', data.get('version'), FILE_VERSION)))
    return data


def _write(path, data):
    """先写同目录的临时文件再 os.replace，原子替换；os.open 一步建成 0600，没有 umask 窗口。
    目标是符号链接时拒绝。Windows 上目标文件被别的进程开着时 replace 会失败，重试三次再报。"""
    if os.path.islink(path):
        raise CredentialsError(_hint(path, t('cred.symlink_write')))
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        if os.path.lexists(tmp):
            os.remove(tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        for i in range(3):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if i == 2:
                    raise
                time.sleep(0.2)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise CredentialsError(_hint(path, t('cred.unwritable', type(e).__name__))) from None


def saved(profile):
    """本机为这个 BASE_URL 保存的凭证（Credential，source='saved'），没有返回 None。"""
    path = credentials_path()
    entry = _load(path)['profiles'].get(profile)
    if entry is None:
        return None
    if not isinstance(entry, dict) or entry.get('kind') not in KINDS or not isinstance(entry.get('token'), str):
        raise CredentialsError(_hint(path, t('cred.entry_incomplete', profile)))
    try:
        cred = Credential(entry['token'], kind=entry['kind'], source='saved', expires_at=entry.get('expires_at'),
                          user=entry.get('user'), device_name=entry.get('device_name'),
                          created_at=entry.get('created_at'))
        cred.expires()
    except (CredentialsError, ValueError, TypeError):
        raise CredentialsError(_hint(path, t('cred.entry_bad', profile))) from None
    return cred


def save(profile, cred):
    """把 cred 存成这个 BASE_URL 的登录态（覆盖旧的），返回文件路径。"""
    path = credentials_path()
    data = _load(path)
    data['profiles'][profile] = cred.entry()
    _write(path, data)
    return path


def remove(profile):
    """删掉这个 BASE_URL 的登录态，返回被删的那份（Credential），本来就没有返回 None。只动本机文件。"""
    path = credentials_path()
    data = _load(path)
    if profile not in data['profiles']:
        return None
    try:
        old = saved(profile)
    except CredentialsError:
        old = None                  # 坏的一项照样删掉，只是没法拿它去撤销
    del data['profiles'][profile]
    _write(path, data)
    return old


def resolve(api_key, profile):
    """按优先级找凭证：参数 > 环境变量 QUAFU_API_KEY > 本机保存的这个 BASE_URL 的登录态。都没有返回 None。"""
    if api_key is not None:
        return Credential(api_key, 'api_key', 'argument')
    env = os.environ.get(ENV_KEY)
    if env and env.strip():
        try:
            return Credential(env, 'api_key', 'env')
        except CredentialsError as e:
            raise CredentialsError(t('env_var', ENV_KEY, e)) from None
    return saved(profile)
