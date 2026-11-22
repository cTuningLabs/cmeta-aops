"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

set-wsl-network: WSL 2's network mode on this Windows machine (nat or mirrored) in %USERPROFILE%\\.wslconfig, the mode in
use, and the Hyper-V firewall rule that lets chosen machines reach WSL in mirrored mode. See _desc.yaml.
"""

import base64
import ipaddress
import os
import re
import subprocess

from task_c36be4b9314a45e0.api.ctask import InitCTask


WSL_VM_CREATOR = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'   # the Hyper-V firewall's id of WSL
RULE = 'cmeta-wsl-allow'
MODES = ('nat', 'mirrored')


def set_mode(text, mode):
    """The text of a .wslconfig with networkingMode=<mode> in its [wsl2] section, every other line as it was."""
    lines = text.splitlines()
    out, section, done = [], '', False
    for line in lines:
        m = re.match(r'^\s*\[([^\]]+)\]\s*$', line)
        if m:
            if section == 'wsl2' and not done:
                out.append(f'networkingMode={mode}')
                done = True
            section = m.group(1).strip().lower()
        elif section == 'wsl2' and re.match(r'^\s*networkingMode\s*=', line, re.I):
            if not done:
                out.append(f'networkingMode={mode}')
                done = True
            continue
        out.append(line)
    if not done:
        if section != 'wsl2':
            out += (['', '[wsl2]'] if out else ['[wsl2]'])
        out.append(f'networkingMode={mode}')
    return '\r\n'.join(out) + '\r\n'


def network_of(text):
    """One address or network as Windows lists a rule's (192.168.1.5, 192.168.1.0/24, 192.168.1.0/255.255.255.0) and as
    --allow_from gives it: the network in one spelling (192.168.1.5/32); '' when it is neither."""
    text = str(text).strip()
    if '/' in text:
        ip, mask = text.split('/', 1)
        if '.' in mask:
            try:
                mask = str(ipaddress.IPv4Network(f'0.0.0.0/{mask}').prefixlen)
            except ValueError:
                return ''
        text = f'{ip}/{mask}'
    try:
        return str(ipaddress.ip_network(text, strict = False))
    except ValueError:
        return ''


def mode_of(text):
    """networkingMode of the [wsl2] section ('' when none: WSL's default, nat)."""
    section = ''
    for line in text.splitlines():
        m = re.match(r'^\s*\[([^\]]+)\]\s*$', line)
        if m:
            section = m.group(1).strip().lower()
            continue
        m = re.match(r'^\s*networkingMode\s*=\s*(\S+)', line, re.I)
        if section == 'wsl2' and m:
            return m.group(1).strip().lower()
    return ''


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    @staticmethod
    def _run(args, timeout = 120):
        try:
            p = subprocess.run(args, stdin = subprocess.DEVNULL, capture_output = True, timeout = timeout)
            out = (p.stdout + p.stderr).decode('utf-8', 'replace').replace('\x00', '')
            return p.returncode, out
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e)

    def _powershell(self, script, elevated):
        """A PowerShell script, as an administrator when asked (the UAC prompt; -EncodedCommand: no quoting)."""
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        if not elevated:
            return self._run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded])
        # a declined (or unanswered) prompt starts nothing: Start-Process returns no process - 1223 (ERROR_CANCELLED),
        # never "exit $null", which is 0 (2026-11-22: a cluster went on as if the rule had changed)
        outer = ("$p = Start-Process -FilePath powershell -ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','"
                 + encoded + "' -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ErrorAction SilentlyContinue; "
                 "if (-not $p) { Write-Output 'the administrator prompt (UAC) was declined or not answered'; exit 1223 }; "
                 "exit $p.ExitCode")
        return self._run(['powershell', '-NoProfile', '-NonInteractive', '-Command', outer], timeout = 600)

    def _rule(self):
        """The remote addresses of the cMeta rule, or None when there is none."""
        code, out = self._powershell(f"$r = Get-NetFirewallHyperVRule -Name '{RULE}' -ErrorAction SilentlyContinue; "
                                     "if ($r) { 'RULE ' + (@($r.RemoteAddresses) -join ',') } else { 'NONE' }", False)
        # whole lines only: an error of PowerShell echoes the script's text
        m = re.search(r'^RULE (\S+)\s*$', out, re.M)
        if m:
            return m.group(1)
        return None if re.search(r'^NONE\s*$', out, re.M) else '?'

    ############################################################
    def run(self,
            ctx: dict,
            mode: str = '',            # nat or mirrored (nothing: say what is set and in use)
            allow_from: str = '',      # mirrored: the addresses / networks of other machines let into WSL (comma-separated); none: the rule removed
            restart: bool = False,     # wsl --shutdown, so that the mode applies (every distribution and Docker Desktop's engine stop)
    ):
        con = ctx['control'].get('con', False)
        mode = str(mode or '').strip().lower()
        if mode and mode not in MODES:
            return self.cm.error(f'the mode is nat or mirrored (got "{mode}")')
        path = os.path.join(os.path.expanduser('~'), '.wslconfig')
        try:
            with open(path, encoding = 'utf-8-sig') as f:
                text = f.read()
        except OSError:
            text = ''

        changed = False
        if mode and (mode_of(text) or 'nat') != mode:
            if text and not os.path.exists(path + '.cmeta-before'):
                with open(path + '.cmeta-before', 'w', encoding = 'utf-8', newline = '') as f:
                    f.write(text)
            text = set_mode(text, mode)
            with open(path, 'w', encoding = 'utf-8', newline = '') as f:
                f.write(text)
            changed = True
            if con:
                print(f'cMeta info: {path}: networkingMode={mode}' + ('' if restart else ' - it applies after WSL restarts '
                      '(cx task run set-wsl-network --restart, or wsl --shutdown)'))

        if allow_from:
            if str(allow_from).strip().lower() == 'none':
                script = f"Remove-NetFirewallHyperVRule -Name '{RULE}' -ErrorAction SilentlyContinue; exit 0"
            else:
                remote = []
                for a in str(allow_from).split(','):
                    a = a.strip()
                    try:
                        remote.append(str(ipaddress.ip_network(a, strict = False)))
                    except ValueError:
                        return self.cm.error(f'--allow_from: "{a}" is not an address or a network')
                listed = ','.join(f"'{x}'" for x in remote)
                script = (f"Remove-NetFirewallHyperVRule -Name '{RULE}' -ErrorAction SilentlyContinue; "
                          f"New-NetFirewallHyperVRule -Name '{RULE}' -DisplayName 'cMeta: WSL reachable from {', '.join(remote)}' "
                          f"-Direction Inbound -VMCreatorId '{WSL_VM_CREATOR}' -RemoteAddresses @({listed}) -Action Allow "
                          f"-Profiles Any | Out-Null; exit 0")
            if con:
                print('cMeta info: the Hyper-V firewall of WSL is changed by an administrator: accept the prompt (UAC)')
            code, out = self._powershell(script, True)
            if code == 1223:
                return self.cm.error(f'the firewall rule {RULE} is unchanged: the administrator\'s prompt (UAC) was declined or '
                                     f'not answered (exit 1223) - run it again and accept the prompt')
            if code != 0:
                return self.cm.error(f'changing the firewall rule {RULE} failed (exit {code}): {out.strip()[-500:]}')
            # what the rule lets in now, read back: the change is done only when it is there
            now = self._rule()
            if str(allow_from).strip().lower() == 'none':
                if now not in (None, '?'):
                    return self.cm.error(f'the firewall rule {RULE} is still there (it lets in {now})')
            elif now != '?':
                got = {network_of(a) for a in (now or '').split(',') if a.strip()}
                missing = [a for a in remote if a not in got]
                if missing:
                    return self.cm.error(f'the firewall rule {RULE} does not let in {", ".join(missing)} (it lets in {now or "nothing"})')

        if restart:
            if con:
                print('cMeta info: wsl --shutdown (every distribution and Docker Desktop\'s engine stop; Docker Desktop starts '
                      'its engine again)')
            self._run(['wsl.exe', '--shutdown'], timeout = 300)

        set_now = mode_of(text) or 'nat'
        code, out = self._run(['wsl.exe', '-e', 'wslinfo', '--networking-mode'], timeout = 180)
        in_use = out.strip().splitlines()[-1].strip().lower() if code == 0 and out.strip() else '?'
        rule = self._rule()
        result = {'return': 0, 'config': path, 'mode_set': set_now, 'mode_in_use': in_use, 'allow_from': rule or '',
                  'changed': changed}
        if con:
            print('')
            print(f'WSL networking: set {set_now} ({path}), in use {in_use}'
                  + ('' if in_use in ('?', set_now) else ' - WSL restarts to apply it: --restart'))
            print(f'  Hyper-V firewall rule {RULE}: ' + ('not readable without an administrator' if rule == '?' else
                                                         f'lets in {rule}' if rule else 'none (other machines reach nothing in WSL)'))
            if set_now == 'mirrored':
                print('  Docker Desktop\'s engine keeps its own network: a node with this machine\'s addresses is a WSL instance')
        return result
