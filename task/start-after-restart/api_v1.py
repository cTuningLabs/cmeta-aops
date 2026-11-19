"""
start-after-restart - keep the servers of this machine: start them after every restart, before anyone logs in, and
start or stop them now (README.md). A server is the cserver, the ssh server, or any server the host artifact of this
machine declares with its command in the foreground (projects: <name>: server: run):

  cx task run start-after-restart                                   status: what is enabled here, what runs, its log
  cx task run start-after-restart enable --what=cserver,ssh         ssh: the fleet's key for this machine (cx host whoami)
  cx task run start-after-restart enable --what=cserver             only the cserver
  cx task run start-after-restart enable --what=<declared server>   a server of the host artifact (server: run)
  cx task run start-after-restart disable --what=cserver,ssh        no start after a restart any more (those running keep running)
  cx task run start-after-restart off|on --what=cserver             the switch: the registered start kept, a restart passes it over (no administrator)
  cx task run start-after-restart enable --what=cserver --at=login  Windows: started when the user logs in, in a window (no administrator)
  cx task run start-after-restart start|stop --what=cserver,ssh     now, as a restart would start it (and stop it)
  cx task run start-after-restart start --what=cserver --window     ... in a console window of its own (Windows)
  cx task run start-after-restart run --what=cserver                what a restart runs (waits for Tailscale, keeps it up)
  --workdir=<folder>                                                the folder the servers start in (default: the user's)

Windows: a task of the Task Scheduler per server (folder \\cMeta\\), at startup, as the user who enabled it, with no
login and no stored password (S4U), on battery too, with no time limit; registering and removing one needs an
administrator - enable and disable ask Windows for one (UAC) when this console is not one; off and on need none.
At login (Windows, --at=login): a value of the user's Run key and a .cmd beside the logs - the server starts when the
user logs in, in a window of its own, in the user's session (what it opens shows on the desktop); one or the other:
the login start switches the boot start off, and the other way round.
Linux and macOS: a line in the user's crontab, @reboot - cron starts it as the user at the boot. The server runs under
a supervisor of this task (`run`): it waits until the Tailscale address exists, starts the server in the foreground
and starts it again when it ends, until `stop` - which it obeys itself: it ends its server and goes. Its log and
records are in log::local:start-after-restart. The supervisor starts in the user's folder (always there) and moves
into --workdir: a folder gone since the enable is logged and the servers start in the user's folder - a restart never
fails over it.

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
import urllib.parse

from task_c36be4b9314a45e0.api.ctask import InitCTask, boot_time, recorded_process_alive, start_by_system

TASK = 'start-after-restart,9bfa8da390e84d16'
LOG_ARTIFACT = 'start-after-restart'
WHAT = ('cserver', 'ssh')      # the servers the task knows by itself; any other name is one the host artifact declares
ACTIONS = ('status', 'enable', 'disable', 'on', 'off', 'start', 'stop', 'run')
WIN_FOLDER = '\\cMeta\\'
CRON_MARK = '# cmeta start-after-restart '
TAILSCALE_CLI = ['C:\\Program Files\\Tailscale\\tailscale.exe', '/Applications/Tailscale.app/Contents/MacOS/Tailscale',
                 '/opt/homebrew/bin/tailscale', '/usr/local/bin/tailscale', '/usr/bin/tailscale']
RETRY_SECONDS = 30             # a server that ended is started again after this
LOG_KEEP_BYTES = 5_000_000     # a log above this is renamed to <name>.log.old at the next start
STOP_SECONDS = 15              # stop waits this long for a supervisor to end its server and go, before it ends them itself
RUN_KEY = 'Software\\Microsoft\\Windows\\CurrentVersion\\Run'      # HKEY_CURRENT_USER: what starts when this user logs in
ATS = ('boot', 'login')        # when a server starts by itself: at the boot (before any login), or when the user logs in


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


def probe(address, port, what, timeout=5.0, path='/'):
    """Whether the server answers as such a server does: 'answers' (the cserver's HTTP status line, an ssh server's
    banner), 'silent' (the connection is taken and nothing comes back - a server that hangs, or on macOS a third-party
    Python the system keeps off the network: the kernel takes the connection, the program never gets it), or
    'closed'. A connection alone says too little. path: what an HTTP server is asked for (a declared server: the
    path of its own URL, its health check)."""
    import socket
    try:
        s = socket.create_connection((address or '127.0.0.1', int(port)), timeout=timeout)
    except OSError:
        return 'closed'
    try:
        s.settimeout(timeout)
        if what == 'cserver':
            asked = re.sub(r'[^\x21-\x7e]', '', str(path or '/')) or '/'
            s.sendall(b'GET ' + asked.encode('ascii') + b' HTTP/1.0\r\nHost: start-after-restart\r\n\r\n')
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


def end_group(pgid):
    """Ends what is left of a process group whose leader has gone (POSIX: a supervisor that ended its server and
    went - a process of that server's own may remain). The group only, never a process by its number: the leader's
    number may be another program's by now."""
    if os.name == 'nt':
        return
    import signal
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(int(pgid), sig)
        except (OSError, TypeError, ValueError):
            return
        time.sleep(1)


def can_terminate(pid):
    """Whether this process may end that one. On Windows the servers of a start without a login run in a session a
    console that is not an administrator's may not reach: OpenProcess is refused (access denied, error 5). A process
    that is gone needs nothing (True)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if os.name == 'nt':
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x0001, False, pid)           # PROCESS_TERMINATE
        if handle:
            k32.CloseHandle(handle)
            return True
        return k32.GetLastError() != 5
    try:
        os.kill(pid, 0)
    except PermissionError:
        return False
    except OSError:
        pass
    return True


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


def command_words(line):
    """What runs a declared command (server: run) without this console's PATH. One that begins with cx, cxt or cmeta
    is run by the Python cMeta runs on (python -m cmeta ...: a restart has no PATH to find the launchers with), as a
    list of words, with -q; any other command goes to the system's shell as it is written (Windows: one line for
    cmd.exe)."""
    line = str(line or '').strip()
    try:
        words = shlex.split(line, posix=os.name != 'nt')
    except ValueError:
        words = []
    if os.name == 'nt':
        # the quotes around a part of a word are the shell's, not the program's: "--x=a b" and --x="a b" are --x=a b
        words = [re.sub(r'"([^"]*)"|\'([^\']*)\'', lambda m: m.group(1) if m.group(1) is not None else m.group(2), w)
                 for w in words]
    head = os.path.basename(words[0]).lower() if words else ''
    head = head[:-4] if head.endswith('.exe') else head
    # a server kept by this task has no one to answer a question (2026-11-19: a llama.cpp start asked which cached
    # Python to take, and ended): a cMeta command runs with -q, its defaults taken
    quiet = [] if ('-q' in words or '--quiet' in words) else ['-q']
    if head in ('cx', 'cmeta'):
        return [sys.executable, '-m', 'cmeta'] + words[1:] + quiet
    if head == 'cxt':
        return [sys.executable, '-m', 'cmeta', 'task', 'run'] + words[1:] + quiet
    return 'cmd.exe /d /c ' + line if os.name == 'nt' else ['/bin/sh', '-c', line]


def url_endpoint(url):
    """(the host, the port) a server's URL names (http://host:port/...), or ('', 0)."""
    try:
        u = urllib.parse.urlsplit(str(url or ''))
        return u.hostname or '', int(u.port or (443 if u.scheme == 'https' else 80)) if u.hostname else 0
    except ValueError:
        return '', 0


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            action: str = 'status',          # status, enable, disable, on, off, start, stop, run (what a restart runs)
            what: str = 'cserver',           # cserver, ssh, a server the host artifact of this machine declares (server: run), or several: cserver,ssh
            cserver_host: str = 'tailscale', # the address the cserver listens on: tailscale (its address), 127.0.0.1 ...
            cserver_port: int = 8004,        # the cserver's port
            ssh_host: str = '',              # the host artifact this machine is: the key the fleet reaches it with (run-openssh --host); default: cx host whoami
            ssh_port: int = 2222,            # the ssh server's port
            name: str = '',                  # a second set of its own (its own task names, logs and ports): tests
            wait: int = 600,                 # seconds a restart waits for the Tailscale address before it starts anyway
            delay: int = 30,                 # seconds after the boot before the start (the network, Tailscale)
            workdir: str = '',               # the folder the servers start in (their current folder); empty: the user's folder
            window: bool = False,            # start: in a console window of its own, the server's output in it (Windows; closing the window stops it)
            quick: bool = False,             # status: what is registered and what runs only - no port is asked, the machine is not looked at
            at: str = '',                    # enable, on: boot (the default) or login (Windows: when the user logs in, in a window); off, disable: that one only (default: both)
    ):
        """
        Keep the servers of this machine - the cserver, the ssh server, any server its host artifact declares: start
        them after every restart, before anyone logs in, and start or stop them now (see the module docstring):
        status (the default), enable, disable, on, off, start, stop, run.
        """
        self.con = ctx['control'].get('con', False)
        action = str(action or 'status').lower()
        if action not in ACTIONS:
            return self.cm.error(f'unknown action "{action}": use {", ".join(ACTIONS[:-1])} or {ACTIONS[-1]}')
        name = str(name or '')
        if name and not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            return self.cm.error('--name may have letters, digits, "_" and "-" only')
        try:
            self.opts = {'cserver_host': str(cserver_host or 'tailscale'), 'cserver_port': int(cserver_port),
                         'ssh_host': str(ssh_host or ''), 'ssh_port': int(ssh_port), 'name': name,
                         'wait': int(wait), 'delay': int(delay)}
        except (TypeError, ValueError):
            return self.cm.error('--cserver_port, --ssh_port, --wait and --delay are numbers')
        self.window = bool(window)
        self._host = None
        self.at = str(at or '').strip().lower()
        if self.at and self.at not in ATS:
            return self.cm.error(f'--at takes boot (after a restart, before any login) or login (when the user logs in, '
                                 f'in a window) - got "{at}"')
        if self.at == 'login' and os.name != 'nt' and action in ('enable', 'on'):
            return self.cm.error('--at=login (a start when the user logs in, in a window) is a Windows thing here: on '
                                 'Linux and macOS a server starts at the boot (crontab @reboot)')
        if self.at == 'login' and action == 'run':
            # the login start: in the user's session, in the window the .cmd opened
            self.window = True

        # the servers: the two the task knows by itself, or ones the host artifact of this machine declares
        whats = [w.lower() if w.lower() in WHAT else w for w in (x.strip() for x in str(what or 'cserver').split(',')) if w]
        if not whats or [w for w in whats if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', w)]:
            return self.cm.error(f'--what takes cserver, ssh, a server the host artifact of this machine declares, or '
                                 f'several with commas (got "{what}")')
        unknown = [w for w in whats if w not in WHAT and not self._declared(w)]
        if unknown and name:
            return self.cm.error('--name makes a second set of the task\'s own cserver and ssh: not of a declared '
                                 f'server ({",".join(unknown)})')
        if unknown:
            host = self._this_host().get('alias')
            return self.cm.error(
                f'--what={",".join(unknown)}: not cserver or ssh, and ' +
                (f'the host artifact of this machine ({host}) declares no such server - projects: {unknown[0]}: server: '
                 f'run: <its command in the foreground>' if host else
                 'no host artifact is this machine (cx host whoami) to declare such a server'))

        # the folder the servers start in: given, or the user's (what cron gives its jobs); a path as the user typed
        # it is kept absolute, for the restart has no current folder of this console
        workdir = str(workdir or '').strip()
        self.workdir_given = bool(workdir)
        self.opts['workdir'] = os.path.abspath(os.path.expanduser(workdir)) if workdir else os.path.expanduser('~')
        if action in ('enable', 'on', 'start') and not os.path.isdir(self.opts['workdir']):
            return self.cm.error(f'--workdir: the folder "{self.opts["workdir"]}" does not exist')

        r = self._folder()
        if r['return'] > 0:
            return r
        self.folder = r['path']

        if action == 'run':
            if len(whats) != 1:
                return self.cm.error('run takes one server: --what=cserver, --what=ssh or one declared server')
            return self._supervise(whats[0])

        if action == 'disable':
            # the start after a restart only: servers running now keep running (the user, 2026-11-13: "sometimes I
            # just want to disable them for the next restart but not stop them") - stop ends them
            r = self._disable_all(whats) if self.at != 'login' else {'return': 0}
            if r['return'] > 0:
                return r
            if self.at != 'boot':
                for w in whats:
                    self._login_remove(w)
            running = [w for w in whats if self._running(w)[1]]
            if running and self.con:
                print(f'{" and ".join(running)}: still running now, as before - '
                      f'cx task run start-after-restart stop --what={",".join(running)}'
                      f'{" --name=" + self.opts["name"] if self.opts["name"] else ""} ends {"them" if len(running) > 1 else "it"}')
            return {'return': 0, 'action': action, 'running': running}

        if action == 'stop':
            # all the servers at once: on Windows one question for an administrator at most, not one per server
            results = self._stop_all(whats)
            left = [w for w in whats if results[w].get('still_running')]
            if left:
                return self.cm.error(f'{" and ".join(left)} still running: Windows refused to end it, or the question for '
                                     'an administrator was declined - run this again and answer it, or from an '
                                     'administrator\'s console')
            return {'return': 0, 'action': action, 'servers': results}

        results = {}
        for w in whats:
            r = self._status(w, quick=bool(quick)) if action == 'status' else getattr(self, '_' + action)(w)
            if r['return'] > 0:
                return r
            results[w] = r
        if action == 'status' and self.con and not quick:
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
                'record': os.path.join(f, k + '.json'), 'stop': os.path.join(f, k + '.stop'),
                # the switch (off: a restart passes the registered start over) and the note of a start that was asked for
                'off': os.path.join(f, k + '.off'), 'asked': os.path.join(f, k + '.asked'),
                # what the user's Run key starts at login (a .cmd: a Run value is kept short)
                'login': os.path.join(f, k + '.login.cmd')}

    def _login_name(self, what):
        return f'cMeta {self._key(what)} at login'

    def _this_host(self):
        """The host artifact this machine is (cx host whoami, then its _desc): {'alias', 'uid', 'desc'}, or {} when
        none is. Asked once per run."""
        if getattr(self, '_host', None) is None:
            self._host = {}
            cat = self.cmeta['uses_categories']['host']
            r = self.cm.access({'category': cat, 'command': 'whoami', 'con': False})
            if r.get('return') == 0 and r.get('host'):
                ref = f'{r["host"]},{r["uid"]}' if r.get('uid') else r['host']
                rr = self.cm.access({'category': cat, 'command': 'show', 'arg1': ref, 'con': False})
                desc = (rr.get('host') or {}).get('desc') if rr.get('return') == 0 else None
                self._host = {'alias': r['host'], 'uid': r.get('uid') or '', 'desc': desc if isinstance(desc, dict) else {}}
        return self._host

    def _declared(self, what):
        """A server the host artifact of this machine declares for the task to keep - projects: <what>: server: run:
        <its command in the foreground> - as its server block, or {}. A declaration comes before the task's own
        cserver and ssh of the same name; a second set (--name) is always the task's own."""
        if self.opts.get('name'):
            return {}
        project = ((self._this_host().get('desc') or {}).get('projects') or {}).get(what)
        server = project.get('server') if isinstance(project, dict) else None
        return server if isinstance(server, dict) and str(server.get('run') or '').strip() else {}

    def _workdir(self, what):
        """The folder a server starts in: --workdir when given; else the one its declaration names (server:
        workdir); else the user's folder."""
        declared = str(self._declared(what).get('workdir') or '').strip()
        if declared and not getattr(self, 'workdir_given', True):
            return os.path.abspath(os.path.expanduser(declared))
        return self.opts['workdir']

    def _endpoint(self, what, o=None):
        """(the address, the port, how it answers: 'cserver' = HTTP, 'ssh' = a banner) of a server, by the settings o
        (those of a running supervisor, or this command line's)."""
        o = o or self.opts
        declared = self._declared(what)
        if declared:
            host, port = url_endpoint(declared.get('url'))
            return host or '127.0.0.1', port, 'cserver'
        if what == 'ssh':
            return tailscale_address(), o['ssh_port'], 'ssh'
        return (tailscale_address() if o['cserver_host'] == 'tailscale' else o['cserver_host']), o['cserver_port'], 'cserver'

    def _waits_for_tailscale(self, what):
        """A server that listens on the Tailscale address is started when that address exists."""
        declared = self._declared(what)
        if declared:
            return bool(re.match(r'100\.', url_endpoint(declared.get('url'))[0]) or
                        re.search(r'\btailscale\b', str(declared.get('run'))))
        return what == 'ssh' or self.opts['cserver_host'] == 'tailscale'

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
        if self._workdir(what) != o['workdir']:
            # the folder its declaration names: read again at each start, so that the host artifact decides
            words.remove(f'--workdir={o["workdir"]}')
        if o['ssh_host']:
            words.append(f'--ssh_host={o["ssh_host"]}')
        if o['name']:
            words.append(f'--name={o["name"]}')
        return words

    def _server_words(self, what):
        """The server itself, in the foreground: the command its host artifact declares, else the task's own."""
        o = self.opts
        declared = self._declared(what)
        if declared:
            return command_words(declared['run'])
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
        line = time.strftime('%Y-%m-%d %H:%M:%S ') + text
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        if getattr(self, 'window', False):
            # a start in a window: the supervisor's lines are on its screen too
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                pass

    def _was_asked(self, p):
        """Whether this start was asked for - start leaves a note just before it - and is not a restart's: such a
        start runs whatever the switch says. The note is read once; one written before the machine's last boot (a
        start that never came up) is no one's - what runs first after a boot is the restart's."""
        try:
            written = os.path.getmtime(p['asked'])
            os.remove(p['asked'])
        except OSError:
            return False
        boot = boot_time()
        return not (boot and written < boot - 2)

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
        # the switch: off keeps the registered start and lets a restart pass it over (on and off need no
        # administrator, where registering and removing a startup task do); a start that was asked for runs anyway
        asked = self._was_asked(p)
        if os.path.isfile(p['off']) and not asked and getattr(self, 'at', '') != 'login':
            self._log(p['log'], f'start-after-restart {what}: switched off - not started '
                                f'(cx task run start-after-restart on --what={what})')
            return {'return': 0, 'off': True}
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
        work = self._workdir(what)
        if not os.path.isdir(work):
            self._log(p['log'], f'WARNING: the folder {work} (--workdir) does not exist: the servers start in {os.getcwd()}')
            work = os.getcwd()
        os.chdir(work)
        window = bool(getattr(self, 'window', False))
        # obeys_stop: this supervisor ends its server itself when stop asks (one from before 0.75.1 does not: stop
        # then ends the processes at once, as it always did)
        record = {'pid': os.getpid(), 'started': time.time(), 'what': what, 'opts': self.opts, 'cwd': work, 'child': 0,
                  'obeys_stop': True, 'window': window, 'session': windows_session() if os.name == 'nt' else None}
        with open(p['record'], 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=1)
        self._log(p['log'], f'start-after-restart {what}: supervisor {os.getpid()}, home {self.cm.home_path}, '
                            f'python {sys.executable}, in {work}' + (' - in a window: closing it, or Ctrl-C, stops the server' if window else ''))

        # the Tailscale address first: a server started before it listens on 127.0.0.1 only (or not at all)
        if self._waits_for_tailscale(what):
            deadline = time.monotonic() + max(0, self.opts['wait'])
            address = tailscale_address()
            while not address and time.monotonic() < deadline and not os.path.isfile(p['stop']):
                time.sleep(5)
                address = tailscale_address()
            self._log(p['log'], f'Tailscale address: {address or "none after " + str(self.opts["wait"]) + " s - starting anyway"}')

        child = None
        try:
            while not os.path.isfile(p['stop']):
                words = self._server_words(what)
                self._log(p['log'], 'starting: ' + (words if isinstance(words, str) else ' '.join(words)))
                if window:
                    # the server writes to the window itself (its console), not to the log
                    child = subprocess.Popen(words, stdin=subprocess.DEVNULL, cwd=work)
                else:
                    with open(p['log'], 'a', encoding='utf-8') as out:
                        child = subprocess.Popen(words, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=work)
                record.update(child=child.pid, child_started=time.time())
                with open(p['record'], 'w', encoding='utf-8') as f:
                    json.dump(record, f, indent=1)
                code = self._wait(child, p)
                self._log(p['log'], f'ended (exit code {code})')
                for _ in range(RETRY_SECONDS):
                    if os.path.isfile(p['stop']):
                        break
                    time.sleep(1)
        except KeyboardInterrupt:
            # Ctrl-C in its window: the server got it too; what is left of it ends with the supervisor
            if child is not None and child.poll() is None:
                kill_group(child.pid)
            self._log(p['log'], 'stopped (Ctrl-C)')
            return {'return': 0, 'stopped': True}
        self._log(p['log'], 'stopped (asked)')
        return {'return': 0, 'stopped': True}

    def _wait(self, child, p):
        """Waits for the server to end -> its exit code (None: it did not end). A stop asked for meanwhile is obeyed
        here: the supervisor ends its own server and everything that one started. Whoever asks then needs no right
        over these processes - which a console that is not an administrator's does not have over the session
        without a login (Windows), nor a page served from another session."""
        while True:
            try:
                return child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            if os.path.isfile(p['stop']):
                try:
                    return child.wait(timeout=0.3)         # a server that is ending by itself right now
                except subprocess.TimeoutExpired:
                    pass
                self._log(p['log'], 'stop asked: ending the server')
                kill_group(child.pid)
                try:
                    return child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    return None

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

    def _registered(self, what):
        """(registered to start after a restart, a line about it, the command line it runs)."""
        return self._win_query(what) if os.name == 'nt' else self._cron_has(what)

    def _status(self, what, quick=False):
        p = self._paths(what)
        enabled, detail, command = self._registered(what)
        off = enabled and os.path.isfile(p['off'])
        rec, running = self._running(what)
        login = self._login_query(what)
        out = {'return': 0, 'enabled': enabled, 'on': enabled and not off, 'login': bool(login), 'detail': detail,
               'running': running, 'supervisor': rec.get('pid') if running else 0,
               'window': bool(rec.get('window')) if running else False,
               'session': rec.get('session') if running else None, 'declared': bool(self._declared(what)), 'log': p['log']}
        if quick:
            # what is registered and what runs: no port asked, no log read (the hosts page asks this for every server)
            if self.con:
                print(f'{what}: ' + ('at login' if login else 'on' if out['on'] else 'off (registered)' if enabled else 'not registered') +
                      (f'; running (supervisor {rec.get("pid")})' if running else '; not started by this task'))
            return out

        # the settings of the running supervisor when there is one (its address and port), else this command line's
        o = dict(self.opts, **(rec.get('opts') or {})) if running else self.opts
        address, port, kind = self._endpoint(what, o)
        asked = urllib.parse.urlsplit(str(self._declared(what).get('url') or ''))
        state = probe(address or '127.0.0.1', port, kind,
                      path=(asked.path or '/') + ('?' + asked.query if asked.query else ''))
        answers = state == 'answers'
        workdir = (workdir_of(command) or (self._workdir(what) if self._declared(what).get('workdir') else '')) if enabled else ''
        tail = ''
        if os.path.isfile(p['log']):
            with open(p['log'], encoding='utf-8', errors='replace') as f:
                tail = ''.join(f.readlines()[-5:])
        out.update(workdir=workdir, cwd=rec.get('cwd', '') if running else '', address=address, port=port,
                   answers=answers, probe=state)
        if self.con:
            starts = ''
            if workdir:
                starts = f'; starts in {workdir}' + ('' if os.path.isdir(workdir) else
                                                     ' - a folder that does NOT exist: it would start in the user\'s folder')
            named = f'{what}{" (" + self.opts["name"] + ")" if self.opts["name"] else ""}'
            if off:
                print(f'{named}: registered, but SWITCHED OFF - a restart does not start it '
                      f'(cx task run start-after-restart on --what={what}){" - " + detail if detail else ""}{starts}')
            else:
                print(f'{named}: {"ENABLED after a restart" if enabled else "not enabled after a restart"}'
                      f'{" - " + detail if detail else ""}{starts}')
            where = ''
            if running:
                where = ', in a window' if rec.get('window') else ', in the session without a login' if rec.get('session') == 0 else ''
            now = (f'running (supervisor {rec.get("pid")}{", in " + rec["cwd"] if rec.get("cwd") else ""}{where})' if running
                   else 'not started by this task')
            said = {'answers': 'answers',
                    'silent': 'takes the connection but answers nothing (a server that hangs - or, on macOS, a '
                              'third-party Python the system keeps off the network: Apple\'s own programs answer there)',
                    'closed': 'does not answer'}[state]
            if login:
                print(f'  at login: ON - it starts when {os.environ.get("USERNAME") or "the user"} logs in, in a window '
                      f'(the Run key value "{self._login_name(what)}")')
            print(f'  now: {now}; {address or "127.0.0.1"}:{port} {said}')
            if self._declared(what):
                print(f'  runs: {self._declared(what)["run"]}  (the host artifact {self._this_host().get("alias")})')
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
        window = bool(getattr(self, 'window', False))
        if window and os.name != 'nt':
            if self.con:
                print(f'cMeta warning: --window is for Windows - {what} starts as usual; its output: tail -f {p["log"]}')
            window = False
        # the note of a start that was asked for: the supervisor reads it, and runs whatever the switch says
        with open(p['asked'], 'w', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S'))

        # the scheduled task runs in the session without a login: only while the boot start is on - a server whose boot
        # start is switched off (its user starts it at login, in a window, to see what it opens) starts in this session
        how = ''
        if os.name == 'nt' and not window and self._win_query(what)[0] and not os.path.isfile(p['off']):
            # the scheduled task itself: the same account, session and environment as after a restart. Where Windows
            # refuses it to this console, an administrator is asked - but not in the session without a login, which
            # has no desktop to ask on: there the server starts as a process of its own, as one not registered does
            script = f'Start-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName {ps_quote(self._win_name(what))}'
            r = self._powershell(script, admin=False)
            if r['return'] > 0 and windows_session() != 0:
                r = self._powershell(script, admin=True)
                if r['return'] > 0:
                    return r
            if r['return'] == 0:
                how = 'the scheduled task'

        if how:
            pass
        elif os.name == 'nt':
            # by the system, as a process of its own: one started as a child would end with a command that is run
            # with a time limit (cx host up --project, the Start of the hosts page) - and it gets the account's own
            # environment, as after a restart, not this console's. Without a window, or in one of its own.
            if what == 'ssh':
                self._find_ssh_host()
            var, home = self._home_env()
            command = ' '.join(cmd_quote(w) for w in self._run_words(what))
            if window:
                line = (f'cmd.exe /d /v:off /c title cMeta {self._key(what)} - closing this window stops it && '
                        f'set "{var}={home}" && {command} --window')
            else:
                line = f'cmd.exe /d /v:off /c set "{var}={home}" && {command} >> "{p["boot_log"]}" 2>&1'
            pid, why = start_by_system(line, cwd=self.opts['workdir'] if os.path.isdir(self.opts['workdir']) else os.path.expanduser('~'),
                                       window=window)
            how = 'a window of its own' if window else 'a process of its own, without a window'
            if not pid:
                # the system could not be asked: the plain way (a command with a time limit ends it when it returns)
                if self.con:
                    print(f'cMeta warning: {why} - started as a process of this command instead')
                with open(p['boot_log'], 'a', encoding='utf-8') as out:
                    subprocess.Popen(self._run_words(what), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                     cwd=self.opts['workdir'], env=dict(os.environ, **{var: home}),
                                     creationflags=0x00000200 | 0x08000000)
                how = 'a process of this command'
        else:
            enabled, _, line = self._cron_has(what)
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
                    subprocess.Popen(self._run_words(what), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                     cwd=self.opts['workdir'], env=dict(os.environ, **{var: home}), start_new_session=True)
                    how = 'a process of its own'
        for _ in range(20):
            time.sleep(1)
            rec, running = self._running(what)
            if running:
                break
        if self.con:
            print(f'{what}: {"started by " + how + " (supervisor " + str(rec.get("pid")) + ")" if running else "did not start - see " + p["log"] + " and " + p["boot_log"]}')
        return {'return': 0 if running else 1, 'started': running, 'how': how,
                **({} if running else {'error': f'{what} did not start - see {p["log"]} and {p["boot_log"]}'})}

    def _end_processes(self, pids, windows=None):
        """Ends processes and everything they started. On Windows the servers of a start without a login run in a
        session that a console which is not an administrator's may not reach (access denied; 2026-11-13: such a
        console could not end them and said nothing): then Windows asks for an
        administrator (UAC), once, and an administrator's PowerShell ends their trees."""
        pids = [int(p) for p in pids if p]
        windows = os.name == 'nt' if windows is None else windows
        if windows and pids and not all(can_terminate(p) for p in pids):
            if self.con:
                print('the servers run in the session without a login, which this console may not reach: '
                      'Windows asks for an administrator to end them')
            return self._powershell('\n'.join(f'& cmd.exe /d /c "taskkill /PID {p} /T /F >nul 2>&1"' for p in pids),
                                    admin=True)
        for p in pids:
            kill_group(p)
        return {'return': 0}

    def _stop_all(self, whats):
        """stop for the servers named: their stop files - a supervisor that obeys them ends its server and goes, so
        that no right over its processes is needed (STOP_SECONDS) -, their startup tasks stopped (the user's own
        right), what still runs ended by this command - on Windows with one question for an administrator at most -
        and a check that they are gone (10 s). {what: {'stopped', 'still_running'}}."""
        found = {}
        for what in whats:
            with open(self._paths(what)['stop'], 'w', encoding='utf-8') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
            found[what] = self._running(what)
            if os.name == 'nt' and self._win_query(what)[0]:
                self._powershell(f'Stop-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName {ps_quote(self._win_name(what))}',
                                 admin=False)

        # the supervisors that obey the stop file: time to end their servers and go
        obeying = [w for w in whats if found[w][1] and found[w][0].get('obeys_stop')]
        deadline = time.monotonic() + STOP_SECONDS
        while obeying and time.monotonic() < deadline:
            time.sleep(0.5)
            obeying = [w for w in obeying if self._running(w)[1]]

        # what still runs (a supervisor that did not go in that time, or one from before it could obey), ended from
        # here; of one that went, what its server may have left behind
        pids, groups = [], []
        for what in whats:
            rec, running = found[what]
            if not running:
                continue
            if rec.get('obeys_stop') and what not in obeying:
                groups.append(rec.get('pid'))
                continue
            child = rec.get('child')
            if child and recorded_process_alive(child, rec.get('child_started', 0)):
                pids.append(child)
            pids.append(rec.get('pid'))
        r = self._end_processes(pids)
        if r['return'] > 0 and self.con:
            print('cMeta warning: ' + str(r.get('error') or 'the servers could not be ended'))
        for pid in groups:
            end_group(pid)

        results = {}
        for what in whats:
            rec, running = found[what]
            if what == 'ssh' and not self._declared(what):
                # the server run-openssh started (its own record, its own stop): never an sshd of another run; the
                # port of the running supervisor when there was one
                port = (rec.get('opts') or {}).get('ssh_port', self.opts['ssh_port']) if running else self.opts['ssh_port']
                words = [sys.executable, '-m', 'cmeta', 'task', 'run', 'run-openssh', 'stop', f'--port={port}', '-q']
                if self.opts['name']:
                    words.append(f'--name={self.opts["name"]}')
                subprocess.run(words, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            still = False
            if running:
                for _ in range(10):
                    if not self._running(what)[1]:
                        break
                    time.sleep(1)
                else:
                    still = True
            if self.con:
                print(f'{what}: ' + ('NOT stopped - supervisor %s still runs' % rec.get('pid') if still else
                                     'stopped (supervisor %s)' % rec.get('pid') if running else
                                     'was not started by this task'))
            results[what] = {'return': 0, 'stopped': running and not still, 'still_running': still}
        return results

    ############################################################
    # enable, disable; the switch: on, off

    def _enable(self, what):
        o = self.opts
        if getattr(self, 'at', '') == 'login':
            # the user's own Run key: no administrator, so also from the session without a login (a page served there)
            return self._login_enable(what)
        if what == 'ssh' and not self._declared(what):
            self._find_ssh_host()
            if not o['ssh_host'] and self.con:
                print('ssh: no host artifact for this machine (--ssh_host, cx host whoami) - the keys of '
                      '~/.ssh/authorized_keys are allowed (run-openssh\'s default)')
        if os.name == 'nt' and not elevated() and windows_session() == 0:
            # the session without a login has no desktop for Windows to ask on: say how, do not wait for an answer
            return self.cm.error(f'registering {what} to start after a restart needs an administrator, and this command '
                                 f'runs in the session without a login, where Windows cannot ask for one: run once, in a '
                                 f'terminal of this machine, "cx task run start-after-restart enable --what={what}"')
        r = self._win_enable(what) if os.name == 'nt' else self._cron_enable(what)
        if r['return'] > 0:
            return r
        off = self._paths(what)['off']
        if os.path.isfile(off):
            os.remove(off)
        gone = self._login_remove(what)
        if self.con:
            print(f'{what}: ENABLED - it starts after every restart of this machine, before anyone logs in '
                  f'({"the Task Scheduler" if os.name == "nt" else "crontab @reboot"}); now: '
                  f'cx task run start-after-restart start --what={what}{" --name=" + o["name"] if o["name"] else ""}' +
                  ('; its start at login is removed (one or the other)' if gone else ''))
        return dict(r, on=True, login=False)

    def _on(self, what):
        """The switch on: a registered start is a restart's again - as it was registered, whatever this command line
        says, and without an administrator. Nothing registered yet: enable, with this command line's settings."""
        if getattr(self, 'at', '') == 'login':
            return self._login_enable(what)
        enabled = self._registered(what)[0]
        if not enabled:
            return self._enable(what)
        off = self._paths(what)['off']
        was_off = os.path.isfile(off)
        if was_off:
            os.remove(off)
        gone = self._login_remove(what)
        if self.con:
            print(f'{what}: ON - it starts after every restart of this machine' + ('' if was_off else ' (it was on already)') +
                  ('; its start at login is removed (one or the other)' if gone else ''))
        return {'return': 0, 'enabled': True, 'on': True, 'login': False}

    def _off(self, what):
        """The switch off: the registered start stays, a restart passes it over. A server that runs keeps running;
        start starts it whatever the switch says. No administrator: disable removes the registration and needs one.
        --at=login: the start at login only; --at=boot: the boot start only; neither: both."""
        at = getattr(self, 'at', '')
        gone = self._login_remove(what) if at != 'boot' else False
        if gone and self.con:
            print(f'{what}: no longer started at login')
        enabled = self._registered(what)[0]
        if at == 'login' or not enabled:
            if self.con and not enabled and not gone:
                print(f'{what}: not enabled after a restart - nothing to switch off')
            return {'return': 0, 'enabled': enabled, 'on': enabled and not os.path.isfile(self._paths(what)['off']),
                    'login': False}
        with open(self._paths(what)['off'], 'w', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
        if self.con:
            print(f'{what}: OFF - a restart no longer starts it; its registered start is kept '
                  f'(on: cx task run start-after-restart on --what={what}; disable removes it)')
        return {'return': 0, 'enabled': True, 'on': False, 'login': False}

    ############################################################
    # at login (Windows): a value of the user's Run key that runs a .cmd beside the logs, in a window of its own

    def _login_query(self, what):
        """The command the user's Run key holds for this server, or '' (none, or not Windows)."""
        if os.name != 'nt':
            return ''
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                value, _ = winreg.QueryValueEx(k, self._login_name(what))
                return str(value or '')
        except OSError:
            return ''

    def _login_lines(self, what):
        """The .cmd the login start runs: in a window titled after the server, this home named, the supervisor told
        it is the login start (its window, no switch to obey)."""
        var, home = self._home_env()
        words = self._run_words(what) + ['--window', '--at=login']
        # in a .cmd a % starts a variable: a path that has one keeps it doubled
        command = ' '.join(cmd_quote(w) for w in words).replace('%', '%%')
        return ['@echo off', 'setlocal DisableDelayedExpansion',
                f'rem cMeta start-after-restart: {what} when {os.environ.get("USERNAME") or "the user"} logs in, in this '
                f'window - "cx task run start-after-restart off --what={what} --at=login" removes it',
                f'title cMeta {self._key(what)} - closing this window stops it',
                f'set "{var}={home.replace("%", "%%")}"', f'cd /d "{os.path.expanduser("~")}"', command, '']

    def _login_enable(self, what):
        """The server starts when the user logs in, in a window: the .cmd written, the Run key's value set (both the
        user's own: no administrator). A boot start that is on is switched off - one or the other."""
        if os.name != 'nt':
            return self.cm.error('--at=login is a Windows thing here: on Linux and macOS a server starts at the boot')
        import winreg
        if what == 'ssh' and not self._declared(what):
            self._find_ssh_host()
        p = self._paths(what)
        with open(p['login'], 'w', encoding='utf-8', newline='\r\n') as f:
            f.write('\n'.join(self._login_lines(what)))
        value = 'cmd.exe /d /v:off /c ""%s""' % p['login']
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, self._login_name(what), 0, winreg.REG_SZ, value)
        switched = False
        if self._registered(what)[0] and not os.path.isfile(p['off']):
            with open(p['off'], 'w', encoding='utf-8') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
            switched = True
        if self.con:
            print(f'{what}: AT LOGIN - it starts when {os.environ.get("USERNAME") or "the user"} logs in, in a window of '
                  f'its own (the Run key value "{self._login_name(what)}" runs {p["login"]})' +
                  ('; its start after a restart is switched off (one or the other)' if switched else ''))
        return {'return': 0, 'login': True, 'on': False, 'enabled': self._registered(what)[0], 'cmd': p['login'],
                'value': value, 'boot_switched_off': switched}

    def _login_remove(self, what):
        """No start at login any more: the Run key's value and the .cmd removed -> whether there was one."""
        if os.name != 'nt':
            return False
        import winreg
        had = False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, self._login_name(what))
                had = True
        except OSError:
            pass
        try:
            os.remove(self._paths(what)['login'])
        except OSError:
            pass
        return had

    def _disable_all(self, whats):
        """No start after a restart any more for the servers named (those running keep running): on Windows their
        startup tasks removed with one question for an administrator at most, elsewhere their crontab lines."""
        if os.name == 'nt':
            names = [self._win_name(w) for w in whats if self._win_query(w)[0]]
            if names:
                r = self._powershell('\n'.join(f'Unregister-ScheduledTask -TaskPath {ps_quote(WIN_FOLDER)} -TaskName '
                                               f'{ps_quote(n)} -Confirm:$false' for n in names), admin=True)
                if r['return'] > 0:
                    return r
        else:
            for w in whats:
                r = self._cron_disable(w)
                if r['return'] > 0:
                    return r
        for w in whats:
            off = self._paths(w)['off']
            if os.path.isfile(off):
                os.remove(off)
            if self.con:
                print(f'{w}: DISABLED - nothing starts it after a restart any more')
        return {'return': 0}

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
