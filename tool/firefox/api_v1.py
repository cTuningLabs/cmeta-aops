"""
Mozilla Firefox as a cMeta tool (README.md): detected where the system keeps it, installed and upgraded with the
system's own channel - the snap or the distribution's package on Linux, winget on Windows, Homebrew's cask on macOS.
The newest version is Mozilla's (product-details.mozilla.org) and, for a snap, the one its channel offers.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import configparser
import json
import os
import re
import shutil
import subprocess
import urllib.request

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

MOZILLA_VERSIONS = 'https://product-details.mozilla.org/1.0/firefox_versions.json'
WINGET_ID = 'Mozilla.Firefox'
CASK = 'firefox'
SNAP = 'firefox'
PACKAGE = 'firefox'
VERSION_RE = r'(\d+\.\d+(?:\.\d+)?(?:esr)?)'


def run(cmd, timeout = 300):
    """(return code, stdout, stderr) of a command; never raises (127: it could not be started)."""
    try:
        p = subprocess.run(cmd, stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.PIPE,
                           timeout = timeout)
        return p.returncode, p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace')
    except Exception as e:
        return 127, '', str(e)


def fetch_json(url, timeout = 30):
    with urllib.request.urlopen(urllib.request.Request(url, headers = {'User-Agent': 'cmeta-aops'}), timeout = timeout) as r:
        return json.loads(r.read().decode('utf-8'))


############################################################ Pure helpers (offline tests)

def version_of_output(text):
    """"Mozilla Firefox 160.0" -> 160.0 (snap's mount-namespace warnings on stderr are not read)."""
    m = re.search(r'Mozilla Firefox\s+' + VERSION_RE, text or '')
    return m.group(1) if m else None


def version_of_application_ini(text):
    """[App] Version=160.0 of the application.ini beside firefox.exe (Windows: firefox.exe --version prints nothing
    to a console)."""
    parser = configparser.ConfigParser(interpolation = None)
    try:
        parser.read_string(text or '')
        return parser.get('App', 'Version', fallback = None)
    except configparser.Error:
        return None


def snap_versions(snap_info):
    """(installed, offered by the tracked channel) of "snap info <name>": the snap's own suffix (-1) dropped."""
    def clean(v):
        return re.sub(r'-\d+$', '', v) if v else None

    installed = re.search(r'^installed:\s+(\S+)', snap_info or '', re.M)
    tracking = re.search(r'^tracking:\s+(\S+)', snap_info or '', re.M)
    offered = None
    if tracking:
        # latest/stable/ubuntu-26.04 is served by the latest/stable line
        channel = tracking.group(1)
        for name in (channel, '/'.join(channel.split('/')[:2])):
            m = re.search(r'^\s+' + re.escape(name) + r':\s+(\S+)', snap_info, re.M)
            if m and m.group(1) not in ('^', '--', '↑'):
                offered = m.group(1)
                break
    return clean(installed.group(1) if installed else None), clean(offered)


def linux_channel(real_path, snap_installed, dpkg_owner):
    """How this Firefox is installed on Linux: snap (its binary under /snap, or the snap is installed), deb (a real
    package of the distribution - not Ubuntu's transitional one, which only installs the snap), or other."""
    if (real_path or '').startswith('/snap/') or snap_installed:
        return 'snap'
    if dpkg_owner:
        return 'deb'
    return 'other'


class CTool(InitCTool):
    """Mozilla Firefox: the system's installation, upgraded through its own channel."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect_versions(self, ctx, paths, params = None):
        """The version of each Firefox found: --version (Linux, macOS), application.ini beside it (Windows)."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        found = {}
        for candidate in paths:
            path = candidate[1:] if candidate.startswith('!') else candidate
            version = None
            if uname == 'windows':
                ini = os.path.join(os.path.dirname(path), 'application.ini')
                if os.path.isfile(ini):
                    with open(ini, encoding = 'utf-8', errors = 'replace') as f:
                        version = version_of_application_ini(f.read())
            else:
                rc, out, _ = run([path, '--version'], 60)
                version = version_of_output(out)
            if version:
                found[candidate] = {'output': f'BROWSER version : {version}'}
        return {'return': 0, 'found_paths_with_versions': found}

    ############################################################
    def latest_version(self, ctx, params):
        """The newest Firefox: what the snap's channel offers when Firefox is a snap (that is what an upgrade gets),
        else Mozilla's latest release."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        notes = []
        if uname == 'linux' and shutil.which('snap'):
            rc, out, _ = run(['snap', 'info', SNAP], 60)
            installed, offered = snap_versions(out) if rc == 0 else (None, None)
            if installed and offered:
                if self.running():
                    notes.append('Firefox is running: a snap refresh waits until it is closed')
                return {'return': 0, 'version': offered, 'source': f'the snap {SNAP} (its tracked channel)', 'notes': notes}
        try:
            version = fetch_json(MOZILLA_VERSIONS).get('LATEST_FIREFOX_VERSION')
        except Exception as e:
            return {'return': 16, 'error': f'cannot read Mozilla\'s versions ({MOZILLA_VERSIONS}): {e}'}
        if not version:
            return {'return': 16, 'error': f'no LATEST_FIREFOX_VERSION in {MOZILLA_VERSIONS}'}
        return {'return': 0, 'version': version, 'source': MOZILLA_VERSIONS, 'notes': notes}

    def running(self):
        rc, out, _ = run(['pgrep', '-x', 'firefox'], 15) if shutil.which('pgrep') else (1, '', '')
        return rc == 0 and bool(out.strip())

    ############################################################
    def install(self, ctx, params, cmd = None, *misc):
        """Install Firefox, or bring it to the newest version, through the system's channel."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        c = params.get('control', {})
        con, quiet = c.get('con', False), c.get('quiet', False)
        wanted = str(params.get('version') or '').strip()
        if wanted and wanted not in ('latest',):
            r = self.latest_version(ctx, params)
            if r.get('return') == 0 and r['version'] != wanted:
                return {'return': 16, 'install_cmd': None,
                        'error': f'only the newest Firefox ({r["version"]}) is installed through the system\'s channel, '
                                 f'not {wanted}'}

        if uname == 'linux':
            steps = self.linux_steps(quiet)
        elif uname == 'windows':
            winget = shutil.which('winget')
            if not winget:
                return {'return': 16, 'install_cmd': None, 'error': 'winget is not available'}
            have = self.system_path(uname)
            verb = 'upgrade' if have else 'install'
            steps = [[winget, verb, '--id', WINGET_ID, '-e', '--source', 'winget', '--accept-package-agreements',
                      '--accept-source-agreements', '--disable-interactivity']]
        elif uname == 'darwin':
            brew = shutil.which('brew')
            if not brew:
                return {'return': 16, 'install_cmd': None, 'error': 'Homebrew is not available (cx tool setup brew)'}
            have = os.path.isdir('/Applications/Firefox.app')
            steps = [[brew, 'upgrade' if have else 'install', '--cask', CASK]]
        else:
            return {'return': 16, 'install_cmd': None, 'error': f'no Firefox install for {uname}'}

        if isinstance(steps, dict):
            return dict(steps, install_cmd = None)

        for step in steps:
            if con:
                print(f'INFO: {" ".join(step)}')
            rc = subprocess.call(step)
            # winget's "no newer version" is not a failure
            if rc != 0 and not (uname == 'windows' and rc in (-1978335189, 0x8A15002B)):
                return {'return': 16, 'install_cmd': None, 'error': f'"{" ".join(step)}" exited with {rc}'}

        path = self.system_path(uname)
        if not path:
            return {'return': 16, 'install_cmd': None, 'error': 'Firefox was installed, but it is not found'}
        return {'return': 0, 'install_cmd': None, 'found_path': path}

    def linux_steps(self, quiet):
        """The commands for Linux: snap refresh / install, or the distribution's package (apt)."""
        sudo = [] if os.geteuid() == 0 else (['sudo', '-n'] if quiet else ['sudo'])
        path = shutil.which('firefox')
        real = os.path.realpath(path) if path else ''
        snap_installed = False
        if shutil.which('snap'):
            rc, out, _ = run(['snap', 'list', SNAP], 30)
            snap_installed = rc == 0 and SNAP in out
        owner = None
        if path and shutil.which('dpkg-query'):
            rc, out, _ = run(['dpkg-query', '-W', '-f=${Version}', PACKAGE], 30)
            # Ubuntu's firefox package of version "1snap1" only installs the snap
            owner = PACKAGE if rc == 0 and out.strip() and 'snap' not in out else None
        channel = linux_channel(real, snap_installed, owner)

        if channel == 'snap' or (not path and shutil.which('snap')):
            if snap_installed and self.running():
                return {'return': 16, 'error': 'Firefox is running: the snap is refreshed only when it is closed - '
                                               'close Firefox, then run the upgrade again'}
            return [sudo + ['snap', 'refresh' if snap_installed else 'install', SNAP]]
        if shutil.which('apt-get'):
            return [sudo + ['apt-get', 'update'],
                    sudo + ['apt-get', 'install', '-y'] + (['--only-upgrade'] if owner else []) + [PACKAGE]]
        return {'return': 16, 'error': 'no snap and no apt here: install Firefox with the distribution\'s package '
                                       'manager (dnf install firefox, pacman -S firefox ...)'}

    def system_path(self, uname):
        if uname == 'windows':
            for base in (os.environ.get('ProgramFiles', r'C:\Program Files'),
                         os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')):
                exe = os.path.join(base, 'Mozilla Firefox', 'firefox.exe')
                if os.path.isfile(exe):
                    return exe
            return None
        if uname == 'darwin':
            exe = '/Applications/Firefox.app/Contents/MacOS/firefox'
            return exe if os.path.isfile(exe) else None
        return shutil.which('firefox') or ('/snap/bin/firefox' if os.path.exists('/snap/bin/firefox') else None)
