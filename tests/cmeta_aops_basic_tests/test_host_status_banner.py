"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx host status" of an ssh host asks for sshd's identification line, not only for an open port: a server that sends
"SSH-2.0-..." is up, one that accepts and closes at once is "refused", one that stays silent is "no banner", a closed
port is down. Local sockets stand in for the servers.
"""

import importlib.util
import pathlib
import socket
import threading

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def status():
    spec = importlib.util.spec_from_file_location('host_status_under_test', REPO_ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ssh_banner_status


def serve(behaviour):
    """A listening socket whose one accepted connection behaves as asked; returns (port, stop)."""
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def run():
        srv.settimeout(5)
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            if behaviour == 'banner':
                conn.sendall(b'SSH-2.0-OpenSSH_9.9\r\n')
                stop.wait(2)
            elif behaviour == 'silent':
                stop.wait(5)
            # 'close': the connection ends at once
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return port, stop


def test_a_banner_is_up(status):
    port, stop = serve('banner')
    try:
        assert status('127.0.0.1', port, 2) == 'up'
    finally:
        stop.set()


def test_an_accept_without_a_banner_is_refused(status):
    port, stop = serve('close')
    try:
        assert status('127.0.0.1', port, 2) == 'refused'
    finally:
        stop.set()


def test_silence_is_no_banner(status):
    port, stop = serve('silent')
    try:
        assert status('127.0.0.1', port, 1) == 'no banner'
    finally:
        stop.set()


def test_a_closed_port_is_down(status):
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    assert status('127.0.0.1', port, 1) == 'down'
