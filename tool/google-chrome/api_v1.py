"""
Google Chrome as a cMeta tool (README.md): detected where the system keeps it, installed and upgraded with the
system's own channel - Google's package and apt repository on Linux (dnf for an rpm system), winget on Windows,
Homebrew's cask on macOS. The newest version is the one that channel gives - apt's or dnf's candidate from Google's
repository, winget's package, the cask - so that an upgrade brings exactly it (setup detects the tool again at that
version); Google's version history (versionhistory.googleapis.com, per platform) for a missing Chrome on Linux (its
current package is installed) and where no channel answers, and as a note when Google is ahead.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import datetime
import json
import os
import plistlib
import re
import shutil
import subprocess
import time
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

# winget's exit codes (unsigned): no newer version, and no installed package found - a Chrome installed by Google's
# own installer is not linked to winget's package (seen 2026-11-17 on Windows 11)
WINGET_NO_UPGRADE = 0x8A15002B
WINGET_NOT_INSTALLED = 0x8A150014


def run(cmd, timeout = 300, env = None):
    """(return code, stdout, stderr) of a command; never raises (127: it could not be started)."""
    try:
        p = subprocess.run(cmd, stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.PIPE,
                           timeout = timeout, env = dict(os.environ, **env) if env else None)
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


def version_of_info_plist(data):
    """macOS: CFBundleShortVersionString of Google Chrome.app/Contents/Info.plist (XML or binary) - read without
    starting the program: a quarantined app waits for the user to allow its first start."""
    try:
        value = plistlib.loads(data).get('CFBundleShortVersionString') if data else None
    except Exception:
        return None
    return value if value and re.fullmatch(VERSION_RE, str(value)) else None


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


def plain(version):
    """The numbers of a version, for comparing those of different sources: 157.0.8103.78-1 (Google's deb and rpm)
    -> 157.0.8103.78."""
    m = re.match(r'\s*(\d+(?:\.\d+)+)', version or '')
    return m.group(1) if m else None


def older(a, b):
    """True when version a is older than version b (their numbers)."""
    def key(v):
        return tuple(int(x) for x in (plain(v) or '0').split('.'))
    return key(a) < key(b)


def apt_versions(policy):
    """(installed, candidate) of "apt-cache policy google-chrome-stable", as numbers; None for "(none)"."""
    def value(label):
        m = re.search(r'^\s*' + label + r':\s*(\S+)', policy or '', re.M)
        return None if not m or m.group(1) == '(none)' else plain(re.sub(r'^\d+:', '', m.group(1)))

    return value('Installed'), value('Candidate')


def newest_of_dnf_info(text):
    """The newest version "dnf info google-chrome-stable" prints (the installed and the available package)."""
    newest = None
    for v in re.findall(r'^Version\s*:\s*(\S+)', text or '', re.M):
        if plain(v) and (newest is None or older(newest, v)):
            newest = plain(v)
    return newest


def version_of_winget_show(text):
    """The version of "winget show --id Google.Chrome -e" (Version: 157.0.8103.79)."""
    m = re.search(r'^\s*Version\s*:\s*(\S+)', text or '', re.M | re.I)
    return plain(m.group(1)) if m else None


def version_of_cask_info(text):
    """The version of "brew info --json=v2 --cask google-chrome" (157.0.8103.79)."""
    text = text or ''
    try:
        data = json.JSONDecoder().raw_decode(text[text.index('{'):])[0]
        return plain(((data.get('casks') or [{}])[0]).get('version'))
    except (ValueError, AttributeError, IndexError):
        return None


def moved_on(pinned, fresh, where):
    """The error when the system's channel offers another newest version, after a refresh, than the one asked for (the
    one --status found): setup detects the tool again at the version it asked for, so nothing is installed then. None
    when they agree or either is unknown."""
    pinned, fresh = plain(pinned), plain(re.sub(r'^\d+:', '', fresh or ''))
    if not pinned or not fresh or pinned == fresh:
        return None
    return (f'{where} offer{"" if where.endswith("s") else "s"} Chrome {fresh} now, not {pinned} as found before - '
            f'nothing was installed; run the upgrade again to get {fresh}')


def quarantine_waits(value):
    """True when a com.apple.quarantine attribute says the user has not allowed the app yet (its flags, the first
    field, without 0x40): its first start waits for Gatekeeper's question. False without the attribute."""
    value = (value or '').strip()
    if not value:
        return False
    try:
        return not int(value.split(';')[0], 16) & 0x40
    except ValueError:
        return True


class CTool(InitCTool):
    """Google Chrome: the system's installation, upgraded through its own channel."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect_versions(self, ctx, paths, params = None):
        """The version of each Chrome found: the version folder beside it (Windows), Info.plist (macOS), --version
        (Linux)."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        found = {}
        for candidate in paths:
            path = candidate[1:] if candidate.startswith('!') else candidate
            version = self.version_at(path, uname)
            if version:
                found[candidate] = {'output': f'BROWSER version : {version}'}
        return {'return': 0, 'found_paths_with_versions': found}

    def version_at(self, path, uname):
        if uname == 'windows':
            try:
                return version_of_folder(os.listdir(os.path.dirname(path)))
            except OSError:
                return None
        if uname == 'darwin':
            try:
                with open(os.path.join(os.path.dirname(os.path.dirname(path)), 'Info.plist'), 'rb') as f:
                    version = version_of_info_plist(f.read())
            except OSError:
                version = None
            if version or self.quarantined(path):
                return version
        rc, out, _ = run([path, '--version'], 60)
        return version_of_output(out)

    def quarantined(self, path):
        """True for a macOS app whose program would wait for Gatekeeper's question on its first start."""
        app = path[:path.find('.app/') + 4] if path and '.app/' in path else path
        rc, out, _ = run(['xattr', '-p', 'com.apple.quarantine', app], 15) if app and shutil.which('xattr') else (1, '', '')
        return rc == 0 and quarantine_waits(out)

    ############################################################
    def installation(self, uname):
        """What is installed here: {path, kind, cask, apt}; path None when Chrome is missing."""
        path = self.system_path(uname)
        inst = {'path': path, 'kind': None, 'cask': None, 'apt': None}
        if uname == 'windows':
            inst['kind'] = 'winget' if path else None
        elif uname == 'darwin':
            brew = self.brew()
            if brew and path:
                rc, out, _ = run([brew, 'list', '--cask', '--versions', CASK], 120)
                inst['cask'] = CASK if rc == 0 and out.strip().startswith(CASK) else None
            inst['kind'] = ('cask' if inst['cask'] else 'app') if path else None
        elif uname == 'linux':
            if shutil.which('apt-cache'):
                rc, out, _ = run(['apt-cache', 'policy', PACKAGE], 60, env = {'LC_ALL': 'C'})
                if rc == 0 and out.strip():
                    installed, candidate = apt_versions(out)
                    inst['apt'] = {'installed': installed, 'candidate': candidate}
            if (inst['apt'] or {}).get('installed'):
                inst['kind'] = 'deb'
            elif path and shutil.which('rpm'):
                rc, out, _ = run(['rpm', '-q', '--qf', '%{VERSION}', PACKAGE], 30)
                inst['kind'] = 'rpm' if rc == 0 and plain(out.strip()) else 'other'
            elif path:
                inst['kind'] = 'other'
        return inst

    ############################################################
    def latest_version(self, ctx, params):
        """The newest stable Chrome as the system's channel gives it, so that an upgrade brings exactly that version:
        apt's or dnf's candidate from Google's repository, winget's package, Homebrew's cask; Google's version history
        for this platform for a missing Chrome on Linux (Google's current package is installed then) and where no
        channel answers, and as a note when Google is ahead of the system's channel."""
        host = ctx['tasks']['global']['host']['os']
        uname = host['uname']
        if uname == 'linux' and host.get('uarch') == 'arm64':
            return {'return': 16, 'error': 'Google publishes no Chrome for Linux on arm64'}
        inst = self.installation(uname)
        notes = []
        version, source = None, None

        if uname == 'linux':
            apt = inst['apt'] or {}
            if inst['kind'] == 'deb' and apt.get('candidate'):
                version, source = apt['candidate'], f'apt ({PACKAGE}, Google\'s repository)'
                stale = self.apt_lists_note()
                if stale:
                    notes.append(stale)
            elif inst['kind'] == 'rpm' and shutil.which('dnf'):
                version, source = self.dnf_newest(), f'dnf ({PACKAGE}, Google\'s repository)'
                if not version:
                    notes.append(f'dnf gives no version of {PACKAGE}')
        elif uname == 'windows' and shutil.which('winget'):
            rc, out, _ = run([shutil.which('winget'), 'show', '--id', WINGET_ID, '-e', '--source', 'winget',
                              '--accept-source-agreements', '--disable-interactivity'], 180)
            version = version_of_winget_show(out) if rc == 0 else None
            source = f'winget ({WINGET_ID})'
            if not version:
                notes.append(f'winget gives no version of {WINGET_ID} (exit code {hex(rc & 0xFFFFFFFF)}; '
                             f'an old index: "winget source update")')
        elif uname == 'darwin' and self.brew():
            rc, out, _ = run([self.brew(), 'info', '--json=v2', '--cask', CASK], 120)
            version = version_of_cask_info(out) if rc == 0 else None
            source = f'Homebrew ({CASK})'
            if not version:
                notes.append(f'Homebrew gives no version of the cask {CASK} (exit code {rc})')

        url = VERSION_HISTORY.format(platform = platform_of(uname, host.get('uarch')))
        try:
            google, failed = newest_of_history(fetch_json(url)), None
        except Exception as e:
            google, failed = None, f'cannot read Google\'s version history ({url}): {e}'
        if version:
            if google and older(version, google):
                notes.append(f'Google has released {google}: {source} does not offer it yet')
            return {'return': 0, 'version': version, 'source': source, 'notes': notes}
        if failed:
            return {'return': 16, 'error': failed}
        if not google:
            return {'return': 16, 'error': f'no version in {url}'}
        return {'return': 0, 'version': google, 'source': 'Google\'s version history (stable)', 'notes': notes}

    def dnf_newest(self):
        """The newest Chrome dnf offers, as root sees it when sudo needs no password (root installs it), else as this
        user."""
        query = ['env', 'LC_ALL=C', 'dnf', 'info', PACKAGE]
        for cmd in ([query] if os.geteuid() == 0 else [['sudo', '-n'] + query, query]):
            rc, out, _ = run(cmd, 300)
            version = newest_of_dnf_info(out) if rc == 0 else None
            if version:
                return version
        return None

    def apt_lists_note(self):
        """A note when apt's package lists are older than a day (their newest file), else None."""
        folder = '/var/lib/apt/lists'
        try:
            newest = max([os.path.getmtime(folder)] + [e.stat().st_mtime for e in os.scandir(folder) if e.is_file()])
        except (OSError, ValueError):
            return None
        if time.time() - newest < 24 * 3600:
            return None
        when = datetime.datetime.fromtimestamp(newest).strftime('%Y-%m-%d')
        return f'apt\'s package lists are from {when}: "sudo apt-get update" may find a newer Chrome'

    ############################################################
    def install(self, ctx, params, cmd = None, *misc):
        """Install Chrome, or bring it to the newest version, through the system's channel."""
        host = ctx['tasks']['global']['host']['os']
        uname = host['uname']
        c = params.get('control', {})
        con, quiet = c.get('con', False), c.get('quiet', False)
        wanted = str(params.get('version') or '').strip()
        pinned = wanted if wanted and wanted != 'latest' else None
        if pinned:
            r = self.latest_version(ctx, params)
            if r.get('return') == 0 and plain(r['version']) != plain(pinned):
                return {'return': 16, 'install_cmd': None,
                        'error': f'only the newest Chrome ({r["version"]}) is installed through the system\'s channel, '
                                 f'not {pinned}'}

        inst = self.installation(uname)
        if uname == 'linux':
            r = self.linux_install(ctx, params, inst, con, quiet, host.get('uarch'), pinned)
        elif uname == 'windows':
            r = self.windows_install(inst, con)
        elif uname == 'darwin':
            r = self.mac_install(inst, con)
        else:
            r = {'return': 16, 'error': f'no Chrome install for {uname}'}
        if r['return'] > 0:
            return dict(r, install_cmd = None)

        path = self.system_path(uname)
        if not path:
            return {'return': 16, 'install_cmd': None, 'error': 'Chrome was installed, but it is not found'}
        if con and uname == 'linux':
            print('INFO: a Chrome that runs now uses the new version after its next start (it offers to relaunch)')
        return {'return': 0, 'install_cmd': None, 'found_path': path}

    def call(self, step, con, env = None):
        if con:
            print(f'INFO: {" ".join(step)}')
        return subprocess.call(step, env = dict(os.environ, **env) if env else None)

    def windows_install(self, inst, con):
        """winget, Google.Chrome (the machine-wide package): upgrade; a Chrome in Program Files that winget does not
        link to its package (installed by Google's own installer) is installed over by that package. A Chrome of the
        user's own folder (LOCALAPPDATA) updates itself and is not replaced by the machine-wide package."""
        winget = shutil.which('winget')
        if not winget:
            return {'return': 16, 'error': 'winget is not available'}
        common = ['--id', WINGET_ID, '-e', '--source', 'winget', '--accept-package-agreements',
                  '--accept-source-agreements', '--disable-interactivity']
        if inst['path']:
            step = [winget, 'upgrade'] + common
            rc = self.call(step, con) & 0xFFFFFFFF
            if rc == WINGET_NOT_INSTALLED:
                bases = [os.path.normcase(os.environ.get(v, d)) for v, d in
                         (('ProgramFiles', r'C:\Program Files'), ('ProgramFiles(x86)', r'C:\Program Files (x86)'))]
                if not any(os.path.normcase(inst['path']).startswith(b + os.sep) for b in bases):
                    return {'return': 16, 'error': f'this Chrome ({inst["path"]}) is installed for this user only and '
                                                   f'winget does not link it to {WINGET_ID}: it updates itself '
                                                   f'(chrome://settings/help)'}
                if con:
                    print(f'INFO: winget does not link this Chrome to {WINGET_ID}: installing that package over it')
                step = [winget, 'install'] + common
                rc = self.call(step, con) & 0xFFFFFFFF
        else:
            step = [winget, 'install'] + common
            rc = self.call(step, con) & 0xFFFFFFFF
        # winget's "no newer version" is not a failure
        if rc not in (0, WINGET_NO_UPGRADE):
            return {'return': 16, 'error': f'"{" ".join(step)}" exited with {hex(rc)}'}
        return {'return': 0}

    def mac_install(self, inst, con):
        """Homebrew: upgrade the cask that installed it; an app from Google's disk image is replaced by the cask (the
        profile stays in ~/Library/Application Support/Google/Chrome); a missing one is installed. Without Homebrew's
        own update first, so that it installs the version "brew info" gave (setup detects the tool again at that one)."""
        brew = self.brew()
        if not brew:
            return {'return': 16, 'error': 'Homebrew is not available (cx tool setup brew)'}
        if inst['cask']:
            step = [brew, 'upgrade', '--cask', CASK]
        elif inst['path']:
            step = [brew, 'install', '--cask', '--force', CASK]
        else:
            step = [brew, 'install', '--cask', CASK]
        rc = self.call(step, con, {'HOMEBREW_NO_AUTO_UPDATE': '1'})
        if rc != 0:
            return {'return': 16, 'error': f'"{" ".join(step)}" exited with {rc}'}
        return {'return': 0}

    def linux_install(self, ctx, params, inst, con, quiet, uarch, pinned = None):
        """apt: an installed Chrome is upgraded from Google's repository (its package added it), its lists refreshed
        first; a missing one is installed from Google's current package, which adds the repository. dnf the same with
        the rpm. When the version asked for (the one --status found) is no longer the newest after a refresh, or is
        not the downloaded package's, nothing is installed and the error says so."""
        if uarch == 'arm64':
            return {'return': 16, 'error': 'Google publishes no Chrome for Linux on arm64 (Chromium is the distribution\'s)'}
        sudo = [] if os.geteuid() == 0 else (['sudo', '-n'] if quiet else ['sudo'])
        if shutil.which('apt-get'):
            apt = sudo + ['env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get']
            if inst['kind'] == 'deb':
                rc = self.call(apt + ['update'], con)
                if rc != 0:
                    return {'return': 16, 'error': f'"{" ".join(apt + ["update"])}" exited with {rc}'}
                rc, out, _ = run(['apt-cache', 'policy', PACKAGE], 60, env = {'LC_ALL': 'C'})
                error = moved_on(pinned, apt_versions(out)[1] if rc == 0 else None, 'apt\'s refreshed package lists')
                if error:
                    return {'return': 16, 'error': error}
                steps = [apt + ['install', '-y', '--only-upgrade', PACKAGE]]
            else:
                from tool_c393ba5c6fa14f66.api.common_release import _download
                content = os.path.join(os.getcwd(), 'content')
                os.makedirs(content, exist_ok = True)
                r = _download(self, ctx, params, DEB_URL, os.path.relpath(content), os.path.basename(DEB_URL))
                if r['return'] > 0:
                    return r
                deb = os.path.abspath(r['path'])
                if shutil.which('dpkg-deb'):
                    rc, out, _ = run(['dpkg-deb', '-f', deb, 'Version'], 60)
                    error = moved_on(pinned, out.strip() if rc == 0 else None, 'Google\'s current package')
                    if error:
                        return {'return': 16, 'error': error}
                steps = [apt + ['install', '-y', deb]]
        elif shutil.which('dnf'):
            if inst['kind'] == 'rpm':
                error = moved_on(pinned, self.dnf_newest(), 'dnf\'s metadata') if pinned else None
                if error:
                    return {'return': 16, 'error': error}
                steps = [sudo + ['dnf', 'upgrade', '-y', PACKAGE]]
            else:
                steps = [sudo + ['dnf', 'install', '-y', RPM_URL]]
        else:
            return {'return': 16, 'error': 'no apt and no dnf here: install Chrome from https://www.google.com/chrome/'}
        for step in steps:
            rc = self.call(step, con)
            if rc != 0:
                return {'return': 16, 'error': f'"{" ".join(step)}" exited with {rc}'}
        return {'return': 0}

    ############################################################
    def brew(self):
        return shutil.which('brew') or next((b for b in ('/opt/homebrew/bin/brew', '/usr/local/bin/brew')
                                             if os.path.isfile(b)), None)

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
            for app in ('/Applications/Google Chrome.app', os.path.expanduser('~/Applications/Google Chrome.app')):
                exe = os.path.join(app, 'Contents', 'MacOS', 'Google Chrome')
                if os.path.isfile(exe):
                    return exe
            return None
        return shutil.which(PACKAGE) or shutil.which('google-chrome')
