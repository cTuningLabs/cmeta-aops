"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx task run run-openssh": an OpenSSH server run as the user - no service, no administrator - on a
port of its own (default 2222), with key-only logins:

  cx task run run-openssh --host=<host artifact this machine is>   # start (the default action): the fleet's key
  cx task run run-openssh --keys=<public key file>
  cx task run run-openssh status
  cx task run run-openssh stop
  cx task run run-openssh --keys=a.pub,b.pub --port=2223 --listen=192.168.1.10

- It listens on the machine's Tailscale address by default (the one "tailscale ip -4" reports),
  else on 127.0.0.1; --listen=<address> picks another (0.0.0.0: every network, which the firewall
  may block or expose).
- The keys allowed: --host=<host>, the public key of the key the fleet reaches this machine with
  (the host artifact's "access: key", as "cx host key <host>" finds it on this machine: the artifact
  it names, else the copy a secret holds, else ~/.ssh); --keys, separated by commas: public key
  files, authorized_keys files, the keys themselves, or references - secret::<alias> (the secret's
  ssh.public_key) and <category>::<artifact>/<file> (resolved like a host's key; a private key named
  there stands for the .pub beside it). Without either, the user's ~/.ssh/authorized_keys.
- Its host key, configuration, authorized keys, log and PID live in a cache entry
  (task--run-openssh), one folder per --name and port, so the host key stays the same.
- Stop ends the server and the logins it serves.
- Windows: the portable Win32-OpenSSH of tool/openssh-server; logins get cmd.exe. Tailscale's own
  firewall rule ("Tailscale-In") admits connections to its address. Linux, macOS: the system sshd,
  which run as a user logs in that user only.
"""

import getpass
import ipaddress
import os
import re
import shutil
import signal
import socket
import subprocess
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

TAILSCALE = ipaddress.ip_network('100.64.0.0/10')

# The categories a key reference is resolved with (the _cmeta.yaml uses_categories name them too)
HOST = 'host,e4e49c251c814f6d'
SECRET = 'secret,9d63451ea1f14010'

# Where Tailscale's installers put its command when it is not on PATH
TAILSCALE_CLI = ['C:\\Program Files\\Tailscale\\tailscale.exe', '/Applications/Tailscale.app/Contents/MacOS/Tailscale',
                 '/opt/homebrew/bin/tailscale', '/usr/local/bin/tailscale', '/home/linuxbrew/.linuxbrew/bin/tailscale']
SFTP = ['/usr/lib/openssh/sftp-server', '/usr/libexec/openssh/sftp-server', '/usr/lib/ssh/sftp-server',
        '/usr/libexec/sftp-server']


def tailscale_cli():
    """The tailscale command, or None."""
    return shutil.which('tailscale') or next((p for p in TAILSCALE_CLI if os.path.isfile(p)), None)


def local_address(address):
    """Whether the address is one of this machine's (a server can listen on it)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((address, 0))
        return True
    except OSError:
        return False


def tailscale_address(cli = None):
    """
    This machine's Tailscale IPv4 address, or None: the one "tailscale ip -4" reports, if it is in
    Tailscale's range and on this machine. Without the tailscale command there is no answer: the
    carrier-grade NAT of some networks hands out addresses of the same range.
    """
    cli = cli or tailscale_cli()
    if not cli:
        return None
    try:
        out = subprocess.run([cli, 'ip', '-4'], capture_output = True, text = True, timeout = 10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for word in out.split():
        try:
            if ipaddress.ip_address(word) in TAILSCALE and local_address(word):
                return word
        except ValueError:
            pass
    return None


def read_keys(keys, resolve = None):
    """
    The authorized_keys lines of --keys (separated by commas: files, keys, or references that `resolve`
    turns into a public key file - (path, error)): (lines, error). A private key file is refused.
    """
    items = [k.strip() for k in keys.split(',')] if isinstance(keys, str) else list(keys or [])
    lines = []
    for item in [i for i in items if i]:
        words = item.split()
        if words[0].startswith(('ssh-', 'ecdsa-', 'sk-')) and len(words) >= 2:
            lines.append(item)
            continue

        path = os.path.expanduser(item)
        if '::' in item and not os.path.isfile(path):
            if not resolve:
                return None, f'"{item}" is a reference and nothing resolves it here'
            path, error = resolve(item)
            if error:
                return None, error
        if not os.path.isfile(path):
            return None, f'"{item}" is neither a key file, a public key nor a reference to one'

        for line in open(path, encoding = 'utf-8', errors = 'replace'):
            line = line.strip()
            if line.startswith('-----'):
                return None, f'{path} is a private key: name its public key (.pub)'
            if line and not line.startswith('#'):
                lines.append(line)
    return list(dict.fromkeys(lines)), None


def listening(address, port, timeout = 1.0):
    try:
        with socket.create_connection(('127.0.0.1' if address in ('0.0.0.0', '::') else address, int(port)),
                                      timeout = timeout):
            return True
    except OSError:
        return False


def alive(pid):
    """Whether the process is running and is an sshd program (not a PID another program got since)."""
    if os.name == 'nt':
        r = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'], capture_output = True, text = True)
        return r.stdout.strip().lower().startswith('"sshd.exe"')
    try:
        os.kill(pid, 0)
    except OSError:
        return False

    # The program's name: sshd rewrites its title, which macOS shows as "comm"
    try:
        with open(f'/proc/{pid}/comm') as f:
            program = f.read().strip()
    except OSError:
        try:
            program = subprocess.run(['ps', '-p', str(pid), '-o', 'ucomm='], capture_output = True, text = True).stdout.strip()
        except OSError:
            return False
    return os.path.basename(program) == 'sshd'


def sshd_config(port, address, hostkey, authorized, pidfile = None, sftp = None, windows = False):
    """The lines of the server's sshd_config: logins with the keys of the authorized file only."""
    def path(p, tokens = False):
        p = p.replace('\\', '/') if windows else p
        p = p.replace('%', '%%') if tokens else p      # AuthorizedKeysFile expands %h, %u, ...
        return f'"{p}"' if ' ' in p else p
    config = [f'Port {port}', f'ListenAddress {address}', f'HostKey {path(hostkey)}',
              f'AuthorizedKeysFile {path(authorized, tokens = True)}', 'PubkeyAuthentication yes',
              'PasswordAuthentication no', 'KbdInteractiveAuthentication no', 'StrictModes no', 'LogLevel INFO']
    if not windows:
        config += [f'PidFile {path(pidfile)}', 'UsePAM no']
    if sftp:
        config.append(f'Subsystem sftp {path(sftp)}')
    return config


def stop_server(pid):
    """Ends the server and the logins it serves (on Linux and macOS each login is a child process of
    the server that would outlive it)."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output = True)
        return
    logins = []
    if shutil.which('pgrep'):
        r = subprocess.run(['pgrep', '-P', str(pid)], capture_output = True, text = True)
        logins = [int(p) for p in r.stdout.split() if p.isdigit()]
    for p in [pid] + logins:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _public_key_of(self, ref):
        """
        The public key file a reference names: secret::<alias> is the secret's ssh.public_key;
        <category>::<artifact>/<file> is resolved as a host's key is ("cx host key": the artifact when it is
        here, else a secret's copy, else ~/.ssh), a private key standing for the .pub beside it: (path, error).
        """
        uses = self.cmeta.get('uses_categories', {})
        cat, _, rest = ref.partition('::')
        if cat == 'secret' and '/' not in rest:
            r = self.cm.access({'category': uses.get('secret', SECRET), 'command': 'find', 'arg1': rest, 'con': False})
            arts = r.get('artifacts', []) if r['return'] == 0 else []
            if len(arts) != 1:
                return None, f'secret "{rest}" {"not found" if not arts else "matches " + str(len(arts)) + " secrets"}'
            rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(arts[0]['path'], '_desc'))
            desc = rd.get('data') or {} if rd['return'] == 0 else {}
            inside = str((desc.get('ssh') or {}).get('public_key') or '')
            if not inside:
                return None, f'secret "{rest}" declares no ssh.public_key'
            path = os.path.join(arts[0]['path'], *inside.replace('\\', '/').split('/'))
            return (path, None) if os.path.isfile(path) else (None, f'secret "{rest}": {path} does not exist')

        r = self.cm.access({'category': uses.get('host', HOST), 'command': 'key', 'arg1': ref, 'con': False})
        if r['return'] > 0:
            return None, r.get('error', f'"{ref}" cannot be resolved')
        if not r.get('public'):
            return None, f'"{ref}": no public key beside {r.get("path")} - name the .pub file'
        return r['public'], None

    ############################################################
    def run(self,
            ctx: dict,
            action: str = 'start',    # start, stop or status
            port: int = 2222,         # the port to listen on
            listen: str = '',         # the address to listen on (default: Tailscale's, else 127.0.0.1)
            keys: str = '',           # public keys allowed: files, keys or references, separated by commas
            host: str = '',           # the host artifact this machine is: the fleet's key for it is allowed
            name: str = 'default',    # several servers: one folder per name and port
    ):
        """
        Start, stop or show an OpenSSH server run as the user (see the module docstring).
        """
        con = ctx['control'].get('con', False)
        _global = ctx['tasks']['global']
        windows = os.name == 'nt'
        action = str(action or 'start').lower()
        if action not in ('start', 'stop', 'status'):
            return self.cm.error(f'unknown action "{action}": use start, stop or status')
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 0
        if not 0 < port < 65536:
            return self.cm.error('--port must be a number from 1 to 65535')
        name = str(name or 'default')
        if not re.fullmatch(r'[A-Za-z0-9._-]+', name) or name.strip('.') == '':
            return self.cm.error('--name may have letters, digits, ".", "_" and "-" only')

        r = self.cm.access({'category': self.cmeta['uses_categories']['cache'], 'command': 'get',
                            'arg1': 'task--run-openssh',
                            'tags': ['task', 'c36be4b9314a45e0', 'run-openssh', '9216be02930b41f8']})
        if self.cm.catch_error(r):
            return r
        state = os.path.join(r['artifact']['path'], f'{name}-{port}')
        os.makedirs(state, exist_ok = True)
        pidfile = os.path.join(state, 'sshd.pid')
        log = os.path.join(state, 'sshd.log')
        user = getpass.getuser()

        pid = None
        if os.path.isfile(pidfile):
            try:
                pid = int(open(pidfile).read().strip())
            except ValueError:
                pid = None
        running = bool(pid) and alive(pid)
        listen_file = os.path.join(state, 'listen.txt')
        current = open(listen_file).read().strip() if os.path.isfile(listen_file) else ''

        if action == 'status' or (action == 'start' and running):
            if running:
                if con:
                    print(f'INFO: OpenSSH server running (PID {pid}), {"listening" if listening(current, port) else "not answering"}'
                          f' on {current}:{port}: ssh -p {port} {user}@{current}')
                    if action == 'start':
                        print('INFO: it is already running: stop it first to change its address or keys')
                return {'return': 0, 'running': True, 'pid': pid, 'listen': current, 'port': port, 'user': user, 'state': state}
            if con:
                print(f'INFO: no OpenSSH server of "{name}" on port {port}')
            return {'return': 0, 'running': False, 'port': port, 'state': state}

        if action == 'stop':
            if running:
                stop_server(pid)
                for _ in range(50):
                    if not alive(pid):
                        break
                    time.sleep(0.1)
            if os.path.isfile(pidfile):
                os.remove(pidfile)
            if con:
                print(f'INFO: OpenSSH server {"stopped (PID " + str(pid) + ")" if running else "was not running"}')
            return {'return': 0, 'running': False, 'stopped': running, 'port': port}

        # Start: the address, the keys, the host key and the configuration
        address = listen or tailscale_address() or '127.0.0.1'
        if con and address in ('0.0.0.0', '::'):
            print('WARNING: listening on every network of this machine')
        elif con and not listen and address == '127.0.0.1':
            print('INFO: no Tailscale address ("tailscale ip -4"): only this machine can connect;'
                  ' --listen=<address> picks another')
        items = [k.strip() for k in str(keys or '').split(',') if k.strip()]
        if host:
            r = self.cm.access({'category': self.cmeta.get('uses_categories', {}).get('host', HOST), 'command': 'key',
                                'arg1': str(host), 'con': False})
            if r['return'] > 0:
                return r
            if not r.get('public'):
                return self.cm.error(f'host {host}: no public key beside its key {r.get("path")}')
            items.append(r['public'])
            if con:
                print(f'INFO: the key of host {host} ({r.get("ref")}): {r["public"]}')
        default_keys = os.path.expanduser('~/.ssh/authorized_keys')
        lines, error = read_keys(items or (default_keys if os.path.isfile(default_keys) else ''), resolve = self._public_key_of)
        if error:
            return self.cm.error(error)
        if not lines:
            return self.cm.error('no public keys to allow: give --host=<the host artifact this machine is> or --keys=<public key file, key or reference>[,...]')

        sshd = _global['openssh-server']['path']
        tools = os.path.dirname(sshd)
        keygen = os.path.join(tools, 'ssh-keygen.exe') if windows else (shutil.which('ssh-keygen') or '/usr/bin/ssh-keygen')
        hostkey = os.path.join(state, 'ssh_host_ed25519_key')
        if not os.path.isfile(hostkey):
            k = subprocess.run([keygen, '-q', '-t', 'ed25519', '-N', '', '-C', f'cmeta-run-openssh-{name}', '-f', hostkey],
                               capture_output = True, text = True)
            if k.returncode != 0:
                return self.cm.error(f'ssh-keygen failed: {(k.stderr or k.stdout).strip()}')
        if windows:
            # sshd refuses a host key that other users can read
            subprocess.run(['icacls', hostkey, '/inheritance:r', '/grant:r', f'{user}:F'], capture_output = True)
        else:
            os.chmod(hostkey, 0o600)

        authorized = os.path.join(state, 'authorized_keys')
        with open(authorized, 'w', encoding = 'utf-8', newline = '\n') as f:
            f.write('\n'.join(lines) + '\n')
        if not windows:
            os.chmod(authorized, 0o600)

        sftp = os.path.join(tools, 'sftp-server.exe') if windows else next((p for p in SFTP if os.path.isfile(p)), None)
        config = sshd_config(port, address, hostkey, authorized, pidfile = pidfile,
                             sftp = sftp if sftp and os.path.isfile(sftp) else None, windows = windows)
        cfg = os.path.join(state, 'sshd_config')
        with open(cfg, 'w', encoding = 'utf-8', newline = '\n') as f:
            f.write('# An OpenSSH server run as the user by task/run-openssh\n' + '\n'.join(config) + '\n')

        t = subprocess.run([sshd, '-t', '-f', cfg], capture_output = True, text = True)
        if t.returncode != 0:
            return self.cm.error(f'sshd rejects its configuration {cfg}: {(t.stderr or t.stdout).strip()[-500:]}')

        # In the background, detached from this process (and from a Job Object on Windows)
        out = open(log, 'ab')
        command = [sshd, '-D', '-e', '-f', cfg]
        if windows:
            flags = 0x00000008 | 0x00000200            # DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP
            try:
                p = subprocess.Popen(command, stdout = out, stderr = subprocess.STDOUT, stdin = subprocess.DEVNULL,
                                     creationflags = flags | 0x01000000)    # CREATE_BREAKAWAY_FROM_JOB
            except OSError:
                p = subprocess.Popen(command, stdout = out, stderr = subprocess.STDOUT, stdin = subprocess.DEVNULL,
                                     creationflags = flags)
        else:
            p = subprocess.Popen(command, stdout = out, stderr = subprocess.STDOUT, stdin = subprocess.DEVNULL,
                                 start_new_session = True)
        out.close()
        with open(pidfile, 'w') as f:
            f.write(str(p.pid))
        with open(listen_file, 'w') as f:
            f.write(address)

        for _ in range(100):
            if p.poll() is not None or listening(address, port):
                break
            time.sleep(0.1)
        if p.poll() is not None:
            tail = open(log, encoding = 'utf-8', errors = 'replace').read()[-800:]
            return self.cm.error(f'sshd exited with code {p.returncode}: {tail.strip()}')

        fingerprint = subprocess.run([keygen, '-lf', hostkey + '.pub'], capture_output = True, text = True).stdout.strip()
        if con:
            print(f'INFO: OpenSSH server started (PID {p.pid}) on {address}:{port}, {len(lines)} key(s) allowed')
            print(f'INFO: connect with: ssh -p {port} {user}@{address}')
            print(f'INFO: host key: {fingerprint}')
            print(f'INFO: stop with: cx task run run-openssh stop --port={port}' + (f' --name={name}' if name != 'default' else ''))
        return {'return': 0, 'running': True, 'pid': p.pid, 'listen': address, 'port': port, 'user': user,
                'state': state, 'host_key': fingerprint}
