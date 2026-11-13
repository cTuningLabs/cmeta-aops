"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A zombie counts as stopped (2026-11-01): in a container without an init, a detached server or a test-on-hosts runner
that ended is never reaped, os.kill(pid, 0) still finds its pid, and "stop" said "the server process did not stop"
while "peek" showed the runner as running. Both pid_alive() read the state in /proc now. POSIX with /proc (Linux).
"""

import importlib.util
import os
import pathlib
import time
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_runtime():
    path = REPO_ROOT / 'task' / 'manage-cmeta-project' / 'runtime.py'
    spec = importlib.util.spec_from_file_location('project_runtime_under_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_test_on_hosts(helpers):
    path = REPO_ROOT / 'task' / 'test-on-hosts' / 'api_v1.py'
    line = 'from task_c36be4b9314a45e0.api.ctask import InitCTask, recorded_process_alive'
    src = path.read_text(encoding='utf-8')
    assert line in src
    src = src.replace(line, 'class InitCTask:\n    pass')
    ns = types.ModuleType('test_on_hosts_pid_under_test')
    ns.__file__ = str(path)
    ns.__dict__.update(helpers('recorded_process_alive'))
    exec(compile(src, str(path), 'exec'), ns.__dict__)
    return ns


@pytest.mark.skipif(not hasattr(os, 'fork') or not os.path.isdir('/proc'), reason='a zombie needs fork and /proc')
def test_a_zombie_counts_as_stopped(ctask_helpers):
    checks = [load_runtime().pid_alive, load_test_on_hosts(ctask_helpers).pid_alive]
    for alive in checks:
        assert alive(os.getpid()) is True

    pid = os.fork()
    if pid == 0:
        os._exit(0)                                     # the child ends at once; nobody waits for it yet

    # until the kernel shows it as a zombie
    deadline = time.monotonic() + 5
    state = ''
    while time.monotonic() < deadline:
        with open('/proc/%d/stat' % pid, encoding='ascii', errors='replace') as f:
            state = f.read().rsplit(')', 1)[-1].split()[0]
        if state == 'Z':
            break
        time.sleep(0.05)
    assert state == 'Z'

    try:
        for alive in checks:
            assert alive(pid) is False                  # os.kill(pid, 0) still succeeds here
    finally:
        os.waitpid(pid, 0)
    for alive in checks:
        assert alive(pid) is False
