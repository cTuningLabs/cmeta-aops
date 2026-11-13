"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The website runtime of manage-cmeta-project (a background start: server.pid and server.log in the runtime folder)
trusts its server.pid only while it names the server it started (2026-11-13): after a server's reboot the record
of the day before named a number a process of the new boot held - the start said "Already running" and returned, the
website stayed down for minutes, and a stop would have killed that unrelated process. A record written before the
machine's last boot, or naming a process that started after the record was written, is stale: never "already
running", never stopped. Checked here with real processes on this system (Windows, Linux, macOS).
"""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from test_cmeta_project_current_home import call, shared_fixture  # noqa: F401 - the fixture of the background start

AOPS = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def runtime():
    spec = importlib.util.spec_from_file_location('website_runtime_stale_pid_test', AOPS / 'task/manage-cmeta-project/runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sleeper():
    """A live process that is not a website server: what a reused process number names after a reboot."""
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], stdin=subprocess.DEVNULL)
    time.sleep(0.5)
    yield p
    p.kill()
    p.wait()


def record(path, pid, written):
    path.write_text(str(pid), encoding='utf-8')
    os.utime(str(path), (written, written))


def test_the_system_says_when_it_started_and_when_a_process_started(runtime, sleeper):
    boot = runtime.boot_time()
    now = time.time()
    assert 0 < boot < now, boot
    started = runtime.process_started(sleeper.pid)
    assert started is not None and abs(started - now) < 30, (started, now)          # started a moment ago
    mine = runtime.process_started(os.getpid())
    assert mine is not None and boot - 5 <= mine <= now + 5, (boot, mine, now)
    assert runtime.process_started(2 ** 22 + 3) is None                             # no such process


def test_a_record_of_the_server_it_started_is_trusted(runtime, sleeper, tmp_path):
    pid_file = tmp_path / 'server.pid'
    record(pid_file, sleeper.pid, time.time())                 # written after the process started: the normal case
    assert runtime.recorded_server(pid_file) == sleeper.pid


def test_a_record_from_before_the_boot_is_stale(runtime, sleeper, tmp_path):
    """After a reboot: whatever holds the number now, the record names a process of the boot before."""
    pid_file = tmp_path / 'server.pid'
    record(pid_file, sleeper.pid, runtime.boot_time() - 3600)
    assert runtime.recorded_server(pid_file) == 0


def test_a_record_naming_a_process_started_after_it_is_stale(runtime, sleeper, tmp_path):
    """The number given again to another process (after a reboot, or after the server died)."""
    pid_file = tmp_path / 'server.pid'
    started = runtime.process_started(sleeper.pid)
    record(pid_file, sleeper.pid, max(runtime.boot_time() + 1, started - 60))
    assert runtime.recorded_server(pid_file) == 0


def test_a_missing_dead_or_broken_record(runtime, tmp_path):
    pid_file = tmp_path / 'server.pid'
    assert runtime.recorded_server(pid_file) == 0                                  # none
    p = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.DEVNULL)
    p.wait()
    record(pid_file, p.pid, time.time())
    assert runtime.recorded_server(pid_file) == 0                                  # gone
    pid_file.write_text('not a number', encoding='utf-8')
    assert runtime.recorded_server(pid_file) == 0


def test_stop_never_kills_the_process_a_stale_record_names(runtime, sleeper, tmp_path):
    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir()
    record(runtime_dir / 'server.pid', sleeper.pid, runtime.boot_time() - 3600)
    status = runtime.native_control('status', runtime_dir)
    assert status['running'] is False and status['pid'] == 0
    stopped = runtime.native_control('stop', runtime_dir)
    assert stopped['running'] is False
    time.sleep(1)
    assert sleeper.poll() is None, 'the stop killed a process a stale record named'


def test_a_background_start_goes_ahead_over_a_stale_record(shared_fixture, sleeper):  # noqa: F811
    """The whole start as the host's after_restart runs it: the record names a live process that is not the server
    (written before that process started) - the start must start the server, and its stop must leave that process."""
    cm, root, profile = shared_fixture
    profile = dict(profile, task='task::site-sleeper,3f81d0c6a95e4b27')
    assert call(cm, action='bootstrap', project_home=str(root), profile=profile)['return'] == 0
    runtime_dir = Path(cm.home_path) / 'repos/local/state/website-probe-site/runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    stale = time.time() - 3600
    record(runtime_dir / 'server.pid', sleeper.pid, stale)
    started = call(cm, action='run', project_home=str(root), detach=True)
    assert started['return'] == 0 and started['running'] and not started.get('already'), started
    assert started['pid'] != sleeper.pid
    assert int((runtime_dir / 'server.pid').read_text()) == started['pid']
    stopped = call(cm, action='stop', project_home=str(root))
    assert stopped['return'] == 0 and not stopped['running'], stopped
    assert sleeper.poll() is None, 'the stop killed the process the stale record named'
