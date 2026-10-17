"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

manage-cloudflare-tunnel: the Cloudflare Tunnel service of this machine. A remotely managed tunnel (the routes
are set in the Cloudflare dashboard, the machine holds only the tunnel's token) is run by cloudflared as a
system service - a systemd unit on Linux, a launchd daemon on macOS - with the token in a root-only file passed
by --token-file, so it never shows on a command line or in a unit file.

    cxt manage-cloudflare-tunnel                          # status (no root needed)
    cxt manage-cloudflare-tunnel --strict -q              # an error when something is not right
    cxt manage-cloudflare-tunnel install --token_file=<file> [--force] [--plan]
    cxt manage-cloudflare-tunnel restart | upgrade [--version=<v>] | uninstall   [--plan]

The status reads the connector's metrics server (127.0.0.1:20241-20245): /ready gives the connections to
Cloudflare's edge, /config the routes the dashboard set. Each route's origin is tried (a TCP connect) and its
public hostname asked over HTTPS (a Cloudflare Access login answers with a redirect to cloudflareaccess.com).

The planning functions are pure and tested offline; run() executes their steps with "sudo -n" in a quiet or
non-terminal run (never a hidden prompt) and plain sudo in a terminal. Windows: status only for now.
"""

import base64
import binascii
import json
import os
import plistlib
import re
import shlex
import shutil
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request

from task_c36be4b9314a45e0.api.ctask import InitCTask, ask

TOOL = 'cloudflared,0c899df096624c7a'
SETUP = 'setup,a2f9b61079ce4333'

TOKEN_PATH = '/etc/cloudflared/token'
SYSTEM_BIN = '/usr/local/bin/cloudflared'
UNIT_NAME = 'cloudflared'
UNIT_PATH = '/etc/systemd/system/cloudflared.service'
LAUNCHD_LABEL = 'com.cloudflare.cloudflared'
PLIST_PATH = '/Library/LaunchDaemons/com.cloudflare.cloudflared.plist'
WINDOWS_SERVICE = 'cloudflared'
METRICS_PORTS = (20241, 20242, 20243, 20244, 20245)

# What a plan shows when the release is not in the cMeta cache yet (the run sets it up)
PLANNED_BINARY = '<the cloudflared release set up by "cx tool setup cloudflared">'

# A binary in one of these folders belongs to the system (a package, brew): a root service may run it.
# Anything else - the cMeta cache above all, which the user cleans - is copied to SYSTEM_BIN first.
SYSTEM_DIRS = ('/usr/bin/', '/usr/sbin/', '/usr/local/bin/', '/opt/homebrew/', '/home/linuxbrew/', '/snap/')

UNIT_TEXT = """[Unit]
Description=Cloudflare Tunnel client
After=network-online.target
Wants=network-online.target

[Service]
TimeoutStartSec=15
Type=notify
ExecStart={binary} --no-autoupdate tunnel run --token-file {token}
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
"""


##############################################################################################################
# Pure functions, tested offline

def detect_os():
    """'windows', 'darwin' or 'linux'."""
    if os.name == 'nt':
        return 'windows'
    return 'darwin' if sys.platform == 'darwin' else 'linux'


def decode_token(text):
    """The account and tunnel of a tunnel token (base64 of {"a": account, "t": tunnel, "s": secret}).
    Raises ValueError for anything else. The secret is never returned."""
    value = (text or '').strip()
    if not value or any(c.isspace() for c in value):
        raise ValueError('a tunnel token is one word (copy it from the dashboard: Networks -> Tunnels -> the tunnel -> install command)')
    try:
        data = json.loads(base64.b64decode(value + '=' * (-len(value) % 4)).decode('utf-8'))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ValueError('this is not a Cloudflare tunnel token (not base64 JSON)')
    if not isinstance(data, dict) or not all(data.get(k) for k in ('a', 't', 's')):
        raise ValueError('this is not a Cloudflare tunnel token (no account, tunnel and secret)')
    return {'account': str(data['a']), 'tunnel': str(data['t'])}


def redact(argv):
    """A command line with the value of --token hidden ("--token X" and "--token=X")."""
    out, hide = [], False
    for a in argv:
        if hide:
            out.append('<hidden>')
            hide = False
        elif a == '--token':
            out.append(a)
            hide = True
        elif a.startswith('--token='):
            out.append('--token=<hidden>')
        else:
            out.append(a)
    return out


def parse_systemctl_show(text):
    """`systemctl show -p ActiveState,UnitFileState,LoadState,ExecStart <unit>` as a dict; 'argv' = the
    ExecStart command line ("ExecStart={ path=/usr/bin/x ; argv[]=/usr/bin/x a b ; ignore_errors=no ; ... }")."""
    d = {}
    for line in text.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            d[k.strip()] = v.strip()
    m = re.search(r'argv\[\]=(.*?)\s;\s', d.get('ExecStart', ''))
    d['argv'] = m.group(1).split() if m else []
    return d


def parse_launchctl_print(text):
    """`launchctl print system/<label>`: the state ("state = running") and the program arguments."""
    state = re.search(r'^\s*state = (\S+)', text, re.M)
    args = re.search(r'arguments = \{(.*?)\}', text, re.S)
    return {'state': state.group(1) if state else 'unknown',
            'argv': [x.strip() for x in args.group(1).strip().splitlines() if x.strip()] if args else []}


def parse_sc_qc(text):
    """`sc qc <service>` / `sc query <service>`: the state and the binary path name."""
    state = re.search(r'STATE\s*:\s*\d+\s+([A-Z_]+)', text)
    binary = re.search(r'BINARY_PATH_NAME\s*:\s*(.+)', text)
    start = re.search(r'START_TYPE\s*:\s*\d+\s+([A-Z_]+)', text)
    return {'state': state.group(1).lower() if state else 'unknown',
            'argv': binary.group(1).strip().split() if binary else [],
            'enabled': start.group(1).lower() if start else ''}


def parse_ingress(config):
    """The routes of the connector's /config answer: [{hostname, path, service}] without the catch-all, and the
    catch-all service. Accepts the JSON text or the parsed dict."""
    if isinstance(config, str):
        config = json.loads(config)
    rules = ((config or {}).get('config') or {}).get('ingress') or []
    routes, catch_all = [], None
    for r in rules:
        if r.get('hostname'):
            routes.append({'hostname': r['hostname'], 'path': r.get('path') or '', 'service': r.get('service', '')})
        else:
            catch_all = r.get('service', '')
    return {'version': (config or {}).get('version'), 'routes': routes, 'catch_all': catch_all}


def origin_address(service):
    """(host, port) of a route's origin to try with a TCP connect, or None (http_status:404, hello_world,
    unix sockets, bastion)."""
    m = re.match(r'^(https?|tcp|ssh|rdp|smb)://(\[[^\]]+\]|[^:/]+)(?::(\d+))?', service or '')
    if not m:
        return None
    default = {'http': 80, 'https': 443, 'ssh': 22, 'rdp': 3389, 'smb': 445}.get(m.group(1))
    port = int(m.group(3)) if m.group(3) else default
    return (m.group(2).strip('[]'), port) if port else None


def public_verdict(status, location):
    """A short word on what the public hostname answered."""
    if status is None:
        return 'no answer'
    if 'cloudflareaccess.com' in (location or ''):
        return 'Cloudflare Access login'
    if status in (401, 403):
        return f'{status}: a login is asked'
    if status in (502, 503, 530):
        return f'{status}: Cloudflare cannot reach the origin'
    return str(status)


def last_error(log):
    """The message of the last ERR line of cloudflared's log ('... ERR Register tunnel error from server side
    error="Failed to get tunnel" connIndex=0 ...' -> 'Register tunnel error from server side error="Failed to get
    tunnel"'), or ''."""
    for line in reversed((log or '').splitlines()):
        m = re.search(r'\bERR\s+(.*)', line)
        if m:
            return re.sub(r'\s+(connIndex|event|ip|location)=\S+', '', m.group(1)).strip()
    return ''


def with_sudo(cmd, interactive, root = False):
    """sudo in front of a system command: "-n" (never a hidden prompt) unless the run is interactive."""
    if root:
        return cmd
    return ('sudo ' if interactive else 'sudo -n ') + cmd


def needs_copy(binary):
    """True when the binary is not in a system folder (a root service must not run it from the cMeta cache)."""
    return not any((binary or '').startswith(d) for d in SYSTEM_DIRS)


def unit_text(binary, token = TOKEN_PATH):
    """The systemd unit of the tunnel."""
    return UNIT_TEXT.format(binary = binary, token = token)


def plist_bytes(binary, token = TOKEN_PATH):
    """The launchd daemon of the tunnel."""
    return plistlib.dumps({'Label': LAUNCHD_LABEL,
                           'ProgramArguments': [binary, '--no-autoupdate', 'tunnel', 'run', '--token-file', token],
                           'RunAtLoad': True,
                           'KeepAlive': True,
                           'ThrottleInterval': 5,
                           'StandardOutPath': '/Library/Logs/com.cloudflare.cloudflared.out.log',
                           'StandardErrorPath': '/Library/Logs/com.cloudflare.cloudflared.err.log'})


def action_steps(action, uname, binary = None, token_tmp = None, service_tmp = None, channel = None, new_binary = None):
    """
    The steps of an action as (what, command, needs root, may fail) tuples. Nothing runs here.
    binary: the cloudflared the service is to run; token_tmp / service_tmp: private temporary files holding the
    token and the unit/plist (install); channel: 'apt', 'dnf', 'brew' or 'copy' (upgrade); new_binary: the
    binary that replaces SYSTEM_BIN (upgrade by copy).
    A start that fails (systemctl restart, launchctl bootstrap / kickstart) may fail: a wrong token makes it
    fail after its start timeout, and the connector check that follows every action says why.
    """
    q = shlex.quote
    steps = []
    if uname not in ('linux', 'darwin'):
        raise ValueError(f'"{action}" is not supported on {uname} yet: on Windows run "cloudflared service install <token>" '
                         'in an administrator terminal')

    if action == 'install':
        run_binary = binary
        if needs_copy(binary):
            steps.append((f'cloudflared copied to {SYSTEM_BIN}', f'install -d -m 0755 {os.path.dirname(SYSTEM_BIN)}', True, False))
            steps.append(('', f'install -m 0755 {q(binary)} {SYSTEM_BIN}', True, False))
            run_binary = SYSTEM_BIN
        steps.append((f'the token in {TOKEN_PATH} (root only)', f'install -d -m 0755 {os.path.dirname(TOKEN_PATH)}', True, False))
        steps.append(('', f'install -m 0600 {q(token_tmp)} {TOKEN_PATH}', True, False))
        if uname == 'linux':
            steps.append((f'the unit {UNIT_PATH}', f'install -m 0644 {q(service_tmp)} {UNIT_PATH}', True, False))
            steps.append(('the service enabled and (re)started', 'systemctl daemon-reload', True, False))
            steps.append(('', f'systemctl enable {UNIT_NAME}', True, False))
            steps.append(('', f'systemctl restart {UNIT_NAME}', True, True))
        else:
            steps.append((f'the daemon {PLIST_PATH}', f'install -m 0644 {q(service_tmp)} {PLIST_PATH}', True, False))
            steps.append(('the daemon (re)loaded', f'launchctl bootout system/{LAUNCHD_LABEL}', True, True))
            steps.append(('', f'launchctl bootstrap system {PLIST_PATH}', True, True))
        return steps

    if action == 'uninstall':
        if uname == 'linux':
            steps.append(('the service stopped and disabled', f'systemctl disable --now {UNIT_NAME}', True, True))
            steps.append((f'the unit and the token removed', f'rm -f {UNIT_PATH} {TOKEN_PATH}', True, False))
            steps.append(('', 'systemctl daemon-reload', True, False))
        else:
            steps.append(('the daemon stopped', f'launchctl bootout system/{LAUNCHD_LABEL}', True, True))
            steps.append(('the daemon and the token removed', f'rm -f {PLIST_PATH} {TOKEN_PATH}', True, False))
        return steps

    if action in ('restart', 'upgrade'):
        if action == 'upgrade':
            if channel == 'apt':
                steps.append(('the package upgraded (apt)', 'apt-get update', True, False))
                steps.append(('', 'apt-get install --only-upgrade -y cloudflared', True, False))
            elif channel == 'dnf':
                steps.append(('the package upgraded (dnf)', 'dnf upgrade -y cloudflared', True, False))
            elif channel == 'brew':
                steps.append(('the brew formula upgraded', 'brew upgrade cloudflared', False, False))
            elif channel == 'copy':
                steps.append((f'the new release copied to {SYSTEM_BIN}', f'install -m 0755 {q(new_binary)} {SYSTEM_BIN}', True, False))
            else:
                raise ValueError(f'cannot tell how the cloudflared of the service was installed ({binary})')
        if uname == 'linux':
            steps.append(('the service restarted', f'systemctl restart {UNIT_NAME}', True, True))
        else:
            steps.append(('the daemon restarted', f'launchctl kickstart -k system/{LAUNCHD_LABEL}', True, True))
        return steps

    raise ValueError(f'unknown action "{action}"')


##############################################################################################################

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,                  # cMeta context
            action: str = 'status',     # status | install | uninstall | restart | upgrade
            token_file: str = '',       # install: a file holding the tunnel token (else asked in a terminal)
            force: bool = False,        # install: replace a tunnel service that exists
            plan: bool = False,         # print the steps of an action, run nothing
            version: str = '',          # upgrade of a copied binary / install: the cloudflared release (the tool's pin otherwise)
            public: bool = True,        # status: ask each public hostname over HTTPS
            strict: bool = False,       # status: an error when the service, the connector or an origin is not right
            metrics: str = '',          # the connector's metrics server host:port (127.0.0.1:20241-20245 otherwise)
            wait: int = 30,             # seconds to wait for the connector after install/restart/upgrade
            timeout: int = 300,         # seconds per command
    ):
        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **os** (str): windows, linux or darwin.
                - **binary** (dict): path, version, channel of the cloudflared the service runs (or the one on the PATH).
                - **service** (dict): manager, state, enabled, command (the token hidden).
                - **connector** (dict): ready, connections, connector_id, metrics.
                - **routes** (list): hostname, path, service, origin (listening/closed/-), public (what the hostname answered).
                - **ok** (bool): the service running, the connector ready, every origin listening.
                - **steps** (list): the commands of an action (planned or run).
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        uname = detect_os()
        interactive = (not quiet) and sys.stdin.isatty()
        root = uname != 'windows' and os.geteuid() == 0

        if action == 'status':
            r = self._status(uname, public, metrics, timeout)
            if con:
                self._print_status(r, space)
            if strict and not r['ok']:
                return self.cm.error('the tunnel is not right: ' + '; '.join(r['problems']))
            return r

        if action not in ('install', 'uninstall', 'restart', 'upgrade'):
            return self.cm.error(f'unknown action "{action}": status, install, uninstall, restart or upgrade')

        if uname == 'windows':
            return self.cm.error(f'"{action}" is not supported on Windows yet: run "cloudflared service install <token>" '
                                 'in an administrator terminal (the status works here)')

        before = self._service(uname)
        tmp_dir = None
        try:
            kw = {}

            if action == 'install':
                if before['state'] not in ('missing', 'unknown') and not force:
                    return self.cm.error(f'a tunnel service exists here ({before["manager"]}, {before["state"]}): '
                                         'add --force to replace its token and its unit')
                token = self._token(token_file, interactive, plan)
                if token.get('return', 0) > 0:
                    return token
                rs = self._setup_tool(ctx, version, install = not plan)
                if rs['return'] > 0:
                    if not plan:
                        return rs
                    rs = {'return': 0, 'path': PLANNED_BINARY, 'version': version}
                kw['binary'] = rs['path']
                tmp_dir = tempfile.mkdtemp(prefix = 'cmeta-cloudflared-')
                kw['token_tmp'] = os.path.join(tmp_dir, 'token')
                kw['service_tmp'] = os.path.join(tmp_dir, 'cloudflared.service' if uname == 'linux' else 'cloudflared.plist')
                run_binary = SYSTEM_BIN if needs_copy(rs['path']) else rs['path']
                if not plan:
                    fd = os.open(kw['token_tmp'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'w') as f:
                        f.write(token['token'])
                    with open(kw['service_tmp'], 'wb') as f:
                        f.write(unit_text(run_binary).encode() if uname == 'linux' else plist_bytes(run_binary))
                if con:
                    print (f'{space}INFO: tunnel {token["tunnel"]} (account {token["account"]}), cloudflared {rs.get("version", "")} '
                           f'at {run_binary}')

            elif action in ('restart', 'upgrade', 'uninstall') and before['state'] == 'missing':
                return self.cm.error(f'there is no tunnel service on this machine to {action}')

            if action == 'upgrade':
                binary = before.get('binary') or ''
                kw['binary'] = binary
                kw['channel'] = self._channel(uname, binary)
                if kw['channel'] == 'copy':
                    rs = self._setup_tool(ctx, version, install = not plan)
                    if rs['return'] > 0:
                        if not plan:
                            return rs
                        rs = {'return': 0, 'path': PLANNED_BINARY, 'version': None}
                    current = self._version(binary)
                    if current and current == rs.get('version') and not force:
                        if con:
                            print (f'{space}INFO: cloudflared {current} is already the release asked for - nothing to upgrade')
                        return {'return': 0, 'os': uname, 'steps': [], 'upgraded': False}
                    kw['new_binary'] = rs['path']

            try:
                steps = action_steps(action, uname, **kw)
            except ValueError as e:
                return self.cm.error(str(e))

            lines = [(what, with_sudo(cmd, interactive, root) if needs_root else cmd, may_fail) for what, cmd, needs_root, may_fail in steps]

            if con or plan:
                print ('')
                print (f'{space}{action}: the steps on this {uname} machine:')
                for what, line, _ in lines:
                    if what:
                        print (f'{space}  # {what}')
                    print (f'{space}  {line}')

            if plan:
                return {'return': 0, 'os': uname, 'steps': [x[1] for x in lines], 'planned': True}

            # Root without a hidden prompt: asked once, before anything changes
            if not interactive and not root and any(line.startswith('sudo -n ') for _, line, _ in lines) and \
                    self._sh('sudo -n true')[1] != 0:
                return self.cm.error('sudo needs a password on this machine: run the task in a terminal (without -q), '
                                     'or add a NOPASSWD rule; nothing was changed')

            if not quiet:
                rr = ask('Run these steps? [Y/n] ')
                if rr['return'] > 0:
                    return rr
                if rr['answer'].strip().lower() not in ('', 'y', 'yes'):
                    return {'return': 0, 'os': uname, 'steps': [], 'status': 'declined'}

            for what, line, may_fail in lines:
                rr = self.cm.utils.sys.run(line, capture_output = not con, con = con, timeout = int(timeout), verbose = verbose,
                                           text_cmd = 'RUN:', space = space, fail_on_error = False, logger = self.logger)
                rc = rr.get('returncode', -1) if rr.get('return', 0) == 0 else -1
                if rc != 0 and not may_fail:
                    out = ((rr.get('stdout') or '') + (rr.get('stderr') or '')).strip()
                    return self.cm.error(f'"{line}" failed (exit code {rc})' + (f':\n{out}' if out else ''))
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors = True)

        result = {'return': 0, 'os': uname, 'steps': [x[1] for x in lines]}
        if action == 'uninstall':
            result['service'] = self._service(uname)
            if con:
                print (f'{space}INFO: the tunnel service is removed (the cloudflared binary stays)')
            return result

        # The connector after install / restart / upgrade
        deadline = time.monotonic() + int(wait)
        while True:
            connector = self._connector(metrics)
            if connector['ready'] or time.monotonic() >= deadline:
                break
            time.sleep(1)
        result['connector'] = connector
        result['service'] = self._service(uname)
        if con:
            print ('')
            self._print_status(self._status(uname, False, metrics, timeout), space)
        if not connector['ready']:
            logs = 'journalctl -u cloudflared -n 50 --no-pager' if uname == 'linux' else 'tail -50 /Library/Logs/com.cloudflare.cloudflared.err.log'
            said = last_error(self._sh(with_sudo(logs, interactive, root))[0])
            return self.cm.error(f'the connector is not ready after {wait} s (service {result["service"]["state"]})'
                                 + (f', cloudflared says: {said}' if said else '') + f' - see "sudo {logs}"'
                                 + (' (is the token right?)' if action == 'install' else ''))
        return result

    ############################################################
    def _sh(self, cmd, timeout = 30):
        """Run a read-only command; its output ('' when it fails) and its exit code."""
        rr = self.cm.utils.sys.run(cmd, capture_output = True, con = False, timeout = timeout,
                                   fail_on_error = False, logger = self.logger)
        if rr.get('return', 0) > 0:
            return '', -1
        return (rr.get('stdout') or '') + (rr.get('stderr') or ''), rr.get('returncode', -1)

    ############################################################
    def _token(self, token_file, interactive, planned):
        """The token from the file, else asked (hidden) in a terminal; checked, never printed."""
        if token_file:
            path = os.path.abspath(os.path.expanduser(token_file))
            try:
                with open(path, encoding = 'utf-8') as f:
                    text = f.read()
            except OSError as e:
                return self.cm.error(f'cannot read the token file: {e}')
        elif planned:
            return {'return': 0, 'token': '', 'account': '<from the token>', 'tunnel': '<from the token>'}
        elif interactive:
            import getpass
            text = getpass.getpass('Tunnel token (dashboard: Networks -> Tunnels -> the tunnel -> install command; hidden): ')
        else:
            return self.cm.error('no token: give --token_file=<a file holding the tunnel token>, or run in a terminal to be asked')
        try:
            info = decode_token(text)
        except ValueError as e:
            return self.cm.error(str(e))
        return dict(info, token = text.strip(), **{'return': 0})

    ############################################################
    def _setup_tool(self, ctx, version, install = True):
        """cloudflared through tool/cloudflared (detected, else the pinned release)."""
        ii = {'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': SETUP, 'name': TOOL, 'ctx': ctx,
              'con': False, 'quiet': True, 'install': install, 'skip_install': not install}
        if version:
            ii['version'] = version
        r = self.cm.access(ii)
        if r['return'] > 0:
            return self.cm.error('cloudflared is not available: ' + r.get('error', '') +
                                 ('' if install else ' (a plan does not install it: run "cx tool setup cloudflared -q" first)'))
        return r

    ############################################################
    def _version(self, binary):
        out, rc = self._sh(f'{shlex.quote(binary)} --version' if os.name != 'nt' else f'"{binary}" --version')
        m = re.search(r'cloudflared version (\d+\.\d+\.\d+)', out)
        return m.group(1) if m else ''

    ############################################################
    def _channel(self, uname, binary):
        """How the binary of the service came: apt, dnf, brew or copy (this task's copy of the cMeta release)."""
        real = os.path.realpath(binary) if binary else ''
        if real.startswith(('/opt/homebrew/', '/home/linuxbrew/')) or '/Cellar/' in real:
            return 'brew'
        if uname == 'linux' and real:
            if shutil.which('dpkg') and self._sh(f'dpkg -S {shlex.quote(real)}')[1] == 0:
                return 'apt'
            if shutil.which('rpm') and self._sh(f'rpm -qf {shlex.quote(real)}')[1] == 0:
                return 'dnf'
        if binary == SYSTEM_BIN:
            return 'copy'
        return None

    ############################################################
    def _service(self, uname):
        """The tunnel service: manager, state (active/running, inactive, failed, missing, unknown), enabled, command."""
        if uname == 'linux':
            if not shutil.which('systemctl'):
                return {'manager': 'none', 'state': 'unknown', 'enabled': '', 'command': '', 'binary': ''}
            out, _ = self._sh(f'systemctl show -p LoadState,ActiveState,UnitFileState,ExecStart {UNIT_NAME}')
            d = parse_systemctl_show(out)
            state = 'missing' if d.get('LoadState') == 'not-found' else d.get('ActiveState', 'unknown')
            argv = d['argv']
            return {'manager': 'systemd', 'name': UNIT_NAME + '.service', 'state': state, 'enabled': d.get('UnitFileState', ''),
                    'command': ' '.join(redact(argv)), 'binary': argv[0] if argv else ''}
        if uname == 'darwin':
            out, rc = self._sh(f'launchctl print system/{LAUNCHD_LABEL}')
            if rc != 0:
                state = 'missing' if not os.path.exists(PLIST_PATH) else 'not loaded'
                return {'manager': 'launchd', 'name': LAUNCHD_LABEL, 'state': state, 'enabled': '', 'command': '', 'binary': ''}
            d = parse_launchctl_print(out)
            return {'manager': 'launchd', 'name': LAUNCHD_LABEL, 'state': d['state'], 'enabled': 'loaded',
                    'command': ' '.join(redact(d['argv'])), 'binary': d['argv'][0] if d['argv'] else ''}
        out, rc = self._sh(f'sc query {WINDOWS_SERVICE}')
        if rc != 0 or 'STATE' not in out:
            return {'manager': 'windows service', 'state': 'missing', 'enabled': '', 'command': '', 'binary': ''}
        d = parse_sc_qc(out + '\n' + self._sh(f'sc qc {WINDOWS_SERVICE}')[0])
        return {'manager': 'windows service', 'name': WINDOWS_SERVICE, 'state': d['state'], 'enabled': d['enabled'],
                'command': ' '.join(redact(d['argv'])), 'binary': d['argv'][0].strip('"') if d['argv'] else ''}

    ############################################################
    @staticmethod
    def _get(url, timeout = 3):
        """An HTTP GET of a local URL: (status, text) or (None, '')."""
        try:
            with urllib.request.urlopen(url, timeout = timeout) as f:
                return f.status, f.read().decode('utf-8', 'replace')
        except (urllib.error.URLError, OSError, ValueError):
            return None, ''

    ############################################################
    def _connector(self, metrics):
        """The connector's /ready and /config from its metrics server."""
        hosts = [metrics] if metrics else [f'127.0.0.1:{p}' for p in METRICS_PORTS]
        for h in hosts:
            status, text = self._get(f'http://{h}/ready')
            if status is None:
                continue
            try:
                ready = json.loads(text)
            except ValueError:
                ready = {}
            c = {'metrics': h, 'ready': status == 200, 'connections': ready.get('readyConnections', 0),
                 'connector_id': ready.get('connectorId', '')}
            status, text = self._get(f'http://{h}/config')
            try:
                c['config'] = parse_ingress(text) if status == 200 else None
            except ValueError:
                c['config'] = None
            return c
        return {'metrics': '', 'ready': False, 'connections': 0, 'connector_id': '', 'config': None}

    ############################################################
    @staticmethod
    def _public(hostname, timeout = 10):
        """What https://<hostname>/ answers, redirects not followed: (status, location)."""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context = ssl.create_default_context()))
        req = urllib.request.Request(f'https://{hostname}/', headers = {'User-Agent': 'cmeta-manage-cloudflare-tunnel'})
        try:
            with opener.open(req, timeout = timeout) as f:
                return f.status, f.headers.get('Location', '')
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get('Location', '') if e.headers else ''
        except (urllib.error.URLError, OSError, ValueError):
            return None, ''

    ############################################################
    def _status(self, uname, public, metrics, timeout):
        """The whole picture, read only."""
        service = self._service(uname)
        binary = service.get('binary') or shutil.which('cloudflared') or ''
        b = {'path': binary, 'version': self._version(binary) if binary else '',
             'channel': self._channel(uname, binary) if binary and uname != 'windows' else None}
        connector = self._connector(metrics)
        config = connector.pop('config', None) or {}
        routes = []
        for r in config.get('routes', []):
            addr = origin_address(r['service'])
            origin = '-'
            if addr:
                try:
                    socket.create_connection(addr, timeout = 2).close()
                    origin = 'listening'
                except OSError:
                    origin = 'closed'
            item = dict(r, origin = origin)
            if public:
                status, location = self._public(r['hostname'])
                item['public'] = public_verdict(status, location)
                item['public_status'] = status
            routes.append(item)

        problems = []
        if service['state'] == 'missing' and not connector['metrics']:
            problems.append('no tunnel service on this machine')
        elif service['state'] not in ('active', 'running'):
            problems.append(f'service {service["state"]}')
        if not connector['ready'] and problems != ['no tunnel service on this machine']:
            problems.append('connector not ready' if connector['metrics'] else 'no connector metrics server answers')
        problems += [f'{r["hostname"]}: origin {r["service"]} closed' for r in routes if r['origin'] == 'closed']
        return {'return': 0, 'os': uname, 'binary': b, 'service': service, 'connector': connector,
                'config_version': config.get('version'), 'catch_all': config.get('catch_all'), 'routes': routes,
                'ok': not problems, 'problems': problems}

    ############################################################
    @staticmethod
    def _print_status(r, space):
        b, s, c = r['binary'], r['service'], r['connector']
        print ('')
        if b['path']:
            print (f'{space}cloudflared: {b["version"] or "?"} at {b["path"]}' + (f' ({b["channel"]})' if b.get('channel') else ''))
        else:
            print (f'{space}cloudflared: not found ("cx tool setup cloudflared" installs the pinned release)')
        line = f'{space}service:     {s["manager"]} {s.get("name", "")} {s["state"]}' + (f', {s["enabled"]}' if s.get('enabled') else '')
        print (line)
        if s.get('command'):
            print (f'{space}             {s["command"]}')
        if c['metrics']:
            print (f'{space}connector:   {"ready" if c["ready"] else "NOT ready"}, {c["connections"]} connection(s) to the edge, '
                   f'connector {c["connector_id"] or "?"}, metrics {c["metrics"]}')
        else:
            print (f'{space}connector:   no metrics server answers on 127.0.0.1:{METRICS_PORTS[0]}-{METRICS_PORTS[-1]}')
        if r['routes']:
            print (f'{space}routes (set in the Cloudflare dashboard, configuration version {r["config_version"]}):')
            for x in r['routes']:
                pub = f', public: {x["public"]}' if 'public' in x else ''
                print (f'{space}  {x["hostname"]}{x["path"]} -> {x["service"]}  (origin {x["origin"]}{pub})')
        print (f'{space}verdict:     ' + ('OK' if r['ok'] else 'NOT OK - ' + '; '.join(r['problems'])))
