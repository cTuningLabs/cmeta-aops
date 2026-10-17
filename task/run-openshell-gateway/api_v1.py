"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-openshell-gateway: a local NVIDIA OpenShell gateway of this user, without upstream's package or service. The
binaries come from tool/openshell (an installation on the PATH, else the pinned release in the cMeta cache).

    cx task run run-openshell-gateway [start|status|test|stop|remove] [--name=cmeta] [--port=17691] [--driver=docker]

start: the gateway's keys (openshell-gateway generate-certs) and gateway.toml in the work folder, a configuration
check (config preflight), the gateway started in a session of its own (it outlives the shell and an ssh connection),
a wait until it listens, and its registration with the CLI ("openshell gateway add http://127.0.0.1:<port> --local
--name <name>"). It listens in plaintext on 127.0.0.1 only and lets local users in without a login, as upstream's own
Docker compose setup does; its database lives in the work folder (XDG_STATE_HOME) and its telemetry is off.

The pure parts (the configuration text, the reading of the CLI's gateway list) are tested offline.
"""

import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

from task_c36be4b9314a45e0.api.ctask import InitCTask

SETUP = 'setup,a2f9b61079ce4333'
TOOL = 'openshell,7990c822d96f41d4'
MARKER = 'cmeta-openshell-ok'


def detect_os():
    """windows, linux or darwin."""
    s = platform.system().lower()
    return 'windows' if s.startswith('win') else ('darwin' if s == 'darwin' else 'linux')


def default_workdir(name):
    """The work folder of a gateway: next to the state of upstream's own gateway (~/.local/state/openshell/gateway)."""
    state = os.environ.get('XDG_STATE_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'state')
    return os.path.join(state, 'openshell', f'cmeta-{name}')


def gateway_toml(name, port, driver, jwt_dir):
    """The gateway's configuration: plaintext on loopback, local users let in, the sandbox JWT keys of generate-certs."""
    q = lambda p: json.dumps(str(p).replace('\\', '/'))
    lines = ['# Written by cMeta (task run-openshell-gateway): rewritten at every start', '',
             '[openshell]', 'version = 2', '',
             '[openshell.gateway]', f'bind_address = "127.0.0.1:{int(port)}"', 'disable_tls = true', 'log_level = "info"']
    if driver:
        lines.append(f'compute_driver = "{driver}"')
    lines += ['', '[openshell.gateway.auth]', 'allow_unauthenticated_users = true', '',
              '[openshell.gateway.gateway_jwt]',
              f'signing_key_path = {q(os.path.join(jwt_dir, "signing.pem"))}',
              f'public_key_path = {q(os.path.join(jwt_dir, "public.pem"))}',
              f'kid_path = {q(os.path.join(jwt_dir, "kid"))}',
              f'gateway_id = "cmeta-{name}"']
    return '\n'.join(lines) + '\n'


def registered(listing, name):
    """The endpoint the CLI has registered under a name ("openshell gateway list -o json"), or None."""
    try:
        data = json.loads(listing)
    except (TypeError, ValueError):
        return None
    items = data.get('gateways') if isinstance(data, dict) else data
    for g in items or []:
        if isinstance(g, dict) and g.get('name') == name:
            return g.get('endpoint') or g.get('url') or ''
    return None


def listening(port, timeout = 1.0):
    """Whether something accepts connections on 127.0.0.1:<port>."""
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout = timeout):
            return True
    except OSError:
        return False


def log_tail(path, lines = 6):
    """The last lines of a log, for an error message."""
    try:
        with open(path, encoding = 'utf-8', errors = 'replace') as f:
            return ' | '.join(x.strip() for x in f.read().strip().splitlines()[-lines:])
    except OSError:
        return ''


# What a sandbox prints when its supervisor (Docker host networking) cannot reach the gateway on the host's loopback:
# Docker Desktop (macOS, Windows/WSL2) has host networking off by default (2026-10-17, the Mac mini)
DESKTOP_HINT = ('Docker Desktop gives containers host networking only when it is switched on: Settings > Resources > '
                'Network > Enable host networking (and no Enhanced Container Isolation) - OpenShell\'s supervisor needs it')


def supervisor_unreachable(text):
    """Whether a failed sandbox's output says its supervisor could not reach the gateway."""
    return 'Startup configuration fetch failed' in (text or '') or 'ControlSupervisorStartFailed' in (text or '')


def podman_socket():
    """The rootless Podman socket the gateway's Podman driver looks for."""
    runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
    return os.path.join(runtime, 'podman', 'podman.sock')


def podman_major(text):
    """The major version of "podman --version" ("podman version 5.7.0" -> 5), or 0."""
    import re
    m = re.search(r'(\d+)\.\d+', text or '')
    return int(m.group(1)) if m else 0


def pick_driver(env):
    """
    The driver when none is asked for: Docker when its daemon answers, else Podman 5 or newer, else '' (the gateway's
    own detection). The gateway's detection tries Podman before Docker - a Podman 4 without its socket made it exit
    while Docker worked (the T470p) - and finds no Docker Desktop, whose socket is not /var/run/docker.sock (the Mac).
    Returns (driver, why).
    """
    def answer(args):
        try:
            p = subprocess.run(args, env = env, stdin = subprocess.DEVNULL, stdout = subprocess.PIPE,
                               stderr = subprocess.STDOUT, timeout = 30)
            return p.returncode, p.stdout.decode('utf-8', 'replace')
        except (OSError, subprocess.TimeoutExpired):
            return -1, ''

    docker = shutil.which('docker', path = env.get('PATH'))
    if docker and answer([docker, 'info', '--format', '{{.ServerVersion}}'])[0] == 0:
        return 'docker', 'the Docker daemon answers'
    podman = shutil.which('podman', path = env.get('PATH'))
    if podman:
        rc, text = answer([podman, '--version'])
        if rc == 0 and podman_major(text) >= 5:
            return 'podman', f'Podman {text.split()[-1]}'
        if rc == 0:
            return '', f'Podman {text.split()[-1]} is older than the 5.x OpenShell needs, and no Docker daemon answers'
    return '', 'no Docker daemon answers and no Podman 5 is here'


def alive(pid):
    """Whether the process lives (POSIX)."""
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,                  # cMeta context
            action: str = 'start',      # start | status | test | stop | remove
            name: str = 'cmeta',        # the gateway's name: its registration with the CLI
            port: int = 17691,          # its port on 127.0.0.1 (upstream's packaged gateway uses 17670)
            driver: str = '',           # docker | podman | vm (default: Docker when it answers, else Podman 5+, else the gateway's detection)
            workdir: str = '',          # its keys, gateway.toml, database, log and pid file (default ~/.local/state/openshell/cmeta-<name>)
            config_home: str = '',      # XDG_CONFIG_HOME of the CLI and the gateway (default: theirs, ~/.config)
            wait: int = 120,            # seconds to wait for the gateway to listen
            image: str = '',            # test: the sandbox image (--from; default: the gateway's, a minimal Ubuntu)
            timeout: int = 900,         # test: seconds for the sandbox (its images are pulled the first time)
    ):
        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **cli**, **gateway** (str): the binaries.
                - **version** (str): the CLI's version.
                - **running** (bool), **pid** (int), **listening** (bool), **endpoint** (str), **workdir** (str).
                - **registered** (str): the endpoint the CLI has under the name ('' when none).
                - **test** (dict): ok, sandbox, seconds, output (action test).
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)

        if detect_os() == 'windows':
            return self.cm.error('OpenShell runs on Linux and macOS: on Windows run it in WSL2 '
                                 '(cx task run run-openshell-gateway --on=wsl)')
        if action not in ('start', 'status', 'test', 'stop', 'remove'):
            return self.cm.error(f'unknown action "{action}": start, status, test, stop or remove')

        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': SETUP, 'name': TOOL,
                            'ctx': ctx, 'con': False, 'quiet': True})
        if r['return'] > 0:
            return self.cm.error('OpenShell is not available: ' + r.get('error', ''))
        cli = r.get('path') or ''
        gateway = ((r.get('features') or {}).get('paths') or {}).get('gateway') or shutil.which('openshell-gateway') or ''
        version = r.get('version') or ''

        workdir = os.path.abspath(os.path.expanduser(workdir or default_workdir(name)))
        endpoint = f'http://127.0.0.1:{int(port)}'
        env = dict(os.environ, OPENSHELL_TELEMETRY_ENABLED = 'false', NO_COLOR = '1', OPENSHELL_COLOR = 'never')
        if config_home:
            env['XDG_CONFIG_HOME'] = os.path.abspath(os.path.expanduser(config_home))
        self._ctx = {'cli': cli, 'gateway': gateway, 'env': env, 'workdir': workdir, 'name': name, 'port': int(port),
                     'endpoint': endpoint}

        out = {'return': 0, 'cli': cli, 'gateway': gateway, 'version': version, 'workdir': workdir, 'endpoint': endpoint}

        if action in ('stop', 'remove'):
            stopped = self._stop(con)
            out['stopped'] = stopped
            if action == 'remove':
                self._cli(['gateway', 'remove', name])
                shutil.rmtree(workdir, ignore_errors = True)
                if con:
                    print(f'cMeta info: gateway "{name}" unregistered, {workdir} removed')
            out.update(self._status())
            return out

        if action in ('start', 'test'):
            r = self._start(int(wait), driver, con)
            if r['return'] > 0:
                return r

        out.update(self._status())

        if action == 'test':
            out['test'] = self._test(image, int(timeout), con)

        if con:
            self._print(out)
        if action == 'test' and not out['test']['ok']:
            return dict(out, **self.cm.error(f'the test sandbox failed: {out["test"].get("error") or "no marker in its output"}'))
        return out

    ############################################################
    def _cli(self, args, timeout = 60):
        """The CLI with the gateway's environment: (returncode, output)."""
        c = self._ctx
        try:
            p = subprocess.run([c['cli']] + list(args), env = c['env'], stdin = subprocess.DEVNULL,
                               stdout = subprocess.PIPE, stderr = subprocess.STDOUT, timeout = timeout)
            return p.returncode, p.stdout.decode('utf-8', errors = 'replace')
        except subprocess.TimeoutExpired as e:
            return -1, (e.stdout or b'').decode('utf-8', errors = 'replace') + f'\n(timed out after {timeout} s)'
        except OSError as e:
            return -1, str(e)

    def _pid(self):
        try:
            with open(os.path.join(self._ctx['workdir'], 'gateway.pid'), encoding = 'utf-8') as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    ############################################################
    def _start(self, wait, driver, con):
        c = self._ctx
        if not c['gateway'] or not os.path.isfile(c['gateway']):
            return self.cm.error('this OpenShell has no gateway binary (openshell-gateway): cx tool setup openshell --new')

        pid = self._pid()
        if pid and alive(pid) and listening(c['port']):
            if con:
                print(f'cMeta info: the gateway "{c["name"]}" runs already (pid {pid}, {c["endpoint"]})')
            return self._register(con)
        if listening(c['port']):
            return self.cm.error(f'another process listens on 127.0.0.1:{c["port"]}: --port=<another one>')

        # No driver asked for: Docker when it answers, else Podman 5+ (said in a line)
        if not driver:
            driver, why = pick_driver(c['env'])
            if con:
                chosen = driver or "the gateway's own detection"
                print(f'cMeta info: the driver: {chosen} ({why}; --driver=<name> picks another)')

        # The Podman driver talks to the user's Podman service: its socket unit started when it is not (systemd)
        if driver == 'podman' and not os.path.exists(podman_socket()):
            if shutil.which('systemctl'):
                subprocess.run(['systemctl', '--user', 'start', 'podman.socket'], stdin = subprocess.DEVNULL,
                               stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL)
                if con:
                    print(f'cMeta info: the Podman user socket was not active: systemctl --user start podman.socket')
            if not os.path.exists(podman_socket()):
                return self.cm.error(f'the Podman driver needs the user socket {podman_socket()}: '
                                     f'systemctl --user enable --now podman.socket (or podman system service --time=0 &)')

        pki = os.path.join(c['workdir'], 'pki')
        os.makedirs(os.path.join(c['workdir'], 'state'), exist_ok = True)
        self._ctx['driver'] = driver
        if not os.path.isfile(os.path.join(pki, 'jwt', 'signing.pem')):
            p = subprocess.run([c['gateway'], 'generate-certs', '--output-dir', pki, '--server-san', 'host.openshell.internal'],
                               env = c['env'], stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
            if p.returncode != 0:
                return self.cm.error('openshell-gateway generate-certs failed: ' + p.stdout.decode('utf-8', 'replace')[-500:])

        toml = os.path.join(c['workdir'], 'gateway.toml')
        with open(toml, 'w', encoding = 'utf-8', newline = '\n') as f:
            f.write(gateway_toml(c['name'], c['port'], driver, os.path.join(pki, 'jwt')))

        env = dict(c['env'], XDG_STATE_HOME = os.path.join(c['workdir'], 'state'))
        p = subprocess.run([c['gateway'], 'config', 'preflight', '--path', toml], env = env, stdin = subprocess.DEVNULL,
                           stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
        if p.returncode != 0:
            return self.cm.error('the gateway configuration is not right (config preflight): '
                                 + p.stdout.decode('utf-8', 'replace')[-800:])

        # A session of its own: no hang-up from the shell or the ssh connection that started it
        log = open(os.path.join(c['workdir'], 'gateway.log'), 'ab')
        proc = subprocess.Popen([c['gateway'], '--config', toml], cwd = c['workdir'], env = env, stdin = subprocess.DEVNULL,
                                stdout = log, stderr = subprocess.STDOUT, start_new_session = True)
        log.close()
        with open(os.path.join(c['workdir'], 'gateway.pid'), 'w', encoding = 'utf-8') as f:
            f.write(f'{proc.pid}\n')
        if con:
            print(f'cMeta info: the gateway "{c["name"]}" started (pid {proc.pid}); waiting until it listens on {c["endpoint"]} ...')

        deadline = time.monotonic() + max(1, wait)
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                logf = os.path.join(c['workdir'], 'gateway.log')
                return self.cm.error(f'the gateway exited with code {proc.returncode} ({logf}): {log_tail(logf)}')
            if listening(c['port']):
                break
            time.sleep(1)
        else:
            return self.cm.error(f'the gateway does not listen on {c["endpoint"]} after {wait} s: see '
                                 f'{os.path.join(c["workdir"], "gateway.log")} (--wait=<seconds>)')
        return self._register(con)

    def _register(self, con):
        c = self._ctx
        rc, listing = self._cli(['gateway', 'list', '-o', 'json'])
        have = registered(listing, c['name']) if rc == 0 else None
        if have and have.rstrip('/') == c['endpoint']:
            return {'return': 0}
        if have is not None:
            self._cli(['gateway', 'remove', c['name']])
        rc, text = self._cli(['gateway', 'add', c['endpoint'], '--local', '--name', c['name']])
        if rc != 0:
            return self.cm.error(f'openshell gateway add failed: {text.strip()[-500:]}')
        if con:
            print(f'cMeta info: registered with the CLI as "{c["name"]}" ({c["endpoint"]})')
        return {'return': 0}

    ############################################################
    def _stop(self, con):
        c = self._ctx
        pid = self._pid()
        if not pid or not alive(pid):
            if con:
                print(f'cMeta info: the gateway "{c["name"]}" is not running')
            return False
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and alive(pid):
            time.sleep(0.5)
        if alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.remove(os.path.join(c['workdir'], 'gateway.pid'))
        except OSError:
            pass
        if con:
            print(f'cMeta info: the gateway "{c["name"]}" stopped (pid {pid})')
        return True

    ############################################################
    def _status(self):
        c = self._ctx
        pid = self._pid()
        rc, listing = self._cli(['gateway', 'list', '-o', 'json'])
        st = {'pid': pid, 'running': bool(pid and alive(pid)), 'listening': listening(c['port']),
              'registered': (registered(listing, c['name']) or '') if rc == 0 else ''}
        st['sandboxes'] = None
        if st['listening'] and st['registered']:
            rc, text = self._cli(['-g', c['name'], 'sandbox', 'list'])
            st['sandboxes'] = text.strip() if rc == 0 else f'(sandbox list failed: {text.strip()[-200:]})'
        return st

    def _test(self, image, timeout, con):
        c = self._ctx
        box = 'cx-test-' + uuid.uuid4().hex[:8]
        args = ['-g', c['name'], 'sandbox', 'create', '--name', box, '--no-keep'] + (['--from', image] if image else []) + \
               ['--', 'sh', '-c', f'echo {MARKER}; id -u; uname -m']
        if con:
            print(f'cMeta info: a test sandbox {box} (its images are pulled the first time) ...')
        t0 = time.monotonic()
        rc, text = self._cli(args, timeout = timeout)
        ok = rc == 0 and MARKER in text
        error = '' if ok else text.strip()[-400:]
        if not ok and supervisor_unreachable(text):
            error = 'the sandbox supervisor could not reach the gateway on this machine\'s loopback. ' + DESKTOP_HINT
        return {'ok': ok, 'sandbox': box, 'seconds': round(time.monotonic() - t0, 1), 'returncode': rc,
                'output': text[-2000:], 'error': error}

    def _print(self, out):
        print('')
        print(f'openshell:  {out["version"]} at {out["cli"]} (gateway: {out["gateway"] or "-"})')
        print(f'gateway:    {"running, pid " + str(out["pid"]) if out["running"] else "not running"}'
              f'{", listening on " + out["endpoint"] if out["listening"] else ""}   folder {out["workdir"]}')
        print(f'registered: {out["registered"] or "no"} (the CLI: cx tool run openshell -- -g {self._ctx["name"]} ...)')
        if out.get('sandboxes') is not None:
            print('sandboxes:  ' + (out['sandboxes'].replace('\n', '\n            ') or '-'))
        if out.get('test'):
            t = out['test']
            print(f'test:       {"OK" if t["ok"] else "FAILED"} in {t["seconds"]} s ({t["sandbox"]}, created and deleted)')
