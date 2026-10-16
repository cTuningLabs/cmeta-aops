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
import os
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

# Columns of the fleet table (list); DOCKER and PODMAN = the client versions the probe saw ("-" = not
# installed, "(daemon down)" when the Docker client is there but no daemon answers)
LIST_COLUMNS = ['HOST', 'TYPE', 'MACHINE', 'STATUS', 'OS', 'SUDO', 'DOCKER', 'PODMAN', 'CMETA', 'AOPS', 'PROBED']

# The cMeta AOPS repository (ctuninglabs@cmeta-aops), known by the UID in its _cmr.yaml "artifact:" -
# its folder name differs between hosts (cTuningLabs@cmeta-aops on the Mac); the name is the fallback
# for a state.yaml probed before the artifact id was recorded.
AOPS_REPO_UID = '3cb4ee4f444048f6'
AOPS_REPO_NAME = 'cmeta-aops'


def declared_project_states(saved, desc):
    """The saved states of the projects the host still declares: a project taken out of _desc.yaml leaves
    state.yaml at the next probe of the host (before 2026-10-16 its last state stayed there for ever)."""
    declared = (desc or {}).get('projects') or {}
    return {name: st for name, st in ((saved or {}).get('projects') or {}).items() if name in declared}


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
            if active:
                hosts = [h for h in hosts if h['status'] in ('up', 'here')]

        rows = []
        for h in hosts:
            rows.append(self._row(h, want_status))

        if con:
            cols = LIST_COLUMNS if want_status else [c for c in LIST_COLUMNS if c != 'STATUS']
            show = bool(details) or bool(d)
            self._print_table(cols, rows, details=self._status_details(hosts) if want_status and show else None,
                              projects=self._project_details(hosts))
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
                              projects=self._project_details(hosts))

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
            if stdin_file:
                r = self._cmd_stdin(ctx, h, stdin_file)
            else:
                r = self._cmd_run(ctx, h, cmd, raw=raw, interactive=bool(interactive))
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
        x11=False,          # ssh -X: X11 forwarding (or "access: x11: true" in the host's _desc.yaml)
        forward=None,       # ssh -L: local ports to forward to the host, e.g. --forward=1455 or --forward=8080:80,5000
        dry_run=False,      # print the command instead of opening the shell
    ):
        """
        Open an interactive shell on a host: ssh, wsl.exe -d, docker exec -it, adb shell.

            cx host ssh lab-mac-mini-macos               (also: cx host shell / login)
            cx host ssh lab-thinkpad-ubuntu --x11       # a remote GUI program shows up here
            cx host ssh lab-thinkpad-ubuntu --forward=1455   # a login page the host serves on localhost:1455 opens in this browser
        """

        con = ctx['control'].get('con', False)

        if not arg1:
            return self.cm.error('which host? cx host ssh <host>')

        r = self._get_host(ctx, arg1)
        if self.cm.catch_error(r): return r
        h = r['host']

        r = self._cmd_run(ctx, h, None, interactive=True, x11=bool(x11), forwards=self._csv(forward))
        if self.cm.catch_error(r): return r

        if r.get('here'):
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
        return {'return': 0, 'returncode': rc}

    ############################################################
    def restart_(
        self,
        ctx,
        arg1=None,          # host alias (one host)
        yes=False,          # do not ask (also implied by -q)
        wait=True,          # wait until the host answers again (--no-wait: return at once)
        timeout=600,        # seconds to wait for it
        skip_after=False,   # do not run the host's "commands: after_restart"
        dry_run=False,      # print what would run, restart nothing
    ):
        """
        Reboot a host - after a y/N question unless --yes or -q - then wait until it is back and run its
        "commands: after_restart" (servers to bring up). ssh hosts: "sudo -n shutdown -r now" (Windows:
        "shutdown /r /t 5"); a WSL distro: wsl -t + start; a container: docker restart; adb: adb reboot;
        or the host's own "commands: restart".

            cx host restart lab-laptop-ubuntu
            cx host restart dapple-labs-azure-vm-ubuntu --yes      # then its Labs server comes up again
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

        self._refresh_state(ctx, h, con)            # the uptime, the versions: state.yaml says what is there now
        return result

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
        project=None,      # named environment; omitted: the host's global environment
    ):
        """
        Bring a host's repositories up to date, the way its _desc.yaml declares: "bisync" (two-way, rclone
        over ssh, the user's _8-bisync scripts), "copy" (one-way local -> host, never deletes), "git"
        (git pull --ff-only on the host's own clone), per repository or by the host's default.

            cx host sync                                  # every reachable host that declares a sync
            cx host sync dapple-labs-azure-vm-ubuntu      # one host (being down is an error)
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
                report.append([alias, '*', '-', f'skipped ({h["status"]})', ''])
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
                r = self._sync_repo(ctx, h, name, entry, resync=resync, resync_mode=resync_mode, unlock=unlock,
                                    dry_run=dry_run, con=con, verbose=verbose)
                elapsed = f'{time.monotonic() - t0:.0f}s'
                if r['return'] > 0:
                    report.append([alias, name, entry['method'], 'FAILED: ' + r['error'], elapsed])
                    if con: print(f'*** STOPPED: {alias} / {name} failed - {r["error"]}')
                    return {'return': 1, 'error': f'{alias}: sync of {name} failed - {r["error"]}', 'report': report}
                report.append([alias, name, entry['method'], 'ok', elapsed])
                changed = True

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
                        report.append([alias, '(after)', cmd, f'exit code {rr.get("returncode")}', ''])
                        if con: print(f'WARNING: "{cmd}" on {alias} returned {rr.get("returncode")}')

            if changed and not dry_run:
                self._refresh_state(ctx, h, con)        # state.yaml says what is there now

        if con:
            print('')
            self._print_table(['HOST', 'REPOSITORY', 'METHOD', 'RESULT', 'TIME'], report)

        return {'return': 0, 'report': report}

    ############################################################
    def push_(
        self,
        ctx,
        arg1=None,          # host alias
        arg2=None,          # a repository name from the host's sync list, or a local path (then --to)
        dirs=None,          # only these directories/files of it (comma-separated, relative, "task/run-ai/")
        to=None,            # remote path (required for a local path; default for a repository: its remote)
        dry_run=False,      # show what would be copied, copy nothing
        delete=False,       # rclone sync instead of copy: also delete remote files missing locally (within --dirs)
        index=True,         # after a repository push: "cx --reindex" on the host, so a new artifact is found there (--index- skips it)
        unparsed=None,      # everything after "--" goes to rclone
        project=None,      # named environment; omitted: the host's global environment
    ):
        """
        Copy a few directories of a repository (or any local path) to a host, one way, local -> host,
        without touching the bisync baseline - for a quick fix when a sync glitched, or when only one task
        changed. Never deletes unless --delete. After a repository push the host's index is rebuilt
        ("cx --reindex", a second or two), so an artifact new to the host is found by "cx <cat> find" at
        once; --index- skips that (a push of category code or files only).

            cx host push lab-thinkpad-ubuntu ctuninglabs@cmeta-aops --dirs=task/run-ai/,tool/agy/
            cx host push lab-laptop-ubuntu ctuninglabs@cmeta-aops --dirs=task/run-ai/ --dry_run
            cx host push lab-mac-mini-macos D:\\tmp\\check.sh --to=/Users/user/cmeta-tests/check.sh

        The repository's blacklist (tmp*/, __pycache__/, .venv/, .git/ ...) still applies.
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
        if arg2 in entries:
            entry = entries[arg2]
            local = entry['local']
            remote_path = to or entry['remote']
            blacklist = entry['blacklist']
        else:
            local = os.path.abspath(arg2)
            if not os.path.exists(local):
                return self.cm.error(f'"{arg2}" is neither a repository of {h["alias"]} '
                                     f'({", ".join(entries) or "none declared"}) nor a local path')
            if not to:
                return self.cm.error('--to=<remote path> is required for a local path')
            remote_path = to

        whitelist = []
        for d in self._csv(dirs):
            d = d.replace('\\', '/')
            if not d.startswith('/'):
                d = '/' + d          # anchored: "task/run-ai/" means the top-level one, not every match
            whitelist.append(d)

        extra = list(self._csv(unparsed)) if isinstance(unparsed, str) else list(unparsed or [])
        if dry_run:
            extra.append('--dry-run')

        # a single file lands AT --to (rclone copyto); "copy" would make a folder of that name with the file
        # inside (seen 2026-10-07: --to=.../decode_test.py gave decode_test.py/decode_test.py)
        command = 'sync' if delete else ('copyto' if os.path.isfile(local) else 'copy')
        if command == 'copyto':
            whitelist, blacklist = [], []        # rclone: "can't limit to single files when using filters"
        r = self._rclone(ctx, h, command, local, remote_path,
                         whitelist=whitelist, blacklist=blacklist, extra=extra, con=con, verbose=verbose)
        if self.cm.catch_error(r): return r

        result = {'return': 0, 'host': h['alias'], 'local': local, 'remote': remote_path, 'dirs': whitelist}

        # A pushed folder is on the host's disk but not in its index until the index is rebuilt (seen 2026-10-06
        # with new tools: invisible to "cx tool find" there). The engine has no per-artifact refresh of an
        # existing path, and a full rebuild takes a second or two on the test hosts.
        if index and arg2 in entries and not dry_run:
            cmd = 'cx --reindex'
            r = self._cmd_run(ctx, h, cmd)
            if self.cm.catch_error(r): return r
            t0 = time.monotonic()
            rr = self._run_local(r['cmd'], capture=not verbose, con=con, verbose=verbose, timeout=300)
            result['index'] = {'cmd': cmd, 'returncode': rr.get('returncode'), 'seconds': round(time.monotonic() - t0, 1)}
            if con:
                if rr.get('returncode', 0) == 0:
                    print(f'INDEX ({h["alias"]}): {cmd} - ok ({time.monotonic() - t0:.1f}s)')
                else:
                    print(f'WARNING: "{cmd}" on {h["alias"]} returned {rr.get("returncode")} - run it there by hand')

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
            cx host upgrade dapple-labs-azure-vm-ubuntu --sync --restart --yes
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
                    cmd = f'{head}uv tool install --force --refresh "{spec}"'
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

    ############################################################
    def restore_(
        self,
        ctx,
        arg1=None,          # the instance
        name=None,          # the snapshot (default: the last one)
        force=False,        # a docker or wsl host declared by hand
    ):
        """
        Bring an instance back to a snapshot (the last one by default): a docker or podman container is removed
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
                # a folder's contents into the local folder ("/." as docker cp reads it), a file into it
                cmds = [f'{engine} cp {container}:{remote}/. {self.cm.utils.files.quote_path(dst)}',
                        f'{engine} cp {container}:{remote} {self.cm.utils.files.quote_path(dst)}']
            else:
                distro = str(acc.get('distro') or h['alias'])
                mnt = self._wsl_mnt(dst)
                copy = f'if [ -d {q(remote)} ]; then cp -r {q(remote + "/.")} {q(mnt)}; else cp {q(remote)} {q(mnt + "/")}; fi'
                cmds = [f'wsl.exe -d {distro}' + (f' --user {user}' if user else '') + f' -- sh -c "{copy}"']
            what = {'host': h['alias'], 'remote': remote, 'local': dst}

        if dry_run:
            if con:
                for cmd in cmds:
                    print (f'DRY RUN: {cmd}')
            return dict(what, **{'return': 0, 'dry_run': True, 'cmds': cmds})

        for i, cmd in enumerate(cmds):
            rr = self._run_local(cmd, capture=True, con=False, timeout=1800)
            ok = rr.get('returncode', 1) == 0
            if not into and h['type'] == 'docker':
                if ok:
                    break                                   # the folder form worked; the file form is the alternative
                if i == 0:
                    continue
            if not ok:
                return self.cm.error(f'"{cmd}" failed: {(rr.get("stderr") or rr.get("stdout") or "").strip()}')

        # pull --files: keep only the matching files of what came
        patterns = [p for p in (files or []) if p]
        if not into and patterns and os.path.isdir(dst):
            for folder, _, names in os.walk(dst):
                for name in names:
                    if not any(fnmatch.fnmatch(name, p) for p in patterns):
                        try:
                            os.remove(os.path.join(folder, name))
                        except OSError:
                            pass

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
        return dict(r, host_uid=h['uid'], host_alias=h['alias'])

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
            rows.append({'alias': name, 'path': p.get('path'), 'cmeta': st.get('cmeta_version', '-'),
                         'aops': st.get('aops_version', '-'), 'server': server,
                         'status': server.get('status', 'not checked'), 'probed': st.get('probed_at')})
        return rows

    def _project_details(self, hosts):
        return {h['alias']: [f'{p["alias"]}  server: {p["status"]}  cMeta: {p["cmeta"]}  '
                             f'AOPS: {p["aops"]}  {p["server"].get("url", "")}'
                             + (' (last probe)' if p['server'] and not h.get('project_status') else '')
                             for p in self._project_rows(h)] for h in hosts}

    def _project_status_all(self, ctx, hosts, timeout=DEFAULT_STATUS_TIMEOUT, cmd_timeout=DEFAULT_STATUS_CMD_TIMEOUT):
        """One bounded remote HTTP check batch per reachable host; never start a project server."""
        from concurrent.futures import ThreadPoolExecutor

        def one(h):
            desc = h.get('host_desc') or h['desc']
            names = [h['project']] if h.get('project') else list(desc.get('projects') or {})
            if not names: return
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
        """
        posix = os.name != 'nt'
        try:
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
        t = h['type']
        acc = h['desc'].get('access') or {}

        if t == 'ssh':
            if self._here(h):
                return 'here'
            addr = acc.get('address') or h['alias']
            port = int(acc.get('port') or DEFAULT_SSH_PORT)
            try:
                with socket.create_connection((addr, port), timeout=timeout):
                    return 'up'
            except OSError:
                return 'down'

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

    def _usable(self, h):
        """
        A host a command can run on: up, this machine ("here"), or a WSL distro that is merely stopped
        (wsl.exe starts it for the next command). Everything else - down, missing, timeout, error - is skipped.
        """
        return h.get('status') in ('up', 'here') or (h.get('type') == 'wsl' and h.get('status') == 'stopped')

    def _here(self, h):
        """This host is the machine the command runs on: its declared hostname is the local one."""
        if h['type'] != 'ssh':
            return False
        acc = h['desc'].get('access') or {}
        name = acc.get('hostname')
        if not name:
            return False
        me = platform.node().split('.')[0].lower()
        return str(name).split('.')[0].lower() == me

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
        is not on this machine - another orchestrator without that private repository - falls back to a
        file of the same name in ~/.ssh.
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
                path = os.path.join(os.path.expanduser('~'), '.ssh', os.path.basename(rel))
                if not os.path.isfile(path):
                    return self.cm.error(f'key artifact "{cref}" is not on this machine and ~/.ssh/{os.path.basename(rel)} '
                                         f'does not exist either (from "{key}")')
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
            opts.append('-X')
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
            if cmd is not None and not interactive and not stdin and os.name == 'nt' and any(c in cmd for c in '"^%\n\r'):
                r = self._temp_script(cmd)
                if r['return'] > 0: return r
                return self._cmd_stdin(ctx, h, r['path'])
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
            # for ever beyond a few KB (the 4.9 KB probe hung until its timeout).
            import base64, hashlib, tempfile
            with open(script, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('ascii')
            stdin_file = os.path.join(tempfile.gettempdir(),
                                      'cmeta-host-script-' + hashlib.sha1(script.encode('utf-8')).hexdigest()[:12] + '.b64')
            with open(stdin_file, 'w') as f:
                f.write('\n'.join(b64[i:i + 76] for i in range(0, len(b64), 76)) + '\n')
            reader_ps = ('[Console]::OutputEncoding = [Text.Encoding]::UTF8; '
                         "$s = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((@($input) -join ''))); "
                         'Invoke-Expression $s')
            encoded = base64.b64encode(reader_ps.encode('utf-16-le')).decode('ascii')
            reader = f'{shell.strip()} -NoProfile -EncodedCommand {encoded}'
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
        return self.cm.utils.sys.run(cmd, capture_output=capture, timeout=timeout, con=con, verbose=verbose,
                                     print_cmd=verbose, fail_on_error=False, logger=self.logger)

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
        {name: {'method', 'local', 'remote', 'blacklist', 'workdir'}} from the host's "sync:" block.
        An entry is a name, or {name: {method, remote, blacklist, workdir}}. The remote folder of a
        repository is its own `remote`, else `<repos path>/<name>` (see _sync_repos_path).
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
            }
        return entries

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

    def _sync_repo(self, ctx, h, name, entry, resync, resync_mode, unlock, dry_run, con, verbose):
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
            rr = self._run_local(r['cmd'], capture=False, con=con, verbose=verbose)
            if rr.get('returncode', 1) != 0:
                return self.cm.error(f'git on {h["alias"]} returned {rr.get("returncode")}')
            return {'return': 0}

        local = entry['local']
        if not os.path.isdir(local):
            return self.cm.error(f'local repository not found: {local}')

        extra = list(DEFAULT_RCLONE_FLAGS)
        if dry_run: extra.append('--dry-run')

        if method == 'copy':
            return self._rclone(ctx, h, 'copy', local, entry['remote'], blacklist=entry['blacklist'],
                                extra=extra, con=con, verbose=verbose)

        # bisync
        if resync:
            mode = str(resync_mode or 'newer')
            if mode not in ('newer', 'older', 'path1', 'path2', 'larger', 'smaller'):
                return self.cm.error(f'unknown --resync_mode "{mode}" (newer | older | path1 | path2 | larger | smaller)')
            extra += ['--resync-mode', mode]
        return self._rclone(ctx, h, 'resync' if resync else 'bisync', local, entry['remote'],
                            blacklist=entry['blacklist'], extra=extra, con=con, verbose=verbose,
                            workdir=self._bisync_workdir(h, entry), unlock=unlock)

    def _rclone(self, ctx, h, command, local, remote_path, whitelist=None, blacklist=None, extra=None,
                con=True, verbose=False, workdir=None, unlock=False, from_remote=False):
        """rclone <command> local -> host (host -> local with from_remote), through the task rclone-to-ssh (which
        sets rclone up if needed)."""
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

        rr = self.cm.access(ii)
        if self.cm.catch_error(rr): return rr
        if rr.get('returncode', 0) != 0:
            return self.cm.error(f'rclone {command} returned {rr.get("returncode")}')
        return {'return': 0, 'cmd': rr.get('cmd')}

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
        if with_status:
            row['status'] = h.get('status') or '-'
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
        """The table; `details` = {first cell (the host): [lines]} printed indented under that row."""
        keys = {'HOST': 'alias', 'TYPE': 'type', 'MACHINE': 'machine', 'STATUS': 'status', 'OS': 'os',
                'SUDO': 'sudo', 'DOCKER': 'docker', 'PODMAN': 'podman', 'CMETA': 'cmeta', 'AOPS': 'aops',
                'PROBED': 'probed'}
        table = []
        for row in rows:
            if isinstance(row, dict):
                table.append([str(row.get(keys.get(c, c.lower()), '-')) for c in columns])
            else:
                table.append([str(x) for x in row])
        widths = [len(c) for c in columns]
        for row in table:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))
        fmt = '  '.join('{:<' + str(w) + '}' for w in widths)
        print(fmt.format(*columns).rstrip())
        for row in table:
            print(fmt.format(*row).rstrip())
            for line in (projects or {}).get(row[0], []) or []:
                print('  * ' + str(line))
            for line in (details or {}).get(row[0], []) or []:
                print('    * ' + str(line))
