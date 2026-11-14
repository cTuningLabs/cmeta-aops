"""
system-ssh-server - the system's own OpenSSH server of a Linux machine, keys only, allowing the fleet's key for this
machine (README.md):

  cx task run system-ssh-server                 status: installed, running, keys only, the fleet's key allowed, port
  cx task run system-ssh-server enable          install it if missing, keys only, the fleet's key, started at every boot
  cx task run system-ssh-server disable         stopped and no longer started at boot (its settings stay)

It starts at boot by itself (systemd), before any login and without the cMeta repositories - unlike run-openssh, the
server cMeta runs as the user (Windows, or a machine whose repositories are not there at boot). The key: that of the
host artifact this machine is (cx host whoami, cx host key), or --host / --key.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re
import shutil
import socket
import subprocess
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask

DROPIN = '/etc/ssh/sshd_config.d/50-cmeta-keys-only.conf'
DROPIN_TEXT = ('# cmeta-aops system-ssh-server: key logins only (a password never opens this machine over ssh).\n'
               '# "cx task run system-ssh-server disable" stops the server; delete this file to allow passwords again.\n'
               'PasswordAuthentication no\n'
               'KbdInteractiveAuthentication no\n'
               'PermitRootLogin prohibit-password\n')
PORT = 22


def key_body(line):
    """(type, base64) of a public key line - what identifies a key in authorized_keys, whatever its options or comment."""
    m = re.search(r'(?:^|\s)((?:ssh|ecdsa|sk)-[\w@.-]+)\s+([A-Za-z0-9+/=]{20,})', line or '')
    return (m.group(1), m.group(2)) if m else None


def with_key(authorized_keys, public_key):
    """authorized_keys with public_key added once: (text, added)."""
    body = key_body(public_key)
    if not body:
        raise ValueError('not an ssh public key')
    lines = (authorized_keys or '').splitlines()
    if any(key_body(l) == body for l in lines if not l.lstrip().startswith('#')):
        return authorized_keys or '', False
    text = '\n'.join(lines + [public_key.strip()]) + '\n'
    return text.lstrip('\n'), True


def listening(ss_ltn, port):
    """Whether "ss -ltn" shows a listener on the port (any address)."""
    return any(re.search(r':%d\s' % port, l + ' ') for l in (ss_ltn or '').splitlines()[1:])


def banner(port, host = '127.0.0.1', timeout = 3.0):
    """The server's first line (SSH-2.0-OpenSSH_...), or ''."""
    try:
        with socket.create_connection((host, port), timeout = timeout) as s:
            s.settimeout(timeout)
            return s.recv(256).decode('utf-8', 'replace').strip().splitlines()[0]
    except (OSError, IndexError):
        return ''


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            action: str = 'status',    # status, enable, disable
            host: str = '',            # the host artifact whose key is allowed (default: cx host whoami)
            key: str = '',             # or a public key file / <category>::<artifact>/<file> to allow instead
    ):
        """
        The system's OpenSSH server, keys only: status (the default), enable, disable.
        """
        self.con = ctx['control'].get('con', False)
        self.quiet = ctx['control'].get('quiet', False)
        action = str(action or 'status').lower()
        if action not in ('status', 'enable', 'disable'):
            return self.cm.error(f'unknown action "{action}": use status, enable or disable')
        if not sys.platform.startswith('linux'):
            return self.cm.error('system-ssh-server sets up the system\'s OpenSSH server of Linux; on Windows (and '
                                 'where the repositories are there at boot) cx task run start-after-restart enable '
                                 '--what=ssh runs cMeta\'s own (run-openssh)')
        if action == 'enable':
            return self._enable(host, key)
        if action == 'disable':
            return self._disable()
        return self._status()

    ############################################################
    def _say(self, text):
        if self.con:
            print(text)

    def _run(self, words, input_text = None):
        try:
            p = subprocess.run(words, input = input_text.encode('utf-8') if input_text is not None else None,
                               stdin = None if input_text is not None else subprocess.DEVNULL,
                               stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
        except OSError as e:
            return 127, str(e)
        return p.returncode, p.stdout.decode('utf-8', 'replace')

    def _sudo(self, words, input_text = None):
        """As root: itself when root, else sudo (sudo -n in a quiet run; in a terminal sudo may ask)."""
        if os.geteuid() == 0:
            return self._run(words, input_text)
        code, out = self._run(['sudo', '-n'] + words, input_text)
        if code != 0 and 'password' in out.lower() and not self.quiet and sys.stdin.isatty() and input_text is None:
            code, out = subprocess.call(['sudo'] + words), ''
        return code, out

    def _sshd(self):
        return shutil.which('sshd') or ('/usr/sbin/sshd' if os.path.isfile('/usr/sbin/sshd') else None)

    def _units(self):
        """The systemd units of the server: Ubuntu 22.10+ starts it from ssh.socket; others ssh / sshd.service."""
        code, out = self._run(['systemctl', 'list-unit-files', '--no-legend', 'ssh.socket', 'ssh.service', 'sshd.service'])
        names = [l.split()[0] for l in out.splitlines() if l.strip()] if code == 0 else []
        if 'ssh.socket' in names:
            return ['ssh.socket'], 'ssh.service'
        if 'ssh.service' in names:
            return ['ssh.service'], 'ssh.service'
        return ['sshd.service'], 'sshd.service'

    def _public_key(self, host, key):
        """The public key to allow: --key (a file or a cRef path, its .pub for a private key), else the host
        artifact's (cx host key of --host or of cx host whoami)."""
        host_cat = 'host,e4e49c251c814f6d'
        if key:
            path = key
            if '::' in key:
                r = self.cm.access({'category': 'utils', 'command': 'cref', 'arg1': key, 'con': False})
                path = r.get('path') or key if r.get('return', 1) == 0 else key
            if not path.endswith('.pub') and os.path.isfile(path + '.pub'):
                path += '.pub'
        else:
            if not host:
                r = self.cm.access({'category': host_cat, 'command': 'whoami', 'con': False})
                if r.get('return', 1) > 0 or not r.get('host'):
                    return self.cm.error('this machine is no host artifact (cx host whoami): name one with --host, or '
                                         'a public key with --key')
                host = r['host']
            r = self.cm.access({'category': host_cat, 'command': 'key', 'arg1': host, 'con': False})
            if r.get('return', 1) > 0:
                return r
            path = r.get('public') or ''
        if not path or not os.path.isfile(path):
            return self.cm.error(f'no public key file found ({path or "none"})')
        with open(path, encoding = 'utf-8', errors = 'replace') as f:
            text = f.read().strip()
        if not key_body(text) or 'PRIVATE KEY' in text:
            return self.cm.error(f'{path} is not an ssh public key')
        return {'return': 0, 'public_key': text, 'path': path, 'host': host}

    ############################################################
    def _status(self):
        sshd = self._sshd()
        units, service = self._units()
        code, active = self._run(['systemctl', 'is-active'] + units)
        code_e, enabled = self._run(['systemctl', 'is-enabled'] + units)
        code_s, ss = self._run(['ss', '-ltn'])
        auth = os.path.expanduser('~/.ssh/authorized_keys')
        keys = 0
        if os.path.isfile(auth):
            with open(auth, encoding = 'utf-8', errors = 'replace') as f:
                keys = sum(1 for l in f if key_body(l) and not l.lstrip().startswith('#'))
        state = {'installed': bool(sshd), 'units': units, 'active': active.strip(), 'enabled': enabled.strip(),
                 'keys_only': os.path.isfile(DROPIN), 'authorized_keys': keys,
                 'listening': listening(ss, PORT) if code_s == 0 else None, 'banner': banner(PORT)}
        self._say('system OpenSSH server: %s' % ('installed (%s)' % sshd if sshd else 'not installed'))
        if sshd:
            self._say(f'  {", ".join(units)}: {state["active"] or "?"}, at boot: {state["enabled"] or "?"}')
            self._say(f'  port {PORT}: {"listening - " + state["banner"] if state["listening"] else "not listening"}')
            self._say(f'  keys only: {"yes (" + DROPIN + ")" if state["keys_only"] else "no - passwords may be allowed"}')
            self._say(f'  keys allowed for {os.environ.get("USER", "this user")}: {keys} (~/.ssh/authorized_keys)')
        return dict(state, **{'return': 0})

    def _enable(self, host, key):
        r = self._public_key(host, key)
        if r['return'] > 0:
            return r
        public_key, key_path = r['public_key'], r['path']

        # 1. the package
        if not self._sshd():
            if shutil.which('apt-get'):
                words = ['env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y', 'openssh-server']
            elif shutil.which('dnf'):
                words = ['dnf', 'install', '-y', 'openssh-server']
            else:
                return self.cm.error('no apt-get or dnf here: install the OpenSSH server with the distribution\'s '
                                     'package manager, then run this again')
            self._say('installing the OpenSSH server: ' + ' '.join(words))
            code, out = self._sudo(words)
            if code != 0 or not self._sshd():
                return self.cm.error('the OpenSSH server was not installed: ' + out.strip()[-300:])

        # 2. keys only
        code, out = self._sudo(['mkdir', '-p', os.path.dirname(DROPIN)])
        if code == 0:
            code, out = self._sudo(['tee', DROPIN], DROPIN_TEXT)
        if code != 0:
            return self.cm.error(f'writing {DROPIN} failed: {out.strip()[-200:]}')
        code, out = self._sudo([self._sshd(), '-t'])
        if code != 0:
            self._sudo(['rm', '-f', DROPIN])
            return self.cm.error(f'sshd refused its configuration (sshd -t): {out.strip()[-300:]} - {DROPIN} removed')

        # 3. the fleet's key for this machine
        folder = os.path.expanduser('~/.ssh')
        os.makedirs(folder, mode = 0o700, exist_ok = True)
        os.chmod(folder, 0o700)
        auth = os.path.join(folder, 'authorized_keys')
        old = ''
        if os.path.isfile(auth):
            with open(auth, encoding = 'utf-8', errors = 'replace') as f:
                old = f.read()
        text, added = with_key(old, public_key)
        if added:
            with open(auth, 'w', encoding = 'utf-8') as f:
                f.write(text)
        os.chmod(auth, 0o600)
        self._say(f'the key {key_path}: {"allowed" if added else "allowed already"} (~/.ssh/authorized_keys)')

        # 4. started now and at every boot
        units, service = self._units()
        code, out = self._sudo(['systemctl', 'enable', '--now'] + units)
        if code != 0:
            return self.cm.error('systemctl enable --now %s failed: %s' % (' '.join(units), out.strip()[-300:]))
        # a server running from before reads the new settings
        self._sudo(['systemctl', 'try-reload-or-restart', service])
        return self._status()

    def _disable(self):
        units, service = self._units()
        code, out = self._sudo(['systemctl', 'disable', '--now'] + units + ([service] if service not in units else []))
        if code != 0 and self._sshd():
            return self.cm.error('systemctl disable --now failed: ' + out.strip()[-300:])
        self._say('the system OpenSSH server is stopped and no longer starts at boot (its settings and keys stay)')
        return self._status()
