"""
Mozilla Firefox as a cMeta tool (README.md): detected where the system keeps it, installed and upgraded with the
system's own channel - the snap or the distribution's package on Linux, winget on Windows, Homebrew's cask on macOS.
The newest version is the one that channel gives - the snap's channel, apt's or dnf's candidate, winget's package, the
cask - so that an upgrade brings exactly it (setup detects the tool again at that version); Mozilla's
(product-details.mozilla.org) where none answers, and as a note when Mozilla is ahead.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import configparser
import datetime
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

MOZILLA_VERSIONS = 'https://product-details.mozilla.org/1.0/firefox_versions.json'
MOZILLA_KEYS = {'release': 'LATEST_FIREFOX_VERSION', 'esr': 'FIREFOX_ESR'}
WINGET_IDS ={'release': 'Mozilla.Firefox', 'esr': 'Mozilla.Firefox.ESR'}
CASK = 'firefox'
CASKS = {'release': 'firefox', 'esr': 'firefox@esr'}
SNAP = 'firefox'
PACKAGE = 'firefox'
VERSION_RE = r'(\d+\.\d+(?:\.\d+)?(?:esr)?)'

# winget's exit codes (unsigned): no newer version, and no installed package found - a Firefox installed by Mozilla's
# own installer is not linked to winget's package (as Thunderbird, seen 2026-11-17 on Windows 11)
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


def read_text(path):
    try:
        with open(path, encoding = 'utf-8', errors = 'replace') as f:
            return f.read()
    except OSError:
        return None


############################################################ Pure helpers (offline tests)

def version_of_output(text):
    """"Mozilla Firefox 160.0" -> 160.0 (snap's mount-namespace warnings on stderr are not read)."""
    m = re.search(r'Mozilla Firefox\s+' + VERSION_RE, text or '')
    return m.group(1) if m else None


def version_of_application_ini(text):
    """[App] Version=160.0 of the application.ini beside firefox.exe (Windows: firefox.exe --version prints nothing
    to a console) or in Firefox.app/Contents/Resources (macOS)."""
    parser = configparser.ConfigParser(interpolation = None)
    try:
        parser.read_string(text or '')
        return parser.get('App', 'Version', fallback = None)
    except configparser.Error:
        return None


def plain(version):
    """The numbers of a version, for comparing those of different sources: 160.0~build1 (Mozilla's deb), 153.7.0esr,
    160.0-1 -> 160.0, 153.7.0, 160.0."""
    m = re.match(r'\s*(\d+\.\d+(?:\.\d+)*)', version or '')
    return m.group(1) if m else None


def older(a, b):
    """True when version a is older than version b (their numbers)."""
    def key(v):
        return tuple(int(x) for x in (plain(v) or '0').split('.'))
    return key(a) < key(b)


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


def apt_versions(policy):
    """(installed, candidate) of "apt-cache policy firefox", as numbers (1:160.0~build1 -> 160.0); None for "(none)"
    and for Ubuntu's transitional package that only installs the snap (1:1snap1-0ubuntu5)."""
    def value(label):
        m = re.search(r'^\s*' + label + r':\s*(\S+)', policy or '', re.M)
        return None if not m or m.group(1) == '(none)' else plain(re.sub(r'^\d+:', '', m.group(1)))

    return value('Installed'), value('Candidate')


def newest_of_dnf_info(text):
    """The newest version "dnf info firefox" prints (it lists the installed and the available package)."""
    newest = None
    for v in re.findall(r'^Version\s*:\s*(\S+)', text or '', re.M):
        if plain(v) and (newest is None or older(newest, v)):
            newest = plain(v)
    return newest


def version_of_winget_show(text):
    """The version of "winget show --id <package> -e" (Version: 160.0)."""
    m = re.search(r'^\s*Version\s*:\s*(\S+)', text or '', re.M | re.I)
    return plain(m.group(1)) if m else None


def version_of_cask_info(text):
    """The version of "brew info --json=v2 --cask <cask>" (160.0)."""
    text = text or ''
    try:
        data = json.JSONDecoder().raw_decode(text[text.index('{'):])[0]
        return plain(((data.get('casks') or [{}])[0]).get('version'))
    except (ValueError, AttributeError, IndexError):
        return None


def arp_name_locale(name):
    """(channel, language) of a Windows Uninstall entry's DisplayName: "Mozilla Firefox (x64 en-US)" ->
    (release, en-US), "Mozilla Firefox ESR (x64 de)" -> (esr, de); (None, None) for another name."""
    m = re.match(r'\s*Mozilla Firefox\b(?P<mid>[^()]*)\((?:[\w-]+\s+)?(?P<lang>[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)\)\s*$',
                 name or '')
    if not m:
        return None, None
    return ('esr' if 'esr' in m.group('mid').lower().split() else 'release'), m.group('lang')


def winget_id(channel, language = None):
    """winget's package of a channel and language: Mozilla.Firefox[.ESR] for en-US, else with .<language>
    (Mozilla.Firefox.de, Mozilla.Firefox.ESR.fr)."""
    base = WINGET_IDS.get(channel) or WINGET_IDS['release']
    return base if not language or language == 'en-US' else f'{base}.{language}'


def moved_on(pinned, fresh, where):
    """The error when a package manager's refreshed lists offer another newest version than the one asked for (the one
    --status found): setup detects the tool again at the version it asked for, so nothing is installed then. None when
    they agree or either is unknown."""
    pinned, fresh = plain(pinned), plain(re.sub(r'^\d+:', '', fresh or ''))
    if not pinned or not fresh or pinned == fresh:
        return None
    return (f'{where} offer Firefox {fresh} now, not {pinned} as found before - nothing was installed; run the '
            f'upgrade again to get {fresh}')


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


def linux_channel(real_path, snap_installed, dpkg_owner, rpm_owner = None):
    """How this Firefox is installed on Linux: snap (its binary under /snap, or the snap is installed), deb or rpm (a
    real package of the distribution - not Ubuntu's transitional deb, which only installs the snap), or other."""
    if (real_path or '').startswith('/snap/') or snap_installed:
        return 'snap'
    if dpkg_owner:
        return 'deb'
    if rpm_owner:
        return 'rpm'
    return 'other'


class CTool(InitCTool):
    """Mozilla Firefox: the system's installation, upgraded through its own channel."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect_versions(self, ctx, paths, params = None):
        """The version of each Firefox found: application.ini (Windows, macOS), --version (Linux)."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        found = {}
        for candidate in paths:
            path = candidate[1:] if candidate.startswith('!') else candidate
            version = self.version_at(path, uname)
            if version:
                found[candidate] = {'output': f'BROWSER version : {version}'}
        return {'return': 0, 'found_paths_with_versions': found}

    def version_at(self, path, uname):
        """application.ini beside firefox.exe on Windows (which prints nothing to a console) and in
        Contents/Resources on macOS - no program is started there: a quarantined app waits for the user to allow its
        first start (a Homebrew cask's Thunderbird, 2026-11-17); else --version."""
        if uname == 'darwin':
            folder = os.path.join(os.path.dirname(os.path.dirname(path)), 'Resources')
        else:
            folder = os.path.dirname(path if uname == 'windows' else os.path.realpath(path))
        ini = read_text(os.path.join(folder, 'application.ini'))
        if uname in ('windows', 'darwin') and version_of_application_ini(ini):
            return version_of_application_ini(ini)
        if uname == 'windows' or (uname == 'darwin' and self.quarantined(path)):
            return None
        rc, out, _ = run([path, '--version'], 60)
        return version_of_output(out) or version_of_application_ini(ini)

    def quarantined(self, path):
        """True for a macOS app whose program would wait for Gatekeeper's question on its first start."""
        app = path[:path.find('.app/') + 4] if path and '.app/' in path else path
        rc, out, _ = run(['xattr', '-p', 'com.apple.quarantine', app], 15) if app and shutil.which('xattr') else (1, '', '')
        return rc == 0 and quarantine_waits(out)

    ############################################################
    def installation(self, uname):
        """What is installed here: {path, kind, channel, language, cask, snap, apt, snap_ok}; path None when Firefox
        is missing (snap and apt are still read on Linux: they tell what an install would get)."""
        path = self.system_path(uname)
        inst = {'path': path, 'kind': None, 'channel': None, 'language': None, 'cask': None, 'snap': None,
                'apt': None, 'snap_ok': False}
        if uname == 'windows':
            entry = self.windows_entry(os.path.dirname(path)) if path else None
            inst['channel'], inst['language'] = arp_name_locale(entry.get('name')) if entry else (None, None)
            inst['kind'] = 'winget' if path else None
        elif uname == 'darwin':
            brew = self.brew()
            if brew and path:
                # "brew list" exits with 1 when one of the casks is not installed: the lines of the others count
                rc, out, _ = run([brew, 'list', '--cask', '--versions'] + list(CASKS.values()), 120)
                for line in out.splitlines():
                    token = line.split()[0] if line.split() else ''
                    if token in CASKS.values():
                        inst['cask'] = token
            inst['channel'] = next((c for c, t in CASKS.items() if t == inst['cask']), None)
            inst['kind'] = ('cask' if inst['cask'] else 'app') if path else None
        elif uname == 'linux':
            if shutil.which('snap'):
                rc, out, _ = run(['snap', 'info', SNAP], 60)
                if rc == 0:
                    inst['snap_ok'] = True
                    installed, offered = snap_versions(out)
                    tracking = re.search(r'^tracking:\s+(\S+)', out, re.M)
                    # what "snap install firefox" gets where it is missing
                    stable = re.search(r'^\s+latest/stable:\s+(\d\S*)', out, re.M)
                    inst['snap'] = {'installed': installed, 'offered': offered,
                                    'tracking': tracking.group(1) if tracking else None,
                                    'stable': re.sub(r'-\d+$', '', stable.group(1)) if stable else None}
            if shutil.which('apt-cache'):
                rc, out, _ = run(['apt-cache', 'policy', PACKAGE], 60, env = {'LC_ALL': 'C'})
                if rc == 0 and out.strip():
                    installed, candidate = apt_versions(out)
                    inst['apt'] = {'installed': installed, 'candidate': candidate}
            rpm_owner = None
            if path and shutil.which('rpm'):
                rc, out, _ = run(['rpm', '-q', '--qf', '%{VERSION}', PACKAGE], 30)
                rpm_owner = PACKAGE if rc == 0 and plain(out.strip()) else None
            if path:
                inst['kind'] = linux_channel(os.path.realpath(path), bool((inst['snap'] or {}).get('installed')),
                                             PACKAGE if (inst['apt'] or {}).get('installed') else None, rpm_owner)
        return inst

    def windows_entry(self, folder):
        """The Uninstall entry of the Firefox in folder (its DisplayName tells the channel and the language)."""
        try:
            import winreg
        except ImportError:
            return None
        entries = []
        sub = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
        for root, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                           (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY), (winreg.HKEY_CURRENT_USER, 0)):
            try:
                key = winreg.OpenKey(root, sub, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with key:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(key, name) as k:
                            values = {}
                            for v in ('DisplayName', 'InstallLocation'):
                                try:
                                    values[v] = winreg.QueryValueEx(k, v)[0]
                                except OSError:
                                    values[v] = None
                    except OSError:
                        continue
                    if arp_name_locale(values['DisplayName'])[0]:
                        entries.append({'name': values['DisplayName'], 'location': values['InstallLocation']})
        norm = lambda p: os.path.normcase(os.path.normpath(p)) if p else None
        same = [e for e in entries if folder and norm(e['location']) == norm(folder)]
        return (same or entries or [None])[0]

    ############################################################
    def latest_version(self, ctx, params):
        """The newest Firefox as the system's channel gives it, so that an upgrade brings exactly that version: the
        snap's tracked channel, apt's or dnf's candidate, winget's package, Homebrew's cask; Mozilla's latest release
        where none answers, and as a note when Mozilla is ahead of the system's channel."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        inst = self.installation(uname)
        channel = inst['channel'] or 'release'
        notes = []
        version, source = None, None

        if uname == 'linux':
            snap, apt = inst['snap'] or {}, inst['apt'] or {}
            if snap.get('installed') and snap.get('offered'):
                if self.running():
                    notes.append('Firefox is running: a snap refresh waits until it is closed')
                version, source = snap['offered'], f'the snap {SNAP} (its tracked channel)'
            elif not inst['path'] and inst['snap_ok'] and snap.get('stable'):
                version, source = snap['stable'], f'the snap {SNAP} (latest/stable)'
            elif inst['kind'] == 'deb' and apt.get('candidate'):
                version, source = apt['candidate'], f'apt ({PACKAGE})'
            elif not inst['path'] and not inst['snap_ok'] and apt.get('candidate'):
                version, source = apt['candidate'], f'apt ({PACKAGE})'
            elif (inst['kind'] == 'rpm' or (not inst['path'] and not inst['snap_ok'])) and shutil.which('dnf'):
                version, source = self.dnf_newest(), f'dnf ({PACKAGE})'
                if not version:
                    notes.append(f'dnf gives no version of {PACKAGE}')
            if version and source.startswith('apt'):
                stale = self.apt_lists_note()
                if stale:
                    notes.append(stale)
        elif uname == 'windows' and shutil.which('winget'):
            package = winget_id(channel, inst['language'])
            rc, out, _ = run([shutil.which('winget'), 'show', '--id', package, '-e', '--source', 'winget',
                              '--accept-source-agreements', '--disable-interactivity'], 180)
            version = version_of_winget_show(out) if rc == 0 else None
            source = f'winget ({package})'
            if not version:
                notes.append(f'winget gives no version of {package} (exit code {hex(rc & 0xFFFFFFFF)})')
        elif uname == 'darwin' and self.brew():
            cask = inst['cask'] or CASKS[channel]
            rc, out, _ = run([self.brew(), 'info', '--json=v2', '--cask', cask], 120)
            version = version_of_cask_info(out) if rc == 0 else None
            source = f'Homebrew ({cask})'
            if not version:
                notes.append(f'Homebrew gives no version of the cask {cask} (exit code {rc})')

        try:
            mozilla, failed = fetch_json(MOZILLA_VERSIONS).get(MOZILLA_KEYS[channel]), None
        except Exception as e:
            mozilla, failed = None, f'cannot read Mozilla\'s versions ({MOZILLA_VERSIONS}): {e}'
        if version:
            if mozilla and older(version, mozilla):
                notes.append(f'Mozilla has released {mozilla}: {source} does not offer it yet')
            return {'return': 0, 'version': version, 'source': source, 'notes': notes}
        if failed:
            return {'return': 16, 'error': failed}
        if not mozilla:
            return {'return': 16, 'error': f'no {MOZILLA_KEYS[channel]} in {MOZILLA_VERSIONS}'}
        return {'return': 0, 'version': mozilla, 'source': MOZILLA_VERSIONS, 'notes': notes}

    def dnf_newest(self):
        """The newest Firefox dnf offers, as root sees it when sudo needs no password - root installs it, and a user's
        own metadata can come from another mirror (Fedora 44, 2026-11-17) - else as this user."""
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
        return f'apt\'s package lists are from {when}: "sudo apt-get update" may find a newer Firefox'

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
        pinned = wanted if wanted and wanted != 'latest' else None
        if pinned:
            r = self.latest_version(ctx, params)
            if r.get('return') == 0 and plain(r['version']) != plain(pinned):
                return {'return': 16, 'install_cmd': None,
                        'error': f'only the newest Firefox ({r["version"]}) is installed through the system\'s channel, '
                                 f'not {pinned}'}

        inst = self.installation(uname)
        if uname == 'linux':
            r = self.linux_install(inst, con, quiet, pinned)
        elif uname == 'windows':
            r = self.windows_install(inst, con)
        elif uname == 'darwin':
            r = self.mac_install(inst, con)
        else:
            r = {'return': 16, 'error': f'no Firefox install for {uname}'}
        if r['return'] > 0:
            return dict(r, install_cmd = None)

        path = self.system_path(uname)
        if not path:
            return {'return': 16, 'install_cmd': None, 'error': 'Firefox was installed, but it is not found'}
        return {'return': 0, 'install_cmd': None, 'found_path': path}

    def call(self, step, con, env = None):
        if con:
            print(f'INFO: {" ".join(step)}')
        return subprocess.call(step, env = dict(os.environ, **env) if env else None)

    def windows_install(self, inst, con):
        """winget: upgrade the package of this channel and language; a Firefox winget does not link to its package
        (installed by Mozilla's own installer) is installed over by that package, in its folder."""
        winget = shutil.which('winget')
        if not winget:
            return {'return': 16, 'error': 'winget is not available'}
        package = winget_id(inst['channel'] or 'release', inst['language'])
        common = ['--id', package, '-e', '--source', 'winget', '--accept-package-agreements',
                  '--accept-source-agreements', '--disable-interactivity']
        if inst['path']:
            step = [winget, 'upgrade'] + common
            rc = self.call(step, con) & 0xFFFFFFFF
            if rc == WINGET_NOT_INSTALLED:
                folder = os.path.dirname(inst['path'])
                default = os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Mozilla Firefox')
                where = [] if os.path.normcase(folder) == os.path.normcase(default) else ['--location', folder]
                if con:
                    print(f'INFO: winget does not link this Firefox to {package}: installing that package over it')
                step = [winget, 'install'] + common + where
                rc = self.call(step, con) & 0xFFFFFFFF
        else:
            step = [winget, 'install'] + common
            rc = self.call(step, con) & 0xFFFFFFFF
        # winget's "no newer version" is not a failure
        if rc not in (0, WINGET_NO_UPGRADE):
            return {'return': 16, 'error': f'"{" ".join(step)}" exited with {hex(rc)}'}
        return {'return': 0}

    def mac_install(self, inst, con):
        """Homebrew: upgrade the cask that installed it; an app from Mozilla's disk image is replaced by the cask (the
        profile stays in ~/Library/Application Support/Firefox); a missing one is installed. Without Homebrew's own
        update first, so that it installs the version "brew info" gave (setup detects the tool again at that one)."""
        brew = self.brew()
        if not brew:
            return {'return': 16, 'error': 'Homebrew is not available (cx tool setup brew)'}
        if inst['cask']:
            step = [brew, 'upgrade', '--cask', inst['cask']]
        elif inst['path']:
            step = [brew, 'install', '--cask', '--force', CASK]
        else:
            step = [brew, 'install', '--cask', CASK]
        rc = self.call(step, con, {'HOMEBREW_NO_AUTO_UPDATE': '1'})
        if rc != 0:
            return {'return': 16, 'error': f'"{" ".join(step)}" exited with {rc}'}
        return {'return': 0}

    def linux_install(self, inst, con, quiet, pinned = None):
        """The snap (refresh, refused while Firefox runs; install where snap works), else the distribution's package
        with apt or dnf - their lists refreshed first; when the version asked for (the one --status found) is no longer
        their newest after that, nothing is installed and the error says so."""
        sudo = [] if os.geteuid() == 0 else (['sudo', '-n'] if quiet else ['sudo'])
        kind, missing = inst['kind'], not inst['path']
        snap_installed = bool((inst['snap'] or {}).get('installed'))
        if kind == 'snap' or (missing and inst['snap_ok']):
            if snap_installed and self.running():
                return {'return': 16, 'error': 'Firefox is running: the snap is refreshed only when it is closed - '
                                               'close Firefox, then run the upgrade again'}
            steps = [sudo + ['snap', 'refresh' if snap_installed else 'install', SNAP]]
        elif kind == 'deb' or (missing and shutil.which('apt-get')):
            apt = sudo + ['env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get']
            rc = self.call(apt + ['update'], con)
            if rc != 0:
                return {'return': 16, 'error': f'"{" ".join(apt + ["update"])}" exited with {rc}'}
            rc, out, _ = run(['apt-cache', 'policy', PACKAGE], 60, env = {'LC_ALL': 'C'})
            error = moved_on(pinned, apt_versions(out)[1] if rc == 0 else None, 'apt\'s refreshed package lists')
            if error:
                return {'return': 16, 'error': error}
            steps = [apt + ['install', '-y'] + (['--only-upgrade'] if kind == 'deb' else []) + [PACKAGE]]
        elif kind == 'rpm' or (missing and shutil.which('dnf')):
            error = moved_on(pinned, self.dnf_newest(), 'dnf\'s metadata') if pinned else None
            if error:
                return {'return': 16, 'error': error}
            steps = [sudo + ['dnf', 'upgrade' if kind == 'rpm' else 'install', '-y', PACKAGE]]
        else:
            return {'return': 16, 'error': 'this Firefox is not a snap, a deb or an rpm (a tarball from Mozilla '
                                           'updates itself), or no snap, apt or dnf is here: install Firefox with the '
                                           'distribution\'s package manager (pacman -S firefox ...)'}
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
                         os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')):
                exe = os.path.join(base, 'Mozilla Firefox', 'firefox.exe')
                if os.path.isfile(exe):
                    return exe
            return None
        if uname == 'darwin':
            for app in ('/Applications/Firefox.app', os.path.expanduser('~/Applications/Firefox.app')):
                exe = os.path.join(app, 'Contents', 'MacOS', 'firefox')
                if os.path.isfile(exe):
                    return exe
            return None
        return shutil.which('firefox') or ('/snap/bin/firefox' if os.path.exists('/snap/bin/firefox') else None)
