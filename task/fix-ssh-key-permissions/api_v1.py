"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

fix-ssh-key-permissions: the permissions OpenSSH wants on a private key - readable by its owner alone - made or
checked on any OS. Linux and macOS: no group or other bits on a key (600), nothing writable by others in ~/.ssh
(what ssh refuses; 700 and 600 are conventions ssh does not demand of the folder and config). Windows: an ACL of the user alone,
with read access for SYSTEM and Administrators, written with icacls and checked with Get-Acl, both by SIDs
(S-1-5-18, S-1-5-32-544 and the user's own), so that a localized Windows ("Administrateurs") or a domain account
is handled the same. A private key is told by its header ("-----BEGIN ... PRIVATE KEY-----"), never by its name;
nothing of a key is printed.

    cx task run fix-ssh-key-permissions <file or folder> [--recursive] [--check]
    cx task run fix-ssh-key-permissions --ssh_dir [--check]

Why a task: the author's fix-permissions.bat did this by hand on Windows (2025); every place cMeta writes or
mounts a key (cx secret import, setup-cmeta-host, the containers of the "run on any host" design) needs the
same, on every OS, with a check that says who else can read the key.
"""

import csv
import os
import stat
import subprocess
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask

# Files a folder scan never opens (the key files are found by their header among the rest)
SKIP_EXT = {'.bat', '.cmd', '.ps1', '.sh', '.py', '.md', '.txt', '.log', '.json', '.yaml', '.yml', '.csv', '.html',
            '.pub', '.ppk', '.reg', '.zip', '.7z', '.gz', '.tar', '.xz', '.pf'}
MAX_KEY_SIZE = 65536

# The files of ~/.ssh that ssh wants private besides the keys (known_hosts and the .pub files stay readable)
SSH_DIR_FILES = {'config', 'authorized_keys', 'environment', 'rc'}

SYSTEM_SID = 'S-1-5-18'
ADMINS_SID = 'S-1-5-32-544'

# Get-Acl of one path, one line per access rule: "<SID> <rights> <Allow|Deny>" (a name is translated to its SID;
# an orphaned SID stays as it is)
PS_ACL = ("(Get-Acl -LiteralPath '{path}').Access | ForEach-Object {{ $id = $_.IdentityReference; "
          "if ($id -isnot [System.Security.Principal.SecurityIdentifier]) {{ try {{ $id = $id.Translate([System.Security.Principal.SecurityIdentifier]) }} catch {{ }} }}; "
          "'{{0}} {{1}} {{2}}' -f $id.Value, $_.FileSystemRights, $_.AccessControlType }}")


def _run(args):
    """A short local command: (return code, stdout as text); bytes decoded, never text=True."""
    try:
        r = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return r.returncode, r.stdout.decode('utf-8', errors='replace')


def is_private_key(path):
    """True for a file whose first line is a private key header; scripts, notes, public keys never (by extension)."""
    if os.path.splitext(path)[1].lower() in SKIP_EXT:
        return False
    try:
        if os.path.getsize(path) > MAX_KEY_SIZE:
            return False
        with open(path, 'rb') as f:
            head = f.read(64)
    except OSError:
        return False
    return head.startswith(b'-----BEGIN ') and b'PRIVATE KEY' in head


def user_sid():
    """The SID of the user running this (whoami /user as CSV), '' when it cannot be read."""
    code, out = _run(['whoami', '/user', '/fo', 'csv', '/nh'])
    if code != 0:
        return ''
    for row in csv.reader(out.strip().splitlines()):
        if len(row) >= 2 and row[1].startswith('S-'):
            return row[1].strip()
    return ''


def windows_readers(path, me):
    """The SIDs other than the user, SYSTEM and Administrators that an Allow rule of the path gives access to."""
    script = PS_ACL.format(path=path.replace("'", "''"))
    code, out = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script])
    if code != 0:
        return None, out.strip().splitlines()[-1:]
    others = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].startswith('S-') and parts[-1] == 'Allow':
            sid = parts[0]
            if sid not in (me, SYSTEM_SID, ADMINS_SID) and sid not in others:
                others.append(sid)
    return others, []


def _icacls(path, args):
    """icacls on one path: [] when done, else [what it said] - the reason ("Access is denied") with the summary."""
    code, out = _run(['icacls', path] + args)
    if code == 0:
        return []
    lines = [line.strip() for line in out.strip().splitlines() if line.strip()]
    return ['; '.join(lines[-2:]) if lines else f'icacls exit {code}']


def windows_tighten(path, me, folder):
    """The ACL of the user alone (full), SYSTEM and Administrators read; a folder passes it on to what is made inside."""
    inherit = '(OI)(CI)' if folder else ''
    for args in (['/inheritance:r'],
                 ['/grant:r', f'*{me}:{inherit}F'],
                 ['/grant:r', f'*{SYSTEM_SID}:{inherit}R'],
                 ['/grant:r', f'*{ADMINS_SID}:{inherit}R']):
        error = _icacls(path, args)
        if error:
            return error

    # The rules of others set on the path itself (not inherited) stay through /inheritance:r: removed one by one
    # (a key made on GitHub's Windows runner had a rule of its own for OWNER RIGHTS, S-1-3-4 - 2026-10-17)
    others, error = windows_readers(path, me)
    if others is None:
        return error
    for sid in others:
        error = _icacls(path, ['/remove:g', f'*{sid}'])
        if error:
            return error
    return []


# What ssh refuses: a private key that others can read or write, a ~/.ssh folder or file that others can write
# (700 and 600 are the conventions; 755 on the folder and 644 on config are accepted by ssh and left alone)
KEY_FORBIDDEN = 0o077
SSH_FORBIDDEN = 0o022


def posix_problem(path, forbidden):
    """What is wrong with the mode and owner of a path for ssh, '' when nothing: forbidden bits set, another owner."""
    st = os.stat(path)
    mode = stat.S_IMODE(st.st_mode)
    problems = []
    if mode & forbidden:
        problems.append(f'mode {mode:o} ({"readable" if forbidden == KEY_FORBIDDEN else "writable"} by others)')
    if hasattr(os, 'getuid') and st.st_uid not in (os.getuid(), 0):
        problems.append(f'owned by uid {st.st_uid}, not you')
    return ', '.join(problems)


class CTask(InitCTask):
    """
    The permissions OpenSSH wants on private keys, made or checked.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            target: str = None,         # a private key, or a folder whose private keys are found by their header
                                        # ("path" is a control word of every task - the working directory - so not here)
            check: bool = False,        # report only, change nothing
            recursive: bool = False,    # a folder: its sub-folders too
            ssh_dir: bool = False,      # ~/.ssh: the folder (700), its keys, config and authorized_keys (600)
    ):
        con = ctx['control'].get('con', False)
        windows = os.name == 'nt'

        # ---- what to look at: (path, kind, the POSIX bits that must not be set)
        targets = []
        if ssh_dir:
            d = os.path.join(os.path.expanduser('~'), '.ssh')
            if not os.path.isdir(d):
                return self.cm.error(f'no ~/.ssh folder here ({d})')
            targets.append((d, 'ssh folder', SSH_FORBIDDEN))
            for name in sorted(os.listdir(d)):
                p = os.path.join(d, name)
                if os.path.isfile(p) and is_private_key(p):
                    targets.append((p, 'private key', KEY_FORBIDDEN))
                elif os.path.isfile(p) and name in SSH_DIR_FILES:
                    targets.append((p, 'ssh file', SSH_FORBIDDEN))

        if target:
            p = os.path.abspath(os.path.expanduser(str(target)))
            if os.path.isfile(p):
                targets.append((p, 'private key' if is_private_key(p) else 'file', KEY_FORBIDDEN))
            elif os.path.isdir(p):
                if recursive:
                    for root, dirs, files in os.walk(p):
                        dirs[:] = sorted(x for x in dirs if x not in ('.git', '__pycache__'))
                        for name in sorted(files):
                            f = os.path.join(root, name)
                            if is_private_key(f):
                                targets.append((f, 'private key', KEY_FORBIDDEN))
                else:
                    for name in sorted(os.listdir(p)):
                        f = os.path.join(p, name)
                        if os.path.isfile(f) and is_private_key(f):
                            targets.append((f, 'private key', KEY_FORBIDDEN))
            else:
                return self.cm.error(f'not found: {p}')

        if not targets:
            if target:
                return {'return': 0, 'files': [], 'open': 0, 'fixed': 0, 'note': f'no private key found in {target}'}
            return self.cm.error('give a private key or a folder to look in, or --ssh_dir')

        me = user_sid() if windows else ''
        if windows and not me:
            return self.cm.error('cannot read the SID of the current user (whoami /user)')

        # ---- look, then fix unless --check
        rows = []
        n_open = n_fixed = 0
        for p, kind, forbidden in targets:
            if windows:
                # Windows OpenSSH looks at the private keys alone: the folder and config are not its concern
                if kind in ('ssh folder', 'ssh file'):
                    problem = ''
                else:
                    others, errors = windows_readers(p, me)
                    if others is None:
                        return self.cm.error(f'cannot read the ACL of {p}: {" ".join(errors)}')
                    problem = ('readable by ' + ', '.join(others)) if others else ''
            else:
                problem = posix_problem(p, forbidden)

            # problem: what was wrong when looked at; left: what is still wrong after the fix, looked at again - before
            # 2026-10-17 a fixed key kept its old problem in the row, and cx secret generate took it for a failure
            status = 'ok'
            left = problem
            if problem:
                n_open += 1
                status = 'too open'
                if not check:
                    if windows:
                        errors = windows_tighten(p, me, folder=False)
                        if errors:
                            return self.cm.error(f'cannot tighten {p}: {" ".join(errors)}')
                        others, errors = windows_readers(p, me)
                        left = ('readable by ' + ', '.join(others)) if others else ' '.join(errors or [])
                    else:
                        os.chmod(p, stat.S_IMODE(os.stat(p).st_mode) & ~forbidden)
                        left = posix_problem(p, forbidden)
                    if left:
                        status = 'still open'
                    else:
                        status = 'fixed'
                        n_fixed += 1
            rows.append({'path': p, 'kind': kind, 'status': status, 'problem': problem, 'left': left})

        if con:
            print ('')
            print (f'{"STATUS":<9} {"KIND":<12} PATH  (what was wrong)')
            for row in rows:
                print (f'{row["status"]:<9} {row["kind"]:<12} {row["path"]}' + (f'  ({row["problem"]})' if row['problem'] else ''))
            print ('')
            if check:
                print (f'cMeta info: {len(rows)} looked at, {n_open} too open (run without --check to tighten them)')
            else:
                print (f'cMeta info: {len(rows)} looked at, {n_fixed} tightened')

        return {'return': 0, 'files': rows, 'open': n_open, 'fixed': n_fixed}
