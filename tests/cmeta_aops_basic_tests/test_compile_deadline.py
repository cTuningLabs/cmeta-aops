"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The compile deadline (--compile_timeout): a deadline in ctx['tasks']['deadlines'] that task/cmd reads.
Every command that runs while it is open gets min(its own timeout, the time left); one that would
start after it is not started; the message names the deadline and the option; closed, nothing is
limited. The deadline is opened and closed by compile-and-run-program around its compile pipeline
(checked by reading its code here; the real runs are in a test session). Offline: small Python
scripts as the commands.
"""

import os
import pathlib
import sys
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = f'"{sys.executable}"'


@pytest.fixture(scope = "module")
def deadlines():
    import importlib.util
    path = REPO_ROOT / "category" / "task" / "api" / "deadlines.py"
    spec = importlib.util.spec_from_file_location("deadlines_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cmd(cm, cmd, ctx = None, **extra):
    p = {"category": "task", "command": "run", "arg1": "cmd", "cmd": cmd, "con": False, "quiet": True}
    if ctx is not None:
        p["ctx"] = ctx
    p.update(extra)
    return cm.access(p)


def sleeper(tmp_path, seconds = 30):
    path = tmp_path / "sleep.py"
    path.write_text(f"import time\ntime.sleep({seconds})\n")
    return f'{PY} "{path}"'


# The module

def test_seconds(deadlines):
    for none in (None, "", 0, "0", False):
        assert deadlines.seconds(none) is None
    assert deadlines.seconds("2.5") == 2 and deadlines.seconds(0.2) == 1 and deadlines.seconds(600) == 600


def test_open_close_nearest(deadlines):
    ctx = {"tasks": {}}
    assert deadlines.open_deadline(ctx, "compile", None, "--compile_timeout") is None
    assert "deadlines" not in ctx["tasks"] and deadlines.nearest(ctx) is None
    a = deadlines.open_deadline(ctx, "compile", 3600, "--compile_timeout")
    b = deadlines.open_deadline(ctx, "build", 60, "--build_timeout")
    assert deadlines.nearest(ctx) is b                      # the one that ends first
    assert 59 <= deadlines.time_left(b) <= 60
    assert deadlines.describe(a) == "the compile deadline of 3600 s (--compile_timeout)"
    deadlines.close_deadline(ctx, b)
    assert deadlines.nearest(ctx) is a
    deadlines.close_deadline(ctx, a)
    deadlines.close_deadline(ctx, None)
    assert "deadlines" not in ctx["tasks"]
    passed = {"name": "x", "seconds": 1, "until": time.time() - 5, "option": "--x"}
    assert deadlines.time_left(passed) == 0


# task/cmd with a deadline

def test_without_a_deadline_nothing_changes(cm, tmp_path):
    r = run_cmd(cm, f'{PY} -c "print(42)"', capture_output = True)
    assert r["return"] == 0 and r["stdout"].strip() == "42" and not r.get("timed_out")


def warm_up(cm):
    """One command before the deadline opens: the first task run of a process also detects the host."""
    assert run_cmd(cm, f'{PY} -c "pass"')["return"] == 0


def test_deadline_stops_a_long_command(cm, deadlines, tmp_path):
    warm_up(cm)
    ctx = {"tasks": {}}
    deadlines.open_deadline(ctx, "compile", 2, "--compile_timeout")
    started = time.time()
    r = run_cmd(cm, sleeper(tmp_path), ctx = ctx)
    assert r["return"] == 99, r
    assert "the compile deadline of 2 s (--compile_timeout) passed" in r["error"] and "stopped after" in r["error"]
    assert time.time() - started < 20


def test_per_command_timeout_wins_when_shorter(cm, deadlines, tmp_path):
    ctx = {"tasks": {}}
    deadlines.open_deadline(ctx, "compile", 600, "--compile_timeout")
    r = run_cmd(cm, sleeper(tmp_path), ctx = ctx, timeout = 1)
    assert r["return"] == 99 and "timed out after 1 s" in r["error"] and "deadline" not in r["error"], r


def test_a_command_after_the_deadline_is_not_started(cm, deadlines, tmp_path):
    ctx = {"tasks": {}}
    entry = deadlines.open_deadline(ctx, "compile", 1, "--compile_timeout")
    entry["until"] = time.time() - 1                       # already passed
    marker = tmp_path / "ran.txt"
    script = tmp_path / "mark.py"
    script.write_text(f"open(r'{marker}', 'w').write('x')\n")
    r = run_cmd(cm, f'{PY} "{script}"', ctx = ctx)
    assert r["return"] == 99 and "was not started" in r["error"] and "the compile deadline of 1 s" in r["error"], r
    assert not marker.exists()


def test_nested_commands_share_the_deadline_and_it_closes(cm, deadlines, tmp_path):
    """Two commands in one phase: the second gets only the time left; after the phase, none."""
    warm_up(cm)
    ctx = {"tasks": {}}
    entry = deadlines.open_deadline(ctx, "compile", 3, "--compile_timeout")
    r1 = run_cmd(cm, f'{PY} -c "import time; time.sleep(1.2)"', ctx = ctx)
    assert r1["return"] == 0, r1
    started = time.time()
    r2 = run_cmd(cm, sleeper(tmp_path), ctx = ctx)          # a "nested" build: the same ctx
    assert r2["return"] == 99 and "deadline" in r2["error"], r2
    assert time.time() - started < 10                         # stopped by the time left, about 2 s
    deadlines.close_deadline(ctx, entry)
    r3 = run_cmd(cm, f'{PY} -c "import time; time.sleep(0.1); print(7)"', ctx = ctx, capture_output = True)
    assert r3["return"] == 0 and r3["stdout"].strip() == "7" and not r3.get("timed_out")


def test_compile_and_run_program_opens_and_closes_the_deadline():
    """The deadline is opened before the compile pipeline, closed in a finally before the state is
    saved, and never written to the repro file."""
    src = (REPO_ROOT / "task" / "compile-and-run-program" / "api_v1.py").read_text(encoding = "utf-8")
    i_open = src.index("deadlines.open_deadline(ctx, 'compile', params.get('compile_timeout'), '--compile_timeout')")
    i_access = src.index("r = self.cm.access(p)", i_open)
    i_close = src.index("deadlines.close_deadline(ctx, compile_deadline)", i_access)
    i_save = src.index("write_file(path_repro_compile", i_close)
    assert i_open < i_access < i_close < i_save
    assert "finally:" in src[i_access:i_close]
    template = (REPO_ROOT / "program" / "template-c-cpu" / "_desc.yaml").read_text(encoding = "utf-8")
    assert "timeout: '{{params.compile_timeout|$None}}'" in template     # the per-command limit stays
