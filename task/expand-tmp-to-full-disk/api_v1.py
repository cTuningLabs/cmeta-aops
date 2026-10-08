"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import shutil
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask

TMP = '/tmp'
UNIT = 'tmp.mount'


def truthy(value):
    """The engine hands CLI booleans over as strings."""
    return value is True or str(value).strip().lower() in ('true', '1', 'yes', 'on')


def tmp_mount(mounts_text, target = TMP):
    """
    The mount of /tmp from /proc/mounts: {source, fstype, options} of the last entry mounted on it, or
    None when /tmp is not a mount point (a folder of the root filesystem).
    """
    found = None
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == target:
            found = {'source': parts[0], 'fstype': parts[2], 'options': parts[3].split(',')}
    return found


def fstab_tmpfs_lines(fstab_text, target = TMP):
    """The line numbers (from 1) of the /etc/fstab entries that mount a tmpfs on /tmp."""
    lines = []
    for number, line in enumerate(fstab_text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        parts = s.split()
        if len(parts) >= 3 and parts[1] == target and parts[2] == 'tmpfs':
            lines.append(number)
    return lines


def plan(mount, unit_active, fstab_lines):
    """
    The steps that move /tmp to the disk, in order: (name, command, needs_sudo, kind) - kind is "lasting"
    (holds from the next boot on) or "now" (this session). Nothing when /tmp is not a tmpfs.
    """
    steps = []
    if not mount or mount['fstype'] != 'tmpfs':
        return steps
    if unit_active:
        steps.append(('mask', f'systemctl mask {UNIT}', True, 'lasting'))
    for number in fstab_lines:
        steps.append(('fstab', f"sed -i.cmeta-backup '{number}s/^/#/' /etc/fstab", True, 'lasting'))
    steps.append(('unmount', f'systemctl stop {UNIT}' if unit_active else f'umount {TMP}', True, 'now'))
    return steps


def with_sudo(cmd, needs_sudo, interactive):
    """sudo in front of a system command: "-n" (never a hidden prompt) unless the run is interactive."""
    if not needs_sudo:
        return cmd
    return ('sudo ' if interactive else 'sudo -n ') + cmd


def gib(n):
    return f'{n / 2**30:.1f} GiB'


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,                  # cMeta context
            check: bool = False,        # Only report what /tmp is and what would change
            dry_run: bool = False,      # Print the commands, run nothing
            timeout: int = None,
            env: dict = None,
    ):

        """
        Move /tmp from a RAM-backed tmpfs (with its size limit and per-user quota) to the disk of the
        root filesystem, lasting and at once.

            cx task run expand-tmp-to-full-disk
            cx task run expand-tmp-to-full-disk --check
            cx task run expand-tmp-to-full-disk --dry_run

        Returns: before and after {fstype, source, options, total, free} of /tmp, steps [{name, cmd, kind,
        returncode}], changed, ready (/tmp is on a disk now), reboot (True when only a reboot finishes it),
        and return 1 when a step failed or on Windows.
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        check, dry_run = truthy(check), truthy(dry_run)

        uname = ctx['tasks']['global']['host']['os']['uname']
        result = {'return': 0, 'os': uname, 'before': {}, 'after': {}, 'steps': [], 'changed': False, 'ready': False, 'reboot': False}

        if uname == 'windows':
            return self.cm.error('expand-tmp-to-full-disk is for Linux: on Windows the temporary folder (TEMP) is a folder on a disk already')

        def look():
            usage = shutil.disk_usage(TMP)
            d = {'total': usage.total, 'free': usage.free}
            if uname == 'linux':
                try:
                    with open('/proc/mounts') as f:
                        m = tmp_mount(f.read())
                except OSError:
                    m = None
                d.update(m or {'source': 'the root filesystem', 'fstype': 'disk', 'options': []})
            else:
                d.update({'source': os.path.realpath(TMP), 'fstype': 'disk', 'options': []})
            return d

        before = look()
        result['before'] = before
        on_tmpfs = before['fstype'] == 'tmpfs'

        if con:
            where = f"{before['fstype']} ({before['source']})"
            extra = ', per-user quota' if 'usrquota' in before['options'] else ''
            print(f'expand-tmp-to-full-disk: {TMP} is on {where}{extra}: {gib(before["free"])} free of {gib(before["total"])}')

        if uname == 'darwin' or not on_tmpfs:
            result['after'] = before
            result['ready'] = True
            if con:
                print(f'expand-tmp-to-full-disk: {TMP} is on a disk, nothing to do')
            return result

        root = hasattr(os, 'geteuid') and os.geteuid() == 0
        interactive = (not quiet) and sys.stdin.isatty()

        r = self.cm.utils.sys.run(f'systemctl is-active {UNIT}', capture_output = True, fail_on_error = False, logger = self.logger)
        unit_active = r.get('returncode', 1) == 0 and (r.get('stdout') or '').strip() == 'active'
        try:
            with open('/etc/fstab') as f:
                fstab_lines = fstab_tmpfs_lines(f.read())
        except OSError:
            fstab_lines = []

        steps = plan(before, unit_active, fstab_lines)
        for name, cmd, needs_sudo, kind in steps:
            result['steps'].append({'name': name, 'cmd': with_sudo(cmd, needs_sudo and not root, interactive), 'kind': kind, 'returncode': None})

        if check or dry_run:
            result['after'] = before
            if con:
                print('expand-tmp-to-full-disk: would run' + (' (nothing was changed):' if check else ':'))
                for s in result['steps']:
                    print(f'  {s["name"]:10} {s["cmd"]}   # {s["kind"]}')
            return result

        failed = []
        for s in result['steps']:
            if con:
                print(f'=== expand-tmp-to-full-disk: {s["name"]}: {s["cmd"]}')
                sys.stdout.flush()
            rr = self.cm.utils.sys.run(s['cmd'], capture_output = True, con = con, verbose = verbose, print_cmd = False,
                                       fail_on_error = False, timeout = timeout, env = env, logger = self.logger)
            s['returncode'] = rr.get('returncode', 0)
            if s['returncode'] == 0:
                result['changed'] = True
                continue
            if s['name'] == 'unmount':
                # A process holds a file in the tmpfs: detach it lazily - new opens of /tmp go to the disk,
                # the process keeps its file until it closes it
                lazy = with_sudo(f'umount -l {TMP}', not root, interactive)
                if con:
                    print(f'=== expand-tmp-to-full-disk: unmount-lazy: {lazy}')
                rr = self.cm.utils.sys.run(lazy, capture_output = True, con = con, verbose = verbose, print_cmd = False,
                                           fail_on_error = False, timeout = timeout, env = env, logger = self.logger)
                s['note'] = 'busy, detached lazily'
                s['returncode'] = rr.get('returncode', 0)
                if s['returncode'] == 0:
                    result['changed'] = True
                    continue
            failed.append(s['name'])
            if con:
                err = (rr.get('stderr') or '').strip().splitlines()
                print(f'expand-tmp-to-full-disk: {s["name"]} failed (exit code {s["returncode"]})' + (f': {err[-1]}' if err else ''))

        if not failed:
            # The folder beneath the tmpfs is /tmp now: world-writable with the sticky bit, as a /tmp must be
            mode = os.stat(TMP).st_mode & 0o7777
            if mode != 0o1777:
                rr = self.cm.utils.sys.run(with_sudo(f'chmod 1777 {TMP}', not root, interactive), capture_output = True,
                                           fail_on_error = False, logger = self.logger)
                result['steps'].append({'name': 'mode', 'cmd': f'chmod 1777 {TMP}', 'kind': 'now', 'returncode': rr.get('returncode', 0)})

        after = look()
        result['after'] = after
        result['ready'] = after['fstype'] != 'tmpfs'
        result['reboot'] = (not result['ready']) and any(s['name'] in ('mask', 'fstab') and s['returncode'] == 0 for s in result['steps'])

        if failed:
            lines = '\n'.join('  ' + s['cmd'].replace('sudo -n ', 'sudo ') for s in result['steps'] if s['returncode'] not in (0, None))
            hint = 'sudo needs a password here: run these in a terminal, then run again' if not interactive else 'these commands failed'
            return self.cm.error(f'expand-tmp-to-full-disk could not finish ({", ".join(failed)}): {hint}:\n{lines}')
        if con:
            if result['ready']:
                print(f'expand-tmp-to-full-disk: {TMP} is on {after["fstype"]} ({after["source"]}) now: {gib(after["free"])} free of {gib(after["total"])}')
            elif result['reboot']:
                print(f'expand-tmp-to-full-disk: set up for the next boot; {TMP} stays a tmpfs until then')
        return result
