"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

host - a login endpoint of a machine: an OS reachable over ssh (this machine included - a host whose
declared hostname is the local one runs its commands locally), a WSL distro, a container, a phone over
adb. One artifact per thing a command can be run on. It points at its machine artifact (the asset) and
may be reached `via` another host (a container on a remote machine).

Declared by hand in _desc.yaml; observed by `probe` in state.yaml (never edited by hand).
The layout of _desc.yaml and the commands are in ../README.md.

Every verb is built on four driver primitives - status, up/down, run, push/pull - so a new access type
is one more branch in _cmd_run/_status/_up/_down and all the verbs work on it at once.
"""

import fnmatch
import hashlib
import ipaddress
import os
import urllib.error
import urllib.parse
import urllib.request
import re
import sys
import shutil
import socket
import platform
import subprocess
import datetime
import time
import threading
import copy
import json
import shlex
import tempfile
import textwrap

from cmeta.category import InitCategory

DESC_FILE = '_desc.yaml'
STATE_FILE = 'state.yaml'

TYPES = ('ssh', 'wsl', 'docker', 'adb')

DEFAULT_SSH_PORT = 22
DEFAULT_CONNECT_TIMEOUT = 15     # seconds, ssh -o ConnectTimeout
DEFAULT_STATUS_TIMEOUT = 3       # seconds, the TCP probe of "status"
DEFAULT_STATUS_CMD_TIMEOUT = 20  # seconds, a "status" check that runs a command (adb devices, docker inspect, wsl -l)
DEFAULT_PROBE_TIMEOUT = 120      # seconds, the whole probe script
RESTART_DOWN_WAIT = 120          # seconds a restarted ssh host without a boot stamp may stay "up" before it counts as back
DEFAULT_SHELL = 'bash -l'        # a login shell, so ~/.local/bin (cx, uv) and brew are on PATH

# What never leaves this machine when a repository is synced (the user's bisync scripts, 2026-10)
DEFAULT_BLACKLIST = ['tmp*/', '__pycache__/', '.venv/', '.git/', '.claude/', '__symlinks/']
DEFAULT_RCLONE_FLAGS = ['--transfers=4', '--checkers=4']

SYNC_METHODS = ('bisync', 'copy', 'git', 'none')

# A partial repository (a sync entry with "artifacts:"): only the artifacts its cRef patterns select travel. The
# rclone rules they give are kept beside the bisync listings (a bisync whose rules changed needs --resync), and
# PARTIAL.md in the host's copy says what it holds.
PARTIAL_NOTE = 'PARTIAL.md'
GLOB_CHARS = re.compile(r'([\[\]{}\\])')        # escaped in a rule; * and ? are escaped too where a part is literal
UID_SUFFIX = re.compile(r',[0-9a-f]{16}$')

# Columns of the fleet table (list); DOCKER and PODMAN = the client versions the probe saw ("-" = not
# installed, "(daemon down)" when the Docker client is there but no daemon answers)
LIST_COLUMNS = ['HOST', 'TYPE', 'MACHINE', 'STATUS', 'OS', 'SUDO', 'DOCKER', 'PODMAN', 'CMETA', 'AOPS', 'PROBED']

# The cMeta AOPS repository (ctuninglabs@cmeta-aops), known by the UID in its _cmr.yaml "artifact:" -
# its folder name differs between hosts (cTuningLabs@cmeta-aops on the Mac); the name is the fallback
# for a state.yaml probed before the artifact id was recorded.
AOPS_REPO_UID = '3cb4ee4f444048f6'
AOPS_REPO_NAME = 'cmeta-aops'


def windows_here():
    """Whether this machine runs Windows: a command line then goes through cmd.exe to ssh.exe (its own quoting rules)."""
    return os.name == 'nt'


# GNU Screen as cMeta sets it up on a host (the newest copy found there; any version)
# X11 inside Screen: the display of the login that attaches, written for the windows (see _screen_command)
SCREEN_DISPLAY_HOOK = '[ -f ~/.cmeta-screen-display ] && . ~/.cmeta-screen-display'
SCREEN_DISPLAY_SAVE = 'if [ -n "$DISPLAY" ]; then printf "export DISPLAY=%q\\n" "$DISPLAY" > ~/.cmeta-screen-display; if [ -n "$XAUTHORITY" ]; then printf "export XAUTHORITY=%q\\n" "$XAUTHORITY" >> ~/.cmeta-screen-display; fi; fi; '
SCREEN_TOOL = 'cx tool run screen,05d0264fd24b40f6'

# The limit of a query to a session (-Q, -ls): Screen 5.0 answers -Q through the attached display and waits while that
# terminal is not read (a connection that died silently) - the query is stopped and nothing is listed
SCREEN_QUERY_TIMEOUT = '--timeout=10'

# One session of "screen -ls" (any version): "<pid>.<name>" then parenthesised fields - a start time (Screen 4.x of
# the distributions), the state (Attached, Detached, Multi, attached, Dead ???)
SCREEN_SESSION = re.compile(r'^\s*(\d+)\.(\S+)\s+(\(.*)$')


def parse_screens(text):
    """
    The sessions in the output of the screens script of "cx host screens": "@@ls" and Screen's own listing, then for
    each session "@@windows <pid>.<name>" and its window list (empty where -Q is missing: Screen before 4.2). No
    Screen on the host, no session, a login message: [].

    Returns:
        list: [{'id', 'name', 'pid', 'state', 'started', 'windows'}] in the listing's order.
    """
    sessions, current, section = [], None, None
    for line in text.splitlines():
        if line.startswith('@@ls'):
            section = 'ls'
            continue
        if line.startswith('@@windows '):
            key = line[len('@@windows '):].strip()
            current = next((s for s in sessions if s['id'] == key), None)
            section = 'windows'
            continue
        if section == 'ls':
            m = SCREEN_SESSION.match(line)
            if not m:
                continue
            fields = re.findall(r'\(([^()]*)\)', m.group(3))
            state = next((f for f in reversed(fields) if re.search(r'attached|detached|dead', f, re.I)), '')
            started = next((f for f in fields if f != state), '')
            sessions.append({'id': f'{m.group(1)}.{m.group(2)}', 'name': m.group(2), 'pid': int(m.group(1)),
                             'state': state.lower(), 'started': started, 'windows': ''})
        elif section == 'windows' and current is not None and line.strip():
            current['windows'] = (current['windows'] + '  ' + line.strip()).strip()
    return sessions


# The script "cx host screens" runs on a POSIX host: Screen's listing, then the windows of each session (-Q, where the
# Screen has it - an older one answers with its usage and exit 1, so nothing is kept); nothing is installed
SCREENS_SCRIPT = f'''scr() {{ {SCREEN_TOOL} --con- --skip_install -q {SCREEN_QUERY_TIMEOUT} -- "$@"; }}
out=$(scr -ls 2>&1)
printf '%s\\n' '@@ls' "$out"
for s in $(printf '%s\\n' "$out" | sed -n 's/^[[:space:]]*\\([0-9][0-9]*\\.[^[:space:]]*\\)[[:space:]].*/\\1/p'); do
    printf '@@windows %s\\n' "$s"
    if w=$(scr -S "$s" -Q windows 2>/dev/null); then printf '%s\\n' "$w"; fi
done
'''


def ssh_banner_status(addr, port, timeout):
    """
    up | down | refused | no banner | blocked here: the port accepts a connection AND the server sends its
    identification line ("SSH-2.0-..."), which an sshd sends first, at once. A port that accepts and then closes without
    it (a wedged sshd, OpenSSH 9.8+ refusing a penalised source) is "refused"; silence within the timeout is "no banner":
    neither can run a command, and "up" from the TCP accept alone misled (a VM, 2026-10-25: up in the table, every ssh
    reset). "blocked here": THIS machine refused the socket (WinError 10013 - a local firewall, or a VPN that lets only
    chosen programs out): it says nothing about the host.
    """
    try:
        with socket.create_connection((addr, port), timeout=timeout) as s:
            s.settimeout(timeout)
            try:
                data = s.recv(256)
            except socket.timeout:
                return 'no banner'
            except OSError:
                return 'refused'
            return 'up' if data.startswith(b'SSH-') else ('refused' if not data else 'no banner')
    except PermissionError:
        return 'blocked here'
    except OSError:
        return 'down'


def site_label(url):
    """
    The name of a public URL in the tables: its host and the folders before its file, so that the URLs of one site
    tell apart (the user, 2026-10-29) - https://example.org/wiki/index.php/Main_Page is example.org/wiki,
    https://example.org/cm/repo/ is example.org/cm/repo, https://example.org/healthz is example.org (a last part
    without "/" after it is a file or an endpoint, and so is any part with a dot).
    """
    u = urllib.parse.urlsplit(str(url))
    if not u.netloc:
        return str(url)
    folders = []
    parts = u.path.split('/')[1:]
    for i, part in enumerate(parts):
        if '.' in part or i == len(parts) - 1:
            break
        if part:
            folders.append(part)
    return '/'.join([u.netloc] + folders)


def clixml_text(text):
    """
    PowerShell's "#< CLIXML" blocks as plain text: started with -EncodedCommand (every command and script cx sends to
    a PowerShell host) and without a console, PowerShell writes its error, warning and progress records to stderr as
    serialized XML, unreadable in an error line (seen 2026-10-29). The text of each record stays, progress goes, any
    other text is kept as it is; no switch of powershell.exe turns this off.
    """
    if not text or '#< CLIXML' not in text:
        return text
    import html
    out = []
    for line in text.splitlines():
        if line.strip() == '#< CLIXML':
            continue
        if not line.startswith('<Objs '):
            out.append(line)
            continue
        records = ''
        for kind, body in re.findall(r'<S S="(\w+)">(.*?)</S>', line):
            body = re.sub(r'_x([0-9A-Fa-f]{4})_', lambda m: chr(int(m.group(1), 16)), html.unescape(body))
            records += ('WARNING: ' if kind.lower() == 'warning' else '') + body
        out += records.splitlines()
    return '\n'.join(out) + ('\n' if out else '')


def screens_script(quit=None):
    """The screens script, with the session `quit` (a validated screen name) ended before the listing: "@@quit <rc>"
    says whether Screen found it (0) - its shell and whatever ran in it end with it."""
    if not quit:
        return SCREENS_SCRIPT
    head, body = SCREENS_SCRIPT.split('\n', 1)
    return head + f'\nscr -S {shlex.quote(quit)} -X quit >/dev/null 2>&1; printf \'@@quit %s\\n\' "$?"\n' + body


def screen_name(value, default='cx-host'):
    """Bare and explicitly empty flags select the default; omission leaves the ordinary shell."""
    if value is None or value is False or str(value).strip().lower() in ('false', 'no', 'off', '0'):
        return ''
    name = default if value is True or str(value).strip().lower() in ('', 'true', 'yes', 'on', '1') else str(value).strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
        raise ValueError('screen name must be 1-64 letters, digits, underscores or hyphens, starting with a letter or digit')
    return name


def declared_project_states(saved, desc):
    """The saved states of the projects the host still declares: a project taken out of _desc.yaml leaves
    state.yaml at the next probe of the host (before 2026-10-16 its last state stayed there for ever)."""
    declared = (desc or {}).get('projects') or {}
    return {name: st for name, st in ((saved or {}).get('projects') or {}).items() if name in declared}


def system_id_of(raw):
    """The hash recorded as system_id: the first 16 hex digits of sha256(the OS's own id, stripped, lowercase) -
    the same as probe.sh and probe.ps1 print; '' for no id. The raw id itself is never written anywhere."""
    raw = str(raw or '').strip().lower()
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16] if raw else ''


_LOCAL_SYSTEM_ID = None


def local_system_id():
    """
    The system_id of the OS this process runs on (cached): Linux /etc/machine-id (else /var/lib/dbus/machine-id),
    the macOS IOPlatformUUID, the Windows MachineGuid; '' when there is none (a container without a machine-id).
    It stays across reboots and renames of the machine - a hostname does not (the Mac mini: Mac, Grigoris-Mac-mini,
    Mac-001, Mac.lan) - and it is one per OS installation (a WSL distro has its own).
    """
    global _LOCAL_SYSTEM_ID
    if _LOCAL_SYSTEM_ID is not None:
        return _LOCAL_SYSTEM_ID

    raw = ''
    try:
        if sys.platform == 'win32':
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography', 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                raw = str(winreg.QueryValueEx(key, 'MachineGuid')[0])
        elif sys.platform == 'darwin':
            out = subprocess.run(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out.decode('utf-8', errors='replace'))
            raw = m.group(1) if m else ''
        else:
            for p in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
                if os.path.isfile(p):
                    with open(p, encoding='utf-8', errors='replace') as f:
                        raw = f.read().strip()
                    if raw:
                        break
    except Exception:
        raw = ''

    _LOCAL_SYSTEM_ID = system_id_of(raw)
    return _LOCAL_SYSTEM_ID


class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)
        self._key_cache = {}
        self._host_cache = {}
        self._adb_batch = None        # {parent alias (None = here): (devices, reason)} while _status_all runs
        self._adb_locks = {}
        self._adb_lock = threading.Lock()

    ############################################################
    # Commands
    ############################################################

    ############################################################
    def list_(
        self,
        ctx,
        arg1=None,          # host alias, UID or wildcard (default: all)
        tags=None,          # only hosts with these tags (comma-separated, "-tag" excludes)
        machine=None,       # only the hosts of this machine (alias)
        type=None,          # only this type: ssh, wsl, docker, adb
        status=False,       # check liveness (a TCP probe per ssh host, wsl -l, docker inspect, adb devices)
        active=False,       # like --status, and keep only the hosts that are up (or here)
        details=False,      # with --status: what each parent of a moving device answered, under the row
        d=False,            # same as --details
        sort=None,          # accepted for compatibility with the base command
        skip_uids=False,    # accepted for compatibility with the base command
        project=None,      # one named project; omitted: global environment with project sub-rows
        made=False,         # only the instances cMeta made (get-host--docker: made_from in their _desc.yaml)
    ):
        """
        The fleet as a table: host, type, machine, (status), OS, sudo, the Docker and Podman clients
        ("-" = not installed, "(daemon down)" = a Docker client without a running daemon), the cMeta
        engine version, the cMeta AOPS version (the repository ctuninglabs@cmeta-aops; "none" when the
        host has no AOPS) and the date of the last probe.

            cx host ls
            cx host ls --tags=ubuntu
            cx host ls --machine=my-pc
            cx host ls --active                      # only what answers right now
            cx host ls --made --status               # the instances cMeta made (docker, podman), up or stopped

        OS, cMeta and AOPS come from state.yaml, written by "cx host probe" - "-" means never probed.
        """

        con = ctx['control'].get('con', False)

        r = self._select(ctx, arg1, tags, machine, type, project=project)
        if self.cm.catch_error(r): return r
        hosts = r['hosts']
        if made:
            hosts = [h for h in hosts if h['desc'].get('made_from')]

        want_status = status or active
        if want_status:
            self._status_all(ctx, hosts)
            self._project_status_all(ctx, hosts)
            self._public_status_all(hosts)
            if active:
                hosts = [h for h in hosts if h['status'] in ('up', 'here')]

        rows = []
        for h in hosts:
            rows.append(self._row(h, want_status))

        if con:
            show_status = want_status or any(self._retired(h) for h in hosts)
            cols = LIST_COLUMNS if show_status else [c for c in LIST_COLUMNS if c != 'STATUS']
            show = bool(details) or bool(d)
            self._print_table(cols, rows, details=self._status_details(hosts) if want_status and show else None,
                              projects=self._project_details(hosts, cols))
            if not hosts:
                print('no hosts' + (' match' if (arg1 or tags or machine or type or active) else ' yet - add one with "cx host add <repo>:<alias>" and write its _desc.yaml'))

        return {'return': 0, 'hosts': rows}

    ############################################################
    def status_(
        self,
        ctx,
        arg1=None,          # host alias, UID or wildcard (default: all)
        tags=None,          # only hosts with these tags
        machine=None,       # only the hosts of this machine
        type=None,          # only this type
        timeout=DEFAULT_STATUS_TIMEOUT,          # seconds per TCP probe (an ssh host)
        cmd_timeout=DEFAULT_STATUS_CMD_TIMEOUT,  # seconds per check that runs a command (adb devices, docker inspect, wsl -l), ssh included
        details=False,      # add the time every check took, and what each parent of a moving device answered
        d=False,            # same as --details
        project=None,      # check only this project's server below each selected host
        made=False,         # only the instances cMeta made (get-host--docker: made_from in their _desc.yaml)
    ):
        """
        Is each host reachable right now? "here" = this machine, "up"/"down" for the rest,
        "missing" for a container or distro that does not exist (yet), "via X down" when the parent is off,
        "timeout" when a check did not answer within --cmd_timeout. A device that moves between machines
        is "up" with "via <parent>" in ADDRESS, or "down" when no parent sees it. One line per host;
        -d adds a TIME column and, under a moving device, what each parent answered and how long it took.

            cx host status
            cx host status lab-laptop-ubuntu
            cx host status -d                      # the time every check took, and what each parent of a moving device said
            cx host status --cmd_timeout=120       # a thorough check of hosts that are slow to answer

        All hosts are checked at once, and so are the candidate parents of a moving device; the table
        appears when the slowest check answers or times out. A cold fleet (peers asleep, adb servers not
        started, caches cold) answers in tens of seconds the first time and in a few seconds after that.
        """

        con = ctx['control'].get('con', False)
        verbose = bool(details) or bool(d)       # not the global -v: CMETA_VERBOSE is set in the user's environment

        r = self._select(ctx, arg1, tags, machine, type, project=project)
        if self.cm.catch_error(r): return r
        hosts = r['hosts']
        if made:
            hosts = [h for h in hosts if h['desc'].get('made_from')]

        self._status_all(ctx, hosts, timeout=int(timeout), cmd_timeout=int(cmd_timeout))
        self._project_status_all(ctx, hosts, timeout=int(timeout), cmd_timeout=int(cmd_timeout))
        self._public_status_all(hosts, timeout=int(timeout))

        rows = [self._row(h, True) for h in hosts]
        if con:
            columns = ['HOST', 'TYPE', 'OS', 'STATUS', 'ADDRESS'] + (['TIME'] if verbose else [])
            table = []
            for h in hosts:
                line = [h['alias'], h['type'], self._os_short(h), h['status'], self._address_text(h)]
                if verbose:
                    line.append(f'{h.get("status_time", 0):.1f}s')
                table.append(line)
            self._print_table(columns, table, details=self._status_details(hosts) if verbose else None,
                              projects=self._project_details(hosts, columns))

        return {'return': 0, 'hosts': rows}

    ############################################################
    def probe_(
        self,
        ctx,
        arg1=None,          # host alias, UID or wildcard (default: all)
        tags=None,          # only hosts with these tags
        machine=None,       # only the hosts of this machine
        type=None,          # only this type
        timeout=DEFAULT_PROBE_TIMEOUT,    # seconds per host
        project=None,      # probe this environment; omitted: global and all declared projects
    ):
        """
        Ask every reachable host what it is (OS, kernel, GPU, Python, uv, cx, cMeta version and home,
        disk, every repository under <cMeta home>/repos with its git branch/commit and _cmr version)
        and write the answer to the host's state.yaml. Declared facts stay in _desc.yaml; state.yaml
        is observed only.

            cx host probe                    # the whole fleet, hosts that are down are skipped and reported
            cx host probe lab-mac-mini-macos # one host: being down is an error
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        r = self._select(ctx, arg1, tags, machine, type, project=project)
        if self.cm.catch_error(r): return r
        hosts = r['hosts']
        if not hosts:
            return self.cm.error(f'no host matches "{arg1}"' if arg1 else 'no hosts to probe')

        self._status_all(ctx, hosts)

        explicit = self._is_explicit(arg1, hosts)

        results = {}
        for h in hosts:
            alias = h['alias']
            if not self._usable(h):
                if explicit:
                    return self.cm.error(f'host "{alias}" is {h["status"]} - nothing to probe')
                results[alias] = {'skipped': h['status']}
                if con: print(f'{alias:32} skipped ({h["status"]})')
                continue

            t0 = time.monotonic()
            r = self._probe_one(ctx, h, int(timeout), verbose)
            if r['return'] > 0:
                if explicit: return r
                results[alias] = {'error': r['error']}
                if con: print(f'{alias:32} ERROR: {r["error"]}')
                continue

            st = r['state']
            if not project:
                for name in (h['desc'].get('projects') or {}):
                    pr = self._project_host(h, name)
                    if pr['return'] > 0: return pr
                    pr = self._probe_one(ctx, pr['host'], int(timeout), verbose)
                    if pr['return'] > 0: return pr
                st = self._read_yaml(os.path.join(h['path'], STATE_FILE))
                h['state'] = st
            results[alias] = st
            if con:
                repos = st.get('repos', {})
                print(f'{alias:32} {st.get("os", "?"):28} cMeta {st.get("cmeta_version") or "-":9} '
                      f'aops {st.get("aops_version") or "-":8} {len(repos)} repos  ({time.monotonic() - t0:.1f}s)')

        return {'return': 0, 'probed': results}

    ############################################################
    def connect_(self, ctx, arg1=None, endpoint=None, serial=None, pair: bool = False,
                 pairing_endpoint=None, keepalive: bool = False, period=10, duration=0,
                 timeout=15, instructions: bool = False):
        """Connect an Android fleet host over Wi-Fi, optionally pair or keep reconnecting.

        cx host connect <watch> --pair       # adb asks for the watch PIN in this terminal
        cx host connect <watch> --endpoint=IP:port
        cx host connect <watch> --keepalive  # foreground loop; stop with Ctrl+C

        Runs on this host's declared local ADB controller. Pairing credentials stay with
        adb; observed device identity and connection endpoint live in the host state.
        """
        if not arg1: return self.cm.error('which Android host? cx host connect <host>')
        r = self._get_host(ctx, arg1)
        if self.cm.catch_error(r): return r
        h = r['host']
        if h['type'] != 'adb': return self.cm.error('connect currently supports adb hosts')
        parents = h.get('via_list') or []
        if parents:
            local_parent = False
            for alias in parents:
                r = self._get_host(ctx, alias)
                if r.get('return') == 0 and self._here(r['host']):
                    local_parent = True
                    break
            if not local_parent:
                return self.cm.error('run connect on a declared ADB controller: ' + ', '.join(parents))
        r = self.cm.access({'category': self.cmeta['uses_categories']['task'], 'command': 'run',
                            'arg1': self.cmeta['uses_artifacts']['task::keep-adb-connection-alive'],
                            'ctx': ctx, 'host': h['alias'] + ',' + h['uid'], 'ip': endpoint,
                            'serial': serial or '', 'once': not keepalive, 'pair': pair,
                            'pairing_endpoint': pairing_endpoint or '', 'period': period,
                            'duration': duration, 'timeout': timeout, 'instructions': instructions})
        self._host_cache.pop(h['alias'], None)
        return r

    ############################################################
    def run_(
        self,
        ctx,
        arg1=None,          # host alias (or the command, when --tags/--machine/--type/--all select the hosts)
        arg2=None,          # the command to run there (quote it)
        tags=None,          # run on every host with these tags
        machine=None,       # run on every host of this machine
        type=None,          # run on every host of this type
        all=False,          # run on every host
        script=None,        # a local script file sent to the host's shell on stdin instead of a command
        timeout=None,       # seconds
        capture=False,      # return the output instead of streaming it to the terminal
        raw=False,          # do not wrap the command in the host's shell (ssh/docker: as given)
        interactive=False,  # a terminal for the command (ssh -t / docker exec -it): it can ask questions; needs a terminal here
        project=None,      # named environment; omitted: the host's global environment
        unparsed=None,      # the command as the words after "--" (cx host run <host> -- <command>)
        screen=None,        # keep the command in GNU Screen; bare: cx-host, or --screen=<name>
        screen_title=None,  # title of a new screen window (task delegation supplies its project)
    ):
        """
        Run a command on a host (or on a selection of hosts), through its driver: locally when the host
        is this machine, else ssh / wsl.exe / docker exec / adb shell, wrapped in the host's login shell.

            cx host run lab-laptop-ubuntu "cx --version"
            cx host run lab-laptop-ubuntu -- ls -la /tmp        # the words after "--", cMeta parses none of them
            cx host run --tags=ubuntu "uname -a"
            cx host run lab-thinkpad-ubuntu --script=check.sh
            cx host run lab-thinkpad-ubuntu "cx task run test-python" --interactive   # a terminal there: the command can ask

        The command is passed through the local shell, then ssh, then the remote shell: keep it simple,
        and put anything with quotes of its own in a script (--script). After "--" the words are joined
        with spaces; a word that holds a space gets double quotes (one word for bash and PowerShell alike).
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        try:
            screen = screen_name(screen)
        except ValueError as e:
            return self.cm.error(str(e))
        if screen:
            if capture or script or timeout or raw or bool(tags or machine or type or all):
                return self.cm.error('--screen needs one interactive host, without --capture, --script, --timeout or --raw')
            if not self._screen_terminal():
                return self.cm.error('--screen needs a terminal here; use --on_detach for an unattended task')
            interactive = True

        # The words after "--" are the command (not with a command given as an argument too)
        if unparsed:
            if arg2 is not None or (bool(tags or machine or type or all) and arg1 is not None):
                return self.cm.error('the command is given twice: as an argument and after "--" - keep one')

            words = [str(w) for w in unparsed]
            arg2 = ' '.join(f'"{w}"' if (any(c.isspace() for c in w) and '"' not in w) else w for w in words)

            if bool(tags or machine or type or all):
                arg1, arg2 = arg2, None

        selection = bool(tags or machine or type or all)
        if selection and arg2 is None:
            cmd, arg1 = arg1, None
        else:
            cmd = arg2

        if not cmd and not script:
            return self.cm.error('nothing to run: cx host run <host> "<command>" (or --script=<file>)')
        if not selection and not arg1:
            return self.cm.error('no host given: cx host run <host> "<command>", or select hosts with --tags/--machine/--type/--all')
        if interactive and (capture or script):
            return self.cm.error('--interactive gives the command a terminal: not with --capture or --script')

        r = self._select(ctx, arg1, tags, machine, type, project=project)
        if self.cm.catch_error(r): return r
        hosts = r['hosts']
        if not hosts:
            return self.cm.error(f'no host matches "{arg1}"' if arg1 else 'no hosts match the selection')

        stdin_file = None
        if script:
            if not os.path.isfile(script):
                return self.cm.error(f'script not found: {script}')
            stdin_file = os.path.abspath(script)

        outputs = {}
        failed = 0
        for h in hosts:
            host_cmd = cmd
            if screen:
                r = self._screen_command(h, host_cmd, screen, screen_title, ctx['control'].get('quiet', False))
                if self.cm.catch_error(r): return r
                host_cmd = r['cmd']
            if stdin_file:
                r = self._cmd_stdin(ctx, h, stdin_file)
            else:
                r = self._cmd_run(ctx, h, host_cmd, raw=raw, interactive=bool(interactive))
            if self.cm.catch_error(r): return r

            if con and (len(hosts) > 1 or verbose):
                print('')
                print(f'=== {h["alias"]} ({self._address_text(h)})')

            rr = self._run_local(r['cmd'], capture=capture, timeout=timeout, con=con, verbose=verbose)
            outputs[h['alias']] = {'returncode': rr.get('returncode'), 'stdout': rr.get('stdout', ''),
                                   'stderr': rr.get('stderr', '')}
            if rr.get('returncode', 0) != 0:
                failed += 1
                if con:
                    print(f'{h["alias"]}: exit code {rr.get("returncode")}' +
                          (f' - {rr.get("stderr", "").strip()}' if capture and rr.get('stderr') else ''))

        if con and capture:
            for alias, o in outputs.items():
                if len(hosts) > 1:
                    print(f'=== {alias}')
                print(o['stdout'].rstrip())

        if failed and len(hosts) == 1:
            o = outputs[hosts[0]['alias']]
            return {'return': 1, 'error': f'command failed on {hosts[0]["alias"]} (exit code {o["returncode"]})',
                    'outputs': outputs}

        return {'return': 0, 'outputs': outputs, 'failed': failed}

    ############################################################
    def ssh_(
        self,
        ctx,
        arg1=None,          # host alias
        x11=False,          # ssh -Y: X11 forwarding (or "access: x11: true" in the host's _desc.yaml); on Windows DISPLAY=localhost:0.0 unless set
        forward=None,       # ssh -L: local ports to forward to the host, e.g. --forward=1455 or --forward=8080:80,5000
        dry_run=False,      # print the command instead of opening the shell
        screen=None,        # persistent GNU Screen shell: bare = cx-host, or --screen=<name>
    ):
        """
        Open an interactive shell on a host: ssh, wsl.exe -d, docker exec -it, adb shell.

            cx host ssh lab-mac-mini-macos               (also: cx host shell / login)
            cx host ssh lab-thinkpad-ubuntu --x11       # a remote GUI program shows up here
            cx host ssh lab-thinkpad-ubuntu --forward=1455   # a login page the host serves on localhost:1455 opens in this browser
            cx host ssh lab-thinkpad-ubuntu --screen         # create/reconnect cx-host; SSH may disconnect
            cx host ssh lab-thinkpad-ubuntu --screen=work    # a separate shell; exit ends its last window
        """

        con = ctx['control'].get('con', False)

        if not arg1:
            return self.cm.error('which host? cx host ssh <host>')

        r = self._get_host(ctx, arg1)
        if self.cm.catch_error(r): return r
        h = r['host']

        try:
            screen = screen_name(screen)
        except ValueError as e:
            return self.cm.error(str(e))
        cmd = None
        if screen:
            if not dry_run and not self._screen_terminal():
                return self.cm.error('--screen needs a terminal here')
            r = self._screen_command(h, None, screen, quiet=ctx['control'].get('quiet', False), x11=bool(x11))
            if self.cm.catch_error(r): return r
            cmd = r['cmd']

        if x11 and os.name == 'nt' and not os.environ.get('DISPLAY'):
            # the Windows OpenSSH client forwards X11 only with DISPLAY set: the X server of the laptop (VcXsrv, X410)
            os.environ['DISPLAY'] = 'localhost:0.0'
            if con:
                print('cMeta info: DISPLAY=localhost:0.0 for the X11 forwarding (an X server must run here)')
        r = self._cmd_run(ctx, h, cmd, interactive=True, x11=bool(x11), forwards=self._csv(forward))
        if self.cm.catch_error(r): return r

        if r.get('here') and not screen:
            if con: print(f'{h["alias"]} is this machine - opening a local shell')
            cmd = 'cmd.exe' if os.name == 'nt' else os.environ.get('SHELL', '/bin/sh')
        else:
            cmd = r['cmd']

        if dry_run:
            if con: print(cmd)
            return {'return': 0, 'cmd': cmd, 'dry_run': True}

        if con and ctx['control'].get('verbose', False):
            print(f'RUN: {cmd}')

        rc = subprocess.call(cmd, shell=True)
        return {'return': 1 if screen and rc != 0 else 0, 'returncode': rc}

    @staticmethod
    def _screen_terminal():
        try:
            return sys.stdin.isatty() and sys.stdout.isatty()
        except (AttributeError, ValueError):
            return False

    ############################################################
    def key_(
        self,
        ctx,
        arg1=None,          # host alias, or a reference <category>::<artifact>/<file>
    ):
        """
        The ssh key cx uses to reach a host, as THIS machine finds it, and the public key beside it: the host's
        "access: key" - a reference <category>::<artifact>/<file> into a private repository, found through the
        artifact when it is here, else through the copy a secret holds (cx secret which), else ~/.ssh - or a path.
        A reference in place of the host is resolved the same way. Prints paths, never a key. It is what
        "cx task run run-openssh --host=<host>" allows: a machine serves the fleet with the key the fleet reaches it with.

            cx host key lab-laptop-ubuntu
            cx host key fgg.crypt::ssh-x/2026/id_ed25519
        """

        con = ctx['control'].get('con', False)

        ref = str(arg1 or '').strip()
        if not ref:
            return self.cm.error('cx host key <host> | <category>::<artifact>/<file>')

        # The declared key of the host, or the reference as given
        if '::' in ref:
            key = ref
        else:
            r = self._select(ctx, ref)
            if self.cm.catch_error(r): return r
            hosts = r['hosts']
            if len(hosts) != 1:
                return self.cm.error(f'no host matches "{ref}"' if not hosts else f'"{ref}" matches {len(hosts)} hosts')
            key = (hosts[0]['desc'].get('access') or {}).get('key')
            if not key:
                return self.cm.error(f'host {hosts[0]["alias"]} declares no access.key (ssh uses its default keys for it)')

        r = self._key_path(key)
        if self.cm.catch_error(r): return r
        path = r['path']
        public = path if path.endswith('.pub') else (path + '.pub' if os.path.isfile(path + '.pub') else None)

        if con:
            print(f'key: {path}')
            print(f'public key: {public or "none beside it"}')
        return {'return': 0, 'ref': str(key), 'path': path, 'public': public}

    ############################################################
    def screens_(
        self,
        ctx,
        arg1=None,          # host alias (or a selection: --tags / --machine / --type)
        tags=None,          # a selection by tags
        machine=None,       # the hosts of a machine
        type=None,          # ssh | wsl | docker
        project=None,       # a named environment of the host (its cx)
        quit=None,          # end the session of this name there first (screen -S <name> -X quit: its shell and the run in it), then list
    ):
        """
        The GNU Screen sessions on a host - the persistent terminals of "cx host ssh --screen" and "--on_screen", and
        any other screen of the host's user: name, state, start time where Screen gives it, the titles of the windows
        (a run-ai terminal shows its project; Screen 4.2+ answers -Q, an older one lists none). Read only: nothing is
        changed or installed on the host - no Screen there means no sessions. With --quit=<name> the session of that
        name is ended first (what runs in it dies with its shell), then what is left is listed.

            cx host screens lab-thinkpad-ubuntu
            cx host screens --tags=ubuntu
            cx host screens lab-thinkpad-ubuntu --quit=ai1
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        if not (arg1 or tags or machine or type):
            return self.cm.error('which host? cx host screens <host> (or --tags/--machine/--type)')
        if quit is not None:
            try:
                quit = screen_name(quit, default='')
            except ValueError as e:
                return self.cm.error(str(e))
            if not quit:
                return self.cm.error('--quit=<name>: which screen session?')

        r = self._select(ctx, arg1, tags, machine, type, project)
        if self.cm.catch_error(r): return r
        hosts = r['hosts']
        if not hosts:
            return self.cm.error(f'no host matches "{arg1}"' if arg1 else 'no hosts match')

        import tempfile
        script = os.path.join(tempfile.gettempdir(), f'cmeta-host-screens-{os.getpid()}.sh')
        with open(script, 'w', encoding='utf-8', newline='\n') as f:
            f.write(screens_script(quit))

        screens, errors, ended = {}, {}, {}
        try:
            for h in hosts:
                shell = self._shell(h).strip()
                if h['type'] == 'adb' or shell in ('powershell', 'pwsh', 'cmd', 'none', 'raw') or (self._here(h) and os.name == 'nt'):
                    errors[h['alias']] = 'not a POSIX host: no GNU Screen there'
                    continue
                r = self._cmd_stdin(ctx, h, script)
                if r['return'] > 0:
                    errors[h['alias']] = r['error']
                    continue
                rr = self._run_local(r['cmd'], capture=True, timeout=180, con=False, verbose=verbose)
                if rr.get('returncode') not in (0, None) and '@@ls' not in (rr.get('stdout') or ''):
                    errors[h['alias']] = (rr.get('stderr') or rr.get('stdout') or '').strip()[-300:] or f'exit code {rr.get("returncode")}'
                    continue
                screens[h['alias']] = parse_screens(rr.get('stdout') or '')
                if quit:
                    m = re.search(r'^@@quit (\d+)', rr.get('stdout') or '', re.M)
                    ended[h['alias']] = bool(m) and m.group(1) == '0'
        finally:
            try:
                os.remove(script)
            except OSError:
                pass

        if con:
            many = len(hosts) > 1
            for h in hosts:
                alias = h['alias']
                if quit and alias in ended:
                    print(f'{alias}: screen "{quit}" ' + ('ended' if ended[alias] else 'not found (nothing ended)'))
                if alias in errors:
                    print(f'{alias}: {errors[alias]}')
                elif not screens.get(alias):
                    print(f'{alias}: no screens')
                else:
                    if many:
                        print(f'=== {alias}')
                    rows = [('SCREEN', 'PID', 'STATE', 'STARTED', 'WINDOWS')] + \
                           [(s['name'], str(s['pid']), s['state'] or '-', s['started'] or '-', s['windows'] or '-') for s in screens[alias]]
                    widths = [max(len(row[i]) for row in rows) for i in range(4)]
                    for row in rows:
                        print('  '.join(row[i].ljust(widths[i]) for i in range(4)) + '  ' + row[4])

        if errors and len(hosts) == 1:
            return self.cm.error(f'{hosts[0]["alias"]}: {errors[hosts[0]["alias"]]}')
        result = {'return': 0, 'screens': screens, 'errors': errors}
        if quit:
            result['ended'] = ended
        return result

    def _screen_command(self, h, cmd, name, title=None, quiet=False, x11=False):
        """Screen owns the shell/command; reconnecting resumes it without sending another command."""
        shell = self._shell(h).strip()
        if h['type'] == 'adb' or shell in ('powershell', 'pwsh', 'cmd', 'none', 'raw') or (self._here(h) and os.name == 'nt'):
            return self.cm.error('--screen needs a POSIX host with GNU Screen (Linux/macOS, WSL or a container)')

        shell_words = shlex.split(shell)
        if cmd is not None:
            shell_words += ['-c', cmd]
        title = title or ('shell' if cmd is None else cmd)
        # X11: a window's shell keeps the DISPLAY of the login that made it, so a later login with --x11 could not
        # open a window from inside (2026-10-26). The attach writes the login's DISPLAY to ~/.cmeta-screen-display and
        # a window made by cMeta sources it at every prompt; an older window takes it with ". ~/.cmeta-screen-display".
        shell_words = ['env', 'PROMPT_COMMAND=' + SCREEN_DISPLAY_HOOK] + shell_words
        args = ['-S', name, '-d', '-R', '-t', title] + shell_words
        # Show the actual existing title (including a run-ai project), then let Screen attach or create.
        # The new title/command are ignored by Screen when a session already exists.
        # Any Screen works: -Q (Screen 4.2+) only lists the windows first - an older Screen answers it with its usage
        # and exit 1, so nothing is listed, and -S/-d/-R/-t work the same (checked with 4.00.03, 4.08, 4.09, 5.0).
        # The query asks the Screen the session runs with (cMeta's choice, never installed for it): the first one on
        # the PATH can be another (a Mac: Apple's 4.00.03 in /usr/bin before Homebrew's). It has a time limit: Screen
        # 5.0 answers -Q through the attached display, so a session still attached to a terminal nobody reads (a
        # connection that died silently, a closed laptop) would keep it waiting - then nothing is listed
        query = (f'if cmeta_screen_windows=$({SCREEN_TOOL} --con- --skip_install -q {SCREEN_QUERY_TIMEOUT} -- -S {shlex.quote(name)} -Q windows 2>/dev/null); '
                 'then printf \'%s\\n\' "$cmeta_screen_windows"; fi')
        launch = f'{SCREEN_TOOL} --con-' + (' -q' if quiet else '') + ' -- ' + ' '.join(shlex.quote(w) for w in args)
        message = f'cMeta info: screen "{name}" on {h["alias"]}; existing windows (if any):'
        if x11:
            message += ' (X11: a window made before today takes this login\'s display with: . ~/.cmeta-screen-display)'
        return {'return': 0, 'cmd': f'printf \'%s\\n\' {shlex.quote(message)}; {query}; {SCREEN_DISPLAY_SAVE}exec {launch}'}

    ############################################################
    def restart_(
        self,
        ctx,
        arg1=None,          # host alias (one host)
        yes=False,          # do not ask (also implied by -q)
        wait=True,          # wait until the host answers again (--no-wait: return at once)
        timeout=600,        # seconds to wait for it
        skip_after=False,   # do not run the host's "commands: after_restart"
        skip_check=False,   # do not wait for the host's declared projects afterwards
        check_timeout=300,  # seconds to wait for every project's server and public URLs to answer
        dry_run=False,      # print what would run, restart nothing
    ):
        """
        Reboot a host - after a y/N question unless --yes or -q - then wait until it is back and run its
        "commands: after_restart" (servers to bring up). ssh hosts: "sudo -n shutdown -r now" (Windows:
        "shutdown /r /t 5"); a WSL distro: wsl -t + start; a container: docker restart; adb: adb reboot;
        or the host's own "commands: restart". A host with "projects" is checked like "cx host status" does - each
        server on the host, its public URLs from here - just before the restart and after it, until everything
        that answered before answers again or --check_timeout; one that does not makes the restart fail, a project
        that did not answer before (a server started on demand only) is only reported (--skip_check: no check).

            cx host restart lab-laptop-ubuntu
            cx host restart my-azure-vm-ubuntu --yes      # then its web server comes up again
            cx host restart my-pc-wsl2 --dry_run
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        if not arg1:
            return self.cm.error('which host? cx host restart <host>')

        r = self._get_host(ctx, arg1)
        if self.cm.catch_error(r): return r
        h = r['host']
        alias = h['alias']
        t = h['type']
        acc = h['desc'].get('access') or {}
        cmds = h['desc'].get('commands') or {}
        if not isinstance(cmds, dict):
            return self.cm.error(f'host "{alias}": "commands" must be a mapping with up / down / restart / after_restart '
                                 f'(a bare list means a key line is missing or commented out)')

        h['status'] = self._status(ctx, h)
        if not self._usable(h):
            return self.cm.error(f'host "{alias}" is {h["status"]} - nothing to restart')

        # What restarts it
        here = h['status'] == 'here'
        local_cmd = None          # run on this machine as it is
        host_cmd = None           # run on the host through its driver
        if cmds.get('restart'):
            local_cmd = str(cmds['restart'])
        elif t == 'ssh':
            shell = self._shell(h).strip()
            host_cmd = 'shutdown /r /t 5' if shell in ('powershell', 'pwsh', 'cmd') else 'sudo -n shutdown -r now'
        elif t == 'wsl':
            distro = str(acc.get('distro') or '')
            local_cmd = f'wsl.exe -t {distro} && wsl.exe -d {distro} -- true' if distro else 'wsl.exe --shutdown && wsl.exe -- true'
        elif t == 'docker':
            local_cmd = f'{self._engine(h)} restart {acc.get("container") or alias}'
            if h.get('via'):
                r = self._get_host(ctx, h['via'])
                if r['return'] > 0: return r
                if not self._here(r['host']):
                    r = self._cmd_run(ctx, r['host'], local_cmd)
                    if r['return'] > 0: return r
                    local_cmd = r['cmd']
        elif t == 'adb':
            parent = None
            if len(h.get('via_list') or []) > 1:
                self._resolve_via(ctx, h)
            if h.get('via'):
                r = self._get_host(ctx, h['via'])
                if r['return'] > 0: return r
                if not self._here(r['host']):
                    parent = r['host']
            local_cmd = self._adb_cmd(parent, (f'-s {acc["serial"]} ' if acc.get('serial') else '') + 'reboot')
            if parent is not None:
                r = self._cmd_run(ctx, parent, local_cmd)
                if r['return'] > 0: return r
                local_cmd = r['cmd']
        else:
            return self.cm.error(f'unknown type "{t}"')

        if host_cmd is not None:
            r = self._cmd_run(ctx, h, host_cmd)
            if self.cm.catch_error(r): return r
            local_cmd = r['cmd']

        after = cmds.get('after_restart') or []
        if isinstance(after, str): after = [after]

        if dry_run:
            if con:
                print(f'{alias}: would run  {local_cmd}')
                for c in after:
                    print(f'{alias}: then on the host  {c}')
            return {'return': 0, 'cmd': local_cmd, 'after_restart': after, 'dry_run': True}

        if not yes and not quiet:
            what = 'THIS machine' if here else self._address_text(h)
            try:
                answer = input(f'Restart {alias} ({what})' + (f' and then run {len(after)} command(s)' if after else '') + '? [y/N] ')
            except EOFError:
                answer = ''
            if answer.strip().lower() not in ('y', 'yes'):
                if con: print('cancelled')
                return {'return': 0, 'result': 'cancelled'}

        # What answers NOW must answer after the restart: the projects' checks as "cx host status" makes them. A
        # project that does not answer before (a server started on demand only, or one already broken) is reported
        # afterwards, not required (2026-10-29: a host's on-demand cserver would have failed every restart)
        required = None
        if (h['desc'].get('projects') or {}) and not skip_check and not skip_after and not here:
            self._project_status_all(ctx, [h])
            self._public_status_all([h])
            required = {k for k, s in self._project_checks(h).items()
                        if self._check_answers(k, s) or s == 'check failed' or str(s).startswith('host ')}

        # The boot an ssh host runs NOW: "back" below means a new boot answers, not the old one still answering while
        # it shuts down (2026-10-13: a VM took more than 20 s to drop ssh, "back" came at the first poll, the
        # after_restart command started the servers on the old boot, and the reboot killed them seconds later)
        stamp_before = self._boot_stamp(ctx, h) if (t == 'ssh' and not here) else ''

        if con:
            print(f'{alias}: {local_cmd}')
        rr = self._run_local(local_cmd, capture=True, con=con, verbose=verbose, timeout=120)
        rc = rr.get('returncode', 0)
        # ssh reports 255 when the connection drops as the host goes down - that is the normal outcome
        if rc not in (0, 255) and t != 'ssh':
            return self.cm.error(f'restart command failed (exit code {rc}): {(rr.get("stderr") or "").strip()}')

        if here:
            return {'return': 0, 'result': 'restarting this machine'}

        result = {'return': 0, 'result': 'restart requested', 'after_restart': []}
        if not wait:
            return result

        if con: print(f'{alias}: waiting for it to come back (up to {timeout}s) ...')
        time.sleep(5 if t in ('wsl', 'docker') else 20)
        t_start = time.monotonic()
        t_end = t_start + int(timeout)
        back = False
        seen_down = False
        while time.monotonic() < t_end:
            if self._status(ctx, h) != 'up':
                seen_down = True
            elif t != 'ssh':
                back = True
                break
            elif stamp_before:
                # The same stamp is the old boot still answering; no stamp yet is a boot that cannot run a command yet
                if self._boot_stamp(ctx, h) not in ('', stamp_before):
                    back = True
                    break
            elif seen_down or time.monotonic() - t_start > RESTART_DOWN_WAIT:
                # No stamp to compare: it went away and came back, or never seemed to go away within the time a
                # shutdown can take (a host that rebooted faster than the polling)
                back = True
                break
            time.sleep(5 if t in ('wsl', 'docker') else 10)
        if not back:
            return {'return': 1, 'error': f'{alias} did not come back within {timeout}s', 'result': 'restart requested'}
        result['result'] = 'restarted and back'
        if con: print(f'{alias}: back')

        if after and not skip_after:
            for c in after:
                r = self._cmd_run(ctx, h, c)
                if self.cm.catch_error(r): return r
                if con:
                    print('')
                    print(f'AFTER RESTART ({alias}): {c}')
                rr = self._run_local(r['cmd'], capture=not verbose, con=con, verbose=verbose, timeout=600)
                rc = rr.get('returncode', 0)
                result['after_restart'].append({'cmd': c, 'returncode': rc})
                if con and rc != 0:
                    print(f'WARNING: "{c}" on {alias} returned {rc}: {(rr.get("stderr") or "").strip()[-300:]}')

        # The servers: a launcher that detaches returns 0 at once, so its exit code says nothing about them
        # (2026-10-28: a VM came back, its start script returned 0, and a site's backend failed at every start -
        # unseen for two days). Wait for what answered before the restart, as "cx host status" checks it.
        failed = []
        if required is not None:
            h['status'] = 'up'
            failed = self._wait_projects(ctx, h, con, int(check_timeout), required)
            result['projects'] = self._project_rows(h)

        self._refresh_state(ctx, h, con)            # the uptime, the versions: state.yaml says what is there now
        if failed:
            result.update({'return': 1, 'error': f'{alias} is back, but not every project that answered before the '
                                                 f'restart answers after {int(check_timeout)}s: ' + ', '.join(failed)})
        return result

    def _project_checks(self, h):
        """The checks of the host's declared projects as the last check left them: {('server', project): status,
        ('url', project, url): status}."""
        checks = {}
        for p in self._project_rows(h):
            checks[('server', p['alias'])] = p['status']
            for x in p['public']:
                checks[('url', p['alias'], x['url'])] = x.get('status', '')
        return checks

    @staticmethod
    def _check_answers(key, status):
        """A server answers when "up" (a project without a server URL, or a retired one, has nothing to answer);
        a public URL when it "works"."""
        return status in ('up', 'not configured', 'retired') if key[0] == 'server' else status == 'works'

    def _wait_projects(self, ctx, h, con, timeout, required=None):
        """After a restart: check the host's declared projects - each server on the host, its public URLs from
        here - until every check of `required` (all of them when None) answers or the time is up, then print them.
        Returns the projects with a required check that does not answer; the others are printed, not counted."""
        t_end = time.monotonic() + timeout
        while True:
            self._project_status_all(ctx, [h])
            self._public_status_all([h])
            now = self._project_checks(h)
            failing = [k for k, s in now.items() if not self._check_answers(k, s) and (required is None or k in required)]
            failed = list(dict.fromkeys(k[1] for k in failing))
            if not failed or time.monotonic() >= t_end:
                break
            if con:
                print(f'{h["alias"]}: waiting for {len(failed)} project(s): {", ".join(failed)}')
            time.sleep(15)

        if con:
            def note(key, status):
                return '' if self._check_answers(key, status) or required is None or key in required \
                    else '  (did not answer before the restart either: not required)'
            print('')
            print(f'PROJECTS ({h["alias"]}):')
            for p in self._project_rows(h):
                print(f'  {p["alias"]:36} {p["status"]:12} {(p["server"] or {}).get("url") or ""}'
                      + note(('server', p['alias']), p['status']))
                for x in p['public']:
                    print(f'      {x.get("status", ""):10} {x["url"]}' + (f'  (HTTP {x["http_status"]})' if x.get('http_status') else '')
                          + note(('url', p['alias'], x['url']), x.get('status', '')))
        return failed

    ############################################################
    def up_(
        self,
        ctx,
        arg1=None,          # host alias, UID or wildcard
        tags=None,          # or a selection
        machine=None,
        type=None,
    ):
        """
        Start a host that can be started from here: a WSL distro, a container (created from its image on
        the first start), or anything with a declared "commands: up" (a cloud VM: az vm start ...).
        An ssh host without one is reported, not started.

            cx host up my-pc-wsl2       (also: cx host start)
        """

        return self._up_down(ctx, 'up', arg1, tags, machine, type)

    ############################################################
    def down_(
        self,
        ctx,
        arg1=None,          # host alias, UID or wildcard
        tags=None,          # or a selection
        machine=None,
        type=None,
    ):
        """
        Stop a host that can be stopped from here: a WSL distro (wsl -t), a container (docker stop), or
        anything with a declared "commands: down".

            cx host down my-pc-wsl2     (also: cx host stop)
        """

        return self._up_down(ctx, 'down', arg1, tags, machine, type)

    ############################################################
    def sync_(
        self,
        ctx,
        arg1=None,          # host alias, UID or wildcard (default: every host that declares a sync)
        tags=None,          # or a selection
        machine=None,
        type=None,
        repos=None,         # only these repositories (comma-separated names from the host's sync list)
        resync=False,       # bisync: rebuild the baseline (first run of a pair, or after "Must run --resync")
        resync_mode='newer',  # with --resync, which copy wins where both sides have a file: newer | path1 (this machine) | path2 (the host) | older | larger | smaller
        unlock=False,       # bisync: drop a stale lock left by a cancelled run
        dry_run=False,      # show what would change, change nothing (rclone --dry-run; git fetch only)
        skip_after=False,   # do not run the host's "sync: after" commands (e.g. cx --reindex)
        backup=False,       # keep what this run overwrites or deletes: .cmeta-sync-backups/<repository>/<run id>/ beside the repos folder of each side
        project=None,      # named environment; omitted: the host's global environment
        skip_check=False,   # do not compare the two sides after the sync (the check is on by default: rclone check, name and size)
        retries=2,          # how many times a transient failure of a repository is tried again
        pause=True,         # on problems, wait for Enter at the end when a person is at the terminal (never with -q; --pause- turns it off)
    ):
        """
        Bring a host's repositories up to date, the way its _desc.yaml declares: "bisync" (two-way, rclone
        over ssh, the user's _8-bisync scripts), "copy" (one-way local -> host, never deletes), "git"
        (git pull --ff-only on the host's own clone), per repository or by the host's default.

            cx host sync                                  # every reachable host that declares a sync
            cx host sync my-azure-vm-ubuntu      # one host (being down is an error)
            cx host sync --tags=ubuntu --dry_run
            cx host sync lab-thinkpad-ubuntu --repos=ctuninglabs@cmeta-aops --resync --resync_mode=path1

        A few directories only, one-way: "cx host push".
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        r = self._select(ctx, arg1, tags, machine, type, project=project)
        if self.cm.catch_error(r): return r
        hosts = r['hosts']
        if not hosts:
            return self.cm.error(f'no host matches "{arg1}"' if arg1 else 'no hosts')

        explicit = self._is_explicit(arg1, hosts)

        only = self._csv(repos)

        self._status_all(ctx, hosts)

        report = []
        problems = []            # what a person must look at: a failed repository, a check that found differences
        for h in hosts:
            alias = h['alias']
            sync = h['desc'].get('sync') or {}
            entries = self._sync_entries(h)

            if not entries:
                if explicit:
                    return self.cm.error(f'host "{alias}" declares no sync (no "sync: repos" in its _desc.yaml)')
                continue

            if not self._usable(h):
                if explicit:
                    return self.cm.error(f'host "{alias}" is {h["status"]} - cannot sync')
                report.append([alias, '*', '-', f'skipped ({h["status"]})', '-', ''])
                problems.append(f'{alias}: skipped ({h["status"]})')
                if con: print(f'{alias}: skipped ({h["status"]})')
                continue

            if h['status'] == 'here':
                if explicit:
                    return self.cm.error(f'host "{alias}" is this machine - nothing to sync to')
                continue

            if only:
                unknown = [x for x in only if x not in entries]
                if unknown:
                    return self.cm.error(f'{alias}: repositories not in its sync list: {", ".join(unknown)} '
                                         f'(declared: {", ".join(entries)})')
                selected = [(n, e) for n, e in entries.items() if n in only]
            else:
                selected = list(entries.items())

            if con:
                print('')
                print(f'=== {alias} ({self._address_text(h)}): {len(selected)} repositories' + (' - DRY RUN' if dry_run else ''))

                # A folder that the _desc.yaml does not name says where it comes from
                first = selected[0][1] if selected else {}
                if first.get('repos_path_from') not in (None, 'declared'):
                    why = {'probed': 'the cMeta home the last probe found there',
                           'declared home': 'the declared cmeta home (never probed)',
                           'default': 'the default: no repos_path declared, no cMeta home known - probe the host first'}
                    print(f'    into {first["repos_path"]} ({why.get(first["repos_path_from"], first["repos_path_from"])})')

            changed = False
            for name, entry in selected:
                t0 = time.monotonic()
                try:
                    retries_n = max(0, int(retries))
                except (TypeError, ValueError):
                    retries_n = 2
                r = self._sync_repo_robust(ctx, h, name, entry, resync=resync, resync_mode=resync_mode, unlock=unlock,
                                           dry_run=dry_run, con=con, verbose=verbose, backup=backup, retries=retries_n)
                notes = r.get('notes') or []
                if r['return'] > 0:
                    elapsed = f'{time.monotonic() - t0:.0f}s'
                    report.append([alias, name, entry['method'], 'FAILED: ' + str(r['error'])[:300], '-', elapsed])
                    problems.append(f'{alias} / {name}: {str(r["error"])[:300]}')
                    if con: print(f'*** FAILED: {alias} / {name} - {r["error"]} (the other repositories go on)')
                    continue
                changed = True
                result = 'ok' if dry_run else 'ok: ' + self._moved_text(r.get('moved') or {})
                if notes: result += ' (' + '; '.join(notes) + ')'

                # the check: both sides compared; a difference right after a good sync is a file that changed during
                # the run (the other side at work) - synced once more and compared again
                check = '-'
                both_sides = list(r.get('both_sides') or [])
                if not dry_run and not skip_check and entry['method'] != 'git':
                    c = self._check_repo(ctx, h, name, entry, con, verbose)
                    once_more = ''
                    if c.get('conflicts'):
                        merged = self._settle_index_conflicts(ctx, h, name, entry, c['conflicts'], con, verbose)
                        if merged:
                            notes.append(f'{len(merged)} memory index(es) merged from conflict copies')
                            both_sides = [b for b in both_sides if b not in merged]
                            once_more = 'the merged index taken into the baseline'
                    if not c.get('ok') and c.get('errors', 0) >= 0:
                        once_more = f'the check found {self._check_text(c)}'
                    if once_more:
                        if con: print(f'    {once_more}: synced once more')
                        r2 = self._sync_repo_robust(ctx, h, name, entry, resync=False, resync_mode=resync_mode, unlock=unlock,
                                                    dry_run=False, con=con, verbose=verbose, backup=backup, retries=retries_n)
                        if r2.get('return', 0) == 0:
                            again = self._moved_text(r2.get('moved') or {})
                            if again != 'nothing to move': result += f' + {again}'
                            both_sides += [b for b in (r2.get('both_sides') or []) if b not in both_sides]
                        c = self._check_repo(ctx, h, name, entry, con, verbose)
                    check = self._check_text(c) if c.get('errors', 0) >= 0 else 'not checked: ' + str(c.get('error', ''))[:120]
                    if not c.get('ok'):
                        problems.append(f'{alias} / {name}: the check: {check}' + (f' - the list: {c["file"]}' if c.get('file') else ''))
                    if con: print(f'CHECK ({alias} / {name}): {check}')
                if both_sides:
                    # the run itself made conflict copies: a person merges them (an index was merged by the run)
                    problems.append(f'{alias} / {name}: {len(both_sides)} file(s) changed on both sides since the last sync - kept as '
                                    f'.conflict1/.conflict2 on both sides, the name itself gone: ' + ', '.join(both_sides[:3]))
                    result += f' ({len(both_sides)} changed on both sides: conflict copies)'
                elif entry['method'] == 'git':
                    check = 'git: the pull is the check'
                elif skip_check and not dry_run:
                    check = 'skipped'
                if notes and 'merged' in notes[-1]: result += ' (' + notes[-1] + ')'
                elapsed = f'{time.monotonic() - t0:.0f}s'
                report.append([alias, name, entry['method'], result, check, elapsed])

            after = sync.get('after') or []
            if isinstance(after, str): after = [after]
            if changed and after and not dry_run and not skip_after:
                for cmd in after:
                    r = self._cmd_run(ctx, h, cmd)
                    if self.cm.catch_error(r): return r
                    if con:
                        print('')
                        print(f'AFTER ({alias}): {cmd}')
                    rr = self._run_local(r['cmd'], capture=not verbose, con=con, verbose=verbose)
                    if rr.get('returncode', 0) != 0:
                        report.append([alias, '(after)', cmd, f'exit code {rr.get("returncode")}', '-', ''])
                        problems.append(f'{alias}: "{cmd}" returned {rr.get("returncode")}')
                        if con: print(f'WARNING: "{cmd}" on {alias} returned {rr.get("returncode")}')

            if changed and not dry_run:
                self._refresh_state(ctx, h, con)        # state.yaml says what is there now

        synced = [row for row in report if str(row[3]).startswith('ok')]
        ok = not problems
        n_repos = f'{len(synced)} repositor' + ('y' if len(synced) == 1 else 'ies')
        if dry_run:
            summary = f'DRY RUN: {n_repos} looked at, nothing changed' + (f'; {len(problems)} problem(s)' if problems else '')
        else:
            summary = (f'{n_repos} synced' + ('' if skip_check else ' and checked') if ok
                       else f'{len(problems)} problem(s) - {n_repos} ok: ' + ' | '.join(p[:300] for p in problems[:6]))
        if con:
            print('')
            self._print_table(['HOST', 'REPOSITORY', 'METHOD', 'RESULT', 'CHECK', 'TIME'], report)
            print('')
            print(self._banner(ok, 'STATUS: ' + ('SUCCESS - ' if ok else 'FAILED - ') + summary))
            # a person at a terminal reads the problems before the window closes; never in a quiet run
            if problems and pause and not ctx['control'].get('quiet', False) and not ctx['control'].get('pause_at_the_end', False):
                try:
                    if sys.stdin is not None and sys.stdin.isatty():
                        input('Press Enter to continue (the problems are listed above) ...')
                except (EOFError, OSError):
                    pass

        out = {'return': 0 if ok else 1, 'report': report, 'problems': problems, 'summary': summary}
        if not ok:
            out['error'] = summary
        return out

    ############################################################
    def push_(
        self,
        ctx,
        arg1=None,          # host alias
        arg2=None,          # a repository name from the host's sync list, a repository registered here (its alias), or a local path (then --to)
        dirs=None,          # only these directories/files of it (comma-separated, relative, "task/run-ai/")
        artifacts=None,     # only these artifacts: cRef patterns separated by ";" ("work::2026*;fgg.project::cMeta/!AI"); a partial repository's own by default
        to=None,            # remote path (required for a local path; default for a repository: its remote)
        dry_run=False,      # show what would be copied, copy nothing
        delete=False,       # rclone sync instead of copy: also delete remote files missing locally (within --dirs)
        index=True,         # after a repository push: "cx repo reindex <repository>" on the host (plugged there the first time), so a new artifact is found there (--index- skips it)
        secrets=False,      # a repository of secrets (secrets: true in its _cmr.yaml) goes only with this flag and --artifacts naming the secrets
        unparsed=None,      # everything after "--" goes to rclone
        project=None,      # named environment; omitted: the host's global environment
    ):
        """
        Copy a few directories of a repository (or any local path) to a host, one way, local -> host,
        without touching the bisync baseline - for a quick fix when a sync glitched, or when only one task
        changed. Never deletes unless --delete. After a repository push that repository is rescanned on the host
        ("cx repo reindex <repository>", plugged there when the host does not know it yet; the whole index with a
        cMeta older than 0.34.0), so an artifact new to the host is found by "cx <cat> find" at once; --index- skips
        that (a push of category code or files only).

            cx host push lab-thinkpad-ubuntu ctuninglabs@cmeta-aops --dirs=task/run-ai/,tool/agy/
            cx host push lab-laptop-ubuntu ctuninglabs@cmeta-aops --dirs=task/run-ai/ --dry_run
            cx host push lab-mac-mini-macos D:\\tmp\\check.sh --to=/Users/user/cmeta-tests/check.sh
            cx host push lab-laptop-ubuntu my-repo --artifacts="work::2026*;my.project::x/!AI"
            cx host push lab-laptop-ubuntu my-secrets --artifacts="secret::git-work-without-pass" --secrets

        The repository's blacklist (tmp*/, __pycache__/, .venv/, .git/ ...) still applies. A partial repository
        (artifacts: in the host's sync entry) goes as its selection, never whole; --artifacts writes PARTIAL.md there.
        A repository of secrets goes only by name, with --secrets: into a folder only the host's user can read, then
        "cx secret check --fix" there makes every private key owner-only (the transfer does not keep the mode).
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        if not arg1 or not arg2:
            return self.cm.error('usage: cx host push <host> <repository | local path> [--dirs=a/,b/] [--to=<remote path>]')

        r = self._get_host(ctx, arg1, project=project)
        if self.cm.catch_error(r): return r
        h = r['host']

        if h['type'] in ('docker', 'wsl'):
            # an instance on this machine: a local file or folder goes inside (docker cp / cp through wsl.exe)
            if not to:
                return self.cm.error('--to=<path inside> is required for an instance (a local file or folder goes to it)')
            local = os.path.abspath(arg2)
            if not os.path.exists(local):
                return self.cm.error(f'"{arg2}" is not a local path (an instance mounts its repositories: push a file or a folder)')
            return self._copy_instance(ctx, h, local, to, into=True, dry_run=dry_run, con=con)
        if h['type'] != 'ssh':
            return self.cm.error(f'push works on ssh hosts and on docker / wsl instances ({h["alias"]} is {h["type"]})')
        if self._here(h):
            return self.cm.error(f'{h["alias"]} is this machine - nothing to push to')

        entries = self._sync_entries(h)
        blacklist = list(DEFAULT_BLACKLIST)
        patterns = self._patterns(artifacts)
        repository = ''
        if arg2 in entries:
            entry = entries[arg2]
            local = entry['local']
            remote_path = to or entry['remote']
            blacklist = entry['blacklist']
            repository = arg2
            if not patterns and not dirs:
                patterns = entry.get('artifacts') or []         # a partial repository goes as declared, never whole
        elif os.path.exists(arg2):
            local = os.path.abspath(arg2)
            if not to:
                return self.cm.error('--to=<remote path> is required for a local path')
            remote_path = to
        else:
            # a repository registered here that the host does not sync (a repository of secrets): by its alias
            r = self.cm.access({'category': 'repo,f4f792ab40c7498f', 'command': 'find', 'arg1': arg2, 'con': False})
            arts = (r.get('artifacts') or []) if r.get('return', 1) == 0 else []
            if len(arts) != 1 or not os.path.isdir(arts[0]['path']):
                return self.cm.error(f'"{arg2}" is neither a repository of {h["alias"]} '
                                     f'({", ".join(entries) or "none declared"}), nor a repository registered here, nor a local path')
            local = arts[0]['path']
            repository = arg2
            remote_path = to or (self._sync_repos_path(h, h['desc'].get('sync') or {})[0].rstrip('/') + '/' + os.path.basename(local))

        # a repository of secrets: only by name, only on purpose
        holds_secrets = bool(repository) and bool(self._repo_desc(local).get('secrets'))
        if holds_secrets and not (secrets and patterns):
            return self.cm.error(f'{arg2} holds secrets (secrets: true in its _cmr.yaml): name the secrets {h["alias"]} needs and say so - '
                                 f'cx host push {h["alias"]} {arg2} --artifacts="secret::<alias>;..." --secrets')

        extra = list(self._csv(unparsed)) if isinstance(unparsed, str) else list(unparsed or [])
        if dry_run:
            extra.append('--dry-run')

        whitelist = []
        for d in self._csv(dirs):
            d = d.replace('\\', '/')
            if not d.startswith('/'):
                d = '/' + d          # anchored: "task/run-ai/" means the top-level one, not every match
            whitelist.append(d)
        if patterns and not whitelist:
            r = self._selection_rules(local, patterns)
            if self.cm.catch_error(r): return r
            whitelist = r['rules']
            extra.append('--ignore-case')
            if con:
                print(f'PUSH ({h["alias"]}): {len(patterns)} artifact pattern(s) of {arg2} -> {len(whitelist)} rule(s)')

        if holds_secrets and not dry_run and self._shell(h).strip() not in ('powershell', 'pwsh', 'cmd'):
            # the folder first, readable by the host's user alone: the keys are never readable by others there, not even
            # for the moment between the copy (rclone's sftp does not keep a file's mode) and "cx secret check --fix"
            q = self._sh_path(remote_path)
            r = self._cmd_run(ctx, h, f'mkdir -p {q} && chmod 700 {q}')
            if self.cm.catch_error(r): return r
            rr = self._run_local(r['cmd'], capture=True, con=con, verbose=verbose, timeout=120)
            if rr.get('returncode', 1) != 0:
                return self.cm.error(f'the folder {remote_path} could not be made owner-only on {h["alias"]}: {rr.get("stderr", "")}'.strip())

        # a single file lands AT --to (rclone copyto); "copy" would make a folder of that name with the file
        # inside (seen 2026-10-07: --to=.../decode_test.py gave decode_test.py/decode_test.py)
        command = 'sync' if delete else ('copyto' if os.path.isfile(local) else 'copy')
        if command == 'copyto':
            whitelist, blacklist = [], []        # rclone: "can't limit to single files when using filters"
        r = self._rclone(ctx, h, command, local, remote_path,
                         whitelist=whitelist, blacklist=blacklist, extra=extra, con=con, verbose=verbose)
        if self.cm.catch_error(r): return r

        result = {'return': 0, 'host': h['alias'], 'local': local, 'remote': remote_path, 'dirs': whitelist}

        if patterns and not dry_run:
            r = self._write_partial_note(ctx, h, arg2, remote_path, patterns, whitelist, 'push', verbose)
            if r['return'] > 0 and con:
                print(f'WARNING: {PARTIAL_NOTE} was not written on {h["alias"]}: {r.get("error")}')

        # A pushed folder is on the host's disk but not in its index until the index is rebuilt (seen 2026-10-06
        # with new tools: invisible to "cx tool find" there): only the pushed repository is rescanned ("cx repo
        # reindex", cMeta 0.34.0+), plugged when the host does not know it yet; a cMeta too old for it gets the
        # whole index rebuilt as before
        if index and repository and not dry_run:
            r = self._index_on_host(ctx, h, arg2, remote_path, con, verbose)
            if self.cm.catch_error(r): return r
            result['index'] = {k: r[k] for k in ('cmd', 'returncode', 'seconds')}

        # the private keys made owner-only there, and what is there checked (the table shows the references, never a value)
        if holds_secrets and not dry_run:
            r = self._cmd_run(ctx, h, 'cx secret check --fix')
            if self.cm.catch_error(r): return r
            rr = self._run_local(r['cmd'], capture=False, con=con, verbose=verbose, timeout=300)
            result['secret_check'] = rr.get('returncode')
            if rr.get('returncode', 0) != 0 and con:
                print(f'WARNING: "cx secret check --fix" on {h["alias"]} returned {rr.get("returncode")}')

        return result

    ############################################################
    def pull_(
        self,
        ctx,
        arg1=None,          # host alias
        arg2=None,          # a file or folder on the host (relative to its login home, or absolute)
        to=None,            # the local folder it goes into (default: the current directory; made when missing)
        files=None,         # only these files of a folder (comma-separated patterns, "*.jsonl,steps.txt")
        dry_run=False,      # show what would be copied, copy nothing
        unparsed=None,      # everything after "--" goes to rclone
        project=None,       # named environment; omitted: the host's global environment
    ):
        """
        Copy a file or a folder of a host here, one way, host -> local: the other way of push, for the results
        of a run there (verdicts, logs, records). A folder's files go into --to with their sub-folders, a file
        goes into --to; nothing here is deleted. rclone is set up when missing (-q: without asking).

            cx host pull lab-laptop-ubuntu cmeta-tests/20261014-1407-versions/work --to=D:\\runs\\t470p -q
            cx host pull lab-mac-mini-macos cmeta-tests/20261014-1407-versions/work --files=*.jsonl --to=D:\\runs\\mac
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        if not arg1 or not arg2:
            return self.cm.error('usage: cx host pull <host> <remote file or folder> [--to=<local folder>] [--files=*.jsonl]')

        r = self._get_host(ctx, arg1, project=project)
        if self.cm.catch_error(r): return r
        h = r['host']

        local = os.path.abspath(to or '.')
        if h['type'] in ('docker', 'wsl'):
            os.makedirs(local, exist_ok=True)
            return self._copy_instance(ctx, h, arg2, local, into=False, files=list(self._csv(files)), dry_run=dry_run, con=con)
        if h['type'] != 'ssh':
            return self.cm.error(f'pull works on ssh hosts and on docker / wsl instances ({h["alias"]} is {h["type"]})')
        if self._here(h):
            return self.cm.error(f'{h["alias"]} is this machine - nothing to pull from')

        os.makedirs(local, exist_ok=True)

        extra = list(self._csv(unparsed)) if isinstance(unparsed, str) else list(unparsed or [])
        if dry_run:
            extra.append('--dry-run')

        # "copy" of a remote file puts it into the local folder, of a remote folder its contents
        r = self._rclone(ctx, h, 'copy', local, arg2.replace('\\', '/'), whitelist=list(self._csv(files)),
                         extra=extra, con=con, verbose=verbose, from_remote=True)
        if self.cm.catch_error(r): return r

        return {'return': 0, 'host': h['alias'], 'remote': arg2, 'local': local}

    ############################################################
    def backup_(
        self,
        ctx,
        arg1=None,          # host alias
        to=None,            # the folder the dated backup goes into (default: the machine artifact's backup/<host>/)
        dry_run=False,      # list what would be copied, with sizes; copy nothing
        skip_commands=False,  # do not run the host's "backup: commands: before"
        unparsed=None,      # everything after "--" goes to rclone
        project=None,       # named environment; omitted: the host's global environment
    ):
        """
        Copy what only this host has - its configuration, state, secrets and scripts, as the "backup:" block of its
        _desc.yaml declares - into a dated folder of the machine artifact it belongs to:
        <machine>/backup/<host>/<YYYYMMDD-HHMM>/, with backup.yaml saying what came and from where. The machine
        artifact is the asset's record, so the files a rebuild needs sit next to it; "cx host restore" puts them
        back on this host or on its replacement. Root-only files ("sudo_paths") are read through sudo into a
        staging folder on the host first (passwordless sudo), then fetched and removed there.

            cx host backup my-azure-vm-ubuntu --dry_run      # the paths, their kind and size; nothing copied
            cx host backup my-azure-vm-ubuntu
            cx host backup my-azure-vm-ubuntu --to=D:\\backups\\vm
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        if not arg1:
            return self.cm.error('which host? cx host backup <host> [--to=<folder>] [--dry_run]')

        r = self._get_host(ctx, arg1, project=project)
        if self.cm.catch_error(r): return r
        h = r['host']
        if h['type'] != 'ssh':
            return self.cm.error(f'backup works on ssh hosts ({h["alias"]} is {h["type"]})')
        if self._here(h):
            return self.cm.error(f'{h["alias"]} is this machine - nothing to back up from')

        r = self._backup_entries(h)
        if self.cm.catch_error(r): return r
        entries, block = r['entries'], r['block']

        r = self._backup_root(ctx, h, to)
        if self.cm.catch_error(r): return r
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
        dest = os.path.join(r['root'], stamp)

        # the host says what each path is (a folder, a file, missing) and how big it is: one round trip
        r = self._backup_stat(ctx, h, entries, verbose)
        if self.cm.catch_error(r): return r
        stat = r['stat']

        if con:
            print(f'=== {h["alias"]} ({self._address_text(h)}) -> {dest}' + (' - DRY RUN' if dry_run else ''))
            for e in entries:
                st = stat.get(e['path']) or {}
                print(f'    {st.get("kind", "?"):>7}  {st.get("size", "?"):>9}  {e["path"]}' + (f'  (files: {", ".join(e["files"])})' if e['files'] else '')
                      + ('  [sudo]' if e['sudo'] else ''))
        missing = [e['path'] for e in entries if (stat.get(e['path']) or {}).get('kind') == 'missing'
                   or ((stat.get(e['path']) or {}).get('kind') == 'files' and not (stat.get(e['path']) or {}).get('items'))]
        if missing and con:
            print(f'    not on the host, skipped: {", ".join(missing)}')
        entries = [e for e in entries if e['path'] not in missing and (stat.get(e['path']) or {}).get('kind') in ('file', 'folder', 'files')]

        if dry_run:
            return {'return': 0, 'host': h['alias'], 'dest': dest, 'entries': entries, 'stat': stat, 'dry_run': True}

        before = (block.get('commands') or {}).get('before') or []
        if isinstance(before, str): before = [before]
        if before and not skip_commands:
            for cmd in before:
                r = self._cmd_run(ctx, h, cmd)
                if self.cm.catch_error(r): return r
                if con: print(f'BEFORE ({h["alias"]}): {cmd}')
                rr = self._run_local(r['cmd'], capture=not verbose, con=con, verbose=verbose, timeout=600)
                if rr.get('returncode', 0) != 0:
                    return self.cm.error(f'"{cmd}" on {h["alias"]} returned {rr.get("returncode")} - nothing backed up')

        extra = list(self._csv(unparsed)) if isinstance(unparsed, str) else list(unparsed or [])
        exclude = [str(x) for x in (block.get('exclude') or [])]
        os.makedirs(dest, exist_ok=True)

        # root-only files first: copied by sudo into a staging folder the host's user owns, fetched, removed there
        sudo_entries = [e for e in entries if e['sudo']]
        staging = f'.cmeta-backup-{stamp}'
        if sudo_entries:
            lines = ['set -e', f'rm -rf "$HOME"/{staging}', f'mkdir -p "$HOME"/{staging}']
            for e in sudo_entries:
                q = shlex.quote(e['path'].lstrip('/'))
                lines.append(f'sudo mkdir -p "$HOME"/{staging}/$(dirname {q}) && sudo cp -a {shlex.quote(e["path"])} "$HOME"/{staging}/{q}')
            lines.append(f'sudo chown -R "$(id -u):$(id -g)" "$HOME"/{staging} && chmod -R u+rX "$HOME"/{staging}')
            r = self._backup_script(ctx, h, '\n'.join(lines) + '\n', verbose)
            if self.cm.catch_error(r): return r
            r = self._rclone(ctx, h, 'copy', os.path.join(dest, 'root'), staging, blacklist=exclude, extra=extra,
                             con=con, verbose=verbose, from_remote=True)
            self._backup_script(ctx, h, f'rm -rf "$HOME"/{staging}\n', verbose)       # whatever happened, nothing stays
            if self.cm.catch_error(r): return r

        # then the host user's own paths, each into its place under <dest>/home/
        for e in entries:
            if e['sudo']:
                continue
            kind = stat[e['path']]['kind']
            if kind == 'files':
                # the matched files of the folder, one by one (rclone would walk the whole folder for an include rule)
                for item in stat[e['path']].get('items') or []:
                    local = os.path.join(dest, 'home', *item.split('/'))
                    os.makedirs(os.path.dirname(local), exist_ok=True)
                    r = self._rclone(ctx, h, 'copyto', local, item, extra=extra, con=con, verbose=verbose, from_remote=True)
                    if self.cm.catch_error(r): return r
                continue
            if kind == 'file':
                # rclone copy of a remote file puts it into the local folder: the file's own folder here
                local = os.path.join(dest, 'home', *e['path'].split('/')[:-1])
            else:
                local = os.path.join(dest, 'home', *e['path'].split('/'))
            r = self._rclone(ctx, h, 'copy', local, e['path'], blacklist=exclude if kind == 'folder' else [],
                             extra=extra, con=con, verbose=verbose, from_remote=True)
            if self.cm.catch_error(r): return r

        manifest = {
            'host': f'{h["alias"]},{h["uid"]}',
            'machine': h['desc'].get('machine'),
            'address': self._address_text(h),
            'backed_up': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'home': stat.get('_home', ''),
            'state': {k: (h.get('state') or {}).get(k) for k in ('os', 'cmeta_version', 'cmeta_home', 'aops_version', 'probed') if (h.get('state') or {}).get(k)},
            # per entry: what it is, its size and mode, the matched files of a "files" entry, and the modes of what a
            # folder holds (the restore puts them back; the copy keeps none)
            'entries': [{k: v for k, v in {'path': e['path'], 'kind': stat[e['path']]['kind'], 'size': stat[e['path']].get('size'),
                                           'mode': stat[e['path']].get('mode'), 'sudo': e['sudo'], 'files': e['files'],
                                           'items': stat[e['path']].get('items') or [],
                                           'item_modes': stat[e['path']].get('item_modes') or {},
                                           'modes': stat[e['path']].get('modes') or {},
                                           'local': ('root/' if e['sudo'] else 'home/') + e['path'].strip('/')}.items()
                         if k not in ('item_modes', 'modes') or v} for e in entries],
            'exclude': exclude,
            'commands': block.get('commands') or {},
            'made_by': 'cx host backup',
        }
        self._write_yaml(os.path.join(dest, 'backup.yaml'), manifest)

        keep = block.get('keep')
        removed = []
        if isinstance(keep, int) and keep > 0:
            root = os.path.dirname(dest)
            older = sorted(d for d in os.listdir(root) if re.match(r'^\d{8}-\d{4}$', d) and os.path.isfile(os.path.join(root, d, 'backup.yaml')))
            for d in older[:-keep]:
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                removed.append(d)

        if con:
            print('')
            print(f'backed up: {dest}' + (f'  (older backups removed: {", ".join(removed)})' if removed else ''))
        return {'return': 0, 'host': h['alias'], 'dest': dest, 'entries': manifest['entries'], 'removed': removed}

    ############################################################
    def restore_(
        self,
        ctx,
        arg1=None,          # host alias (or an instance cMeta made: back to a snapshot, see below)
        source=None,        # the backup folder (default: the newest backup of this host in its machine artifact)
        into=None,          # put everything under this folder on the host instead of its real place (a test, a look)
        paths=None,         # only these paths of the backup (comma-separated, as backup.yaml names them)
        dry_run=False,      # list what would go where; copy nothing
        yes=False,          # a production host (ai: production: true) restores only with --yes
        skip_commands=False,  # do not run the host's "backup: commands: after_restore"
        name=None,          # an instance's snapshot name (cx host restore <instance> --name=<snapshot>)
        force=False,        # an instance declared by hand (docker, wsl)
        project=None,       # named environment; omitted: the host's global environment
    ):
        """
        Put a backup back on a host: every path of "cx host backup" to where it came from, root-only ones through
        sudo, then the host's "backup: commands: after_restore" (e.g. cx --reindex). The newest backup of the host
        is taken from its machine artifact, --source names another (the backup of the host this one replaces). With
        --into=<folder> everything lands under that folder on the host - a look, or a test on a disposable host.

            cx host restore my-azure-vm-ubuntu --dry_run
            cx host restore new-vm-ubuntu --source=<machine>/backup/my-azure-vm-ubuntu/20261023-1130 --yes
            cx host restore lab-laptop-ubuntu --source=<that folder> --into=cmeta-tests/restore-test

        An instance cMeta made (docker, wsl) goes back to a snapshot instead: cx host restore <instance> [--name=<snapshot>].
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        if not arg1:
            return self.cm.error('which host? cx host restore <host> [--source=<backup folder>] [--into=<folder>] [--dry_run]')

        r = self._get_host(ctx, arg1, project=project)
        if self.cm.catch_error(r): return r
        h = r['host']
        if h['type'] in ('docker', 'wsl'):
            return self._restore_instance(ctx, arg1, name, force)
        if h['type'] != 'ssh':
            return self.cm.error(f'restore works on ssh hosts and on instances cMeta made ({h["alias"]} is {h["type"]})')
        if self._here(h):
            return self.cm.error(f'{h["alias"]} is this machine - restore by hand here')

        if source:
            src = os.path.abspath(source)
        else:
            r = self._backup_root(ctx, h, None)
            if self.cm.catch_error(r): return r
            stamps = sorted(d for d in (os.listdir(r['root']) if os.path.isdir(r['root']) else [])
                            if re.match(r'^\d{8}-\d{4}$', d) and os.path.isfile(os.path.join(r['root'], d, 'backup.yaml')))
            if not stamps:
                return self.cm.error(f'no backup of {h["alias"]} under {r["root"]} - cx host backup {h["alias"]} first, or --source=<folder>')
            src = os.path.join(r['root'], stamps[-1])
        manifest_path = os.path.join(src, 'backup.yaml')
        if not os.path.isfile(manifest_path):
            return self.cm.error(f'{src} holds no backup.yaml (not a folder "cx host backup" made)')
        manifest = self._read_yaml(manifest_path)
        entries = manifest.get('entries') or []
        only = self._csv(paths)
        if only:
            unknown = [p for p in only if p not in [e['path'] for e in entries]]
            if unknown:
                return self.cm.error(f'not in this backup: {", ".join(unknown)} (it holds: {", ".join(e["path"] for e in entries)})')
            entries = [e for e in entries if e['path'] in only]

        production = bool((h['desc'].get('ai') or {}).get('production'))
        if production and not yes and not dry_run and not into:
            return self.cm.error(f'{h["alias"]} is a production host: cx host restore {h["alias"]} ... --yes (or --dry_run, or --into=<folder>)')

        into = str(into or '').replace('\\', '/').strip().rstrip('/')
        if con:
            print(f'=== {src} -> {h["alias"]} ({self._address_text(h)})' + (f' under {into}/' if into else '') + (' - DRY RUN' if dry_run else ''))
            for e in entries:
                target = (into + '/' + e['path'].strip('/')) if into else e['path']
                print(f'    {e.get("kind", "?"):>7}  {str(e.get("size") or ""):>9}  {e["local"]}  ->  {target}' + ('  [sudo]' if e.get('sudo') and not into else ''))
        if dry_run:
            return {'return': 0, 'host': h['alias'], 'source': src, 'entries': entries, 'dry_run': True}

        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M')
        staging = f'.cmeta-restore-{stamp}'
        made = []
        for e in entries:
            local = os.path.join(src, *e['local'].split('/'))
            if not os.path.exists(local):
                if e.get('kind') in ('folder', 'files'):
                    # a folder that was empty on the host (or whose files were all excluded) has no copy in the
                    # backup: it is made again, empty, with its mode
                    made.append(e)
                    if con:
                        print(f'    {e["path"]}: nothing in the backup (the folder was empty, or all of it excluded) - made again, empty')
                    continue
                return self.cm.error(f'{local} is not in the backup')
            if e.get('kind') == 'files':
                # the folder's matched files, one by one, each at its own place
                for item in e.get('items') or []:
                    f_local = os.path.join(src, 'home', *item.split('/'))
                    f_remote = (into + '/' + item) if into else item
                    r = self._rclone(ctx, h, 'copyto', f_local, f_remote, extra=[], con=con, verbose=verbose)
                    if self.cm.catch_error(r): return r
                continue
            if e.get('sudo') and not into:
                remote = staging + '/' + e['path'].strip('/')
            else:
                remote = (into + '/' + e['path'].strip('/')) if into else e['path']
            command = 'copyto' if e.get('kind') == 'file' else 'copy'
            r = self._rclone(ctx, h, command, local, remote, extra=[], con=con, verbose=verbose)
            if self.cm.catch_error(r): return r

        # one script on the host: the root-only entries from the staging folder into their place, the folders that
        # were empty made again, then every recorded mode put back (the copy keeps none - a private key would land
        # readable by all); an entry restored through sudo keeps its chmod through sudo too
        sudo_entries = [e for e in entries if e.get('sudo')] if not into else []
        lines = ['set -e']
        for e in sudo_entries:
            q = shlex.quote(e['path'])
            lines.append(f'sudo mkdir -p $(dirname {q}) && sudo cp -a "$HOME"/{staging}/{shlex.quote(e["path"].strip("/"))} {q}')
        for e in made:
            s = 'sudo ' if (e.get('sudo') and not into) else ''
            lines.append(f'{s}mkdir -p {shlex.quote((into + "/" + e["path"].strip("/")) if into else e["path"])}')

        def mode_of(value):
            return str(value) if re.fullmatch(r'[0-7]{3,4}', str(value or '')) else ''
        for e in entries:
            s = 'sudo ' if (e.get('sudo') and not into) else ''
            target = (into + '/' + e['path'].strip('/')) if into else e['path']
            if e.get('kind') == 'files':
                for item, mode in (e.get('item_modes') or {}).items():
                    if mode_of(mode):
                        lines.append(f'{s}chmod {mode_of(mode)} {shlex.quote((into + "/" + item) if into else item)}')
                continue
            if mode_of(e.get('mode')):
                lines.append(f'{s}chmod {mode_of(e["mode"])} {shlex.quote(target)}')
            for rel, mode in (e.get('modes') or {}).items():
                if mode_of(mode) and rel:
                    lines.append(f'{s}chmod {mode_of(mode)} {shlex.quote(target + "/" + rel)} 2>/dev/null || true')
        if sudo_entries:
            lines.append(f'rm -rf "$HOME"/{staging}')
        if len(lines) > 1:
            r = self._backup_script(ctx, h, '\n'.join(lines) + '\n', verbose)
            if self.cm.catch_error(r): return r

        after = (manifest.get('commands') or {}).get('after_restore') or ((h['desc'].get('backup') or {}).get('commands') or {}).get('after_restore') or []
        if isinstance(after, str): after = [after]
        if after and not skip_commands and not into:
            for cmd in after:
                r = self._cmd_run(ctx, h, cmd)
                if self.cm.catch_error(r): return r
                if con: print(f'AFTER ({h["alias"]}): {cmd}')
                rr = self._run_local(r['cmd'], capture=not verbose, con=con, verbose=verbose, timeout=600)
                if rr.get('returncode', 0) != 0 and con:
                    print(f'WARNING: "{cmd}" on {h["alias"]} returned {rr.get("returncode")}')

        if con:
            print('')
            print(f'restored {len(entries)} path(s) of {src} on {h["alias"]}' + (f' under {into}/' if into else ''))
        return {'return': 0, 'host': h['alias'], 'source': src, 'entries': entries, 'into': into}

    def _backup_entries(self, h):
        """The host's "backup:" block as a list of {path, files, sudo}: paths relative to the login home or absolute;
        an item is a path, or {path: ..., files: [patterns]} for a few files of a folder; sudo_paths are root-only."""
        block = h['desc'].get('backup') or {}
        if not block or not (block.get('paths') or block.get('sudo_paths')):
            return self.cm.error(f'host "{h["alias"]}" declares no backup (no "backup: paths" in its _desc.yaml)')
        entries = []
        for sudo, key in ((False, 'paths'), (True, 'sudo_paths')):
            for item in block.get(key) or []:
                if isinstance(item, dict):
                    path, files = str(item.get('path') or ''), self._csv(item.get('files'))
                else:
                    path, files = str(item), []
                path = path.replace('\\', '/').strip()
                if path.startswith('~/'):
                    path = path[2:]
                path = path.rstrip('/') if path != '/' else path
                if not path:
                    continue
                entries.append({'path': path, 'files': files, 'sudo': sudo})
        return {'return': 0, 'entries': entries, 'block': block}

    def _backup_root(self, ctx, h, to):
        """Where the host's backups go: --to, else <the machine artifact's folder>/backup/<host alias>/."""
        if to:
            return {'return': 0, 'root': os.path.abspath(to)}
        ref = str(h['desc'].get('machine') or '')
        if not ref:
            return self.cm.error(f'host "{h["alias"]}" names no machine - say where with --to=<folder>')
        r = self.cm.access({'category': self.cmeta['uses_categories']['machine'], 'command': 'find',
                            'arg1': ref.split('::')[-1], 'con': False})
        arts = (r.get('artifacts') or []) if r.get('return', 1) == 0 else []
        if len(arts) != 1 or not os.path.isdir(arts[0]['path']):
            return self.cm.error(f'the machine {ref} of {h["alias"]} is not here ({len(arts)} found) - say where with --to=<folder>')
        return {'return': 0, 'root': os.path.join(arts[0]['path'], 'backup', h['alias'])}

    def _backup_script(self, ctx, h, script, verbose):
        """Run a few shell lines on the host (its login shell on stdin) and return their output."""
        r = self._temp_script(script)
        if r['return'] > 0: return r
        r = self._cmd_stdin(ctx, h, r['path'])
        if r['return'] > 0: return r
        rr = self._run_local(r['cmd'], capture=True, con=False, verbose=verbose, timeout=600)
        if rr.get('returncode', 1) != 0:
            return self.cm.error(f'on {h["alias"]}: {(rr.get("stderr") or rr.get("stdout") or "").strip()[-400:] or "exit " + str(rr.get("returncode"))}')
        return {'return': 0, 'stdout': rr.get('stdout', '') or ''}

    def _backup_stat(self, ctx, h, entries, verbose):
        """What each path is on the host - file | folder | files (a folder's matched files, listed) | missing - with its
        size in KB and its mode (one round trip; root-only paths are looked at through sudo)."""
        lines = ['echo "_home|$HOME"']
        for e in entries:
            q = shlex.quote(e['path'])
            s = 'sudo ' if e['sudo'] else ''
            if e['files']:
                # the matched files of the folder, each on its own line with its mode: copied one by one, never the whole folder
                globs = ' '.join(shlex.quote(e['path'] + '/' + p) for p in e['files'])
                lines.append(f'if [ -d {q} ]; then echo "{e["path"]}|files|$(du -ck $(ls -d {globs} 2>/dev/null) 2>/dev/null | tail -1 | cut -f1)|$(stat -c %a {q} 2>/dev/null)"; '
                             f'for f in $(ls -d {globs} 2>/dev/null); do echo "{e["path"]}|item|$f|$(stat -c %a "$f" 2>/dev/null)"; done; '
                             f'else echo "{e["path"]}|missing||"; fi')
            else:
                # a folder: its mode, then the mode of everything inside it (the copy keeps none of them; GNU find - a
                # host without -printf gives no modes and the restore applies none)
                lines.append(f'if {s}test -d {q}; then echo "{e["path"]}|folder|$({s}du -sk {q} 2>/dev/null | cut -f1)|$({s}stat -c %a {q} 2>/dev/null)"; '
                             f'{s}find {q} -mindepth 1 -printf "{e["path"]}|mode|%m|%P\\n" 2>/dev/null | head -5000; '
                             f'elif {s}test -e {q}; then echo "{e["path"]}|file|$({s}du -k {q} 2>/dev/null | cut -f1)|$({s}stat -c %a {q} 2>/dev/null)"; '
                             f'else echo "{e["path"]}|missing||"; fi')
        r = self._backup_script(ctx, h, '\n'.join(lines) + '\n', verbose)
        if self.cm.catch_error(r): return r
        stat = {}
        for line in r['stdout'].splitlines():
            parts = line.rstrip().split('|')
            if parts[0] == '_home' and len(parts) > 1:
                stat['_home'] = parts[1]
            elif len(parts) >= 3 and parts[1] == 'item':
                stat.setdefault(parts[0], {}).setdefault('items', []).append(parts[2].strip())
                if len(parts) >= 4 and parts[3].strip():
                    stat[parts[0]].setdefault('item_modes', {})[parts[2].strip()] = parts[3].strip()
            elif len(parts) >= 4 and parts[1] == 'mode':
                stat.setdefault(parts[0], {}).setdefault('modes', {})['|'.join(parts[3:]).strip()] = parts[2].strip()
            elif len(parts) >= 4:
                kb = parts[2].strip()
                stat.setdefault(parts[0], {}).update({'kind': parts[1], 'size': f'{int(kb)} KB' if kb.isdigit() else '', 'mode': parts[3].strip()})
        return {'return': 0, 'stat': stat}

    @staticmethod
    def _write_yaml(path, data):
        import yaml
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('# Written by "cx host backup": what was copied from the host and where it belongs; "cx host restore" reads it.\n\n')
            f.write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120))

    ############################################################
    def upgrade_(
        self,
        ctx,
        arg1=None,          # host alias, UID or wildcard
        tags=None,          # or a selection
        machine=None,
        type=None,
        version=None,       # a cMeta version to install instead of the latest
        sync=False,         # first bring the host's repositories up to date (cx host sync <host>)
        restart=False,      # then reboot the host and run its "commands: after_restart" (cx host restart <host>)
        yes=False,          # do not ask before the restart (also implied by -q)
        timeout=600,        # seconds to wait for a restarted host
        dry_run=False,      # print the commands, run nothing
        engine=True,        # the cMeta engine (--engine- leaves it alone, e.g. with --system only)
        system=False,       # the OS packages too, with "cx task run upgrade-os" on the host (needs passwordless sudo there)
        firmware=False,     # the firmware too (upgrade-os --firmware: fwupd on Linux)
        check=False,        # with --system/--firmware: only list what would be upgraded (upgrade-os --check)
        project=None,      # named environment; omitted: the host's global environment
    ):
        """
        Update the cMeta engine on a host, as its _desc.yaml declares under "cmeta:":
        install "uv-tool" -> uv tool upgrade cmeta (or uv tool install --force "cmeta==<version>");
        install "pip" -> pip install -U cmeta; install "editable" -> git pull in the source tree;
        or the literal "cmeta: upgrade" command. Then prints the new "cx --version".

        --system (and --firmware) also runs the task upgrade-os on the host: the OS packages with the OS's
        own commands (apt, dnf, zypper, pacman, apk, softwareupdate + brew, winget), the firmware with fwupd,
        and reports whether the OS asks for a reboot; --check only lists what would be upgraded.

        The full update of a host that runs servers is sync, upgrade, restart - in that order, since the
        upgrade replaces the engine under the running servers and only the restart brings them up on the
        new one (through "commands: after_restart"): --sync and --restart do the three steps per host.

            cx host upgrade lab-laptop-ubuntu
            cx host upgrade --tags=ubuntu --version=0.33.0
            cx host upgrade my-azure-vm-ubuntu --sync --restart --yes
            cx host upgrade lab-laptop-ubuntu --system --firmware --check     # what the OS would upgrade
            cx host upgrade lab-laptop-ubuntu --engine- --system --restart --yes
        """

        if project and (restart or system or firmware):
            return self.cm.error('--project cannot be combined with --restart, --system or --firmware: these affect the whole host')

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        r = self._select(ctx, arg1, tags, machine, type, project=project)
        if self.cm.catch_error(r): return r
        hosts = r['hosts']
        if not hosts:
            return self.cm.error(f'no host matches "{arg1}"' if arg1 else 'no hosts')

        explicit = self._is_explicit(arg1, hosts)
        self._status_all(ctx, hosts)

        results = {}
        for h in hosts:
            alias = h['alias']
            cm = h['desc'].get('cmeta') or {}
            install = str(cm.get('install') or '')
            steps = []          # what this host got: sync / upgrade / restart notes for the summary

            cmd = cm.get('upgrade')
            if not cmd:
                if install == 'uv-tool':
                    # "uv tool install ... --force", not "uv tool upgrade": a tool installed with an exact
                    # version pin (cmeta==0.32.5) is never upgraded by the latter - it only prints a hint.
                    # The extras of the existing install ([server] for a cserver host) must be repeated, or
                    # the reinstall silently drops them (seen 2026-10-06: cserver gone on the P14s Gen 4):
                    # declared as "cmeta: extras: [server]", else read from uv's receipt of the tool.
                    extras = cm.get('extras')
                    if extras:
                        spec_extras = '[' + ','.join(self._csv(extras)) + ']'
                        head = ''
                    else:
                        spec_extras = '${E:+[$E]}'
                        # [^]]* and not .*: the receipt line ends with "] }]" and a greedy match would take
                        # the last bracket and produce cmeta[server]}]
                        head = ('E=$(sed -n "s/.*extras = \\[\\([^]]*\\)\\].*/\\1/p" "$(uv tool dir 2>/dev/null || echo ~/.local/share/uv/tools)'
                                '/cmeta/uv-receipt.toml" 2>/dev/null | tr -d " \\"" | head -1); ')
                    spec = f'cmeta{spec_extras}=={version}' if version else f'cmeta{spec_extras}@latest'
                    # --refresh: uv's cached view of PyPI lags a fresh release by minutes (2026-10-07: "already
                    # 0.33.0" and "no version of cmeta==0.33.1" on a VM right after the upload)
                    # --with pip: pip in the tool environment, as the installers do since cMeta 0.37.7 (a page's or a
                    # task's packages install the usual way; a tool environment without it works through uv only)
                    cmd = f'{head}uv tool install --force --refresh --with pip "{spec}"'
                elif install == 'pip' and project:
                    venv = h['project_desc']['venv']
                    python = venv.rstrip('/\\') + ('/Scripts/python.exe' if self._shell(h).strip() in ('powershell', 'pwsh') else '/bin/python')
                    spec = 'cmeta' + ('[' + ','.join(self._csv(cm.get('extras'))) + ']' if cm.get('extras') else '')
                    spec += '==' + str(version) if version else ''
                    cmd = 'uv pip install --upgrade --python ' + shlex.quote(python) + ' ' + shlex.quote(spec)
                elif install == 'pip':
                    cmd = f'pip install -U "cmeta=={version}"' if version else 'pip install -U cmeta'
                elif install == 'editable':
                    src = cm.get('source')
                    if not src:
                        results[alias] = 'no cmeta.source for the editable install'
                        continue
                    cmd = f'git -C "{src}" pull --ff-only'
                else:
                    msg = f'no "cmeta: install" (uv-tool | pip | editable) or "cmeta: upgrade" declared'
                    if explicit: return self.cm.error(f'{alias}: {msg}')
                    results[alias] = msg
                    if con: print(f'{alias:32} skipped - {msg}')
                    continue

            if not self._usable(h):
                if explicit: return self.cm.error(f'host "{alias}" is {h["status"]}')
                results[alias] = f'skipped ({h["status"]})'
                if con: print(f'{alias:32} skipped ({h["status"]})')
                continue

            here = h['status'] == 'here'
            sync_entries = self._sync_entries(h) if sync else {}
            cmds = h['desc'].get('commands') or {}
            after_restart = cmds.get('after_restart') if isinstance(cmds, dict) else None
            after_restart = [after_restart] if isinstance(after_restart, str) else (after_restart or [])

            if dry_run:
                if sync:
                    if here:
                        steps.append('no sync (this machine)')
                    elif sync_entries:
                        steps.append('would sync ' + ', '.join(sync_entries))
                    else:
                        steps.append('no sync declared')
                if system or firmware:
                    steps.append('would run: ' + self._upgrade_os_cmd(system, firmware, check))
                if engine:
                    steps.append(f'would run: {cmd}')
                if restart:
                    if here and not explicit:
                        steps.append('no restart (this machine, in a selection)')
                    else:
                        steps.append('would restart' + (f' + {len(after_restart)} after_restart command(s)' if after_restart else ''))
                results[alias] = '; '.join(steps)
                if con: print(f'{alias:32} {results[alias]}')
                continue

            # 1. sync - the host's declared repositories, as "cx host sync <host>"
            if sync:
                if here:
                    steps.append('no sync (this machine)')
                elif not sync_entries:
                    steps.append('no sync declared')
                else:
                    if con:
                        print('')
                        print(f'=== {alias}: sync ({len(sync_entries)} repositories)')
                    r = self.sync_(ctx, arg1=alias, project=project)
                    if r['return'] > 0:
                        results[alias] = f'sync failed - {r.get("error", "")}'
                        if explicit:
                            return {'return': 1, 'error': f'{alias}: {results[alias]}', 'results': results}
                        if con: print(f'{alias:32} {results[alias]} - not upgraded')
                        continue
                    steps.append(f'synced {len(sync_entries)}')

            # 1b. the OS packages and the firmware: task upgrade-os on the host, through its shell
            rc = 0
            if system or firmware:
                os_cmd = self._upgrade_os_cmd(system, firmware, check)
                sudo_state = str((h.get('state') or {}).get('sudo') or '')
                if sudo_state == 'password' and not here and not check:
                    steps.append('OS: skipped - sudo needs a password there (run "cx task run upgrade-os" in a terminal on it, or add a NOPASSWD rule)')
                else:
                    r = self._cmd_run(ctx, h, os_cmd)
                    if self.cm.catch_error(r): return r
                    if con:
                        print('')
                        print(f'=== {alias}: {os_cmd}')
                    rr = self._run_local(r['cmd'], capture=True, con=con, verbose=verbose, timeout=3600)
                    rc = rr.get('returncode', 0)
                    out = (rr.get('stdout') or '') + (rr.get('stderr') or '')
                    if con:
                        tail = [x for x in out.strip().splitlines() if x.strip()]
                        for line in tail[-12:]:
                            print('    ' + line)
                    verdict = next((x for x in reversed(out.strip().splitlines()) if x.startswith('upgrade-os:')), '')
                    if rc != 0:
                        steps.append('OS: FAILED - ' + (verdict or f'exit code {rc}'))
                        results[alias] = '; '.join(steps)
                        if explicit:
                            return {'return': 1, 'error': f'{alias}: {results[alias]}', 'results': results}
                        if con: print(f'{alias:32} {results[alias]}')
                        continue
                    steps.append('OS: ' + (verdict.replace('upgrade-os: ', '', 1) if verdict else 'done'))

            # 2. upgrade the engine
            if engine:
                before = self._cmeta_version_on(ctx, h)

                r = self._cmd_run(ctx, h, cmd)
                if self.cm.catch_error(r): return r
                if con:
                    print('')
                    print(f'=== {alias}: {cmd}   (cMeta {before or "?"} before)')
                rr = self._run_local(r['cmd'], capture=False, con=con, verbose=verbose)
                rc = rr.get('returncode', 0)

                after = self._cmeta_version_on(ctx, h)
                if rc != 0:
                    steps.append(f'exit code {rc} (cMeta {after or "?"})')
                elif after and before and after == before:
                    steps.append(f'already {after}')
                else:
                    steps.append(f'{before or "?"} -> {after or "?"}')
            results[alias] = '; '.join(steps) or 'nothing asked'
            if con: print(f'{alias:32} {results[alias]}')
            if rc != 0:
                if explicit:
                    return {'return': 1, 'error': f'{alias}: upgrade {results[alias]}', 'results': results}
                continue        # a failed upgrade is not restarted
            if not restart and not check:
                self._refresh_state(ctx, h, con)        # (a restart probes the host itself afterwards)

            # 3. restart - reboot and bring the servers up on the new engine, as "cx host restart <host>"
            if restart:
                if here and not explicit:
                    steps.append('not restarted (this machine, in a selection)')
                else:
                    if con:
                        print('')
                        print(f'=== {alias}: restart')
                    r = self.restart_(ctx, arg1=alias, yes=yes or quiet, timeout=timeout)
                    if r['return'] > 0:
                        steps.append('restart: ' + str(r.get('error') or r.get('result') or 'failed'))
                        results[alias] = '; '.join(steps)
                        if explicit:
                            return {'return': 1, 'error': f'{alias}: {results[alias]}', 'results': results}
                        if con: print(f'{alias:32} {results[alias]}')
                        continue
                    note = str(r.get('result') or 'restarted')
                    ran = r.get('after_restart') or []
                    failed = [x for x in ran if x.get('returncode', 0) != 0]
                    if ran:
                        note += f', {len(ran)} after_restart command(s)' + (f' ({len(failed)} FAILED)' if failed else '')
                    steps.append(note)
                results[alias] = '; '.join(steps)
                if con: print(f'{alias:32} {results[alias]}')

        return {'return': 0, 'results': results}

    def destroy_(
        self,
        ctx,
        arg1=None,          # the instance (a docker or WSL host made by cx task run get-host--docker / get-host--wsl)
        image=False,        # also remove its image (left alone when another container uses it)
        keep_artifact=False,  # remove the container or distribution, keep the host artifact
        force=False,        # a docker or wsl host declared by hand: remove its container or distribution anyway
    ):
        """
        Destroy an instance cMeta made (cx task run get-host--docker / get-host--wsl): its container is stopped and
        removed through the engine of its parent (a WSL distribution unregistered, its disk with it), the host
        artifact deleted, and with --image its image removed. A docker or wsl host declared by hand needs --force;
        other types are refused. ("rm" and "remove" are the engine's names for "delete", which removes an artifact
        alone - hence "destroy" for the whole instance.)

            cx host destroy my-pc-docker-ubuntu-24.04 [--image]
            cx host destroy my-pc-wsl-ubuntu-26.04
        """
        con = ctx['control'].get('con', False)
        if not arg1:
            return self.cm.error('cx host destroy <instance> [--image] [--keep_artifact]')
        r = self._get_host(ctx, arg1)
        if r['return'] > 0: return r
        h = r['host']
        if h['type'] not in ('docker', 'wsl'):
            return self.cm.error(f'{h["alias"]} is a {h["type"]} host, not an instance: "cx host delete {h["alias"]}" removes an artifact alone')
        made = bool(h['desc'].get('made_from')) or 'made-by-cmeta' in (h['cmeta'].get('tags') or [])
        if not made and not force:
            return self.cm.error(f'{h["alias"]} was not made by cMeta (no made_from): --force removes its {"distribution" if h["type"] == "wsl" else "container"} anyway')

        acc = h['desc'].get('access') or {}
        if h['type'] == 'wsl':
            distro = str(acc.get('distro') or h['alias'])
            cmds = [(f'wsl.exe --terminate {distro}', 'stopped'), (f'wsl.exe --unregister {distro}', 'distribution')]
        else:
            name = acc.get('container') or h['alias']
            engine = self._engine(h)
            cmds = [(f'{engine} rm -f {name}', 'container')]
            if image and acc.get('image'):
                cmds.append((f'{engine} rmi {acc["image"]}', 'image'))

        parent = None
        if h.get('via'):
            rp = self._get_host(ctx, h['via'])
            if rp['return'] > 0: return rp
            if not self._here(rp['host']):
                parent = rp['host']

        done = []
        for cmd, what in cmds:
            run = cmd
            if parent is not None:
                rc = self._cmd_run(ctx, parent, cmd)
                if rc['return'] > 0: return rc
                run = rc['cmd']
            rr = self._run_local(run, capture=True, con=False)
            ok = rr.get('returncode', 1) == 0
            note = '' if ok else (rr.get('stderr', '') or '').strip().splitlines()[-1:] or ['failed']
            done.append(f'{what}: ' + ('removed' if ok else f'not removed ({note[0] if note else "failed"})'))

        if not keep_artifact:
            rd = self.cm.access({'category': 'host,' + self.cmeta['artifact'], 'command': 'delete', 'arg1': h['alias'], 'force': True, 'con': False})
            if rd['return'] > 0: return rd
            done.append('artifact: deleted')

        if con:
            print (f'cMeta info: {h["alias"]}: ' + '; '.join(done))
        return {'return': 0, 'alias': h['alias'], 'done': done}

    ############################################################
    def snapshot_(
        self,
        ctx,
        arg1=None,          # the instance (a docker, podman or WSL host cMeta made)
        name=None,          # the snapshot's name (default: the time, 20261015-2355)
        note=None,          # a word about it, kept in the record
        force=False,        # a docker or wsl host declared by hand
    ):
        """
        Keep the state of an instance: a docker or podman container is committed to an image
        (cmeta/snapshot:<instance>-<name>; the container keeps running), a WSL distribution exported to a tar
        next to its disk (<location>/snapshots/<name>.tar). The host artifact records it under "snapshots"
        (name, time, image or file, note); "cx host restore <instance> [--name=<snapshot>]" brings the instance
        back to it, "cx host show <instance>" lists them.

            cx host snapshot my-pc-docker-ubuntu-26.04
            cx host snapshot my-pc-docker-ubuntu-26.04 --name=before-torch --note="the clean toolchain"
        """
        con = ctx['control'].get('con', False)
        if not arg1:
            return self.cm.error('cx host snapshot <instance> [--name=<name>] [--note=<text>]')
        r = self._instance(ctx, arg1, force)
        if r['return'] > 0: return r
        h = r['host']
        acc = h['desc'].get('access') or {}

        snap = re.sub(r'[^A-Za-z0-9._-]+', '-', str(name or '')).strip('-.') or datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        record = {'name': snap, 'time': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
        if note:
            record['note'] = str(note)

        if h['type'] == 'wsl':
            distro = str(acc.get('distro') or h['alias'])
            folder = os.path.join(self._wsl_location(h, distro), 'snapshots')
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                return self.cm.error(f'cannot make {folder}: {e}')
            record['file'] = os.path.join(folder, snap + '.tar')
            cmd = f'wsl.exe --export {distro} {self.cm.utils.files.quote_path(record["file"])}'
        else:
            record['image'] = f'cmeta/snapshot:{h["alias"]}-{snap}'
            cmd = f'{self._engine(h)} commit {acc.get("container") or h["alias"]} {record["image"]}'

        rr = self._engine_cmd(ctx, h, cmd, timeout=1800)
        if rr['return'] > 0: return rr
        if rr.get('returncode', 1) != 0:
            err = (rr.get('stderr') or '').strip()
            hint = ''
            if 'content digest' in err and 'not found' in err:
                # Docker Desktop's image store: the container's image was rebuilt under the same tag while it ran
                hint = ' - the instance\'s image was rebuilt under it: cx host destroy, then make it again before a snapshot'
            return self.cm.error(f'"{cmd}" failed: {err}{hint}')

        r = self._record_snapshot(h, record)
        if r['return'] > 0: return r
        if con:
            print (f'cMeta info: {h["alias"]}: snapshot {snap} kept as {record.get("image") or record.get("file")}; back to it with "cx host restore {h["alias"]} --name={snap}"')
        return {'return': 0, 'alias': h['alias'], 'snapshot': record}

    def _restore_instance(
        self,
        ctx,
        arg1=None,          # the instance
        name=None,          # the snapshot (default: the last one)
        force=False,        # a docker or wsl host declared by hand
    ):
        """
        "cx host restore <instance>": bring an instance back to a snapshot (the last one by default): a docker or podman container is removed
        and made again from the snapshot's image with the instance's run arguments (its entrypoint plugs the
        repositories and indexes again; what was set up inside after the snapshot is gone), a WSL distribution
        unregistered and imported again from the snapshot's tar.

            cx host restore my-pc-docker-ubuntu-26.04
            cx host restore my-pc-docker-ubuntu-26.04 --name=before-torch
        """
        con = ctx['control'].get('con', False)
        if not arg1:
            return self.cm.error('cx host restore <instance> [--name=<snapshot>]')
        r = self._instance(ctx, arg1, force)
        if r['return'] > 0: return r
        h = r['host']
        acc = h['desc'].get('access') or {}

        snapshots = [s for s in (h['desc'].get('snapshots') or []) if isinstance(s, dict)]
        if not snapshots:
            return self.cm.error(f'{h["alias"]} has no snapshot yet: cx host snapshot {h["alias"]}')
        if name:
            chosen = [s for s in snapshots if s.get('name') == str(name)]
            if not chosen:
                return self.cm.error(f'{h["alias"]} has no snapshot "{name}" (it has: {", ".join(str(s.get("name")) for s in snapshots)})')
            record = chosen[-1]
        else:
            record = snapshots[-1]

        if h['type'] == 'wsl':
            distro = str(acc.get('distro') or h['alias'])
            tar = str(record.get('file') or '')
            if not os.path.isfile(tar):
                return self.cm.error(f'the snapshot file {tar} is gone')
            location = self._wsl_location(h, distro)
            for cmd in (f'wsl.exe --terminate {distro}', f'wsl.exe --unregister {distro}',
                        f'wsl.exe --import {distro} {self.cm.utils.files.quote_path(location)} {self.cm.utils.files.quote_path(tar)} --version 2'):
                rr = self._engine_cmd(ctx, h, cmd, timeout=1800)
                if rr['return'] > 0: return rr
                if rr.get('returncode', 1) != 0 and not cmd.startswith('wsl.exe --terminate'):
                    return self.cm.error(f'"{cmd}" failed: {(rr.get("stderr") or rr.get("stdout") or "").strip()}')
        else:
            engine = self._engine(h)
            container = acc.get('container') or h['alias']
            image = str(record.get('image') or '')
            keep = acc.get('keepalive') or 'sleep infinity'
            run_args = acc.get('run_args') or ''
            for cmd in (f'{engine} rm -f {container}',
                        f'{engine} run -d --name {container} {run_args} {image} {keep}'.replace('  ', ' ')):
                rr = self._engine_cmd(ctx, h, cmd, timeout=600)
                if rr['return'] > 0: return rr
                if rr.get('returncode', 1) != 0:
                    return self.cm.error(f'"{cmd}" failed: {(rr.get("stderr") or "").strip()}')
            self._wait_ready(ctx, h)

        if con:
            print (f'cMeta info: {h["alias"]}: back to the snapshot {record.get("name")} of {record.get("time")}')
        return {'return': 0, 'alias': h['alias'], 'snapshot': record}

    def _copy_instance(self, ctx, h, src, dst, into, files=None, dry_run=False, con=False):
        """
        A file or folder between this machine and an instance on it: into the instance (push: a folder's contents
        land in --to, a file lands at --to) or out of it (pull: into the local folder). docker: "docker cp", the
        copied files given to the instance's user; wsl: cp through wsl.exe, this machine's drives seen as
        /mnt/<drive>. An instance carried by another machine is refused: push to that machine first.
        """
        if h.get('via'):
            rp = self._get_host(ctx, h['via'])
            if rp['return'] > 0: return rp
            if not self._here(rp['host']):
                return self.cm.error(f'{h["alias"]} is carried by {h["via"]}: push to that machine, then copy there (cx host run {h["via"]} ...)')

        acc = h['desc'].get('access') or {}
        user = str(acc.get('user') or '')
        home = '/root' if user == 'root' else (f'/home/{user}' if user else '')

        def inside(path):
            path = str(path).replace('\\', '/')
            if path.startswith('~/'):
                path = path[2:]
            if not path.startswith('/'):
                path = (home + '/' + path) if home else ('/' + path)
            return path

        q = shlex.quote
        patterns = [p for p in (files or []) if p] if not into else []
        landing = dst
        if into:
            remote = inside(dst)
            is_dir = os.path.isdir(src)
            make = remote if is_dir else remote.rsplit('/', 1)[0] or '/'
            if h['type'] == 'docker':
                engine = self._engine(h)
                container = acc.get('container') or h['alias']
                cmds = [f'{engine} exec {container} mkdir -p {q(make)}',
                        f'{engine} cp {self.cm.utils.files.quote_path(src + (os.sep + "." if is_dir else ""))} {container}:{remote}']
                if user:
                    cmds.append(f'{engine} exec -u root {container} chown -R {user}:{user} {q(remote)}')
            else:
                distro = str(acc.get('distro') or h['alias'])
                mnt = self._wsl_mnt(src) + ('/.' if is_dir else '')
                copy = f'mkdir -p {q(make)} && cp -r {q(mnt)} {q(remote)}'
                cmds = [f'wsl.exe -d {distro}' + (f' --user {user}' if user else '') + f' -- sh -c "{copy}"']
            what = {'host': h['alias'], 'local': src, 'remote': remote}
        else:
            remote = inside(src)
            if h['type'] == 'docker':
                engine = self._engine(h)
                container = acc.get('container') or h['alias']
                # docker cp cannot choose files: with --files the folder lands in a folder of its own inside the local
                # one, and only the matching files move on. Before 2026-10-17 it landed in the local folder itself
                # and every file there that did not match was deleted - also the files that were there before
                if patterns and not dry_run:
                    landing = tempfile.mkdtemp(prefix='.cmeta-pull-', dir=dst)
                # a folder's contents into the local folder ("/." as docker cp reads it), a file into it
                cmds = [f'{engine} cp {container}:{remote}/. {self.cm.utils.files.quote_path(landing)}',
                        f'{engine} cp {container}:{remote} {self.cm.utils.files.quote_path(landing)}']
            else:
                distro = str(acc.get('distro') or h['alias'])
                mnt = self._wsl_mnt(dst)
                if patterns:
                    # only the matching files, with their sub-folders: the rest is not wanted, and a whole folder can
                    # hold names a drive of this machine cannot take (two that differ by case only, on NTFS)
                    names = ' -o '.join(f'-name {q(p)}' for p in patterns)
                    folder = f'cd {q(remote)} && find . -type f \\( {names} \\) -exec cp --parents -t {q(mnt)} {{}} +'
                else:
                    folder = f'cp -r {q(remote + "/.")} {q(mnt)}'
                copy = f'if [ -d {q(remote)} ]; then {folder}; else cp {q(remote)} {q(mnt + "/")}; fi'
                cmds = [f'wsl.exe -d {distro}' + (f' --user {user}' if user else '') + f' -- sh -c "{copy}"']
            what = {'host': h['alias'], 'remote': remote, 'local': dst}

        if dry_run:
            if con:
                for cmd in cmds:
                    print (f'DRY RUN: {cmd}')
            return dict(what, **{'return': 0, 'dry_run': True, 'cmds': cmds})

        file_form = False
        try:
            for i, cmd in enumerate(cmds):
                rr = self._run_local(cmd, capture=True, con=False, timeout=1800)
                ok = rr.get('returncode', 1) == 0
                if not into and h['type'] == 'docker':
                    if ok:
                        file_form = i == 1
                        break                               # the folder form worked; the file form is the alternative
                    if i == 0:
                        continue
                if not ok:
                    return self.cm.error(f'"{cmd}" failed: {(rr.get("stderr") or rr.get("stdout") or "").strip()}')

            # pull --files from a container: the matching files of what came move into the local folder with their
            # sub-folders (a file named by itself comes whatever its name); nothing else there is touched
            if landing != dst:
                for folder, _, names in os.walk(landing):
                    rel = os.path.relpath(folder, landing)
                    for name in names:
                        if file_form or any(fnmatch.fnmatch(name, p) for p in patterns):
                            target = os.path.normpath(os.path.join(dst, rel))
                            os.makedirs(target, exist_ok=True)
                            os.replace(os.path.join(folder, name), os.path.join(target, name))
        finally:
            if landing != dst:
                shutil.rmtree(landing, ignore_errors=True)

        if con:
            print (f'{h["alias"]}: ' + (f'{src} -> {remote}' if into else f'{remote} -> {dst}'))
        return dict(what, **{'return': 0})

    @staticmethod
    def _wsl_mnt(path):
        """A path of this machine as WSL sees it: D:\\x\\y -> /mnt/d/x/y."""
        p = os.path.abspath(path).replace('\\', '/')
        if len(p) > 1 and p[1] == ':':
            return '/mnt/' + p[0].lower() + p[2:]
        return p

    def _instance(self, ctx, arg1, force):
        """An instance cMeta made (a docker or wsl host with made_from), or any docker/wsl host with --force."""
        r = self._get_host(ctx, arg1)
        if r['return'] > 0: return r
        h = r['host']
        if h['type'] not in ('docker', 'wsl'):
            return self.cm.error(f'{h["alias"]} is a {h["type"]} host, not an instance (docker, podman or WSL)')
        made = bool(h['desc'].get('made_from')) or 'made-by-cmeta' in (h['cmeta'].get('tags') or [])
        if not made and not force:
            return self.cm.error(f'{h["alias"]} was not made by cMeta (no made_from): --force takes it anyway')
        return {'return': 0, 'host': h}

    def _wsl_location(self, h, distro):
        """The folder of a WSL instance's disk: made_from.location, else the default of get-host--wsl."""
        return str((h['desc'].get('made_from') or {}).get('location') or
                   os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'cmeta', 'wsl', distro))

    def _engine_cmd(self, ctx, h, cmd, timeout=600):
        """An engine or wsl.exe command for an instance, run here or on the parent that carries it; captured."""
        parent = None
        if h.get('via'):
            rp = self._get_host(ctx, h['via'])
            if rp['return'] > 0: return rp
            if not self._here(rp['host']):
                parent = rp['host']
        if parent is not None:
            rc = self._cmd_run(ctx, parent, cmd)
            if rc['return'] > 0: return rc
            cmd = rc['cmd']
        rr = self._run_local(cmd, capture=True, con=False, timeout=timeout)
        rr['return'] = 0
        return rr

    def _record_snapshot(self, h, record):
        """The snapshot appended to the host artifact's _desc (yaml or json, whichever it has)."""
        for name in ('_desc.yaml', '_desc.json'):
            path = os.path.join(h['path'], name)
            if os.path.isfile(path):
                break
        else:
            return self.cm.error(f'{h["alias"]} has no _desc file to record the snapshot in')
        r = self.cm.utils.files.safe_read_yaml_or_json(path)
        if r['return'] > 0: return r
        desc = r.get('data') or {}
        desc.setdefault('snapshots', []).append(record)
        return self.cm.utils.files.safe_write_file(path, desc, atomic=True, sort_keys=False, logger=self.logger)

    def _wait_ready(self, ctx, h, timeout=600):
        """
        True once a container's entrypoint has plugged and indexed its repositories (the file ~/.cmeta-ready it
        writes at the end; an image without that file in its entrypoint counts as ready at once): after "cx host
        up" or a restore, so that the next command inside finds every artifact.
        """
        check = 'if grep -q cmeta-ready "$HOME/entrypoint.sh" 2>/dev/null; then test -f "$HOME/.cmeta-ready"; else true; fi'
        r = self._cmd_run(ctx, h, check)
        if r['return'] > 0:
            return False
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            rr = self._run_local(r['cmd'], capture=True, con=False, timeout=60)
            if rr.get('returncode', 1) == 0:
                return True
            time.sleep(2)
        return False

    def _cmeta_version_on(self, ctx, h):
        """The 'cMeta version X' a host reports, or None."""
        r = self._cmd_run(ctx, h, 'cx --version')
        if r['return'] > 0:
            return None
        rr = self._run_local(r['cmd'], capture=True, con=False, timeout=120)
        for line in (rr.get('stdout', '') or '').splitlines():
            if 'cmeta version' in line.lower():
                return line.split('version', 1)[-1].strip()
        return None

    ############################################################
    def sync_endpoint_(self, ctx, arg1=None):
        """Resolve a host's SSH transport for sync tasks, without connecting or changing the host."""
        if not arg1:
            return self.cm.error('name one SSH host')
        r = self._get_host(ctx, arg1)
        if self.cm.catch_error(r, fail16=True): return r
        h = r['host']
        if h['type'] != 'ssh' or h.get('via'):
            return self.cm.error('sync endpoints currently require a direct SSH host')
        r = self._ssh_parts(h)
        if self.cm.catch_error(r, fail16=True): return r
        # the host's repositories folder (declared sync.repos_path, else the probed home, else ~/CMETA/repos):
        # where a sync task keeps the host's side of its backups (<repos>/local/result/sync-backup--...)
        return dict(r, host_uid=h['uid'], host_alias=h['alias'],
                    repos=self._sync_repos_path(h, h['desc'].get('sync') or {})[0])

    def show_(
        self,
        ctx,
        arg1=None,          # host alias
        project=None,      # named environment; omitted: the host's global environment
    ):
        """
        Everything known about a host: the declared _desc.yaml, then the observed state.yaml.

            cx host show lab-laptop-ubuntu
        """

        con = ctx['control'].get('con', False)

        if not arg1:
            return self.cm.error('which host? cx host show <host>')

        r = self._get_host(ctx, arg1, project=project)
        if self.cm.catch_error(r): return r
        h = r['host']

        if con:
            import yaml
            print(f'# {h["alias"]}  ({h["path"]})')
            print('')
            print('# --- declared (_desc.yaml)')
            print(yaml.safe_dump(h['desc'], sort_keys=False, allow_unicode=True, width=120).rstrip())
            print('')
            print('# --- observed (state.yaml)')
            print(yaml.safe_dump(h['state'], sort_keys=False, allow_unicode=True, width=120).rstrip()
                  if h['state'] else '# never probed - run: cx host probe ' + h['alias'])

        return {'return': 0, 'host': {'alias': h['alias'], 'path': h['path'], 'desc': h['desc'], 'state': h['state']}}

    ############################################################
    # Selection and loading
    ############################################################

    def _project_host(self, h, name):
        """Select an environment without changing the cached host or inheriting its global sync."""
        desc = h.get('host_desc') or h['desc']
        project = (desc.get('projects') or {}).get(name)
        if not isinstance(project, dict):
            return self.cm.error(f'host "{h["alias"]}" has no project "{name}"')
        for key in ('path', 'venv'):
            if not project.get(key):
                return self.cm.error(f'project "{name}" needs {key}')
        if not (project.get('cmeta') or {}).get('home'):
            return self.cm.error(f'project "{name}" needs cmeta.home')
        if self._shell(h).strip() in ('cmd', 'none') or h['type'] == 'adb':
            return self.cm.error('project environments require a POSIX or PowerShell host shell')
        selected = copy.deepcopy(h)
        selected['host_desc'] = copy.deepcopy(desc)
        selected['project'] = name
        selected['project_desc'] = copy.deepcopy(project)
        for key in ('cmeta', 'sync', 'commands'):
            selected['desc'][key] = copy.deepcopy(project.get(key) or {})
        root_state = h.get('host_state') or h.get('state') or {}
        selected['host_state'] = copy.deepcopy(root_state)
        selected['state'] = copy.deepcopy((root_state.get('projects') or {}).get(name) or {})
        return {'return': 0, 'host': selected}

    def _project_command(self, h, cmd):
        """An explicit project always selects its venv and cMeta home, or fails before the command."""
        p = h['project_desc']
        venv, path, home = str(p['venv']), str(p['path']), str(p['cmeta']['home'])
        if self._shell(h).strip() in ('powershell', 'pwsh'):
            q = lambda value: "'" + value.replace("'", "''") + "'"
            return (f'if (!(Test-Path -LiteralPath {q(venv + "/Scripts/cx.exe")})) {{ throw "Project cx missing" }}; '
                    f'Set-Location -LiteralPath {q(path)} -ErrorAction Stop; '
                    f'$env:VIRTUAL_ENV={q(venv)}; $env:CMETA_HOME={q(home)}; '
                    f'$env:PATH={q(venv + "/Scripts;")}+$env:PATH; '
                    'Remove-Item Env:CMETA_INTERNAL_REPO_PATH -ErrorAction SilentlyContinue; ' + cmd)
        q = shlex.quote
        command_shell = q(shlex.split(self._shell(h))[0])
        return (f'test -x {q(venv + "/bin/cx")} && cd {q(path)} && '
                f'. {q(venv + "/bin/activate")} && export CMETA_HOME={q(home)} && '
                'unset CMETA_INTERNAL_REPO_PATH && ' + command_shell + ' -c ' + q(cmd))

    def _global_command_here(self, h, cmd):
        """On the host itself, don't let an activated project override its declared global cx."""
        home = (h['desc'].get('cmeta') or {}).get('home')
        cx = (h.get('state') or {}).get('cx')
        if not home or not cx or self._shell(h).strip() in ('powershell', 'pwsh', 'cmd', 'none'):
            return cmd
        active = os.environ.get('VIRTUAL_ENV')
        paths = os.environ.get('PATH', '').split(os.pathsep)
        if active:
            active_bin = os.path.normpath(os.path.join(active, 'bin'))
            paths = [p for p in paths if os.path.normpath(p) != active_bin]
        paths.insert(0, os.path.dirname(cx))
        q = shlex.quote
        return (f'test -x {q(cx)} && export CMETA_HOME={q(str(home))} && '
                f'export PATH={q(os.pathsep.join(paths))} && '
                'unset VIRTUAL_ENV CONDA_PREFIX CMETA_INTERNAL_REPO_PATH && '
                + q(shlex.split(self._shell(h))[0]) + ' -c ' + q(cmd))

    def _project_rows(self, h):
        desc = h.get('host_desc') or h['desc']
        names = [h['project']] if h.get('project') else list(desc.get('projects') or {})
        rows = []
        for name in names:
            p = desc['projects'][name]
            st = h['state'] if h.get('project') else ((h.get('state') or {}).get('projects') or {}).get(name, {})
            server = (h.get('project_status') or {}).get(name) or st.get('server') or {}
            if self._retired(h):
                server = {'status': 'retired', 'url': (p.get('server') or {}).get('url')}
            rows.append({'alias': name, 'path': p.get('path'), 'cmeta': st.get('cmeta_version', '-'),
                         'aops': st.get('aops_version', '-'), 'server': server,
                         'status': server.get('status', 'not checked'), 'probed': st.get('probed_at'),
                         # the public URLs of the server checked from this machine (status: _public_status_all)
                         'public': list((h.get('public_status') or {}).get(name) or [])})
        return rows

    @staticmethod
    def _public_urls(server):
        """The URLs of a project's server checked FROM HERE, not through the host: its "public" list (a string or a
        list), else its "url" when that is not a loopback, private or link-local address - a site behind a tunnel or
        a proxy is reachable from anywhere, and a host whose ssh is down can still serve it."""
        urls = server.get('public')
        if isinstance(urls, str):
            urls = [urls]
        if urls:
            return [str(u) for u in urls if u]
        url = str(server.get('url') or '')
        host = urllib.parse.urlsplit(url).hostname or ''
        if not url or not host:
            return []
        try:
            ip = ipaddress.ip_address(host)
            # 100.64.0.0/10 is the shared address space Tailscale uses: ipaddress does not call it private
            private = ip.is_loopback or ip.is_private or ip.is_link_local or ip in ipaddress.ip_network('100.64.0.0/10')
        except ValueError:
            private = host == 'localhost' or host.endswith(('.local', '.localhost', '.internal'))
        return [] if private else [url]

    def _public_status_all(self, hosts, timeout=DEFAULT_STATUS_TIMEOUT):
        """The public URLs of every project's server checked from this machine, all at once: "works" (HTTP 2xx or
        3xx, a redirect not followed - a sign-in page answers 303), "http <code>", "timeout", "unreachable". Kept in
        h['public_status'] = {project: [{'url', 'status', 'http_status', 'checked_at'}]}."""
        from concurrent.futures import ThreadPoolExecutor

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect())
        jobs = []
        for h in hosts:
            h['public_status'] = {}
            if self._retired(h):
                continue
            desc = h.get('host_desc') or h['desc']
            names = [h['project']] if h.get('project') else list(desc.get('projects') or {})
            for name in names:
                for url in self._public_urls(((desc.get('projects') or {}).get(name) or {}).get('server') or {}):
                    jobs.append((h, name, url))

        def check(job):
            h, name, url = job
            result = {'url': url, 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'cmeta-host-status'})
                try:
                    with opener.open(request, timeout=float(timeout)) as response:
                        status = response.status
                except urllib.error.HTTPError as error:
                    status = error.code
                result.update(http_status=status, status='works' if 200 <= status < 400 else f'http {status}')
            except Exception as error:
                reason = getattr(error, 'reason', error)
                timed_out = isinstance(reason, (TimeoutError, socket.timeout)) or 'timed out' in str(error).lower()
                result['status'] = 'timeout' if timed_out else 'unreachable'
            return job, result

        if jobs:
            with ThreadPoolExecutor(max_workers=min(16, len(jobs))) as pool:
                for (h, name, url), result in pool.map(check, jobs):
                    h['public_status'].setdefault(name, []).append(result)

    def _project_details(self, hosts, columns):
        """{host alias: [project row]}: the cells of each project by table column, printed aligned under its
        host's row (a server row: its status, health URL and versions); the text left over follows the last column."""
        out = {}
        for h in hosts:
            declared = (h.get('host_desc') or h['desc']).get('projects') or {}
            rows = []
            for p in self._project_rows(h):
                # a host that is down or a failed check has no URL in its result: show the declared one
                url = (p['server'] or {}).get('url') or ((declared.get(p['alias']) or {}).get('server') or {}).get('url', '')
                probed = p['probed'] or ''
                row = {'alias': '  * ' + p['alias'], 'type': 'server' if url else 'project', 'status': p['status'],
                       'cmeta': p['cmeta'], 'aops': p['aops'], 'probed': probed[:16].replace('T', ' ')}
                if 'ADDRESS' in columns:
                    row['address'] = url
                    row['extra'] = f'(cMeta: {p["cmeta"]}  AOPS: {p["aops"]})'
                else:
                    # cx host ls: the versions have their own columns; without STATUS, the status saved by the last check
                    row['extra'] = url + ('' if 'STATUS' in columns or not p['server'] else f'  ({p["status"]} at the last check)')
                rows.append(row)
                # the public URLs of the server, checked from here: one line each under the project
                for pub in p.get('public') or []:
                    site = site_label(pub['url'])
                    prow = {'alias': '      ' + site, 'type': 'web', 'status': pub.get('status', ''), 'cmeta': '', 'aops': '', 'probed': ''}
                    if 'ADDRESS' in columns:
                        prow['address'] = pub['url']
                        prow['extra'] = f'(HTTP {pub["http_status"]})' if pub.get('http_status') else ''
                    else:
                        prow['extra'] = pub['url']
                    rows.append(prow)
            out[h['alias']] = rows
        return out

    def _project_status_all(self, ctx, hosts, timeout=DEFAULT_STATUS_TIMEOUT, cmd_timeout=DEFAULT_STATUS_CMD_TIMEOUT):
        """One bounded remote HTTP check batch per reachable host; never start a project server."""
        from concurrent.futures import ThreadPoolExecutor

        def one(h):
            desc = h.get('host_desc') or h['desc']
            names = [h['project']] if h.get('project') else list(desc.get('projects') or {})
            if not names: return
            if self._retired(h):
                h['project_status'] = {name: {'status': 'retired'} for name in names}
                return
            if not self._usable(h):
                h['project_status'] = {name: {'status': 'host ' + str(h.get('status') or 'down')} for name in names}
                return
            servers = {}
            for name in names:
                server = desc['projects'][name].get('server') or {}
                servers[name] = server
            # Execute using the host's ordinary Python, so a missing project venv is not a false host outage.
            code = '''import concurrent.futures, datetime, json, urllib.request, urllib.error
servers = json.loads(SERVERS)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None
def check(item):
    name, cfg = item
    url = cfg.get('url')
    result = {'url': url, 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if not url: return name, dict(result, status='not configured')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        try:
            with opener.open(url, timeout=TIMEOUT) as response: status = response.status
        except urllib.error.HTTPError as error: status = error.code
        expected = cfg.get('expected_status')
        if isinstance(expected, int): expected = [expected]
        ok = status in expected if expected is not None else 200 <= status < 400
        result.update(status='up' if ok else 'unhealthy', http_status=status)
    except Exception as error:
        result.update(status='timeout' if isinstance(getattr(error, 'reason', error), TimeoutError) else 'down')
    return name, result
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    print(json.dumps(dict(pool.map(check, servers.items()))))
'''.replace('SERVERS', repr(json.dumps(servers))).replace('TIMEOUT', repr(float(timeout)))
            base = copy.deepcopy(h)
            base['desc'] = copy.deepcopy(desc)
            base.pop('project', None)
            if self._shell(base).strip() in ('powershell', 'pwsh'):
                import base64
                encoded = base64.b64encode(code.encode()).decode()
                script = "python -c \"import base64;exec(base64.b64decode('" + encoded + "'))\"\n"
            else:
                script = "python3 - <<'CMETA_PROJECT_STATUS'\n" + code + 'CMETA_PROJECT_STATUS\n'
            r = self._temp_script(script, suffix='.ps1' if self._shell(base).strip() in ('powershell', 'pwsh') else '.sh')
            if r['return'] == 0:
                r = self._cmd_stdin(ctx, base, r['path'])
            try:
                if r['return'] > 0: raise ValueError(r.get('error'))
                rr = self._run_local(r['cmd'], capture=True, timeout=int(cmd_timeout), con=False)
                if rr.get('returncode', 1) != 0: raise ValueError('remote check failed')
                h['project_status'] = json.loads(rr.get('stdout', '').strip().splitlines()[-1])
            except (ValueError, IndexError):
                h['project_status'] = {name: {'status': 'check failed'} for name in names}

        with ThreadPoolExecutor(max_workers=min(16, len(hosts) or 1)) as pool:
            list(pool.map(one, hosts))

    def _select(self, ctx, arg1=None, tags=None, machine=None, type=None, project=None):
        """Find host artifacts (base find) and load their _desc.yaml and state.yaml."""

        if arg1 is not None and arg1 in self._host_cache and not (tags or machine or type or project):
            return {'return': 0, 'hosts': [self._host_cache[arg1]]}

        # Program contexts contain loaded API modules, which cannot be deep-copied.
        # Keep the context shared, as for other nested access() calls.
        p = self._prepare_input_from_ctx(ctx, base=True)
        p.update({'command': 'find', 'ctx': ctx, 'arg1': arg1, 'tags': tags, 'con': False})
        r = self.cm.access(p)
        if r['return'] > 0 and r['return'] != 16: return r

        hosts = []
        for a in r.get('artifacts', []):
            # Alias-only lookups follow redirects in base find; fleet selections skip the stubs.
            if (a.get('cmeta') or {}).get('migrated_to'):
                continue
            h = self._load_host(a)
            if machine and h['machine'] != machine: continue
            if type and h['type'] != type: continue
            hosts.append(h)

        hosts.sort(key=lambda x: x['alias'])
        if project:
            selected = []
            for h in hosts:
                r = self._project_host(h, project)
                if r['return'] > 0: return r
                selected.append(r['host'])
            hosts = selected
        return {'return': 0, 'hosts': hosts}

    def _get_host(self, ctx, alias, project=None):
        """Exactly one host."""
        r = self._select(ctx, alias, project=project)
        if r['return'] > 0: return r
        hosts = r['hosts']
        if len(hosts) == 0:
            return self.cm.error(f'host "{alias}" not found')
        if len(hosts) > 1:
            return self.cm.error(f'"{alias}" matches {len(hosts)} hosts: ' + ', '.join(h['alias'] for h in hosts))
        return {'return': 0, 'host': hosts[0]}

    def _load_host(self, a):
        path = a['path']
        parts = a.get('cmeta_ref_parts', {})
        alias = parts.get('artifact_alias') or parts.get('artifact_uid') or os.path.basename(path)
        desc = self._read_yaml(os.path.join(path, DESC_FILE))
        state = self._read_yaml(os.path.join(path, STATE_FILE))
        # Wireless ports/transport names can change; the observed endpoint is state, not configuration.
        if desc.get('type') == 'adb' and (desc.get('access') or {}).get('wireless'):
            observed = state.get('adb_connection') or {}
            if observed.get('serial'):
                desc.setdefault('access', {})['serial'] = observed['serial']
        # "via" is one parent, or a list of candidate parents for a device that moves between machines
        # (a phone or a tablet plugged into whichever machine is at hand): then the parent that saw it
        # last (state.yaml via_now) is the working guess until _resolve_via asks around
        via_raw = desc.get('via')
        if isinstance(via_raw, (list, tuple)):
            via_list = [self._ref_alias(v) for v in via_raw]
        else:
            via_list = [self._ref_alias(via_raw)]
        via_list = [v for v in via_list if v]
        via_now = state.get('via_now') if len(via_list) > 1 else None
        h = {
            'alias': alias,
            'uid': parts.get('artifact_uid'),
            'path': path,
            'cmeta': a.get('cmeta', {}),
            'desc': desc,
            'state': state,
            'type': str(desc.get('type') or 'ssh'),
            'machine': self._ref_alias(desc.get('machine')),
            'via': via_now if via_now in via_list else (via_list[0] if via_list else None),
            'via_list': via_list,
            'via_resolved': len(via_list) <= 1,
            'via_seen': None,
            'status': None,
        }
        self._host_cache[alias] = h
        return h

    def _read_yaml(self, path):
        if not os.path.isfile(path):
            return {}
        r = self.cm.utils.files.safe_read_file(path, logger=self.logger)
        if r['return'] > 0:
            return {}
        return r.get('data') or {}

    @staticmethod
    def _ref_alias(ref):
        """'machine,uid::my-pc,uid' or 'my-pc' -> 'my-pc'."""
        if not ref:
            return None
        s = str(ref)
        if '::' in s:
            s = s.split('::')[-1]
        return s.split(',')[0].strip()

    @staticmethod
    def _csv(value):
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            items = []
            for v in value:
                items += [x.strip() for x in str(v).split(',')]
        else:
            items = [x.strip() for x in str(value).split(',')]
        return [x for x in items if x]

    @staticmethod
    def _is_explicit(arg1, hosts):
        """One host named outright (no wildcard): then being down is an error, not a skip."""
        return bool(arg1) and '*' not in str(arg1) and '?' not in str(arg1) and len(hosts) == 1

    ############################################################
    # A device that moves between machines: via = [parent, parent, ...]
    ############################################################

    def _resolve_via(self, ctx, h, timeout=DEFAULT_STATUS_TIMEOUT, cmd_timeout=DEFAULT_STATUS_CMD_TIMEOUT):
        """
        For a host declared with several parents (via: [a, b, c] - a phone or a tablet plugged into
        whichever machine is at hand): the parent that reaches it now. Every candidate is asked at once
        (a parent that is up runs "adb devices"; a cold fleet then costs the slowest parent, not the sum);
        among the parents that list the host's serial the one recorded in state.yaml (via_now) wins, then
        the declared order: h['via'] points at it and state.yaml remembers it (via_now, via_seen_at).
        Runs once per process; h['via_seen'] says whether any parent sees the device, h['via_tried'] what
        each parent answered and how long it took.
        """
        if h.get('via_resolved'):
            return h.get('via')
        h['via_resolved'] = True
        cands = list(h.get('via_list') or [])
        now = (h.get('state') or {}).get('via_now')
        if now in cands:
            cands.remove(now)
            cands.insert(0, now)
        serial = str((h['desc'].get('access') or {}).get('serial') or '')

        # The parent artifacts first, one after the other (the index is not asked from several threads)
        parents = []
        for alias in cands:
            r = self._get_host(ctx, alias)
            parents.append((alias, r.get('host'), r.get('error')))

        def ask(item):
            alias, p, error = item
            t0 = time.monotonic()
            if p is None:
                return alias, None, f'{alias}: {error}', 0.0
            parent = None if self._here(p) else p
            if parent is not None:
                ps = self._status(ctx, parent, timeout, cmd_timeout)
                if ps != 'up':
                    return alias, None, f'{alias} {ps}', time.monotonic() - t0
            if h['type'] != 'adb':
                return alias, {}, f'{alias}: up', time.monotonic() - t0        # another type with several parents: up is enough
            devices, reason = self._adb_devices(ctx, parent, cmd_timeout)
            dt = time.monotonic() - t0
            if devices is None:
                return alias, None, f'{alias}: {reason}', dt
            if (serial and serial in devices) or (not serial and devices):
                return alias, devices, f'{alias}: connected', dt
            return alias, None, f'{alias}: not connected', dt

        from concurrent.futures import ThreadPoolExecutor
        answers = []
        if parents:
            with ThreadPoolExecutor(max_workers=len(parents)) as ex:
                answers = list(ex.map(ask, parents))

        tried = []
        seen_on = None
        for alias, devices, line, dt in answers:            # in preference order: via_now first, then as declared
            tried.append(f'{line} ({dt:.1f}s)')
            if devices is not None and seen_on is None:
                seen_on = alias
                if devices:
                    h['adb_devices'] = devices
        h['via_tried'] = tried
        h['via_seen'] = seen_on is not None
        if seen_on is not None:
            h['via'] = seen_on
            if seen_on != now:
                self._update_state(h, {'via_now': seen_on,
                                       'via_seen_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')})
        return h['via'] if seen_on is not None else None

    def _update_state(self, h, updates):
        """Merge a few observed keys into the host's state.yaml (read-modify-write, atomic)."""
        path = os.path.join(h['path'], STATE_FILE)
        state = dict(self._read_yaml(path))
        state.update(updates)
        r = self.cm.utils.files.safe_write_file(path, state, atomic=True, sort_keys=False, logger=self.logger)
        if r['return'] == 0:
            h['state'] = state
        return r

    def _adb_cmd(self, parent, args):
        """
        adb with `args` on a parent host (None = this machine): the adb on PATH here, else the copy that
        cMeta set up as a tool - "cx tool run adb" detects it or installs the platform tools on first use,
        and --con- keeps cMeta's own console output out of adb's (the parent's login shell has cx on PATH).
        """
        if parent is None and shutil.which('adb'):
            return 'adb ' + args
        return 'cx tool run adb -q --con- -- ' + args

    def _adb_devices(self, ctx, parent, timeout=DEFAULT_STATUS_CMD_TIMEOUT):
        """
        ({serial: state} as "adb devices" reports them on a parent (None = here), reason): the dict is
        None when adb did not answer and the reason says why ("adb not available", "timeout: no answer
        in 20s on <parent>"). The command is killed at the timeout: a status never waits for a hung adb
        server or ssh. During a status of several hosts (_status_all) a parent is asked once: the moving
        devices ask the same parent at the same moment, the first asker runs the command and the others
        wait for its answer - one ssh login per parent, not one per device.
        """
        batch = self._adb_batch
        if batch is None:
            return self._adb_devices_now(ctx, parent, timeout)
        key = parent['alias'] if parent is not None else None
        with self._adb_lock:
            lock = self._adb_locks.setdefault(key, threading.Lock())
        with lock:
            if key not in batch:
                batch[key] = self._adb_devices_now(ctx, parent, timeout)
            return batch[key]

    def _adb_devices_now(self, ctx, parent, timeout=DEFAULT_STATUS_CMD_TIMEOUT):
        """One "adb devices" on the parent, now (see _adb_devices)."""
        where = f' on {parent["alias"]}' if parent is not None else ''
        cmd = self._adb_cmd(parent, 'devices')
        if parent is not None:
            r = self._cmd_run(ctx, parent, cmd)
            if r['return'] > 0:
                return None, f'adb not available{where}: {r["error"]}'
            cmd = r['cmd']
        rr = self._run_quick(cmd, timeout)
        if rr.get('timeout'):
            return None, f'timeout: no answer in {int(timeout)}s{where}'
        if rr.get('returncode', 1) != 0:
            return None, f'adb not available{where}'
        out = {}
        for line in (rr.get('stdout', '') or '').splitlines():
            line = line.strip()
            if not line or line.lower().startswith('list of') or line.startswith('*'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
        return out, 'ok'

    @staticmethod
    def _run_quick(cmd, timeout):
        """
        A status check: `cmd` through the local shell, output captured, the whole process tree killed at
        the timeout (the engine's run helper waits for a hung child; a shell's child, ssh.exe, would keep
        the pipes open after the shell alone is killed). {'returncode', 'stdout', 'stderr', 'timeout'}.
        No check reads stdin, so it is closed: Windows' ssh.exe on a console stdin (a cserver or a cx started in
        cmd.exe) waits for a key after the remote command ended - every check through ssh timed out (2026-10-29).
        """
        posix = os.name != 'nt'
        try:
            p = subprocess.Popen(cmd, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=posix)
        except OSError as e:
            return {'returncode': 127, 'stdout': '', 'stderr': str(e), 'timeout': False}
        timed_out = False
        try:
            out, err = p.communicate(timeout=max(1, int(timeout)))
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                if posix:
                    import signal
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                else:
                    subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True)
            except Exception:
                pass
            try:
                p.kill()
            except Exception:
                pass
            try:
                out, err = p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                out, err = b'', b''
        decode = lambda b: (b or b'').decode('utf-8', errors='replace') if isinstance(b, bytes) else (b or '')
        return {'returncode': None if timed_out else p.returncode, 'stdout': decode(out), 'stderr': decode(err),
                'timeout': timed_out}

    @staticmethod
    def _tool_text(value):
        """A probed tool version for the table: '-' when absent; older probes stored the raw command output."""
        s = str(value or '').strip()
        if not s or s == '-':
            return '-'
        low = s.lower()
        if 'not found' in low or 'not recognized' in low or 'no such file' in low or 'cannot access' in low:
            return '-'
        if low.startswith('docker version '):
            s = s[len('docker version '):].split(',')[0].strip()
        elif low.startswith('podman version '):
            s = s[len('podman version '):].strip()
        return s if len(s) <= 22 else s[:21] + '~'

    ############################################################
    # Status
    ############################################################

    @staticmethod
    def _retired(h):
        """Retirement is declared, never inferred from a failed connection or an alias."""
        return (h.get('host_desc') or h.get('desc') or {}).get('retired') is True

    def _status_all(self, ctx, hosts, timeout=DEFAULT_STATUS_TIMEOUT, cmd_timeout=DEFAULT_STATUS_CMD_TIMEOUT):
        """Fill h['status'] (and h['status_time'], seconds) for every host, all checks at once."""
        from concurrent.futures import ThreadPoolExecutor

        def one(h):
            t0 = time.monotonic()
            try:
                h['status'] = self._status(ctx, h, timeout, cmd_timeout)
            except Exception as e:
                h['status'] = f'error: {e}'
            h['status_time'] = time.monotonic() - t0

        if not hosts:
            return
        self._adb_batch = {}          # one "adb devices" per parent for this status, shared by the moving devices
        try:
            with ThreadPoolExecutor(max_workers=min(16, len(hosts))) as ex:
                list(ex.map(one, hosts))
        finally:
            self._adb_batch = None

    def _status(self, ctx, h, timeout=DEFAULT_STATUS_TIMEOUT, cmd_timeout=DEFAULT_STATUS_CMD_TIMEOUT):
        if self._retired(h):
            return 'retired'
        t = h['type']
        acc = h['desc'].get('access') or {}

        if t == 'ssh':
            if self._here(h):
                return 'here'
            addr = acc.get('address') or h['alias']
            port = int(acc.get('port') or DEFAULT_SSH_PORT)
            status = ssh_banner_status(addr, port, timeout)
            if status == 'blocked here':
                # This machine refused Python's own socket: a VPN with per-program split tunnelling may let ssh out
                # and not Python, and every host behind it looked "down" (2026-10-29). The host's own ssh command
                # answers instead.
                status = self._status_through_ssh(ctx, h, cmd_timeout)
            return status

        parent = None
        if len(h.get('via_list') or []) > 1 and t == 'adb':
            # a device that moves: the parent that sees it now; what each parent answered is kept for
            # the result and for -v (h['parents']), the table says only up / down
            self._resolve_via(ctx, h, timeout, cmd_timeout)
            h['parents'] = list(h.get('via_tried') or ['no parent declared'])
            if not h.get('via_seen'):
                return 'down'
        if h.get('via'):
            r = self._get_host(ctx, h['via'])
            if r['return'] > 0:
                return f'error: via {h["via"]} - {r["error"]}'
            parent = r['host']
            if self._here(parent):
                parent = None
            else:
                ps = self._status(ctx, parent, timeout, cmd_timeout)
                if ps != 'up':
                    return f'via {h["via"]} {ps}'

        if t == 'wsl':
            if parent is not None:
                return 'unknown (wsl via a remote host)'
            distro = str(acc.get('distro') or '')
            states = self._wsl_states()
            st = states.get(distro.lower())
            if st is None:
                return 'missing'
            # WSL stops a distro a few seconds after its last command and starts it again for the next
            # one (wsl.exe -d): a stopped distro is reachable - "stopped", not "down" (which the commands
            # that need a host skip; a "down" distro would never be probed or upgraded, seen 2026-10-08)
            return 'up' if st == 'running' else 'stopped'

        if t == 'docker':
            name = acc.get('container') or h['alias']
            engine = self._engine(h)
            cmd = f'{engine} inspect -f "{{{{.State.Status}}}}" {name}'
            if parent is not None:
                r = self._cmd_run(ctx, parent, cmd)
                if r['return'] > 0: return 'error: ' + r['error']
                cmd = r['cmd']
            rr = self._run_quick(cmd, cmd_timeout)
            if rr.get('timeout'):
                return f'timeout ({int(cmd_timeout)}s, {engine} inspect' + (f' on {h["via"]}' if parent is not None else '') + ')'
            if rr.get('returncode', 1) != 0:
                return 'missing'
            return 'up' if rr.get('stdout', '').strip() == 'running' else 'down'

        if t == 'adb':
            serial = str(acc.get('serial') or '')
            devices = h.pop('adb_devices', None)            # what _resolve_via already saw on the parent
            if devices is None:
                devices, reason = self._adb_devices(ctx, parent, cmd_timeout)
                if devices is None:
                    return reason if reason.startswith('timeout') else 'error: ' + reason
            if serial and serial in devices:
                return 'up' if devices[serial] == 'device' else f'down ({devices[serial]})'
            connected = list(devices.keys())
            if not serial:
                # Without a serial any connected device would do - say so instead of claiming "up"
                return f'no serial declared (connected: {", ".join(connected)})' if connected else 'down'
            return 'down'

        return f'unknown type "{t}"'

    def _status_through_ssh(self, ctx, h, cmd_timeout):
        """
        The status of an ssh host whose port this machine's Python may not open (ssh_banner_status said "blocked
        here"): the host's own ssh command (its key, BatchMode) runs "exit" there. up | down (through ssh) |
        timeout (...); "blocked here" when no ssh command can be built. Costs a login, so only after a refusal.
        """
        r = self._cmd_run(ctx, h, 'exit', raw=True)
        if r.get('return', 1) > 0:
            return 'blocked here'
        rr = self._run_quick(r['cmd'], cmd_timeout)
        if rr.get('timeout'):
            return f'timeout ({int(cmd_timeout)}s, through ssh)'
        return 'up' if rr.get('returncode') == 0 else 'down (through ssh)'

    def _usable(self, h):
        """
        A host a command can run on: up, this machine ("here"), or a WSL distro that is merely stopped
        (wsl.exe starts it for the next command). Everything else - down, missing, timeout, error - is skipped.
        """
        return h.get('status') in ('up', 'here') or (h.get('type') == 'wsl' and h.get('status') == 'stopped')

    def _here(self, h):
        """
        This host is the machine the command runs on: the system_id its last probe recorded is the local one;
        without one on either side (never probed, a container without a machine-id), its declared hostname is
        the local one. A recorded system_id that differs decides "not here" even when the hostnames are equal
        (two machines left with the same default hostname).
        """
        if h['type'] != 'ssh':
            return False
        recorded = str((h.get('state') or {}).get('system_id') or '').strip().lower()
        mine = local_system_id()
        if recorded and mine:
            return recorded == mine

        acc = h['desc'].get('access') or {}
        name = acc.get('hostname')
        if not name:
            return False
        me = platform.node().split('.')[0].lower()
        return str(name).split('.')[0].lower() == me

    ############################################################
    def whoami_(
        self,
        ctx,
    ):
        """
        The host artifact of the machine this command runs on: the ssh host whose probed system_id is the local
        one (an id that stays across reboots and renames), else the one whose declared hostname is the local one.
        Prints its alias; returns {'host': alias, 'uid', 'machine', 'by': 'system_id' | 'hostname'}, or
        {'host': ''} when none is (an instance names itself after the hostname then).

            cx host whoami
        """
        con = (ctx.get('control') or {}).get('con', False)
        mine = local_system_id()

        r = self._select(ctx)
        if r['return'] > 0: return r

        by_id = []
        by_name = []
        for h in r['hosts']:
            if h['type'] != 'ssh':
                continue
            recorded = str((h.get('state') or {}).get('system_id') or '').strip().lower()
            if mine and recorded == mine:
                by_id.append(h)
            elif self._here(h):
                by_name.append(h)

        found, by = (by_id, 'system_id') if by_id else (by_name, 'hostname')
        if not found:
            if con:
                print(f'no host artifact is this machine ({platform.node()}): declare one with access: hostname, '
                      f'then "cx host probe <alias>" records its system_id')
            return {'return': 0, 'host': '', 'system_id': mine}

        if len(found) > 1 and con:
            print(f'cMeta warning: {len(found)} hosts match this machine by {by}: '
                  f'{", ".join(x["alias"] for x in found)} - the first is taken')
        h = found[0]
        if con:
            print(h['alias'])
        return {'return': 0, 'host': h['alias'], 'uid': h.get('uid'), 'machine': h['desc'].get('machine'),
                'by': by, 'system_id': mine}

    def _wsl_states(self):
        """{distro lower: 'running' | 'stopped'} - wsl.exe prints UTF-16."""
        try:
            out = subprocess.run(['wsl.exe', '-l', '-v'], capture_output=True, timeout=20).stdout
        except Exception:
            return {}
        text = out.decode('utf-16-le', errors='ignore').replace('\x00', '')
        states = {}
        for line in text.splitlines():
            parts = line.replace('*', ' ').split()
            if len(parts) >= 2 and parts[0].upper() != 'NAME':
                states[parts[0].lower()] = parts[1].lower()
        return states

    ############################################################
    # Drivers: the local command line that reaches a host
    ############################################################

    def _ssh_exe(self):
        if os.name == 'nt':
            p = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'OpenSSH', 'ssh.exe')
            if os.path.isfile(p):
                return p
        return 'ssh'

    def _key_path(self, key):
        """
        The ssh key file: given as <category>::<artifact>/<file> (a cMeta reference, resolved on this
        machine) or as a path (absolute, ~ and environment variables expanded). A reference whose artifact
        is not on this machine - another orchestrator without that private repository - is the copy a secret
        artifact holds of that file ("cx secret which": its files.from and files.names name it); without one,
        as before 2026-10-22, a file of the same name in ~/.ssh, with a warning (names in ~/.ssh can collide).
        """
        if not key:
            return {'return': 0, 'path': None}
        key = str(key)
        if key in self._key_cache:
            return {'return': 0, 'path': self._key_cache[key]}
        if '::' in key:
            i = key.find('::')
            j = key.find('/', i)
            if j < 0:
                return self.cm.error(f'key "{key}" must be <category>::<artifact>/<file in the artifact>')
            cref, rel = key[:j], key[j + 1:]
            r = self.cm.access({'category': self.cmeta['uses_categories']['utils'], 'command': 'find_by_cid',
                                'arg1': cref, 'con': False})
            arts = r.get('artifacts', []) if r['return'] == 0 else []
            if len(arts) > 1:
                return self.cm.error(f'key artifact "{cref}" resolves to {len(arts)} artifacts')
            if len(arts) == 1:
                path = os.path.join(arts[0]['path'], *rel.split('/'))
            else:
                rs = self.cm.access({'category': self.cmeta['uses_categories'].get('secret', 'secret,9d63451ea1f14010'), 'command': 'which',
                                     'arg1': key, 'con': False})
                if rs.get('return', 1) == 0 and rs.get('path'):
                    path = rs['path']
                else:
                    path = os.path.join(os.path.expanduser('~'), '.ssh', os.path.basename(rel))
                    if not os.path.isfile(path):
                        return self.cm.error(f'key artifact "{cref}" is not on this machine, no secret holds a copy of the key '
                                             f'("cx secret which {key}") and ~/.ssh/{os.path.basename(rel)} does not exist either')
                    print(f'cMeta warning: the key "{key}" is taken from {path} (its artifact is not on this machine and no '
                          f'secret holds a copy: "cx secret which")')
        else:
            path = os.path.expanduser(os.path.expandvars(key))
        if not os.path.isfile(path):
            return self.cm.error(f'key file not found: {path} (from "{key}")')
        self._key_cache[key] = path
        return {'return': 0, 'path': path}

    def _ssh_parts(self, h, batch=True, tty=False, x11=False, forwards=None):
        """target 'user@address', the option string, and the full 'ssh <options> target' prefix."""
        acc = h['desc'].get('access') or {}
        addr = acc.get('address') or h['alias']
        user = acc.get('user')
        target = f'{user}@{addr}' if user else str(addr)

        q = self.cm.utils.files.quote_path
        opts = []
        r = self._key_path(acc.get('key'))
        if r['return'] > 0: return r
        if r['path']:
            opts += ['-i', q(r['path']), '-o', 'IdentitiesOnly=yes']
        if batch:
            opts += ['-o', 'BatchMode=yes']
        if tty:
            # a terminal forced for a command (cx host run --interactive): without the log level, ssh's own
            # "Connection to <host> closed." would end every such run (errors and key warnings still show)
            opts += ['-t', '-o', 'LogLevel=ERROR']
        if x11:
            # trusted forwarding: untrusted (-X) needs xauth on the client, which Windows OpenSSH has not ("xauth key
            # data not generated", the remote DISPLAY stays empty); -Y works with the X server on the laptop (2026-10-26)
            opts.append('-Y')
        for fw in forwards or []:
            # "1455" forwards localhost:1455 here to localhost:1455 there; "8080:80" maps the two ports
            fw = str(fw).strip()
            if not fw: continue
            local_port, _, remote_port = fw.partition(':')
            opts += ['-L', f'{local_port}:localhost:{remote_port or local_port}']
        opts += ['-o', f'ConnectTimeout={acc.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT)}']
        if acc.get('port'):
            opts += ['-p', str(acc['port'])]
        if acc.get('options'):
            opts.append(str(acc['options']).strip())
        options = ' '.join(opts)
        return {'return': 0, 'target': target, 'options': options,
                'cmd': f'{q(self._ssh_exe())} {options} {q(target)}'.strip()}

    def _shell(self, h):
        acc = h['desc'].get('access') or {}
        return str(acc.get('shell') or DEFAULT_SHELL)

    def _engine(self, h):
        """
        The container engine of a docker-type host: "access: engine: podman" (an instance made by get-host--docker
        --engine=podman), else the engine of made_from, else docker. The commands a host needs (exec, inspect, run,
        start, stop, restart, rm) are the same words for both engines.
        """
        acc = h['desc'].get('access') or {}
        return str(acc.get('engine') or (h['desc'].get('made_from') or {}).get('engine') or 'docker')

    def _boot_stamp(self, ctx, h):
        """
        A stamp of the boot an ssh host is running - Linux: the kernel's boot id; macOS: the boot time; a
        PowerShell login: the last boot time - so that a restart can tell a new boot from the old one still
        answering. '' when it cannot be read (the host is down, a cmd.exe login, no answer within 30 s).
        """
        shell = self._shell(h).strip()
        if shell in ('powershell', 'pwsh'):
            cmd = "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')"
        elif shell == 'cmd':
            return ''
        else:
            cmd = 'cat /proc/sys/kernel/random/boot_id 2>/dev/null || sysctl -n kern.boottime 2>/dev/null'

        try:
            r = self._cmd_run(ctx, h, cmd)
            if r['return'] > 0:
                return ''
            rr = self._run_local(r['cmd'], capture=True, con=False, timeout=30)
            if rr.get('returncode', 1) != 0:
                return ''
            return (rr.get('stdout') or '').strip()
        except Exception:
            return ''

    @staticmethod
    def _powershell_command(shell, cmd):
        """Carry local PowerShell syntax through cmd.exe without exposing quotes or operators."""
        import base64

        payload = "$ProgressPreference='SilentlyContinue'; " + cmd + '\nif ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }'
        encoded = base64.b64encode(payload.encode('utf-16-le')).decode('ascii')
        return f'{shell.strip()} -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}'

    @staticmethod
    def _wrap(shell, cmd, double_quotes=False):
        """
        Run cmd in the host's shell: bash -l -c '...', powershell -NoProfile -Command "...", cmd /c ...

        double_quotes: the wrapped command is an argument of a LOCAL Windows process (wsl.exe, docker,
        adb), where cmd.exe only groups with double quotes - a single-quoted 'a b' arrives as two
        arguments, and an unquoted "|" is taken by cmd.exe itself. Through ssh the remote shell parses
        the command, so single quotes are right there.
        """
        s = shell.strip()
        if s in ('powershell', 'pwsh'):
            return f'{s} -NoProfile -Command "{cmd.replace(chr(34), chr(92) + chr(34))}"'
        if s == 'cmd':
            return f'cmd /c "{cmd}"'
        if s in ('none', 'raw'):
            return cmd
        if double_quotes:
            return f'{s} -c "' + cmd.replace('"', '\\"') + '"'
        return f"{s} -c '" + cmd.replace("'", "'\\''") + "'"

    def _cmd_run(self, ctx, h, cmd, interactive=False, raw=False, stdin=False, x11=False, forwards=None):
        """
        The local command line that runs `cmd` on host h (cmd None = an interactive shell).
        'here' is True when the host is this machine: the caller runs cmd as it is.
        """
        t = h['type']
        wireless = (h['desc'].get('access') or {}).get('wireless')
        if t == 'adb' and isinstance(wireless, dict) and wireless.get('auto_connect'):
            r = self.connect_(ctx, h['alias'] + ',' + h['uid'])
            if self.cm.catch_error(r): return r
            h['desc'].setdefault('access', {})['serial'] = r['serial']
        acc = h['desc'].get('access') or {}
        shell = self._shell(h)
        if acc.get('x11'):
            x11 = True

        # A wsl/docker/adb host reached through a remote parent: the parent's shell parses the command
        parent = None
        if t != 'ssh' and len(h.get('via_list') or []) > 1:
            self._resolve_via(ctx, h)                       # a device that moves: the parent that sees it
        if t != 'ssh' and h.get('via'):
            r = self._get_host(ctx, h['via'])
            if r['return'] > 0: return r
            if not self._here(r['host']):
                parent = r['host']

        if cmd is not None and h.get('project') and not stdin:
            cmd = self._project_command(h, cmd)
        elif cmd is not None and not stdin and self._here(h):
            cmd = self._global_command_here(h, cmd)

        local_windows = os.name == 'nt' and parent is None and t != 'ssh'

        # A wsl or docker host of this Windows machine: the command is one argument of a local process
        # (wsl.exe, docker), and cmd.exe does not read the \" that _wrap writes inside it - it toggles its
        # quoting on every ", so a | or $( ) behind an inner quote is cut loose, and wsl.exe drops the $
        # variables on the way (seen 2026-10-08: "cx host upgrade" of the docker host failed on the uv
        # receipt command; 2026-10-11: X="two words"; echo "$X" printed nothing in WSL). As for ssh below,
        # such a command goes to the host's shell on stdin, from a temporary script.
        if (t in ('wsl', 'docker') and local_windows and cmd is not None and not raw and not interactive and not stdin
                and any(c in cmd for c in '"^%\n\r')):
            r = self._temp_script(cmd)
            if r['return'] > 0: return r
            return self._cmd_stdin(ctx, h, r['path'])

        wrapped = None if cmd is None else (cmd if raw else self._wrap(shell, cmd, double_quotes=local_windows))

        if t == 'ssh':
            if self._here(h):
                if cmd is not None and not raw and not stdin and shell.strip() in ('powershell', 'pwsh'):
                    cmd = self._powershell_command(shell, cmd)
                return {'return': 0, 'cmd': cmd, 'here': True}
            # A command with a double quote cannot ride inside the one argument cmd.exe hands to ssh.exe:
            # cmd.exe toggles its quoting on EVERY ", backslash or not, so a | or & behind the first inner
            # quote is run by cmd.exe itself (seen 2026-10-06: "'head' is not recognized"). Such a command
            # goes to the host's shell on stdin instead, from a temporary script.
            # (not when the caller feeds the host's stdin itself: the script route needs stdin too)
            if cmd is not None and not interactive and not stdin and windows_here() and any(c in cmd for c in '"^%\n\r'):
                r = self._temp_script(cmd)
                if r['return'] > 0: return r
                return self._cmd_stdin(ctx, h, r['path'])

            # The same command WITH a terminal: stdin is the user's keyboard, so it travels base64-encoded instead and
            # runs there from a temporary script (a POSIX host; seen 2026-10-22 with a quoted word of --on)
            if (cmd is not None and interactive and not stdin and not raw and windows_here() and any(c in cmd for c in '"^%\n\r')
                    and shell.strip() not in ('powershell', 'pwsh', 'cmd', 'none', 'raw')):
                wrapped = self._encoded_posix_command(shell, cmd)
            r = self._ssh_parts(h, batch=not interactive, tty=interactive and cmd is not None,
                                x11=x11 and interactive, forwards=forwards if interactive else None)
            if r['return'] > 0: return r
            local = r['cmd'] if cmd is None else f'{r["cmd"]} "{wrapped}"'

        elif t == 'wsl':
            base = 'wsl.exe'
            if acc.get('distro'): base += f' -d {acc["distro"]}'
            if acc.get('user'): base += f' --user {acc["user"]}'
            local = base if cmd is None else f'{base} -- {wrapped}'

        elif t == 'docker':
            name = acc.get('container') or h['alias']
            flags = ''
            if interactive or cmd is None: flags += '-it '
            elif stdin: flags += '-i '
            if acc.get('user'): flags += f'-u {acc["user"]} '
            local = f'{self._engine(h)} exec {flags}{name} ' + (shell if cmd is None else wrapped)

        elif t == 'adb':
            s = f'-s {acc["serial"]} ' if acc.get('serial') else ''
            if cmd is None:
                inner = f'{s}shell'
            elif raw and not any(c in cmd for c in '"\'|&;$<>()'):
                # a plain command ("sh -s" for a script on stdin) travels unquoted: through a remote parent on
                # Windows a double quote would send the whole line down the temporary-script route, whose own
                # stdin redirect would then displace the script meant for the device
                inner = f'{s}shell {cmd}'
            else:
                inner = f'{s}shell "{cmd}"'
            local = self._adb_cmd(parent, inner)

        else:
            return self.cm.error(f'host "{h["alias"]}": unknown type "{t}" (one of {", ".join(TYPES)})')

        if parent is not None:
            r = self._cmd_run(ctx, parent, local, interactive=interactive or cmd is None, stdin=stdin)
            if r['return'] > 0: return r
            local = r['cmd']

        return {'return': 0, 'cmd': local, 'here': False}

    @staticmethod
    def _encoded_posix_command(shell, cmd):
        """
        A command for a POSIX host that keeps the terminal (ssh -t) yet holds no character cmd.exe could misread on
        its way to ssh.exe: the command base64-encoded, decoded there into a temporary script that the host's shell
        runs, then removed (base64 -d: GNU coreutils, macOS 13+).
        """
        import base64
        b64 = base64.b64encode(cmd.encode('utf-8')).decode('ascii')
        return f'f=$(mktemp) && echo {b64} | base64 -d > $f && {shell.strip()} $f; rc=$?; rm -f $f; exit $rc'

    def _temp_script(self, cmd, suffix='.sh'):
        """A command as a one-off script file (LF endings) in the temp dir, removed when the process exits."""
        import tempfile
        import atexit
        fd, path = tempfile.mkstemp(prefix='cmeta-host-', suffix=suffix)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(cmd.rstrip('\n') + '\n')
        atexit.register(lambda p=path: os.path.isfile(p) and os.remove(p))
        return {'return': 0, 'path': path}

    def _cmd_stdin(self, ctx, h, script):
        """Run a local script file on the host, through its shell's stdin ("bash -l -s < file")."""
        shell = self._shell(h)
        if h['type'] == 'adb':
            # Android has no bash and no login shell: toybox sh reads the script from adb's stdin
            r = self._cmd_run(ctx, h, 'sh -s', raw=True, stdin=True)
            if r['return'] > 0: return r
            return {'return': 0, 'cmd': r['cmd'] + ' < ' + self.cm.utils.files.quote_path(script), 'here': False}
        stdin_file = script
        if shell.strip() in ('powershell', 'pwsh'):
            # Not "-Command -": over a Windows OpenSSH server it runs stdin line by line and dies at the
            # first multi-line block (seen 2026-10-07 on the Acer: the probe stopped at the docker check).
            # The script goes on stdin as base64 lines (plain ASCII, whatever the host's code page: the
            # host fills $input before any script could switch the input encoding, and an accented script
            # came back as CP850 mojibake) and a tiny encoded reader decodes it as UTF-8 and runs it as one
            # script, with its output in UTF-8; the remote command line then holds no character cmd.exe
            # (sshd's default shell) could misread. $input is the one stdin reader that took a 34 KB
            # script: a StreamReader on OpenStandardInput() and [Console]::In.ReadToEnd() both stalled
            # for ever beyond a few KB (the 4.9 KB probe hung until its timeout). No progress records: without a
            # console PowerShell sends them to stderr as a "#< CLIXML" blob ("Preparing modules for first use" of
            # Get-Volume, seen 2026-10-29), as _powershell_command already says for a command.
            import base64, hashlib, tempfile
            with open(script, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('ascii')
            stdin_file = os.path.join(tempfile.gettempdir(),
                                      'cmeta-host-script-' + hashlib.sha1(script.encode('utf-8')).hexdigest()[:12] + '.b64')
            with open(stdin_file, 'w') as f:
                f.write('\n'.join(b64[i:i + 76] for i in range(0, len(b64), 76)) + '\n')
            reader_ps = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'; "
                         "$s = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((@($input) -join ''))); "
                         'Invoke-Expression $s')
            encoded = base64.b64encode(reader_ps.encode('utf-16-le')).decode('ascii')
            # -ExecutionPolicy Bypass as for a command (_powershell_command): under Windows' default policy an
            # Import-Module of a gallery module in a script waited without a word (2026-10-29)
            reader = f'{shell.strip()} -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}'
            here_cmd = f'{shell.strip()} -NoProfile -ExecutionPolicy Bypass -File {self.cm.utils.files.quote_path(script)}'
        elif shell.strip() == 'cmd':
            return self.cm.error('a script on stdin needs a bash or powershell shell on the host')
        else:
            reader = f'{shell} -s'
            here_cmd = f'{shell} {self.cm.utils.files.quote_path(script)}'

        if h.get('project'):
            if shell.strip() in ('powershell', 'pwsh'):
                reader = self._project_command(h, reader)
                here_cmd = self._project_command(h, here_cmd)
            else:
                # Read the login profile before selecting the project, then use a non-login
                # script reader so a second profile cannot put global cx back ahead of the venv.
                script_shell = shlex.quote(shlex.split(shell)[0])
                reader = self._wrap(shell, self._project_command(h, script_shell + ' -s'))
                here_cmd = self._wrap(shell, self._project_command(h, script_shell + ' ' + shlex.quote(script)))

        if h['type'] == 'ssh' and self._here(h):
            if h.get('project') and shell.strip() in ('powershell', 'pwsh'):
                here_cmd = self._powershell_command(shell, here_cmd)
            if not h.get('project') and shell.strip() not in ('powershell', 'pwsh'):
                script_shell = shlex.quote(shlex.split(shell)[0])
                here_cmd = self._global_command_here(h, script_shell + ' ' + shlex.quote(script))
            return {'return': 0, 'cmd': here_cmd, 'here': True}

        r = self._cmd_run(ctx, h, reader, raw=True, stdin=True)
        if r['return'] > 0: return r
        return {'return': 0, 'cmd': r['cmd'] + ' < ' + self.cm.utils.files.quote_path(stdin_file), 'here': False}

    def _run_local(self, cmd, capture=False, timeout=None, con=True, verbose=False):
        if timeout is not None:
            timeout = int(timeout)
        # The child writes straight to the terminal: push out what was printed before it, or the
        # host header lands after the command output when stdout is a pipe
        sys.stdout.flush()
        rr = self.cm.utils.sys.run(cmd, capture_output=capture, timeout=timeout, con=con, verbose=verbose,
                                   print_cmd=verbose, fail_on_error=False, logger=self.logger)
        if rr.get('stderr'):
            rr['stderr'] = clixml_text(rr['stderr'])
        return rr

    ############################################################
    # up / down
    ############################################################

    def _up_down(self, ctx, what, arg1, tags, machine, type):
        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        if not (arg1 or tags or machine or type):
            return self.cm.error(f'which host? cx host {what} <host> (or --tags/--machine/--type)')

        r = self._select(ctx, arg1, tags, machine, type)
        if self.cm.catch_error(r): return r
        hosts = r['hosts']
        if not hosts:
            return self.cm.error(f'no host matches "{arg1}"' if arg1 else 'no hosts match')

        explicit = self._is_explicit(arg1, hosts)
        self._status_all(ctx, hosts)

        results = {}
        for h in hosts:
            alias = h['alias']
            r = self._up_one(ctx, h, verbose) if what == 'up' else self._down_one(ctx, h, verbose)
            if r['return'] > 0:
                if explicit: return r
                results[alias] = 'error: ' + r['error']
            else:
                results[alias] = r['result']
            if con:
                print(f'{alias:32} {results[alias]}')

        return {'return': 0, 'results': results}

    def _declared_command(self, ctx, h, what, verbose):
        cmds = h['desc'].get('commands') or {}
        if not isinstance(cmds, dict):
            return self.cm.error(f'host "{h["alias"]}": "commands" must be a mapping with up / down / restart / after_restart')
        cmd = cmds.get(what)
        if not cmd:
            return None
        rr = self._run_local(cmd, capture=not verbose, con=True, verbose=verbose)
        rc = rr.get('returncode', 0)
        return {'return': 0, 'result': f'{what}: ran "{cmd}"' + ('' if rc == 0 else f' - exit code {rc}')}

    def _up_one(self, ctx, h, verbose):
        t = h['type']
        acc = h['desc'].get('access') or {}
        status = h.get('status') or self._status(ctx, h)

        if status in ('up', 'here'):
            return {'return': 0, 'result': f'already {status}'}

        r = self._declared_command(ctx, h, 'up', verbose)
        if r is not None:
            return r

        if t == 'wsl':
            if status == 'missing':
                return self.cm.error(f'WSL distro "{acc.get("distro")}" does not exist on this machine (wsl -l -v)')
            base = 'wsl.exe' + (f' -d {acc["distro"]}' if acc.get('distro') else '')
            rr = self._run_local(f'{base} -- true', capture=True, con=False)
            if rr.get('returncode', 1) != 0:
                return self.cm.error(f'wsl.exe could not start {acc.get("distro")}: {rr.get("stderr", "").strip()}')
            return {'return': 0, 'result': 'started'}

        if t == 'docker':
            name = acc.get('container') or h['alias']
            if status == 'missing':
                # Artifact-owned volumes must survive container recreation; never replace lost data silently.
                for volume in h['desc'].get('artifact_mounts') or []:
                    if volume.get('storage') != 'volume':
                        continue
                    volume_name = volume.get('volume') or ''
                    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', volume_name):
                        return self.cm.error('Invalid registered artifact volume name')
                    check = f'{self._engine(h)} volume inspect {volume_name}'
                    if h.get('via'):
                        parent = self._get_host(ctx, h['via'])
                        if parent['return'] > 0: return parent
                        if not self._here(parent['host']):
                            routed = self._cmd_run(ctx, parent['host'], check)
                            if routed['return'] > 0: return routed
                            check = routed['cmd']
                    observed = self._run_local(check, capture=True, con=False)
                    if observed.get('returncode', 1) != 0:
                        return self.cm.error(f'Registered state volume {volume_name} is missing; restore a backup before recreating this container')
                    try:
                        labels = json.loads(observed['stdout'])[0].get('Labels') or {}
                    except (KeyError, ValueError, IndexError, TypeError):
                        return self.cm.error('Cannot verify registered artifact volume: ' + volume_name)
                    if labels.get('cmeta.artifact') != volume.get('uid') or labels.get('cmeta.subpath') != volume.get('subpath'):
                        return self.cm.error('Registered volume belongs to another artifact: ' + volume_name)
                image = acc.get('image')
                if not image:
                    return self.cm.error(f'container "{name}" does not exist and no "access: image" is declared to create it')
                keep = acc.get('keepalive') or 'sleep infinity'
                run_args = acc.get('run_args') or ''
                cmd = f'{self._engine(h)} run -d --name {name} {run_args} {image} {keep}'.replace('  ', ' ')
            else:
                cmd = f'{self._engine(h)} start {name}'
            if h.get('via'):
                r = self._get_host(ctx, h['via'])
                if r['return'] > 0: return r
                if not self._here(r['host']):
                    r = self._cmd_run(ctx, r['host'], cmd)
                    if r['return'] > 0: return r
                    cmd = r['cmd']
            rr = self._run_local(cmd, capture=True, con=False)
            if rr.get('returncode', 1) != 0:
                return self.cm.error(f'"{cmd}" failed: {rr.get("stderr", "").strip()}')
            ready = self._wait_ready(ctx, h)          # the entrypoint plugs and indexes the repositories again
            return {'return': 0, 'result': ('created and started' if status == 'missing' else 'started') + ('' if ready else ' (its entrypoint did not finish in time)')}

        if t == 'ssh':
            return {'return': 0, 'result': f'{status} - an ssh host is not started from here (declare "commands: up" for a VM)'}

        return {'return': 0, 'result': f'{status} - nothing to start for type {t}'}

    def _down_one(self, ctx, h, verbose):
        t = h['type']
        acc = h['desc'].get('access') or {}
        status = h.get('status') or self._status(ctx, h)

        if status == 'here':
            return {'return': 0, 'result': 'this machine - not stopping it'}
        if status not in ('up',):
            return {'return': 0, 'result': f'already {status}'}

        r = self._declared_command(ctx, h, 'down', verbose)
        if r is not None:
            return r

        if t == 'wsl':
            cmd = 'wsl.exe -t ' + str(acc.get('distro') or '')
        elif t == 'docker':
            cmd = f'{self._engine(h)} stop ' + str(acc.get('container') or h['alias'])
            if h.get('via'):
                r = self._get_host(ctx, h['via'])
                if r['return'] > 0: return r
                if not self._here(r['host']):
                    r = self._cmd_run(ctx, r['host'], cmd)
                    if r['return'] > 0: return r
                    cmd = r['cmd']
        else:
            return {'return': 0, 'result': f'up - a {t} host is not stopped from here (declare "commands: down")'}

        rr = self._run_local(cmd, capture=True, con=False)
        if rr.get('returncode', 1) != 0:
            return self.cm.error(f'"{cmd}" failed: {rr.get("stderr", "").strip()}')
        return {'return': 0, 'result': 'stopped'}

    ############################################################
    # probe
    ############################################################

    @staticmethod
    def _upgrade_os_cmd(system, firmware, check):
        """The upgrade-os command for a host: quiet (sudo -n, no questions), the OS packages unless only the
        firmware was asked for, --check to list only."""
        cmd = 'cx task run upgrade-os -q'
        if not system:
            cmd += ' --system- --apps-'
        if firmware:
            cmd += ' --firmware'
        if check:
            cmd += ' --check'
        return cmd

    def _refresh_state(self, ctx, h, con):
        """
        Probe the host again after a sync that changed something, an upgrade or a restart, so that its
        state.yaml - and "cx host ls" - say what is there now (the versions, the uptime); a probe that
        fails is reported, never fatal (2026-10-07: "cx host ls" showed a VM at 0.32.0 after its
        upgrade to 0.33.0, from the probe of the morning).
        """
        r = self._probe_one(ctx, h, DEFAULT_PROBE_TIMEOUT, False)
        if r['return'] > 0:
            if con:
                print(f'{h["alias"]}: the probe after the change failed - {r.get("error")} (run "cx host probe {h["alias"]}" later)')
            return
        st = r['state']
        if con:
            print(f'{h["alias"]}: probed - cMeta {st.get("cmeta_version") or "-"}, aops {st.get("aops_version") or "-"}, '
                  f'{st.get("os", "?")}')

    def _probe_one(self, ctx, h, timeout, verbose):
        shell = self._shell(h).strip()
        if h['type'] == 'adb':
            name = 'probe-android.sh'
        elif shell in ('powershell', 'pwsh'):
            name = 'probe.ps1'
        else:
            name = 'probe.sh'
        script = os.path.join(self.path, 'files', name)
        if not os.path.isfile(script):
            return self.cm.error(f'probe script missing: {script}')

        r = self._cmd_stdin(ctx, h, script)
        if r['return'] > 0: return r

        rr = self._run_local(r['cmd'], capture=True, timeout=timeout, con=verbose, verbose=verbose)
        out = rr.get('stdout', '') or ''
        if rr.get('returncode', 1) != 0 and 'hostname=' not in out:
            err = (rr.get('stderr', '') or '').strip().splitlines()
            return self.cm.error(f'probe failed (exit code {rr.get("returncode")})' + (f': {err[-1]}' if err else ''))

        state = {'probed_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                 'probed_from': platform.node()}
        for k in ('via_now', 'via_seen_at'):               # where a moving device was last seen survives a probe
            if (h.get('state') or {}).get(k):
                state[k] = h['state'][k]
        repos = {}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith('repo|'):
                # repo|<folder>|git|<branch>|<commit>|<date>|<changed files>|<_cmr version>|<_cmr artifact>
                p = (line.split('|') + [''] * 9)[1:9]
                name = p[0]
                if not name: continue
                entry = {'kind': p[1] or 'copy'}
                if p[1] == 'git':
                    entry.update({'branch': p[2], 'commit': p[3], 'date': p[4]})
                    try: entry['changed_files'] = int(p[5])
                    except ValueError: pass
                if p[6]: entry['version'] = p[6]
                if p[7]: entry['artifact'] = p[7]
                repos[name] = entry
            elif '=' in line:
                k, _, v = line.partition('=')
                k = k.strip()
                v = v.strip()
                if k and v:
                    state[k] = v
        aops = self._aops_version(repos)
        if aops: state['aops_version'] = aops
        state['repos'] = repos

        if h.get('project'):
            self._project_status_all(ctx, [h])
            state['server'] = (h.get('project_status') or {}).get(h['project'], {})
        saved = self._read_yaml(os.path.join(h['path'], STATE_FILE))
        if h.get('project'):
            saved.setdefault('projects', {})[h['project']] = state
        else:
            projects = declared_project_states(saved, h.get('desc'))
            if projects: state['projects'] = projects
            if h['type'] == 'adb' and (h['desc'].get('access') or {}).get('wireless'):
                if saved.get('adb_connection'):
                    state['adb_connection'] = saved['adb_connection']
            saved = state
        r = self.cm.utils.files.safe_write_file(os.path.join(h['path'], STATE_FILE), saved, atomic=True,
                                                sort_keys=False, logger=self.logger)
        if r['return'] > 0: return r

        h['state'] = state
        return {'return': 0, 'state': state}

    ############################################################
    # sync / push
    ############################################################

    @staticmethod
    def _sync_repos_path(h, sync):
        """
        The folder of the host's repositories, and where it comes from:

        - 'declared': `sync: repos_path` of the host (or of the selected project);
        - 'probed': `<cmeta_home>/repos`, the home that cx reported there at the last probe (`cx --print-home`,
          or `cx --version` of an older cMeta; state.yaml) - whatever chose it on the host: CMETA_HOME, a virtual
          environment, a wrapper script;
        - 'declared home': `<cmeta: home>/repos` of the _desc.yaml, for a host that was never probed;
        - 'default': ~/CMETA/repos, when nothing is known (what every host got before 2026-10-12).

        Every host that synced repositories then declared its repos_path, so none of them changed.
        """
        declared = sync.get('repos_path')
        if declared:
            return str(declared), 'declared'

        for home, source in ((h.get('state') or {}).get('cmeta_home'), 'probed'), \
                            (((h.get('desc') or {}).get('cmeta') or {}).get('home'), 'declared home'):
            home = str(home or '').strip()
            if home:
                # A Windows home as rclone's sftp takes it (C:/Users/...), joined with "/" like a declared path
                return home.replace('\\', '/').rstrip('/') + '/repos', source

        return '~/CMETA/repos', 'default'

    def _sync_entries(self, h):
        """
        {name: {'method', 'local', 'remote', 'blacklist', 'workdir', 'artifacts'}} from the host's "sync:" block.
        An entry is a name, or {name: {method, remote, blacklist, workdir, artifacts}}. The remote folder of a
        repository is its own `remote`, else `<repos path>/<name>` (see _sync_repos_path). With `artifacts` (cRef
        patterns) only those artifacts travel: a partial repository (see _selection_rules).
        """
        sync = h['desc'].get('sync') or {}
        repos_path, source = self._sync_repos_path(h, sync)
        default = str(sync.get('default') or 'bisync')
        blacklist = sync.get('blacklist')
        if blacklist is None:
            blacklist = list(DEFAULT_BLACKLIST)
        workdir = sync.get('workdir')

        entries = {}
        for item in sync.get('repos') or []:
            if isinstance(item, dict):
                name, opts = next(iter(item.items()))
                opts = opts or {}
            else:
                name, opts = str(item), {}
            method = str(opts.get('method') or default)
            bl = list(blacklist) + self._csv(opts.get('blacklist'))
            entries[name] = {
                'method': method,
                'local': str(self.cm.repos_path / name),
                'remote': str(opts.get('remote') or (repos_path.rstrip('/') + '/' + name)),
                'blacklist': bl,
                'workdir': opts.get('workdir', workdir),
                'repos_path': repos_path,           # where the repositories of the host are, and why
                'repos_path_from': source,
                'artifacts': self._patterns(opts.get('artifacts')),
            }
        return entries

    @staticmethod
    def _patterns(value):
        """The artifacts of a partial repository: a list, or one string with ";" between the patterns (a cRef holds commas)."""
        if not value:
            return []
        items = value if isinstance(value, (list, tuple)) else str(value).split(';')
        return [str(x).strip().replace('\\', '/') for x in items if str(x).strip()]

    @staticmethod
    def _glob(text, wildcards=False):
        """A path part as part of an rclone rule: its glob characters escaped (with wildcards, * and ? stay wildcards)
        and a comma as "?" (rclone-to-ssh splits its whitelist at commas)."""
        out = GLOB_CHARS.sub(r'\\\1', str(text))
        out = re.sub(r'\*+', '*', out) if wildcards else out.replace('*', '\\*').replace('?', '\\?')
        return out.replace(',', '?')

    def _shard_globs(self, alias, slices):
        """The shard folders above an artifact pattern, as the engine names them (shard_name: the alias's first
        characters in lower case): literal where the pattern's literal start covers the slice, else that start and "*"."""
        if not slices:
            return []
        literal = re.match(r'[^*?]*', alias).group(0)
        r = self.cm.utils.files.shard_name(literal, slices)
        full = r.get('parts', [])[:-1] if r.get('return', 1) == 0 else []
        out, start = [], 0
        for i, length in enumerate(slices):
            end = start + int(length)
            if end <= len(literal) and i < len(full):
                out.append(self._glob(full[i]))
            else:
                part = literal[start:end].lower().replace(' ', '_') if start < len(literal) else ''
                out.append(self._glob(part) + '*')
            start = end
        return out

    def _repo_desc(self, local):
        """The _cmr.yaml of a local repository (an empty dict when unreadable)."""
        rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(local, '_cmr'))
        data = rd.get('data') if rd.get('return', 1) == 0 else None
        return data if isinstance(data, dict) else {}

    def _selection_rules(self, local, patterns):
        """
        The anchored rclone whitelist of a partial repository from its artifact patterns,
        "<category>::<artifact>[/<path inside>]" - cRefs whose aliases compare without case, with * and ? as wildcards:

            fgg.project::cMeta/!AI      that artifact's !AI folder, and its _cmeta and _desc
            fgg.project::cmeta-aops     the whole artifact (it must exist here)
            work::2026*                 every artifact of the category whose alias starts with 2026 - a folder glob
                                        through the category's shard folders, so an artifact made later on either
                                        side is in it and the rules do not change between runs

        The repository's _cmr.yaml and the definitions of the categories it holds itself come along (the copy is a
        repository the host's cMeta can index). -> {'rules': [...]}
        """
        rules = ['/_cmr.yaml']
        desc = self._repo_desc(local)
        repo_slices = {str(k): v for k, v in (desc.get('sharding_slices') or {}).items()}
        repo_uid = str(desc.get('artifact') or '').split(',')[-1].strip()

        def ours(a):
            """An artifact of this repository, by its repository's UID: a repository nested in this folder (the engine's
            internal repository inside a source tree) is another repository."""
            uid = str((a.get('cmeta_ref_parts') or {}).get('repo_uid') or '')
            return uid == repo_uid if (uid and repo_uid) else self.cm.utils.files.is_path_within(local, a['path'])

        def add(rule):
            if rule not in rules:
                rules.append(rule)

        def found(category, name):
            r = self.cm.access({'category': category, 'command': 'find', 'arg1': name, 'con': False})
            return (r.get('artifacts') or []) if r.get('return', 1) == 0 else []

        for pattern in patterns:
            if '::' not in pattern:
                return self.cm.error(f'"{pattern}": an artifact pattern is <category>::<artifact>[/<path inside>]')
            cat_part, rest = pattern.split('::', 1)
            art_part, _, inside = rest.partition('/')
            cat_part, art_part, inside = UID_SUFFIX.sub('', cat_part.strip()), art_part.strip(), inside.strip('/')
            wild = any(c in art_part for c in '*?')

            # the category, or every category folder of the repository a wildcard matches
            if any(c in cat_part for c in '*?'):
                names = sorted(d for d in os.listdir(local) if os.path.isdir(os.path.join(local, d)) and d != 'category'
                               and not d.startswith(('.', '_')) and fnmatch.fnmatch(d.lower(), cat_part.lower()))
            else:
                names = [cat_part]
            cats = [a[0] for a in (found(self.cmeta['uses_categories'].get('category', 'category,dd9ea50e7f76467f'), n) for n in names) if len(a) == 1]
            if not cats:
                return self.cm.error(f'"{pattern}": no category "{cat_part}" (in {local})')

            for cat in cats:
                parts = cat['cmeta_ref_parts']
                cat_alias, cat_uid = parts['artifact_alias'], parts['artifact_uid']
                if ours(cat):
                    add('/' + os.path.relpath(cat['path'], local).replace(os.sep, '/') + '/')

                if wild:
                    slices = repo_slices.get(cat_uid) or (cat.get('cmeta') or {}).get('sharding_slices')
                    base = '/' + '/'.join([self._glob(cat_alias)] + self._shard_globs(UID_SUFFIX.sub('', art_part), slices) +
                                          [self._glob(UID_SUFFIX.sub('', art_part), wildcards=True)])
                else:
                    arts = [a for a in found(f'{cat_alias},{cat_uid}', art_part) if ours(a)]
                    if not arts:
                        if len(cats) == 1:
                            return self.cm.error(f'"{pattern}": no artifact "{art_part}" of {cat_alias} in {local}')
                        continue
                    base = '/' + '/'.join(self._glob(p) for p in os.path.relpath(arts[0]['path'], local).split(os.sep))

                if not inside:
                    add(base + '/')
                    continue
                add(base + '/_cmeta.*')
                add(base + '/_desc.*')
                inner = '/'.join(self._glob(p) for p in inside.split('/'))
                is_file = not wild and os.path.isfile(os.path.join(local, *base.strip('/').split('/'), *inside.split('/')))
                add(base + '/' + inner + ('' if is_file else '/'))

        return {'return': 0, 'rules': rules}

    def _selection_file(self, h, name, entry):
        """The rules of the last bisync of a partial repository, beside rclone's listings of that host."""
        return os.path.join(self._bisync_workdir(h, entry), f'cmeta-selection-{name}.txt')

    @staticmethod
    def _sh_path(path):
        """A remote path for a POSIX shell: quoted, a leading ~/ kept as the home."""
        path = str(path)
        return '"$HOME"/' + shlex.quote(path[2:]) if path.startswith('~/') else shlex.quote(path)

    def _index_on_host(self, ctx, h, name, remote, con, verbose):
        """
        After files of a repository arrived on a host: that repository rescanned there ("cx repo reindex"), plugged
        when the host does not know it yet (a first push or sync), else the whole index rebuilt (a cMeta older than
        0.34.0). -> {'cmd', 'returncode', 'seconds'}
        """
        if self._shell(h).strip() in ('powershell', 'pwsh'):
            path = str(remote).replace("'", "''")
            cmd = (f"cx repo reindex {name} -q; if ($LASTEXITCODE -ne 0) {{ cx repo plug '{path}' -q }}; "
                   f"if ($LASTEXITCODE -ne 0) {{ cx --reindex }}")
        else:
            cmd = f'cx repo reindex {shlex.quote(name)} -q || cx repo plug {self._sh_path(remote)} -q || cx --reindex'
        r = self._cmd_run(ctx, h, cmd)
        if self.cm.catch_error(r): return r
        t0 = time.monotonic()
        rr = self._run_local(r['cmd'], capture=not verbose, con=con, verbose=verbose, timeout=300)
        out = {'return': 0, 'cmd': cmd, 'returncode': rr.get('returncode'), 'seconds': round(time.monotonic() - t0, 1)}
        if con:
            if rr.get('returncode', 0) == 0:
                print(f'INDEX ({h["alias"]}): {cmd} - ok ({out["seconds"]:.1f}s)')
            else:
                print(f'WARNING: "{cmd}" on {h["alias"]} returned {rr.get("returncode")} - run it there by hand')
        return out

    def _write_partial_note(self, ctx, h, name, remote, patterns, rules, how, verbose):
        """PARTIAL.md at the root of the host's copy of a partial repository: what it holds, from where, since when.
        Outside the rules, so a bisync never brings it back."""
        now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        lines = [f'# A partial copy of the repository {name}', '',
                 'This folder holds only the artifacts selected below. The rest of the repository stays on the machine it',
                 f'comes from, which writes this file at every "cx host {how}".', '',
                 '| | |', '|---|---|',
                 f'| from | {socket.gethostname()} (`cx host {how}`) |',
                 f'| written | {now} |', '',
                 '## The selection', '', '`artifacts:` of the sync entry of this host, or `--artifacts` of a push:', '']
        lines += [f'- `{p}`' for p in patterns]
        lines += ['', '## The rclone rules it gives', '', '```'] + rules + ['```', '',
                  'An artifact made here outside these rules does not travel back. A file of the selection changed on both',
                  'machines between two runs of a bisync comes back as two copies, `<name>.conflict1` and `<name>.conflict2`',
                  '(run-ai merges its own records and lists the others for the agent). This file is not synced.', '']
        folder = tempfile.mkdtemp(prefix='cmeta-partial-')
        try:
            path = os.path.join(folder, PARTIAL_NOTE)
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(lines))
            return self._rclone(ctx, h, 'copyto', path, str(remote).rstrip('/') + '/' + PARTIAL_NOTE, con=False, verbose=verbose)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def _bisync_workdir(self, h, entry):
        """Where rclone keeps the bisync listings and lock of this host: declared, or bisync-<alias>."""
        wd = entry.get('workdir')
        if wd:
            return os.path.expandvars(os.path.expanduser(str(wd)))
        if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
            base = os.path.join(os.environ['LOCALAPPDATA'], 'rclone')
        else:
            base = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache'), 'rclone')
        return os.path.join(base, 'bisync-' + h['alias'])

    def _sync_repo(self, ctx, h, name, entry, resync, resync_mode, unlock, dry_run, con, verbose, backup=False,
                   force=False, capture=False):
        """One run of the declared method; force: rclone's --force past its delete guard (bisync); capture: rclone's
        output kept in the result ('output') for the verdicts, with -v so that what moved can be counted."""
        method = entry['method']
        if method not in SYNC_METHODS:
            return self.cm.error(f'{name}: unknown sync method "{method}" (one of {", ".join(SYNC_METHODS)})')

        if method == 'none':
            if con: print(f'--- {name}: method none, skipped')
            return {'return': 0}

        if con:
            print('')
            print(f'--- {name}: {method}' + (' --resync' if resync and method == 'bisync' else ''))

        if method == 'git':
            remote = entry['remote']
            cmd = (f'git -C "{remote}" fetch --dry-run && git -C "{remote}" status -sb' if dry_run
                   else f'git -C "{remote}" pull --ff-only')
            r = self._cmd_run(ctx, h, cmd)
            if r['return'] > 0: return r
            rr = self._run_local(r['cmd'], capture=capture, con=con, verbose=verbose)
            text = (rr.get('stdout') or '') + (rr.get('stderr') or '') if capture else ''
            if rr.get('returncode', 1) != 0:
                tail = [l.strip() for l in text.splitlines() if l.strip()][-2:]
                rx = self.cm.error(f'git on {h["alias"]} returned {rr.get("returncode")}' + (': ' + ' | '.join(tail) if tail else ''))
                rx['output'] = text
                return rx
            if not dry_run:
                self._index_after_sync(ctx, h, name, entry, method, con, verbose)
            m = re.search(r'Updating ([0-9a-f]+)\.\.([0-9a-f]+)', text)
            what = f'pulled {m.group(1)}..{m.group(2)}' if m else ('already up to date' if 'Already up to date' in text else ('pulled' if capture else ''))
            return {'return': 0, 'output': text, 'git': what}

        local = entry['local']
        if not os.path.isdir(local):
            return self.cm.error(f'local repository not found: {local}')

        # a repository of secrets never travels with a sync: the secrets a host needs go there once, by name
        if self._repo_desc(local).get('secrets'):
            return self.cm.error(f'{name} holds secrets (secrets: true in its _cmr.yaml) and is never synced - push the ones '
                                 f'{h["alias"]} needs: cx host push {h["alias"]} {name} --artifacts="secret::<alias>;..." --secrets')

        extra = list(DEFAULT_RCLONE_FLAGS)
        if dry_run: extra.append('--dry-run')
        if capture: extra.append('-v')                  # the per-file lines, counted after the run (never shown live)
        if force and method == 'bisync': extra.append('--force')

        # --backup: what this run overwrites or deletes is kept in the result artifact sync-backup--<repository> of each
        # side's local repository - an artifact the index knows ("cx result ls") - under <the other side>/<run id>/;
        # rclone makes the run folder only when a file goes there, and the host's copy of the artifact gets its
        # _cmeta after the run (_backup_mark_remote), so the host's index can know it too
        dirs = None
        if backup:
            r = self._backup_dirs(h, name, entry)
            if r['return'] > 0: return r
            dirs = r
            if method == 'copy':
                extra += ['--backup-dir', ':sftp:' + dirs['remote']]
            else:
                extra += ['--backup-dir1', dirs['local'], '--backup-dir2', ':sftp:' + dirs['remote']]
            if con:
                where = f'{dirs["here"]}/{dirs["run_id"]}/ of result::local:{dirs["artifact"]} on {h["alias"]}'
                if method != 'copy':
                    where = f'{h["alias"]}/{dirs["run_id"]}/ of result::local:{dirs["artifact"]} here, and ' + where
                print(f'    --backup: what this run overwrites or deletes goes to {where}')

        # a partial repository: only the artifacts its patterns select, the aliases compared without case as cMeta does
        rules = []
        if entry.get('artifacts'):
            r = self._selection_rules(local, entry['artifacts'])
            if r['return'] > 0: return r
            rules = r['rules']
            extra.append('--ignore-case')
            if con:
                print(f'    a partial repository: {len(entry["artifacts"])} artifact pattern(s) -> {len(rules)} rule(s); '
                      f'{PARTIAL_NOTE} there says which')

        if method == 'copy':
            r = self._rclone(ctx, h, 'copy', local, entry['remote'], whitelist=rules, blacklist=entry['blacklist'],
                             extra=extra, con=con, verbose=verbose, capture=capture)
            if r['return'] > 0: return r
            if dirs and not dry_run:
                self._backup_mark_remote(ctx, h, dirs, con, verbose)
            if dry_run: return r
            if not rules:
                self._index_after_sync(ctx, h, name, entry, method, con, verbose)
                return r
            return self._after_partial(ctx, h, name, entry, rules, 'sync', con, verbose)

        # bisync: rclone's listings hold only what the rules let through, so a run with other rules than the last one
        # would read the difference as deletions - it needs --resync
        selection = self._selection_file(h, name, entry) if rules else ''
        if rules and not resync:
            try:
                with open(selection, encoding='utf-8') as f:
                    last = f.read()
            except OSError:
                last = None
            if last != '\n'.join(rules) + '\n':
                return self.cm.error(f'{name}: the selection of artifacts ' + ('changed since the last sync' if last is not None else
                                     'has not been synced with these rules yet') + ' - run once with --resync (--resync_mode=path1: '
                                     'this machine wins where both sides have a file)')
        if resync:
            mode = str(resync_mode or 'newer')
            if mode not in ('newer', 'older', 'path1', 'path2', 'larger', 'smaller'):
                return self.cm.error(f'unknown --resync_mode "{mode}" (newer | older | path1 | path2 | larger | smaller)')
            extra += ['--resync-mode', mode]
        r = self._rclone(ctx, h, 'resync' if resync else 'bisync', local, entry['remote'], whitelist=rules,
                         blacklist=entry['blacklist'], extra=extra, con=con, verbose=verbose,
                         workdir=self._bisync_workdir(h, entry), unlock=unlock, capture=capture)
        if r['return'] > 0: return r
        if dirs and not dry_run:
            self._backup_mark_remote(ctx, h, dirs, con, verbose)
        if dry_run: return r
        if not rules:
            self._index_after_sync(ctx, h, name, entry, method, con, verbose)
            return r
        os.makedirs(os.path.dirname(selection), exist_ok=True)
        with open(selection, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(rules) + '\n')
        rr = self._after_partial(ctx, h, name, entry, rules, 'sync', con, verbose)
        if rr.get('return', 0) > 0: return rr
        self._index_after_sync(ctx, h, name, entry, method, con, verbose, on_host=False)
        return r

    def _backup_dirs(self, h, name, entry):
        """
        Where a --backup run keeps what it overwrites or deletes: the result artifact sync-backup--<repository> of
        this machine's local repository (made now, under <host alias>/<run id>/) and the same artifact of the host's
        local repository (under <this machine>/<run id>/): {'artifact', 'run_id', 'here', 'local', 'remote',
        'remote_artifact', 'cmeta_file'}.
        """
        alias = f'sync-backup--{name}'
        r = self.cm.access({'category': self.cmeta['uses_categories'].get('result', 'result,6567e4df4d04488a'), 'command': 'get',
                            'arg1': f'local:{alias}', 'meta': {'permanent': True, 'tags': ['sync-backup'], 'repository': name},
                            'con': False})
        if r['return'] > 0: return r
        path = r['artifact']['path']
        run_id = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        here = re.sub(r'[^A-Za-z0-9_.-]', '-', socket.gethostname()).strip('-.') or 'orchestrator'
        remote_artifact = '/'.join([entry['remote'].rstrip('/').rsplit('/', 1)[0], 'local', 'result', alias])
        cmeta_file = next((os.path.join(path, n) for n in ('_cmeta.yaml', '_cmeta.json') if os.path.isfile(os.path.join(path, n))), '')
        return {'return': 0, 'artifact': alias, 'run_id': run_id, 'here': here, 'local': os.path.join(path, h['alias'], run_id),
                'remote': '/'.join([remote_artifact, here, run_id]), 'remote_artifact': remote_artifact, 'cmeta_file': cmeta_file}

    def _backup_mark_remote(self, ctx, h, dirs, con, verbose):
        """
        After a --backup run: when files went to the host's backup folder and the artifact there has no _cmeta yet,
        it gets the local one's copy and the host's local repository is reindexed, so "cx result ls" shows it there.
        Nothing to do when nothing was backed up. A host without a POSIX shell is left as it is.
        """
        if not dirs.get('cmeta_file'):
            return {'return': 0}
        mark = dirs['remote_artifact'] + '/' + os.path.basename(dirs['cmeta_file'])
        r = self._cmd_run(ctx, h, f'test -d {shlex.quote(dirs["remote"])} && test ! -e {shlex.quote(mark)}')
        if r['return'] > 0:
            return {'return': 0}
        rr = self._run_local(r['cmd'], capture=True, con=False, verbose=verbose)
        if rr.get('returncode') != 0:
            return {'return': 0}
        r = self._rclone(ctx, h, 'copyto', dirs['cmeta_file'], mark, con=con, verbose=verbose)
        if r['return'] > 0:
            if con:
                print(f'WARNING: the backup artifact of {h["alias"]} got no _cmeta: {r.get("error")}')
            return {'return': 0}
        return self._index_on_host(ctx, h, 'local', dirs['remote_artifact'].rsplit('/result/', 1)[0], con, verbose)

    def _sync_changed_meta(self, h, entry, side):
        """
        The meta files (an artifact's _cmeta.*, the repository's _cmr.*) that the two-way sync just run changed on
        one side (1 = this machine, 2 = the host), from rclone's listings of that side before and after the run
        (<workdir>/<pair>.path<side>.lst-old and .lst): a sync that moved no meta file needs no reindex on that
        side. -> a list of paths (relative to the repository, "/"), or None when the listings cannot be read (a
        first sync, a resync).
        """
        workdir = self._bisync_workdir(h, entry)
        prefix = re.sub(r'[\s\\/:?*]', '_', str(entry['local']).strip('\\/')) + '..'
        suffix = f'.path{side}.lst'
        files = [f for f in os.listdir(workdir) if f.startswith(prefix) and f.endswith(suffix)] if os.path.isdir(workdir) else []
        if len(files) != 1 or not os.path.isfile(os.path.join(workdir, files[0] + '-old')):
            return None
        try:
            with open(os.path.join(workdir, files[0]), encoding='utf-8', errors='replace') as f:
                new = set(f.read().splitlines())
            with open(os.path.join(workdir, files[0] + '-old'), encoding='utf-8', errors='replace') as f:
                old = set(f.read().splitlines())
        except OSError:
            return None
        changed = []
        for line in sorted(new ^ old):
            m = re.search(r'"(.*)"$', line)
            if m and not line.startswith('#') and os.path.basename(m.group(1)).startswith(('_cmeta.', '_cmr.')):
                if m.group(1) not in changed: changed.append(m.group(1))
        return changed

    def _index_here(self, h, name, entry, con):
        """
        After a two-way sync, the index of this machine brought up to date at the smallest cost: an artifact whose
        _cmeta.* is new or changed is reindexed by itself (cx <category> reindex <repository>:<alias>); a meta that
        is gone, a changed _cmr.*, an artifact the category does not resolve, or listings that cannot be read mean
        the whole repository (cx repo reindex: seconds, 50 s on a Windows for the largest); a sync that changed no
        meta file changes nothing. A failure is a warning: the files are there, the index is rebuilt by hand.
        """
        changed = self._sync_changed_meta(h, entry, 1)
        if changed == []:
            if con: print(f'INDEX (here): no meta file of {name} changed here - the index is current')
            return
        t0 = time.monotonic()
        whole, done = changed is None, []
        for path in (changed or []):
            parts = path.replace('\\', '/').strip('/').split('/')
            if len(parts) < 3 or parts[-1].startswith('_cmr.') or not os.path.isdir(os.path.join(entry['local'], *parts[:-1])):
                whole = True
                break
            r = self.cm.access({'category': parts[0], 'command': 'reindex', 'arg1': f'{name}:{parts[-2]}', 'con': False})
            if r.get('return', 0) > 0:
                whole = True
                break
            done.append(parts[-2])
        if whole:
            r = self.cm.access({'category': 'repo', 'command': 'reindex', 'arg1': name, 'con': False})
            what = f'cx repo reindex {name}'
        else:
            what = f'{len(done)} artifact(s) of {name} reindexed: ' + ', '.join(done[:5]) + (' ...' if len(done) > 5 else '')
        if con:
            if r.get('return', 0) == 0:
                print(f'INDEX (here): {what} - ok ({time.monotonic() - t0:.1f}s)')
            else:
                print(f'WARNING: {name} was not reindexed here after the two-way sync: {r.get("error")} - run "cx repo reindex {name}"')

    def _index_after_sync(self, ctx, h, name, entry, method, con, verbose, on_host=True):
        """
        After a sync that moved files: the repository rescanned on the host ("cx repo reindex" there, plugged the
        first time - after a two-way sync only when a meta file changed on that side) and, after a two-way sync,
        here too (what came back) - so a new artifact is found at once on both sides. Without it a synced work
        item stayed invisible until a reindex by hand (the P14s, 2026-10-26).
        """
        if on_host:
            changed = self._sync_changed_meta(h, entry, 2) if method == 'bisync' else None
            if changed == []:
                if con: print(f'INDEX ({h["alias"]}): no meta file of {name} changed there - the index is current')
            else:
                r = self._index_on_host(ctx, h, name, entry['remote'], con, verbose)
                if r.get('return', 0) > 0 and con:
                    print(f'WARNING: {name} was not reindexed on {h["alias"]}: {r.get("error")}')
        if method == 'bisync':
            self._index_here(h, name, entry, con)


    ############################################################
    # The sync that finishes and proves it: repairs, retries, the check of both sides, the verdict
    ############################################################

    @staticmethod
    def _bisync_failure(text):
        """What rclone's bisync said when it failed -> (kind, detail): 'lock' (a stale lock file), 'too-many-deletes'
        ((side, gone, total): its >50% delete guard), 'needs-resync' (no usable listings: a new pair, a side replaced),
        'transient' (worth another try), 'other'."""
        s = text or ''
        if 'prior lock file found' in s:
            return 'lock', None
        m = re.search(r'too many deletes \(>\d+%, (\d+) of (\d+)\) on (Path[12])', s)
        if m:
            return 'too-many-deletes', (m.group(3), int(m.group(1)), int(m.group(2)))
        if re.search(r'Must run --resync|all files were changed|cannot find prior Path1 or Path2 listings|listing.*not found', s):
            return 'needs-resync', None
        if re.search(r'retrying may help|Please try again|Error is retryable|connection reset|broken pipe|timed out|i/o timeout|EOF', s):
            return 'transient', None
        return 'other', None

    @staticmethod
    def _moved(text):
        """What a captured run moved, from rclone's own lines (-v): copies to the host and here, deletes on each side.
        A bisync queues each file with its direction; a resync copies in two phases, one per direction."""
        n = {'to_host': 0, 'to_here': 0, 'deleted_host': 0, 'deleted_here': 0}
        lines = (text or '').splitlines()
        if 'Resync is copying files to' in (text or ''):
            phase = None
            for l in lines:
                if 'Resync is copying files to' in l:
                    phase = 'to_here' if l.rstrip().endswith('Path1') else 'to_host'
                elif phase and re.search(r': Copied \((new|replaced existing)\)', l):
                    n[phase] += 1
            return n
        for l in lines:
            if 'Queue copy to' in l:
                n['to_host' if 'Path2' in l.split('Queue copy to', 1)[1][:12] else 'to_here'] += 1
            elif 'Queue delete' in l:
                n['deleted_here' if '- Path1' in l else 'deleted_host'] += 1
        if not any(n.values()):                       # a one-way copy: no queue lines, the per-file lines count
            n['to_host'] = sum(1 for l in lines if re.search(r': Copied \((new|replaced existing)\)', l))
            n['deleted_host'] = sum(1 for l in lines if re.search(r': Deleted$', l.rstrip()))
        return n

    @staticmethod
    def _moved_text(n):
        if n.get('git'):
            return n['git']
        parts = []
        if n.get('to_host'): parts.append(f'{n["to_host"]} to host')
        if n.get('to_here'): parts.append(f'{n["to_here"]} here')
        if n.get('deleted_host'): parts.append(f'{n["deleted_host"]} deleted there')
        if n.get('deleted_here'): parts.append(f'{n["deleted_here"]} deleted here')
        return ', '.join(parts) if parts else 'nothing to move'

    def _side_intact(self, ctx, h, entry, side):
        """Whether the side that lost more than half of its files is still a repository (its _cmr.* there and not
        empty): then the deletes are real and may be forced; a wiped or detached side is never followed."""
        if side == 'Path1':
            local = entry['local']
            if not any(os.path.isfile(os.path.join(local, f)) for f in ('_cmr.yaml', '_cmr.json')):
                return False
            for root, dirs, files in os.walk(local):
                if any(f not in ('_cmr.yaml', '_cmr.json') for f in files):
                    return True
            return False
        remote = entry['remote']
        if self._shell(h).strip() in ('powershell', 'pwsh'):
            path = str(remote).replace("'", "''")
            cmd = f"if ((Test-Path '{path}\\_cmr.yaml') -or (Test-Path '{path}\\_cmr.json')) {{ exit 0 }} else {{ exit 1 }}"
        else:
            q = self._sh_path(remote)
            cmd = f'test -f {q}/_cmr.yaml || test -f {q}/_cmr.json'
        r = self._cmd_run(ctx, h, cmd)
        if r.get('return', 0) > 0: return False
        rr = self._run_local(r['cmd'], capture=True, con=False, verbose=False, timeout=60)
        return rr.get('returncode', 1) == 0

    def _remote_empty(self, ctx, h, entry):
        """Whether the host's folder of the repository is missing or empty: a new pair, safe to seed from here."""
        remote = entry['remote']
        if self._shell(h).strip() in ('powershell', 'pwsh'):
            return False
        q = self._sh_path(remote)
        r = self._cmd_run(ctx, h, f'ls -A {q} 2>/dev/null | head -c 1')
        if r.get('return', 0) > 0: return False
        rr = self._run_local(r['cmd'], capture=True, con=False, verbose=False, timeout=60)
        return rr.get('returncode', 1) == 0 and not (rr.get('stdout') or '').strip()

    def _sync_repo_robust(self, ctx, h, name, entry, resync, resync_mode, unlock, dry_run, con, verbose, backup, retries):
        """The declared sync of one repository, run until it finishes or until nothing known cures it: a stale lock is
        dropped, rclone's delete guard is passed with --force when the side that lost the files is still a repository
        (the deleted files kept in the host's sync-backup artifact), a new pair is seeded from this machine, a transient
        error is tried again (retries). -> the result of the last run, with 'notes' (what was done) and 'moved'."""
        notes, force, attempt = [], False, 0
        while True:
            attempt += 1
            r = self._sync_repo(ctx, h, name, entry, resync=resync, resync_mode=resync_mode, unlock=unlock, dry_run=dry_run,
                                con=con, verbose=verbose, backup=backup, force=force, capture=not dry_run)
            r['notes'] = notes
            if r.get('return', 0) == 0:
                if not dry_run:
                    r['moved'] = {'git': r['git']} if r.get('git') else self._moved(r.get('output', ''))
                    # a file changed on both sides since the last run: rclone keeps both copies as .conflict1/2 and
                    # the name itself is gone on both sides - the paths, for the verdict (from its renames: its warning
                    # "New or changed in both paths" also names files that are new on both sides and equal)
                    seen = []
                    for l in (r.get('output') or '').splitlines():
                        m = re.search(r': (.+?): Moved \(server-side\) to: (.+)\.conflict\d+$', l.rstrip())
                        if m and m.group(1) == m.group(2) and m.group(1) not in seen:
                            seen.append(m.group(1))
                    r['both_sides'] = seen
                    if verbose and r.get('output'):
                        print(r['output'])
                return r
            if dry_run or entry['method'] != 'bisync' or attempt > retries + 3:
                return r
            kind, detail = self._bisync_failure((r.get('output') or '') + (r.get('error') or ''))
            if con:
                print(f'    attempt {attempt} failed ({kind}): {str(r.get("error", ""))[:200]}')
            if kind == 'lock' and not unlock:
                unlock = True
                notes.append('a stale lock dropped')
                continue
            if kind == 'too-many-deletes' and not force:
                side, gone, total = detail
                where = 'this machine' if side == 'Path1' else h['alias']
                if not self._side_intact(ctx, h, entry, side):
                    r['error'] = (f'{gone} of {total} files are gone from {where} and its folder is not a repository any more '
                                  f'(no _cmr.yaml, or empty): nothing forced - look at it before anything is deleted on the other side')
                    return r
                force, backup = True, True
                notes.append(f'{gone} of {total} files gone from {where}: the deletes forced (the host keeps its copies in its sync-backup artifact)')
                if con: print(f'    {notes[-1]}')
                continue
            if kind == 'needs-resync' and not resync:
                if self._remote_empty(ctx, h, entry):
                    resync, resync_mode = True, 'path1'
                    notes.append('a new pair: seeded from this machine (--resync --resync_mode=path1)')
                    if con: print(f'    {notes[-1]}')
                    continue
                r['error'] = (f'{r.get("error", "")} - the pair needs a new baseline: read "cx host sync {h["alias"]} --repos={name} '
                              f'--resync --resync_mode=path1 --dry_run" (path1 = this machine wins, path2 = the host) and run it')
                return r
            if kind == 'transient' and attempt <= retries:
                notes.append('tried again')
                time.sleep(5)
                continue
            return r

    @staticmethod
    def _check_summary(path):
        """rclone check --combined=<path> read: how many files are equal, missing on the host, missing here, different,
        in error; the conflict copies rclone's bisync left (<name>.conflict<n>) on either side."""
        n = {'equal': 0, 'missing_host': 0, 'missing_here': 0, 'differ': 0, 'errors': 0, 'conflicts': []}
        keys = {'=': 'equal', '-': 'missing_host', '+': 'missing_here', '*': 'differ', '!': 'errors'}
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.rstrip('\n')
                    if len(line) < 3 or line[1] != ' ' or line[0] not in keys:
                        continue
                    n[keys[line[0]]] += 1
                    if re.search(r'\.conflict\d+$', line[2:]):
                        n['conflicts'].append(line[2:])
        except OSError:
            n['errors'] = -1
        # conflict copies present on both sides are in step: noted, not a difference (a conflict made by this run is
        # judged by the run's own words - "New or changed in both paths" - in sync_)
        n['ok'] = n['errors'] == 0 and not (n['missing_host'] or n['missing_here'] or n['differ'])
        return n

    @staticmethod
    def _check_text(n):
        if n.get('errors', 0) < 0:
            return 'not read'
        note = f'; {len(n["conflicts"])} conflict copies to look at' if n.get('conflicts') else ''
        if n.get('ok'):
            return f'identical ({n["equal"]})' + note
        parts = []
        if n['missing_host']: parts.append(f'{n["missing_host"]} missing there')
        if n['missing_here']: parts.append(f'{n["missing_here"]} missing here')
        if n['differ']: parts.append(f'{n["differ"]} differ')
        if n['errors']: parts.append(f'{n["errors"]} unreadable')
        return 'DIFFERENCES: ' + ', '.join(parts) + note

    def _check_repo(self, ctx, h, name, entry, con, verbose):
        """The two sides compared name by name and size by size (rclone check --size-only, the sync's own filters;
        one way for a copy): the proof that the repository is in step, independent of rclone's listings. -> the
        summary of _check_summary plus 'file' (the combined listing kept in the bisync workdir)."""
        method = entry['method']
        local = entry['local']
        rules = []
        if entry.get('artifacts'):
            r = self._selection_rules(local, entry['artifacts'])
            if r['return'] > 0:
                return {'ok': False, 'errors': -1, 'error': r['error']}
            rules = r['rules']
        workdir = self._bisync_workdir(h, entry)
        os.makedirs(workdir, exist_ok=True)
        combined = os.path.join(workdir, 'check-' + re.sub(r'[^A-Za-z0-9_.@-]', '_', name) + '.txt')
        extra = ['--size-only', '--combined', combined]
        if rules: extra.append('--ignore-case')
        if method == 'copy': extra.append('--one-way')
        for attempt in (1, 2):                      # a check that fails to run (a connection hiccup) is tried once more
            r = self._rclone(ctx, h, 'check', local, entry['remote'], whitelist=rules or None, blacklist=entry['blacklist'],
                             extra=extra, con=con, verbose=verbose, capture=True, accept=(0, 1))
            if r.get('return', 0) == 0:
                break
            time.sleep(3)
        if r.get('return', 0) > 0:
            return {'ok': False, 'errors': -1, 'error': r.get('error', 'rclone check failed'), 'file': combined}
        n = self._check_summary(combined)
        n['file'] = combined
        return n

    @staticmethod
    def _merge_index_lines(a, b):
        """Two versions of a memory index (one line per memory): the lines of the first, then the lines of the second
        it does not have, in their order - nothing of either side is lost."""
        la = a.rstrip('\n').split('\n') if a.strip() else []
        lb = b.rstrip('\n').split('\n') if b.strip() else []
        seen = set(la)
        merged = la + [l for l in lb if l not in seen and l.strip()]
        return '\n'.join(merged).rstrip('\n') + '\n'

    def _settle_index_conflicts(self, ctx, h, name, entry, conflicts, con, verbose):
        """Conflict copies of a memory index (MEMORY.md.conflict1 / .conflict2: two sessions wrote one index between two
        syncs) merged by line union into MEMORY.md, written here and put on the host with the same time (so the next
        bisync sees one equal file), the copies removed on both sides. Other conflicts are left for a person.
        -> the list of indexes merged."""
        local, remote = entry['local'], entry['remote']
        merged = []
        by_base = {}
        for path in conflicts:
            m = re.match(r'^(.*?)\.conflict\d+$', path)
            if m and os.path.basename(m.group(1)) == 'MEMORY.md':
                by_base.setdefault(m.group(1), []).append(path)
        for base, copies in sorted(by_base.items()):
            texts = []
            for c in sorted(copies):
                lp = os.path.join(local, *c.split('/'))
                if os.path.isfile(lp):
                    with open(lp, encoding='utf-8', errors='replace') as f:
                        texts.append(f.read())
            lp = os.path.join(local, *base.split('/'))
            if os.path.isfile(lp):
                with open(lp, encoding='utf-8', errors='replace') as f:
                    texts.insert(0, f.read())
            if not texts:
                continue
            text = texts[0]
            for other in texts[1:]:
                text = self._merge_index_lines(text, other)
            os.makedirs(os.path.dirname(lp), exist_ok=True)
            with open(lp, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
            r = self._rclone(ctx, h, 'copyto', lp, remote + '/' + base, con=False, verbose=verbose, capture=True)
            if r.get('return', 0) > 0:
                if con: print(f'WARNING: {base} merged here, not put on {h["alias"]}: {r.get("error")}')
                continue
            for c in copies:
                cp = os.path.join(local, *c.split('/'))
                if os.path.isfile(cp):
                    os.remove(cp)
                q = self._sh_path(remote + '/' + c) if self._shell(h).strip() not in ('powershell', 'pwsh') else None
                if q:
                    rr = self._cmd_run(ctx, h, f'rm -f {q}')
                    if rr.get('return', 0) == 0:
                        self._run_local(rr['cmd'], capture=True, con=False, verbose=False, timeout=60)
            merged.append(base)
            if con: print(f'    {base}: {len(copies)} conflict copies merged by line union, the same file on both sides')
        return merged

    @staticmethod
    def _banner(ok, summary):
        """STATUS: SUCCESS or STATUS: FAILED in large letters, with the summary under it."""
        font = {'S': (' ###', '#   ', ' ## ', '   #', '### '), 'U': ('#  #', '#  #', '#  #', '#  #', ' ## '),
                'C': (' ###', '#   ', '#   ', '#   ', ' ###'), 'E': ('####', '#   ', '### ', '#   ', '####'),
                'F': ('####', '#   ', '### ', '#   ', '#   '), 'A': (' ## ', '#  #', '####', '#  #', '#  #'),
                'I': ('###', ' # ', ' # ', ' # ', '###'), 'L': ('#   ', '#   ', '#   ', '#   ', '####'),
                'D': ('### ', '#  #', '#  #', '#  #', '### '), '!': ('#', '#', '#', ' ', '#')}
        word = 'SUCCESS!' if ok else 'FAILED!'
        rows = ['  '.join(font[c][i] for c in word) for i in range(5)]
        line = '=' * 100
        # the summary wrapped at the line's width, a problem per line
        text = []
        for part in summary.split(' | '):
            text += textwrap.wrap(part, 100) or ['']
        return '\n'.join([line, 'STATUS:'] + rows + text + [line])

    def _after_partial(self, ctx, h, name, entry, rules, how, con, verbose):
        """After a partial repository reached a host: PARTIAL.md there, and the repository indexed (plugged the first time)."""
        r = self._write_partial_note(ctx, h, name, entry['remote'], entry['artifacts'], rules, how, verbose)
        if r['return'] > 0 and con:
            print(f'WARNING: {PARTIAL_NOTE} was not written on {h["alias"]}: {r.get("error")}')
        r = self._index_on_host(ctx, h, name, entry['remote'], con, verbose)
        if self.cm.catch_error(r): return r
        return {'return': 0}

    def _rclone(self, ctx, h, command, local, remote_path, whitelist=None, blacklist=None, extra=None,
                con=True, verbose=False, workdir=None, unlock=False, from_remote=False, capture=False, accept=(0,)):
        """rclone <command> local -> host (host -> local with from_remote), through the task rclone-to-ssh (which
        sets rclone up if needed). capture: rclone's output comes back in 'output' instead of the console; accept:
        the return codes that are not an error (rclone check answers 1 when the sides differ)."""
        r = self._ssh_parts(h)
        if r['return'] > 0: return r

        ii = {
            'category': self.cmeta['uses_categories']['task'],
            'command': 'run',
            'arg1': self.cmeta['uses_artifacts']['task::rclone-to-ssh'],
            'rclone_command': command,
            'local_dir': local,
            'remote': f'{r["target"]}:{remote_path}',
            'ssh_options': r['options'],
            'blacklist': list(blacklist or []),
            'whitelist': list(whitelist or []),
            'progress': False,
            'unparsed': list(extra or []),
            'con': con,
            'verbose': verbose,
            # -q of the host command reaches the task: rclone is set up without asking (the cache may have been cleaned)
            'quiet': bool(ctx['control'].get('quiet', False)),
        }
        if workdir: ii['workdir'] = workdir
        if unlock: ii['unlock'] = True
        if from_remote: ii['from_remote'] = True
        if capture:
            ii['capture'] = True
            ii['unparsed'] = list(ii['unparsed']) + ['--color', 'never']      # the paths it names, read as they are

        rr = self.cm.access(ii)
        if self.cm.catch_error(rr): return rr
        output = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', (rr.get('stdout') or '') + (rr.get('stderr') or ''))
        if rr.get('returncode', 0) not in accept:
            # the cause from rclone's own words, for the table and the verdict
            tail = [l.split(' : ', 1)[-1].strip() for l in output.splitlines() if 'ERROR' in l or 'NOTICE' in l]
            tail = [l for l in tail if l and 'Skipped' not in l][-2:]
            r = self.cm.error(f'rclone {command} returned {rr.get("returncode")}' + (': ' + ' | '.join(tail) if tail else ''))
            r['output'] = output
            r['returncode'] = rr.get('returncode')
            return r
        return {'return': 0, 'cmd': rr.get('cmd'), 'returncode': rr.get('returncode', 0), 'output': output}

    ############################################################
    # Output
    ############################################################

    def _address_text(self, h):
        t = h['type']
        acc = h['desc'].get('access') or {}
        if t == 'ssh':
            if self._here(h): return 'this machine'
            addr = acc.get('address') or h['alias']
            return f'{acc["user"]}@{addr}' if acc.get('user') else str(addr)
        if t == 'wsl':
            return f'wsl {acc.get("distro", "?")}' + (f' via {h["via"]}' if h.get('via') else '')
        if t == 'docker':
            return f'{self._engine(h)} {acc.get("container") or h["alias"]}' + (f' via {h["via"]}' if h.get('via') else '')
        if t == 'adb':
            via_list = h.get('via_list') or []
            text = f'adb {acc.get("serial", "?")}'
            if len(via_list) <= 1:
                return text + (f' via {h["via"]}' if h.get('via') else '')
            # a device that moves: where it is when a parent sees it; else only that it moves, and where it may be
            if h.get('via_seen'):
                return text + f' via {h["via"]} (moves)'
            return text + ' (moves: ' + ', '.join(via_list) + ')'
        return '?'

    @staticmethod
    def _os_short(h):
        """One word for the OS: the declared "os:" (ubuntu, windows, macos, android), else a guess from the probed one."""
        declared = str((h.get('desc') or {}).get('os') or '').strip()
        if declared:
            return declared.lower()
        probed = str((h.get('state') or {}).get('os') or '').lower()
        for word in ('ubuntu', 'debian', 'fedora', 'windows', 'android', 'macos'):
            if word in probed:
                return word
        if 'darwin' in probed or 'mac os' in probed:
            return 'macos'
        return probed.split()[0] if probed else '-'

    def _row(self, h, with_status):
        st = h['state'] or {}
        os_text = st.get('os', '-')
        probed = st.get('probed_at', '-')
        if probed != '-':
            probed = probed[:16].replace('T', ' ')
        # a device that moves between machines: its own machine, then where it is - "@ <parent>" when a
        # parent sees it now, "(moves)" when none does, "@ <parent>?" when not asked (last seen there)
        machine = h['machine'] or '-'
        if len(h.get('via_list') or []) > 1:
            if h.get('via_seen'):
                machine += ' @ ' + h['via']
            elif h.get('via_seen') is False:
                machine += ' (moves)'
            else:
                machine += ' @ ' + (h.get('via') or '?') + '?'
        row = {
            'alias': h['alias'],
            'type': h['type'],
            'machine': machine,
            'os': os_text if len(os_text) <= 26 else os_text[:25] + '~',
            'os_short': self._os_short(h),
            'sudo': st.get('sudo', '-'),
            'docker': self._tool_text(st.get('docker')),
            'podman': self._tool_text(st.get('podman')),
            'cmeta': st.get('cmeta_version', '-'),
            'aops': st.get('aops_version') or self._aops_version(st.get('repos') or {}) or ('none' if probed != '-' else '-'),
            'probed': probed,
        }
        row['projects'] = self._project_rows(h)
        if h.get('project'): row['project'] = h['project']
        # for programs that show the fleet (a web page): what the console prints in ADDRESS, and the artifact itself
        row['address'] = self._address_text(h)
        row['uid'] = str((h.get('cmeta') or {}).get('artifact') or h.get('uid') or '').split(',')[-1]
        row['tags'] = list((h.get('cmeta') or {}).get('tags') or [])
        row['made'] = bool((h.get('desc') or {}).get('made_from'))
        row['retired'] = self._retired(h)
        if with_status or row['retired']:
            row['status'] = 'retired' if row['retired'] else (h.get('status') or '-')
            if h.get('status_time') is not None:
                row['status_time'] = round(h['status_time'], 2)
            if h.get('parents'):
                row['parents'] = list(h['parents'])
        return row

    @staticmethod
    def _status_details(hosts):
        """{alias: [lines]} - printed under a host's row with -v (a moving device: what each parent answered)."""
        return {h['alias']: list(h['parents']) for h in hosts if h.get('parents')}

    @staticmethod
    def _aops_version(repos):
        """The _cmr.yaml version of the cMeta AOPS repository among a host's probed repositories, or None:
        by the artifact UID when the probe recorded it, else by the folder name (<owner>@cmeta-aops)."""
        if not isinstance(repos, dict):
            return None
        by_name = None
        for name, entry in repos.items():
            if not isinstance(entry, dict):
                continue
            artifact = str(entry.get('artifact') or '')
            if artifact.split(',')[-1].strip() == AOPS_REPO_UID:
                return str(entry.get('version') or '?')
            n = str(name).lower()
            if n == AOPS_REPO_NAME or n.endswith('@' + AOPS_REPO_NAME):
                by_name = str(entry.get('version') or '?')
        return by_name

    def _print_table(self, columns, rows, details=None, projects=None):
        """The table; `projects` = {first cell (the host): [project rows]} aligned in the same columns under
        that row (their "extra" text after the last column); `details` = {host: [lines]} printed indented."""
        keys = {'HOST': 'alias', 'TYPE': 'type', 'MACHINE': 'machine', 'STATUS': 'status', 'OS': 'os',
                'SUDO': 'sudo', 'DOCKER': 'docker', 'PODMAN': 'podman', 'CMETA': 'cmeta', 'AOPS': 'aops',
                'PROBED': 'probed'}
        table = []
        for row in rows:
            if isinstance(row, dict):
                table.append([str(row.get(keys.get(c, c.lower()), '-')) for c in columns])
            else:
                table.append([str(x) for x in row])
        sub = {host: [([str(p.get(keys.get(c, c.lower()), '')) for c in columns], str(p.get('extra', '')))
                      for p in lines] for host, lines in (projects or {}).items()}
        widths = [len(c) for c in columns]
        for row in table + [cells for lines in sub.values() for cells, _ in lines]:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))
        fmt = '  '.join('{:<' + str(w) + '}' for w in widths)
        print(fmt.format(*columns).rstrip())
        for row in table:
            print(fmt.format(*row).rstrip())
            for cells, extra in sub.get(row[0], []):
                line = fmt.format(*cells)
                print((line + '  ' + extra).rstrip() if extra else line.rstrip())
            for line in (details or {}).get(row[0], []) or []:
                print('    * ' + str(line))
