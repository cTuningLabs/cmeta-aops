"""
Authors: Grigori Fursin. Licensed under the Apache License, Version 2.0 (the category is bound for cmeta-aops).

secret - identities and credentials as artifacts (README.md): git identities, ssh keys, tokens, files. The meta
holds references, never values; the files live inside the artifact (self-contained) or in another artifact (cRef).

    cx secret ls [<alias or wildcard>]      # alias, kind, repository, hosts, used by
    cx secret show <alias>                  # the references of one identity (never a value)
    cx secret check [<alias>]               # the files exist, their mode, the passphrase as declared, the variables set
    cx secret import [<alias>] [--force]    # the files copied in from files.from, the private key made owner-only
    cx secret generate <alias>              # a new ed25519 key pair without a passphrase (automation, containers, hosts)
    cx secret use <alias> --repo=<clone>    # the git identity written into a clone's .git/config (or --git_global)
    cx secret render <alias> --out=<file>   # the same as a git config include file, with the ssh config stanza
"""

import datetime
import os
import re
import shutil
import stat
import subprocess

from cmeta.category import InitCategory

CATEGORY = 'secret,9d63451ea1f14010'
DESC_FILE = '_desc.yaml'

# The keys of _desc.yaml that name a file (dotted), with what the file is
FILE_KEYS = {'ssh.key': 'private key', 'ssh.public_key': 'public key', 'signing.key': 'signing key',
             'signing.allowed_signers': 'allowed signers', 'token.file': 'token file'}


def _get(d, dotted):
    for k in dotted.split('.'):
        d = d.get(k) if isinstance(d, dict) else None
    return d


class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _select(self, ctx, arg1=None):
        """The secret artifacts (all, or the ones matching arg1), each with its desc."""
        r = self.cm.access({'category': CATEGORY, 'command': 'find', 'arg1': arg1 or '*', 'con': False})
        if r['return'] > 0:
            return r

        found = []
        for a in sorted(r.get('artifacts', []), key = lambda a: a['cmeta_ref_parts']['artifact_alias']):
            rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a['path'], '_desc'))
            desc = rd.get('data') or {} if rd['return'] == 0 else {}
            found.append({'alias': a['cmeta_ref_parts']['artifact_alias'], 'path': a['path'],
                          'repo': a['cmeta_ref_parts'].get('artifact_repo_alias', ''), 'desc': desc})
        return {'return': 0, 'secrets': found}

    ############################################################
    def _resolve(self, s, ref):
        """A file reference of a secret -> (path or None, how it was given)."""
        ref = str(ref or '')
        if not ref:
            return None, ''
        if ref.startswith('env:'):
            return os.environ.get(ref[4:]) or None, 'env'
        if '::' in ref:
            cat, rest = ref.split('::', 1)
            alias, _, inside = rest.partition('/')
            r = self.cm.access({'category': cat, 'command': 'find', 'arg1': alias, 'con': False})
            if r['return'] > 0 or not r.get('artifacts'):
                return None, 'cref'
            return os.path.join(r['artifacts'][0]['path'], *inside.split('/')), 'cref'
        return os.path.join(s['path'], *ref.replace('\\', '/').split('/')), 'inside'

    ############################################################
    def ls_(self, ctx, arg1: str = None):
        """
        The secret artifacts: alias, kind, repository, hosts, used by - never a value.
        """
        r = self._select(ctx, arg1)
        if r['return'] > 0:
            return r

        con = ctx['control'].get('con', False)
        if con:
            print ('')
            print (f'{"SECRET":<30} {"KIND":<7} {"REPO":<12} {"HOSTS":<28} USED BY')
            for s in r['secrets']:
                d = s['desc']
                hosts = ','.join(_get(d, 'ssh.hosts') or [])
                used = ', '.join(str(x) for x in (d.get('used_by') or [])) or '-'
                print (f'{s["alias"]:<30} {str(d.get("kind", "?")):<7} {s["repo"]:<12} {hosts:<28} {used}')

        return r

    ############################################################
    def show_(self, ctx, arg1: str = None):
        """
        The references of one identity (the files, the variables, the policy) - never a value.
        """
        if not arg1:
            return self.cm.error('cx secret show <alias>')
        r = self._select(ctx, arg1)
        if r['return'] > 0:
            return r
        if not r['secrets']:
            return self.cm.error(f'secret "{arg1}" not found')

        con = ctx['control'].get('con', False)
        for s in r['secrets']:
            d = s['desc']
            if con:
                print ('')
                print (f'{s["alias"]}  (kind {d.get("kind", "?")}, repository {s["repo"]}, {s["path"]})')
                for key, what in FILE_KEYS.items():
                    ref = _get(d, key)
                    if ref:
                        path, how = self._resolve(s, ref)
                        print (f'  {what:<16} {ref}  [{how}: {path or "unresolved"}]')
                if _get(d, 'ssh.passphrase'):
                    print (f'  {"passphrase":<16} {_get(d, "ssh.passphrase")}')
                if d.get('used_by'):
                    print ('  used by:')
                    for x in d['used_by']:
                        print (f'    - {x}')

        return r

    ############################################################
    def _key_permissions(self, ctx, path, check=False):
        """
        The task fix-ssh-key-permissions on one private key: tightened (mode 600, or on Windows the owner-only ACL by
        SIDs), or with check=True only looked at; returns what the task says of it ('' when nothing is wrong).
        """
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'fix-ssh-key-permissions,756226a90d2f48bf',
                            'target': path, 'check': bool(check), 'ctx': ctx, 'con': False})
        if r['return'] > 0:
            return f'permissions not checked: {r.get("error", "")}'
        rows = r.get('files') or []
        return rows[0].get('problem', '') if rows else ''

    def _tighten(self, ctx, path):
        """A private key readable by its owner alone, through the task fix-ssh-key-permissions."""
        return self._key_permissions(ctx, path)

    ############################################################
    def import_(self, ctx, arg1: str = None, force: bool = False):
        """
        Copy the files of a secret into the artifact (files/...) from where files.from says they are - the
        names of files.names, else the files the references name - and tighten the private keys (mode 600;
        on Windows the ACL OpenSSH accepts: the user, SYSTEM and Administrators read). The source is left as it
        is. Then files.status of _desc.yaml says imported, with the date (a text edit: the comments stay).
        Nothing of the contents is printed.

            cx secret import git-work-without-pass
            cx secret import                         # every secret still "not imported"
            cx secret import <alias> --force         # again, over the files already there
        """
        r = self._select(ctx, arg1)
        if r['return'] > 0:
            return r

        con = ctx['control'].get('con', False)
        done = []
        for s in r['secrets']:
            d = s['desc']
            status = str(_get(d, 'files.status') or '')
            if status == 'imported' and not force:
                if con and arg1:
                    print (f'cMeta info: {s["alias"]}: already imported (--force imports again)')
                continue

            source = _get(d, 'files.from')
            if not source or '::' not in str(source):
                return self.cm.error(f'{s["alias"]}: files.from must name where the files are (a cRef such as my-vault::ssh-x/2026)')
            src_dir = self._resolve(s, str(source))[0]
            if not src_dir or not os.path.isdir(src_dir):
                return self.cm.error(f'{s["alias"]}: the source of files.from is not a folder here: {source}')

            names = _get(d, 'files.names') or []
            if not names:
                names = list(dict.fromkeys(os.path.basename(str(_get(d, key))) for key in FILE_KEYS if _get(d, key)))
            private = os.path.basename(str(_get(d, 'ssh.key') or ''))

            dst_dir = os.path.join(s['path'], 'files')
            os.makedirs(dst_dir, exist_ok=True)
            for name in names:
                src = os.path.join(src_dir, name)
                if not os.path.isfile(src):
                    return self.cm.error(f'{s["alias"]}: {name} is not in {source}')
                dst = os.path.join(dst_dir, name)
                shutil.copy2(src, dst)
                if name == private:
                    left = self._tighten(ctx, dst)
                    if left:
                        return self.cm.error(f'{s["alias"]}: {name} copied but its permissions could not be tightened ({left})')

            # The status in _desc.yaml, by a text edit that keeps the comments
            desc_path = os.path.join(s['path'], DESC_FILE)
            with open(desc_path, encoding='utf-8') as f:
                text = f.read()
            stamp = datetime.datetime.now().astimezone().isoformat(timespec='minutes')
            new = re.sub(r'(?m)^(\s*status:\s*)not imported(.*)$', lambda m: f'{m.group(1)}imported{m.group(2)}\n{m.group(1).split("status")[0]}imported: {stamp}', text, count=1)
            if new == text and 'imported:' in text:
                new = re.sub(r'(?m)^(\s*imported:\s*).*$', lambda m: f'{m.group(1)}{stamp}', text, count=1)
            if new != text:
                with open(desc_path, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(new)

            done.append(s['alias'])
            if con:
                print (f'cMeta info: {s["alias"]}: {len(names)} file(s) imported from {source}' + (f', {private} tightened' if private in names else ''))

        return {'return': 0, 'imported': done}

    ############################################################
    def check_(self, ctx, arg1: str = None):
        """
        The files of each secret exist, a private key has the declared passphrase policy (ssh-keygen asks it
        with an empty passphrase: refused = a passphrase is set; the output is never printed), the mode is 600.
        """
        r = self._select(ctx, arg1)
        if r['return'] > 0:
            return r

        con = ctx['control'].get('con', False)
        rows = []
        for s in r['secrets']:
            d = s['desc']
            for key, what in FILE_KEYS.items():
                ref = _get(d, key)
                if not ref:
                    continue
                path, how = self._resolve(s, ref)
                status = 'ok'
                notes = []
                if not path or not os.path.isfile(path):
                    # Not imported yet: the file is looked at where files.from says it is, with a status of its own
                    source = _get(d, 'files.from')
                    spath = self._resolve(s, f'{source}/{os.path.basename(str(ref))}')[0] if source and '::' in str(source) else None
                    if spath and os.path.isfile(spath):
                        path, status = spath, 'source'
                        notes.append(f'not imported: checked at {source}')
                    else:
                        rows.append((s['alias'], what, 'MISSING', f'import from {source}' if source else 'no file, no files.from'))
                        continue

                if key == 'ssh.key':
                    # The owner-only check of the task fix-ssh-key-permissions: the mode on Linux and macOS, the ACL by SIDs on Windows
                    problem = self._key_permissions(ctx, path, check=True)
                    if problem:
                        notes.append(problem)
                if key == 'ssh.key':
                    try:
                        p = subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', path], stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                        has_pass = p.returncode != 0
                    except (OSError, subprocess.SubprocessError):
                        has_pass = None
                    policy = str(_get(d, 'ssh.passphrase') or '')
                    if has_pass is None:
                        notes.append('passphrase: not checked (no ssh-keygen)')
                    elif policy in ('ask', 'agent') and not has_pass:
                        notes.append(f'declared {policy} but the key has NO passphrase')
                    elif policy == 'none' and has_pass:
                        notes.append('declared none but the key HAS a passphrase')
                    else:
                        notes.append('passphrase ' + ('set' if has_pass else 'none') + (f' as declared ({policy})' if policy else ''))
                rows.append((s['alias'], what, status, '; '.join(notes)))

        if con:
            print ('')
            print (f'{"SECRET":<30} {"ITEM":<16} {"STATUS":<8} NOTES')
            for row in rows:
                print (f'{row[0]:<30} {row[1]:<16} {row[2]:<8} {row[3]}')

        return {'return': 0, 'rows': rows}

    ############################################################
    def _one(self, ctx, arg1, kinds, what):
        """Exactly one secret of one of these kinds, or an error that says why."""
        if not arg1:
            return self.cm.error(f'cx secret {what} <alias>')
        r = self._select(ctx, arg1)
        if r['return'] > 0:
            return r
        if len(r['secrets']) != 1:
            return self.cm.error(f'"{arg1}" matches {len(r["secrets"])} secrets: name one (cx secret ls)')
        s = r['secrets'][0]
        kind = str(s['desc'].get('kind') or '')
        if kind not in kinds:
            return self.cm.error(f'{s["alias"]} is a secret of kind "{kind}": {what} works on {" and ".join(kinds)}')
        return {'return': 0, 'secret': s}

    def _git_settings(self, s, quiet):
        """
        The git settings of a git identity, as (key, value) pairs: the name and email, the ssh key that pushes
        (core.sshCommand with IdentitiesOnly), the signing key and its format, signing of commits, the allowed signers.
        A key whose passphrase must be typed (ask) or come from an agent cannot serve a quiet run: refused with the cure.
        """
        d = s['desc']
        name, email = _get(d, 'identity.name'), _get(d, 'identity.email')
        if not name or not email:
            return self.cm.error(f'{s["alias"]}: identity.name and identity.email are needed in its _desc.yaml')
        if quiet and str(_get(d, 'ssh.passphrase') or '') in ('ask', 'agent'):
            return self.cm.error(f'{s["alias"]}: its key has a passphrase ({_get(d, "ssh.passphrase")}), which a quiet run cannot give: '
                                 f'use its without-pass twin')

        pairs = [('user.name', str(name)), ('user.email', str(email))]
        key = _get(d, 'ssh.key')
        if key:
            path = self._resolve(s, key)[0]
            if not path or not os.path.isfile(path):
                return self.cm.error(f'{s["alias"]}: its ssh key is not there ({key}): cx secret import {s["alias"]}')
            pairs.append(('core.sshCommand', f'ssh -i "{path.replace(os.sep, "/")}" -o IdentitiesOnly=yes'))
        skey = _get(d, 'signing.key')
        if skey:
            path = self._resolve(s, skey)[0]
            if not path or not os.path.isfile(path):
                return self.cm.error(f'{s["alias"]}: its signing key is not there ({skey})')
            pairs += [('gpg.format', str(_get(d, 'signing.format') or 'ssh')), ('user.signingkey', path.replace(os.sep, '/'))]
            if _get(d, 'signing.sign_commits'):
                pairs.append(('commit.gpgsign', 'true'))
            allowed = _get(d, 'signing.allowed_signers')
            if allowed:
                apath = self._resolve(s, allowed)[0]
                if apath:
                    pairs.append(('gpg.ssh.allowedSignersFile', apath.replace(os.sep, '/')))
        return {'return': 0, 'pairs': pairs}

    ############################################################
    def generate_(self, ctx, arg1: str = None, comment: str = '', force: bool = False):
        """
        A new ed25519 key pair for an ssh or git secret, at the files its _desc.yaml names (ssh.key and
        ssh.public_key, inside the artifact), without a passphrase - the key of automation, containers and hosts
        (a key with a passphrase is the human's: made by them with ssh-keygen). The private key is made owner-only
        (fix-ssh-key-permissions). Only the public key's path and fingerprint are printed.

            cx secret generate deploy-key-lab --comment=lab-ci
            cx secret generate deploy-key-lab --force     # a new pair over the old one
        """
        r = self._one(ctx, arg1, ('ssh', 'git'), 'generate')
        if r['return'] > 0:
            return r
        s = r['secret']
        d = s['desc']
        con = ctx['control'].get('con', False)

        if str(_get(d, 'ssh.passphrase') or 'none') != 'none':
            return self.cm.error(f'{s["alias"]}: ssh.passphrase is {_get(d, "ssh.passphrase")} - a key with a passphrase is made by '
                                 f'you (ssh-keygen -t ed25519 -f <file>), then imported; generate makes keys without one')
        key = _get(d, 'ssh.key')
        if not key or ':' in str(key):
            return self.cm.error(f'{s["alias"]}: ssh.key must name a file inside the artifact (files/id_ed25519_x) to generate it')
        path = self._resolve(s, key)[0]
        pub = self._resolve(s, _get(d, 'ssh.public_key') or f'{key}.pub')[0]
        if os.path.exists(path) and not force:
            return self.cm.error(f'{s["alias"]}: {key} exists already (--force makes a new pair over it)')

        keygen = shutil.which('ssh-keygen')
        if not keygen:
            return self.cm.error('ssh-keygen is not found: cx tool setup open-ssh')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for p in (path, path + '.pub'):
            if os.path.exists(p):
                os.remove(p)
        p = subprocess.run([keygen, '-q', '-t', 'ed25519', '-N', '', '-C', comment or s['alias'], '-f', path],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if p.returncode != 0:
            return self.cm.error(f'{s["alias"]}: ssh-keygen failed ({p.stderr.decode("utf-8", "replace").strip()})')
        if pub and os.path.normcase(pub) != os.path.normcase(path + '.pub'):
            shutil.move(path + '.pub', pub)
        left = self._tighten(ctx, path)
        if left:
            return self.cm.error(f'{s["alias"]}: the key was made but its permissions could not be tightened ({left})')

        fp = subprocess.run([keygen, '-l', '-f', pub or path + '.pub'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30).stdout.decode('utf-8', 'replace').strip()
        if con:
            print (f'cMeta info: {s["alias"]}: a new ed25519 key pair; the public key: {pub or path + ".pub"}')
            print (f'            {fp}')
        return {'return': 0, 'key': path, 'public_key': pub or path + '.pub', 'fingerprint': fp}

    ############################################################
    def use_(self, ctx, arg1: str = None, repo: str = '', git_global: bool = False):
        """
        Write a git identity into a clone's .git/config (--repo=<path>), or into the user's global git config
        (--git_global): user.name, user.email, core.sshCommand (its key, IdentitiesOnly), the signing key and
        format, commit.gpgsign, the allowed signers - through "git config". Paths and names are printed, never a
        key's content.

            cx secret use git-work-without-pass --repo=~/src/project
            cx secret use git-work-without-pass --git_global
        """
        r = self._one(ctx, arg1, ('git',), 'use')
        if r['return'] > 0:
            return r
        s = r['secret']
        con = ctx['control'].get('con', False)
        if bool(repo) == bool(git_global):
            return self.cm.error('cx secret use <alias> --repo=<clone> | --git_global (one of them)')

        rs = self._git_settings(s, ctx['control'].get('quiet', False))
        if rs['return'] > 0:
            return rs
        git = shutil.which('git')
        if not git:
            return self.cm.error('git is not found: cx tool setup git')

        if repo:
            repo = os.path.abspath(os.path.expanduser(repo))
            if not os.path.isdir(os.path.join(repo, '.git')):
                return self.cm.error(f'{repo} is not a git clone (no .git)')
            where = ['-C', repo, 'config', '--local']
        else:
            where = ['config', '--global']

        for k, v in rs['pairs']:
            p = subprocess.run([git] + where + [k, v], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if p.returncode != 0:
                return self.cm.error(f'git config {k} failed: {p.stderr.decode("utf-8", "replace").strip()}')
            if con:
                print (f'  {k} = {v}')
        if con:
            print (f'cMeta info: {s["alias"]} is the git identity of ' + (repo if repo else 'this user (global)'))
        return {'return': 0, 'set': dict(rs['pairs']), 'where': repo or 'global'}

    ############################################################
    def render_(self, ctx, arg1: str = None, out: str = ''):
        """
        A standalone git config of a git identity (the settings of "use", as an include file) and, in its comments,
        the ssh config stanza of its hosts - for a machine or a container without cMeta:

            cx secret render git-work-without-pass --out=~/work.gitconfig
            git config --global include.path ~/work.gitconfig
        """
        r = self._one(ctx, arg1, ('git',), 'render')
        if r['return'] > 0:
            return r
        s = r['secret']
        con = ctx['control'].get('con', False)
        rs = self._git_settings(s, False)
        if rs['return'] > 0:
            return rs

        sections = {}
        for k, v in rs['pairs']:
            section, _, name = k.rpartition('.')
            if section == 'gpg.ssh':
                section = 'gpg "ssh"'
            sections.setdefault(section, []).append((name, v))
        lines = [f'# git identity {s["alias"]}, rendered by "cx secret render" on '
                 f'{datetime.datetime.now().astimezone().isoformat(timespec="minutes")}']
        for h in _get(s['desc'], 'ssh.hosts') or []:
            path = self._resolve(s, _get(s['desc'], 'ssh.key'))[0]
            lines += [f'# ssh config: Host {h}', f'#   IdentityFile {path}', '#   IdentitiesOnly yes']
        for section, items in sections.items():
            lines.append(f'[{section}]')
            # a value in double quotes, its backslashes and quotes escaped (the git config file format)
            lines += ['\t' + name + ' = "' + value.replace('\\', '\\\\').replace('"', '\\"') + '"' for name, value in items]

        path = os.path.abspath(os.path.expanduser(out or f'{s["alias"]}.gitconfig'))
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(lines) + '\n')
        if con:
            print (f'cMeta info: {s["alias"]}: {path} (git config --global include.path "{path}")')
        return {'return': 0, 'path': path, 'set': dict(rs['pairs'])}
