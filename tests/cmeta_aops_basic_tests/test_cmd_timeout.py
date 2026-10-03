"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/cmd with a timeout: a command that runs past it is stopped together with the processes it
started (a process group on Linux and macOS, a Job Object on Windows) and the task fails with
"timed out"; without a timeout nothing changes; any return code but 0 fails (a negative one is a
signal on Linux and macOS). Offline: the commands are small Python scripts.
"""

import os
import sys
import time

import pytest

PY = f'"{sys.executable}"'


def run_cmd(cm, cmd, **extra):
    p = {"category": "task", "command": "run", "arg1": "cmd", "cmd": cmd, "con": False, "quiet": True}
    p.update(extra)
    return cm.access(p)


def script(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return f'{PY} "{path}"'


def test_no_timeout_unchanged(cm):
    r = run_cmd(cm, f'{PY} -c "print(42)"', capture_output = True)
    assert r["return"] == 0, r.get("error")
    assert r["stdout"].strip() == "42" and not r.get("timed_out")
    r = run_cmd(cm, f'{PY} -c "print(42)"', capture_output = True, timeout = 30)
    assert r["return"] == 0 and r["stdout"].strip() == "42" and not r.get("timed_out")


def test_timeout_stops_the_command_and_its_children(cm, tmp_path):
    # The command starts a child that writes a file after 6 s and waits for it
    marker = tmp_path / "child-survived.txt"
    child = tmp_path / "child.py"
    child.write_text(f"import time\ntime.sleep(6)\nopen(r'{marker}', 'w').write('x')\n")
    parent = script(tmp_path, "parent.py", f"import subprocess, sys\nsubprocess.run([sys.executable, r'{child}'])\n")
    started = time.time()
    r = run_cmd(cm, parent, timeout = 2)
    assert r["return"] == 99 and "timed out after 2 s" in r["error"], r
    assert time.time() - started < 6
    time.sleep(6)
    assert not marker.exists(), "the child of the timed-out command was not stopped"


@pytest.mark.parametrize("extra", [{"capture_output": True}, {"save_script": "tmp-cmd-timeout{ext}"},
                                   {"cmds": "two"}])
def test_timeout_in_other_modes(cm, tmp_path, extra):
    sleep = script(tmp_path, "sleep.py", "import time\ntime.sleep(30)\n")
    extra = dict(extra)
    if "save_script" in extra:
        extra["save_script"] = str(tmp_path / extra["save_script"].format(ext = ".bat" if os.name == "nt" else ".sh"))
    cmd = sleep
    if extra.get("cmds") == "two":
        extra["cmds"] = [f'{PY} -c "print(1)"', sleep]    # each command gets the full time
        cmd = ""
    started = time.time()
    r = run_cmd(cm, cmd, timeout = 2, **extra)
    assert r["return"] == 99 and "timed out" in r["error"], r
    assert time.time() - started < 20


def test_timeout_without_failing(cm, tmp_path):
    sleep = script(tmp_path, "sleep.py", "import time\ntime.sleep(30)\n")
    r = run_cmd(cm, sleep, timeout = "1", fail_if_nonzero_return_code = False)
    assert r["return"] == 0 and r["timed_out"] is True and r["returncode"] == -1


def test_nonzero_exit_fails(cm, tmp_path):
    r = run_cmd(cm, script(tmp_path, "exit3.py", "import sys\nsys.exit(3)\n"))
    assert r["return"] == 99 and "return code 3" in r["error"]


@pytest.mark.skipif(os.name == "nt", reason = "signals end processes on Linux and macOS")
def test_a_signal_fails(cm, tmp_path):
    # Killed by SIGKILL: -9 when the shell runs the command itself, 137 when it forks
    r = run_cmd(cm, script(tmp_path, "kill.py", "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n"))
    assert r["return"] == 99, r
