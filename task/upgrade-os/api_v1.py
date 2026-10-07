"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

upgrade-os: bring the operating system's packages (and, when asked, its firmware) up to date with the
commands the OS itself uses, chosen from what the host task detected - the package manager of a Linux
distribution (apt-get, dnf, yum, zypper, pacman, apk, ...), softwareupdate and Homebrew on macOS, winget
(and Windows Update when asked) on Windows - and say whether the OS wants a reboot. plan() is pure and
decides the commands; run() executes them.
"""

import os
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask

# The system package managers: how to refresh the index, upgrade everything, drop what nothing needs any
# more, list what would be upgraded (--check), and how the OS says a reboot is due. Missing keys = no
# such step. {kind} of apt is "upgrade" or "dist-upgrade" (--full); the Dpkg options keep a changed
# configuration file instead of asking about it.
APT = {'update': '{pm} update',
       'upgrade': 'env DEBIAN_FRONTEND=noninteractive {pm} -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold {kind}',
       'full': 'dist-upgrade', 'normal': 'upgrade',
       'autoremove': 'env DEBIAN_FRONTEND=noninteractive {pm} -y autoremove',
       'check': 'apt list --upgradable',
       'reboot_file': '/var/run/reboot-required'}
SYSTEM = {
    'apt-get': APT,
    'apt': APT,
    'dnf': {'upgrade': 'dnf -y upgrade --refresh', 'autoremove': 'dnf -y autoremove', 'check': 'dnf check-update',
            'reboot_cmd': 'needs-restarting -r', 'reboot_codes': (1,)},
    'microdnf': {'upgrade': 'microdnf -y upgrade'},
    'tdnf': {'upgrade': 'tdnf -y upgrade', 'check': 'tdnf check-update'},
    'yum': {'upgrade': 'yum -y update', 'autoremove': 'yum -y autoremove', 'check': 'yum check-update',
            'reboot_cmd': 'needs-restarting -r', 'reboot_codes': (1,)},
    'zypper': {'update': 'zypper --non-interactive refresh', 'upgrade': 'zypper --non-interactive update',
               'check': 'zypper list-updates', 'reboot_cmd': 'zypper needs-rebooting', 'reboot_codes': (102,)},
    'pacman': {'upgrade': 'pacman -Syu --noconfirm', 'check': 'pacman -Qu'},
    'apk': {'update': 'apk update', 'upgrade': 'apk upgrade', 'check': 'apk list --upgradable'},
    'xbps-install': {'upgrade': 'xbps-install -Syu -y', 'check': 'xbps-install -Sun'},
}
# macOS: the system (softwareupdate, root) and the user's Homebrew; Windows: the user's apps (winget) and,
# only when asked, Windows Update through the PSWindowsUpdate module (an elevated PowerShell)
MACOS_SYSTEM = {'upgrade': 'softwareupdate -ia', 'check': 'softwareupdate -l', 'sudo': True, 'reboot_text': 'restart'}
BREW = {'update': 'brew update', 'upgrade': 'brew upgrade', 'check': 'brew outdated', 'sudo': False}
WINGET = {'upgrade': 'winget upgrade --all --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity',
          'check': 'winget upgrade --source winget --accept-source-agreements', 'sudo': False}
WINDOWS_UPDATE = {'upgrade': 'powershell -NoProfile -ExecutionPolicy Bypass -Command "if (-not (Get-Module -ListAvailable PSWindowsUpdate)) { Install-Module PSWindowsUpdate -Force -Scope CurrentUser }; Import-Module PSWindowsUpdate; Get-WindowsUpdate -AcceptAll -Install -IgnoreReboot"',
                  'check': 'powershell -NoProfile -ExecutionPolicy Bypass -Command "if (-not (Get-Module -ListAvailable PSWindowsUpdate)) { Install-Module PSWindowsUpdate -Force -Scope CurrentUser }; Import-Module PSWindowsUpdate; Get-WindowsUpdate"',
                  'sudo': False, 'reboot_cmd': 'powershell -NoProfile -Command "if (Test-Path \'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired\') { exit 1 } else { exit 0 }"', 'reboot_codes': (1,)}
# Firmware: fwupd on Linux (the LVFS: laptops, docks, NVMe, ...); macOS firmware comes with softwareupdate;
# Windows firmware comes through Windows Update (the OEM's channel)
FWUPD = {'update': 'fwupdmgr refresh --force', 'check': 'fwupdmgr get-updates', 'upgrade': 'fwupdmgr update -y', 'sudo': True}

REBOOT = {'linux': 'shutdown -r now', 'darwin': 'shutdown -r now', 'windows': 'shutdown /r /t 5'}


def truthy(value):
    return value is True or str(value).strip().lower() in ('true', 'yes', '1', 'on')


def plan(uname, os_extra, system = True, apps = True, firmware = False, windows_update = False, check = False,
         full = False, autoremove = False, root = False, interactive = False):
    """
    The steps for this OS, in order: (name, command, needs_sudo, kind) - kind is "system", "apps",
    "firmware" or "reboot?" (a probe whose exit code says a reboot is due; its reboot_codes come along
    as the fifth element). Nothing runs here. --check lists what would be upgraded instead of upgrading.
    """
    steps = []
    extra = os_extra or {}

    def add(name, cmd, sudo, kind, codes = None):
        if cmd:
            steps.append((name, cmd, bool(sudo) and not root, kind, codes))

    if uname == 'linux':
        pm = extra.get('package_manager') or ''
        table = SYSTEM.get(pm)
        if system and table:
            kind_word = table.get('full') if full else table.get('normal')
            fmt = lambda c: c.format(pm = pm, kind = kind_word or '')
            if check:
                if table.get('update') and pm in ('apt-get', 'apt'):
                    add('update', fmt(table['update']), True, 'system')      # apt lists only what its index knows
                add('check', fmt(table['check']) if table.get('check') else None, False, 'system')
            else:
                add('update', fmt(table['update']) if table.get('update') else None, True, 'system')
                add('upgrade', fmt(table['upgrade']), True, 'system')
                if autoremove:
                    add('autoremove', fmt(table['autoremove']) if table.get('autoremove') else None, True, 'system')
                if table.get('reboot_file'):
                    add('reboot?', f'test -f {table["reboot_file"]}', False, 'reboot?', (0,))
                elif table.get('reboot_cmd'):
                    add('reboot?', table['reboot_cmd'], False, 'reboot?', table.get('reboot_codes', (1,)))
        elif system and not table:
            add('system', None, False, 'system')
        if apps and extra.get('brew_present'):
            add('brew check' if check else 'brew upgrade', BREW['check'] if check else BREW['update'] + ' && ' + BREW['upgrade'], False, 'apps')
        if firmware:
            add('firmware refresh', FWUPD['update'], True, 'firmware')
            add('firmware check' if check else 'firmware update', FWUPD['check'] if check else FWUPD['upgrade'], True, 'firmware')
    elif uname == 'darwin':
        if system:
            add('system check' if check else 'system upgrade', MACOS_SYSTEM['check'] if check else MACOS_SYSTEM['upgrade'],
                not check, 'system')
        if apps:
            add('brew check' if check else 'brew upgrade', BREW['check'] if check else BREW['update'] + ' && ' + BREW['upgrade'], False, 'apps')
        # firmware: part of softwareupdate on a Mac
    elif uname == 'windows':
        if apps:
            add('apps check' if check else 'apps upgrade', WINGET['check'] if check else WINGET['upgrade'], False, 'apps')
        if system and windows_update:
            add('windows update check' if check else 'windows update', WINDOWS_UPDATE['check'] if check else WINDOWS_UPDATE['upgrade'],
                False, 'system')
            if not check:
                add('reboot?', WINDOWS_UPDATE['reboot_cmd'], False, 'reboot?', WINDOWS_UPDATE['reboot_codes'])
        # firmware: through Windows Update, the OEM's channel
    return steps


def with_sudo(cmd, needs_sudo, interactive):
    """sudo in front of a system command: "-n" (never a hidden prompt) unless the run is interactive."""
    if not needs_sudo:
        return cmd
    return ('sudo ' if interactive else 'sudo -n ') + cmd


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            system: bool = True,            # the OS packages (apt, dnf, ..., softwareupdate; Windows Update only with --windows_update)
            apps: bool = True,              # the user's package manager: Homebrew, winget
            firmware: bool = False,         # the firmware too (fwupd on Linux; macOS and Windows have it in their system updates)
            windows_update: bool = False,   # Windows: also Windows Update (needs an elevated shell and the PSWindowsUpdate module)
            check: bool = False,            # only list what would be upgraded, upgrade nothing
            full: bool = False,             # apt: dist-upgrade instead of upgrade (new dependencies, kernel packages)
            autoremove: bool = False,       # drop the packages nothing needs any more (apt, dnf, yum)
            reboot: bool = False,           # reboot at the end when the OS says it is due (shutdown -r now)
            dry_run: bool = False,          # print the commands, run nothing
            ignore_errors: bool = False,    # go on after a failed step (the result still says which failed)
            timeout: int = None,            # seconds per command
            env: dict = None,
            **misc,
    ):
        """
        Upgrade the OS (and its firmware when asked) with its own commands, from what the host task
        detected; the OS packages need root: sudo without a prompt (sudo -n) unless the run is
        interactive (a terminal, not -q), where sudo may ask once.

            cx task run upgrade-os                         # the OS packages, and brew / winget apps
            cx task run upgrade-os --check                 # what would be upgraded (no root needed where the OS allows)
            cx task run upgrade-os --firmware --autoremove --reboot
            cx task run upgrade-os --dry_run

        Returns: os, package_manager, steps [{name, cmd, returncode}], reboot_required, and return 1
        when a step failed (unless --ignore_errors).
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        host = ctx['tasks']['global']['host']
        uname = host['os']['uname']
        extra = dict(host.get('os_extra') or {})
        if uname != 'windows':
            import shutil
            extra['brew_present'] = shutil.which('brew') is not None
        root = uname != 'windows' and hasattr(os, 'geteuid') and os.geteuid() == 0
        interactive = (not quiet) and sys.stdin.isatty()
        # the engine hands CLI booleans over as strings
        system, apps, firmware = truthy(system), truthy(apps), truthy(firmware)
        windows_update, check, full = truthy(windows_update), truthy(check), truthy(full)
        autoremove, reboot, dry_run, ignore_errors = truthy(autoremove), truthy(reboot), truthy(dry_run), truthy(ignore_errors)

        steps = plan(uname, extra, system = system, apps = apps, firmware = firmware, windows_update = windows_update,
                     check = check, full = full, autoremove = autoremove, root = root, interactive = interactive)
        label = f"{extra.get('id') or uname}" + (f" ({extra.get('package_manager')})" if extra.get('package_manager') else '')
        result = {'return': 0, 'os': extra.get('id') or uname, 'uname': uname, 'package_manager': extra.get('package_manager'),
                  'steps': [], 'reboot_required': None, 'check': check, 'dry_run': dry_run}

        if not steps:
            if con:
                print(f'upgrade-os: nothing to do on {label} - no package manager this task knows' +
                      (' (Windows Update: --windows_update)' if uname == 'windows' and system else ''))
            return result

        if con and (dry_run or verbose):
            print(f'upgrade-os on {label}:')
            for name, cmd, needs_sudo, kind, codes in steps:
                print(f'  {name:18} {with_sudo(cmd, needs_sudo, interactive)}')
            if dry_run:
                result['steps'] = [{'name': n, 'cmd': with_sudo(c, s, interactive), 'returncode': None} for n, c, s, k, codes in steps]
                return result

        failed = []
        for name, cmd, needs_sudo, kind, codes in steps:
            line = with_sudo(cmd, needs_sudo, interactive)
            if con:
                print('')
                print(f'=== upgrade-os: {name}: {line}')
                sys.stdout.flush()              # keep the header ahead of the command's own output in a pipe
            rr = self.cm.utils.sys.run(line, capture_output = (kind == 'reboot?') or not con, con = con and kind != 'reboot?',
                                       verbose = verbose, print_cmd = False, fail_on_error = False, timeout = timeout,
                                       env = env, logger = self.logger)
            rc = rr.get('returncode', 0)
            result['steps'].append({'name': name, 'cmd': line, 'returncode': rc})
            if kind == 'reboot?':
                result['reboot_required'] = rc in (codes or (1,))
                continue
            if rc != 0:
                if name == 'check' and extra.get('package_manager') in ('dnf', 'yum', 'tdnf') and rc == 100:
                    result['steps'][-1]['note'] = 'updates available'      # dnf/yum check-update: 100 = updates are available
                    continue
                if kind == 'firmware' and rc == 2:
                    result['steps'][-1]['note'] = 'nothing to do'          # fwupdmgr: 2 = no updates available
                    continue
                if check and name == 'update':
                    if con:                     # --check without root: list from the index as it is
                        print(f'upgrade-os: the index refresh failed (exit code {rc}: no passwordless sudo?) - listing from the current index')
                    continue
                failed.append(name)
                if con:
                    err = (rr.get('stderr') or '').strip().splitlines()
                    print(f'upgrade-os: {name} failed (exit code {rc})' + (f': {err[-1]}' if err else '') +
                          (' - sudo needs a password here: run it in a terminal, or add a NOPASSWD rule' if needs_sudo and rc == 1 and not interactive else ''))
                if not ignore_errors:
                    break

        if con:
            done = [s['name'] for s in result['steps'] if s['name'] != 'reboot?' and (s['returncode'] == 0 or s.get('note'))]
            text = f'upgrade-os: {label}: ' + (', '.join(done) + ' ok' if done else 'nothing ran')
            if failed:
                text += f'; FAILED: {", ".join(failed)}'
            if result['reboot_required'] is True:
                text += '; a reboot is required'
            elif result['reboot_required'] is False:
                text += '; no reboot required'
            print('')
            print(text)

        if failed and not ignore_errors:
            result['return'] = 1
            result['error'] = f'upgrade-os: {", ".join(failed)} failed on {label}'
            return result

        if reboot and result['reboot_required'] and not check:
            line = with_sudo(REBOOT[uname], uname != 'windows', interactive)
            if con:
                print(f'upgrade-os: rebooting ({line})')
            self.cm.utils.sys.run(line, capture_output = True, con = False, fail_on_error = False, logger = self.logger)
            result['rebooting'] = True
        return result
