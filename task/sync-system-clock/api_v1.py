"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

sync-system-clock: the system clock checked against a time server and, when it is off or its time service is
not running, put right with the OS's own commands - Windows: the Windows Time service (w32time) set to start
automatically, started and told to resync (an elevated PowerShell: expect the administrator prompt); Linux:
NTP switched on with timedatectl and systemd-timesyncd restarted or chrony stepped; WSL2: the clock is a copy
of the Windows host's, "hwclock -s" sets it again from the hardware clock, and the Windows host is where the
lasting fix is; macOS: sntp against the server and network time switched on. plan() is pure and decides the
commands; run() measures, then executes the fix when it is needed, then measures again.

Why a task: on 2026-10-12 the clock of WSL2 on a laptop was seen stepping by -3.3 s and +6.2 s every 30 s - the
Windows host's time service was stopped and its clock 6 s off, and the distribution's NTP kept correcting the
copy. cMeta measures its own durations on the monotonic clock since then; every program that compares
timestamps (TLS, git, make, Kerberos, file syncs) suffers from such a clock, so the fix is one command on every
machine of a fleet.

    cx task run sync-system-clock                   # measure; fix when the clock is off or the service is down
    cx task run sync-system-clock --check           # measure and report only
    cx task run sync-system-clock --force           # fix even when the clock looks right
    cx task run sync-system-clock --server=pool.ntp.org --max_offset=0.5
"""

import os
import re
import shutil
import sys
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

DEFAULT_SERVER = {'windows': 'time.windows.com', 'darwin': 'time.apple.com', 'linux': 'pool.ntp.org', 'wsl2': 'pool.ntp.org'}

# The Windows fix, elevated: an inner PowerShell started with RunAs and waited for, as task/enable-long-paths-win
# does it (exit 1223 = the administrator prompt was declined). The inner command holds no quotes of its own.
WINDOWS_FIX_INNER = ('Set-Service -Name w32time -StartupType Automatic; Start-Service -Name w32time; '
                     'w32tm /resync /rediscover | Out-Null; exit $LASTEXITCODE')
WINDOWS_FIX = (
    'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "'
    'try { $p = Start-Process -FilePath powershell.exe -ArgumentList '
    "'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command','" + WINDOWS_FIX_INNER + "' "
    '-Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode } '
    'catch { Write-Host $_.Exception.Message; exit 1223 }"'
)

# What to do by hand when the automatic fix cannot run (no passwordless sudo, the prompt declined)
MANUAL = {
    'windows': ['Open a terminal as administrator and run:',
                '  sc config w32time start= auto', '  net start w32time', '  w32tm /resync /rediscover'],
    'linux': ['Run with root rights:', '  timedatectl set-ntp true',
              '  systemctl restart systemd-timesyncd    (or: chronyc makestep, when chrony keeps the clock)'],
    'wsl2': ['Inside WSL2 run: sudo hwclock -s   (sets the clock from the hardware clock = the Windows clock);',
             'the lasting fix is the WINDOWS host\'s time service: run this task there (an administrator prompt).'],
    'darwin': ['Run with root rights:', '  sntp -sS <server>', '  systemsetup -setusingnetworktime on'],
}


##############################################################################################################
# The measurements, as text to parse: pure functions, tested offline

def parse_w32tm_stripchart(text):
    """The offsets `w32tm /stripchart /dataonly` prints, one per sample in seconds ("22:10:38, -00.0123447s"),
    and the lines it prints instead when the server does not answer ("22:10:38, error: 0x800705B4")."""
    offsets, errors = [], []
    for line in text.splitlines():
        m = re.search(r',\s*([+-]?\d+(?:\.\d+)?)s\s*$', line.strip())
        if m:
            offsets.append(float(m.group(1)))
        elif 'error' in line.lower():
            errors.append(line.strip())
    return offsets, errors


def parse_sc_query(text):
    """The state of a Windows service from `sc query <name>` ("STATE : 4  RUNNING" -> "running")."""
    m = re.search(r'STATE\s*:\s*\d+\s+([A-Z_]+)', text)
    return m.group(1).lower() if m else 'unknown'


def parse_timedatectl(text):
    """`timedatectl show` (key=value lines) or `timedatectl` (Key: value lines) as a dict of lower-case keys."""
    d = {}
    for line in text.splitlines():
        line = line.strip()
        if '=' in line and ' ' not in line.split('=', 1)[0]:
            k, v = line.split('=', 1)
        elif ':' in line:
            k, v = line.split(':', 1)
        else:
            continue
        d[k.strip().lower().replace(' ', '_')] = v.strip()
    return d


def parse_offset_line(text, key = 'offset'):
    """The seconds of the line that holds `key`: "Offset: +1.234ms" (timedatectl timesync-status), "System time :
    0.000123 seconds fast of NTP time" (chronyc tracking; "slow" is negative). The sign as the tool prints it.
    None when there is no such line."""
    for line in text.splitlines():
        if key not in line.lower():
            continue
        m = re.search(r'([+-]?\d+(?:\.\d+)?)\s*(ns|us|µs|ms|s)\b', line)
        if m:
            scale = {'ns': 1e-9, 'us': 1e-6, 'µs': 1e-6, 'ms': 1e-3, 's': 1.0}[m.group(2)]
            return float(m.group(1)) * scale
        m = re.search(r'([+-]?\d+(?:\.\d+)?)\s*seconds?\s+(fast|slow)', line)
        if m:
            value = float(m.group(1))
            return value if m.group(2) == 'fast' else -value
    return None


def parse_sntp(text):
    """macOS sntp: "+0.012345 +/- 0.001234 time.apple.com 17.253.2.253" -> 0.012345; None without such a line."""
    for line in text.splitlines():
        m = re.match(r'\s*([+-]\d+(?:\.\d+)?)\s+\+/-', line)
        if m:
            return float(m.group(1))
    return None


##############################################################################################################
# The commands per OS: pure

def detect_os():
    """'windows', 'darwin', 'wsl2' or 'linux' (a Linux kernel built by Microsoft is WSL)."""
    if os.name == 'nt':
        return 'windows'
    if sys.platform == 'darwin':
        return 'darwin'
    try:
        with open('/proc/sys/kernel/osrelease') as f:
            if 'microsoft' in f.read().lower():
                return 'wsl2'
    except OSError:
        pass
    return 'linux'


def plan(uname, has = None, server = None, samples = 3):
    """
    The commands of this OS as a dict: 'measure' - (command, parser name) pairs that give the offset of the
    clock and the state of the time service; 'fix' - (name, command, needs_sudo) steps that put the clock
    right; 'service' - the name of what keeps the clock. `has(name)` says whether a program is on the machine
    (shutil.which by default). Nothing runs here.
    """
    has = has or (lambda name: shutil.which(name) is not None)
    server = server or DEFAULT_SERVER.get(uname, 'pool.ntp.org')
    p = {'os': uname, 'server': server, 'measure': [], 'fix': [], 'service': None}

    if uname == 'windows':
        p['service'] = 'w32time'
        p['measure'].append((f'w32tm /stripchart /computer:{server} /samples:{int(samples)} /dataonly', 'w32tm'))
        p['measure'].append(('sc query w32time', 'sc'))
        p['fix'].append(('w32time: automatic, started, resynced (administrator prompt)', WINDOWS_FIX, False))

    elif uname == 'darwin':
        p['service'] = 'network time (sntp)'
        p['measure'].append((f'sntp {server}', 'sntp'))
        p['fix'].append(('the clock stepped from the server', f'sntp -sS {server}', True))
        p['fix'].append(('network time on', 'systemsetup -setusingnetworktime on', True))

    else:
        chrony = has('chronyc')
        p['service'] = 'chrony' if chrony else 'systemd-timesyncd'
        if chrony:
            p['measure'].append(('chronyc tracking', 'chronyc'))
        elif has('timedatectl'):
            p['measure'].append(('timedatectl timesync-status', 'timesync'))
        if has('timedatectl'):
            p['measure'].append(('timedatectl show', 'timedatectl'))
        if uname == 'wsl2':
            p['fix'].append(('the clock set from the hardware clock (the Windows host\'s)', 'hwclock -s', True))
        else:
            if has('timedatectl'):
                p['fix'].append(('NTP on', 'timedatectl set-ntp true', True))
            if chrony:
                p['fix'].append(('chrony stepped', 'chronyc makestep', True))
            else:
                p['fix'].append(('systemd-timesyncd restarted', 'systemctl restart systemd-timesyncd', True))
    return p


def with_sudo(cmd, needs_sudo, interactive):
    """sudo in front of a system command: "-n" (never a hidden prompt) unless the run is interactive."""
    if not needs_sudo:
        return cmd
    return ('sudo ' if interactive else 'sudo -n ') + cmd


def read_measurements(outputs):
    """The offset (seconds, the tool's sign), the text it came from and the service state, from the outputs of
    the 'measure' commands: {parser name: text}."""
    offset, source, state = None, '', {}
    if 'w32tm' in outputs:
        offsets, errors = parse_w32tm_stripchart(outputs['w32tm'])
        if offsets:
            offset, source = sum(offsets) / len(offsets), f'w32tm against the server, {len(offsets)} sample(s)'
        elif errors:
            source = 'w32tm: ' + errors[0]
    if 'sc' in outputs:
        state['state'] = parse_sc_query(outputs['sc'])
    if 'sntp' in outputs:
        offset, source = parse_sntp(outputs['sntp']), 'sntp against the server'
    if 'chronyc' in outputs:
        offset, source = parse_offset_line(outputs['chronyc'], 'system time'), 'chronyc tracking'
    if 'timesync' in outputs:
        offset, source = parse_offset_line(outputs['timesync'], 'offset'), 'timedatectl timesync-status'
    if 'timedatectl' in outputs:
        d = parse_timedatectl(outputs['timedatectl'])
        ntp = d.get('ntp', d.get('ntp_service', ''))
        state['ntp'] = ntp
        state['synchronized'] = d.get('ntpsynchronized', d.get('system_clock_synchronized', ''))
        state['state'] = 'running' if ntp.lower() in ('yes', 'active') else ('stopped' if ntp else 'unknown')
    return offset, source, state


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,                  # cMeta context
            check: bool = False,        # measure and report only
            force: bool = False,        # fix even when the clock looks right
            server: str = None,         # the time server to measure against (the OS's default otherwise)
            max_offset: float = 1.0,    # seconds: a larger offset (either way) is "off"
            samples: int = 3,           # w32tm samples
            timeout: int = 180,         # seconds per command
            delay: int = 3,             # seconds before the administrator prompt on Windows
    ):
        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **os** (str): windows, linux, wsl2 or darwin.
                - **offset_seconds** (float | None): the clock's offset as the tool prints it; None when no tool answered.
                - **offset_source** (str): which tool measured it.
                - **service** (dict): the state of what keeps the clock.
                - **ok** (bool): within max_offset and the service running.
                - **fixed** (bool | None): what the fix achieved (None: nothing was run).
                - **actions** (list): the commands that ran.
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        uname = detect_os()
        p = plan(uname, server = server, samples = samples)
        interactive = (not quiet) and sys.stdin.isatty()
        max_offset = float(max_offset)

        if not p['measure']:
            return self.cm.error(f'no program to measure the clock with on this {uname} machine (timedatectl, chronyc, sntp or w32tm)')

        r = self._measure(p, con, verbose, space, timeout)
        offset, source, state = r['offset'], r['source'], r['state']

        ok = offset is not None and abs(offset) <= max_offset and state.get('state', 'running') == 'running'
        result = {'return': 0, 'os': uname, 'server': p['server'], 'offset_seconds': offset, 'offset_source': source,
                  'service': dict(state, name = p['service']), 'ok': ok, 'fixed': None, 'actions': []}

        if con:
            print ('')
            print (f'{space}{self._line(uname, p, offset, source, state, max_offset)}')

        if check or (ok and not force):
            return result

        # The fix
        if con:
            print ('')
            if uname == 'windows':
                print (f'{space}INFO: the Windows Time service will be set to start automatically, started and told to resync:')
                print (f'{space}      a command runs in administrator mode, so please accept the Windows prompt (UAC).')
                sys.stdout.flush()
                time.sleep(int(delay))
            else:
                print (f'{space}INFO: putting the clock right with the OS\'s own commands ...')

        failed = []
        for name, cmd, needs_sudo in p['fix']:
            line = with_sudo(cmd, needs_sudo, interactive)
            result['actions'].append(line)
            rr = self.cm.utils.sys.run(line, capture_output = not con, con = con, timeout = int(timeout), verbose = verbose,
                                       text_cmd = 'RUN:', space = space, fail_on_error = False, logger = self.logger)
            rc = rr.get('returncode', -1) if rr.get('return', 0) == 0 else -1
            if rc != 0:
                why = {1223: 'the administrator prompt was declined'}.get(rc, f'exit code {rc}')
                if needs_sudo and rc == 1 and not interactive:
                    why += ' - sudo needs a password here: run it in a terminal, or add a NOPASSWD rule'
                failed.append(f'{name}: {why}')

        # Measured again
        r = self._measure(p, con, verbose, space, timeout)
        offset2, source2, state2 = r['offset'], r['source'], r['state']
        ok2 = offset2 is not None and abs(offset2) <= max_offset and state2.get('state', 'running') == 'running'
        result.update(offset_seconds = offset2, offset_source = source2, service = dict(state2, name = p['service']),
                      ok = ok2, fixed = ok2)

        if con:
            print ('')
            print (f'{space}after: {self._line(uname, p, offset2, source2, state2, max_offset)}')

        if ok2:
            if uname == 'wsl2' and con:
                print (f'{space}NOTE: WSL2 copies the Windows host\'s clock - run this task on the Windows host for the lasting fix.')
            return result

        steps = '\n'.join('  ' + x for x in MANUAL.get(uname, []))
        detail = ('; '.join(failed) + '. ') if failed else ''
        return self.cm.error(f'the clock is not right after the fix ({detail}{self._line(uname, p, offset2, source2, state2, max_offset)}).\n'
                             f'By hand:\n{steps}')

    ############################################################
    def _measure(self, p, con, verbose, space, timeout):
        """Run the 'measure' commands and read them."""
        outputs = {}
        for cmd, parser in p['measure']:
            rr = self.cm.utils.sys.run(cmd, capture_output = True, con = False, timeout = int(timeout), verbose = verbose,
                                       text_cmd = 'RUN:', space = space, fail_on_error = False, logger = self.logger)
            if con and verbose:
                print (f'{space}RUN: {cmd}')
            outputs[parser] = (rr.get('stdout') or '') + '\n' + (rr.get('stderr') or '') if rr.get('return', 0) == 0 else ''
        offset, source, state = read_measurements(outputs)
        return {'offset': offset, 'source': source, 'state': state}

    ############################################################
    @staticmethod
    def _line(uname, p, offset, source, state, max_offset):
        """One line: the OS, the service, the offset and the verdict."""
        names = {'windows': 'Windows', 'darwin': 'macOS', 'wsl2': 'WSL2 (a copy of the Windows host\'s clock)', 'linux': 'Linux'}
        svc = p['service'] + (f' {state["state"]}' if state.get('state') else '')
        if offset is None:
            what = f'offset unknown ({source or "no answer from the time server"})'
            verdict = 'CANNOT TELL'
        else:
            what = f'offset {offset:+.3f} s ({source})'
            verdict = 'OK' if abs(offset) <= max_offset else f'OFF by more than {max_offset:g} s'
        if state.get('state') not in (None, 'running', 'unknown'):
            verdict = f'the time service is {state["state"]}'
        return f'clock: {names.get(uname, uname)}, {svc}, {what} against {p["server"]} - {verdict}'
