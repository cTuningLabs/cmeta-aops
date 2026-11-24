"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of test-on-hosts (2026-11-24), with the real runner and a stand-in for cx:
- a step that runs is ended by the file stop-step - with what it started - and the round goes on with its next
  command; a stop asked before a step started is not for it; while a step runs, work/current.json says which one;
- on Windows the round's home gets its file cache in the round's folder, right after the plug.
"""

import json
import os
import pathlib
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / 'task' / 'test-on-hosts' / 'runner.py'

# what a long step does: a child of its own that writes a file every 0.2 s (so that the test sees it end too)
CHILD = ('import sys, time\n'
         'while True:\n'
         '    open(sys.argv[1], "a").write("x")\n'
         '    time.sleep(0.2)\n')


def fake_cx(folder):
    # a cx that takes the round's home (--print-home) and writes its other calls into FAKE_LOG
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


def start_round(tmp_path, commands):
    fake_cx(tmp_path / 'bin')
    (tmp_path / 'tree').mkdir()
    root = tmp_path / 'round'
    env = dict(os.environ, PATH = str(tmp_path / 'bin') + os.pathsep + os.environ.get('PATH', ''),
               FAKE_HOME = str(root / 'home'), FAKE_LOG = str(tmp_path / 'calls.log'))
    p = subprocess.Popen([sys.executable, str(RUNNER), str(root), str(tmp_path / 'tree')] + list(commands), env = env,
                         stdin = subprocess.DEVNULL)
    return p, root


def wait_for(what, seconds = 60):
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        if what():
            return True
        time.sleep(0.1)
    return False


def test_a_running_step_is_stopped_with_what_it_started_and_the_round_goes_on(tmp_path):
    child = tmp_path / 'child.py'
    child.write_text(CHILD)
    beat = tmp_path / 'beat.txt'
    long_step = '!"%s" "%s" "%s"' % (sys.executable, child, beat)
    p, root = start_round(tmp_path, [long_step, 'task run after -q'])
    try:
        current = root / 'work' / 'current.json'
        assert wait_for(lambda: beat.exists() and current.exists()), 'the long step did not start'
        said = json.loads(current.read_text())
        assert said['step'] == '1' and said['command'] == long_step and said['pid'] > 0

        (root / 'stop-step').write_text('asked\n')                       # what --action=stop-step makes
        assert p.wait(60) == 0                                           # the runner ends: the round went on to its end
    finally:
        if p.poll() is None:
            p.kill()

    steps = (root / 'work' / 'steps.txt').read_text().splitlines()
    assert [s for s in steps if s.startswith('1: stopped in ') and '(asked)' in s], steps
    assert [s for s in steps if s.startswith('2: exit 0 in ') and s.endswith('task run after -q')], steps
    assert (root / 'DONE').exists() and not (root / 'stop-step').exists() and not (root / 'work' / 'current.json').exists()

    # what the step started is gone: its file does not grow any more
    size = beat.stat().st_size
    time.sleep(1.0)
    assert beat.stat().st_size == size


def test_a_stop_asked_before_a_step_started_is_not_for_it(tmp_path):
    fake_cx(tmp_path / 'bin')
    (tmp_path / 'tree').mkdir()
    root = tmp_path / 'round'
    root.mkdir()
    (root / 'stop-step').write_text('asked\n')                           # left from before
    env = dict(os.environ, PATH = str(tmp_path / 'bin') + os.pathsep + os.environ.get('PATH', ''),
               FAKE_HOME = str(root / 'home'), FAKE_LOG = str(tmp_path / 'calls.log'))
    subprocess.run([sys.executable, str(RUNNER), str(root), str(tmp_path / 'tree'), 'task run one -q'], env = env,
                   stdin = subprocess.DEVNULL, check = True, timeout = 120)
    steps = (root / 'work' / 'steps.txt').read_text().splitlines()
    assert [s for s in steps if s.startswith('1: exit 0 in ')] and not [s for s in steps if 'stopped' in s]


def test_on_windows_the_rounds_home_keeps_its_file_cache_in_the_rounds_folder(tmp_path):
    p, root = start_round(tmp_path, ['task run one -q'])
    assert p.wait(120) == 0
    steps = (root / 'work' / 'steps.txt').read_text().splitlines()
    calls = (tmp_path / 'calls.log').read_text().splitlines()
    wanted = '--meta.file_cache=%s' % (root / 'fc')
    if os.name == 'nt':
        assert steps[1].startswith('file-cache: exit 0 in ') and wanted in steps[1]
        assert [c for c in calls if 'config set task' in c and wanted in c]
        assert calls.index(next(c for c in calls if 'repo plug' in c)) < calls.index(next(c for c in calls if 'config set task' in c))
    else:
        assert not [s for s in steps if s.startswith('file-cache')] and not [c for c in calls if 'config set' in c]


def test_stop_step_makes_the_file_where_a_step_runs_and_says_where_none_does(task_namespace, tmp_path):
    ns = task_namespace('test-on-hosts')
    t = ns['CTask'].__new__(ns['CTask'])
    root = tmp_path / 'here'
    (root / 'work').mkdir(parents = True)
    t.here_root_of = lambda local: str(root)

    r = t.stop_step(False, 'r1', str(tmp_path), 'cmeta-tests/test-on-hosts-r1', ['here'])
    assert r['asked']['here'] == {'stopping': False, 'step': None, 'said': ns['NO_STEP']} and not (root / 'stop-step').exists()

    (root / 'work' / 'current.json').write_text(json.dumps({'step': '2', 'pid': 4242, 'command': 'task run x', 'started': 'now'}))
    r = t.stop_step(False, 'r1', str(tmp_path), 'cmeta-tests/test-on-hosts-r1', ['here'])
    assert r['asked']['here']['stopping'] is True and r['asked']['here']['step']['step'] == '2'
    assert (root / 'stop-step').exists()
