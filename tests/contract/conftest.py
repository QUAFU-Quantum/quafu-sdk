# -*- coding: utf-8 -*-
"""契约测试夹具：用任务分发器自己的环境在子进程里起一份真任务分发器，SDK 经真 HTTP 连它。

为什么不在测试进程里 import 任务分发器：两边的依赖与 Python 版本互不牵扯（任务分发器按它自己的 pyproject，
SDK 这边 3.9 也能跑契约测试），也免得任务分发器的依赖混进 SDK 的依赖切割检查。子进程用 `uv run --project dispatcher`。

线上 nginx 把 {BASE_URL}/api/v1/* 转到任务分发器的 /v1/*；这里用一个本机小代理做同样的改写，
SDK 照常以「门户地址」连它、自己拼 /api/v1，测到的就是真实的地址拼法。
数据落临时目录、不出网（设备数据走快照兜底）、不开真机通道。不在 Linux 上、没有 uv 或没给任务分发器源码目录时整组跳过；
第一次跑要先同步任务分发器的虚拟环境，慢一些。"""
import http.client
import http.server
import json
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from quafu.errors import ServerUnavailable
from quafu.transport import HTTPTransport

SDK_DIR = Path(__file__).resolve().parents[2]
# 任务分发器是平台的服务端，源码不在本仓库：QP_DISPATCHER_DIR 指向它的源码目录（含 pyproject.toml）才跑契约测试
DISPATCHER_DIR = Path(os.environ.get('QP_DISPATCHER_DIR') or '/nonexistent').resolve()
PASSWORD = 'pw-12345678'
BOOT = '''
import os, uvicorn
from quafu_dispatcher import create_app, migrate
migrate.upgrade(quiet=True, do_backup=False)
uvicorn.run(create_app(), host='127.0.0.1', port=int(os.environ['QP_DISPATCHER_PORT']), log_level='warning')
'''


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def call(base, method, path, body=None, token=None):
    """测试自己对任务分发器发的请求（注册、登录、签 key），返回 (状态码, JSON)。"""
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(body).encode('utf-8') if body is not None else None
    r = HTTPTransport().request(method, base + path, headers, data, 5, 60)
    return r.status, json.loads(r.body.decode('utf-8') or 'null')


class RecordingTransport(HTTPTransport):
    """真 HTTP 传输层，另记下每个请求（path 去掉 /api/v1 前缀）；lose 里的 (method, path) 照常发出、处理，
    但回应丢一次，模拟超时后的重放场景。"""

    def __init__(self):
        super().__init__()
        self.calls, self.lose = [], set()

    def request(self, method, url, headers, body, connect_timeout, read_timeout):
        u = urlsplit(url)
        path = u.path[len('/api/v1'):] if u.path.startswith('/api/v1/') else u.path
        is_json = body and headers.get('Content-Type') == 'application/json'
        self.calls.append({'method': method, 'path': path, 'query': dict(parse_qsl(u.query)),
                           'headers': dict(headers), 'body': json.loads(body) if is_json else None,
                           'form': dict(parse_qsl(body.decode('ascii'))) if body and not is_json else None})
        resp = super().request(method, url, headers, body, connect_timeout, read_timeout)
        if (method, path) in self.lose:
            self.lose.discard((method, path))
            raise ServerUnavailable('模拟：请求已处理但回应丢失', sent=True)
        return resp

    def posts(self, path):
        return [c for c in self.calls if c['method'] == 'POST' and c['path'] == path]


class _Proxy(http.server.BaseHTTPRequestHandler):
    """{BASE}/api/v1/* → 任务分发器 /v1/*，原样转发方法、头与体（线上 nginx 的 location /api/v1/ 同此）。"""
    upstream = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def _forward(self):
        if not self.path.startswith('/api/v1/'):
            body = b'{"detail": "Not Found"}'
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        n = int(self.headers.get('Content-Length') or 0)
        data = self.rfile.read(n) if n else None
        host, port = self.upstream
        c = http.client.HTTPConnection(host, port, timeout=300)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'connection')}
        c.request(self.command, self.path[len('/api'):], body=data, headers=headers)
        r = c.getresponse()
        payload = r.read()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in ('transfer-encoding', 'connection', 'content-length', 'server', 'date'):
                self.send_header(k, v)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        c.close()

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = _forward


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


@pytest.fixture(scope='session')
def base_url(dispatcher_url):
    """一个本机门户地址：SDK 的 base_url 指向它。"""
    u = urlsplit(dispatcher_url)
    handler = type('Proxy', (_Proxy,), {'upstream': (u.hostname, u.port)})
    srv = _ThreadingServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield 'http://127.0.0.1:%d' % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


@pytest.fixture(scope='session')
def dispatcher_url(tmp_path_factory):
    """起一个任务分发器子进程，返回它的 {BASE}/v1；会话结束时关掉。"""
    # 任务分发器给模拟器子进程设 RLIMIT_AS，只有 Linux 设得上；
    # macOS、Windows 上凡要跑模拟的任务都会以 runtime.internal 失败，红的是环境不是 SDK，所以整组跳过、写明原因
    if not sys.platform.startswith('linux'):
        pytest.skip('契约测试只在 Linux 上跑（本机 %s）：本机起的任务分发器要给模拟器子进程设 RLIMIT_AS，'
                    '这里设不上，要跑模拟的任务会失败；未验证，结论以 Linux 那一轮为准' % sys.platform)
    uv = shutil.which('uv')
    if not uv or not (DISPATCHER_DIR / 'pyproject.toml').exists():
        pytest.skip('契约测试要 uv，并用 QP_DISPATCHER_DIR 指向任务分发器源码目录')
    data = tmp_path_factory.mktemp('dispatcher-data')
    boot = data / 'boot.py'
    boot.write_text(BOOT, encoding='utf-8')
    port = _free_port()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('QUAFU_', 'VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT'))}
    # 任务分发器源码对我们只读：虚拟环境建在本目录（.venv-dispatcher，已 gitignore），--frozen 不改它的 uv.lock，不写字节码
    env.update(QD_DATA_DIR=str(data), QD_DEVICES_LIVE='0', QP_DISPATCHER_PORT=str(port), PYTHONDONTWRITEBYTECODE='1',
               UV_PROJECT_ENVIRONMENT=str(SDK_DIR / '.venv-dispatcher'),
               # 注册的 per-IP 频次闸对这套测试是致命的：每个用例注册一个新账号，全部来自 127.0.0.1，
               # 而默认是 30 次/小时、100 次/天（config.REGISTER_PER_IP_PER_*）。本套 50 个用例，
               # 第 31 个起一律 429 register_too_frequent，报出来的却是各式各样的 AssertionError，
               # 很难看出是同一个原因。这个闸是 v1.36 随 register_log（迁移 0010）加的，加之前这套测试是好的，
               # 所以它不是「测试写错了」而是被后加的护栏挡住——护栏本身没问题，是测试环境该把它放开。
               QD_REGISTER_PER_IP_PER_HOUR='100000', QD_REGISTER_PER_IP_PER_DAY='100000',
               # 九鼎模拟打开、但不给 worker 凭证：看护线程不会去九鼎起 worker，三台都是 offline，
               # 测的是列表、metadata 与「不可用时提交回 503」这几处接口形状
               QD_JDSIM='1', QD_JDSIM_WORKER_SECRET='')
    log_path = data / 'dispatcher.log'
    with open(log_path, 'w') as log:
        proc = subprocess.Popen([uv, 'run', '--project', str(DISPATCHER_DIR), '--frozen', '--no-dev', '--quiet',
                                 'python', str(boot)],
                                cwd=str(data), env=env, stdout=log, stderr=subprocess.STDOUT)
        base = 'http://127.0.0.1:%d' % port
        deadline = time.monotonic() + 600
        try:
            while True:
                if proc.poll() is not None:
                    pytest.fail('任务分发器起不来：\n%s' % log_path.read_text(encoding='utf-8')[-3000:])
                try:
                    if HTTPTransport().request('GET', base + '/healthz', {}, None, 1, 2).status == 200:
                        break
                except ServerUnavailable:
                    pass
                if time.monotonic() > deadline:
                    pytest.fail('任务分发器 600 秒内没起来：\n%s' % log_path.read_text(encoding='utf-8')[-3000:])
                time.sleep(0.5)
            yield base + '/v1'
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()


def register(dispatcher_url):
    email = 'sdk-%s@example.com' % uuid.uuid4().hex[:10]
    status, body = call(dispatcher_url, 'POST', '/auth/register',
                        {'email': email, 'password': PASSWORD, 'name': 'SDK 契约', 'org': '测试机构'})
    assert status == 201, body
    status, body = call(dispatcher_url, 'POST', '/auth/login', {'email': email, 'password': PASSWORD})
    assert status == 200, body
    return email, body['token']


@pytest.fixture
def issue(dispatcher_url):
    """新注册一个账号，用会话签一把 API key，返回 (email, key)。"""
    def issue():
        email, token = register(dispatcher_url)
        status, body = call(dispatcher_url, 'POST', '/api-keys', {'name': 'sdk-contract'}, token=token)
        assert status == 201, body
        return email, body['key']
    return issue


@pytest.fixture
def user(dispatcher_url):
    """新注册一个账号，返回 {email, session}：session 是网站登录会话的令牌（网页登录时「浏览器里那个人」）。"""
    email, token = register(dispatcher_url)
    return {'email': email, 'session': token}


@pytest.fixture
def transport(base_url, monkeypatch):
    from quafu import jobs
    monkeypatch.setenv('QUAFU_BASE_URL', base_url)
    monkeypatch.setattr(jobs, 'POLL_FIRST', 0.05)
    return RecordingTransport()


@pytest.fixture
def account(issue):
    return issue()


@pytest.fixture
def client(account, transport):
    """核心 Client，带一把 API Key。"""
    import quafu
    return quafu.Client(api_key=account[1], _transport=transport)
