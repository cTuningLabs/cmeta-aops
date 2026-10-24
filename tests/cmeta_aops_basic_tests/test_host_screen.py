"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Persistent host shells and commands: flags, POSIX validation, transport and reconnect arguments.
"""

import importlib.util
import pathlib
import shlex
import shutil
import sys
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOST = {'alias': 'remote', 'type': 'ssh', 'desc': {'access': {'shell': 'bash -l'}}, 'state': {}}


def screen_version(screen):
    """(major, minor) of a GNU Screen, or None: any version is tested - Apple's 4.00.03 (macOS's /usr/bin/screen)
    answers -v with exit 1, 4.09 and 5.0 with 0."""
    import re
    import subprocess

    if sys.platform == 'win32' or not screen:
        return None
    try:
        out = subprocess.run([screen, '-v'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=10).stdout.decode(errors='replace')
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'Screen version\s+(\d+)\.(\d+)', out)
    return (int(m.group(1)), int(m.group(2))) if m else None


@pytest.fixture
def host(monkeypatch):
    spec = importlib.util.spec_from_file_location('host_screen_under_test', REPO_ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    c = module.Category.__new__(module.Category)
    c.cm = SimpleNamespace(error=lambda s: {'return': 1, 'error': s}, catch_error=lambda r: r['return'] > 0)
    c._here = lambda h: False
    c._screen_terminal = lambda: True
    c._get_host = lambda ctx, ref: {'return': 0, 'host': HOST}
    c._select = lambda *a, **kw: {'return': 0, 'hosts': [HOST]}
    c._cmd_run = lambda ctx, h, cmd, **kw: {'return': 0, 'cmd': cmd or 'ssh remote', 'transport': kw}
    c._run_local = lambda cmd, **kw: {'returncode': 0}
    return module, c


@pytest.mark.parametrize('value, expected', [(None, ''), (False, ''), ('no', ''), ('off', ''),
                                            (True, 'cx-host'), ('', 'cx-host'), ('yes', 'cx-host'), ('work_2', 'work_2')])
def test_flag_names(host, value, expected):
    module, c = host
    assert module.screen_name(value) == expected


@pytest.mark.parametrize('name', ['../work', '-S', 'two words', 'a;hostname', 'a.b', 'x' * 65])
def test_invalid_names_are_refused_before_a_shell_opens(host, name):
    _, c = host
    r = c.ssh_({'control': {}}, 'remote', screen=name, dry_run=True)
    assert r['return'] == 1 and 'screen name' in r['error']


def test_shell_defaults_and_forwarding_use_the_existing_transport(host):
    _, c = host
    calls = []
    c._cmd_run = lambda ctx, h, cmd, **kw: calls.append((cmd, kw)) or {'return': 0, 'cmd': cmd or 'ssh remote'}
    r = c.ssh_({'control': {}}, 'remote', screen=True, forward='1455', x11=True, dry_run=True)
    assert r['return'] == 0 and '-S cx-host -d -R -t shell bash -l' in r['cmd']
    assert calls[0][1] == {'interactive': True, 'x11': True, 'forwards': ['1455']}
    assert 'screen -S cx-host -Q windows' in r['cmd']

    r = c.ssh_({'control': {}}, 'remote', dry_run=True)
    assert r['cmd'] == 'ssh remote' and calls[-1][0] is None

    r = c.ssh_({'control': {}}, 'remote', screen='', dry_run=True)
    assert '-S cx-host -d -R -t shell bash -l' in r['cmd']


def test_command_and_project_title_remain_single_arguments(host):
    _, c = host
    command = "CMETA_ON=here cx task run run-ai '--project=work::a b' 'it\"s 100% (x)'"
    r = c._screen_command(HOST, command, 'ai-work', 'run-ai work::a b')
    launch = r['cmd'].split('; exec ', 1)[1]
    args = shlex.split(launch)
    assert args[-4:] == ['bash', '-l', '-c', command]
    assert not any(a.startswith('--version') for a in args[:args.index('--')]), 'any Screen: no version is asked for'
    assert args[args.index('-t') + 1] == 'run-ai work::a b'
    assert '-R' in args and '-d' in args


@pytest.mark.parametrize('shell, type_', [('powershell', 'ssh'), ('cmd', 'ssh'), ('none', 'ssh'), ('sh', 'adb')])
def test_unsupported_hosts_fail_without_opening_a_shell(host, shell, type_):
    _, c = host
    h = {'alias': 'unsupported', 'type': type_, 'desc': {'access': {'shell': shell}}}
    assert c._screen_command(h, None, 'work')['return'] == 1


def test_a_screen_command_has_a_terminal_and_preserves_errors(host):
    module, c = host
    seen = []
    c._cmd_run = lambda ctx, h, cmd, **kw: seen.append((cmd, kw)) or {'return': 0, 'cmd': cmd}
    r = c.run_({'control': {}}, 'remote', 'echo hello', screen='work')
    assert r['return'] == 0 and seen[0][1]['interactive'] is True
    assert '-S work -d -R' in seen[0][0]

    c._run_local = lambda *a, **kw: {'returncode': 4}
    assert c.run_({'control': {}}, 'remote', 'false', screen=True)['return'] == 1
    monkey_call = module.subprocess.call
    try:
        module.subprocess.call = lambda *a, **kw: 4
        assert c.ssh_({'control': {}}, 'remote', screen=True)['return'] == 1
        assert c.ssh_({'control': {}}, 'remote')['return'] == 0
    finally:
        module.subprocess.call = monkey_call


def test_a_screen_needs_a_terminal_and_cannot_capture_or_timeout(host):
    _, c = host
    for kwargs in ({'capture': True}, {'timeout': 5}, {'script': 'x'}, {'raw': True}, {'all': True}):
        assert c.run_({'control': {}}, 'remote', 'echo x', screen=True, **kwargs)['return'] == 1
    c._screen_terminal = lambda: False
    assert c.ssh_({'control': {}}, 'remote', screen=True)['return'] == 1
    assert c.ssh_({'control': {}}, 'remote', screen=True, dry_run=True)['return'] == 0
    assert c.run_({'control': {}}, 'remote', 'echo x', screen=True)['return'] == 1


@pytest.mark.skipif(screen_version(shutil.which('screen')) is None, reason='needs POSIX and GNU Screen')
def test_real_screen_survives_disconnect_and_does_not_replay_the_command(host, tmp_path):
    """Own socket directory and PTYs: a lost terminal, reattach, then the task's normal exit - with whatever Screen is
    installed (the window titles are read with -Q where it exists: Screen 4.2+)."""
    import os
    import pty
    import select
    import signal
    import subprocess
    import time

    _, c = host
    # Unix socket paths have a small OS limit; keep the socket folder at the sandbox root.
    sockets = tmp_path.parent / ('scr-' + str(os.getpid()))
    sockets.mkdir(mode=0o700)
    env = dict(os.environ, SCREENDIR=str(sockets), TERM='xterm-256color')
    started, duplicate, stop = (tmp_path / name for name in ('started', 'duplicate', 'stop'))
    screen = shutil.which('screen')
    children = []
    transcript = bytearray()

    def wait_for(condition, fd=None):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            if fd is not None and select.select([fd], [], [], 0.05)[0]:
                try:
                    transcript.extend(os.read(fd, 65536))
                except OSError:
                    pass
            else:
                time.sleep(0.05)
        raise AssertionError('screen lifecycle did not reach the expected state: ' + transcript.decode(errors='replace'))

    def attach(command, title):
        line = c._screen_command(HOST, command, 'test-task', title)['cmd']
        # Exercise the real Screen program; tool setup is covered separately through cx on the fleet host.
        prefix = 'cx tool run screen,05d0264fd24b40f6 --con- -- '
        assert prefix in line
        line = line.replace(prefix, shlex.quote(screen) + ' -c /dev/null ')
        pid, fd = pty.fork()
        if pid == 0:
            os.execve('/bin/sh', ['sh', '-c', line], env)
        children.append((pid, fd))
        return fd

    try:
        command = (f'echo started >> {shlex.quote(str(started))}; '
                   f'while [ ! -f {shlex.quote(str(stop))} ]; do sleep 0.1; done')
        first = attach(command, 'original-project')
        wait_for(started.exists, first)
        os.close(first)                         # terminal disappears; Screen must keep the task
        children[-1] = (children[-1][0], None)

        second = attach('touch ' + shlex.quote(str(duplicate)), 'different-project')

        # The window's title is read with -Q (Screen 4.2+); an older Screen has none, and the files below say the rest
        has_query = screen_version(screen) >= (4, 2)

        def attached_to_original():
            if has_query:
                result = subprocess.run([screen, '-S', 'test-task', '-Q', 'windows'], env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if b'original-project' not in result.stdout:
                    return False
            return any('(Attached)' in p for p in
                       subprocess.run([screen, '-ls'], env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode(errors='replace').splitlines())

        wait_for(attached_to_original, second)
        assert started.read_text().splitlines() == ['started']
        assert not duplicate.exists()

        stop.touch()                           # task finishes normally; its last screen window closes
        wait_for(lambda: not list(sockets.iterdir()), second)
    finally:
        stop.touch()
        for pid, fd in children:
            if fd is not None:
                os.close(fd)
            # Reap only the PTY clients made by this test; the private Screen ends through its stop file.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if os.waitpid(pid, os.WNOHANG)[0]:
                    break
                time.sleep(0.05)
            else:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
