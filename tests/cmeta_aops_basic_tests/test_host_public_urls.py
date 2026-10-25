"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx host status" checks a project's public URLs from this machine (projects: <name>: server: public), beside the
server check that runs on the host: works (HTTP 2xx or 3xx, a redirect not followed), http <code>, timeout,
unreachable; a server.url that is not a local address counts as public. Local HTTP servers stand in for the sites.
"""

import http.server
import importlib.util
import pathlib
import socket
import threading
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def module():
    spec = importlib.util.spec_from_file_location('host_public_under_test', REPO_ROOT / 'category/host/api/v1.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def host(module):
    c = module.Category.__new__(module.Category)
    c.cm = SimpleNamespace(error=lambda s: {'return': 1, 'error': s}, catch_error=lambda r: r['return'] > 0)
    return c


def serve(code, location=None):
    """A local HTTP server answering `code` to every request; returns (url, shutdown)."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(code)
            if location:
                self.send_header('Location', location)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{srv.server_port}/healthz', srv.shutdown


def test_which_urls_are_public(module):
    public = module.Category._public_urls
    assert public({'url': 'http://127.0.0.1:8338/healthz'}) == []
    assert public({'url': 'http://localhost:8004/'}) == []
    assert public({'url': 'http://100.79.25.50:8338/'}) == []                       # Tailscale: private
    assert public({'url': 'http://vm.internal:8338/'}) == []
    assert public({'url': 'https://adapt-workshop.org/'}) == ['https://adapt-workshop.org/']
    assert public({'url': 'http://127.0.0.1:8338/healthz', 'public': 'https://a.example/healthz'}) == ['https://a.example/healthz']
    assert public({'url': 'http://127.0.0.1:1/', 'public': ['https://a.example/', 'https://b.example/']}) == ['https://a.example/', 'https://b.example/']
    assert public({}) == []


def test_public_status_of_every_kind(host):
    ok, stop_ok = serve(200)
    moved, stop_moved = serve(303, 'http://127.0.0.1:1/login')
    bad, stop_bad = serve(503)
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    dead = f'http://127.0.0.1:{s.getsockname()[1]}/'
    s.close()
    h = {'alias': 'vm', 'type': 'ssh', 'desc': {'projects': {'site': {'server': {'url': 'http://127.0.0.1:8338/healthz',
                                                                                  'public': [ok, moved, bad, dead]}},
                                                             'bare': {}}}, 'state': {}}
    try:
        host._public_status_all([h], timeout=2)
    finally:
        stop_ok(); stop_moved(); stop_bad()
    results = {r['url']: r for r in h['public_status']['site']}
    assert results[ok]['status'] == 'works' and results[ok]['http_status'] == 200
    assert results[moved]['status'] == 'works' and results[moved]['http_status'] == 303      # the sign-in redirect, not followed
    assert results[bad]['status'] == 'http 503'
    assert results[dead]['status'] in ('unreachable', 'timeout')
    assert 'bare' not in h['public_status']
    rows = host._project_rows(h)
    assert [r['alias'] for r in rows] == ['site', 'bare'] and len(rows[0]['public']) == 4 and rows[1]['public'] == []
    details = host._project_details([h], ['HOST', 'TYPE', 'OS', 'STATUS', 'ADDRESS'])['vm']
    lines = [r for r in details if r.get('type') == 'web']
    assert len(lines) == 4 and lines[0]['alias'].startswith('      127.0.0.1:') and lines[0]['status'] == 'works'
    assert lines[2]['status'] == 'http 503' and lines[2]['extra'] == '(HTTP 503)'


def test_a_retired_host_is_not_checked(host):
    h = {'alias': 'old', 'type': 'ssh', 'desc': {'retired': True, 'projects': {'site': {'server': {'public': ['http://127.0.0.1:1/']}}}}, 'state': {}}
    host._public_status_all([h], timeout=1)
    assert h['public_status'] == {}
