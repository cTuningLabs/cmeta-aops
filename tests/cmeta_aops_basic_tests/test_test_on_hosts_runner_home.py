"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The runner of test-on-hosts runs a round in a throwaway cMeta home (CMETA_HOME). A host whose cx is a wrapper script
exporting a home of its own (the WSL Ubuntu 24.04 host, 2026-10-17) ran the commands in the user's home and its plug
said "already registered": the runner now says so in steps.txt and does not plug the tree into the user's home. An
engine without --print-home (older than 0.35.2) gives no folder, and the tree is plugged as before.
"""

import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / 'task' / 'test-on-hosts' / 'runner.py'


def fake_cx(folder):
    # A cx that answers --print-home with FAKE_HOME and writes its other calls into FAKE_LOG
    folder.mkdir()
    if os.name == 'nt':
        (folder / 'cx.cmd').write_text('@echo off\r\n'
                                       'if "%~1"=="--print-home" (\r\n'
                                       '  echo %FAKE_HOME%\r\n'
                                       '  exit /b 0\r\n'
                                       ')\r\n'
                                       '>>"%FAKE_LOG%" echo %*\r\n'
                                       'exit /b 0\r\n')
    else:
        path = folder / 'cx'
        path.write_text('#!/bin/sh\n'
                        'if [ "$1" = "--print-home" ]; then echo "$FAKE_HOME"; exit 0; fi\n'
                        'echo "$@" >> "$FAKE_LOG"\n')
        path.chmod(0o755)


def run_round(tmp_path, answer):
    fake_cx(tmp_path / 'bin')
    tree = tmp_path / 'tree'
    tree.mkdir()
    root = tmp_path / 'round'
    log = tmp_path / 'calls.log'

    env = dict(os.environ, PATH = str(tmp_path / 'bin') + os.pathsep + os.environ.get('PATH', ''),
               FAKE_HOME = answer(root), FAKE_LOG = str(log))
    subprocess.run([sys.executable, str(RUNNER), str(root), str(tree), 'task run test-python -q'], env = env,
                   stdin = subprocess.DEVNULL, check = True, timeout = 120)

    steps = (root / 'work' / 'steps.txt').read_text().splitlines()
    calls = log.read_text().splitlines() if log.exists() else []
    return steps, calls


def test_a_cx_with_a_home_of_its_own_is_said_and_not_plugged_into(tmp_path):
    own = tmp_path / 'user-home'
    own.mkdir()
    steps, calls = run_round(tmp_path, lambda root: str(own))

    assert steps[0].startswith("home: the host's cx keeps its own home " + str(own))
    assert not [c for c in calls if 'repo plug' in c]
    assert [c for c in calls if 'task run test-python -q' in c] and steps[1].startswith('1: exit 0 in ')


def test_a_cx_that_takes_the_round_home_gets_the_tree_plugged(tmp_path):
    steps, calls = run_round(tmp_path, lambda root: str(root / 'home'))

    assert steps[0].startswith('plug: exit 0 in ') and [c for c in calls if 'repo plug' in c]


def test_an_engine_without_print_home_gets_the_tree_plugged_as_before(tmp_path):
    steps, calls = run_round(tmp_path, lambda root: 'cMeta notice: unknown flag --print-home')

    assert steps[0].startswith('plug: exit 0 in ') and [c for c in calls if 'repo plug' in c]
