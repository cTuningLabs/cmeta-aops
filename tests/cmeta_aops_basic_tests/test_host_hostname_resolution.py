"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/host resolves the hostname to add its addresses, but a name no resolver knows (a CI runner, a
machine without a DNS entry) made every task run wait for the resolver's timeouts - half a minute on
some machines. The lookup is bounded now: after two seconds the task goes on with the addresses it
found without DNS.
"""

import pathlib
import socket
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def host_module():
    path = REPO_ROOT / "task" / "host" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from task_c36be4b9314a45e0.api.ctask import InitCTask",
                                                     "class InitCTask: pass")
    ns = {"__name__": "task_host_under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def test_a_slow_resolver_does_not_hold_the_task(monkeypatch):
    def slow_getaddrinfo(host, port, *args, **kwargs):
        time.sleep(8)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", slow_getaddrinfo)
    ns = host_module()
    started = time.time()
    info = ns["get_hostname_info"]()
    assert time.time() - started < 5
    assert info["hostname"]
    assert not (info["ipv4"] and "203.0.113.7" in info["ipv4"])     # the late answer is not waited for


def test_a_quick_resolver_adds_its_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", 0)),
                                                     (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::7", 0, 0, 0))])
    info = host_module()["get_hostname_info"]()
    assert "203.0.113.7" in info["ipv4"] and "2001:db8::7" in info["ipv6"]


def test_a_failing_resolver_is_not_an_error(monkeypatch):
    def failing(host, port, *a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", failing)
    ns = host_module()
    assert ns["resolve_hostname_addresses"]("nowhere.invalid") == []
    info = ns["get_hostname_info"]()
    assert info["hostname"]
