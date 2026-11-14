"""
Google Chrome as a cMeta tool (README.md): detected where the system keeps it, installed and upgraded with the
system's own channel - Google's package and apt repository on Linux (dnf for an rpm system), winget on Windows,
Homebrew's cask on macOS. The newest version is Google's (versionhistory.googleapis.com, per platform).

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.request

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

VERSION_HISTORY = 'https://versionhistory.googleapis.com/v1/chrome/platforms/{platform}/channels/stable/versions' \
                  '?order_by=version%20desc&pageSize=1'
DEB_URL = 'https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb'
RPM_URL = 'https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm'
PACKAGE = 'google-chrome-stable'
WINGET_ID = 'Google.Chrome'
CASK = 'google-chrome'
VERSION_RE = r'(\d+\.\d+\.\d+\.\d+)'


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
    """"Google Chrome 157.0.8103.78" -> 157.0.8103.78."""
    m = re.search(r'Google Chrome\s+' + VERSION_RE, text or '')
    return m.group(1) if m else None


def version_of_folder(names):
    """Windows: chrome.exe prints no version to a console; the folder of each installed version sits beside it
    (Application\\157.0.8103.78\\) - the newest one."""
    found = [n for n in names or [] if re.fullmatch(VERSION_RE, n)]
    return max(found, key = lambda v: tuple(int(x) for x in v.split('.'))) if found else None


def platform_of(uname, machine):
    """The platform name of Google's version history: linux, win64 / win_arm64, mac / mac_arm64."""
    arm = (machine or '').lower() in ('arm64', 'aarch64')
    if uname == 'windows':
        return 'win_arm64' if arm else 'win64'
    if uname == 'darwin':
        return 'mac_arm64' if arm else 'mac'
    return 'linux'


def newest_of_history(answer):
    versions = (answer or {}).get('versions') or []
    return versions[0].get('version') if versions else None


class CTool(InitCTool):
    """Google Chrome: the system's installation, upgraded through its own channel."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect_versions(self, ctx, paths, params = None):
        """The version of each Chrome found: --version (Linux, macOS), the version folder beside it (Windows)."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        found = {}
        for candidate in paths:
            path = candidate[1:] if candidate.startswith('!') else candidate
            if uname == 'windows':
                try:
                    version = version_of_folder(os.listdir(os.path.dirname(path)))
                except OSError:
                    version = None
            else:
                rc, out, _ = run([path, '--version'], 60)
                version = version_of_output(out)
            if version:
                found[candidate] = {'output': f'BROWSER version : {version}'}
        return {'return': 0, 'found_paths_with_versions': found}

    ############################################################
    def latest_version(self, ctx, params):
        """The newest stable Chrome for this platform (Google's version history)."""
        host = ctx['tasks']['global']['host']['os']
        if host['uname'] == 'linux' and host.get('uarch') == 'arm64':
            return {'return': 16, 'error': 'Google publishes no Chrome for Linux on arm64'}
        url = VERSION_HISTORY.format(platform = platform_of(host['uname'], host.get('uarch')))
        try:
            version = newest_of_history(fetch_json(url))
        except Exception as e:
            return {'return': 16, 'error': f'cannot read Google\'s version history ({url}): {e}'}
        if not version:
            return {'return': 16, 'error': f'no version in {url}'}
        return {'return': 0, 'version': version, 'source': 'Google\'s version history (stable)', 'notes': []}

    ############################################################
    def install(self, ctx, params, cmd = None, *misc):
        """Install Chrome, or bring it to the newest version, through the system's channel."""
        host = ctx['tasks']['global']['host']['os']
        uname = host['uname']
        c = params.get('control', {})
        con, quiet = c.get('con', False), c.get('quiet', False)
        wanted = str(params.get('version') or '').strip()
        if wanted and wanted != 'latest':
            r = self.latest_version(ctx, params)
            if r.get('return') == 0 and r['version'] != wanted:
                return {'return': 16, 'install_cmd': None,
                        'error': f'only the newest Chrome ({r["version"]}) is installed through the system\'s channel, '
                                 f'not {wanted}'}

        if uname == 'linux':
            steps = self.linux_steps(ctx, params, quiet, host.get('uarch'))
        elif uname == 'windows':
            winget = shutil.which('winget')
            if not winget:
                return {'return': 16, 'install_cmd': None, 'error': 'winget is not available'}
            verb = 'upgrade' if self.system_path(uname) else 'install'
            steps = [[winget, verb, '--id', WINGET_ID, '-e', '--source', 'winget', '--accept-package-agreements',
                      '--accept-source-agreements', '--disable-interactivity']]
        elif uname == 'darwin':
            brew = shutil.which('brew')
            if not brew:
                return {'return': 16, 'install_cmd': None, 'error': 'Homebrew is not available (cx tool setup brew)'}
            steps = [[brew, 'upgrade' if self.system_path(uname) else 'install', '--cask', CASK]]
        else:
            return {'return': 16, 'install_cmd': None, 'error': f'no Chrome install for {uname}'}

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
            return {'return': 16, 'install_cmd': None, 'error': 'Chrome was installed, but it is not found'}
        if con and uname == 'linux':
            print('INFO: a Chrome that runs now uses the new version after its next start (it offers to relaunch)')
        return {'return': 0, 'install_cmd': None, 'found_path': path}

    def linux_steps(self, ctx, params, quiet, uarch):
        """apt: an installed Chrome is upgraded from Google's repository (its package added it); a missing one is
        installed from Google's package, which adds the repository. dnf the same with the rpm."""
        if uarch == 'arm64':
            return {'return': 16, 'error': 'Google publishes no Chrome for Linux on arm64 (Chromium is the distribution\'s)'}
        sudo = [] if os.geteuid() == 0 else (['sudo', '-n'] if quiet else ['sudo'])
        installed = False
        if shutil.which('dpkg-query'):
            rc, out, _ = run(['dpkg-query', '-W', '-f=${Status}', PACKAGE], 30)
            installed = rc == 0 and 'install ok installed' in out
        if shutil.which('apt-get'):
            if installed:
                return [sudo + ['apt-get', 'update'],
                        sudo + ['apt-get', 'install', '-y', '--only-upgrade', PACKAGE]]
            from tool_c393ba5c6fa14f66.api.common_release import _download
            content = os.path.join(os.getcwd(), 'content')
            os.makedirs(content, exist_ok = True)
            r = _download(self, ctx, params, DEB_URL, os.path.relpath(content), os.path.basename(DEB_URL))
            if r['return'] > 0:
                return r
            return [sudo + ['apt-get', 'install', '-y', os.path.abspath(r['path'])]]
        if shutil.which('dnf'):
            return [sudo + ['dnf', 'upgrade' if shutil.which(PACKAGE) else 'install', '-y',
                            PACKAGE if shutil.which(PACKAGE) else RPM_URL]]
        return {'return': 16, 'error': 'no apt and no dnf here: install Chrome from https://www.google.com/chrome/'}

    def system_path(self, uname):
        if uname == 'windows':
            for base in (os.environ.get('ProgramFiles', r'C:\Program Files'),
                         os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                         os.environ.get('LOCALAPPDATA', '')):
                exe = os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe')
                if base and os.path.isfile(exe):
                    return exe
            return None
        if uname == 'darwin':
            exe = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
            return exe if os.path.isfile(exe) else None
        return shutil.which(PACKAGE) or shutil.which('google-chrome')
