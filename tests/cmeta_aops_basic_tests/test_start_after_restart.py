"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The task start-after-restart offline: the words of a cmd.exe line (quotes, a folder at a drive's root), the folder a
registered start names (--workdir), the crontab line and its edits (the other lines kept, one line per server), the
startup task the Task Scheduler is given (S4U, at startup, on battery, no time limit, started in the user's folder),
the supervisor (it moves into --workdir, or stays where it was started when that folder is gone; the server started
there; a stop file ends it), the ssh host found by "cx host whoami", the status of a registered start and the checks
of the command line. Nothing here registers a task, edits a real crontab or starts a server.
"""

import json
import os
import sys

import pytest


class StubCM:
    """The few things of the engine the task asks for: its home, its errors, "cx host whoami" and the _desc of the
    host artifact it names ("cx host show")."""

    def __init__(self, home, whoami=None, desc=None):
        self.home_path = home                   # a pathlib.Path, as the engine's (a str() of it where text is needed)
        self.whoami = whoami or {'return': 0, 'host': ''}
        self.desc = desc or {}
        self.calls = []

    def error(self, text):
        return {'return': 1, 'error': text}

    def access(self, params):
        self.calls.append(params)
        if params.get('command') == 'whoami':
            return self.whoami
        if params.get('command') == 'show':
            return {'return': 0, 'host': {'alias': self.whoami.get('host'), 'desc': self.desc, 'state': {}}}
        return {'return': 0}


# a machine whose host artifact declares a server for the task to keep, beside one that it starts another way
DECLARED = {'projects': {'gateway': {'server': {'url': 'http://127.0.0.1:8401/health',
                                                 'run': 'cxt run-some-server --port=8401 --foreground'}},
                         'site': {'server': {'url': 'http://127.0.0.1:8188/', 'start': 'start-site.sh'}}}}


def declared_task(ns, tmp_path, desc=None, **opts):
    task = make_task(ns, tmp_path, **opts)
    task.cm.whoami = {'return': 0, 'host': 'worker', 'uid': '5a3c9e0b7d214f68', 'by': 'system_id'}
    task.cm.desc = DECLARED if desc is None else desc
    return task


def make_task(ns, tmp_path, **opts):
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = StubCM(tmp_path / 'home')
    task.con = False
    task.folder = str(tmp_path / 'log')
    os.makedirs(task.folder, exist_ok=True)
    task.cmeta = {'uses_categories': {'host': 'host,e4e49c251c814f6d', 'log': 'log,487a7639093a4685',
                                      'config': 'config,cc6bfe174be847ed'}}
    task.opts = {'cserver_host': '127.0.0.1', 'cserver_port': 8004, 'ssh_host': '', 'ssh_port': 2222, 'name': '',
                 'wait': 0, 'delay': 30, 'workdir': str(tmp_path)}
    task.opts.update(opts)
    return task


@pytest.fixture
def ns(task_namespace):
    return task_namespace('start-after-restart')


def test_cmd_quote_keeps_plain_words_and_quotes_the_others(ns):
    q = ns['cmd_quote']
    assert q('-q') == '-q'
    assert q('--wait=600') == '--wait=600'
    assert q('--workdir=D:\\Work') == '"--workdir=D:\\Work"'
    assert q('C:\\Program Files\\x.exe') == '"C:\\Program Files\\x.exe"'
    assert q('a&b') == '"a&b"'
    # a folder at a drive's root: the backslash before the closing quote doubled, or the quote would be part of the word
    assert q('--workdir=D:\\') == '"--workdir=D:\\\\"'


@pytest.mark.skipif(os.name != 'nt', reason='the C runtime split of a command line is a Windows thing')
def test_cmd_quote_words_come_back_whole_from_the_windows_split(ns):
    import ctypes
    from ctypes import wintypes
    split = ctypes.windll.shell32.CommandLineToArgvW
    split.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    split.restype = ctypes.POINTER(wintypes.LPWSTR)
    words = ['python.exe', '--workdir=D:\\', '--workdir=D:\\My Work', 'C:\\Users\\x y\\p.exe', '-q', 'a&b']
    n = ctypes.c_int()
    argv = split(' '.join(ns['cmd_quote'](w) for w in words), ctypes.byref(n))
    assert [argv[i] for i in range(n.value)] == words


def test_workdir_of_reads_the_folder_of_a_registered_start(ns):
    w = ns['workdir_of']
    assert w('/d /c set "X=D:\\h" && "py.exe" -m cmeta task run x run --wait=600 "--workdir=D:\\Work" -q') == 'D:\\Work'
    assert w('... "--workdir=D:\\\\" -q') == 'D:\\'
    assert w("@reboot sleep 30; CMETA_HOME=/h /usr/bin/python3 -m cmeta '--workdir=/home/u/my work' -q") == '/home/u/my work'
    assert w('@reboot sleep 30; /usr/bin/python3 -m cmeta --workdir=/home/u/w -q >> /x.log 2>&1') == '/home/u/w'
    assert w('@reboot sleep 30; /usr/bin/python3 -m cmeta -q') == ''
    assert w('') == ''


def test_the_crontab_line_and_its_edits_keep_the_other_lines(ns, tmp_path, monkeypatch):
    task = make_task(ns, tmp_path, workdir='/home/u/my work', ssh_host='worker,5a3c9e0b7d214f68')
    monkeypatch.setenv('CMETA_HOME', str(task.cm.home_path))
    table = {'text': '# the user\'s own\n0 3 * * * /usr/bin/backup\n'}
    task._cron_read = lambda: (table['text'], '')
    task._cron_write = lambda text: table.update(text=text) or {'return': 0}
    task._cron_daemon = lambda: True

    r = task._cron_enable('cserver')
    assert r['return'] == 0
    line = r['line']
    assert line.startswith('@reboot sleep 30; CMETA_HOME=')
    assert line.endswith('# cmeta start-after-restart cserver')
    assert "'--workdir=/home/u/my work'" in line and '--what=cserver' in line and '-q' in line
    assert '>> ' + os.path.join(task.folder, 'cserver.boot.log') in line.replace("'", '')
    assert table['text'].startswith('# the user\'s own\n0 3 * * * /usr/bin/backup\n')

    # again (another port): still one line for the server, the new one
    task.opts['cserver_port'] = 8005
    task._cron_enable('cserver')
    task._cron_enable('ssh')
    lines = table['text'].splitlines()
    assert len([l for l in lines if l.endswith('# cmeta start-after-restart cserver')]) == 1
    assert '--cserver_port=8005' in next(l for l in lines if l.endswith('start-after-restart cserver'))
    assert ns['workdir_of'](next(l for l in lines if l.endswith('start-after-restart ssh'))) == '/home/u/my work'

    enabled, detail, found = task._cron_has('ssh')
    assert enabled and detail == 'crontab @reboot' and found.endswith('start-after-restart ssh')

    # disable: our line goes, the user's stay - and the other server's
    task._cron_disable('cserver')
    assert table['text'].splitlines() == ['# the user\'s own', '0 3 * * * /usr/bin/backup',
                                          next(l for l in lines if l.endswith('start-after-restart ssh'))]
    task._cron_disable('ssh')
    assert table['text'] == '# the user\'s own\n0 3 * * * /usr/bin/backup\n'


def test_the_last_line_gone_leaves_no_crontab(ns, tmp_path, monkeypatch):
    # a user who had no crontab has none again after the disable (an empty text to _cron_write: crontab -r)
    task = make_task(ns, tmp_path)
    monkeypatch.setenv('CMETA_HOME', str(task.cm.home_path))
    table = {'text': ''}
    writes = []
    task._cron_read = lambda: (table['text'], '')
    task._cron_write = lambda text: writes.append(text) or table.update(text=text) or {'return': 0}
    task._cron_daemon = lambda: True
    task._cron_enable('cserver')
    assert writes[-1].count('\n') == 1 and writes[-1].endswith('# cmeta start-after-restart cserver\n')
    task._cron_disable('cserver')
    assert writes[-1] == ''
    task._cron_disable('cserver')                     # nothing of ours left: no write at all
    assert len(writes) == 2


def test_a_second_set_has_lines_and_names_of_its_own(ns, tmp_path):
    task = make_task(ns, tmp_path, name='test')
    assert task._key('ssh') == 'ssh-test'
    assert task._win_name('cserver') == 'cMeta cserver after restart (test)'
    assert task._paths('ssh')['record'] == os.path.join(task.folder, 'ssh-test.json')


def test_the_home_keeps_the_variable_that_names_it(ns, tmp_path, monkeypatch):
    task = make_task(ns, tmp_path)
    monkeypatch.delenv('CMETA_HOME', raising=False)
    monkeypatch.setenv('CMETA_HOME2', str(task.cm.home_path))
    assert task._home_env() == ('CMETA_HOME2', str(task.cm.home_path))
    monkeypatch.setenv('CMETA_HOME', str(task.cm.home_path))
    assert task._home_env() == ('CMETA_HOME', str(task.cm.home_path))
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'another'))
    assert task._home_env() == ('CMETA_HOME2', str(task.cm.home_path))


def test_the_startup_task_of_the_task_scheduler(ns, tmp_path, monkeypatch):
    task = make_task(ns, tmp_path, workdir='D:\\Work', delay=45)
    monkeypatch.setenv('CMETA_HOME', str(task.cm.home_path))
    monkeypatch.setenv('USERDOMAIN', 'PC')
    monkeypatch.setenv('USERNAME', 'someone')
    scripts = []
    task._powershell = lambda script, admin=False: scripts.append((script, admin)) or {'return': 0}

    r = task._win_enable('cserver')
    assert r['return'] == 0 and r['task'] == '\\cMeta\\cMeta cserver after restart'
    script, admin = scripts[0]
    assert admin is True
    assert "-UserId 'PC\\someone' -LogonType S4U -RunLevel Limited" in script
    assert 'New-ScheduledTaskTrigger -AtStartup' in script and "$trigger.Delay = 'PT45S'" in script
    assert '-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries' in script
    assert '-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew' in script
    assert "-TaskPath '\\cMeta\\'" in script and "-TaskName 'cMeta cserver after restart'" in script
    # started in the user's folder (always there); --workdir on its command line
    assert "-WorkingDirectory " + ns['ps_quote'](os.path.expanduser('~')) in script
    argument = r['command']
    assert argument.startswith('/d /v:off /c set "CMETA_HOME=' + str(task.cm.home_path) + '" && ')
    assert '"--workdir=D:\\Work"' in argument and ns['workdir_of'](argument) == 'D:\\Work'
    assert argument.endswith('>> "' + os.path.join(task.folder, 'cserver.boot.log') + '" 2>&1')


def test_the_supervisor_starts_the_server_in_the_folder_and_stops_on_the_stop_file(ns, tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    started_in = tmp_path / 'started-in'
    started_in.mkdir()
    monkeypatch.chdir(started_in)                      # the supervisor moves; the test's folder comes back after it
    monkeypatch.setattr(os, 'setsid', lambda: None, raising=False)
    task = make_task(ns, tmp_path, workdir=str(work))
    stop = task._paths('cserver')['stop']
    # the server: notes the folder it runs in, then asks the supervisor to stop (no 30 s wait for a restart)
    code = ('import os; open("server-cwd.txt", "w").write(os.getcwd()); open(%r, "w").write("stop")' % stop)
    task._server_words = lambda what: [sys.executable, '-c', code]

    r = task._supervise('cserver')
    assert r == {'return': 0, 'stopped': True}
    assert os.path.realpath((work / 'server-cwd.txt').read_text()) == os.path.realpath(str(work))
    with open(task._paths('cserver')['record'], encoding='utf-8') as f:
        record = json.load(f)
    assert record['cwd'] == str(work) and record['pid'] == os.getpid() and record['child'] > 0
    log = open(task._paths('cserver')['log'], encoding='utf-8').read()
    assert 'in ' + str(work) in log and 'ended (exit code 0)' in log and 'stopped (asked)' in log


def test_a_folder_gone_since_the_enable_leaves_the_servers_where_the_start_was(ns, tmp_path, monkeypatch):
    started_in = tmp_path / 'started-in'
    started_in.mkdir()
    monkeypatch.chdir(started_in)
    monkeypatch.setattr(os, 'setsid', lambda: None, raising=False)
    task = make_task(ns, tmp_path, workdir=str(tmp_path / 'renamed-since'))
    stop = task._paths('ssh')['stop']
    task._server_words = lambda what: [sys.executable, '-c', 'open(%r, "w").write("stop")' % stop]
    task.opts['ssh_port'] = 2222

    # the ssh server waits for Tailscale first: none here, no wait (--wait=0)
    monkeypatch.setitem(ns, 'tailscale_address', lambda: '')
    assert task._supervise('ssh')['stopped'] is True
    with open(task._paths('ssh')['record'], encoding='utf-8') as f:
        assert os.path.realpath(json.load(f)['cwd']) == os.path.realpath(str(started_in))
    log = open(task._paths('ssh')['log'], encoding='utf-8').read()
    assert 'WARNING: the folder ' + str(tmp_path / 'renamed-since') + ' (--workdir) does not exist' in log
    assert 'Tailscale address: none after 0 s - starting anyway' in log


def test_a_second_supervisor_ends_at_once(ns, tmp_path):
    # the record names a live supervisor of this boot (another process, written after it started): a second one -
    # a start during the boot's run, or macOS's cron running the @reboot lines when a crontab changes - ends at once
    import subprocess
    import time
    task = make_task(ns, tmp_path)
    p = task._paths('cserver')
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], stdin=subprocess.DEVNULL)
    try:
        with open(p['record'], 'w', encoding='utf-8') as f:
            json.dump({'pid': other.pid, 'started': time.time(), 'what': 'cserver', 'opts': task.opts, 'child': 0}, f)

        def no_server(what):
            raise AssertionError('a second supervisor must start no server')
        task._server_words = no_server

        r = task._supervise('cserver')
        assert r == {'return': 0, 'already': True, 'supervisor': other.pid}
        with open(p['record'], encoding='utf-8') as f:
            assert json.load(f)['pid'] == other.pid             # the running one's record is kept
        assert not os.path.exists(p['stop'])
        assert 'supervisor %d runs already - this one (%d) ends' % (other.pid, os.getpid()) in open(p['log'], encoding='utf-8').read()
    finally:
        other.kill()
        other.wait()


def test_the_probe_wants_an_answer_not_only_a_connection(ns):
    import socket
    import threading

    def serve(kind):
        srv = socket.socket()
        srv.bind(('127.0.0.1', 0))
        srv.listen(4)
        held = []

        def loop():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                held.append(c)
                if kind == 'http':
                    c.recv(1024)
                    c.sendall(b'HTTP/1.0 401 Unauthorized\r\n\r\n')
                elif kind == 'ssh':
                    c.sendall(b'SSH-2.0-OpenSSH_test\r\n')
                # 'silent': the connection is taken and kept, nothing is said
        threading.Thread(target=loop, daemon=True).start()
        return srv, held

    servers = {k: serve(k) for k in ('http', 'ssh', 'silent')}
    port = {k: s.getsockname()[1] for k, (s, _) in servers.items()}
    gone = socket.socket()
    gone.bind(('127.0.0.1', 0))
    closed_port = gone.getsockname()[1]
    gone.close()
    try:
        probe = ns['probe']
        assert probe('127.0.0.1', port['http'], 'cserver', timeout=3) == 'answers'
        assert probe('127.0.0.1', port['ssh'], 'ssh', timeout=3) == 'answers'
        assert probe('127.0.0.1', port['silent'], 'cserver', timeout=0.5) == 'silent'
        assert probe('127.0.0.1', port['silent'], 'ssh', timeout=0.5) == 'silent'
        assert probe('127.0.0.1', port['http'], 'ssh', timeout=0.5) == 'silent'      # not an ssh server
        assert probe('127.0.0.1', closed_port, 'cserver', timeout=3) == 'closed'
    finally:
        for srv, held in servers.values():
            srv.close()
            for c in held:
                c.close()


def test_processes_this_console_may_not_end_go_to_an_administrator_once(ns, tmp_path, monkeypatch):
    # Windows: the servers of a start without a login are out of reach of a console that is not an administrator's
    # (2026-11-13: such a disable left both running) - one question for an administrator ends them all
    task = make_task(ns, tmp_path)
    calls, killed = [], []
    task._powershell = lambda script, admin=False: calls.append((script, admin)) or {'return': 0}
    monkeypatch.setitem(ns, 'kill_group', lambda pid: killed.append(pid))
    monkeypatch.setitem(ns, 'can_terminate', lambda pid: pid != 222)
    assert task._end_processes([111, 222, None], windows=True) == {'return': 0}
    assert killed == [] and len(calls) == 1 and calls[0][1] is True
    assert 'taskkill /PID 111 /T /F' in calls[0][0] and 'taskkill /PID 222 /T /F' in calls[0][0]

    calls.clear()
    monkeypatch.setitem(ns, 'can_terminate', lambda pid: True)
    task._end_processes([111, 222], windows=True)
    assert calls == [] and killed == [111, 222]                 # no question when this console may end them
    task._end_processes([], windows=True)
    assert calls == []


def test_this_process_may_end_itself(ns):
    assert ns['can_terminate'](os.getpid()) is True
    assert ns['can_terminate'](None) is True


def test_stop_ends_the_servers_together_and_says_when_one_still_runs(ns, tmp_path, monkeypatch, capsys):
    task = make_task(ns, tmp_path)
    task.con = True
    monkeypatch.setattr(ns['time'], 'sleep', lambda seconds: None)
    task._win_query = task._cron_has = lambda what: (False, '', '')
    ended = []
    task._end_processes = lambda pids, windows=None: ended.append(list(pids)) or {'return': 0}
    states = {'cserver': [True, False]}                          # running at the stop, gone at the check

    def running(what):
        seq = states[what]
        return {'pid': 41, 'child': 0}, (seq.pop(0) if len(seq) > 1 else seq[0])
    task._running = running

    r = task._stop_all(['cserver'])
    assert ended == [[41]] and r['cserver'] == {'return': 0, 'stopped': True, 'still_running': False}
    assert os.path.isfile(task._paths('cserver')['stop'])        # its supervisor starts nothing again
    assert 'cserver: stopped (supervisor 41)' in capsys.readouterr().out

    states['cserver'] = [True]                                   # never gone: refused, or the question declined
    r = task._stop_all(['cserver'])
    assert r['cserver'] == {'return': 0, 'stopped': False, 'still_running': True}
    assert 'cserver: NOT stopped - supervisor 41 still runs' in capsys.readouterr().out


def test_disable_leaves_running_servers_running(ns, tmp_path, capsys):
    # the user, 2026-11-13: "sometimes I just want to disable them for the next restart but not stop them"
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = StubCM(tmp_path / 'home')
    task.cmeta = {'uses_categories': {'host': 'host', 'log': 'log', 'config': 'config'}}
    task._folder = lambda: {'return': 0, 'path': str(tmp_path)}
    disabled = []
    task._disable_all = lambda whats: disabled.append(list(whats)) or {'return': 0}

    def no_stop(whats):
        raise AssertionError('disable must stop nothing')
    task._stop_all = no_stop
    task._running = lambda what: ({'pid': 7}, what == 'cserver')

    r = task.run({'control': {'con': True}}, action='disable', what='cserver,ssh')
    assert r == {'return': 0, 'action': 'disable', 'running': ['cserver']} and disabled == [['cserver', 'ssh']]
    assert 'cserver: still running now, as before - cx task run start-after-restart stop --what=cserver ends it' in capsys.readouterr().out
    assert not os.path.exists(os.path.join(str(tmp_path), 'cserver.stop'))


def test_the_ssh_host_comes_from_whoami_unless_given(ns, tmp_path):
    task = make_task(ns, tmp_path)
    task.cm.whoami = {'return': 0, 'host': 'worker', 'uid': '5a3c9e0b7d214f68', 'by': 'system_id'}
    task._find_ssh_host()
    assert task.opts['ssh_host'] == 'worker,5a3c9e0b7d214f68'

    task = make_task(ns, tmp_path, ssh_host='given,1234567890abcdef')
    task._find_ssh_host()
    assert task.opts['ssh_host'] == 'given,1234567890abcdef' and task.cm.calls == []

    task = make_task(ns, tmp_path)
    task.cm.whoami = {'return': 0, 'host': ''}       # a machine with no host artifact: run-openssh's default
    task._find_ssh_host()
    assert task.opts['ssh_host'] == ''


def test_the_status_of_a_registered_start_names_its_folder(ns, tmp_path, capsys):
    task = make_task(ns, tmp_path, cserver_port=1)  # a port nothing answers on
    task.con = True
    command = '/d /c set "CMETA_HOME=D:\\h" && "py.exe" -m cmeta task run x run "--workdir=%s" -q' % tmp_path
    task._win_query = task._cron_has = lambda what: (True, 'registered', command)
    task._running = lambda what: ({}, False)
    out = task._status('cserver')
    assert out['enabled'] and out['workdir'] == str(tmp_path) and not out['running'] and not out['answers']
    assert out['probe'] == 'closed'
    printed = capsys.readouterr().out
    assert 'ENABLED after a restart - registered; starts in ' + str(tmp_path) in printed
    assert 'not started by this task' in printed

    task._win_query = task._cron_has = lambda what: (True, 'registered', command.replace(str(tmp_path), str(tmp_path / 'gone')))
    task._status('cserver')
    assert 'a folder that does NOT exist' in capsys.readouterr().out


def test_the_command_line_is_checked_before_anything_is_done(ns, tmp_path):
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = StubCM(tmp_path)
    ctx = {'control': {'con': False}}
    assert 'unknown action' in task.run(ctx, action='restart')['error']
    assert '--what takes' in task.run(ctx, what='cserver,we/b')['error']
    assert '--what takes' in task.run(ctx, what=' , ')['error']
    assert '--name may have' in task.run(ctx, name='a b')['error']
    assert 'are numbers' in task.run(ctx, cserver_port='eighty')['error']
    r = task.run(ctx, action='enable', workdir=str(tmp_path / 'no-such-folder'))
    assert r['return'] == 1 and 'does not exist' in r['error']
    assert task.cm.calls == []                        # nothing asked of the engine (no log artifact made)

    # a name that is not the task's own is looked for in the host artifact of this machine - and nothing else is done
    task.cmeta = {'uses_categories': {'host': 'host', 'log': 'log', 'config': 'config'}}
    r = task.run(ctx, what='cserver,web')
    assert r['return'] == 1 and '--what=web: not cserver or ssh' in r['error'] and 'cx host whoami' in r['error']
    assert [c['command'] for c in task.cm.calls] == ['whoami']


############################################################
# a server the host artifact of this machine declares (projects: <name>: server: run)

def test_the_words_of_a_declared_command(ns):
    words = ns['command_words']
    py = sys.executable
    # the launchers of cMeta become this Python: a restart has no PATH to find them with
    # ... with -q: no one is there to answer a question (2026-11-19: a llama.cpp start asked one and ended)
    assert words('cxt run-some-server --port=8401 --foreground') == [py, '-m', 'cmeta', 'task', 'run', 'run-some-server',
                                                                       '--port=8401', '--foreground', '-q']
    assert words('cx app run cserver --param.port=8004') == [py, '-m', 'cmeta', 'app', 'run', 'cserver', '--param.port=8004', '-q']
    assert words('cmeta task run x -q') == [py, '-m', 'cmeta', 'task', 'run', 'x', '-q']
    assert words('cxt x --quiet')[-1] == '--quiet' and '-q' not in words('cxt x --quiet')
    assert words('cxt x "--note=two words"')[-2] == '--note=two words'
    # any other command goes to the system's shell as it is written
    other = words('my-server --listen 127.0.0.1:9000 > out.log')
    if os.name == 'nt':
        assert other == 'cmd.exe /d /c my-server --listen 127.0.0.1:9000 > out.log'
        assert words(r'cxt x --dir=D:\Work\a')[-2] == r'--dir=D:\Work\a'        # a Windows path keeps its backslashes
    else:
        assert other == ['/bin/sh', '-c', 'my-server --listen 127.0.0.1:9000 > out.log']


def test_the_address_of_a_url(ns):
    endpoint = ns['url_endpoint']
    assert endpoint('http://127.0.0.1:8401/health') == ('127.0.0.1', 8401)
    assert endpoint('http://100.64.1.2/') == ('100.64.1.2', 80) and endpoint('https://site.example/x') == ('site.example', 443)
    assert endpoint('') == ('', 0) and endpoint(None) == ('', 0)


def test_a_declared_server_is_kept_by_its_own_command(ns, tmp_path, monkeypatch):
    task = declared_task(ns, tmp_path)
    assert task._declared('gateway')['run'] == 'cxt run-some-server --port=8401 --foreground'
    assert task._declared('site') == {} and task._declared('cserver') == {} and task._declared('nothing') == {}
    assert task._server_words('gateway') == [sys.executable, '-m', 'cmeta', 'task', 'run', 'run-some-server',
                                             '--port=8401', '--foreground', '-q']
    assert task._endpoint('gateway') == ('127.0.0.1', 8401, 'cserver')
    assert task._waits_for_tailscale('gateway') is False                 # it listens on this machine only
    assert task._win_name('gateway') == 'cMeta gateway after restart'
    assert os.path.basename(task._paths('gateway')['off']) == 'gateway.off'
    # the host artifact is asked once per run
    assert [c['command'] for c in task.cm.calls] == ['whoami', 'show']
    assert task.cm.calls[1]['arg1'] == 'worker,5a3c9e0b7d214f68'

    # the task's own cserver stays its own unless the artifact declares one under that name
    assert task._server_words('cserver')[:6] == [sys.executable, '-m', 'cmeta', 'app', 'run', 'cserver']
    desc = {'projects': {'cserver': {'server': {'url': 'http://100.64.1.2:8004/',
                                                 'run': 'cx app run cserver --param.host=tailscale --param.port=8004'}}}}
    task = declared_task(ns, tmp_path, desc=desc)
    assert task._server_words('cserver') == [sys.executable, '-m', 'cmeta', 'app', 'run', 'cserver',
                                             '--param.host=tailscale', '--param.port=8004', '-q']
    assert task._endpoint('cserver') == ('100.64.1.2', 8004, 'cserver') and task._waits_for_tailscale('cserver') is True
    # a second set (--name) is of the task's own servers, whatever the artifact declares
    task = declared_task(ns, tmp_path, desc=desc, name='test', cserver_port=8997)
    assert task._declared('cserver') == {} and '--param.port=8997' in task._server_words('cserver')


def test_a_declared_server_starts_in_the_folder_its_declaration_names(ns, tmp_path):
    there = tmp_path / 'there'
    there.mkdir()
    desc = {'projects': {'gateway': {'server': {'url': 'http://127.0.0.1:8401/', 'run': 'cxt x --foreground',
                                                 'workdir': str(there)}}}}
    task = declared_task(ns, tmp_path, desc=desc)
    task.workdir_given = False                              # no --workdir on the command line: the declaration decides
    assert task._workdir('gateway') == str(there) and task._workdir('ssh') == task.opts['workdir']
    # ... and it is read at each start: the registered command line does not keep it
    assert not [w for w in task._run_words('gateway') if w.startswith('--workdir=')]
    assert '--workdir=' + task.opts['workdir'] in task._run_words('ssh')

    task.workdir_given = True                               # --workdir given: that one, kept in the command line
    assert task._workdir('gateway') == task.opts['workdir']
    assert '--workdir=' + task.opts['workdir'] in task._run_words('gateway')


def test_a_name_no_artifact_declares_is_refused_with_the_way_to_declare_it(ns, tmp_path):
    task = declared_task(ns, tmp_path)
    task._folder = lambda: {'return': 0, 'path': str(tmp_path)}
    ctx = {'control': {'con': False}}
    r = task.run(ctx, what='site')                      # declared, but started another way: no "run"
    assert r['return'] == 1 and 'the host artifact of this machine (worker) declares no such server' in r['error']
    assert 'projects: site: server: run:' in r['error']
    r = task.run(ctx, what='gateway', name='second')
    assert r['return'] == 1 and 'a second set' in r['error']


############################################################
# the switch: off keeps the registered start, a restart passes it over

def test_off_and_on_switch_a_registered_start_without_registering_anything(ns, tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, 'winreg', FakeWinreg())        # never the real Run key of the user
    task = make_task(ns, tmp_path)
    task.con = True
    task._win_query = task._cron_has = lambda what: (True, 'registered', '')

    def no_enable(what):
        raise AssertionError('a registered start is switched, never registered again')
    task._win_enable = task._cron_enable = no_enable
    off = task._paths('cserver')['off']

    assert task._off('cserver') == {'return': 0, 'enabled': True, 'on': False, 'login': False} and os.path.isfile(off)
    assert 'cserver: OFF - a restart no longer starts it' in capsys.readouterr().out
    status = task._status('cserver', quick=True)
    assert status['enabled'] is True and status['on'] is False
    assert 'cserver: off (registered)' in capsys.readouterr().out

    assert task._on('cserver') == {'return': 0, 'enabled': True, 'on': True, 'login': False} and not os.path.exists(off)
    assert task._status('cserver', quick=True)['on'] is True
    assert task._on('cserver')['on'] is True            # on again: nothing to do
    assert 'it was on already' in capsys.readouterr().out


def test_on_registers_what_is_not_registered_and_off_has_nothing_to_switch(ns, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'winreg', FakeWinreg())        # never the real Run key of the user
    task = make_task(ns, tmp_path)
    task._win_query = task._cron_has = lambda what: (False, '', '')
    registered = []
    task._win_enable = task._cron_enable = lambda what: registered.append(what) or {'return': 0, 'enabled': True}
    monkeypatch.setitem(ns, 'windows_session', lambda: 1)

    assert task._off('cserver') == {'return': 0, 'enabled': False, 'on': False, 'login': False}
    assert not os.path.exists(task._paths('cserver')['off'])
    r = task._on('cserver')
    assert r['return'] == 0 and r['on'] is True and registered == ['cserver']

    # enable switches on too: a start that was off is a restart's again
    open(task._paths('cserver')['off'], 'w').close()
    assert task._enable('cserver')['on'] is True and not os.path.exists(task._paths('cserver')['off'])


def test_a_restart_passes_over_a_server_that_is_switched_off_and_a_start_asked_for_runs(ns, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, 'setsid', lambda: None, raising=False)
    task = make_task(ns, tmp_path)
    p = task._paths('cserver')
    open(p['off'], 'w').close()

    def no_server(what):
        raise AssertionError('a server that is switched off is not started by a restart')
    task._server_words = no_server
    assert task._supervise('cserver') == {'return': 0, 'off': True}
    assert 'switched off - not started' in open(p['log'], encoding='utf-8').read()
    assert not os.path.exists(p['record'])              # no supervisor is recorded: nothing runs

    # start leaves a note: the same command then runs whatever the switch says, and the note is used once
    open(p['asked'], 'w').close()
    task._server_words = lambda what: [sys.executable, '-c', 'open(%r, "w").write("stop")' % p['stop']]
    assert task._supervise('cserver') == {'return': 0, 'stopped': True}
    assert not os.path.exists(p['asked']) and os.path.isfile(p['off'])

    # a note left before the machine's last boot (a start that never came up) is not this start's
    open(p['asked'], 'w').close()
    monkeypatch.setitem(ns, 'boot_time', lambda: os.path.getmtime(p['off']) + 3600)
    os.remove(p['stop'])
    task._server_words = no_server
    assert task._supervise('cserver') == {'return': 0, 'off': True}


############################################################
# stop: the supervisor ends its server itself

def test_the_supervisor_obeys_a_stop_while_its_server_runs(ns, tmp_path, monkeypatch):
    import threading
    import time
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, 'setsid', lambda: None, raising=False)
    task = make_task(ns, tmp_path)
    p = task._paths('cserver')
    ready = str(tmp_path / 'server-runs')
    # a server that runs until it is ended; it leaves its number so that the test can see it gone
    code = 'import os, time; open(%r, "w").write(str(os.getpid())); time.sleep(120)' % ready
    task._server_words = lambda what: [sys.executable, '-c', code]

    def ask():
        for _ in range(100):
            if os.path.isfile(ready):
                break
            time.sleep(0.1)
        open(p['stop'], 'w').close()
    threading.Thread(target=ask, daemon=True).start()

    started = time.monotonic()
    assert task._supervise('cserver') == {'return': 0, 'stopped': True}
    assert time.monotonic() - started < 60
    log = open(p['log'], encoding='utf-8').read()
    assert 'stop asked: ending the server' in log and 'stopped (asked)' in log
    with open(p['record'], encoding='utf-8') as f:
        record = json.load(f)
    assert record['obeys_stop'] is True and record['window'] is False
    server = int(open(ready).read())
    assert ns['recorded_process_alive'](server, time.time()) is False


def test_stop_waits_for_a_supervisor_that_obeys_and_ends_nothing_itself(ns, tmp_path, monkeypatch):
    task = make_task(ns, tmp_path)
    monkeypatch.setattr(ns['time'], 'sleep', lambda seconds: None)
    task._win_query = task._cron_has = lambda what: (False, '', '')
    ended, groups = [], []
    task._end_processes = lambda pids, windows=None: ended.append(list(pids)) or {'return': 0}
    monkeypatch.setitem(ns, 'end_group', lambda pid: groups.append(pid))
    states = [True, True, False]                            # running at the stop and once more, then gone by itself

    def running(what):
        return {'pid': 41, 'child': 42, 'obeys_stop': True}, (states.pop(0) if len(states) > 1 else states[0])
    task._running = running

    r = task._stop_all(['cserver'])
    assert r['cserver'] == {'return': 0, 'stopped': True, 'still_running': False}
    assert ended == [[]]                                    # no process ended from here: no right over them is needed
    assert groups == [41]                                   # what its server may have left in its group (POSIX)

    # one that does not go in time is ended as before
    states[:] = [True]
    monkeypatch.setitem(ns, 'recorded_process_alive', lambda pid, written, alive=None: False)
    clock = iter(range(0, 10000, 5))
    monkeypatch.setattr(ns['time'], 'monotonic', lambda: next(clock))
    ended.clear()
    r = task._stop_all(['cserver'])
    assert ended == [[41]] and r['cserver']['still_running'] is True


############################################################
# start: by the system, without a window or in one of its own (Windows)

@pytest.mark.skipif(os.name != 'nt', reason='the start by the system is a Windows thing')
def test_a_start_goes_to_the_system_and_leaves_its_note(ns, tmp_path, monkeypatch):
    task = declared_task(ns, tmp_path)
    task.window = False
    monkeypatch.setenv('CMETA_HOME', str(task.cm.home_path))
    monkeypatch.setattr(ns['time'], 'sleep', lambda seconds: None)
    task._win_query = lambda what: (False, '', '')
    task._running = lambda what: ({}, False)
    lines = []
    monkeypatch.setitem(ns, 'start_by_system', lambda line, cwd='', window=False: lines.append((line, cwd, window)) or (4242, ''))
    p = task._paths('gateway')

    r = task._start('gateway')
    line, cwd, window = lines[0]
    assert window is False and cwd == task.opts['workdir'] and r['how'] == 'a process of its own, without a window'
    assert line.startswith('cmd.exe /d /v:off /c set "CMETA_HOME=' + str(task.cm.home_path) + '" && ')
    assert ' run --what=gateway ' in line and line.endswith('>> "' + p['boot_log'] + '" 2>&1')
    assert os.path.isfile(p['asked'])                       # this start is not a restart's: the switch does not apply

    # in a window of its own: a title, the supervisor told so, no log to redirect to
    task.window = True
    task._start('gateway')
    line, cwd, window = lines[1]
    assert window is True and 'title cMeta gateway - closing this window stops it && ' in line
    assert line.endswith(' --window') and '>>' not in line

    # a registered server is started by its scheduled task - unless a window is asked for
    task._win_query = lambda what: (True, 'registered', '')
    scripts = []
    task._powershell = lambda script, admin=False: scripts.append((script, admin)) or {'return': 0}
    task._start('gateway')
    assert len(lines) == 3 and lines[2][2] is True and scripts == []
    task.window = False
    assert task._start('gateway')['how'] == 'the scheduled task'
    assert "Start-ScheduledTask -TaskPath '\\cMeta\\' -TaskName 'cMeta gateway after restart'" in scripts[0][0]
    assert scripts[0][1] is False and len(lines) == 3


@pytest.mark.skipif(os.name != 'nt', reason='the session without a login is a Windows thing')
def test_registering_is_not_tried_where_windows_cannot_ask_for_an_administrator(ns, tmp_path, monkeypatch):
    task = make_task(ns, tmp_path)
    monkeypatch.setitem(ns, 'windows_session', lambda: 0)
    monkeypatch.setitem(ns, 'elevated', lambda: False)

    def no_register(what):
        raise AssertionError('no startup task is registered from the session without a login')
    task._win_enable = no_register
    r = task._enable('cserver')
    assert r['return'] == 1 and 'in the session without a login' in r['error']
    assert 'cx task run start-after-restart enable --what=cserver' in r['error']

    # a start at login is the user's own Run key: no administrator, so it is made from there all the same
    task.at = 'login'
    task._login_enable = lambda what: {'return': 0, 'login': True}
    assert task._enable('cserver') == {'return': 0, 'login': True}


def test_the_quick_status_asks_no_port(ns, tmp_path, monkeypatch):
    task = make_task(ns, tmp_path)
    task._win_query = task._cron_has = lambda what: (False, '', '')

    def no_probe(*args, **kwargs):
        raise AssertionError('the quick status asks no port')
    monkeypatch.setitem(ns, 'probe', no_probe)
    monkeypatch.setitem(ns, 'tailscale_address', no_probe)
    task._login_query = lambda what: ''
    out = task._status('ssh', quick=True)
    assert out == {'return': 0, 'enabled': False, 'on': False, 'login': False, 'detail': '', 'running': False,
                   'supervisor': 0, 'window': False, 'session': None, 'declared': False, 'log': task._paths('ssh')['log']}


############################################################
# at login (Windows): the user's Run key starts the server in a window when the user logs in

class FakeWinreg:
    """The few calls of winreg the task makes, on a dict: no test touches the real Run key of the user."""
    HKEY_CURRENT_USER = 'HKCU'
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    class _Key:
        def __init__(self, reg):
            self.reg = reg

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved=0, access=0):
        assert (root, path) == ('HKCU', 'Software\\Microsoft\\Windows\\CurrentVersion\\Run')
        return self._Key(self)

    CreateKey = OpenKey

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


@pytest.fixture
def fake_winreg(monkeypatch):
    reg = FakeWinreg()
    monkeypatch.setitem(sys.modules, 'winreg', reg)
    return reg


@pytest.fixture(autouse=True)
def no_real_run_key(monkeypatch):
    # every test of this file: the task's winreg is a fake one (a test that looks at it asks for fake_winreg)
    monkeypatch.setitem(sys.modules, 'winreg', FakeWinreg())


@pytest.mark.skipif(os.name != 'nt', reason='the start at login is a Windows thing')
def test_at_login_the_run_key_starts_a_cmd_in_a_window_and_the_boot_start_is_switched_off(ns, tmp_path, monkeypatch, fake_winreg):
    task = make_task(ns, tmp_path)
    task.at = 'login'
    monkeypatch.setenv('CMETA_HOME', str(task.cm.home_path))
    task._win_query = lambda what: (True, 'registered', '')          # the boot start is registered and on
    p = task._paths('cserver')

    r = task._enable('cserver')
    assert r['return'] == 0 and r['login'] is True and r['boot_switched_off'] is True and os.path.isfile(p['off'])
    assert fake_winreg.values == {'cMeta cserver at login': 'cmd.exe /d /v:off /c ""%s""' % p['login']}
    cmd = open(p['login'], encoding='utf-8').read().splitlines()
    assert cmd[0] == '@echo off' and 'setlocal DisableDelayedExpansion' in cmd
    assert 'title cMeta cserver - closing this window stops it' in cmd
    assert 'set "CMETA_HOME=' + str(task.cm.home_path) + '"' in cmd
    run = cmd[-1]
    assert ' run --what=cserver ' in run and run.endswith(' -q --window --at=login')
    assert open(p['login'], 'rb').read().count(b'\r\n') == len(cmd)             # a .cmd with Windows line ends
    status = task._status('cserver', quick=True)
    assert status['login'] is True and status['on'] is False and status['enabled'] is True

    # the boot start back on: the login start goes (one or the other)
    task.at = ''
    r = task._on('cserver')
    assert r['on'] is True and r['login'] is False and fake_winreg.values == {} and not os.path.exists(p['login'])
    assert not os.path.exists(p['off'])

    # off --at=login removes only the login start; off with neither removes both
    task.at = 'login'
    task._on('cserver')
    assert fake_winreg.values and os.path.isfile(p['off'])
    task.at = 'login'
    r = task._off('cserver')
    assert fake_winreg.values == {} and r['login'] is False and os.path.isfile(p['off'])       # the boot start stays off
    task._on('cserver')
    task.at = ''
    r = task._off('cserver')
    assert fake_winreg.values == {} and os.path.isfile(p['off']) and r == {'return': 0, 'enabled': True, 'on': False, 'login': False}


@pytest.mark.skipif(os.name != 'nt', reason='the start at login is a Windows thing')
def test_a_login_start_is_never_switched_off_and_a_percent_is_kept(ns, tmp_path, monkeypatch, fake_winreg):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, 'setsid', lambda: None, raising=False)
    task = make_task(ns, tmp_path, workdir=str(tmp_path / '100%work'))
    os.makedirs(task.opts['workdir'])
    p = task._paths('cserver')
    open(p['off'], 'w').close()                    # the boot start switched off: a login start runs all the same
    task.at = 'login'
    task._server_words = lambda what: [sys.executable, '-c', 'open(%r, "w").write("stop")' % p['stop']]
    assert task._supervise('cserver') == {'return': 0, 'stopped': True}
    # in a .cmd a % starts a variable: the folder keeps its % doubled
    assert '100%%work' in task._login_lines('cserver')[-2]


def test_at_login_is_refused_where_it_is_not_built(ns, tmp_path):
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = StubCM(tmp_path)
    ctx = {'control': {'con': False}}
    assert '--at takes boot' in task.run(ctx, action='enable', at='lunch')['error']
    if os.name != 'nt':
        assert 'a Windows thing' in task.run(ctx, action='enable', at='login')['error']
