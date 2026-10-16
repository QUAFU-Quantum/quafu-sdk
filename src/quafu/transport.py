# -*- coding: utf-8 -*-
"""HTTP 传输层：标准库 http.client，一个请求一条连接。

- 连接超时与读超时分开：建连用 connect_timeout，连上后 sock.settimeout(read_timeout)。DNS 解析不在超时内。
- 默认不走系统代理：不读 HTTP(S)_PROXY、不读 Windows 注册表。只有显式给 proxy 时才经 CONNECT 隧道走。
- TLS 永远校验证书；自签 CA 只能经 ca_bundle 给一份 PEM，没有关闭校验的开关。
- 不跟随跳转：3xx 原样交给上层，由上层报成协议错误（POST 跟随跳转会丢请求体）。

网络层的失败一律包成 ServerUnavailable；sent 标明请求是否可能已经发出（提交能否安全重试靠它）。
可注入：任何有同签名 request() 的对象都能替代它（单元测试用假传输层）。"""
import http.client
import socket
import ssl
from urllib.parse import urlsplit

from ._i18n import t
from .errors import ServerUnavailable, QuafuError


class Response(object):
    """status：HTTP 码；headers：键已小写的 dict；body：原始字节。"""
    __slots__ = ('status', 'headers', 'body')

    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body


def parse_proxy(proxy):
    """'host:port' 或带 http 协议头的写法 → (host, port)。只支持 HTTP 代理（经 CONNECT 隧道转发 TLS）。"""
    u = urlsplit(proxy if '//' in proxy else '//' + proxy)
    if u.scheme not in ('', 'http') or not u.hostname:
        raise QuafuError(t('transport.proxy_http_only', proxy))
    try:
        return u.hostname, u.port or 8080
    except ValueError:
        raise QuafuError(t('transport.proxy_port', proxy)) from None


class HTTPTransport(object):
    def __init__(self, ca_bundle=None, proxy=None):
        self.ca_bundle = ca_bundle
        self.proxy = parse_proxy(proxy) if proxy else None
        self._ctx = None

    def _context(self):
        if self._ctx is None:
            try:
                self._ctx = ssl.create_default_context(cafile=self.ca_bundle)
            except (OSError, ssl.SSLError) as e:
                raise QuafuError(t('transport.ca_unreadable', self.ca_bundle, type(e).__name__)) from e
        return self._ctx

    def _via(self):
        return t('transport.via_proxy', *self.proxy) if self.proxy else t('transport.no_proxy')

    def _proxy_hint(self, sent):
        """直连没连上时补半句怎么设代理：必须走代理的网络里，用户只看到「未经代理」不知道下一步。"""
        return '' if self.proxy or sent else t('transport.proxy_hint')

    def request(self, method, url, headers, body, connect_timeout, read_timeout):
        """发一个请求，返回 Response（任何 HTTP 码都算成功返回）；网络层失败抛 ServerUnavailable。"""
        u = urlsplit(url)
        https = u.scheme == 'https'
        host, port = u.hostname, u.port or (443 if https else 80)
        path = (u.path or '/') + ('?' + u.query if u.query else '')
        dial = self.proxy or (host, port)
        if https:
            conn = http.client.HTTPSConnection(dial[0], dial[1], timeout=connect_timeout, context=self._context())
        else:
            conn = http.client.HTTPConnection(dial[0], dial[1], timeout=connect_timeout)
        if self.proxy:
            conn.set_tunnel(host, port)
        sent = False
        try:
            conn.connect()
            conn.sock.settimeout(read_timeout)
            sent = True
            conn.request(method, path, body=body, headers=headers)
            r = conn.getresponse()
            data = r.read()
            return Response(r.status, {k.lower(): v for k, v in r.getheaders()}, data)
        # 捕获清单按序写死：证书校验（它同时是 OSError 与 ValueError，先接）→ 网络层 → HTTP 协议层 → 解码。
        # socket.timeout 显式列出：3.9 上它不是 TimeoutError。只接 Exception 的子类，Ctrl-C 照常穿透。
        except ssl.SSLCertVerificationError as e:
            raise ServerUnavailable(t('transport.cert_failed', host, e.verify_message or type(e).__name__),
                                     sent=False) from e
        except socket.timeout as e:
            what = t('transport.no_response', read_timeout) if sent else t('transport.connect_timeout', connect_timeout)
            raise ServerUnavailable(t('transport.timeout', host, what, self._via()) + self._proxy_hint(sent),
                                     sent=sent) from e
        except OSError as e:
            raise ServerUnavailable(t('transport.connect_failed', host, type(e).__name__, self._via())
                                     + self._proxy_hint(sent), sent=sent) from e
        except http.client.HTTPException as e:
            raise ServerUnavailable(t('transport.bad_http', host, type(e).__name__, self._via()), sent=sent) from e
        except ValueError as e:
            raise ServerUnavailable(t('transport.comm_error', host, type(e).__name__), sent=sent) from e
        finally:
            conn.close()
