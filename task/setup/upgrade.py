"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup <tool> --status" and "cx tool setup <tool> --upgrade"
(docs/cmeta-aops/tool-abstraction.md, "Checking for and installing upgrades").

A tool reaches a machine through one *channel*: the mechanism its _desc.yaml
install_cmd (or its api_v1.py install() hook) uses on this OS - winget, brew,
the distro package manager behind {{global.host.os_extra.install_cmd_sudo}},
an upstream install script, npm, pip, or a release binary the hook downloads.
The channel decides what "latest" means for --status (the newest version that
channel can install) and what --upgrade runs (winget upgrade, brew upgrade,
apt-get install --only-upgrade, the script again, the newest release ...).

Everything is derived from keys the tools already carry, so no _desc.yaml has to
change. Two optional keys override the derivation when it is wrong for a tool:

  upgrade_cmd:                  # per OS like install_cmd - what --upgrade runs instead
    linux: 'rustup update'
  cmd_get_latest_version: 'npm view openclaw version'   # prints the newest version
  cmd_get_latest_version_regex: '(\\d+\\.\\d+\\.\\d+)'    # default: first version-like token
  cmd_get_latest_version_uses: [...]                   # set up first, as for cmd_get_versions

The helpers above the "task-bound functions" marker use only the standard library
(plus "packaging", a dependency of the engine), so
tests/cmeta_aops_basic_tests/test_tool_upgrade.py checks them offline.
"""

import os
import re
import copy
import json
import datetime

CHANNEL_WINGET  = 'winget'   # winget install --id=X ...
CHANNEL_BREW    = 'brew'     # brew install X
CHANNEL_SUDO    = 'sudo'     # {{global.host.os_extra.install_cmd_sudo}} - apt, dnf, apk, ... from task/host
CHANNEL_PIP     = 'pip'      # pip install X (the pip tool and its sub-tools)
CHANNEL_NPM     = 'npm'      # npm install -g X
CHANNEL_SCRIPT  = 'script'   # an upstream installer: curl ... | bash, irm ... | iex, install.cmd ...
CHANNEL_RELEASE = 'release'  # api_v1.py install() downloads a release binary (pinned by default)
CHANNEL_RERUN   = 'rerun'    # any other install command: run it again and let detection judge
CHANNEL_NONE    = 'none'     # detect-only tool

CHANNEL_TEXT = {
    CHANNEL_WINGET:  'winget',
    CHANNEL_BREW:    'Homebrew',
    CHANNEL_SUDO:    'the system package manager',
    CHANNEL_PIP:     'pip',
    CHANNEL_NPM:     'npm',
    CHANNEL_SCRIPT:  'the upstream install script',
    CHANNEL_RELEASE: 'the upstream release download',
    CHANNEL_RERUN:   'the install command',
    CHANNEL_NONE:    'no install procedure',
}

# Channels whose package manager can be asked for the newest version it offers
CHANNELS_WITH_OWN_LATEST = (CHANNEL_WINGET, CHANNEL_BREW, CHANNEL_SUDO)

# Install verbs with an upgrade counterpart, for commands that are run again by --upgrade
VERB_SWAPS = [
    (r'\bsnap\s+install\b', 'snap refresh'),
    (r'\brustup\s+toolchain\s+install\b', 'rustup update'),
]

SETUP_TASK = 'setup,a2f9b61079ce4333'
CMD_TASK = 'cmd,c9ba0a88df394d7f'
CACHE_CATEGORY = 'cache,1ebdcc1cc30c4022'
WINGET_TOOL = 'winget,4a6b40ba0d4d49fb'
BREW_TOOL = 'brew,27859c999bdd4085'

# winget exit codes that mean "nothing to do", not "failed": UPDATE_NOT_APPLICABLE ("No available
# upgrade found") and PACKAGE_ALREADY_INSTALLED - as the unsigned HRESULT and as Python may report it
WINGET_NOTHING_TO_DO = {0x8A15002B, 0x8A150011, 0x8A15002B - 2**32, 0x8A150011 - 2**32}

VERSION_LIKE = r'(\d+(?:\.\d+)+[\w.\-+]*)'

# Where an upstream version came from when it is not the release GitHub marks as latest
TAGS_SOURCE = 'the newest release among the upstream tags (cmd_get_versions)'


###################################################################################################
# Pure helpers (no cMeta, no network) - unit-tested offline

def select_for_os(value, uname):
    """
    Pick the entry of a per-OS dict (install_cmd, upgrade_cmd, ...) the way
    task/setup/install.py does: "all" wins, then the OS key, and a non-Windows OS
    without its own key falls back to "linux".
    """
    if not value:
        return None
    if isinstance(value, str):
        return value
    if 'all' in value:
        return value['all']
    os_key = uname if (uname == 'windows' or uname in value) else 'linux'
    return value.get(os_key)


def split_version(version):
    """The version_pip / version_simple / version_major trio that setup hands to install() and detect()."""
    if not version:
        return {}

    version_pip = '==' + version if version[0].isdigit() else version
    version_simple = version
    version_major = None

    for k in ['>', '<', '*', '?']:
        if k in version:
            version_simple = None
            break

    if version_simple:
        if version_simple.startswith('=='):
            version_simple = version_simple[2:]
        version_major = version_simple
        j = version_major.find('.')
        if j > 0:
            version_major = version_major[:j]

    return {'version_pip': version_pip, 'version_simple': version_simple, 'version_major': version_major}


def winget_package_id(cmd):
    """'SST.opencode' from 'winget install --id=SST.opencode -e ...' or 'winget install 7zip.7zip -e ...'."""
    m = re.search(r'--id[=\s]+"?([^\s"]+)', cmd)
    if m:
        return m.group(1)
    m = re.search(r'\b(?:install|upgrade)\s+(.*)$', cmd)
    if m:
        for token in m.group(1).split():
            if not token.startswith('-'):
                return token.strip('"\'')
    return None


def brew_formula(cmd):
    """
    ('gh', False) from 'brew install gh'; ('obsidian', True) from 'brew install --cask obsidian'.
    The last "install" counts, so 'brew update && brew install X' gives X.
    """
    head, sep, tail = cmd.rpartition('install')
    if not sep:
        return None, False
    cask = '--cask' in tail
    for token in tail.split():
        if not token.startswith('-'):
            return token.strip('"\''), cask
    return None, cask


def npm_package(cmd):
    """'openclaw' from 'npm install -g openclaw'; a scoped '@org/pkg' keeps its scope."""
    m = re.search(r'\bnpm\s+(?:install|i|add)\s+(.*)$', cmd)
    if not m:
        return None
    for token in m.group(1).split():
        if token.startswith('-'):
            continue
        token = token.strip('"\'')
        if token.startswith('@'):
            return '@' + token[1:].split('@')[0]
        return token.split('@')[0]
    return None


def derive_channel(install_cmd):
    """
    (channel, package) of one install command template. The package is the winget
    id, the brew formula, "{{name}}" for the system package manager (resolved by the
    caller the way install.py does), the npm package, or None.
    """
    cmd = (install_cmd or '').strip()
    if not cmd:
        return CHANNEL_NONE, None

    low = cmd.lower()

    if 'global.winget.qpath' in low or re.search(r'(^|[\s"&;(])winget(\.exe)?\s', low):
        return CHANNEL_WINGET, winget_package_id(cmd)

    if 'global.brew.qpath' in low or re.search(r'\bbrew\s+install\b', low):
        return CHANNEL_BREW, brew_formula(cmd)[0]

    if 'install_cmd_sudo' in low:
        return CHANNEL_SUDO, '{{name}}'

    if 'global.pip.cmd' in low or re.search(r'\bpip3?(?:\.exe)?\s+install\b', low) or re.search(r'-m\s+pip\s+install\b', low):
        return CHANNEL_PIP, None

    if re.search(r'\bnpm\s+(?:install|i|add)\b', low):
        return CHANNEL_NPM, npm_package(cmd)

    if re.search(r'\|\s*(?:ba|z)?sh\b|\|\s*iex\b|\binstall\.(?:sh|cmd|ps1|bat)\b', low):
        return CHANNEL_SCRIPT, None

    return CHANNEL_RERUN, None


def derive_upgrade_cmd(channel, install_cmd, versioned = False):
    """
    The command --upgrade runs for a declarative channel, from the (possibly already
    versioned) install command. When a specific version was asked for, the versioned
    install command is kept - package managers change versions through "install" -
    except that winget's --no-upgrade must go in any case.
    """
    cmd = install_cmd

    if channel == CHANNEL_WINGET:
        cmd = re.sub(r'\s--no-upgrade\b', '', cmd)
        if not versioned:
            cmd = re.sub(r'\binstall\b', 'upgrade', cmd, count = 1)
        return cmd

    if channel == CHANNEL_BREW and not versioned:
        head, sep, tail = cmd.rpartition('install')
        return head + 'upgrade' + tail if sep else cmd

    if channel == CHANNEL_SUDO and not versioned:
        return cmd.replace('install_cmd_sudo', 'upgrade_cmd_sudo')

    if channel == CHANNEL_NPM and not versioned:
        package = npm_package(cmd)
        if package and '@' not in package.lstrip('@'):
            cmd = re.sub(r'(\s["\']?)' + re.escape(package) + r'(["\']?)(\s|$)',
                         r'\g<1>' + package + r'@latest\g<2>\g<3>', cmd, count = 1)
        return cmd

    for pattern, replacement in VERB_SWAPS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return re.sub(pattern, replacement, cmd, count = 1, flags = re.IGNORECASE)

    return cmd


def normalize_pkg_version(version):
    """
    Strip what distro package managers add around the upstream version:
    '1:2.53.0-1ubuntu1' -> '2.53.0', '2.45.2-r0' -> '2.45.2', '2.47.0-1' -> '2.47.0',
    '2.1.5+ds-0ubuntu0.2' -> '2.1.5'. Pre-releases such as '2.0.0-rc1' and local
    parts such as '25.0.2+10' are kept.
    """
    v = (version or '').strip()
    v = re.sub(r'^\d+:', '', v)
    v = re.sub(r'\+(?:deb|dfsg|ds|ubuntu|really)\S*$', '', v)
    m = re.match(r'^(\d+(?:\.\d+)*)-r?\d\S*$', v)
    if m:
        v = m.group(1)
    return v


def parse_version(version):
    """A comparable packaging Version, or None. Suffixes such as '2.49.0.windows.1' become local parts."""
    v = normalize_pkg_version(version)
    if not v:
        return None

    try:
        from packaging.version import Version
    except ImportError:  # pragma: no cover
        return None

    candidates = [v, re.sub(r'\.(windows|linux|darwin|macos|win|mac|unix)(\.|$)', r'+\1\2', v, flags = re.IGNORECASE)]
    m = re.match(r'(\d+(?:\.\d+)*)', v)
    if m:
        candidates.append(m.group(1))

    for candidate in candidates:
        try:
            return Version(candidate)
        except Exception:
            pass

    return None


def is_prerelease(version):
    """True for rc, alpha, beta, dev, nightly ... versions."""
    v = parse_version(version)
    if v is not None:
        return v.is_prerelease or v.is_devrelease
    return bool(re.search(r'(alpha|beta|rc|dev|nightly|canary|preview|snapshot)', version or '', re.IGNORECASE))


def pick_latest(versions):
    """
    The newest release in a list (in any order): pre-releases are skipped, and
    unparseable versions are considered only when nothing parses.
    """
    best, best_v, fallback = None, None, None
    for s in versions or []:
        if not s:
            continue
        v = parse_version(s)
        if v is None:
            if fallback is None:
                fallback = s
            continue
        if v.is_prerelease or v.is_devrelease:
            continue
        if best_v is None or v > best_v:
            best, best_v = s, v
    return best if best is not None else fallback


def version_verdict(installed, latest):
    """
    'not-installed', 'unknown', 'outdated', 'up-to-date' or 'newer' (installed is ahead
    of the channel, e.g. a script install next to an older winget manifest). Local parts
    are ignored, so git's '2.49.0.windows.1' is up to date against winget's '2.49.0'.
    """
    if not installed:
        return 'not-installed'
    if not latest:
        return 'unknown'

    a, b = parse_version(installed), parse_version(latest)
    if a is None or b is None:
        return 'up-to-date' if normalize_pkg_version(installed) == normalize_pkg_version(latest) else 'unknown'

    from packaging.version import Version
    a, b = Version(a.public), Version(b.public)

    if a < b:
        return 'outdated'
    if a > b:
        return 'newer'
    return 'up-to-date'


def github_repo_from_cmd(cmd):
    """'anomalyco/opencode' from 'git ls-remote --tags https://github.com/anomalyco/opencode'."""
    m = re.search(r'github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?=[\s/"\'`]|$)', cmd or '')
    return f'{m.group(1)}/{m.group(2)}' if m else None


def version_from_tag(tag, regex = None, group = 1):
    """
    Apply a tool's cmd_get_versions_regex (written for "git ls-remote --tags" lines) to
    one tag. With a regex, a tag it does not match is not one of the tool's versions
    (llama.cpp numbers its builds b11322 while GitHub marks a "v0.5.0" release as latest)
    and None is returned; without one, the first version-like token of the tag.
    """
    line = f'refs/tags/{tag}'
    if regex:
        m = re.search(regex, line)
        if not m:
            return None
        try:
            v = m.group(group or 1)
        except IndexError:
            return None
        return v or None
    m = re.search(VERSION_LIKE, tag)
    return m.group(1) if m else None


def github_latest_release_tag(owner_repo, timeout = 15):
    """
    The tag of the newest release GitHub marks as latest (pre-releases excluded), from
    the redirect of /releases/latest - no API call, no rate limit. None when the repo
    has no such release or is unreachable.
    """
    import urllib.request
    import urllib.parse

    url = f'https://github.com/{owner_repo}/releases/latest'
    try:
        request = urllib.request.Request(url, method = 'HEAD', headers = {'User-Agent': 'cmeta-aops'})
        with urllib.request.urlopen(request, timeout = timeout) as response:
            final = response.geturl()
    except Exception:
        return None

    m = re.search(r'/releases/tag/([^/?#]+)', final)
    return urllib.parse.unquote(m.group(1)) if m else None


def parse_winget_versions(output):
    """The newest version in "winget show --versions" output: the first line after the dashes."""
    lines = [l.strip() for l in (output or '').splitlines()]
    after_rule = False
    for l in lines:
        if re.match(r'^-{3,}$', l):
            after_rule = True
            continue
        if after_rule and l:
            return l.split()[0]
    for l in lines:
        if re.match(r'^\d[\w.\-+]*$', l):
            return l
    return None


def parse_candidate_versions(output, regex):
    """
    All versions a package-manager query printed (group 1 of the regex), so the caller
    can take the newest: "dnf info" prints the installed and the available package.
    """
    found = []
    for m in re.finditer(regex, output or '', re.MULTILINE):
        v = m.group(1).strip().rstrip(':')
        if v and v.lower() not in ('(none)', 'none') and v not in found:
            found.append(v)
    return found


def guess_channel_from_path(path, uname = None):
    """
    Where an installed copy most likely came from, judged by its (resolved) path -
    so --status compares a brew-installed gh with brew even if the tool's install
    command on this OS is something else. None when the path says nothing.
    """
    if not path:
        return None

    candidates = [path]
    try:
        real = os.path.realpath(path)
        if real and real != path:
            candidates.append(real)
    except Exception:
        pass

    for p in candidates:
        p = p.replace('\\', '/').lower()
        if '/cache/task--setup--' in p:
            return CHANNEL_RELEASE
        if '/microsoft/winget/' in p:
            return CHANNEL_WINGET
        if '/cellar/' in p or '/caskroom/' in p or '/opt/homebrew/' in p or '/.linuxbrew/' in p:
            return CHANNEL_BREW
        if '/node_modules/' in p or '/appdata/roaming/npm/' in p:
            return CHANNEL_NPM
        if '/site-packages/' in p or re.search(r'/(venv|\.venv|virtualenvs)/', p):
            return CHANNEL_PIP
        if re.search(r'/\.(local|opencode|claude|codex|cargo|rustup|swiftly)/', p):
            return CHANNEL_SCRIPT
        if re.match(r'^/(usr/)?s?bin/', p) or re.match(r'^/usr/(lib|libexec|share)/', p) or p.startswith('/snap/'):
            return CHANNEL_SUDO

    return None


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec = 'seconds')


def cached_tool_path(cache_dir):
    """
    The tool a cache entry of setup points to (its _cmeta.json params.tool_path), when
    the entry and the file exist - what "cx tool setup <tool>" replays before it looks
    at the PATH, so what --upgrade must upgrade.
    """
    meta_file = os.path.join(cache_dir or '', '_cmeta.json')
    if not os.path.isfile(meta_file):
        return None
    try:
        with open(meta_file, 'r', encoding = 'utf-8') as f:
            meta = json.load(f)
    except Exception:
        return None
    tool_path = (meta.get('params') or {}).get('tool_path')
    if tool_path and os.path.isfile(tool_path) and 'tmp' not in (meta.get('tags') or []):
        return tool_path
    return None


###################################################################################################
# Task-bound functions (self is the setup CTask; attached in api_v1.py)

def _run_capture(self, ctx, cmd, env = None, timeout = 120):
    """Run a command through task/cmd with its output captured; a non-zero exit is reported, not raised."""
    ii = {'category': self.category_alias + ',' + self.category_uid,
          'command': 'run',
          'ctx': ctx,
          'arg1': CMD_TASK,
          'cmd': cmd,
          'env': env or {},
          'timeout': timeout,
          'con': False,
          'verbose': False,
          'text_cmd': 'RUN:',
          'fail_if_nonzero_return_code': False,
          'capture_output': True,
    }

    r = self.cm.access(ii)
    if r['return'] > 0:
        return r

    output = (r.get('stdout') or '') + '\n' + (r.get('stderr') or '')

    return {'return': 0, 'returncode': r.get('returncode', 1), 'output': output.replace('\r', '\n')}


def _use(self, ctx, uses, never_install = False, con = False):
    """
    Set up the tools a query needs (git for ls-remote, winget, brew ...). With
    never_install, only what is already on the machine is used: --status must not
    install anything, so a missing tool makes the answer "unknown" instead.
    """
    if not uses:
        return {'return': 0}

    desc = copy.deepcopy(uses)
    if never_install:
        for u in desc:
            u.setdefault('skip_install', True)
            u.setdefault('skip_build', True)

    control = ctx['control']

    ii = {'category': self.category_alias + ',' + self.category_uid,
          'command': 'use',
          'con': con,
          'quiet': True if not con else control.get('quiet', False),
          'verbose': control.get('verbose', False) if con else False,
          'ctx': ctx,
          'desc': desc,
          'local': {},
          'task_artifact_alias': self.artifact_alias,
          'task_artifact_uid': self.artifact_uid,
          'task_artifact_path': self.artifact_path,
    }

    return self.cm.access(ii)


def _quiet_control(ctx):
    """Silence the engine for a sub-step and return what to restore with _restore_control."""
    saved = dict(ctx['control'])
    ctx['control']['con'] = False
    ctx['control']['quiet'] = True
    ctx['control']['verbose'] = False
    return saved


def _restore_control(ctx, saved):
    ctx['control'].clear()
    ctx['control'].update(saved)


def cached_tools(self, ctx, alias):
    """
    The cache entries setup has for this tool, newest version first - "cx tool setup
    <tool>" replays the newest of them before it looks at the PATH, so --status lists
    them first. Entries whose tool is gone are left out (the engine drops them too).
    """
    ii = {'category': CACHE_CATEGORY,
          'command': 'find',
          'tags': ['task', self.category_uid, self.artifact_alias, self.artifact_uid],
          'match': {'params': {'name': alias}},
          'match_empty_version': True,
    }

    r = self.cm.access(ii)
    if r['return'] > 0:
        return []

    found = []
    for artifact in r.get('artifacts', []):
        cmeta = artifact.get('cmeta', {})
        if 'tmp' in cmeta.get('tags', []):
            continue
        params = cmeta.get('params', {})
        tool_path = params.get('tool_path')
        if not tool_path or not os.path.isfile(tool_path):
            continue
        found.append({'path': os.path.normpath(tool_path),
                      'version': params.get('version'),
                      'cache_path': artifact.get('path'),
                      'cache': True})

    found.sort(key = lambda x: self.cm.utils.common.build_sort_key(x, ['@version-']))

    return found


def _install_uses(self, ctx, desc):
    """The tools an install (and so an upgrade) needs on this OS: setup's common ones plus the tool's own."""
    uname = ctx['tasks']['global']['host']['os']['uname']

    uses = []
    if not desc.get('skip_common_install_uses', False):
        uses += select_for_os(self.cdesc.get('install_uses'), uname) or []
    uses += select_for_os(desc.get('install_uses'), uname) or []

    return uses


def resolve_package_name(self, ctx, desc, tool_read, params, call_hook = False):
    """The package {{name}} stands for in install commands - the choice task/setup/install.py makes."""
    host = ctx['tasks']['global']['host']
    os_id = host.get('os_extra', {}).get('id')

    name = tool_read['artifact_au']
    if 'package_name_os_id' in desc and os_id in desc['package_name_os_id']:
        name = desc['package_name_os_id'][os_id]
    elif 'package_name' in desc:
        name = desc['package_name']

    if call_hook:
        # 7z and xz pick the distro package in this hook
        code = tool_read['tool_api_code']
        if hasattr(code, 'customize_install_cmd') and callable(getattr(code, 'customize_install_cmd')):
            try:
                r = code.customize_install_cmd(ctx, '', copy.deepcopy(params), {}, None, None)
                if r.get('return', 0) == 0 and r.get('package_name'):
                    name = r['package_name']
            except Exception:
                pass

    return name


def describe_channels(self, ctx, desc, tool_read, params):
    """
    How this tool is installed on this OS: the primary channel (the install() hook
    when there is one), the declared install_cmd channel (the fallback of a hook, or
    the primary itself), its package, and the brew cask flag.
    """
    uname = ctx['tasks']['global']['host']['os']['uname']
    code = tool_read['tool_api_code']

    has_custom_install = hasattr(code, 'install') and callable(getattr(code, 'install'))

    install_cmd = select_for_os(desc.get('install_cmd'), uname)
    declared, package = derive_channel(install_cmd)
    cask = brew_formula(install_cmd)[1] if declared == CHANNEL_BREW else False

    if package == '{{name}}' or (declared == CHANNEL_SUDO and not package):
        package = self.resolve_package_name(ctx, desc, tool_read, params, call_hook = (declared == CHANNEL_SUDO))

    primary = CHANNEL_RELEASE if has_custom_install else declared

    return {'primary': primary,
            'declared': declared,
            'package': package,
            'cask': cask,
            'install_cmd': install_cmd,
            'has_custom_install': has_custom_install,
            'upgrade_cmd': select_for_os(desc.get('upgrade_cmd'), uname)}


def list_versions(self, ctx, desc, params, never_install = False):
    """
    The versions a tool publishes, newest first - the "cx tool setup <tool> --versions"
    machinery: cmd_get_versions after its cmd_get_versions_uses, parsed with the
    "Available versions:" convention of pip, cmd_get_versions_regex, or one per line.
    """
    ctx_tasks = ctx['tasks']

    cmd_versions = desc.get('cmd_get_versions')
    if not cmd_versions:
        return {'return': 16, 'error': 'no cmd_get_versions in the tool description'}

    r = self._use(ctx, desc.get('cmd_get_versions_uses'), never_install = never_install)
    if r['return'] > 0:
        return r

    r = self.cm.utils.common.expand_string(cmd_versions, ctx_tasks)
    if self.cm.catch_error(r): return r
    cmd_versions = r['string']

    rx = self._run_capture(ctx, cmd_versions, params.get('env'), params.get('timeout') or 120)
    if rx['return'] > 0:
        return rx

    if self.cm.debug:
        print ('=' * 60)
        print ('Output of versions detection:')
        print ('')
        print (rx['output'])
        print ('=' * 60)

    if rx['returncode'] > 0:
        return self.cm.error(f'failed to get versions ({cmd_versions}):\n{rx["output"].strip()}')

    output = rx['output']
    versions = []

    j = output.find('Available versions:')
    if j >= 0:
        # pip
        sversions = output[j + 19:].strip()
        j = sversions.find('\n')
        if j > 0:
            sversions = sversions[:j].strip()
        versions = self.cm.utils.common.split_clean(sversions, ',')
    elif desc.get('cmd_get_versions_regex'):
        regex = desc['cmd_get_versions_regex']
        group = desc.get('cmd_get_versions_regex_group') or 1
        for s in output.splitlines():
            match = re.search(regex, s)
            if match:
                v = match.group(group)
                if v not in versions:
                    versions.append(v)
    else:
        versions = [s for s in output.splitlines() if s.strip()]

    if versions:
        dversions = sorted([{'version': x} for x in versions],
                           key = lambda v: self.cm.utils.common.build_sort_key(v, ['@version-']))
        versions = [dv['version'] for dv in dversions]

    return {'return': 0, 'versions': versions}


def find_latest(self, ctx, desc, tool_read, params, channels, query_channel = None, never_install = True):
    """
    The newest version this tool can get: through its channel (winget's source, the
    brew formula, the distro candidate) and upstream (the release GitHub marks as
    latest, else the newest non-pre-release tag or index entry of cmd_get_versions).

    Returns channel_version/channel_source, upstream_version/upstream_source (None
    when unknown) and notes explaining the gaps. Nothing here installs anything when
    never_install is set, and nothing fails: an unreachable source is a note.
    """
    ctx_tasks = ctx['tasks']
    host = ctx_tasks['global']['host']
    uname = host['os']['uname']

    result = {'return': 0,
              'channel_version': None, 'channel_source': None,
              'upstream_version': None, 'upstream_source': None,
              'notes': []}
    notes = result['notes']

    timeout = params.get('timeout') or 120
    env = params.get('env')

    package = channels.get('package')
    if query_channel is None:
        query_channel = channels['declared']

    # 1. The tool's own answer
    cmd_latest = desc.get('cmd_get_latest_version')
    if cmd_latest:
        r = self._use(ctx, desc.get('cmd_get_latest_version_uses'), never_install = never_install)
        if r['return'] > 0:
            notes.append(f'cmd_get_latest_version needs a tool that is not available ({r.get("error")})')
        else:
            r = self.cm.utils.common.expand_string(cmd_latest, ctx_tasks)
            if self.cm.catch_error(r): return r
            rx = self._run_capture(ctx, r['string'], env, timeout)
            if rx['return'] > 0: return rx
            regex = desc.get('cmd_get_latest_version_regex') or VERSION_LIKE
            group = desc.get('cmd_get_latest_version_regex_group') or 1
            m = re.search(regex, rx['output'], re.MULTILINE) if rx['returncode'] == 0 else None
            if m:
                result['upstream_version'] = m.group(group)
                result['upstream_source'] = 'cmd_get_latest_version'
            else:
                notes.append(f'cmd_get_latest_version gave no version (return code {rx["returncode"]})')

    # 2. The channel's own view
    if query_channel == CHANNEL_WINGET and package:
        if uname != 'windows':
            notes.append('winget is only available on Windows')
        else:
            r = self._use(ctx, [{'task': SETUP_TASK, 'name': WINGET_TOOL}], never_install = True)
            if r['return'] > 0:
                notes.append('winget is not available')
            else:
                winget = ctx_tasks['global'].get('winget', {}).get('qpath') or 'winget'
                cmd = f'{winget} show --id={package} -e --source winget --versions --accept-source-agreements --disable-interactivity'
                rx = self._run_capture(ctx, cmd, env, timeout)
                if rx['return'] > 0: return rx
                v = parse_winget_versions(rx['output']) if rx['returncode'] == 0 else None
                if v:
                    result['channel_version'] = v
                    result['channel_source'] = f'winget ({package})'
                else:
                    notes.append(f'winget has no package {package} in the winget source (return code {rx["returncode"]})')

    elif query_channel == CHANNEL_BREW and package:
        r = self._use(ctx, [{'task': SETUP_TASK, 'name': BREW_TOOL}], never_install = True)
        if r['return'] > 0:
            notes.append('Homebrew is not available')
        else:
            brew = ctx_tasks['global'].get('brew', {}).get('qpath') or 'brew'
            kind = '--cask' if channels.get('cask') else '--formula'
            rx = self._run_capture(ctx, f'{brew} info --json=v2 {kind} {package}', env, timeout)
            if rx['return'] > 0: return rx
            v = None
            if rx['returncode'] == 0:
                try:
                    data = json.loads(rx['output'][rx['output'].find('{'):rx['output'].rfind('}') + 1])
                    if channels.get('cask'):
                        v = (data.get('casks') or [{}])[0].get('version')
                    else:
                        v = ((data.get('formulae') or [{}])[0].get('versions') or {}).get('stable')
                except Exception:
                    v = None
            if v:
                result['channel_version'] = v
                result['channel_source'] = f'Homebrew ({package})'
            else:
                notes.append(f'Homebrew has no {kind[2:]} {package} (return code {rx["returncode"]})')

    elif query_channel == CHANNEL_SUDO and package:
        os_extra = host.get('os_extra', {})
        pm = os_extra.get('package_manager')
        cmd = os_extra.get('candidate_version_cmd')
        regex = os_extra.get('candidate_version_regex')
        if not cmd or not regex:
            notes.append(f'no query for the newest package version with {pm or "this package manager"}')
        else:
            rx = self._run_capture(ctx, cmd.replace('{{name}}', package), env, timeout)
            if rx['return'] > 0: return rx
            v = pick_latest(parse_candidate_versions(rx['output'], regex)) if rx['returncode'] == 0 else None
            if v:
                result['channel_version'] = v
                result['channel_source'] = f'{pm} ({package})'
            else:
                notes.append(f'{pm} knows no package {package} (return code {rx["returncode"]}); the package index may need a refresh')

    # 3. Upstream
    if result['upstream_version'] is None:
        cmd_versions = desc.get('cmd_get_versions')
        repo = github_repo_from_cmd(cmd_versions) if cmd_versions else None

        if repo:
            tag = github_latest_release_tag(repo)
            if tag:
                v = version_from_tag(tag, desc.get('cmd_get_versions_regex'), desc.get('cmd_get_versions_regex_group') or 1)
                if v:
                    result['upstream_version'] = v
                    result['upstream_source'] = f'https://github.com/{repo}/releases/latest'
                else:
                    notes.append(f'the GitHub release marked latest ("{tag}") is not one of this tool\'s versions; using tags')
            else:
                notes.append(f'github.com/{repo} has no release marked latest (or is unreachable); using tags')

        if result['upstream_version'] is None and cmd_versions:
            r = self.list_versions(ctx, desc, params, never_install = never_install)
            if r['return'] > 0:
                notes.append(f'cmd_get_versions failed ({r.get("error", "").strip().splitlines()[0] if r.get("error") else r["return"]})')
            elif r.get('versions'):
                v = pick_latest(r['versions'])
                if v:
                    result['upstream_version'] = v
                    result['upstream_source'] = TAGS_SOURCE
            else:
                notes.append('cmd_get_versions listed no versions')

        if result['upstream_version'] is None and not cmd_versions and not cmd_latest:
            notes.append('the tool has no cmd_get_versions or cmd_get_latest_version, so upstream versions are unknown')

    return result


def _detect_kwargs(self, params, tool_read):
    """The keyword arguments detect_existing_tool() expects, from the user params of a setup run."""
    skip = ('status', 'upgrade', 'detect', 'install', 'build', 'versions', 'version_check',
            'skip_detect', 'skip_install', 'skip_build', 'skip_install_uses', 'skip_build_uses',
            'custom_install', 'custom_build', 'ignore_install_errors', 'ignore_build_errors',
            'here')

    kwargs = {k: v for k, v in params.items() if k not in skip}
    kwargs['tool_read'] = tool_read
    kwargs['task_desc'] = self.cdesc
    kwargs['task_extra_control'] = {'clean': False, 'update': False, 'new': False}
    kwargs.update(split_version(params.get('version')))
    kwargs.setdefault('env', {})
    if not kwargs.get('timeout'):
        kwargs['timeout'] = 60

    return kwargs


def status_tool(self, ctx, params, tool_read):
    """
    "cx tool setup <tool> --status": what is installed (every copy found, the one
    setup would select first), through which channel, what the newest version is
    there and upstream, and the verdict. Prints a short report and returns it as
    result['status']. Installs nothing, writes nothing.
    """
    con = ctx['control'].get('con', False)

    desc = tool_read['desc']
    name = tool_read['artifact_print_name']
    alias = tool_read['artifact_au']
    space = tool_read['space']

    host = ctx['tasks']['global']['host']
    uname = host['os']['uname']

    channels = self.describe_channels(ctx, desc, tool_read, params)

    # What is installed: the cache entries setup replays first, then every copy on the
    # PATH - found without the selection prompt and without noise
    cached = self.cached_tools(ctx, alias) if not params.get('tool_path') else []

    kwargs = self._detect_kwargs(params, tool_read)
    saved = _quiet_control(ctx)
    try:
        r = self.detect_existing_tool(ctx, **kwargs)
    finally:
        _restore_control(ctx, saved)

    if r['return'] > 0 and r['return'] not in (1, 16):
        return r

    detected = list(cached)
    if r['return'] == 0:
        for d in r.get('detected') or [{'path': r.get('path'), 'version': r.get('version')}]:
            same = [c for c in detected if os.path.normcase(os.path.normpath(c['path'])) == os.path.normcase(os.path.normpath(d['path']))]
            if same:
                same[0]['on_path'] = True
            else:
                detected.append({'path': d['path'], 'version': d['version'], 'on_path': True})

    installed = len(detected) > 0
    path = detected[0]['path'] if installed else None
    version = detected[0]['version'] if installed else None

    installed_channel = guess_channel_from_path(path, uname) if installed else None

    # Which channel's "latest" the verdict uses: the one the installed copy came from
    # when the tool is installed that way too (we know the package then), else the
    # declared one, else upstream for release downloads and scripts
    verdict_channel = channels['primary']
    if installed_channel in CHANNELS_WITH_OWN_LATEST and installed_channel == channels['declared']:
        verdict_channel = installed_channel
    elif installed_channel and installed_channel != channels['primary'] and installed_channel != channels['declared']:
        verdict_channel = CHANNEL_RELEASE if installed_channel == CHANNEL_RELEASE else installed_channel

    query_channel = channels['declared'] if channels['declared'] in CHANNELS_WITH_OWN_LATEST else None

    saved = _quiet_control(ctx)
    try:
        rl = self.find_latest(ctx, desc, tool_read, params, channels, query_channel = query_channel, never_install = True)
    finally:
        _restore_control(ctx, saved)
    if self.cm.catch_error(rl): return rl

    notes = rl['notes']

    if verdict_channel in CHANNELS_WITH_OWN_LATEST and rl['channel_version']:
        latest, latest_source = rl['channel_version'], rl['channel_source']
    elif rl['upstream_version'] and verdict_channel not in CHANNELS_WITH_OWN_LATEST:
        latest, latest_source = rl['upstream_version'], rl['upstream_source']
    elif rl['channel_version']:
        latest, latest_source = rl['channel_version'], rl['channel_source']
    else:
        latest, latest_source = rl['upstream_version'], rl['upstream_source']

    if installed and installed_channel and installed_channel != channels['primary'] and installed_channel != channels['declared'] \
            and channels['primary'] not in (CHANNEL_RERUN, CHANNEL_NONE) and installed_channel != alias:
        notes.append(f'the copy that is used seems to come from {CHANNEL_TEXT.get(installed_channel, installed_channel)}, '
                     f'while this tool is installed here through {CHANNEL_TEXT[channels["primary"]]}')

    verdict = version_verdict(version, latest) if installed else 'not-installed'

    # What --upgrade would run
    upgrade_cmd = None
    if channels['upgrade_cmd']:
        upgrade_cmd = channels['upgrade_cmd']
    elif channels['primary'] == CHANNEL_RELEASE:
        upgrade_cmd = f'download of the newest release ({rl["upstream_version"] or "unknown"})'
        if channels['declared'] not in (CHANNEL_NONE, CHANNEL_RERUN) and channels['install_cmd']:
            upgrade_cmd += ', else ' + derive_upgrade_cmd(channels['declared'], channels['install_cmd'])
    elif channels['declared'] != CHANNEL_NONE and channels['install_cmd']:
        upgrade_cmd = derive_upgrade_cmd(channels['declared'], channels['install_cmd'])
    if upgrade_cmd and '{{' in upgrade_cmd:
        # The command refers to the tools the install needs (curl, winget, brew ...): set
        # up the ones already on the machine so the command can be shown expanded
        saved = _quiet_control(ctx)
        try:
            self._use(ctx, self._install_uses(ctx, desc), never_install = True)
        finally:
            _restore_control(ctx, saved)
        r = self.cm.utils.common.expand_string(upgrade_cmd, ctx['tasks'])
        if r['return'] == 0:
            upgrade_cmd = r['string'].replace('{{name}}', channels['package'] or alias)

    status = {'name': alias,
              'os': uname,
              'installed': installed,
              'path': path,
              'version': version,
              'detected': detected,
              'channel': channels['primary'],
              'declared_channel': channels['declared'],
              'installed_channel': installed_channel,
              'package': channels['package'],
              'latest_version': latest,
              'latest_source': latest_source,
              'channel_version': rl['channel_version'],
              'channel_source': rl['channel_source'],
              'upstream_version': rl['upstream_version'],
              'upstream_source': rl['upstream_source'],
              'verdict': verdict,
              'upgrade_cmd': upgrade_cmd,
              'notes': notes}

    if con:
        channel_text = CHANNEL_TEXT[channels['primary']]
        if channels['package'] and channels['primary'] in CHANNELS_WITH_OWN_LATEST:
            channel_text += f' ({channels["package"]})'
        elif channels['primary'] == CHANNEL_RELEASE and channels['declared'] not in (CHANNEL_NONE, CHANNEL_RERUN):
            channel_text += f', else {CHANNEL_TEXT[channels["declared"]]}'

        print ('')
        print (f'{space}Tool "{name}" on {uname}:')
        print ('')
        if installed:
            label = 'installed:'
            for d in detected:
                mark = ''
                if d.get('cache'):
                    mark += '   (cached by setup)'
                if len(detected) > 1 and d['path'] == path:
                    mark += '   <- used by setup'
                print (f'{space}  {label} {str(d["version"]):<14} {d["path"]}{mark}')
                label = ' ' * 10
        else:
            print (f'{space}  installed: -')
        print (f'{space}  channel:   {channel_text}')
        if rl['channel_version']:
            print (f'{space}  latest:    {rl["channel_version"]:<14} via {rl["channel_source"]}')
        if rl['upstream_version']:
            print (f'{space}  upstream:  {rl["upstream_version"]:<14} {rl["upstream_source"]}')
        if upgrade_cmd:
            print (f'{space}  upgrade:   {upgrade_cmd}')
        for n in notes:
            print (f'{space}  note:      {n}')
        print ('')

        upstream_sources = latest_source and (str(latest_source).startswith('http') or latest_source == TAGS_SOURCE)
        via = ' upstream' if upstream_sources else (f' via {latest_source}' if latest_source else '')
        upstream_ahead = (rl['upstream_version'] and latest and rl['upstream_version'] != latest and
                          version_verdict(latest, rl['upstream_version']) == 'outdated')

        if verdict == 'not-installed':
            text = 'not installed'
            if latest:
                text += f' - the newest version available{via} is {latest}; "cx tool setup {alias} --upgrade" installs it'
        elif verdict == 'up-to-date':
            text = f'up to date - {version} is the newest version available{via}'
            if upstream_ahead:
                text += f' (upstream has {rl["upstream_version"]}, not yet in {CHANNEL_TEXT.get(verdict_channel, verdict_channel)})'
        elif verdict == 'outdated':
            text = f'outdated - {latest} is available{via} (installed: {version}); run "cx tool setup {alias} --upgrade"'
        elif verdict == 'newer':
            text = f'{version} is newer than the {latest} available{via}'
        else:
            text = f'{version} is installed; the newest available version could not be determined'

        print (f'{space}STATUS: {text}')

    return {'return': 0, 'status': status}


def prepare_upgrade_version(self, ctx, kwargs):
    """
    Before --upgrade installs a tool that was not found: release-download tools get
    the newest release instead of their pinned default (when it can be determined;
    otherwise the pinned default is installed and a note is printed).
    """
    con = ctx['control'].get('con', False)

    tool_read = kwargs['tool_read']
    desc = tool_read['desc']
    space = tool_read['space']
    name = tool_read['artifact_print_name']

    channels = self.describe_channels(ctx, desc, tool_read, kwargs)
    kwargs['_upgrade_channels'] = channels

    if channels['primary'] != CHANNEL_RELEASE or kwargs.get('version'):
        return {'return': 0}

    rl = self.find_latest(ctx, desc, tool_read, kwargs, channels, query_channel = None, never_install = False)
    if self.cm.catch_error(rl): return rl

    latest = rl['upstream_version']
    if not latest:
        if con:
            print ('')
            print (f'{space}WARNING: the newest release of "{name}" could not be determined ({"; ".join(rl["notes"])}) - installing the pinned default')
        return {'return': 0}

    if con:
        print ('')
        print (f'{space}INFO: the newest release of "{name}" is {latest} ({rl["upstream_source"]})')

    kwargs['version'] = latest
    kwargs.update(split_version(latest))

    return {'return': 0, 'version': latest}


def upgrade_tool(self, ctx, old, **kwargs):
    """
    "cx tool setup <tool> --upgrade" for a tool that detection found: upgrade it
    through its channel (task/setup/install.py in upgrade mode), detect it again and
    report before -> after. The result is the new detection, plus "last_upgrade".
    """
    con = ctx['control'].get('con', False)

    tool_read = kwargs['tool_read']
    desc = tool_read['desc']
    name = tool_read['artifact_print_name']
    space = tool_read['space']

    channels = kwargs.pop('_upgrade_channels', None) or self.describe_channels(ctx, desc, tool_read, kwargs)
    channel = channels['primary']
    version = kwargs.get('version')
    ignore_install_errors = kwargs.get('ignore_install_errors', False)

    old_path = old.get('path')
    old_version = old.get('version')

    record = {'from': old_version, 'to': old_version, 'path': old_path, 'channel': channel,
              'changed': False, 'timestamp': now_iso()}

    if channel == CHANNEL_NONE and not channels['upgrade_cmd']:
        hint = ''
        parents = [u.get('name', '').split(',')[0] for u in desc.get('uses', []) if 'setup' in str(u.get('task', ''))]
        if parents:
            hint = f' - it is set up through {", ".join(p for p in parents if p)}: upgrade that tool instead'
        if con:
            print ('')
            print (f'{space}WARNING: no upgrade procedure for "{name}" (it is detected only){hint}; keeping {old_version} at {old_path}')
        record['skipped'] = 'no upgrade procedure'
        old['last_upgrade'] = record
        return old

    # Release downloads: pick the version to install - the newest release unless one was asked for
    if channel == CHANNEL_RELEASE and not version:
        rl = self.find_latest(ctx, desc, tool_read, kwargs, channels, query_channel = None, never_install = False)
        if self.cm.catch_error(rl): return rl
        latest = rl['upstream_version']
        if not latest:
            why = '; '.join(rl['notes']) or 'the tool has no cmd_get_versions or cmd_get_latest_version'
            return self.cm.error(f'cannot determine the newest release of "{name}" ({why}) - pass --version=<x.y.z> to upgrade to a known release')
        record['latest'] = latest
        if version_verdict(old_version, latest) in ('up-to-date', 'newer'):
            if con:
                print ('')
                print (f'{space}UPGRADE: "{name}" {old_version} is already the newest release ({latest}) - nothing to do')
            old['last_upgrade'] = record
            return old
        version = latest
        kwargs['version'] = version
        kwargs.update(split_version(version))

    # Upgrade through the install machinery in upgrade mode (install.py swaps the
    # verb, drops winget's --no-upgrade, uses upgrade_cmd when the tool has one)
    kwargs['task_extra_control'] = dict(kwargs.get('task_extra_control', {}), upgrade = True)
    kwargs['install'] = True

    r = self.install_tool(ctx, {'return': 0}, **kwargs)
    if not ignore_install_errors and self.cm.catch_error(r): return r

    failed = r.get('failed', False) or r['return'] > 0
    record['cmd'] = r.get('install_cmd')

    # winget reports "No available upgrade found" through a failure code
    nothing_to_do = (channels['declared'] == CHANNEL_WINGET and r.get('returncode') in WINGET_NOTHING_TO_DO)
    if nothing_to_do:
        failed = False

    if failed:
        record['failed'] = True
        if r.get('error'):
            record['error'] = r['error']

    # Detect again: where the install put it, else where the old copy was, else anywhere
    kwargs['task_extra_control'] = dict(kwargs['task_extra_control'], upgrade = False)
    attempts = []
    if r.get('found_path'):
        attempts.append({'tool_path': r['found_path']})
    if old_path:
        attempts.append({'tool_path': old_path})
    attempts.append({'tool_path': None, 'paths': r.get('found_paths') or kwargs.get('paths')})

    rd = None
    for attempt in attempts:
        kw = dict(kwargs)
        kw.update(attempt)
        rd = self.detect_existing_tool(ctx, **kw)
        if rd['return'] == 0:
            break
        if rd['return'] not in (1, 16):
            return rd

    if rd is None or rd['return'] > 0:
        return self.cm.error(f'"{name}" was not found after the upgrade (it was {old_version} at {old_path}): {rd.get("error") if rd else ""}')

    new_version = rd['version']
    new_path = rd['path']
    changed = (new_version != old_version) or (os.path.normcase(os.path.normpath(new_path)) != os.path.normcase(os.path.normpath(old_path or '')))

    record.update({'to': new_version, 'path': new_path, 'changed': changed})
    rd['last_upgrade'] = record

    if con:
        print ('')
        if changed and not failed:
            print (f'{space}UPGRADE: "{name}" {old_version} -> {new_version} ({new_path})')
        elif changed:
            print (f'{space}UPGRADE: "{name}" {old_version} -> {new_version} ({new_path}), although the upgrade command returned an error')
        elif failed:
            print (f'{space}WARNING: the upgrade command failed and "{name}" is still {old_version} at {old_path}')
            installed_channel = guess_channel_from_path(old_path)
            if installed_channel and installed_channel != channels['declared'] and channel not in (CHANNEL_RELEASE, CHANNEL_RERUN, CHANNEL_NONE):
                print (f'{space}         this copy seems to come from {CHANNEL_TEXT.get(installed_channel, installed_channel)}, '
                       f'not from {CHANNEL_TEXT[channels["declared"]]} - upgrade it the way it was installed, or pass --version=<x.y.z>')
        else:
            via = CHANNEL_TEXT[channel]
            if channels['package'] and channel in CHANNELS_WITH_OWN_LATEST:
                via += f' ({channels["package"]})'
            print (f'{space}UPGRADE: "{name}" is already the newest version available via {via} ({old_version})')

    return rd
