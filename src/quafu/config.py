# -*- coding: utf-8 -*-
"""平台地址：全包只在这里定。

BASE_URL 是 QUAFU 门户的地址（scheme://host[:port]，不带路径）。解析顺序，先到先得：
  1. 参数 base_url=...（Client、login、logout、whoami 都收）
  2. 环境变量 QUAFU_BASE_URL
  3. 内置默认值 DEFAULT_BASE_URL
SDK 自己在它后面拼程序端入口 /api/v1 与网页登录页 /oauth/*，用户不必知道这些路径。

内置默认值是「发行出去的客户端必须带一个字面默认值」的那处例外（仓库 docs/base-url.md 第 4 节）：
装完第一次用就能给出登录链接，不需要先配置任何东西。平台换地址时要发新版本改它。"""
import os
from urllib.parse import urlsplit

from ._i18n import t
from .errors import QuafuError

DEFAULT_BASE_URL = 'https://quafu.com.cn'
ENV_BASE_URL = 'QUAFU_BASE_URL'
API_PREFIX = '/api/v1'
LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')


def check_base_url(url):
    """BASE_URL 的硬规则，返回规整后的 scheme://host[:port]（主机名小写、去掉默认端口与尾斜杠）。

    必须 https；http 只许本机回环地址（本地起服务测试用）。不带路径——旧文档里的 .../api/v1 写法在这里
    报清楚，而不是拼成 .../api/v1/api/v1 再收一个看不懂的 404。"""
    if not isinstance(url, str) or not url.strip():
        raise QuafuError(t('config.empty'))
    raw = url.strip()
    try:
        u = urlsplit(raw)
        port = u.port
    except ValueError:
        raise QuafuError(t('config.bad_format', raw)) from None
    scheme, host = u.scheme.lower(), (u.hostname or '').lower()
    if scheme not in ('https', 'http') or not host:
        raise QuafuError(t('config.need_host', raw))
    if scheme == 'http' and host not in LOOPBACK_HOSTS:
        raise QuafuError(t('config.https_required', raw))
    if u.path.rstrip('/') or u.query or u.fragment:
        raise QuafuError(t('config.no_path', DEFAULT_BASE_URL, raw))
    if u.username or u.password:
        raise QuafuError(t('config.no_userinfo'))
    netloc = '[%s]' % host if ':' in host else host
    if port is not None and port != {'https': 443, 'http': 80}[scheme]:
        netloc += ':%d' % port
    return '%s://%s' % (scheme, netloc)


def resolve_base_url(base_url=None):
    """参数 > 环境变量 QUAFU_BASE_URL > 内置默认值，返回规整后的地址。"""
    if base_url is not None:
        return check_base_url(base_url)
    env = os.environ.get(ENV_BASE_URL)
    if env and env.strip():
        try:
            return check_base_url(env)
        except QuafuError as e:
            raise QuafuError(t('env_var', ENV_BASE_URL, e)) from None
    return DEFAULT_BASE_URL


def api_root(base_url):
    """程序端入口：{BASE_URL}/api/v1。"""
    return base_url + API_PREFIX
