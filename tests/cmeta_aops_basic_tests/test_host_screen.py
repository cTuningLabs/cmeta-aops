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
    # the existing windows are asked from the Screen the session runs with, never installed for it
    assert 'cx tool run screen,05d0264fd24b40f6 --con- --skip_install -q -- -S cx-host -Q windows' in r['cmd']

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

    module, c = host
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
        query = module.SCREEN_TOOL + ' --con- --skip_install -q -- '
        prefix = module.SCREEN_TOOL + ' --con- -- '
        assert query in line and prefix in line
        line = line.replace(query, shlex.quote(screen) + ' ').replace(prefix, shlex.quote(screen) + ' -c /dev/null ')
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

        # A reconnect comes after the drop, not in the same instant: Apple's Screen 4.00.03 (before 4.2) hangs a
        # reattach made within about a second of the drop, though it already lists the session as Detached
        # (measured 2026-10-24: 0 and 0.3 s hang, 1 s attaches; Screen 4.09 and 5.0 attach at once)
        def detached():
            return any('(Detached)' in p for p in
                       subprocess.run([screen, '-ls'], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE).stdout.decode(errors='replace').splitlines())

        wait_for(detached)
        if screen_version(screen) < (4, 2):
            time.sleep(1.5)

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


# cx host screens: the listing of any Screen version, and the command around it

LS_4_00 = '''There is a screen on:
\t20370.steps\t(Attached)
1 Socket in /Users/u/screens.
'''
LS_4_09 = '''There are screens on:
\t4242.ai2\t(10/24/26 15:01:02)\t(Attached)
\t4100.ai1\t(10/24/26 14:58:40)\t(Detached)
2 Sockets in /run/screen/S-u.
'''
LS_5_0 = '''There is a screen on:
\t21737.run-ai\t(Multi, attached)
1 Socket in /tmp/uscreens/S-u.
'''


def test_parse_screens_of_every_version(host):
    module, _ = host
    one = module.parse_screens('@@ls\n' + LS_4_00 + '@@windows 20370.steps\n')
    assert one == [{'id': '20370.steps', 'name': 'steps', 'pid': 20370, 'state': 'attached', 'started': '', 'windows': ''}]

    two = module.parse_screens('Welcome to Ubuntu\n@@ls\n' + LS_4_09 + '@@windows 4242.ai2\n0$ run-ai work::a b\n@@windows 4100.ai1\n0* shell\n')
    assert [(s['name'], s['pid'], s['state'], s['started'], s['windows']) for s in two] == [
        ('ai2', 4242, 'attached', '10/24/26 15:01:02', '0$ run-ai work::a b'),
        ('ai1', 4100, 'detached', '10/24/26 14:58:40', '0* shell')]

    assert module.parse_screens('@@ls\n' + LS_5_0)[0]['state'] == 'multi, attached'


@pytest.mark.parametrize('listing', ['No Sockets found in /run/screen/S-u.\n',
                                     'cMeta notice: failed to setup tool "screen"!\n', ''])
def test_no_screen_or_no_session_is_an_empty_list(host, listing):
    module, _ = host
    assert module.parse_screens('@@ls\n' + listing) == []


def test_the_screens_script_installs_nothing_and_reads_windows_only_on_success(host):
    module, _ = host
    script = module.SCREENS_SCRIPT
    assert '--skip_install' in script and 'install' not in script.replace('--skip_install', '')
    assert 'if w=$(scr -S "$s" -Q windows 2>/dev/null); then' in script


def test_screens_command_lists_and_refuses_non_posix_hosts(host, capsys):
    module, c = host
    seen = []
    c._cmd_stdin = lambda ctx, h, script: seen.append(open(script, encoding='utf-8').read()) or {'return': 0, 'cmd': 'ssh remote bash -l -s < x'}
    c._run_local = lambda cmd, **kw: {'returncode': 1, 'stdout': '@@ls\n' + LS_4_09 + '@@windows 4242.ai2\n0$ run-ai work::a b\n'}
    r = c.screens_({'control': {'con': True}}, 'remote')
    assert r['return'] == 0 and [s['name'] for s in r['screens']['remote']] == ['ai2', 'ai1']
    assert seen and seen[0] == module.SCREENS_SCRIPT
    out = capsys.readouterr().out
    assert 'SCREEN' in out and 'ai2' in out and 'run-ai work::a b' in out

    windows_host = {'alias': 'win', 'type': 'ssh', 'desc': {'access': {'shell': 'powershell'}}, 'state': {}}
    c._select = lambda *a, **kw: {'return': 0, 'hosts': [windows_host]}
    r = c.screens_({'control': {}}, 'win')
    assert r['return'] == 1 and 'not a POSIX host' in r['error']
    assert c.screens_({'control': {}})['return'] == 1
