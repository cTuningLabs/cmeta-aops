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
    # the window's shell runs under the prompt hook that takes the display of a later --x11 login (since 2026-10-26)
    assert r['return'] == 0 and '-S cx-host -d -R -t shell env ' in r['cmd'] and r['cmd'].rstrip().endswith('bash -l')
    assert 'PROMPT_COMMAND=[ -f ~/.cmeta-screen-display ] && . ~/.cmeta-screen-display' in r['cmd']
    assert calls[0][1] == {'interactive': True, 'x11': True, 'forwards': ['1455']}
    # the existing windows are asked from the Screen the session runs with, never installed for it
    assert 'cx tool run screen,05d0264fd24b40f6 --con- --skip_install -q --timeout=10 -- -S cx-host -Q windows' in r['cmd']

    r = c.ssh_({'control': {}}, 'remote', dry_run=True)
    assert r['cmd'] == 'ssh remote' and calls[-1][0] is None

    r = c.ssh_({'control': {}}, 'remote', screen='', dry_run=True)
    assert '-S cx-host -d -R -t shell env ' in r['cmd'] and r['cmd'].rstrip().endswith('bash -l')   # the prompt hook, since 2026-10-26


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
    import threading
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
    lock = threading.Lock()
    readers = {}

    # Each client's terminal is read all the time, as a real terminal is: Screen writes the whole screen to a client
    # that (re)attaches, and with that terminal unread it blocks - and so does every -Q query (Screen 4.09 and 5.0)
    def read_terminal(fd, done):
        while not done.is_set():
            try:
                if select.select([fd], [], [], 0.1)[0]:
                    data = os.read(fd, 65536)
                    if not data:
                        return
                    with lock:
                        transcript.extend(data)
            except (OSError, ValueError):
                return

    def drop_terminal(fd):
        """The client's terminal disappears: its reader stops first, so that closing it really hangs the client up."""
        done, thread = readers.pop(fd)
        done.set()
        thread.join(3)
        os.close(fd)

    def wait_for(condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        with lock:
            text = transcript.decode(errors='replace')
        raise AssertionError('screen lifecycle did not reach the expected state; Screen last said: %r; the terminals: %s'
                             % (answers, text))

    answers = {}

    def ask(*args):
        """Screen's answer, or '' when it takes longer than 3 s (the last one of each question kept for a failure)."""
        try:
            r = subprocess.run([screen] + list(args), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=3)
            answers[' '.join(args)] = 'exit %d: %s %s' % (r.returncode, r.stdout.decode(errors='replace'), r.stderr.decode(errors='replace'))
            return r.stdout.decode(errors='replace')
        except subprocess.TimeoutExpired:
            answers[' '.join(args)] = 'no answer in 3 s'
            return ''

    def attach(command, title):
        line = c._screen_command(HOST, command, 'test-task', title)['cmd']
        # Exercise the real Screen program; tool setup is covered separately through cx on the fleet host.
        query = module.SCREEN_TOOL + ' --con- --skip_install -q ' + module.SCREEN_QUERY_TIMEOUT + ' -- '
        prefix = module.SCREEN_TOOL + ' --con- -- '
        assert query in line and prefix in line
        line = line.replace(query, shlex.quote(screen) + ' ').replace(prefix, shlex.quote(screen) + ' -c /dev/null ')
        pid, fd = pty.fork()
        if pid == 0:
            os.execve('/bin/sh', ['sh', '-c', line], env)
        children.append((pid, fd))
        done = threading.Event()
        readers[fd] = (done, threading.Thread(target=read_terminal, args=(fd, done), daemon=True))
        readers[fd][1].start()
        return fd

    try:
        command = (f'echo started >> {shlex.quote(str(started))}; '
                   f'while [ ! -f {shlex.quote(str(stop))} ]; do sleep 0.1; done')
        first = attach(command, 'original-project')
        wait_for(started.exists)
        drop_terminal(first)                    # terminal disappears; Screen must keep the task
        children[-1] = (children[-1][0], None)

        # A reconnect comes after the drop, not in the same instant: Apple's Screen 4.00.03 (before 4.2) hangs a
        # reattach made within about a second of the drop, though it already lists the session as Detached
        # (measured 2026-10-24: 0 and 0.3 s hang, 1 s attaches; Screen 4.09 and 5.0 attach at once)
        wait_for(lambda: '(Detached)' in ask('-ls'))
        if screen_version(screen) < (4, 2):
            time.sleep(1.5)

        second = attach('touch ' + shlex.quote(str(duplicate)), 'different-project')

        # The reattach is seen through -ls alone: a -Q query sent WHILE a client attaches is answered late (Screen
        # 4.09) or never (5.0), and a query killed at its limit left the attach stuck. The real launch asks -Q only
        # before its own attach, when the session is detached - answered at once by every version (4.09 with the
        # list; 5.0 with nothing: it lists the windows of an attached session only)
        wait_for(lambda: '(Attached)' in ask('-ls'))
        assert started.read_text().splitlines() == ['started']
        assert not duplicate.exists()

        # The window keeps its first title (a reattach ignores the new -t): what the "existing windows" line shows
        if screen_version(screen) >= (4, 2):
            time.sleep(0.5)
            titles = ask('-S', 'test-task', '-Q', 'windows')
            if screen_version(screen) < (5, 0) or titles.strip():
                assert 'original-project' in titles and 'different-project' not in titles, answers

        stop.touch()                           # task finishes normally; its last screen window closes
        wait_for(lambda: not list(sockets.iterdir()))
    finally:
        stop.touch()
        for pid, fd in children:
            if fd is not None:
                if fd in readers:
                    drop_terminal(fd)
                else:
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
    assert module.SCREEN_QUERY_TIMEOUT in script, 'a query to a session stuck on a dead terminal is stopped'


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


def test_screens_quit_ends_a_named_session_first(host, capsys):
    """--quit=<name> puts "screen -S <name> -X quit" before the listing, reports whether Screen found it, and refuses a
    bad name before anything runs."""
    module, c = host
    seen = []
    c._cmd_stdin = lambda ctx, h, script: seen.append(open(script, encoding='utf-8').read()) or {'return': 0, 'cmd': 'ssh remote bash -l -s < x'}
    c._run_local = lambda cmd, **kw: {'returncode': 0, 'stdout': '@@quit 0\n@@ls\n' + LS_4_09 + '@@windows 4100.ai1\n0* shell\n'}
    r = c.screens_({'control': {'con': True}}, 'remote', quit='ai2')
    assert r['return'] == 0 and r['ended'] == {'remote': True}
    assert '-S ai2 -X quit' in seen[0] and seen[0].index('-X quit') < seen[0].index('@@ls')
    assert "screen \"ai2\" ended" in capsys.readouterr().out
    c._run_local = lambda cmd, **kw: {'returncode': 0, 'stdout': '@@quit 1\n@@ls\nNo Sockets found in /run/screen/S-u.\n'}
    r = c.screens_({'control': {'con': True}}, 'remote', quit='gone')
    assert r['ended'] == {'remote': False} and 'not found' in capsys.readouterr().out
    assert c.screens_({'control': {}}, 'remote', quit='two words')['return'] == 1
    assert c.screens_({'control': {}}, 'remote', quit='')['return'] == 1
    assert module.screens_script(None) == module.SCREENS_SCRIPT
