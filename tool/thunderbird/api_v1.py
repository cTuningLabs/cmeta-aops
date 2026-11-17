"""
Mozilla Thunderbird as a cMeta tool (README.md): detected where the system keeps it, installed and upgraded with the
system's own channel - the snap or the distribution's package on Linux, winget on Windows, Homebrew's cask on macOS -
in the update channel the installation follows: the monthly release or the ESR (extended support release). The
newest version is the one the system's channel gives - the snap's channel, apt's candidate, winget's package, the
cask - so that an upgrade brings exactly it; Mozilla's newest of the channel (product-details.mozilla.org) where none
answers, and as a note when Mozilla is ahead.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import configparser
import datetime
import json
import ntpath
import os
import re
import shutil
import subprocess
import time
import urllib.request

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

MOZILLA_VERSIONS = 'https://product-details.mozilla.org/1.0/thunderbird_versions.json'
MOZILLA_KEYS = {'release': 'LATEST_THUNDERBIRD_VERSION', 'esr': 'THUNDERBIRD_ESR'}
CHANNELS = ('release', 'esr')
WINGET_IDS = {'release': 'Mozilla.Thunderbird', 'esr': 'Mozilla.Thunderbird.ESR'}
CASKS = {'release': 'thunderbird', 'esr': 'thunderbird@esr'}
SNAP = 'thunderbird'
SNAP_CHANNELS = {'release': 'latest/stable', 'esr': 'esr/stable'}
PACKAGE = 'thunderbird'
VERSION_RE = r'(\d+\.\d+(?:\.\d+)*)(esr)?'

# winget's exit codes (unsigned): no newer version, and no installed package found - a Thunderbird installed by
# Mozilla's own installer is not linked to winget's package (seen 2026-11-17 on Windows 11)
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

def plain(version):
    """153.7.0esr -> 153.7.0: versions are compared without the ESR's suffix (the channel is kept apart)."""
    m = re.match(r'\s*' + VERSION_RE, version or '')
    return m.group(1) if m else None


def version_of_output(text):
    """"Thunderbird 153.7.0esr" (also "Mozilla Thunderbird 160.0") -> 153.7.0esr, as printed (snap's mount-namespace
    warnings on stderr are not read)."""
    m = re.search(r'Thunderbird\s+(\d+\.\d+(?:\.\d+)*(?:esr)?)', text or '')
    return m.group(1) if m else None


def version_of_application_ini(text):
    """[App] Version=153.7.0 of the application.ini beside thunderbird.exe (Windows: thunderbird.exe --version prints
    nothing to a console) or in Thunderbird.app/Contents/Resources (macOS)."""
    parser = configparser.ConfigParser(interpolation = None)
    try:
        parser.read_string(text or '')
        return parser.get('App', 'Version', fallback = None)
    except configparser.Error:
        return None


def channel_of_prefs(text):
    """The update channel of defaults/pref/channel-prefs.js: pref("app.update.channel", "esr") -> esr."""
    m = re.search(r'''pref\(\s*["']app\.update\.channel["']\s*,\s*["']([\w.-]+)["']\s*\)''', text or '')
    return m.group(1) if m else None


def channel_of_update_settings(text):
    """esr or release from ACCEPTED_MAR_CHANNEL_IDS of update-settings.ini (thunderbird-comm-esr, -release)."""
    m = re.search(r'^ACCEPTED_MAR_CHANNEL_IDS\s*=\s*(\S+)', text or '', re.M)
    ids = m.group(1).split(',') if m else []
    if any(i.endswith('-esr') for i in ids):
        return 'esr'
    if any(i.endswith('-release') for i in ids):
        return 'release'
    return None


def channel_of(*hints):
    """The first channel the hints tell: a channel name (esr, release, beta ...) or a version with the ESR's suffix
    (153.7.0esr); None when none does."""
    for hint in hints:
        if not hint:
            continue
        h = str(hint).strip().lower()
        if re.match(r'\d+\.\d+', h):
            if h.endswith('esr') or re.search(r'esr-', h):
                return 'esr'
            continue
        if h == 'default':
            continue
        return h
    return None


def arp_name_locale(name):
    """(channel, language) of a Windows Uninstall entry's DisplayName: "Mozilla Thunderbird ESR (x64 en-US)" ->
    (esr, en-US), "Mozilla Thunderbird (x64 de)" -> (release, de); (None, None) for another name."""
    m = re.match(r'\s*Mozilla Thunderbird\b(?P<mid>[^()]*)\((?:[\w-]+\s+)?(?P<lang>[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)\)\s*$',
                 name or '')
    if not m:
        return None, None
    words = m.group('mid').lower().split()
    channel = 'esr' if 'esr' in words else ('beta' if 'beta' in words else 'release')
    return channel, m.group('lang')


def winget_id(channel, language = None):
    """winget's package of a channel and language: Mozilla.Thunderbird[.ESR] for en-US, else with .<language>
    (Mozilla.Thunderbird.de, Mozilla.Thunderbird.ESR.fr)."""
    base = WINGET_IDS.get(channel) or WINGET_IDS['release']
    return base if not language or language == 'en-US' else f'{base}.{language}'


def newest_of(versions, channel):
    """The newest version of a channel (release unless esr) in Mozilla's thunderbird_versions.json, plain."""
    return plain((versions or {}).get(MOZILLA_KEYS['esr' if channel == 'esr' else 'release']))


def older(a, b):
    """True when version a is older than version b (both plain, numbers only)."""
    def key(v):
        return tuple(int(x) for x in (plain(v) or '0').split('.'))
    return key(a) < key(b)


def version_of_winget_show(text):
    """The version of "winget show --id <package> -e" (Version: 153.7.0), plain."""
    m = re.search(r'^\s*Version\s*:\s*(\S+)', text or '', re.M | re.I)
    return plain(m.group(1)) if m else None


def version_of_cask_info(text):
    """The version of "brew info --json=v2 --cask <cask>" (153.7.0esr), plain."""
    text = text or ''
    try:
        data = json.JSONDecoder().raw_decode(text[text.index('{'):])[0]
        return plain(((data.get('casks') or [{}])[0]).get('version'))
    except (ValueError, AttributeError, IndexError):
        return None


def snap_info(text):
    """{installed, tracking, offered, channels} of "snap info thunderbird", versions plain (153.7.0esr-3 -> 153.7.0):
    offered is what the tracked channel gives (latest/stable/ubuntu-26.04 is served by latest/stable), channels the
    version of each channel listed."""
    def clean(v):
        return plain(re.sub(r'-\d+$', '', v)) if v and v not in ('^', '--', '↑') else None

    text = text or ''
    installed = re.search(r'^installed:\s+(\S+)', text, re.M)
    tracking = re.search(r'^tracking:\s+(\S+)', text, re.M)
    channels = {m.group(1): clean(m.group(2)) for m in re.finditer(r'^\s+([\w.-]+/[\w./-]+):\s+(\S+)', text, re.M)}
    offered = None
    if tracking:
        name = tracking.group(1)
        for candidate in (name, '/'.join(name.split('/')[:2])):
            if channels.get(candidate):
                offered = channels[candidate]
                break
    return {'installed': clean(installed.group(1)) if installed else None,
            'tracking': tracking.group(1) if tracking else None,
            'offered': offered, 'channels': channels}


def snap_channel(tracking):
    """esr for a snap that tracks esr/..., else release."""
    return 'esr' if (tracking or '').startswith('esr') else 'release'


def apt_policy(text):
    """(installed, candidate, esr) of "apt-cache policy thunderbird", versions plain: the epoch, the ESR's suffix and
    the Debian revision dropped (1:140.5.0esr-1~deb12u1 -> 140.5.0); None for "(none)" and for Ubuntu's transitional
    package that only installs the snap (2:1snap1-0ubuntu1); esr when the candidate is an ESR."""
    def raw(label):
        m = re.search(r'^\s*' + label + r':\s*(\S+)', text or '', re.M)
        return None if not m or m.group(1) == '(none)' else re.sub(r'^\d+:', '', m.group(1))

    installed, candidate = raw('Installed'), raw('Candidate')
    return plain(installed), plain(candidate), 'esr' in (candidate or installed or '')


def newest_of_dnf_info(text):
    """The newest version "dnf info thunderbird" prints (it lists the installed and the available package), plain -
    the query task/host gives cx tool setup --status for dnf."""
    versions = [plain(v) for v in re.findall(r'^Version\s*:\s*(\S+)', text or '', re.M)]
    versions = [v for v in versions if v]
    newest = None
    for v in versions:
        if newest is None or older(newest, v):
            newest = v
    return newest


def moved_on(pinned, fresh, where):
    """The error when a package manager's refreshed lists offer another newest version than the one asked for (the one
    --status found): setup detects the tool again at the version it asked for, so nothing is installed then. None when
    they agree or either is unknown."""
    pinned, fresh = plain(pinned), plain(re.sub(r'^\d+:', '', fresh or ''))
    if not pinned or not fresh or pinned == fresh:
        return None
    return (f'{where} offer Thunderbird {fresh} now, not {pinned} as found before - nothing was installed; run the '
            f'upgrade again to get {fresh}')


def linux_kind(real_path, snap_installed, deb_version, rpm_version):
    """How this Thunderbird is installed on Linux: snap (its binary under /snap, or the snap is installed), deb or rpm
    (a real package of the distribution - not Ubuntu's transitional deb, which only installs the snap), or other (a
    tarball from Mozilla)."""
    if (real_path or '').startswith('/snap/') or snap_installed:
        return 'snap'
    if deb_version:
        return 'deb'
    if rpm_version:
        return 'rpm'
    return 'other'


def wanted_channel(params):
    """(channel asked for with --with.channel, error): esr or release, None when not asked."""
    value = str(((params or {}).get('with') or {}).get('channel') or '').strip().lower()
    if not value:
        return None, None
    if value in CHANNELS:
        return value, None
    return None, f'--with.channel is "esr" or "release", not "{value}"'


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


def install_folder(path, uname):
    """The folder of application.ini, channel-prefs.js and update-settings.ini for a Thunderbird binary: beside it
    (Windows, a tarball, /usr/lib/thunderbird), Thunderbird.app/Contents/Resources on macOS."""
    if not path:
        return None
    if uname == 'darwin':
        return os.path.join(os.path.dirname(os.path.dirname(path)), 'Resources')
    if uname == 'windows':
        return ntpath.dirname(path)                 # a Windows path, read as one on any system
    return os.path.dirname(os.path.realpath(path))


class CTool(InitCTool):
    """Mozilla Thunderbird: the system's installation, upgraded through its own channel, in its own update channel."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect_versions(self, ctx, paths, params = None):
        """The version of each Thunderbird found: application.ini beside it (Windows, macOS), its --version (Linux)."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        found = {}
        for candidate in paths:
            path = candidate[1:] if candidate.startswith('!') else candidate
            version = plain(self.version_at(path, uname))
            if version:
                found[candidate] = {'output': f'THUNDERBIRD version : {version}'}
        return {'return': 0, 'found_paths_with_versions': found}

    def version_at(self, path, uname):
        """The version of the Thunderbird at path as found (153.7.0esr, 160.0), or None: application.ini beside
        thunderbird.exe on Windows (which prints nothing to a console) and in Contents/Resources on macOS (no program is
        started there: a quarantined app waits for the user to allow its first start - a Homebrew cask's, 2026-11-17),
        else --version."""
        folder = install_folder(path, uname)
        ini = read_text(os.path.join(folder, 'application.ini')) if folder else None
        if uname in ('windows', 'darwin') and version_of_application_ini(ini):
            return version_of_application_ini(ini)
        if uname == 'windows' or (uname == 'darwin' and self.quarantined(path)):
            return None
        rc, out, _ = run([path, '--version'], 60)
        return version_of_output(out) or version_of_application_ini(ini)

    def quarantined(self, path):
        """True for a macOS app whose program would wait for Gatekeeper's question on its first start: it is not
        started by the tool."""
        app = path[:path.find('.app/') + 4] if path and '.app/' in path else path
        rc, out, _ = run(['xattr', '-p', 'com.apple.quarantine', app], 15) if app and shutil.which('xattr') else (1, '', '')
        return rc == 0 and quarantine_waits(out)

    ############################################################
    def installation(self, uname, path = None):
        """What is installed here (the system's Thunderbird, or the one at path): {path, version, channel, language,
        kind, cask, snap, apt, snap_ok, folder}; path None when Thunderbird is missing (snap and apt are still read on
        Linux: they tell what an install would get)."""
        path = path if path and os.path.isfile(path) else self.system_path(uname)
        inst = {'path': path, 'version': None, 'channel': None, 'language': None, 'kind': None, 'cask': None,
                'snap': None, 'apt': None, 'snap_ok': False, 'folder': install_folder(path, uname)}
        folder = inst['folder']
        prefs = read_text(os.path.join(folder, 'defaults', 'pref', 'channel-prefs.js')) if folder else None
        settings = read_text(os.path.join(folder, 'update-settings.ini')) if folder else None
        if path:
            inst['version'] = self.version_at(path, uname)

        if uname == 'windows':
            entry = self.windows_entry(folder) if path else None
            arp_channel, inst['language'] = arp_name_locale(entry.get('name')) if entry else (None, None)
            inst['kind'] = 'winget' if path else None
            inst['channel'] = channel_of(channel_of_prefs(prefs), channel_of_update_settings(settings), arp_channel,
                                         inst['version'])
        elif uname == 'darwin':
            brew = self.brew()
            # the cask counts for the app it installed, not for another copy (--tool_path)
            if brew and path and path == self.system_path(uname):
                # "brew list" exits with 1 when one of the casks is not installed: the lines of the others count
                rc, out, _ = run([brew, 'list', '--cask', '--versions'] + list(CASKS.values()), 120)
                for line in out.splitlines():
                    token = line.split()[0] if line.split() else ''
                    if token in CASKS.values():
                        inst['cask'] = token
            cask_channel = [c for c, t in CASKS.items() if t == inst['cask']]
            inst['kind'] = ('cask' if inst['cask'] else 'app') if path else None
            # Mozilla's app has no channel-prefs.js (its channel is in ChannelPrefs.framework) and its application.ini
            # says 153.7.0 for the ESR: the "esr" of --version tells it (Mozilla's disk image of 153.7.0esr,
            # 2026-11-17) - asked only when no cask tells the channel, and never of a quarantined app
            printed = None
            if path and not cask_channel and not self.quarantined(path):
                rc, out, _ = run([path, '--version'], 30)
                printed = version_of_output(out)
            inst['channel'] = channel_of(cask_channel[0] if cask_channel else None, channel_of_prefs(prefs),
                                         channel_of_update_settings(settings), printed) if path else None
        elif uname == 'linux':
            if shutil.which('snap'):
                rc, out, _ = run(['snap', 'info', SNAP], 60)
                if rc == 0:
                    inst['snap_ok'] = True
                    inst['snap'] = snap_info(out)
            if shutil.which('apt-cache'):
                rc, out, _ = run(['apt-cache', 'policy', PACKAGE], 60, env = {'LC_ALL': 'C'})
                if rc == 0 and out.strip():
                    installed, candidate, esr = apt_policy(out)
                    inst['apt'] = {'installed': installed, 'candidate': candidate, 'esr': esr}
            rpm_version = None
            if path and shutil.which('rpm'):
                rc, out, _ = run(['rpm', '-q', '--qf', '%{VERSION}', PACKAGE], 30)
                rpm_version = plain(out.strip()) if rc == 0 else None
            snap = inst['snap'] or {}
            if path:
                inst['kind'] = linux_kind(os.path.realpath(path), bool(snap.get('installed')),
                                          (inst['apt'] or {}).get('installed'), rpm_version)
                inst['channel'] = channel_of(snap_channel(snap.get('tracking')) if inst['kind'] == 'snap' else None,
                                             'esr' if inst['kind'] == 'deb' and inst['apt']['esr'] else None,
                                             channel_of_prefs(prefs), channel_of_update_settings(settings),
                                             inst['version'])
        return inst

    def windows_entry(self, folder):
        """The Uninstall entry of the Thunderbird in folder (its DisplayName tells the channel and the language)."""
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
                    if 'thunderbird' in str(values['DisplayName'] or '').lower():
                        entries.append({'name': values['DisplayName'], 'location': values['InstallLocation']})
        norm = lambda p: os.path.normcase(os.path.normpath(p)) if p else None
        same = [e for e in entries if folder and norm(e['location']) == norm(folder)]
        return (same or entries or [None])[0]

    ############################################################
    def latest_version(self, ctx, params):
        """The newest Thunderbird of the channel this one follows (--with.channel for a new one, else the release), as
        the system's channel gives it, so that an upgrade brings exactly that version: the snap's channel, apt's
        candidate, winget's package, Homebrew's cask; Mozilla's newest of the channel where none answers, and as a
        note when Mozilla is ahead of the system's channel."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        asked, error = wanted_channel(params)
        if error:
            return {'return': 1, 'error': error}
        # --tool_path: that copy's channel (cx tool setup thunderbird --status --tool_path=...)
        inst = self.installation(uname, (params or {}).get('tool_path'))
        channel = inst['channel'] if inst['channel'] in CHANNELS else (asked or 'release')
        notes = []
        if inst['path']:
            notes.append((f'the installed Thunderbird follows the {inst["channel"]} channel' if inst['channel'] else
                          'the installed Thunderbird does not tell its channel: the release is taken')
                         + (f' (the cask {inst["cask"]})' if inst['cask'] else ''))
            if asked and inst['channel'] and asked != inst['channel']:
                notes.append(f'--with.channel={asked} is not taken: an upgrade keeps the channel of the installed one')
            if self.running(uname):
                notes.append('Thunderbird is running: close it before an upgrade')

        version, source = None, None
        if uname == 'linux':
            snap, apt = inst['snap'] or {}, inst['apt'] or {}
            if inst['kind'] == 'snap' and snap.get('offered'):
                version, source = snap['offered'], f'the snap {SNAP} ({snap["tracking"]})'
            elif inst['kind'] == 'deb' and apt.get('candidate'):
                version, source = apt['candidate'], f'apt ({PACKAGE})'
            elif not inst['path'] and inst['snap_ok'] and (snap.get('channels') or {}).get(SNAP_CHANNELS[channel]):
                version, source = snap['channels'][SNAP_CHANNELS[channel]], f'the snap {SNAP} ({SNAP_CHANNELS[channel]})'
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
            mozilla, failed = newest_of(fetch_json(MOZILLA_VERSIONS), channel), None
        except Exception as e:
            mozilla, failed = None, f'cannot read Mozilla\'s versions ({MOZILLA_VERSIONS}): {e}'
        if version:
            if mozilla and older(version, mozilla):
                notes.append(f'Mozilla has released {mozilla} ({channel}): {source} does not offer it yet')
            return {'return': 0, 'version': version, 'source': source, 'notes': notes}
        if failed:
            return {'return': 16, 'error': failed}
        if not mozilla:
            return {'return': 16, 'error': f'no {MOZILLA_KEYS[channel]} in {MOZILLA_VERSIONS}'}
        return {'return': 0, 'version': mozilla, 'source': f'{MOZILLA_VERSIONS} ({channel})', 'notes': notes}

    def dnf_newest(self):
        """The newest Thunderbird dnf offers, as root sees it when sudo needs no password - root installs it, and a
        user's own metadata can come from another mirror (Fedora 44, 2026-11-17: 157.0 for the user, 158.0 for root) -
        else as this user."""
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
        return f'apt\'s package lists are from {when}: "sudo apt-get update" may find a newer Thunderbird'

    def running(self, uname):
        if uname == 'windows':
            rc, out, _ = run(['tasklist', '/FI', 'IMAGENAME eq thunderbird.exe', '/NH'], 30)
            return rc == 0 and 'thunderbird.exe' in out.lower()
        rc, out, _ = run(['pgrep', '-x', 'thunderbird'], 15) if shutil.which('pgrep') else (1, '', '')
        return rc == 0 and bool(out.strip())

    ############################################################
    def install(self, ctx, params, cmd = None, *misc):
        """Install Thunderbird, or bring it to the newest version of its channel, through the system's channel."""
        uname = ctx['tasks']['global']['host']['os']['uname']
        c = params.get('control', {})
        con, quiet = c.get('con', False), c.get('quiet', False)

        asked, error = wanted_channel(params)
        if error:
            return {'return': 1, 'install_cmd': None, 'error': error}
        inst = self.installation(uname)
        if inst['path'] and asked and inst['channel'] in CHANNELS and asked != inst['channel']:
            return {'return': 16, 'install_cmd': None,
                    'error': f'Thunderbird {inst["version"]} here follows the {inst["channel"]} channel: an upgrade '
                             f'does not switch it to the {asked} one (a profile is not opened by an older Thunderbird) '
                             f'- uninstall it first to change the channel'}
        channel = inst['channel'] if inst['channel'] in CHANNELS else (asked or 'release')

        wanted = str(params.get('version') or '').strip()
        if wanted and wanted != 'latest':
            r = self.latest_version(ctx, params)
            if r.get('return') == 0 and plain(r['version']) != plain(wanted):
                return {'return': 16, 'install_cmd': None,
                        'error': f'only the newest Thunderbird of its channel ({r["version"]}) is installed through '
                                 f'the system\'s channel, not {wanted}'}

        if inst['path'] and self.running(uname):
            return {'return': 16, 'install_cmd': None,
                    'error': 'Thunderbird is running: close it, then run the upgrade again'}

        pinned = wanted if wanted and wanted != 'latest' else None
        if uname == 'windows':
            r = self.windows_install(inst, channel, con)
        elif uname == 'darwin':
            r = self.mac_install(inst, channel, con)
        elif uname == 'linux':
            r = self.linux_install(inst, channel, con, quiet, pinned)
        else:
            r = {'return': 16, 'error': f'no Thunderbird install for {uname}'}
        if r['return'] > 0:
            return dict(r, install_cmd = None)

        path = self.system_path(uname)
        if not path:
            return {'return': 16, 'install_cmd': None, 'error': 'Thunderbird was installed, but it is not found'}
        return {'return': 0, 'install_cmd': None, 'found_path': path}

    def call(self, step, con, env = None):
        if con:
            print(f'INFO: {" ".join(step)}')
        return subprocess.call(step, env = dict(os.environ, **env) if env else None)

    def windows_install(self, inst, channel, con):
        """winget: upgrade the package of this channel and language; a Thunderbird winget does not link to its package
        (installed by Mozilla's own installer) is installed over by that package, in its folder."""
        winget = shutil.which('winget')
        if not winget:
            return {'return': 16, 'error': 'winget is not available'}
        package = winget_id(channel, inst['language'])
        common = ['--id', package, '-e', '--source', 'winget', '--accept-package-agreements',
                  '--accept-source-agreements', '--disable-interactivity']
        if inst['path']:
            step = [winget, 'upgrade'] + common
            rc = self.call(step, con) & 0xFFFFFFFF
            if rc == WINGET_NOT_INSTALLED:
                default = os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Mozilla Thunderbird')
                where = [] if os.path.normcase(inst['folder']) == os.path.normcase(default) else ['--location', inst['folder']]
                if con:
                    print(f'INFO: winget does not link this Thunderbird to {package}: installing that package over it')
                step = [winget, 'install'] + common + where
                rc = self.call(step, con) & 0xFFFFFFFF
        else:
            step = [winget, 'install'] + common
            rc = self.call(step, con) & 0xFFFFFFFF
        if rc not in (0, WINGET_NO_UPGRADE):
            return {'return': 16, 'error': f'"{" ".join(step)}" exited with {hex(rc)}'}
        return {'return': 0}

    def mac_install(self, inst, channel, con):
        """Homebrew: upgrade the cask that installed it; an app from Mozilla's disk image is replaced by the cask of its
        channel (the profile stays in ~/Library/Thunderbird); a missing one is installed. Without Homebrew's own
        update first, so that it installs the version "brew info" gave (setup detects the tool again at that one)."""
        brew = self.brew()
        if not brew:
            return {'return': 16, 'error': 'Homebrew is not available (cx tool setup brew)'}
        if inst['cask']:
            step = [brew, 'upgrade', '--cask', inst['cask']]
        elif inst['path']:
            step = [brew, 'install', '--cask', '--force', CASKS[channel]]
        else:
            step = [brew, 'install', '--cask', CASKS[channel]]
        rc = self.call(step, con, {'HOMEBREW_NO_AUTO_UPDATE': '1'})
        if rc != 0:
            return {'return': 16, 'error': f'"{" ".join(step)}" exited with {rc}'}
        return {'return': 0}

    def linux_install(self, inst, channel, con, quiet, pinned = None):
        """The snap (refresh, or install in the snap's channel of the channel asked), else the distribution's package
        with apt or dnf - their lists refreshed first; when the version asked for (the one --status found) is no
        longer their newest after that, nothing is installed and the error says so: setup would not find the tool
        again at the version it asked for."""
        root = os.geteuid() == 0
        sudo = [] if root else (['sudo', '-n'] if quiet else ['sudo'])
        kind, missing = inst['kind'], not inst['path']
        if kind == 'snap' or (missing and inst['snap_ok']):
            steps = [sudo + ['snap', 'refresh', SNAP]] if kind == 'snap' else \
                    [sudo + ['snap', 'install', SNAP] + (['--channel=' + SNAP_CHANNELS['esr']] if channel == 'esr' else [])]
        elif kind == 'deb' or (missing and shutil.which('apt-get')):
            apt = sudo + ['env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get']
            rc = self.call(apt + ['update'], con)
            if rc != 0:
                return {'return': 16, 'error': f'"{" ".join(apt + ["update"])}" exited with {rc}'}
            rc, out, _ = run(['apt-cache', 'policy', PACKAGE], 60, env = {'LC_ALL': 'C'})
            error = moved_on(pinned, apt_policy(out)[1] if rc == 0 else None, 'apt\'s refreshed package lists')
            if error:
                return {'return': 16, 'error': error}
            steps = [apt + ['install', '-y'] + (['--only-upgrade'] if kind == 'deb' else []) + [PACKAGE]]
        elif kind == 'rpm' or (missing and shutil.which('dnf')):
            error = moved_on(pinned, self.dnf_newest(), 'dnf\'s metadata') if pinned else None
            if error:
                return {'return': 16, 'error': error}
            steps = [sudo + ['dnf', 'upgrade' if kind == 'rpm' else 'install', '-y', PACKAGE]]
        else:
            return {'return': 16, 'error': 'this Thunderbird is not a snap, a deb or an rpm (a tarball from Mozilla '
                                           'updates itself), or no snap, apt or dnf is here: install it with the '
                                           'distribution\'s package manager'}
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
                exe = os.path.join(base, 'Mozilla Thunderbird', 'thunderbird.exe')
                if os.path.isfile(exe):
                    return exe
            entry = self.windows_entry(None)
            exe = os.path.join(entry['location'], 'thunderbird.exe') if entry and entry.get('location') else None
            return exe if exe and os.path.isfile(exe) else None
        if uname == 'darwin':
            for app in ('/Applications/Thunderbird.app', os.path.expanduser('~/Applications/Thunderbird.app')):
                exe = os.path.join(app, 'Contents', 'MacOS', 'thunderbird')
                if os.path.isfile(exe):
                    return exe
            return None
        return shutil.which('thunderbird') or ('/snap/bin/thunderbird' if os.path.exists('/snap/bin/thunderbird') else None)
