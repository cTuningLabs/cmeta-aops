"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-paperclip: a Paperclip server of this user, without upstream's service. The CLI comes from tool/paperclip (the
pinned npm package in the cMeta cache, run with cMeta's Node.js 24.11+).

    cx task run run-paperclip [start|status|stop] [--instance=default] [--port=3100] [--bind=loopback|lan|tailnet]

start: the instance onboarded with Paperclip's quickstart defaults the first time ("paperclipai onboard --yes": an
embedded PostgreSQL, local disk storage, no LLM provider), else run ("paperclipai run": a doctor with repair, then
the server) - in a session of its own, so that it outlives the shell and an ssh connection - and a wait until
/api/health answers. Its environment: PAPERCLIP_HOME (the data root, ~/.local/state/paperclip by default: apart from
the ~/.paperclip of an "npx paperclipai" of the user), PAPERCLIP_INSTANCE_ID, PORT, PAPERCLIP_BIND (an address other
than loopback needs a login: PAPERCLIP_DEPLOYMENT_MODE=authenticated), telemetry off, no browser.

The pure parts (the environment, the command of a start, the health answer) are tested offline.
"""

import json
import os
import platform
import signal
import socket
import subprocess
import time
import urllib.request

from task_c36be4b9314a45e0.api.ctask import InitCTask

SETUP = 'setup,a2f9b61079ce4333'
TOOL = 'paperclip,dbf17b0c34d145cf'
BINDS = ('loopback', 'lan', 'tailnet')


def detect_os():
    """windows, linux or darwin."""
    s = platform.system().lower()
    return 'windows' if s.startswith('win') else ('darwin' if s == 'darwin' else 'linux')


def default_home():
    """The data root: next to the state of other servers of this user (~/.local/state), apart from Paperclip's own ~/.paperclip."""
    state = os.environ.get('XDG_STATE_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'state')
    return os.path.join(state, 'paperclip')


def server_env(base, home, instance, port, bind):
    """The environment of the server: its data root and instance, its port and bind, a login when it is reachable from
    elsewhere, no telemetry, no browser."""
    env = dict(base, PAPERCLIP_HOME = home, PAPERCLIP_INSTANCE_ID = instance, PORT = str(int(port)),
               PAPERCLIP_BIND = bind, PAPERCLIP_TELEMETRY_DISABLED = '1', DO_NOT_TRACK = '1',
               PAPERCLIP_NO_BROWSER = '1', PAPERCLIP_OPEN_ON_LISTEN = 'false')
    if bind != 'loopback':
        env['PAPERCLIP_DEPLOYMENT_MODE'] = 'authenticated'
    return env


def start_args(cli, home, instance, bind):
    """The command of a start: onboard (quickstart, then the server) when the instance has no configuration yet, else run."""
    if os.path.isfile(os.path.join(home, 'instances', instance, 'config.json')):
        return [cli, 'run']
    return [cli, 'onboard', '--yes'] + (['--bind', bind] if bind != 'loopback' else [])


def health_ok(text):
    """Whether an /api/health answer says the server is up (a JSON status ok, or any 2xx body)."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return bool(text)
    status = str((data or {}).get('status', 'ok')).lower() if isinstance(data, dict) else 'ok'
    return status in ('ok', 'healthy', 'up', 'pass')


def listening(port, timeout = 1.0):
    """Whether something listens on 127.0.0.1:<port>."""
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout = timeout):
            return True
    except OSError:
        return False


def health(port, timeout = 3.0):
    """GET /api/health on 127.0.0.1 -> (ok, the answer)."""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{int(port)}/api/health', timeout = timeout) as r:
            text = r.read(4000).decode('utf-8', 'replace')
            return 200 <= r.status < 300 and health_ok(text), text
    except Exception as e:
        return False, str(e)


def alive(pid):
    """Whether the process lives (POSIX)."""
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def log_tail(path, lines = 8):
    try:
        with open(path, encoding = 'utf-8', errors = 'replace') as f:
            return ' | '.join(x.strip() for x in f.read().splitlines()[-lines:] if x.strip())
    except OSError:
        return ''


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,                  # cMeta context
            action: str = 'start',      # start | status | stop
            instance: str = 'default',  # Paperclip's instance (PAPERCLIP_INSTANCE_ID): its configuration, database and files
            port: int = 3100,           # the port of its UI and API
            bind: str = 'loopback',     # loopback (127.0.0.1, no login) | lan | tailnet (reachable from there, with a login)
            data_dir: str = '',         # the data root (PAPERCLIP_HOME; default ~/.local/state/paperclip) - not --home, cx's own flag
            wait: int = 180,            # seconds to wait for /api/health (the first start sets up its database)
            version: str = '',          # the version of the CLI (default: the tool's pinned one)
    ):
        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **cli** (str), **version** (str): the CLI.
                - **running** (bool), **pid** (int), **listening** (bool), **healthy** (bool), **url** (str).
                - **home** (str), **instance** (str), **log** (str).
        """
        con = ctx['control'].get('con', False)

        if detect_os() == 'windows':
            return self.cm.error('run-paperclip runs the server on Linux and macOS: on Windows run it in WSL2 '
                                 '(cx task run run-paperclip --on=wsl) or on a host (--on=<host>)')
        if action not in ('start', 'status', 'stop'):
            return self.cm.error(f'unknown action "{action}": start, status or stop')
        if bind not in BINDS:
            return self.cm.error(f'unknown bind "{bind}": {", ".join(BINDS)}')

        home = os.path.abspath(os.path.expanduser(data_dir or default_home()))
        log = os.path.join(home, f'cmeta-{instance}.log')
        pid_file = os.path.join(home, f'cmeta-{instance}.pid')
        self._c = {'home': home, 'instance': instance, 'port': int(port), 'log': log, 'pid_file': pid_file}
        out = {'return': 0, 'home': home, 'instance': instance, 'log': log, 'url': f'http://127.0.0.1:{int(port)}',
               'cli': '', 'version': ''}

        if action == 'stop':
            out['stopped'] = self._stop(con)
            out.update(self._status())
            return out

        if action == 'start':
            request = {'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': SETUP, 'name': TOOL, 'ctx': ctx,
                       'con': con, 'quiet': ctx['control'].get('quiet', False)}
            if version:
                request['version'] = version
            r = self.cm.access(request)
            if r['return'] > 0:
                return self.cm.error('Paperclip is not available: ' + r.get('error', ''))
            out['cli'], out['version'] = r.get('path') or '', r.get('version') or ''
            r = self._start(out['cli'], bind, int(wait), con)
            if r['return'] > 0:
                return r

        out.update(self._status())
        if con:
            self._print(out)
        return out

    ############################################################
    def _pid(self):
        try:
            with open(self._c['pid_file'], encoding = 'utf-8') as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return 0

    def _start(self, cli, bind, wait, con):
        c = self._c
        pid = self._pid()
        if pid and alive(pid) and listening(c['port']):
            if con:
                print(f'cMeta info: Paperclip "{c["instance"]}" runs already (pid {pid}, http://127.0.0.1:{c["port"]})')
            return {'return': 0}
        if listening(c['port']):
            return self.cm.error(f'another process listens on 127.0.0.1:{c["port"]}: --port=<another one>')

        os.makedirs(c['home'], exist_ok = True)
        args = start_args(cli, c['home'], c['instance'], bind)
        env = server_env(os.environ, c['home'], c['instance'], c['port'], bind)

        # A session of its own: no hang-up from the shell or the ssh connection that started it
        logf = open(c['log'], 'ab')
        proc = subprocess.Popen(args, cwd = c['home'], env = env, stdin = subprocess.DEVNULL, stdout = logf,
                                stderr = subprocess.STDOUT, start_new_session = True)
        logf.close()
        with open(c['pid_file'], 'w', encoding = 'utf-8') as f:
            f.write(f'{proc.pid}\n')
        if con:
            print(f'cMeta info: Paperclip "{c["instance"]}" started (pid {proc.pid}, {" ".join(os.path.basename(a) if i == 0 else a for i, a in enumerate(args))}); '
                  f'waiting for http://127.0.0.1:{c["port"]}/api/health ...')

        deadline = time.monotonic() + max(1, wait)
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return self.cm.error(f'Paperclip exited with code {proc.returncode} ({c["log"]}): {log_tail(c["log"])}')
            ok, _ = health(c['port'])
            if ok:
                return {'return': 0}
            time.sleep(2)
        return self.cm.error(f'Paperclip does not answer on http://127.0.0.1:{c["port"]}/api/health after {wait} s: see '
                             f'{c["log"]} (--wait=<seconds>)')

    def _stop(self, con):
        c = self._c
        pid = self._pid()
        if not pid or not alive(pid):
            if con:
                print(f'cMeta info: Paperclip "{c["instance"]}" is not running')
            return False
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            os.kill(pid, signal.SIGTERM)

        # its embedded PostgreSQL shuts down with it: a while, then the whole group
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and alive(pid):
            time.sleep(0.5)
        if alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.remove(c['pid_file'])
        except OSError:
            pass
        if con:
            print(f'cMeta info: Paperclip "{c["instance"]}" stopped (pid {pid}); its data stays in {c["home"]}')
        return True

    def _status(self):
        c = self._c
        pid = self._pid()
        ok, answer = health(c['port']) if listening(c['port']) else (False, '')
        return {'pid': pid, 'running': bool(pid and alive(pid)), 'listening': listening(c['port']), 'healthy': ok,
                'health': answer[:300]}

    def _print(self, out):
        print('')
        if out['cli']:
            print(f'paperclip:  {out["version"] or "-"} at {out["cli"]}')
        print(f'server:     {"running, pid " + str(out["pid"]) if out["running"] else "not running"}'
              f'{", healthy at " + out["url"] if out["healthy"] else (", listening on " + out["url"] if out["listening"] else "")}')
        print(f'data:       {out["home"]} (instance {out["instance"]}; log {out["log"]})')
