"""
Authors: Grigori Fursin. Licensed under the Apache License, Version 2.0 (the category is bound for cmeta-aops).

secret - identities and credentials as artifacts (README.md): git identities, ssh keys, tokens, files. The meta
holds references, never values; the files live inside the artifact (self-contained) or in another artifact (cRef).

    cx secret ls [<alias or wildcard>]      # alias, kind, repository, hosts, used by
    cx secret show <alias>                  # the references of one identity (never a value)
    cx secret check [<alias>] [--fix]       # the files exist, their mode, the passphrase as declared, the variables set
    cx secret which <cat>::<art>/<file>     # the secret holding a copy of that file (a host key on another orchestrator)
    cx secret import [<alias>] [--force]    # the files copied in from files.from, the private key made owner-only
    cx secret generate <alias>              # a new ed25519 key pair without a passphrase (automation, containers, hosts)
    cx secret use <alias> --repo=<clone>    # the git identity written into a clone's .git/config (or --git_global)
    cx secret render <alias> --out=<file>   # the same as a git config include file, with the ssh config stanza
    cx secret store <alias> [--password_protected]   # a token typed at a hidden prompt, kept owner-only or sealed
    cx secret run <alias> --env.<NAME>={secret} -- <command>   # the value in the command's environment alone
"""

import base64
import datetime
import getpass
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata

from cmeta.category import InitCategory

CATEGORY = 'secret,9d63451ea1f14010'
DESC_FILE = '_desc.yaml'

# A value kept encrypted with a password (password_protected: true), with the standard library alone: two keys from
# the password by scrypt (a new salt each time), the value XORed with an HMAC-SHA256 key stream, and an HMAC-SHA256
# tag over all of it with the second key (encrypt-then-MAC). A wrong password and a changed file both fail the tag.
SEALED = 'cmeta-secret-sealed-v1'
SCRYPT = {'n': 2 ** 17, 'r': 8, 'p': 1}
TRIES = 3

# What stands for the value in the text of a variable (cx secret run --env.TWINE_PASSWORD={secret})
VALUE_MARK = '{secret}'


def _keys(password, salt, n, r, p):
    """The two 32-byte keys of a password: to encrypt and to sign."""
    if not hasattr(hashlib, 'scrypt'):
        raise RuntimeError('this Python has no hashlib.scrypt (it needs OpenSSL 1.1 or newer)')
    if n < 2 or n & (n - 1) or not 1 <= r <= 32 or not 1 <= p <= 16 or 128 * r * (n + p + 2) > 2 ** 30:
        raise ValueError(f'scrypt parameters out of range (n={n}, r={r}, p={p})')
    key = hashlib.scrypt(unicodedata.normalize('NFC', password).encode('utf-8'), salt=salt, n=n, r=r, p=p,
                         maxmem=128 * r * (n + p + 2) + 2 ** 20, dklen=64)
    return key[:32], key[32:]


def _stream(key, nonce, size):
    """The key stream: HMAC-SHA256 of the nonce and a block counter."""
    blocks = (size + 31) // 32
    return b''.join(hmac.new(key, nonce + i.to_bytes(8, 'big'), hashlib.sha256).digest() for i in range(blocks))[:size]


def _signed(head, data):
    """What the tag covers: the parameters, the salt, the nonce and the encrypted value."""
    return json.dumps(head, sort_keys=True).encode('utf-8') + b'\n' + data


def seal(value, password, params=None):
    """A value encrypted with a password: the text of a sealed file (JSON; nothing of the value or the password)."""
    params = dict(params or SCRYPT)
    salt, nonce = os.urandom(16), os.urandom(16)
    enc, mac = _keys(password, salt, **params)
    plain = value.encode('utf-8')
    data = bytes(a ^ b for a, b in zip(plain, _stream(enc, nonce, len(plain))))
    head = {'format': SEALED, 'kdf': 'scrypt', **params,
            'salt': base64.b64encode(salt).decode('ascii'), 'nonce': base64.b64encode(nonce).decode('ascii')}
    tag = hmac.new(mac, _signed(head, data), hashlib.sha256).digest()
    return json.dumps({**head, 'data': base64.b64encode(data).decode('ascii'),
                       'tag': base64.b64encode(tag).decode('ascii')}, indent=1) + '\n'


def sealed_head(text):
    """The parameters of a sealed file, or None when the text is not one."""
    try:
        d = json.loads(text)
    except ValueError:
        return None
    return d if isinstance(d, dict) and d.get('format') == SEALED else None


def unseal(text, password):
    """The value of a sealed file, or None when the password does not open it (or the file was changed)."""
    d = sealed_head(text)
    if d is None or d.get('kdf') != 'scrypt':
        raise ValueError(f'not a sealed value of the format {SEALED}')
    head = {k: d[k] for k in ('format', 'kdf', 'n', 'r', 'p', 'salt', 'nonce')}
    salt, nonce, data, tag = (base64.b64decode(str(d[k]), validate=True) for k in ('salt', 'nonce', 'data', 'tag'))
    enc, mac = _keys(password, salt, int(d['n']), int(d['r']), int(d['p']))
    if not hmac.compare_digest(hmac.new(mac, _signed(head, data), hashlib.sha256).digest(), tag):
        return None
    return bytes(a ^ b for a, b in zip(data, _stream(enc, nonce, len(data)))).decode('utf-8')

# The keys of _desc.yaml that name a file (dotted), with what the file is
FILE_KEYS = {'ssh.key': 'private key', 'ssh.public_key': 'public key', 'signing.key': 'signing key',
             'signing.allowed_signers': 'allowed signers', 'token.file': 'token file', 'file.path': 'file'}

# The files that hold a secret value: readable by their owner alone (check reports any other reader)
OWNER_ONLY_KEYS = ('ssh.key', 'token.file', 'file.path')


def _get(d, dotted):
    for k in dotted.split('.'):
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _ref_key(ref):
    """<category>::<artifact>[/<path inside>] -> (category alias, artifact alias, path inside): the aliases without
    their UIDs and in lower case, the path with "/" and no slash at its ends - two spellings of one place compare equal."""
    cat, _, rest = str(ref or '').replace('\\', '/').partition('::')
    art, _, inside = rest.partition('/')

    def alias(x):
        return re.sub(r',[0-9a-f]{16}$', '', x.strip()).lower()

    return alias(cat), alias(art), inside.strip('/')


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
            found.append({'alias': a['cmeta_ref_parts']['artifact_alias'], 'uid': a['cmeta_ref_parts'].get('artifact_uid', ''), 'path': a['path'],
                          'repo': a['cmeta_ref_parts'].get('repo_alias') or a['cmeta_ref_parts'].get('artifact_repo_alias', ''), 'desc': desc})
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
    def list_(self, ctx, arg1: str = None):
        """
        The secret artifacts: alias, kind, repository, hosts, used by - never a value. (cx secret ls: the engine turns
        ls into list before it looks for the command, so a category's own listing is its list_, not an ls_.)
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
                if d.get('service'):
                    print (f'  {"service":<16} {d.get("service")}  (the secret a task of that service takes when --secret names none)')
                if d.get('password_protected'):
                    print (f'  {"password":<16} protected: encrypted, the password is asked at each use')
                if _get(d, 'token.stored'):
                    print (f'  {"stored":<16} {_get(d, "token.stored")}')
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

        # what is still wrong after the task (a fixed key's earlier problem is not a failure)
        return (rows[0].get('left', rows[0].get('problem', '')) or '') if rows else ''

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
    def which_(self, ctx, arg1: str = None):
        """
        The secret that holds a copy of a file named by a reference into another artifact, and the copy's path:
        the secret whose files.from is the file's folder and whose files.names list the file, imported into its
        files/. A host's "key: fgg.crypt::ssh-x/2026/id_ed25519" is found this way on a machine that has the secret
        and not the fgg.crypt artifact (another orchestrator). Prints the secret and the path - never a value.

            cx secret which fgg.crypt::ssh-universal4-without-pass/20250130-without-pass/id_ed25519_fgg_universal4
        """
        ref = str(arg1 or '').replace('\\', '/').strip()
        if '::' not in ref or '/' not in ref.split('::', 1)[1]:
            return self.cm.error('cx secret which <category>::<artifact>/<the file\'s path inside it>')
        folder, name = ref.rsplit('/', 1)
        want = _ref_key(folder)

        r = self._select(ctx)
        if r['return'] > 0:
            return r

        found = []
        for s in r['secrets']:
            d = s['desc']
            source = str(_get(d, 'files.from') or '')
            if '::' not in source or _ref_key(source) != want:
                continue
            names = [str(x) for x in (_get(d, 'files.names') or [])] or \
                    [os.path.basename(str(_get(d, key))) for key in FILE_KEYS if _get(d, key)]
            path = os.path.join(s['path'], 'files', name)
            if name in names and os.path.isfile(path):
                found.append({'secret': s['alias'], 'repo': s['repo'], 'path': path})

        if not found:
            return {'return': 16, 'error': f'no secret holds a copy of {ref} (its files.from and files.names name the file, imported into files/)'}

        con = ctx['control'].get('con', False)
        if con:
            print (f'{found[0]["secret"]} ({found[0]["repo"]}): {found[0]["path"]}')
        return {'return': 0, 'secret': found[0]['secret'], 'path': found[0]['path'], 'found': found}

    ############################################################
    def check_(self, ctx, arg1: str = None, fix: bool = False, unlock: bool = False):
        """
        The files of each secret exist, a private key has the declared passphrase policy (ssh-keygen asks it
        with an empty passphrase: refused = a passphrase is set; the output is never printed), the mode is 600.
        --fix tightens a file of the artifact that others can read (after a copy to another machine, whose
        transfer does not keep the mode) through the task fix-ssh-key-permissions; a source file is left alone.
        A password-protected value is looked at without its password (sealed, its parameters); --unlock asks for
        the password and says whether it opens the value (nothing of the value is printed).
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

                if key in OWNER_ONLY_KEYS:
                    # The owner-only check of the task fix-ssh-key-permissions: the mode on Linux and macOS, the ACL by SIDs on Windows
                    problem = self._key_permissions(ctx, path, check=True)
                    if problem and fix and status == 'ok':
                        left = self._tighten(ctx, path)
                        problem = f'tightened (was: {problem})' if not left else f'{problem}; --fix could not tighten it: {left}'
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
                if key == 'token.file' and status == 'ok':
                    status = self._check_sealed(ctx, s, path, notes, unlock)
                rows.append((s['alias'], what, status, '; '.join(notes)))

        if con:
            print ('')
            print (f'{"SECRET":<30} {"ITEM":<16} {"STATUS":<8} NOTES')
            for row in rows:
                print (f'{row[0]:<30} {row[1]:<16} {row[2]:<8} {row[3]}')

        return {'return': 0, 'rows': rows}

    def _check_sealed(self, ctx, s, path, notes, unlock):
        """
        The status of a token file against password_protected: a sealed file is looked at without its password (its
        parameters), with --unlock opened with the password asked; a plain file where a sealed one is declared is PLAIN.
        """
        with open(path, encoding='utf-8') as f:
            text = f.read()
        head = sealed_head(text)
        declared = bool(s['desc'].get('password_protected'))
        if head is None:
            if declared:
                notes.append(f'password_protected, but the value is kept in plain text: cx secret store {s["alias"]} --password_protected --force')
                return 'PLAIN'
            return 'ok'

        if not declared:
            notes.append('sealed, but password_protected is not declared in _desc.yaml')
        notes.append(f'sealed ({head.get("kdf")}, n={head.get("n")}): opened with its password only')
        if not unlock:
            return 'ok'
        if not self._interactive(ctx):
            notes.append('--unlock needs a person at a terminal (not -q)')
            return 'ok'
        try:
            value = unseal(text, getpass.getpass(f'Password of the secret {s["alias"]}: '))
        except (KeyboardInterrupt, EOFError):
            notes.append('not unlocked: cancelled')
            return 'ok'
        except (ValueError, KeyError, RuntimeError) as e:
            notes.append(f'cannot be opened: {e}')
            return 'BROKEN'
        if value is None:
            notes.append('this password does NOT open it')
            return 'WRONG PW'
        notes.append(f'the password opens it ({len(value)} characters)')
        return 'ok'

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

    ############################################################
    def _interactive(self, ctx):
        """
        A person can type here: not -q (a quiet run never answers a prompt), and a terminal - on Windows a real
        console: the NUL device says isatty too, and getpass reads the console, not the standard input, so a caller
        with "< NUL" (an AI agent's shell) would wait at a prompt nobody sees.
        """
        if ctx['control'].get('quiet', False):
            return False
        try:
            if not (sys.stdin and sys.stdin.isatty()):
                return False
        except Exception:
            # a stdin object without isatty, or a closed one
            return False
        if os.name != 'nt':
            return True
        try:
            import ctypes
            import msvcrt
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        except (AttributeError, OSError, ValueError):
            # a stand-in for the standard input (a test, an embedding): its own isatty answers
            return True
        mode = ctypes.c_ulong()
        return bool(ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)))

    def _write_owner_only(self, ctx, path, text):
        """
        A file only its owner can read: created with mode 600 on Linux and macOS, tightened on Windows to the owner's
        ACL (fix-ssh-key-permissions). Returns what is still wrong ('' when nothing).
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        if os.path.exists(tmp):
            os.remove(tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, path)
        return self._tighten(ctx, path) if os.name == 'nt' else ''

    def _token_text(self, s):
        """The text of a token's file and its path - (None, path) when there is no file."""
        ref = _get(s['desc'], 'token.file')
        path = self._resolve(s, ref)[0] if ref else None
        if not path or not os.path.isfile(path):
            return None, path
        with open(path, encoding='utf-8') as f:
            return f.read(), path

    def _needs_password(self, s):
        """The value of this secret is opened with a password: declared so, or its file is sealed."""
        text = self._token_text(s)[0]
        return bool(s['desc'].get('password_protected')) or (text is not None and sealed_head(text) is not None)

    def _value(self, ctx, s):
        """
        The value of a token secret: from its variable (token.env), its file (token.file) or - password-protected -
        its sealed file opened with the password asked at a hidden prompt (three tries). For the environment of a
        command (run); never printed, never written, never returned by a command.
        """
        d = s['desc']
        name = _get(d, 'token.env')
        if name:
            value = os.environ.get(str(name), '')
            return {'return': 0, 'value': value} if value else self.cm.error(f'{s["alias"]}: the variable {name} is not set')

        text, path = self._token_text(s)
        if text is None:
            return self.cm.error(f'{s["alias"]}: no value is kept ({_get(d, "token.file") or "no token.file"}): cx secret store {s["alias"]}')
        if sealed_head(text) is None:
            if d.get('password_protected'):
                return self.cm.error(f'{s["alias"]} is password_protected but its value is kept in plain text, so it is not used: '
                                     f'cx secret store {s["alias"]} --password_protected --force')
            return {'return': 0, 'value': text.strip()}

        if not self._interactive(ctx):
            return self.cm.error(f'{s["alias"]} is password-protected and nobody can type the password here (no terminal, or -q)')
        for attempt in range(1, TRIES + 1):
            try:
                value = unseal(text, getpass.getpass(f'Password of the secret {s["alias"]}: '))
            except (KeyboardInterrupt, EOFError):
                return self.cm.error(f'{s["alias"]}: cancelled')
            except (ValueError, KeyError, RuntimeError) as e:
                return self.cm.error(f'{s["alias"]}: {path} cannot be opened ({e})')
            if value is not None:
                return {'return': 0, 'value': value}
            if attempt < TRIES:
                print ('This password does not open it - try again.')
        return self.cm.error(f'{s["alias"]}: the password does not open it ({TRIES} tries)')

    ############################################################
    def store_(self, ctx, arg1: str = None, password_protected: bool = False, force: bool = False):
        """
        Keep a value (a token) in a secret: typed at a hidden prompt, never printed. Kept owner-only in files/token,
        or with --password_protected encrypted with a password you choose (asked twice) in files/token.sealed - every
        use asks for that password again (cx secret run, the task upload-to-pypi). _desc.yaml gets kind: token,
        token.file, token.stored and password_protected. Needs a person at a terminal (never -q).

            cx secret add my-vault:my-pypi --yaml --desc.service=pypi   # the artifact first; service: what it is for
            cx secret store my-pypi --password_protected
            cx secret store my-pypi --password_protected --force        # a new value or a new password
        """
        if not arg1:
            return self.cm.error('cx secret store <alias> [--password_protected]')
        r = self._select(ctx, arg1)
        if r['return'] > 0:
            return r
        if len(r['secrets']) != 1:
            return self.cm.error(f'"{arg1}" matches {len(r["secrets"])} secrets: name one (a new one first: cx secret add <your secrets repository>:{arg1} --yaml)')
        s = r['secrets'][0]
        d = s['desc']
        kind = str(d.get('kind') or 'token')
        if kind != 'token':
            return self.cm.error(f'{s["alias"]} is a secret of kind "{kind}": store keeps the value of a token')
        if _get(d, 'token.env'):
            return self.cm.error(f'{s["alias"]} takes its value from the variable {_get(d, "token.env")}: nothing to store')
        if not self._interactive(ctx):
            return self.cm.error('cx secret store asks for the value at a hidden prompt: run it in a terminal, without -q')

        rel = 'files/token.sealed' if password_protected else 'files/token'
        path = os.path.join(s['path'], *rel.split('/'))
        kept = [p for p in (os.path.join(s['path'], 'files', 'token.sealed'), os.path.join(s['path'], 'files', 'token')) if os.path.isfile(p)]
        if kept and not force:
            return self.cm.error(f'{s["alias"]}: a value is kept already ({os.path.relpath(kept[0], s["path"])}): --force replaces it')

        try:
            if ctx['control'].get('con', False):
                print (f'cMeta info: {s["alias"]} keeps one token (an API key, the password of a service): paste it at the next '
                       'prompt - nothing is shown as you type' + (', then choose the password that protects it' if password_protected else ''))
            value = getpass.getpass(f'Token/secret of {s["alias"]}: ').strip()
            if not value:
                return self.cm.error('no token typed: nothing was written')
            text = value + '\n'
            if password_protected:
                password = getpass.getpass('A password for it (asked at each use): ')
                if not password:
                    return self.cm.error('an empty password: nothing was written')
                if getpass.getpass('The same password again: ') != password:
                    return self.cm.error('the two passwords differ: nothing was written')
                text = seal(value, password)
                # never keep what would not open again
                if unseal(text, password) != value:
                    return self.cm.error('the sealed value does not open again: nothing was written')
        except (KeyboardInterrupt, EOFError):
            return self.cm.error('cancelled: nothing was written')
        except RuntimeError as e:
            return self.cm.error(f'{e}: nothing was written')

        left = self._write_owner_only(ctx, path, text)
        if left:
            return self.cm.error(f'{s["alias"]}: {rel} written but not made owner-only ({left})')
        # the other form of the value (plain or sealed) does not stay behind
        for p in kept:
            if os.path.normcase(p) != os.path.normcase(path):
                os.remove(p)

        # _desc.yaml: kind, password_protected, token.file and token.stored (an existing file keeps its other text)
        desc_path = os.path.join(s['path'], DESC_FILE)
        stamp = datetime.datetime.now().astimezone().isoformat(timespec='minutes')
        if not os.path.isfile(desc_path):
            with open(desc_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(f'# A token kept by "cx secret store" - never printed; "cx secret show {s["alias"]}" says how.\n'
                        'kind: token\n'
                        + ('password_protected: true    # encrypted: the password is asked at each use\n' if password_protected else '')
                        + f'token:\n  file: {rel}\n  stored: \'{stamp}\'\n')
        else:
            new = dict(d)
            new['kind'] = 'token'
            if password_protected:
                new['password_protected'] = True
            else:
                new.pop('password_protected', None)
            new['token'] = dict(new.get('token') or {}, file=rel, stored=stamp)
            try:
                rw = self.cm.utils.files.safe_write_file(desc_path, new, sort_keys=False, preserve=True)
            except TypeError:
                # an engine before the preserve option: the file is written again
                rw = self.cm.utils.files.safe_write_file(desc_path, new, sort_keys=False)
            if rw['return'] > 0:
                return rw

        if ctx['control'].get('con', False):
            how = f'encrypted in {rel} - every use asks for the password' if password_protected else f'in {rel}, readable by you alone'
            print (f'cMeta info: {s["alias"]}: the value ({len(value)} characters) is kept {how}')
            if password_protected and len(password) < 8:
                print ('cMeta warning: a password of fewer than 8 characters keeps the value from a casual reader, '
                       'not from someone who copies the file and tries passwords')
        return {'return': 0, 'secret': s['alias'], 'file': path, 'password_protected': bool(password_protected)}

    ############################################################
    def run_(self, ctx, arg1: str = None, env: dict = None, window: bool = False, pause: bool = False, log: str = '',
             cmd: list = None, unparsed: list = None):
        """
        Run a command with the value of a secret in its environment - and nowhere else: not on its command line, not
        in a file, not in the environment of cMeta. --env.<NAME>=<text> sets a variable of the command; {secret} in the
        text stands for the value. A password-protected secret asks for its password first. On Windows, from a process
        without a terminal (an AI agent) or with --window, it happens in a console window of its own: the password is
        typed there, the command runs there, SUCCESS or FAILED stays until Enter, and the output comes back here.

            cx secret run my-pypi --env.TWINE_USERNAME=__token__ --env.TWINE_PASSWORD={secret} -- twine upload dist/*
            cx secret run <alias> --env.GH_TOKEN={secret} --window -- gh auth status
        """
        words = [str(w) for w in (cmd or unparsed or [])]
        env = env if isinstance(env, dict) else {}
        if not words or not any(VALUE_MARK in str(v) for v in env.values()):
            return self.cm.error(f'cx secret run <alias> --env.<NAME>={VALUE_MARK} -- <command>: the variable that gets the value, then the command')
        r = self._one(ctx, arg1, ('token',), 'run')
        if r['return'] > 0:
            return r
        s = r['secret']

        if os.name == 'nt' and (window or (self._needs_password(s) and not self._interactive(ctx))):
            if ctx['control'].get('quiet', False):
                return self.cm.error(f'{s["alias"]}: a console window waits for a person, which a quiet run (-q) never does')
            return self._run_in_window(ctx, s, env, words)
        if window and not self._interactive(ctx):
            return self.cm.error(f'{s["alias"]}: --window opens a console window on Windows only - run it in a terminal here')
        return self._run_here(ctx, s, env, words, pause=pause, log=log)

    def _run_here(self, ctx, s, env, words, pause=False, log=''):
        """
        The value opened (the password asked when it is sealed), the command run with its variables, the verdict.
        With pause (the console window of run) SUCCESS or FAILED stays on the screen until Enter; with log, what the
        command prints is also written there for the process that waits for the window.
        """
        if pause:
            if os.name == 'nt':
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetConsoleTitleW(f'cMeta: secret {s["alias"]}')
                except (ImportError, AttributeError, OSError):
                    pass
            print (f'cMeta: {" ".join(words)}')
            print (f'       the secret {s["alias"]} in ' + ', '.join(str(k) for k, v in env.items() if VALUE_MARK in str(v)))
            print ('')

        opened = self._value(ctx, s)
        if opened['return'] > 0:
            result = opened
        else:
            child = dict(os.environ)
            for k, v in env.items():
                child[str(k)] = str(v).replace(VALUE_MARK, opened['value'])
            del opened
            result = self._command(words, child, log)

        verdict = 'SUCCESS' if result['return'] == 0 else f'FAILED: {result.get("error", "")}'
        if pause or log:
            print ('')
            print (verdict)
        if log:
            with open(log, 'a', encoding='utf-8', newline='\n') as f:
                f.write(verdict + '\n')
        if pause:
            try:
                input('Press Enter to close this window ... ')
            except (KeyboardInterrupt, EOFError):
                pass
        return result

    def _command(self, words, env, log=''):
        """The command run with these variables; what it prints goes to the screen, and into log when one is given."""
        words = [shutil.which(words[0]) or words[0]] + words[1:]
        try:
            if not log:
                rc = subprocess.run(words, env=env).returncode
            else:
                env = dict(env, PYTHONIOENCODING=env.get('PYTHONIOENCODING') or 'utf-8')
                decode = getattr(getattr(self.cm.utils, 'sys', None), 'decode_output', None) or (lambda b: b.decode('utf-8', 'replace'))
                p = subprocess.Popen(words, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                with open(log, 'a', encoding='utf-8', newline='\n') as f:
                    for line in iter(p.stdout.readline, b''):
                        text = decode(line)
                        sys.stdout.write(text)
                        sys.stdout.flush()
                        f.write(text)
                rc = p.wait()
        except OSError as e:
            return self.cm.error(f'{words[0]} cannot be started: {e}')
        if rc != 0:
            return {'return': 1, 'error': f'{os.path.basename(words[0])} ended with exit code {rc}', 'exit_code': rc}
        return {'return': 0, 'exit_code': 0}

    def _run_in_window(self, ctx, s, env, words):
        """
        The run in a console window of its own (Windows): the same call with pause and a log, started with
        CREATE_NEW_CONSOLE as "python -m cmeta @@<call file>" (the file holds the call - never the value - and is
        deleted when read). This process waits for the window, then prints what the command printed and its verdict.
        """
        con = ctx['control'].get('con', False)
        fd, log = tempfile.mkstemp(prefix='cmeta-secret-run-', suffix='.log')
        os.close(fd)
        fd, call = tempfile.mkstemp(prefix='cmeta-secret-run-', suffix='.json')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'category': CATEGORY, 'command': 'run', 'arg1': f'{s["alias"]},{s["uid"]}' if s.get('uid') else s['alias'],
                       'env': env, 'cmd': words, 'pause': True, 'log': log}, f)
        if con:
            print (f'cMeta info: {s["alias"]}: a console window asks for the password and runs the command - waiting for it to close ...')

        output = ''
        try:
            rc = subprocess.Popen([sys.executable, '-m', 'cmeta', '@@' + call], creationflags=subprocess.CREATE_NEW_CONSOLE).wait()
        except OSError as e:
            return self.cm.error(f'the console window could not be opened: {e}')
        finally:
            if os.path.isfile(log):
                with open(log, encoding='utf-8', errors='replace') as f:
                    output = f.read()
            for p in (log, call):
                if os.path.exists(p):
                    os.remove(p)

        if con and output:
            print (output.rstrip('\n'))
        if rc != 0:
            last = (output.strip().splitlines() or [''])[-1]
            error = last[len('FAILED: '):] if last.startswith('FAILED: ') else f'the window ended with exit code {rc} (closed?)'
            return {'return': 1, 'error': error, 'exit_code': rc}
        return {'return': 0, 'exit_code': 0}
