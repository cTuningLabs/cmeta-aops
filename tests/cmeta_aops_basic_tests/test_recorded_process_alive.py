"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The check every task of this repository asks before it trusts the process number of a record (category/task/api/
ctask.py: recorded_process_alive, recorded_file_alive): the record must be from this boot, the process alive, and not
started after the record was written - after a restart the numbers are given out again, and a stale record names any
other program (the Labs server of 2026-11-13 found "running" a helper of its own start). The tasks that stop what a
record names (run-openssh, run-llama-cpp-server, run-paperclip, run-openshell-gateway, test-on-hosts,
start-after-restart) all take it from there.
"""

import importlib.util
import os
import pathlib
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def ctask():
    spec = importlib.util.spec_from_file_location('ctask_helpers_under_test', str(REPO_ROOT / 'category' / 'task' / 'api' / 'ctask.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_boot_is_in_the_past(ctask):
    boot = ctask.boot_time()
    assert boot is not None
    assert time.time() - 10 * 365 * 86400 < boot < time.time()


def test_this_process_started_after_the_boot_and_before_now(ctask):
    started = ctask.process_started(os.getpid())
    assert started is not None
    assert ctask.boot_time() - 5 < started <= time.time() + 1


def test_a_record_of_this_run_is_alive(ctask):
    assert ctask.recorded_process_alive(os.getpid(), time.time()) is True


def test_a_record_from_before_the_boot_is_stale(ctask):
    # whatever has the number now: the record was written before the machine started
    assert ctask.recorded_process_alive(os.getpid(), ctask.boot_time() - 3600) is False


def test_a_process_started_after_the_record_has_taken_the_number(ctask):
    started = ctask.process_started(os.getpid())
    assert ctask.recorded_process_alive(os.getpid(), started - 60) is False
    # a few seconds of slack: a record written just before its process started (a wrapper writes it) still counts
    assert ctask.recorded_process_alive(os.getpid(), started - 2) is True


def test_a_dead_process_and_no_number_are_never_alive(ctask):
    assert ctask.recorded_process_alive(os.getpid(), time.time(), alive=lambda pid: False) is False
    assert ctask.recorded_process_alive(0, time.time()) is False
    assert ctask.recorded_process_alive(None, time.time()) is False


def test_a_pid_file_is_judged_by_when_it_was_written(ctask, tmp_path):
    pid_file = tmp_path / 'server.pid'
    pid_file.write_text(str(os.getpid()))
    assert ctask.recorded_file_alive(str(pid_file)) is True
    assert ctask.recorded_file_alive(str(pid_file), os.getpid()) is True
    stale = ctask.boot_time() - 3600
    os.utime(str(pid_file), (stale, stale))
    assert ctask.recorded_file_alive(str(pid_file)) is False
    assert ctask.recorded_file_alive(str(tmp_path / 'missing.pid'), os.getpid()) is False
