"""
start-after-restart - start a cserver and an ssh server of this machine after every restart, before anyone logs in
(README.md):

  cx task run start-after-restart                                   status: what is enabled here, what runs, its log
  cx task run start-after-restart enable --what=cserver,ssh         ssh: the fleet's key for this machine (cx host whoami)
  cx task run start-after-restart enable --what=cserver             only the cserver
  cx task run start-after-restart disable --what=cserver,ssh        no start after a restart any more (and those running stop)
  cx task run start-after-restart start|stop --what=cserver,ssh     now, as a restart would start it (and stop it)
  cx task run start-after-restart run --what=cserver                what a restart runs (waits for Tailscale, keeps it up)
  --workdir=<folder>                                                the folder the servers start in (default: the user's)

Windows: a task of the Task Scheduler per server (folder \\cMeta\\), at startup, as the user who enabled it, with no
login and no stored password (S4U), on battery too, with no time limit; registering and removing one needs an
administrator - enable and disable ask Windows for one (UAC) when this console is not one. Linux and macOS: a line in
the user's crontab, @reboot - cron starts it as the user at the boot. The server runs under a supervisor of this
task (`run`): it waits until the Tailscale address exists, starts the server in the foreground and starts it again
when it ends, until `stop` or `disable`; its log and records in log::local:start-after-restart. The supervisor
starts in the user's folder (always there) and moves into --workdir: a folder gone since the enable is logged and the
servers start in the user's folder - a restart never fails over it.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask, recorded_process_alive

TASK = 'start-after-restart,9bfa8da390e84d16'
LOG_ARTIFACT = 'start-after-restart'
WHAT = ('cserver', 'ssh')
WIN_FOLDER = '\\cMeta\\'
CRON_MARK = '# cmeta start-after-restart '
TAILSCALE_CLI = ['C:\\Program Files\\Tailscale\\tailscale.exe', '/Applications/Tailscale.app/Contents/MacOS/Tailscale',
                 '/opt/homebrew/bin/tailscale', '/usr/local/bin/tailscale', '/usr/bin/tailscale']
RETRY_SECONDS = 30             # a server that ended is started again after this
LOG_KEEP_BYTES = 5_000_000     # a log above this is renamed to <name>.log.old at the next start


def tailscale_cli():
    return shutil.which('tailscale') or next((p for p in TAILSCALE_CLI if os.path.isfile(p)), None)


def tailscale_address():
    """This machine's Tailscale IPv4 address ("tailscale ip -4"), or ''."""
    cli = tailscale_cli()
    if not cli:
        return ''
    try:
        out = subprocess.run([cli, 'ip', '-4'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ''
    return next((l.strip() for l in out.splitlines() if re.fullmatch(r'100\.\d+\.\d+\.\d+', l.strip())), '')


def probe(address, port, what, timeout=5.0):
    """Whether the server answers as such a server does: 'answers' (the cserver's HTTP status line, an ssh server's
    banner), 'silent' (the connection is taken and nothing comes back - a server that hangs, or on macOS a third-party
    Python the system keeps off the network: the kernel takes the connection, the program never gets it), or
    'closed'. A connection alone says too little."""
    import socket
    try:
        s = socket.create_connection((address or '127.0.0.1', int(port)), timeout=timeout)
    except OSError:
        return 'closed'
    try:
        s.settimeout(timeout)
        if what == 'cserver':
            s.sendall(b'GET / HTTP/1.0\r\nHost: start-after-restart\r\n\r\n')
        data = s.recv(16)
        return 'answers' if data.startswith(b'HTTP/' if what == 'cserver' else b'SSH-') else 'silent'
    except OSError:
        return 'silent'
    finally:
        s.close()


def elevated():
    """Whether this process may register a startup task (Windows: an administrator's token)."""
    if os.name != 'nt':
        return os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def kill_group(pid):
    """Ends a process and everything it started (Windows: its tree; POSIX: its process group, then the process)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if pid <= 0:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       stdin=subprocess.DEVNULL)
        return
    import signal
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except OSError:
            try:
                os.kill(pid, sig)
            except OSError:
                return
        time.sleep(2)


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def cmd_quote(word):
    r"""A word of a cmd.exe line for a program that splits its line as the C runtime does (Python): quoted when it has a
    space or a character of cmd's, the backslashes at its end doubled before the closing quote (--workdir=D:\ is
    written "--workdir=D:\\": a single \ before the quote would make the quote a character of the word)."""
    if not re.search(r'[\s!\\&^|<>()]', word):
        return word
    return '"' + re.sub(r'(\\+)$', r'\1\1', word) + '"'


def workdir_of(command):
    """The --workdir a registered start passes: "--workdir=<path>" (Windows), '--workdir=<path>' or bare (cron)."""
    m = re.search(r'''(["'])--workdir=(.*?)\1|--workdir=(\S+)''', command or '')
    if not m:
        return ''
    path = m.group(2) if m.group(1) else m.group(3)
    return path[:-1] if m.group(1) == '"' and path.endswith('\\\\') else path


def windows_session():
    """The Windows session this process runs in (0: a service's - the Task Scheduler's tasks without a login), or None."""
    try:
        import ctypes
        sid = ctypes.c_ulong()
        if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
            return int(sid.value)
    except Exception:
        pass
    return None


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            action: str = 'status',          # status, enable, disable, start, stop, run (what a restart runs)
            what: str = 'cserver',           # cserver, ssh or both: cserver,ssh
            cserver_host: str = 'tailscale', # the address the cserver listens on: tailscale (its address), 127.0.0.1 ...
            cserver_port: int = 8004,        # the cserver's port
            ssh_host: str = '',              # the host artifact this machine is: the key the fleet reaches it with (run-openssh --host); default: cx host whoami
            ssh_port: int = 2222,            # the ssh server's port
            name: str = '',                  # a second set of its own (its own task names, logs and ports): tests
            wait: int = 600,                 # seconds a restart waits for the Tailscale address before it starts anyway
            delay: int = 30,                 # seconds after the boot before the start (the network, Tailscale)
            workdir: str = '',               # the folder the servers start in (their current folder); empty: the user's folder
    ):
        """
        Start a cserver and an ssh server of this machine after every restart, before anyone logs in (see the module
        docstring): status (the default), enable, disable, start, stop, run.
        """
        self.con = ctx['control'].get('con', False)
        action = str(action or 'status').lower()
        if action not in ('status', 'enable', 'disable', 'start', 'stop', 'run'):
            return self.cm.error(f'unknown action "{action}": use status, enable, disable, start, stop or run')
        whats = [w.strip().lower() for w in str(what or 'cserver').split(',') if w.strip()]
        unknown = [w for w in whats if w not in WHAT]
        if unknown or not whats:
            return self.cm.error(f'--what takes cserver, ssh or cserver,ssh (got "{what}")')
        name = str(name or '')
        if name and not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            return self.cm.error('--name may have letters, digits, "_" and "-" only')
        try:
            self.opts = {'cserver_host': str(cserver_host or 'tailscale'), 'cserver_port': int(cserver_port),
                         'ssh_host': str(ssh_host or ''), 'ssh_port': int(ssh_port), 'name': name,
                         'wait': int(wait), 'delay': int(delay)}
        except (TypeError, ValueError):
            return self.cm.error('--cserver_port, --ssh_port, --wait and --delay are numbers')
        # the folder the servers start in: given, or the user's (what cron gives its jobs); a path as the user typed
        # it is kept absolute, for the restart has no current folder of this console
        workdir = str(workdir or '').strip()
        self.opts['workdir'] = os.path.abspath(os.path.expanduser(workdir)) if workdir else os.path.expanduser('~')
        if action in ('enable', 'start') and not os.path.isdir(self.opts['workdir']):
            return self.cm.error(f'--workdir: the folder "{self.opts["workdir"]}" does not exist')

        r = self._folder()
        if r['return'] > 0:
            return r
        self.folder = r['path']

        if action == 'run':
            if len(whats) != 1:
                return self.cm.error('run takes one server: --what=cserver or --what=ssh')
            return self._supervise(whats[0])

        results = {}
        for w in whats:
            r = getattr(self, '_' + action)(w)
            if r['return'] > 0:
                return r
            results[w] = r
        if action == 'status' and self.con:
            self._print_prerequisites(whats)
        return {'return': 0, 'action': action, 'servers': results}

    ############################################################
    # names and places

    def _key(self, what):
        return what + (('-' + self.opts['name']) if self.opts['name'] else '')

    def _win_name(self, what):
        return f'cMeta {what} after restart' + (f' ({self.opts["name"]})' if self.opts['name'] else '')

    def _paths(self, what):
        k = self._key(what)
        f = self.folder
        return {'log': os.path.join(f, k + '.log'), 'boot_log': os.path.join(f, k + '.boot.log'),
                'record': os.path.join(f, k + '.json'), 'stop': os.path.join(f, k + '.stop')}

    def _folder(self):
        """The log artifact (local repository) that keeps the logs and records, made on first use."""
        cat = self.cmeta['uses_categories']['log']
        ref = f'local:{LOG_ARTIFACT}'
        r = self.cm.access({'category': cat, 'command': 'find', 'arg1': ref, 'con': False})
        if r['return'] == 0 and r.get('artifacts'):
            return {'return': 0, 'path': r['artifacts'][0]['path']}
        r = self.cm.access({'category': cat, 'command': 'create', 'arg1': ref, 'yaml': True, 'con': False,
                            'tags': ['start-after-restart', 'cmeta-aops'],
                            'meta': {'desc': 'The logs and records of the task start-after-restart: the servers started '
                                             'after a restart of this machine (<server>.log, <server>.json)'}})
        if r['return'] > 0:
            return r
        return {'return': 0, 'path': r['path']}

    def _home_env(self):
        """The variable that names this home in the enabling process (kept for the restart: cron and the Task Scheduler
        start with almost no environment). The home as text: the engine keeps a pathlib.Path, which shlex.quote refuses."""
        home = str(self.cm.home_path)
        for var in ('CMETA_HOME', 'CMETA_HOME2'):
            if os.environ.get(var) and os.path.normcase(os.path.abspath(os.environ[var])) == os.path.normcase(os.path.abspath(home)):
                return var, home
        return 'CMETA_HOME', home

    def _find_ssh_host(self):
        """The ssh server allows the key the fleet reaches this machine with: the host artifact this machine is, found
        by "cx host whoami" when --ssh_host is not given (none found: run-openssh's own default)."""
        if self.opts['ssh_host']:
            return
        r = self.cm.access({'category': self.cmeta['uses_categories']['host'], 'command': 'whoami', 'con': False})
        if r.get('return') == 0 and r.get('host'):
            self.opts['ssh_host'] = f'{r["host"]},{r["uid"]}' if r.get('uid') else r['host']
            if self.con:
                print(f'ssh: this machine is the host {r["host"]} (cx host whoami) - the fleet\'s key for it is allowed')

    def _run_words(self, what):
        """The command a restart runs: this task's run, by the Python cMeta runs on."""
        o = self.opts
        words = [sys.executable, '-m', 'cmeta', 'task', 'run', TASK, 'run', f'--what={what}',
                 f'--cserver_host={o["cserver_host"]}', f'--cserver_port={o["cserver_port"]}',
                 f'--ssh_port={o["ssh_port"]}', f'--wait={o["wait"]}', f'--workdir={o["workdir"]}', '-q']
        if o['ssh_host']:
            words.append(f'--ssh_host={o["ssh_host"]}')
        if o['name']:
            words.append(f'--name={o["name"]}')
        return words

    def _server_words(self, what):
        """The server itself, in the foreground."""
        o = self.opts
        if what == 'cserver':
            return [sys.executable, '-m', 'cmeta', 'app', 'run', 'cserver', f'--param.host={o["cserver_host"]}',
                    f'--param.port={o["cserver_port"]}', '--param.flags=--no-use-colors']
        words = [sys.executable, '-m', 'cmeta', 'task', 'run', 'run-openssh', f'--port={o["ssh_port"]}', '--foreground']
        if os.name == 'nt' and windows_session() == 0:
            # session 0 (a startup task without a login) has no desktop of its own to give sshd: a hidden desktop
            # fails there (sshd exits with 0xC0000142, its DLLs cannot start) - and no one sees a console in it anyway
            words.append('--hidden_desktop-')
        if o['ssh_host']:
            words.append(f'--host={o["ssh_host"]}')
        if o['name']:
            words.append(f'--name={o["name"]}')
        return words

    ############################################################
    # what a restart runs: the supervisor

    def _log(self, path, text):
        with open(path, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')

    def _supervise(self, what):
        p = self._paths(what)
        # one supervisor per server: a second one ends at once, its record and stop file untouched. A start while the
        # boot's supervisor runs; macOS's cron, which launchd starts on the first change of a crontab after a boot,
        # and which runs the @reboot lines then (2026-11-13: an enable started the cserver a second time)
        rec, running = self._running(what)
        if running and rec.get('pid') != os.getpid():
            self._log(p['log'], f'start-after-restart {what}: supervisor {rec.get("pid")} runs already - '
                                f'this one ({os.getpid()}) ends')
            return {'return': 0, 'already': True, 'supervisor': rec.get('pid')}
        if os.path.isfile(p['log']) and os.path.getsize(p['log']) > LOG_KEEP_BYTES:
            os.replace(p['log'], p['log'] + '.old')
        if os.name != 'nt':
            try:
                os.setsid()                    # a group of its own: stop ends the server and everything it started
            except OSError:
                pass
        if os.path.isfile(p['stop']):
            os.remove(p['stop'])
        # the folder the servers start in: one gone since the enable (renamed, a drive not there) must not keep the
        # machine unreachable - the folder this process was started in instead (the user's), said in the log
        work = self.opts['workdir']
        if not os.path.isdir(work):
            self._log(p['log'], f'WARNING: the folder {work} (--workdir) does not exist: the servers start in {os.getcwd()}')
            work = os.getcwd()
        os.chdir(work)
        record = {'pid': os.getpid(), 'started': time.time(), 'what': what, 'opts': self.opts, 'cwd': work, 'child': 0}
        with open(p['record'], 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=1)
        self._log(p['log'], f'start-after-restart {what}: supervisor {os.getpid()}, home {self.cm.home_path}, '
                            f'python {sys.executable}, in {work}')

        # the Tailscale address first: a server started before it listens on 127.0.0.1 only (or not at all)
        if what == 'ssh' or self.opts['cserver_host'] == 'tailscale':
            deadline = time.monotonic() + max(0, self.opts['wait'])
            address = tailscale_address()
            while not address and time.monotonic() < deadline and not os.path.isfile(p['stop']):
                time.sleep(5)
                address = tailscale_address()
            self._log(p['log'], f'Tailscale address: {address or "none after " + str(self.opts["wait"]) + " s - starting anyway"}')

        while not os.path.isfile(p['stop']):
            words = self._server_words(what)
            self._log(p['log'], 'starting: ' + ' '.join(words))
            with open(p['log'], 'a', encoding='utf-8') as out:
                child = subprocess.Popen(words, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=work)
            record.update(child=child.pid, child_started=time.time())
            with open(p['record'], 'w', encoding='utf-8') as f:
                json.dump(record, f, indent=1)
            code = child.wait()
            self._log(p['log'], f'ended (exit code {code})')
            for _ in range(RETRY_SECONDS):
                if os.path.isfile(p['stop']):
                    break
                time.sleep(1)
        self._log(p['log'], 'stopped (asked)')
        return {'return': 0, 'stopped': True}

    def _running(self, what):
        """(the supervisor's record, whether it is that process still - not a number given to another one since)."""
        p = self._paths(what)
        try:
            with open(p['record'], encoding='utf-8') as f:
                rec = json.load(f)
        except (OSError, ValueError):
            return {}, False
        return rec, recorded_process_alive(rec.get('pid'), rec.get('started', 0))

    ############################################################
    # status, start, stop

    def _status(self, what):
        p = self._paths(what)
        enabled, detail, command = (self._win_query(what) if os.name == 'nt' else self._cron_has(what))
        rec, running = self._running(what)
        # the settings of the running supervisor when there is one (its address and port), else this command line's
        o = dict(self.opts, **(rec.get('opts') or {})) if running else self.opts
        address = tailscale_address() if (what == 'ssh' or o['cserver_host'] == 'tailscale') else o['cserver_host']
        port = o['cserver_port'] if what == 'cserver' else o['ssh_port']
        state = probe(address or '127.0.0.1', port, what)
        answers = state == 'answers'
        workdir = workdir_of(command) if enabled else ''
        tail = ''
        if os.path.isfile(p['log']):
            with open(p['log'], encoding='utf-8', errors='replace') as f:
                tail = ''.join(f.readlines()[-5:])
        out = {'return': 0, 'enabled': enabled, 'detail': detail, 'workdir': workdir, 'running': running,
               'supervisor': rec.get('pid') if running else 0, 'cwd': rec.get('cwd', '') if running else '',
               'address': address, 'port': port, 'answers': answers, 'probe': state, 'log': p['log']}
        if self.con:
            starts = ''
            if workdir:
                starts = f'; starts in {workdir}' + ('' if os.path.isdir(workdir) else
                                                     ' - a folder that does NOT exist: it would start in the user\'s folder')
            print(f'{what}{" (" + self.opts["name"] + ")" if self.opts["name"] else ""}: '
                  f'{"ENABLED after a restart" if enabled else "not enabled after a restart"}'
                  f'{" - " + detail if detail else ""}{starts}')
            now = (f'running (supervisor {rec.get("pid")}{", in " + rec["cwd"] if rec.get("cwd") else ""})' if running
                   else 'not started by this task')
            said = {'answers': 'answers',
                    'silent': 'takes the connection but answers nothing (a server that hangs - or, on macOS, a '
                              'third-party Python the system keeps off the network: Apple\'s own programs answer there)',
                    'closed': 'does not answer'}[state]
            print(f'  now: {now}; {address or "127.0.0.1"}:{port} {said}')
            print(f'  log: {p["log"]}')
            if tail:
                print('  ' + tail.rstrip().replace('\n', '\n  '))
        return out

    def _start(self, what):
        rec, running = self._running(what)
        if running:
            if self.con:
                print(f'{what}: already started by this task (supervisor {rec.get("pid")})')
            return {'return': 0, 'already': True, 'supervisor': rec.get('pid')}
        p = self._paths(what)
        if os.path.isfile(p['stop']):
            os.remove(p['stop'])
        if os.name == 'nt' and self._win_query(what)[0]:
            # the scheduled task itself: the same account, session and environment as after a restart
            r = self._powershell(f'Start-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName {ps_quote(self._win_name(what))}',
                                 admin=False)
            if r['return'] > 0:
                r = self._powershell(f'Start-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName {ps_quote(self._win_name(what))}',
                                     admin=True)
            if r['return'] > 0:
                return r
            how = 'the scheduled task'
        else:
            enabled, _, line = (False, '', '') if os.name == 'nt' else self._cron_has(what)
            m = re.match(r'@reboot\s+(?:sleep\s+\d+;\s*)?(.*)$', line.strip()) if enabled else None
            with open(p['boot_log'], 'a', encoding='utf-8') as out:
                if m:
                    # the crontab's own line, as cron runs it (its settings, its folder, its few variables), without
                    # the wait after a boot: what this command line says (a port, a folder) does not change it
                    env = {k: os.environ[k] for k in ('HOME', 'LOGNAME', 'USER', 'LANG') if k in os.environ}
                    env.update(PATH='/usr/bin:/bin', SHELL='/bin/sh')
                    subprocess.Popen(['/bin/sh', '-c', m.group(1)], stdin=subprocess.DEVNULL, stdout=out,
                                     stderr=subprocess.STDOUT, cwd=os.path.expanduser('~'), env=env, start_new_session=True)
                    how = 'the crontab line'
                else:
                    # not enabled: this command line's settings, in a session of its own, the output in the boot log
                    if what == 'ssh':
                        self._find_ssh_host()
                    var, home = self._home_env()
                    kw = {'creationflags': 0x00000200 | 0x08000000} if os.name == 'nt' else {'start_new_session': True}
                    subprocess.Popen(self._run_words(what), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                     cwd=self.opts['workdir'], env=dict(os.environ, **{var: home}), **kw)
                    how = 'a process of its own'
        for _ in range(20):
            time.sleep(1)
            rec, running = self._running(what)
            if running:
                break
        if self.con:
            print(f'{what}: {"started by " + how + " (supervisor " + str(rec.get("pid")) + ")" if running else "did not start - see " + p["log"] + " and " + p["boot_log"]}')
        return {'return': 0 if running else 1, 'started': running, **({} if running else {'error': f'{what} did not start'})}

    def _stop(self, what):
        p = self._paths(what)
        with open(p['stop'], 'w', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
        rec, running = self._running(what)
        if os.name == 'nt' and self._win_query(what)[0]:
            r = self._powershell(f'Stop-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName {ps_quote(self._win_name(what))}',
                                 admin=False)
            if r['return'] > 0:
                self._powershell(f'Stop-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName {ps_quote(self._win_name(what))}',
                                 admin=True)
        if running:
            child = rec.get('child')
            if child and recorded_process_alive(child, rec.get('child_started', 0)):
                kill_group(child)
            kill_group(rec.get('pid'))
        if what == 'ssh':
            # the server run-openssh started (its own record, its own stop): never an sshd of another run; the port of
            # the running supervisor when there was one
            port = (rec.get('opts') or {}).get('ssh_port', self.opts['ssh_port']) if running else self.opts['ssh_port']
            words = [sys.executable, '-m', 'cmeta', 'task', 'run', 'run-openssh', 'stop', f'--port={port}', '-q']
            if self.opts['name']:
                words.append(f'--name={self.opts["name"]}')
            subprocess.run(words, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.con:
            print(f'{what}: {"stopped (supervisor " + str(rec.get("pid")) + ")" if running else "was not started by this task"}')
        return {'return': 0, 'stopped': running}

    ############################################################
    # enable, disable

    def _enable(self, what):
        o = self.opts
        if what == 'ssh':
            self._find_ssh_host()
        if what == 'ssh' and not o['ssh_host']:
            if self.con:
                print('ssh: no host artifact for this machine (--ssh_host, cx host whoami) - the keys of '
                      '~/.ssh/authorized_keys are allowed (run-openssh\'s default)')
        r = self._win_enable(what) if os.name == 'nt' else self._cron_enable(what)
        if r['return'] > 0:
            return r
        if self.con:
            print(f'{what}: ENABLED - it starts after every restart of this machine, before anyone logs in '
                  f'({"the Task Scheduler" if os.name == "nt" else "crontab @reboot"}); now: '
                  f'cx task run start-after-restart start --what={what}{" --name=" + o["name"] if o["name"] else ""}')
        return r

    def _disable(self, what):
        self._stop(what)
        r = self._win_disable(what) if os.name == 'nt' else self._cron_disable(what)
        if r['return'] > 0:
            return r
        if self.con:
            print(f'{what}: DISABLED - nothing starts it after a restart any more')
        return r

    ############################################################
    # Windows: the Task Scheduler

    def _powershell(self, script, admin=False):
        """Runs a PowerShell script (an administrator's when admin and this process is not one: Windows asks - UAC);
        its last line of output is JSON when the script writes one."""
        path = os.path.join(self.folder, 'last-powershell.ps1')
        result = os.path.join(self.folder, 'last-powershell.json')
        if os.path.isfile(result):
            os.remove(result)
        body = ("$ErrorActionPreference = 'Stop'\n$r = @{ok = $true}\ntry {\n" + script +
                "\n} catch { $r.ok = $false; $r.error = $_.Exception.Message }\n"
                f"$r | ConvertTo-Json -Compress | Set-Content -Encoding utf8 -Path {ps_quote(result)}\n")
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write(body)
        ps = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', path]
        if admin and not elevated():
            if self.con:
                print('Windows asks for an administrator (the Task Scheduler\'s startup tasks need one): answer its window')
            ps = ['powershell.exe', '-NoProfile', '-Command',
                  f"Start-Process powershell.exe -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
                  f"{ps_quote('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' + chr(34) + path + chr(34))}"]
        p = subprocess.run(ps, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with open(result, encoding='utf-8-sig') as f:
                r = json.load(f)
        except (OSError, ValueError):
            return self.cm.error('the PowerShell step gave no answer (refused or cancelled?): ' +
                                 (p.stderr or p.stdout).decode('utf-8', 'replace').strip()[-300:])
        if not r.get('ok'):
            return self.cm.error(str(r.get('error') or 'the PowerShell step failed'))
        return {'return': 0, **r}

    def _win_query(self, what):
        """(registered, a line about it, the command line it runs) - read with schtasks, which any user may run (its
        state from the list, the command from the definition: the XML's names do not change with the language)."""
        tn = WIN_FOLDER + self._win_name(what)
        p = subprocess.run(['schtasks', '/Query', '/TN', tn, '/FO', 'LIST', '/V'], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode:
            return False, '', ''
        text = p.stdout.decode('utf-8', 'replace')
        field = lambda key: next((l.split(':', 1)[1].strip() for l in text.splitlines() if l.strip().startswith(key + ':')), '')
        x = subprocess.run(['schtasks', '/Query', '/TN', tn, '/XML'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE).stdout
        xml = x.decode('utf-16') if x[:2] in (b'\xff\xfe', b'\xfe\xff') else x.decode('utf-8', 'replace')
        m = re.search(r'<Arguments>(.*?)</Arguments>', xml, re.S)
        return True, (f'the Task Scheduler\'s "{tn}" ({field("Status")}, last run {field("Last Run Time")}, '
                      f'result {field("Last Result")})'), html.unescape(m.group(1)) if m else ''

    def _win_enable(self, what):
        p = self._paths(what)
        var, home = self._home_env()
        command = ' '.join(cmd_quote(w) for w in self._run_words(what))
        argument = f'/d /v:off /c set "{var}={home}" && {command} >> "{p["boot_log"]}" 2>&1'
        user = (os.environ.get('USERDOMAIN', '') + '\\' if os.environ.get('USERDOMAIN') else '') + os.environ.get('USERNAME', '')
        # started in the user's folder, always there (a missing "Start in" folder would keep the task from starting at
        # all); the supervisor moves into --workdir itself
        script = '\n'.join([
            f"$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument {ps_quote(argument)} "
            f"-WorkingDirectory {ps_quote(os.path.expanduser('~'))}",
            "$trigger = New-ScheduledTaskTrigger -AtStartup",
            f"$trigger.Delay = 'PT{max(0, self.opts['delay'])}S'",
            f"$principal = New-ScheduledTaskPrincipal -UserId {ps_quote(user)} -LogonType S4U -RunLevel Limited",
            "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable "
            "-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew",
            f"Register-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName {ps_quote(self._win_name(what))} -Action $action "
            f"-Trigger $trigger -Principal $principal -Settings $settings -Force "
            f"-Description {ps_quote('cMeta start-after-restart: ' + what + ' after a restart, without a login (cx task run start-after-restart)')} | Out-Null",
        ])
        r = self._powershell(script, admin=True)
        return r if r['return'] > 0 else {'return': 0, 'enabled': True, 'task': WIN_FOLDER + self._win_name(what), 'command': argument}

    def _win_disable(self, what):
        if not self._win_query(what)[0]:
            return {'return': 0, 'enabled': False}
        script = (f"Unregister-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName {ps_quote(self._win_name(what))} "
                  "-Confirm:$false")
        r = self._powershell(script, admin=True)
        return r if r['return'] > 0 else {'return': 0, 'enabled': False}

    ############################################################
    # Linux, macOS: crontab @reboot

    def _cron_read(self):
        if not shutil.which('crontab'):
            return None, 'no crontab command here (install cron to use start-after-restart)'
        p = subprocess.run(['crontab', '-l'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode:
            return '', ''                   # "no crontab for <user>"
        return p.stdout.decode('utf-8', 'replace'), ''

    def _cron_write(self, text):
        """The user's crontab replaced by text - and none at all when nothing is left (crontab -r), as it was before
        the first enable (an empty crontab is a crontab all the same)."""
        if not text.strip():
            subprocess.run(['crontab', '-r'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return {'return': 0}
        p = subprocess.run(['crontab', '-'], input=text.encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode:
            return self.cm.error('crontab refused the new table: ' + p.stderr.decode('utf-8', 'replace').strip())
        return {'return': 0}

    def _cron_line(self, what):
        p = self._paths(what)
        var, home = self._home_env()
        path = os.pathsep.join([os.path.dirname(sys.executable), '/usr/local/bin', '/opt/homebrew/bin', '/usr/bin',
                                '/bin', '/usr/sbin', '/sbin'])
        command = ' '.join(shlex.quote(w) for w in self._run_words(what))
        return (f'@reboot sleep {max(0, self.opts["delay"])}; {var}={shlex.quote(home)} PATH={shlex.quote(path)} '
                f'{command} >> {shlex.quote(p["boot_log"])} 2>&1 {CRON_MARK}{self._key(what)}')

    def _cron_has(self, what):
        """(enabled, a line about it, the crontab line)."""
        text, error = self._cron_read()
        if text is None:
            return False, error, ''
        line = next((l for l in text.splitlines() if l.rstrip().endswith(CRON_MARK + self._key(what))), '')
        return bool(line), ('crontab @reboot' + ('' if self._cron_daemon() else ' - but no cron daemon runs here') if line else ''), line

    def _cron_daemon(self):
        for name in ('cron', 'crond'):
            if subprocess.run(['pgrep', '-x', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                return True
        return sys.platform == 'darwin'          # launchd starts cron on demand

    def _cron_enable(self, what):
        text, error = self._cron_read()
        if text is None:
            return self.cm.error(error)
        lines = [l for l in text.splitlines() if not l.rstrip().endswith(CRON_MARK + self._key(what))]
        line = self._cron_line(what)
        r = self._cron_write('\n'.join(lines + [line]) + '\n')
        if r['return'] > 0:
            return r
        if self.con and not self._cron_daemon():
            print('WARNING: no cron daemon runs here - nothing will start it after a restart until cron runs')
        return {'return': 0, 'enabled': True, 'line': line}

    def _cron_disable(self, what):
        text, error = self._cron_read()
        if text is None:
            return {'return': 0, 'enabled': False}
        lines = text.splitlines()
        kept = [l for l in lines if not l.rstrip().endswith(CRON_MARK + self._key(what))]
        if len(kept) != len(lines):
            r = self._cron_write('\n'.join(kept) + ('\n' if kept else ''))
            if r['return'] > 0:
                return r
        return {'return': 0, 'enabled': False}

    ############################################################
    def _print_prerequisites(self, whats):
        """What a start without a login needs here - told, never changed."""
        notes = []
        address = tailscale_address()
        notes.append(f'Tailscale: {"this machine is " + address if address else "no address now (tailscale ip -4)"}')
        if os.name == 'nt':
            cli = tailscale_cli()
            if cli:
                p = subprocess.run([cli, 'debug', 'prefs'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
                try:
                    unattended = json.loads(p.stdout.decode('utf-8', 'replace')).get('ForceDaemon')
                    notes.append('Tailscale runs without a login (unattended)' if unattended else
                                 'Tailscale is NOT unattended: it stops at the logout - "tailscale set --unattended=true"')
                except ValueError:
                    pass
            drive = os.path.splitdrive(self.cm.home_path)[0]
            p = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                                f"try {{ $v = Get-BitLockerVolume -MountPoint '{drive}' -ErrorAction Stop; "
                                "'BitLocker ' + $v.ProtectionStatus + ', auto-unlock ' + $v.AutoUnlockEnabled + ', ' + $v.VolumeType } "
                                "catch { 'unknown (an administrator can read it)' }"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            notes.append(f'the home\'s drive {drive}: ' + p.stdout.decode('utf-8', 'replace').strip())
        if 'cserver' in whats:
            r = self.cm.access({'category': self.cmeta['uses_categories']['config'], 'command': 'read', 'arg1': 'cserver',
                                'con': False})
            cfg = (r.get('config_cmeta') or r.get('meta') or {}) if r.get('return') == 0 else {}
            gate = 'a password' if cfg.get('password_sha256') else 'NO password (anyone on the tailnet gets in)'
            mfa = str(cfg.get('login_mfa') or '').lower() in ('yes', 'true', '1', 'on')
            notes.append(f'the cserver\'s sign-in: {gate}{", a code by mail (login_mfa)" if mfa else ""}')
        print('this machine: ' + '; '.join(notes))
