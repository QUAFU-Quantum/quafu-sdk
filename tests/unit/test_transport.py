# -*- coding: utf-8 -*-
"""传输层对着本机真 socket 测：分离超时、断连、不跟随跳转、不走系统代理、TLS 只能靠 ca_bundle。"""
import http.server
import inspect
import json
import shutil
import socket
import ssl
import subprocess
import threading
import time

import pytest

from quafu import Client, ServerUnavailable, QuafuError
from quafu.transport import HTTPTransport, parse_proxy

from ..helpers import KEY, SUBPROCESS_TIMEOUT

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def _send(self, status, body, extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/echo':
            return self._send(200, {'ua': self.headers.get('User-Agent'), 'auth': self.headers.get('Authorization')})
        if self.path == '/slow':
            time.sleep(1.5)
            return self._send(200, {})
        if self.path == '/drop':
            self.close_connection = True          # 一个字节不回就断开
            return
        if self.path == '/redirect':
            return self._send(302, b'', {'Location': 'https://elsewhere.test/'})
        if self.path == '/api/v1/auth/me':
            if self.headers.get('Authorization') != 'Bearer ' + KEY:
                return self._send(401, {'error': '未登录', 'code': 'unauthenticated'})
            return self._send(200, {'user': {'email': 'a@b.test', 'public_id': 'u1'}, 'auth_kind': 'api_key'})
        return self._send(404, {'detail': 'Not Found'})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        return self._send(200, {'got': json.loads(body)})


def _serve(ctx=None):
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    srv.daemon_threads = True
    if ctx is not None:
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def server():
    srv = _serve()
    yield 'http://127.0.0.1:%d' % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _closed_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_roundtrip_headers_and_body(server):
    t = HTTPTransport()
    r = t.request('GET', server + '/echo', {'User-Agent': 'ua-x', 'Authorization': 'Bearer k'}, None, 5, 5)
    assert r.status == 200 and json.loads(r.body) == {'ua': 'ua-x', 'auth': 'Bearer k'}
    assert r.headers['content-type'] == 'application/json'
    r = t.request('POST', server + '/post', {'Content-Type': 'application/json'}, b'{"a": 1}', 5, 5)
    assert json.loads(r.body) == {'got': {'a': 1}}


def test_read_timeout_is_separate_and_marks_sent(server):
    t0 = time.monotonic()
    with pytest.raises(ServerUnavailable) as e:
        HTTPTransport().request('GET', server + '/slow', {}, None, 5, 0.3)
    assert e.value.sent is True and time.monotonic() - t0 < 1.2
    assert '0.3 秒内没有应答' in str(e.value)


def test_refused_connection_is_unsent():
    with pytest.raises(ServerUnavailable) as e:
        HTTPTransport().request('GET', 'http://127.0.0.1:%d/x' % _closed_port(), {}, None, 2, 2)
    assert e.value.sent is False and '未经代理' in str(e.value)
    # 直连失败时说清下一步可以设代理
    assert str(e.value).endswith('。如需经代理访问，请设置环境变量 QUAFU_PROXY=主机:端口')


def test_direct_failure_hints_at_quafu_proxy_in_english(monkeypatch):
    monkeypatch.setenv('QUAFU_LANG', 'en')
    with pytest.raises(ServerUnavailable) as e:
        HTTPTransport().request('GET', 'http://127.0.0.1:%d/x' % _closed_port(), {}, None, 2, 2)
    assert 'no proxy). If you need a proxy, set QUAFU_PROXY=host:port' in str(e.value)


def test_dropped_connection_is_dispatcher_unavailable(server):
    with pytest.raises(ServerUnavailable) as e:
        HTTPTransport().request('GET', server + '/drop', {}, None, 5, 5)
    assert e.value.sent is True and 'RemoteDisconnected' in str(e.value)


def test_redirect_is_not_followed(server):
    r = HTTPTransport().request('GET', server + '/redirect', {}, None, 5, 5)
    assert r.status == 302 and r.headers['location'] == 'https://elsewhere.test/'


def test_system_proxy_env_is_ignored(server, monkeypatch):
    bogus = 'http://127.0.0.1:%d' % _closed_port()
    for v in ('HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        monkeypatch.setenv(v, bogus)
    assert HTTPTransport().request('GET', server + '/echo', {}, None, 5, 5).status == 200


def test_explicit_proxy_is_used_and_named_in_errors():
    port = _closed_port()
    with pytest.raises(ServerUnavailable) as e:
        HTTPTransport(proxy='127.0.0.1:%d' % port).request('GET', 'https://gw.test/v1/x', {}, None, 2, 2)
    assert '经代理 127.0.0.1:%d' % port in str(e.value) and 'QUAFU_PROXY' not in str(e.value)


def test_parse_proxy():
    assert parse_proxy('proxy.test:3128') == ('proxy.test', 3128)
    assert parse_proxy('http://proxy.test:3128') == ('proxy.test', 3128)
    for bad in ('https://proxy.test:3128', 'socks5://proxy.test:1080', ''):
        with pytest.raises(QuafuError):
            parse_proxy(bad)


def test_no_switch_to_disable_verification():
    assert list(inspect.signature(HTTPTransport).parameters) == ['ca_bundle', 'proxy']
    assert list(inspect.signature(Client).parameters) == ['api_key', 'base_url', 'ca_bundle', 'proxy', '_transport']


def test_client_over_real_socket(server):
    """本机回环地址可以用 http；SDK 自己拼 /api/v1。"""
    c = Client(api_key=KEY, base_url=server)
    me = c.whoami()
    assert me['email'] == 'a@b.test' and me['public_id'] == 'u1' and me['base_url'] == server


@pytest.mark.skipif(not shutil.which('openssl'), reason='需要 openssl 生成自签证书')
def test_tls_verifies_and_accepts_only_ca_bundle(tmp_path):
    cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key), '-out', str(cert),
                    '-days', '1', '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1'],
                   check=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    srv = _serve(ctx)
    url = 'https://127.0.0.1:%d/echo' % srv.server_address[1]
    try:
        with pytest.raises(ServerUnavailable) as e:
            HTTPTransport().request('GET', url, {}, None, 5, 5)
        assert 'ca_bundle' in str(e.value) and 'QUAFU_CA_BUNDLE' in str(e.value) and e.value.sent is False
        assert HTTPTransport(ca_bundle=str(cert)).request('GET', url, {}, None, 5, 5).status == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_unreadable_ca_bundle_is_quafu_error(tmp_path):
    with pytest.raises(QuafuError):
        HTTPTransport(ca_bundle=str(tmp_path / 'missing.pem')).request('GET', 'https://gw.test/x', {}, None, 1, 1)
