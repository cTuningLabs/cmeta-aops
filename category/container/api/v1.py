"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

container - build and run docker / podman containers from cMeta templates (prototype).

A template is an artifact of this category. Two kinds, told apart by `kind:` in _desc.yaml:

    kind: base   an OS image with cMeta installed (ubuntu, debian, fedora, rockylinux, amazonlinux, opensuse ...):
                 `template:` defaults (os_version, cmeta_source pypi|git|local, cmeta_version, user, ...),
                 `package_manager:` apt|dnf|microdnf|tdnf|zypper, `packages:`, optional `compute:` variants (cuda: a
                 different FROM plus run flags), `image:` tag template, `tests:`.
    kind: app    something that runs on a base (cmeta-test, cmeta-cserver): `bases:` it
                 accepts, `template:` defaults (port, ...), `clone_repos:` baked into the image, `ports:`, `volumes:`,
                 `env:`, `secrets:` (names only), `config_from_env:`, `cmd:`, `open_url:`, `tests:`; `inherits:`
                 another app.

Every string in a template may use {{cmeta.<key>}} (the merged parameters) and {{host.<key>}}; the rendered
Containerfile, entrypoint and build/run scripts are plain files anyone can reuse without cMeta.

    cx container render <template> [--distro=ubuntu] [--template.os_version=26.04] [--compute=cuda] [--out=<dir>]
    cx container build  <template> [...] [--rebuild] [--pull] [--platform=linux/arm64]
    cx container run    <template> [...] [--port=8010[:8004]] [--repo=<cMeta repo>] [--copy_repo=<cMeta repo>] [--input.<name>=<path>] [-- <cmd>]
                        --repo mounts a plugged repository of this machine (live edits, slow on Docker Desktop / podman
                        machine bind mounts); --copy_repo copies it into the image (fast, rebuilt when it changes)
    cx container start  <template> [...] [--open]          # build + run detached + wait for open_url
    cx container test   <template> [...]                   # build, run the template's tests, PASS/FAIL table
    cx container shell  <template or container name>       # interactive shell
    cx container ps | logs <name> | stop <name> | clean <template or name> [--images]

Engines: --engine=docker|podman (default: config `container.engine`, else docker, else podman). Secrets:
--secret=<config alias> (values or "env:NAME"), never written into an image layer.
"""

import atexit
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser

from cmeta.category import InitCategory

CATEGORY_ALIAS = 'container'
TASK_CATEGORY = 'task,c36be4b9314a45e0'
TASK_BUILD = 'container-build,cb638ed296334871'
TASK_RUN = 'container-run,1eeecb521ba540f2'
CONFIG_CATEGORY = 'config,cc6bfe174be847ed'
REPO_CATEGORY = 'repo,f4f792ab40c7498f'

ENGINES = ('docker', 'podman')
ENGINE_WELL_KNOWN_PATHS = {
    'docker': [r'C:\Program Files\Docker\Docker\resources\bin\docker.exe', '/usr/local/bin/docker', '/usr/bin/docker'],
    'podman': [r'C:\Program Files\RedHat\Podman\podman.exe', '/usr/local/bin/podman', '/usr/bin/podman'],
}

LABEL = 'cmeta.container'

# CMETA_CONTAINER_TRACE=1 shows the full cMeta task trace of the nested build/run tasks (otherwise only the
# engine's own output and this category's progress lines are printed - the trace drowns them)
TRACE = str(os.environ.get('CMETA_CONTAINER_TRACE', '')).lower() in ('1', 'true', 'yes', 'on')


def headless_docker_config():
    """
    Docker Desktop keeps registry credentials in the OS keychain (macOS) or credential manager (Windows) through
    a credsStore in ~/.docker/config.json, and a session without user interaction - ssh, a service - cannot open
    it: every pull then fails with "error getting credentials" (the Mac mini over ssh, 2026-10-15). When the
    store's helper cannot list, the docker commands of this process get a copy of the config without the store
    (DOCKER_CONFIG, removed at exit): anonymous pulls work; a private registry needs a desktop session or a
    DOCKER_CONFIG of your own. Returns the folder set, '' when nothing was needed.
    """
    if os.environ.get('DOCKER_CONFIG') or sys.platform.startswith('linux'):
        return ''
    path = os.path.join(os.path.expanduser('~'), '.docker', 'config.json')
    try:
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return ''
    helpers = {str(cfg.get('credsStore') or '')} | {str(v) for v in (cfg.get('credHelpers') or {}).values()}
    helpers.discard('')
    if not helpers:
        return ''

    broken = False
    if sys.platform == 'darwin':
        # the helpers read the login keychain: can this session open it? (over ssh: "User interaction is not allowed")
        keychain = os.path.join(os.path.expanduser('~'), 'Library', 'Keychains', 'login.keychain-db')
        try:
            r = subprocess.run(['security', 'show-keychain-info', keychain], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            broken = r.returncode != 0
        except (OSError, subprocess.SubprocessError):
            broken = True
    else:
        for helper in helpers:
            try:
                r = subprocess.run([f'docker-credential-{helper}', 'list'], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                broken = broken or r.returncode != 0
            except (OSError, subprocess.SubprocessError):
                broken = True
    if not broken:
        return ''

    folder = tempfile.mkdtemp(prefix='cmeta-docker-config-')
    cfg.pop('credsStore', None)
    cfg.pop('credHelpers', None)
    with open(os.path.join(folder, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    if not os.environ.get('DOCKER_BUILDKIT'):
        # Docker Desktop pulls through its own backend, which asks the store whatever the config says; the
        # classic builder pulls a public base image anonymously (checked over ssh on the Mac mini, 2026-10-15,
        # and on a Windows host signed in with an ssh key, 2026-10-16)
        os.environ['DOCKER_BUILDKIT'] = '0'
    # the endpoints (Docker Desktop: desktop-linux) and the CLI plugins (buildx, compose) live next to the config
    for sub in ('contexts', 'cli-plugins'):
        src = os.path.join(os.path.dirname(path), sub)
        if not os.path.isdir(src):
            continue
        try:
            os.symlink(src, os.path.join(folder, sub), target_is_directory=True)
        except OSError:
            shutil.copytree(src, os.path.join(folder, sub), dirs_exist_ok=True)
    os.environ['DOCKER_CONFIG'] = folder
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    return folder

def qualified_image(name):
    """
    An image name with its registry, as docker reads a short one: "ubuntu:26.04" is docker.io/library/ubuntu:26.04,
    "nvidia/cuda:13.3.1-base-ubuntu26.04" is docker.io/nvidia/cuda:... - podman refuses a short name that its
    registries.conf has no alias for (Ubuntu's podman knows ubuntu and debian, not nvidia/cuda: seen 2026-10-16).
    A name whose first part is a registry (a dot, a port, localhost) is kept.
    """
    name = str(name or '').strip()
    if not name:
        return name
    first, _, rest = name.partition('/')
    if rest and ('.' in first or ':' in first or first == 'localhost'):
        return name
    return f'docker.io/{name}' if rest else f'docker.io/library/{name}'

MIN_PYTHON = '3.9'   # the oldest Python cMeta supports: a distro with an older one gets a Python fetched by uv

# one package-install fragment per package manager; {pkgs} = the space-separated package list
PKG_BLOCKS = {
    'apt': 'RUN apt-get update && apt-get install -y --no-install-recommends {pkgs} && rm -rf /var/lib/apt/lists/*',
    'dnf': 'RUN dnf -y install {pkgs} && dnf clean all',
    'microdnf': 'RUN microdnf -y install {pkgs} && microdnf clean all',
    'tdnf': 'RUN tdnf -y install {pkgs} && tdnf clean all',
    'zypper': 'RUN zypper --non-interactive install --no-recommends {pkgs} && zypper clean --all',
    'conda': 'RUN apt-get update && apt-get install -y --no-install-recommends {pkgs} && rm -rf /var/lib/apt/lists/*',
}


class Category(InitCategory):
    """Build and run docker / podman containers from cMeta templates."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)
        self._engine_cache = {}

    ############################################################
    # small helpers

    def _ref(self):
        return CATEGORY_ALIAS + ',' + str((self.cmeta or {}).get('artifact', ''))

    def _files_dir(self):
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'files')

    def _err(self, msg):
        return {'return': 1, 'error': msg}

    @staticmethod
    def _as_list(v):
        if v is None or v == '':
            return []
        if isinstance(v, (list, tuple)):
            return [x for x in v if x not in (None, '')]
        return [v]

    @staticmethod
    def _as_dict(v):
        return dict(v) if isinstance(v, dict) else {}

    @staticmethod
    def _is_true(v):
        return v is True or str(v).lower() in ('1', 'true', 'yes', 'on')

    def _render(self, text, values, where=''):
        """Expand {{cmeta.*}} / {{host.*}} / {{inputs.*}} in a string with the engine's own renderer."""
        if not isinstance(text, str) or '{{' not in text:
            return {'return': 0, 'string': text}
        r = self.cm.utils.common.expand_string(text, values)
        if r['return'] > 0:
            r['error'] = f'{r["error"]} (while rendering {where or "a template string"})'
        return r

    def _host_facts(self):
        home = os.path.expanduser('~')
        cmeta_home = os.environ.get('CMETA_HOME', '') or getattr(self.cm, 'home_path', '') or ''
        return {
            'home': home,
            'cmeta_home': cmeta_home,
            'repos_dir': os.path.join(cmeta_home, 'repos') if cmeta_home else '',
            'os': sys.platform,
            'is_windows': sys.platform.startswith('win'),
        }

    ############################################################
    # engines

    def _engine_path(self, engine):
        """Path of the docker / podman binary on this host (PATH first, then the well-known install locations)."""
        if engine in self._engine_cache:
            return self._engine_cache[engine]
        p = shutil.which(engine)
        if not p:
            for cand in ENGINE_WELL_KNOWN_PATHS.get(engine, []):
                if os.path.isfile(cand):
                    p = cand
                    break
        self._engine_cache[engine] = p
        if p and engine == 'docker':
            # once per process, before the first docker command: a session without a desktop gets a config
            # without the credential store (see headless_docker_config)
            folder = headless_docker_config()
            if folder:
                print (f'cMeta info: docker\'s credential store cannot be opened in this session (no desktop session): '
                       f'anonymous pulls only, through DOCKER_CONFIG={folder}'
                       + (' and the classic builder (DOCKER_BUILDKIT=0)' if os.environ.get('DOCKER_BUILDKIT') == '0' else ''))
        return p

    def _pick_engine(self, engine=''):
        engine = (engine or '').strip().lower()
        if not engine:
            r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'get', 'arg1': 'container', 'con': False})
            cfg = r.get('config_cmeta', {}) if r.get('return', 1) == 0 else {}
            engine = str(cfg.get('engine', '') or '').lower()
        if not engine:
            for e in ENGINES:
                if self._engine_path(e):
                    engine = e
                    break
        if engine not in ENGINES:
            return self._err(f'unknown or missing container engine "{engine}" - use --engine=docker or --engine=podman '
                             f'(install: cx tool setup docker --install / cx tool setup podman --install)')
        if not self._engine_path(engine):
            return self._err(f'"{engine}" is not installed on this host (cx tool setup {engine} --install)')
        return {'return': 0, 'engine': engine}

    def _engine_run(self, engine, args, capture=True, con=False, timeout=None):
        """Run one engine command directly (ps, logs, stop, inspect ...) - no templating, no task machinery."""
        exe = self._engine_path(engine)
        if not exe:
            return self._err(f'"{engine}" not found')
        cmd = ' '.join([self.cm.q(exe)] + [a if (a.startswith('"') or ' ' not in a) else self.cm.q(a) for a in args])
        return self.cm.utils.sys.run(cmd, capture_output=capture, con=con, timeout=timeout)

    def _daemon_hint(self, engine, err=''):
        if engine == 'docker':
            return ('the docker daemon is not answering - start Docker Desktop (Windows/macOS) or the docker service '
                    '(Linux) and retry' + (f'\n{err}' if err else ''))
        return ('podman is not answering - on Windows/macOS run "podman machine start", on Linux check "podman info"'
                + (f'\n{err}' if err else ''))

    def _check_daemon(self, engine):
        r = self._engine_run(engine, ['info', '--format', '{{.ServerVersion}}'] if engine == 'docker'
                             else ['info', '--format', '{{.Version.Version}}'])
        if r.get('return', 1) > 0 or r.get('returncode', 1) != 0:
            return self._err(self._daemon_hint(engine, (r.get('stderr') or r.get('error') or '').strip()[:300]))
        return {'return': 0, 'version': (r.get('stdout') or '').strip()}

    def _image_hash(self, engine, image):
        """The cmeta.params_hash label of an existing image, '' when the image exists without it, None when absent."""
        r = self._engine_run(engine, ['image', 'inspect', image, '--format', '{{.Config.Labels}}'])
        if r.get('return', 1) > 0 or r.get('returncode', 1) != 0:
            return None
        m = re.search(r'cmeta\.params_hash:([0-9a-f]+)', r.get('stdout') or '')
        return m.group(1) if m else ''

    ############################################################
    # templates

    def _find(self, ref):
        r = self.cm.access({'category': self._ref(), 'command': 'find', 'arg1': ref, 'con': False})
        if r.get('return', 1) > 0:
            return r
        arts = r.get('artifacts') or []
        if len(arts) != 1:
            return self._err(f'container template "{ref}" resolves to {len(arts)} artifacts (cx container list)')
        return {'return': 0, 'artifact': arts[0]}

    def _load_template(self, ref, seen=None):
        """Template + merged _desc.yaml (inherits: parents first, child wins) + the dirs to look for files in."""
        seen = seen or []
        r = self._find(ref)
        if r['return'] > 0:
            return r
        a = r['artifact']
        path = a['path']
        alias = os.path.basename(path)
        uid = (a.get('meta') or {}).get('artifact') or ''
        if path in seen:
            return self._err(f'circular inherits in container template "{alias}"')
        rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(path, '_desc'))
        desc_own = (rd.get('data') or {}) if rd.get('return', 1) == 0 else {}
        desc = {}
        file_dirs = [path]
        for parent in self._as_list(desc_own.get('inherits')):
            rp = self._load_template(parent, seen + [path])
            if rp['return'] > 0:
                return rp
            self.cm.utils.common.deep_merge(desc, copy.deepcopy(rp['desc']), append_lists=False)
            file_dirs += [d for d in rp['file_dirs'] if d not in file_dirs]
        self.cm.utils.common.deep_merge(desc, copy.deepcopy(desc_own), append_lists=False)
        desc.pop('inherits', None)
        return {'return': 0, 'alias': alias, 'uid': uid, 'path': path, 'meta': a.get('meta') or {},
                'desc': desc, 'desc_own': desc_own, 'file_dirs': file_dirs}

    def _file(self, file_dirs, name, default_name=None):
        """First files/<name> along the inheritance chain, else the category default files/<default_name>."""
        for d in file_dirs:
            p = os.path.join(d, 'files', name)
            if os.path.isfile(p):
                return p
        if default_name:
            p = os.path.join(self._files_dir(), default_name)
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def _read(p):
        with open(p, encoding='utf-8') as f:
            return f.read().replace('\r\n', '\n')

    @staticmethod
    def _norm_base(base, allowed):
        base = (base or '').strip()
        if not base:
            return allowed[0] if allowed else 'ubuntu'
        for c in (base, 'host-' + base):
            if c in allowed:
                return c
        return base if base.startswith('host-') else 'host-' + base

    ############################################################
    # repositories

    def _repo_refs(self, *values):
        """--repo / --repos values -> a flat list of references ("a;b" splits on ";" - "," belongs to alias,UID)."""
        out = []
        for v in values:
            for x in self._as_list(v):
                out += [p.strip() for p in str(x).split(';') if p.strip()]
        return [x for i, x in enumerate(out) if x not in out[:i]]

    def _repo_path(self, ref):
        """
        A cMeta repository reference (alias, alias,UID or UID) -> its path on this machine through cMeta's registry;
        a directory path is accepted too (a repository that is not plugged in). Returns {'return', 'path', 'alias'}.
        """
        ref = str(ref).strip().strip('"')
        r = self.cm.access({'category': REPO_CATEGORY, 'command': 'find', 'arg1': ref, 'con': False})
        arts = (r.get('artifacts') or []) if r.get('return', 1) == 0 else []
        if len(arts) == 1 and arts[0].get('path') and os.path.isdir(arts[0]['path']):
            path = arts[0]['path']
            alias = os.path.basename(os.path.normpath(path))
            meta = arts[0].get('meta') or {}
            art = str(meta.get('artifact', '') or '')
            if ',' in art:
                alias = art.split(',')[0].strip() or alias
            return {'return': 0, 'path': path, 'alias': alias}
        if len(arts) > 1:
            return self._err(f'--repo: "{ref}" matches {len(arts)} repositories - use alias,UID (cx repo find {ref})')
        p = os.path.abspath(os.path.expanduser(ref))
        if os.path.isdir(p):
            if not (os.path.isfile(os.path.join(p, '_cmr.yaml')) or os.path.isfile(os.path.join(p, '_cmr.json'))):
                return self._err(f'--repo: "{p}" is a directory but not a cMeta repository (no _cmr.yaml)')
            return {'return': 0, 'path': p, 'alias': os.path.basename(os.path.normpath(p))}
        return self._err(f'--repo: "{ref}" is neither a plugged cMeta repository (cx repo list) nor a directory')

    ############################################################
    # secrets

    def _load_secrets(self, secret_aliases):
        """--secret=<config alias> -> {NAME: value}; a value "env:VAR" is read from the host environment."""
        out = {}
        for alias in self._as_list(secret_aliases):
            r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'get', 'arg1': str(alias), 'con': False})
            cfg = (r.get('config_cmeta') or {}) if r.get('return', 1) == 0 else None
            if not cfg:
                return self._err(f'--secret: config artifact "{alias}" not found or empty '
                                 f'(cx config set {alias} --meta.NAME=env:NAME)')
            for k, v in cfg.items():
                if isinstance(v, (dict, list)):
                    continue
                sv = str(v)
                if sv.startswith('env:'):
                    var = sv[4:].strip()
                    sv = os.environ.get(var, '')
                    if not sv:
                        return self._err(f'--secret {alias}: environment variable "{var}" for "{k}" is not set')
                out[str(k)] = sv
        return {'return': 0, 'secrets': out}

    @staticmethod
    def _pick_secret(name, provided):
        """A secret named in the template: from --secret artifacts first, else the host environment, else None."""
        if name in provided:
            return provided[name]
        return os.environ.get(name) or None

    ############################################################
    # resolution: template + base + parameters -> spec (rendered files, image tags, run configuration)

    def _resolve(self, ctx, name, base='', engine='', compute='', template=None, secret=None, port=None,
                 repo=None, repos_dir='', input=None, env=None, volume=None, platform='', expose_lan=False,
                 no_clone=False, unparsed=None, bake=None):
        re_ = self._pick_engine(engine)
        if re_['return'] > 0:
            return re_
        engine = re_['engine']

        t = self._load_template(name)
        if t['return'] > 0:
            return t
        kind = str(t['desc'].get('kind', 'app')).lower()
        compute = str(compute or t['desc'].get('compute_default') or 'cpu').lower()
        if compute in ('none', ''):
            compute = 'cpu'

        rs = self._load_secrets(secret)
        if rs['return'] > 0:
            return rs
        provided_secrets = rs['secrets']

        # the base
        if kind == 'base':
            b, app = t, None
        else:
            allowed = self._as_list(t['desc'].get('bases')) or ['ubuntu']
            b = self._load_template(self._norm_base(base, allowed))
            if b['return'] > 0:
                return b
            if str(b['desc'].get('kind', '')).lower() != 'base':
                return self._err(f'"{b["alias"]}" is not a base template (kind: base)')
            app = t

        host = self._host_facts()
        cli_template = self._as_dict(template)

        # repositories from this machine: mounted at run time (--repo) or copied into the image (--copy_repo)
        mounted, baked = [], []
        for ref in self._repo_refs(repo):
            rr = self._repo_path(ref)
            if rr['return'] > 0:
                return rr
            mounted.append(rr)
        for ref in self._repo_refs(bake):
            rr = self._repo_path(ref)
            if rr['return'] > 0:
                return rr
            if rr['alias'] not in [m['alias'] for m in mounted]:
                baked.append(rr)
        provided_aliases = [x['alias'] for x in mounted + baked]

        # ---- parameters: base defaults < base compute < app defaults < app compute < --template.*
        cmeta = {}
        bcomp = self._as_dict((b['desc'].get('compute') or {}).get(compute))
        self.cm.utils.common.deep_merge(cmeta, copy.deepcopy(self._as_dict(b['desc'].get('template'))))
        self.cm.utils.common.deep_merge(cmeta, copy.deepcopy(self._as_dict(bcomp.get('template'))))
        acomp = {}
        if app:
            acomp = self._as_dict((app['desc'].get('compute') or {}).get(compute))
            self.cm.utils.common.deep_merge(cmeta, copy.deepcopy(self._as_dict(app['desc'].get('template'))))
            self.cm.utils.common.deep_merge(cmeta, copy.deepcopy(self._as_dict(acomp.get('template'))))
        self.cm.utils.common.deep_merge(cmeta, copy.deepcopy(cli_template))
        if compute != 'cpu' and not bcomp and not acomp:
            return self._err(f'compute "{compute}" is not defined by "{b["alias"]}"' + (f' or "{app["alias"]}"' if app else '')
                             + ' (compute: section in _desc.yaml)')

        cmeta['template_alias'] = t['alias']
        cmeta['kind'] = kind
        cmeta['base_alias'] = b['alias']
        cmeta['base'] = b['alias'][5:] if b['alias'].startswith('host-') else b['alias']
        cmeta['compute'] = compute
        cmeta['compute_suffix'] = '' if compute == 'cpu' else '-' + compute
        cmeta['engine'] = engine
        cmeta.setdefault('os_version', '')
        cmeta.setdefault('cmeta_source', 'pypi')
        cmeta.setdefault('cmeta_version', '')
        cmeta.setdefault('cmeta_extras', 'server')
        cmeta.setdefault('cmeta_local_path', '')
        cmeta.setdefault('cmeta_git_url', 'https://github.com/cTuningLabs/cmeta')
        cmeta.setdefault('cmeta_git_ref', '')
        cmeta.setdefault('user', 'cmeta')
        cmeta.setdefault('python_package', 'python3')
        user = str(cmeta['user'])
        cmeta['home'] = '/root' if user == 'root' else f'/home/{user}'
        cmeta['variant_suffix'] = (('-norepos' if (no_clone and app) else '') + ('-copy' if (baked and app) else '')
                                   + ('-cmeta-local' if (app and str(cmeta['cmeta_source']).lower() == 'local') else ''))
        cmeta['os_version'] = str(cmeta['os_version'])

        values = {'cmeta': cmeta, 'host': host, 'inputs': {}}

        def R(text, where):
            r = self._render(text, values, where)
            if r['return'] > 0:
                raise ValueError(r['error'])
            return r['string']

        try:
            # ---- base facts
            pm = str(b['desc'].get('package_manager', 'apt')).lower()
            if pm not in PKG_BLOCKS:
                return self._err(f'unknown package_manager "{pm}" in "{b["alias"]}"')
            packages = [str(p) for p in self._as_list(b['desc'].get('packages')) + self._as_list(bcomp.get('packages'))]
            pyp = str(cmeta['python_package'])
            if pyp and pyp not in packages and pm != 'conda':
                packages = [pyp] + packages
            cmeta['package_manager'] = pm
            cmeta['packages_line'] = ' '.join(packages)
            cmeta['install_packages_block'] = PKG_BLOCKS[pm].format(pkgs=cmeta['packages_line']) if packages else ''
            env_lines = ['ENV LANG=C.UTF-8 LC_ALL=C.UTF-8']
            if pm in ('apt', 'conda'):
                env_lines.insert(0, 'ENV DEBIAN_FRONTEND=noninteractive')
            cmeta['env_block'] = '\n'.join(env_lines)
            if user == 'root':
                cmeta['user_block'] = ''
            else:
                # The uid rule: a Linux engine keeps the machine's ownership on a bind mount, so the user inside takes
                # the machine user's uid and gid when asked for (--template.uid=1000 --template.gid=1000, what
                # get-host--docker passes on Linux; a system uid could not even plug a mounted repository) - a user
                # or group the base image already has under that number (ubuntu, uid 1000 in ubuntu:24.04) goes
                # first; without uid, a system user as before. Docker Desktop and podman machine need nothing.
                uid = str(cmeta.get('uid') or '').strip()
                gid = str(cmeta.get('gid') or uid).strip()
                if uid:
                    make = (f'(u=$(getent passwd {uid} | cut -d: -f1); [ -z "$u" ] || userdel -r "$u" || true) '
                            f'&& (g=$(getent group {gid} | cut -d: -f1); [ -z "$g" ] || groupdel "$g" || true) '
                            f'&& groupadd -g {gid} {user} && useradd -u {uid} -m -d /home/{user} -g {user} -s /bin/bash {user}')
                else:
                    make = f'groupadd -r {user} && useradd -r -m -d /home/{user} -g {user} -s /bin/bash {user}'
                # sudo without its PAM account check for this user: under rootless podman (--userns=keep-id) the check
                # fails on Rocky Linux 10, Amazon Linux 2023 and Azure Linux 3.0 ("PAM account management error"), so no
                # package could be installed inside (seen 2026-10-16); kept only when this sudo knows the option
                sudoers = f'/etc/sudoers.d/{user}'
                cmeta['user_block'] = (f'RUN {make} '
                                       f'&& echo "{user} ALL=(ALL) NOPASSWD:ALL" > {sudoers} '
                                       f'&& echo "Defaults:{user} !pam_acct_mgmt" >> {sudoers} && chmod 0440 {sudoers} '
                                       f'&& (visudo -cf {sudoers} >/dev/null 2>&1 || sed -i "/pam_acct_mgmt/d" {sudoers})')
            # root_lines: Containerfile lines of a base run as root once the user exists (a stack base: the image's own
            # Python environment given to the user, so that cMeta inside may add to it)
            cmeta['root_block'] = '\n'.join(R(str(x), 'root_lines') for x in self._as_list(b['desc'].get('root_lines')))

            from_tpl = bcomp.get('from') or cmeta.get('from') or ''
            if not from_tpl:
                return self._err(f'"{b["alias"]}" defines no FROM image (template.from)')
            cmeta['from'] = R(str(from_tpl), 'from')
            if engine == 'podman':
                cmeta['from'] = qualified_image(cmeta['from'])

            # ---- cMeta inside the image
            extras = str(cmeta['cmeta_extras'])
            version = str(cmeta['cmeta_version'] or '')
            cmeta['cmeta_pin'] = f'=={version}' if version else ''
            # uv installs cMeta on the distro's python unless a version is asked for (then uv fetches a managed one); a
            # distro whose python is older than cMeta supports (Rocky Linux 8: 3.6) gets one fetched by uv - the same
            # install again with a version range, run only when the first one failed (seen 2026-10-16)
            cmeta.setdefault('python_version', '')
            pyv = str(cmeta['python_version'] or '')
            cmeta['uv_python_flag'] = f' --python "{pyv}"' if pyv else ''

            def uv_install(spec):
                line = f'uv tool install "{spec}"{cmeta["uv_python_flag"]} --with markdown'
                return line if pyv else f'{line} || uv tool install "{spec}" --python ">={MIN_PYTHON}" --with markdown'

            copy_files = []      # [{'src': host path, 'dst': name in the build context}]
            source = str(cmeta['cmeta_source']).lower()
            if source == 'pypi':
                cmeta['install_cmeta_block'] = 'RUN ' + uv_install(f'cmeta[{extras}]{cmeta["cmeta_pin"]}')
            elif source == 'local':
                rt = self._tar_engine_checkout(str(cmeta['cmeta_local_path'] or ''))
                if rt['return'] > 0:
                    return rt
                copy_files.append({'src': rt['tar'], 'dst': 'cmeta_src.tar.gz'})
                src_spec = f'cmeta[{extras}] @ {cmeta["home"]}/cmeta-src'
                cmeta['cmeta_local_sha256'] = rt['sha256']
                cmeta['cmeta_local_checkout'] = rt['checkout']
                cmeta['install_cmeta_block'] = (
                    f'COPY --chown={user} cmeta_src.tar.gz /tmp/cmeta_src.tar.gz\n'
                    f'RUN mkdir -p {cmeta["home"]}/cmeta-src && tar -xzf /tmp/cmeta_src.tar.gz -C {cmeta["home"]}/cmeta-src '
                    f'&& ({uv_install(src_spec)}) && rm -f /tmp/cmeta_src.tar.gz')
            elif source == 'git':
                ref = str(cmeta['cmeta_git_ref'] or '')
                url = str(cmeta['cmeta_git_url']).replace('https://', '')
                tok = self._pick_secret('GITHUB_TOKEN', provided_secrets)
                mount = '--mount=type=secret,id=GITHUB_TOKEN ' if tok else ''
                cmeta['install_cmeta_block'] = (
                    f"RUN {mount}sh -c 'T=$(cat /run/secrets/GITHUB_TOKEN 2>/dev/null); "
                    + uv_install(f'cmeta[{extras}] @ git+https://${{T:+$T@}}{url}{("@" + ref) if ref else ""}') + "'")
            else:
                return self._err(f'cmeta_source must be pypi, git or local (got "{source}")')

            # ---- base image tag
            base_image_tpl = b['desc'].get('image') or 'cmeta/{{cmeta.base_alias}}:{{cmeta.os_version|latest}}{{cmeta.compute_suffix}}-cmeta-{{cmeta.cmeta_version|latest}}'
            cmeta['base_image'] = R(str(base_image_tpl), 'image of ' + b['alias']).lower()
            # the engine's renderer leaves an empty value empty ({{x|latest}} is the default of a MISSING key): no
            # version asked = the newest release, said in the tag; dashes between every part (cmeta-0.37.1, cmeta-latest)
            if not version and cmeta['base_image'].endswith('-cmeta-'):
                cmeta['base_image'] += 'latest'
            if source == 'local':
                cmeta['base_image'] = cmeta['base_image'].rsplit('-cmeta-', 1)[0] + '-cmeta-local-' + cmeta['cmeta_local_sha256'][:8]

            # ---- app facts
            build_secrets, run_env, run_secrets = {}, {}, {}
            ports, volumes, run_flags, tests = [], [], [], []
            open_url, clone_block, app_block, expose_block = '', '', '', ''
            config_from_env = {}
            image = cmeta['base_image']
            desc = (app or b)['desc']

            sec = self._as_dict(desc.get('secrets'))
            for n in self._as_list(sec.get('build')):
                v = self._pick_secret(str(n), provided_secrets)
                if v:
                    build_secrets[str(n)] = v
            for n in self._as_list(sec.get('run')):
                v = self._pick_secret(str(n), provided_secrets)
                if v:
                    run_secrets[str(n)] = v
            if source == 'git':
                tok = self._pick_secret('GITHUB_TOKEN', provided_secrets)
                if tok:
                    build_secrets['GITHUB_TOKEN'] = tok

            if app:
                cmeta.setdefault('port', '')
                cmeta.setdefault('container_port', cmeta.get('port') or '')
                lines = []
                for entry in self._as_list(desc.get('clone_repos')):
                    if isinstance(entry, str):
                        lines.append(f'RUN cx repo get {R(entry, "clone_repos")}')
                        continue
                    e = self._as_dict(entry)
                    url = R(str(e.get('url', '')), 'clone_repos.url')
                    if not url:
                        continue
                    sname = str(e.get('secret', '') or '')
                    checkout = R(str(e.get('checkout', '') or ''), 'clone_repos.checkout')
                    flag = f' --checkout={checkout}' if checkout else ''
                    if sname:
                        repo_name = url.rstrip('/').split('/')[-1].replace('.git', '')
                        if no_clone or any(a == repo_name or a.endswith('@' + repo_name) for a in provided_aliases):
                            continue
                        tok = self._pick_secret(sname, provided_secrets)
                        if tok:
                            build_secrets[sname] = tok
                            bare = url.replace('https://', '')
                            lines.append(f"RUN --mount=type=secret,id={sname} sh -c 'T=$(cat /run/secrets/{sname}); "
                                         f'cx repo get --url="https://${{T:+$T@}}{bare}"{flag}\'')
                        elif e.get('optional'):
                            continue
                        else:
                            return self._err(f'"{app["alias"]}" clones {url} with the secret "{sname}", which is not provided: '
                                             f'pass --secret=<config alias> that defines {sname} (or set {sname} in the environment), '
                                             f'or use --no_clone and mount the repository with --repo=<path>')
                    else:
                        lines.append(f'RUN cx repo get --url={url}{flag}')
                for rr in baked:
                    rt = self._tar_repo(rr['path'], rr['alias'])
                    if rt['return'] > 0:
                        return rt
                    copy_files.append({'src': rt['tar'], 'dst': f'repos/{rr["alias"]}.tar.gz', 'sha256': rt['sha256']})
                    lines.append(f'COPY --chown={user} repos/{rr["alias"]}.tar.gz /tmp/repo.tar.gz')
                    lines.append(f'RUN mkdir -p {cmeta["home"]}/repos/{rr["alias"]} && tar -xzf /tmp/repo.tar.gz -C {cmeta["home"]}/repos/{rr["alias"]} && rm -f /tmp/repo.tar.gz')
                if lines:
                    lines.append('RUN cx --reindex >/dev/null')
                clone_block = '\n'.join(lines)
                app_block = '\n'.join(R(str(x), 'app_lines') for x in self._as_list(desc.get('app_lines')))
                image_tpl = desc.get('image') or 'cmeta/{{cmeta.template_alias}}:{{cmeta.base}}-{{cmeta.os_version|latest}}{{cmeta.compute_suffix}}{{cmeta.variant_suffix}}'
                image = R(str(image_tpl), 'image of ' + app['alias']).lower()
                open_url = str(desc.get('open_url', '') or '')
                config_from_env = self._as_dict(desc.get('config_from_env'))
            cmeta['mount_secrets'] = ' '.join(f'--mount=type=secret,id={n}' for n in build_secrets)
            cmd = [str(x) for x in self._as_list(desc.get('cmd'))] or ['/bin/bash']

            cmeta['image'] = image
            cmeta['clone_block'] = clone_block
            cmeta['app_block'] = app_block

            # ---- ports (desc, then --port overrides the host side of the first mapping or adds one)
            bind = '' if self._is_true(expose_lan) else '127.0.0.1:'
            for p in self._as_list(desc.get('ports')):
                p = R(str(p), 'ports')
                if ':' not in p:
                    p = f'{p}:{p}'
                if p.split(':')[0]:
                    ports.append(p)
            for p in self._as_list(port):
                p = str(p)
                if ':' in p:
                    h, c = p.split(':', 1)
                    ports = [x for x in ports if x.split(':')[-1] != c] + [f'{h}:{c}']
                elif ports:
                    ports[0] = f'{p}:{ports[0].split(":")[-1]}'
                else:
                    ports.append(f'{p}:{p}')
            if ports:
                cmeta['port'] = ports[0].split(':')[0]
                cmeta['container_port'] = ports[0].split(':')[-1]
                expose_block = 'EXPOSE ' + ' '.join(sorted({x.split(':')[-1] for x in ports}))
            cmeta['expose_block'] = expose_block
            ports_publish = [f'{bind}{p}' for p in ports]
            if open_url:
                open_url = R(open_url, 'open_url')

            # ---- volumes: desc, --volume, --repo, --repos_dir, --input.<name>
            inputs = {}
            for v in self._as_list(desc.get('volumes')):
                v = R(str(v), 'volumes')
                if v and not v.startswith(':'):
                    volumes.append(v)
            for v in self._as_list(volume):
                volumes.append(str(v))
            for rr in mounted:
                volumes.append(f'{rr["path"]}:{cmeta["home"]}/repos/{rr["alias"]}')
            if repos_dir:
                rd = os.path.abspath(os.path.expanduser(str(repos_dir)))
                if not os.path.isdir(rd):
                    return self._err(f'--repos_dir: directory not found: {rd}')
                volumes.append(f'{rd}:{cmeta["home"]}/repos')
            for n, pth in self._as_dict(input).items():
                pth = os.path.abspath(os.path.expanduser(str(pth)))
                if not os.path.exists(pth):
                    return self._err(f'--input.{n}: path not found: {pth}')
                inputs[str(n)] = f'{cmeta["home"]}/inputs/{n}'
                volumes.append(f'{pth}:{inputs[str(n)]}')
            values['inputs'] = inputs

            # ---- environment
            for k, v in self._as_dict(desc.get('env')).items():
                run_env[str(k)] = R(str(v), 'env.' + str(k))
            for k, v in self._as_dict(env).items():
                run_env[str(k)] = str(v)
            if config_from_env:
                run_env['CMETA_CONFIG_FROM_ENV'] = ';'.join(f'{k}={v}' for k, v in config_from_env.items())

            # ---- run flags per compute (a list for both engines, or {docker: [...], podman: [...]})
            for src in (bcomp, acomp):
                rf = src.get('run_flags')
                if isinstance(rf, dict):
                    rf = rf.get(engine) or []
                run_flags += [R(str(x), 'run_flags') for x in self._as_list(rf)]

            # ---- the command (after "--" wins); {{inputs.<name>}} may be used in it
            if unparsed:
                cmd = [str(x) for x in unparsed]
            cmd = [R(str(x), 'cmd') for x in cmd]
            cmeta['cmd_json'] = json.dumps(cmd)

            # ---- tests
            for tst in self._as_list(desc.get('tests')) + (self._as_list(b['desc'].get('tests')) if app else []):
                if isinstance(tst, dict):
                    ic = str(tst.get('if_compute', '') or '')
                    if ic and ic != compute:
                        continue
                    tests.append(R(str(tst.get('cmd', '')), 'tests'))
                else:
                    tests.append(R(str(tst), 'tests'))
            tests = [x for i, x in enumerate(tests) if x and x not in tests[:i]]

            # ---- rendered files
            files = {}
            cf_path = self._file(t['file_dirs'], 'Containerfile', 'Containerfile.app' if app else 'Containerfile.base')
            if not cf_path:
                return self._err(f'no Containerfile for "{t["alias"]}"')
            rendered_cf = R(self._read(cf_path), os.path.basename(cf_path))
            # empty blocks (no clone_repos, no app_lines, ...) leave blank lines behind - keep at most one
            rendered_cf = '\n'.join(l for i, l in enumerate(rendered_cf.split('\n'))
                                    if l.strip() or (i > 0 and rendered_cf.split('\n')[i - 1].strip()))
            files['Containerfile'] = rendered_cf.rstrip('\n') + '\n'
            if not app:
                ep = self._file(t['file_dirs'], 'entrypoint.sh', 'entrypoint.sh')
                files['entrypoint.sh'] = R(self._read(ep), 'entrypoint.sh')
            for extra in self._as_list(desc.get('files')):
                p = self._file(t['file_dirs'], str(extra))
                if not p:
                    return self._err(f'"{t["alias"]}" lists files/{extra}, which does not exist')
                copy_files.append({'src': p, 'dst': str(extra)})
        except ValueError as e:
            return self._err(str(e))

        # ---- identity of this build
        h = hashlib.sha256()
        for k in sorted(files):
            h.update(k.encode())
            h.update(files[k].encode('utf-8'))
        for c in copy_files:
            h.update(c['dst'].encode())
            if c['dst'] == 'cmeta_src.tar.gz':
                h.update(cmeta.get('cmeta_local_sha256', '').encode())
            elif c.get('sha256'):
                h.update(c['sha256'].encode())
        h.update(json.dumps({'from': cmeta['from'], 'platform': platform, 'image': image}, sort_keys=True).encode())
        params_hash = h.hexdigest()[:16]

        labels = {LABEL: '1', 'cmeta.template': t['alias'], 'cmeta.base': b['alias'], 'cmeta.kind': kind,
                  'cmeta.compute': compute, 'cmeta.params_hash': params_hash}

        spec = {
            'return': 0,
            'template': t, 'base': b, 'app': app, 'kind': kind, 'engine': engine, 'compute': compute,
            'cmeta': cmeta, 'host': host, 'image': image, 'base_image': cmeta['base_image'],
            'files': files, 'copy_files': copy_files, 'build_secrets': build_secrets, 'platform': platform or '',
            'params_hash': params_hash, 'labels': labels,
            'run': {'ports': ports_publish, 'volumes': volumes, 'env': run_env, 'env_secrets': run_secrets,
                    'run_flags': run_flags, 'cmd': cmd,
                    'name': (('' if t['alias'].startswith('cmeta') else 'cmeta-') + f'{t["alias"]}-{cmeta["base"]}'
                             + (f'-{cmeta["os_version"]}' if cmeta['os_version'] else '')).lower(),
                    'open_url': open_url},
            'tests': tests,
        }
        # the base of an app is a spec of its own (rendered the same way, so that build can make it first)
        if app:
            rb = self._resolve(ctx, b['alias'], engine=engine, compute=compute, template=cli_template, secret=secret,
                               platform=platform)
            if rb['return'] > 0:
                return rb
            spec['base_spec'] = rb
            if rb['image'] != spec['base_image']:
                spec['files']['Containerfile'] = spec['files']['Containerfile'].replace(spec['base_image'], rb['image'])
                spec['base_image'] = rb['image']
                cmeta['base_image'] = rb['image']
        return spec

    def _tar_engine_checkout(self, local_path=''):
        """cmeta_source=local: tar the engine checkout (cmeta/, tests/, pyproject.toml, ...) into a temp file."""
        candidates = [local_path] if local_path else []
        if not local_path:
            r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'get', 'arg1': 'container', 'con': False})
            cfg = r.get('config_cmeta', {}) if r.get('return', 1) == 0 else {}
            if cfg.get('cmeta_local_path'):
                candidates.append(str(cfg['cmeta_local_path']))
            cmeta_home = os.environ.get('CMETA_HOME', '') or getattr(self.cm, 'home_path', '') or ''
            if cmeta_home:
                candidates.append(os.path.join(cmeta_home, '__symlinks', 'cmeta'))
            try:
                import cmeta as _cm
                candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(_cm.__file__))))
            except Exception:
                pass
        root = next((c for c in candidates if c and os.path.isfile(os.path.join(c, 'pyproject.toml'))
                     and os.path.isdir(os.path.join(c, 'cmeta'))), '')
        if not root:
            return self._err('cmeta_source=local needs the engine checkout (a directory with pyproject.toml and cmeta/): '
                             'pass --template.cmeta_local_path=<dir>, or set it once per machine with '
                             '"cx config set container --meta.cmeta_local_path=<dir>"'
                             + (f' (tried: {", ".join(c for c in candidates if c)})' if candidates else ''))
        members = [m for m in ('cmeta', 'tests', 'pyproject.toml', 'MANIFEST.in', 'README.md', 'LICENSE', 'COPYRIGHT', 'NOTICE')
                   if os.path.exists(os.path.join(root, m))]
        tmpdir = os.path.join(tempfile.gettempdir(), 'cmeta-container')
        os.makedirs(tmpdir, exist_ok=True)
        tar_path = os.path.join(tmpdir, 'cmeta_src.tar.gz')

        def _filter(ti):
            n = ti.name.replace('\\', '/')
            if '__pycache__' in n or n.endswith('.pyc') or '/.git' in n or n.startswith('tests/tmp'):
                return None
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ''
            return ti

        with tarfile.open(tar_path, 'w:gz') as tf:
            for m in members:
                tf.add(os.path.join(root, m), arcname=m, filter=_filter)
        h = hashlib.sha256()
        with open(tar_path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return {'return': 0, 'tar': tar_path, 'sha256': h.hexdigest(), 'checkout': root}

    def _tar_repo(self, path, alias):
        """--copy_repo: tar a cMeta repository of this machine (without .git, caches, venvs) for the build context."""
        tmpdir = os.path.join(tempfile.gettempdir(), 'cmeta-container', 'repos')
        os.makedirs(tmpdir, exist_ok=True)
        tar_path = os.path.join(tmpdir, alias + '.tar.gz')
        skip_dirs = {'.git', '__pycache__', '.venv', 'venv', 'node_modules', '.pytest_cache', '.mypy_cache'}

        def _filter(ti):
            parts = ti.name.replace('\\', '/').split('/')
            if any(p in skip_dirs or p.startswith('tmp') for p in parts) or ti.name.endswith(('.pyc', '.pyo')):
                return None
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ''
            ti.mtime = 0                     # a stable archive for a stable hash
            return ti

        with tarfile.open(tar_path, 'w:gz', compresslevel=6) as tf:
            for entry in sorted(os.listdir(path)):
                if entry in skip_dirs:
                    continue
                tf.add(os.path.join(path, entry), arcname=entry, filter=_filter)
        h = hashlib.sha256()
        with open(tar_path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return {'return': 0, 'tar': tar_path, 'sha256': h.hexdigest(), 'size': os.path.getsize(tar_path)}

    ############################################################
    # build / run through the two portable tasks

    def _build_spec(self, ctx, spec, rebuild=False, pull=False, quiet_skip=False):
        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        engine = spec['engine']
        if spec.get('base_spec'):
            r = self._build_spec(ctx, spec['base_spec'], rebuild=rebuild, pull=pull, quiet_skip=quiet_skip)
            if r['return'] > 0:
                return r
        existing = self._image_hash(engine, spec['image'])
        if not rebuild and existing == spec['params_hash']:
            if con and not quiet_skip:
                print(f'  image exists: {spec["image"]}  ({engine}; --rebuild to rebuild)')
            return {'return': 0, 'image': spec['image'], 'skipped': True}
        if con and existing is not None and existing != spec['params_hash'] and not rebuild:
            print(f'  image {spec["image"]} was built from other parameters (hash {existing or "none"}) - rebuilding')
        rd = self._check_daemon(engine)
        if rd['return'] > 0:
            return rd
        build_args = ['--pull'] if pull else []
        ii = {'category': TASK_CATEGORY, 'command': 'run', 'arg1': TASK_BUILD,
              'engine': engine, 'image': spec['image'], 'params_hash': spec['params_hash'],
              'files': spec['files'], 'copy': spec['copy_files'], 'build_args': build_args,
              'secrets': spec['build_secrets'], 'platform': spec['platform'], 'no_cache': bool(rebuild),
              'labels': spec['labels'], 'update': True,
              'con': TRACE, 'verbose': TRACE}
        if con:
            print(f'  building {spec["image"]} with {engine} ...')
        r = self.cm.access(ii)
        if r.get('return', 1) > 0:
            return r
        return {'return': 0, 'image': spec['image'], 'image_id': r.get('image_id', ''), 'context_path': r.get('context_path', '')}

    def _run_spec(self, ctx, spec, detach=False, rm=True, interactive=False, name='', cmd=None, capture=False,
                  extra_flags=None, timeout=None):
        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        run = spec['run']
        ii = {'category': TASK_CATEGORY, 'command': 'run', 'arg1': TASK_RUN,
              'engine': spec['engine'], 'image': spec['image'], 'name': name or '', 'detach': bool(detach), 'rm': bool(rm),
              'interactive': bool(interactive), 'ports': run['ports'], 'volumes': run['volumes'], 'env': run['env'],
              'env_secrets': run['env_secrets'], 'run_flags': run['run_flags'] + list(extra_flags or []),
              'cmd': list(cmd) if cmd is not None else run['cmd'], 'labels': spec['labels'],
              'capture_output': bool(capture) or bool(detach), 'timeout': timeout,
              'con': TRACE, 'verbose': TRACE}
        return self.cm.access(ii)

    def _print_spec(self, spec):
        c = spec['cmeta']
        print(f'  template : {spec["template"]["alias"]} ({spec["kind"]})' + (f'   base: {spec["base"]["alias"]}' if spec['app'] else ''))
        print(f'  engine   : {spec["engine"]}   compute: {spec["compute"]}' + (f'   platform: {spec["platform"]}' if spec['platform'] else ''))
        print(f'  FROM     : {c["from"]}')
        if spec['app']:
            print(f'  base img : {spec["base_image"]}')
        print(f'  image    : {spec["image"]}   (params hash {spec["params_hash"]})')
        print(f'  cMeta    : source={c["cmeta_source"]} version={c["cmeta_version"] or "latest"} extras={c["cmeta_extras"]} user={c["user"]}')
        run = spec['run']
        if run['ports']:
            print(f'  ports    : {", ".join(run["ports"])}')
        if run['volumes']:
            print(f'  volumes  : {", ".join(run["volumes"])}')
        baked = [c['dst'][6:-7] for c in spec['copy_files'] if c['dst'].startswith('repos/')]
        if baked:
            print(f'  copied in: {", ".join(baked)} (from this machine, into the image)')
        if run['env']:
            print(f'  env      : {", ".join(f"{k}={v}" for k, v in run["env"].items())}')
        if run['env_secrets']:
            print(f'  secrets  : {", ".join(run["env_secrets"])} (run, via a temporary env-file)')
        if spec['build_secrets']:
            print(f'  secrets  : {", ".join(spec["build_secrets"])} (build, secret mounts)')
        if run['run_flags']:
            print(f'  run flags: {" ".join(run["run_flags"])}')
        print(f'  cmd      : {" ".join(run["cmd"])}')
        if run['open_url']:
            print(f'  url      : {run["open_url"]}')
        skip = ('cmd_json', 'mount_secrets', 'packages_line', 'image', 'base_image', 'from')
        params = {k: v for k, v in c.items() if not k.endswith('_block') and k not in skip and v not in ('', None)}
        print('  params   : ' + ', '.join(f'{k}={v}' for k, v in sorted(params.items())))

    ############################################################
    # commands

    def render_(self, ctx, arg1=None, distro='', engine='', compute='', template={}, secret=None, port=None, repo=None, repos=None,
                repos_dir='', input={}, env={}, volume=None, platform='', expose_lan=False, no_clone=False, out='',
                copy_repo=None, copy_repos=None, unparsed=None):
        """
        Resolve a template and print (or write with --out=<dir>) the rendered Containerfile, entrypoint and the
        build / run commands - everything the other commands would execute, without executing anything.
        """
        if not arg1:
            return self._err('cx container render <template> [--distro=...] [--template.<key>=<value>] [--out=<dir>]')
        spec = self._resolve(ctx, arg1, distro, engine, compute, template, secret, port, self._repo_refs(repo, repos), repos_dir, input, env,
                             volume, platform, expose_lan, no_clone, unparsed, bake=self._repo_refs(copy_repo, copy_repos))
        if spec['return'] > 0:
            return spec
        print('')
        self._print_spec(spec)
        chain = ([spec['base_spec']] if spec.get('base_spec') else []) + [spec]
        for s in chain:
            for fname, content in s['files'].items():
                print('')
                print(f'----- {s["template"]["alias"]}: {fname}')
                print(content.rstrip('\n'))
        print('')
        print('----- build / run (as the tasks issue them)')
        for s in chain:
            print(f'{s["engine"]} build --file Containerfile --tag {s["image"]}' +
                  ''.join(f' --secret id={k},src=<tmp>' for k in s['build_secrets']) +
                  (f' --platform {s["platform"]}' if s['platform'] else '') + f' <context of {s["template"]["alias"]}>')
        r = spec['run']
        print(f'{spec["engine"]} run --rm' + ''.join(f' -p {p}' for p in r['ports']) + ''.join(f' -v {v}' for v in r['volumes']) +
              ''.join(f' -e {k}={v}' for k, v in r['env'].items()) + (' --env-file <tmp>' if r['env_secrets'] else '') +
              (' ' + ' '.join(r['run_flags']) if r['run_flags'] else '') + f' {spec["image"]} ' + ' '.join(r['cmd']))
        if out:
            out = os.path.abspath(out)
            for s in chain:
                d = os.path.join(out, s['template']['alias'])
                os.makedirs(d, exist_ok=True)
                for fname, content in s['files'].items():
                    with open(os.path.join(d, fname), 'w', encoding='utf-8', newline='\n') as f:
                        f.write(content)
                for c in s['copy_files']:
                    shutil.copy2(c['src'], os.path.join(d, c['dst']))
                with open(os.path.join(d, 'cmeta-params.json'), 'w', encoding='utf-8') as f:
                    json.dump({'image': s['image'], 'params': s['cmeta'], 'run': s['run'], 'tests': s['tests']}, f, indent=2, default=str)
            print('')
            print(f'written to {out}')
        return {'return': 0, 'image': spec['image'], 'base_image': spec['base_image'], 'params': spec['cmeta'], 'tests': spec['tests']}

    def build_(self, ctx, arg1=None, distro='', engine='', compute='', template={}, secret=None, platform='',
               rebuild=False, pull=False, no_clone=False, port=None, copy_repo=None, copy_repos=None, unparsed=None):
        """
        Build the image of a template (its base image first when missing). Images carry the labels
        cmeta.container=1, cmeta.template, cmeta.base, cmeta.compute, cmeta.params_hash.
        """
        if not arg1:
            return self._err('cx container build <template> [--distro=...] [--engine=docker|podman] [--compute=cuda] [--rebuild]')
        spec = self._resolve(ctx, arg1, distro, engine, compute, template, secret, port=port, platform=platform, no_clone=no_clone,
                             bake=self._repo_refs(copy_repo, copy_repos))
        if spec['return'] > 0:
            return spec
        con = ctx['control'].get('con', False)
        if con:
            print('')
            self._print_spec(spec)
            print('')
        r = self._build_spec(ctx, spec, rebuild=self._is_true(rebuild), pull=self._is_true(pull))
        if r['return'] > 0:
            return r
        if con:
            print('')
            print(f'  ready: {spec["image"]}' + (f'  (id {r.get("image_id", "")[:19]})' if r.get('image_id') else ''))
        return {'return': 0, 'image': spec['image'], 'base_image': spec['base_image'], 'engine': spec['engine'],
                'image_id': r.get('image_id', ''), 'context_path': r.get('context_path', '')}

    def run_(self, ctx, arg1=None, distro='', engine='', compute='', template={}, secret=None, port=None, repo=None, repos=None,
             repos_dir='', input={}, env={}, volume=None, platform='', expose_lan=False, no_clone=False, name='',
             detach=False, keep=False, rebuild=False, interactive=False, i=False, copy_repo=None, copy_repos=None, unparsed=None):
        """
        Run a template's container in the foreground (build first when the image is missing). Everything after
        "--" replaces the template's command; --detach returns at once; --keep leaves the container after exit.
        """
        if not arg1:
            return self._err('cx container run <template> [...] [-- <command inside the container>]')
        spec = self._resolve(ctx, arg1, distro, engine, compute, template, secret, port, self._repo_refs(repo, repos), repos_dir, input, env,
                             volume, platform, expose_lan, no_clone, unparsed, bake=self._repo_refs(copy_repo, copy_repos))
        if spec['return'] > 0:
            return spec
        con = ctx['control'].get('con', False)
        r = self._build_spec(ctx, spec, rebuild=self._is_true(rebuild), quiet_skip=True)
        if r['return'] > 0:
            return r
        detach = self._is_true(detach)
        if con:
            print('')
            print(f'  {spec["engine"]} run {spec["image"]}: ' + ' '.join(spec['run']['cmd']) + (f'   name={name}' if name else ''))
            for p in spec['run']['ports']:
                print(f'  port {p}')
            for v in spec['run']['volumes']:
                print(f'  volume {v}')
        rr = self._run_spec(ctx, spec, detach=detach, rm=not self._is_true(keep) and not detach,
                            interactive=self._is_true(interactive) or self._is_true(i), name=name)
        if rr.get('return', 1) > 0:
            return rr
        out = {'return': 0, 'image': spec['image'], 'returncode': rr.get('returncode', 0)}
        if detach:
            out['container_id'] = rr.get('container_id', '')
            if con:
                print(f'  started: {out["container_id"][:12]}' + (f'  ({spec["run"]["open_url"]})' if spec['run']['open_url'] else ''))
        elif rr.get('returncode', 0) != 0:
            rc = rr['returncode']
            out['return'] = rc if isinstance(rc, int) and 0 < rc < 256 else 1
            out['error'] = f'the container exited with code {rc}'
        return out

    def start_(self, ctx, arg1=None, distro='', engine='', compute='', template={}, secret=None, port=None, repo=None, repos=None,
               repos_dir='', input={}, env={}, volume=None, platform='', expose_lan=False, no_clone=False, name='',
               rebuild=False, open=False, wait=90, copy_repo=None, copy_repos=None, unparsed=None):
        """
        Build if needed, run detached under a stable name (cmeta-<template>-<base>), wait until the template's
        open_url answers, print it (--open launches the browser). Stop with: cx container stop <name>.
        """
        if not arg1:
            return self._err('cx container start <template> [--port=8010] [--open]')
        spec = self._resolve(ctx, arg1, distro, engine, compute, template, secret, port, self._repo_refs(repo, repos), repos_dir, input, env,
                             volume, platform, expose_lan, no_clone, unparsed, bake=self._repo_refs(copy_repo, copy_repos))
        if spec['return'] > 0:
            return spec
        con = ctx['control'].get('con', False)
        name = name or spec['run']['name']
        r = self._build_spec(ctx, spec, rebuild=self._is_true(rebuild), quiet_skip=True)
        if r['return'] > 0:
            return r
        ex = self._engine_run(spec['engine'], ['ps', '-a', '--filter', f'name=^{name}$', '--format', '{{.ID}}'])
        if ex.get('returncode', 1) == 0 and (ex.get('stdout') or '').strip():
            self._engine_run(spec['engine'], ['rm', '-f', name])
        rr = self._run_spec(ctx, spec, detach=True, rm=False, name=name)
        if rr.get('return', 1) > 0:
            return rr
        cid = (rr.get('container_id') or '')[:12]
        url = spec['run']['open_url']
        if con:
            print('')
            print(f'  started {name} ({cid}) from {spec["image"]}')
            for p in spec['run']['ports']:
                print(f'  port {p}')
        ok = True
        if url:
            ok = self._wait_url(url, int(wait or 0), spec['engine'], name, con)
        if con:
            if url:
                print(f'  {"ready" if ok else "not answering yet"}: {url}')
            print(f'  logs: cx container logs {name}    shell: cx container shell {name}    stop: cx container stop {name}')
        if url and ok and self._is_true(open):
            try:
                webbrowser.open(url)
            except Exception:
                pass
        return {'return': 0, 'name': name, 'container_id': cid, 'image': spec['image'], 'url': url, 'ready': ok}

    def _wait_url(self, url, seconds, engine, name, con):
        t0 = time.monotonic()
        while time.monotonic() - t0 < max(seconds, 1):
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    if 200 <= resp.status < 500:
                        return True
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    return True
            except Exception:
                pass
            st = self._engine_run(engine, ['inspect', '--format', '{{.State.Running}}', name])
            if st.get('returncode', 1) == 0 and (st.get('stdout') or '').strip().lower() == 'false':
                if con:
                    print('  the container exited - last log lines:')
                    lg = self._engine_run(engine, ['logs', '--tail', '20', name])
                    print((lg.get('stdout') or '') + (lg.get('stderr') or ''))
                return False
            time.sleep(2)
        return False

    def test_(self, ctx, arg1=None, distro='', engine='', compute='', template={}, secret=None, platform='',
              rebuild=False, no_clone=False, port=None, repo=None, repos=None, repos_dir='', wait=90, copy_repo=None, copy_repos=None, unparsed=None):
        """
        Build the template (and its base), then run every entry of its `tests:` inside a throw-away container and,
        for a template with an open_url, start it and probe the URL from the host. Prints PASS / FAIL per test;
        the return code is non-zero when any fails.
        """
        if not arg1:
            return self._err('cx container test <template> [--distro=...] [--compute=cuda]')
        spec = self._resolve(ctx, arg1, distro, engine, compute, template, secret, port=port, repo=self._repo_refs(repo, repos), repos_dir=repos_dir,
                             platform=platform, no_clone=no_clone, bake=self._repo_refs(copy_repo, copy_repos))
        if spec['return'] > 0:
            return spec
        con = ctx['control'].get('con', False)
        if con:
            print('')
            self._print_spec(spec)
            print('')
        r = self._build_spec(ctx, spec, rebuild=self._is_true(rebuild))
        if r['return'] > 0:
            return r
        results = []
        for tcmd in spec['tests']:
            rr = self._run_spec(ctx, spec, detach=False, rm=True, cmd=['sh', '-lc', tcmd], capture=True, timeout=600)
            rc = rr.get('returncode', 1) if rr.get('return', 1) == 0 else 1
            out = ((rr.get('stdout') or '') + (rr.get('stderr') or '')).strip()
            results.append({'test': tcmd, 'ok': rc == 0, 'returncode': rc, 'output': out})
            if con:
                first = out.splitlines()[0][:100] if out else ''
                print(f'  {"PASS" if rc == 0 else "FAIL"}  {tcmd}' + (f'   -> {first}' if first else ''))
                if rc != 0 and out:
                    for line in out.splitlines()[-8:]:
                        print(f'        {line[:160]}')
        url = spec['run']['open_url']
        if url:
            name = spec['run']['name'] + '-test'
            self._engine_run(spec['engine'], ['rm', '-f', name])
            rr = self._run_spec(ctx, spec, detach=True, rm=False, name=name)
            ok = rr.get('return', 1) == 0 and self._wait_url(url, int(wait or 0), spec['engine'], name, con)
            results.append({'test': f'GET {url}', 'ok': ok, 'returncode': 0 if ok else 1, 'output': ''})
            if con:
                print(f'  {"PASS" if ok else "FAIL"}  GET {url}')
            self._engine_run(spec['engine'], ['rm', '-f', name])
        failed = [x for x in results if not x['ok']]
        if con:
            print('')
            print(f'  {len(results) - len(failed)} of {len(results)} tests passed for {spec["image"]}')
        out = {'return': 0 if not failed else 1, 'image': spec['image'], 'results': results}
        if failed:
            out['error'] = f'{len(failed)} test(s) failed for {spec["image"]}'
        return out

    def shell_(self, ctx, arg1=None, distro='', engine='', compute='', template={}, secret=None, repo=None, repos=None, repos_dir='',
               input={}, env={}, volume=None, no_clone=False, copy_repo=None, copy_repos=None, unparsed=None):
        """
        Interactive shell: in a running container started by cMeta (cx container shell <name>), or in a fresh
        throw-away container of a template (cx container shell <template> [--distro=...]).
        """
        if not arg1:
            return self._err('cx container shell <template or running container name>')
        re_ = self._pick_engine(engine)
        if re_['return'] > 0:
            return re_
        eng = re_['engine']
        st = self._engine_run(eng, ['inspect', '--format', '{{.State.Running}}', str(arg1)])
        if st.get('returncode', 1) == 0 and (st.get('stdout') or '').strip().lower() == 'true':
            exe = self._engine_path(eng)
            cmd = f'{self.cm.q(exe)} exec -it {arg1} sh -lc "exec bash || exec sh"'
            r = self.cm.utils.sys.run(cmd, capture_output=False, con=True)
            return {'return': 0, 'returncode': r.get('returncode', 0)}
        spec = self._resolve(ctx, arg1, distro, eng, compute, template, secret, repo=self._repo_refs(repo, repos), repos_dir=repos_dir, input=input,
                             env=env, volume=volume, no_clone=no_clone, bake=self._repo_refs(copy_repo, copy_repos))
        if spec['return'] > 0:
            return spec
        r = self._build_spec(ctx, spec, quiet_skip=True)
        if r['return'] > 0:
            return r
        rr = self._run_spec(ctx, spec, detach=False, rm=True, interactive=True, cmd=['sh', '-lc', 'exec bash || exec sh'])
        return {'return': 0 if rr.get('return', 1) == 0 else 1, 'returncode': rr.get('returncode', 0), 'error': rr.get('error')}

    def ps_(self, ctx, engine='', all=True):
        """Containers and images created by cMeta (label cmeta.container=1) for the selected engine."""
        re_ = self._pick_engine(engine)
        if re_['return'] > 0:
            return re_
        eng = re_['engine']
        rd = self._check_daemon(eng)
        if rd['return'] > 0:
            return rd
        print('')
        print(f'--- {eng} containers created by cMeta')
        r = self._engine_run(eng, ['ps'] + (['-a'] if self._is_true(all) else []) + ['--filter', f'label={LABEL}=1', '--format',
                             'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'])
        print((r.get('stdout') or '').rstrip() or '  (none)')
        print('')
        print(f'--- {eng} images created by cMeta')
        created = '{{.CreatedSince}}' if eng == 'docker' else '{{.Created}}'
        r = self._engine_run(eng, ['images', '--filter', f'label={LABEL}=1', '--format',
                             'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t' + created])
        print((r.get('stdout') or '').rstrip() or '  (none)')
        return {'return': 0}

    def logs_(self, ctx, arg1=None, engine='', follow=False, tail='200'):
        """Logs of a container started by cMeta: cx container logs <name> [--follow]."""
        if not arg1:
            return self._err('cx container logs <container name> [--follow]')
        re_ = self._pick_engine(engine)
        if re_['return'] > 0:
            return re_
        exe = self._engine_path(re_['engine'])
        cmd = f'{self.cm.q(exe)} logs --tail {int(tail)}' + (' --follow' if self._is_true(follow) else '') + f' {arg1}'
        r = self.cm.utils.sys.run(cmd, capture_output=False, con=True)
        return {'return': 0 if r.get('returncode', 1) == 0 else 1}

    def stop_(self, ctx, arg1=None, engine='', all=False, remove=True):
        """Stop (and by default remove) a container started by cMeta; --all stops every cMeta container."""
        re_ = self._pick_engine(engine)
        if re_['return'] > 0:
            return re_
        eng = re_['engine']
        names = []
        if self._is_true(all):
            r = self._engine_run(eng, ['ps', '-a', '--filter', f'label={LABEL}=1', '--format', '{{.Names}}'])
            names = [x for x in (r.get('stdout') or '').split() if x]
        elif arg1:
            names = [str(arg1)]
        if not names:
            return self._err('cx container stop <name> | --all')
        for n in names:
            self._engine_run(eng, ['stop', '-t', '5', n])
            if self._is_true(remove):
                self._engine_run(eng, ['rm', '-f', n])
            print(f'  stopped{" and removed" if self._is_true(remove) else ""}: {n}')
        return {'return': 0, 'stopped': names}

    def clean_(self, ctx, arg1=None, engine='', images=False, all=False):
        """
        Remove the containers (and with --images the images) that cMeta created for a template:
        cx container clean <template> [--images]; --all for everything labelled cmeta.container=1.
        """
        re_ = self._pick_engine(engine)
        if re_['return'] > 0:
            return re_
        eng = re_['engine']
        if not arg1 and not self._is_true(all):
            return self._err('cx container clean <template> [--images] | --all [--images]')
        flt = [f'label={LABEL}=1'] + ([] if self._is_true(all) else [f'label=cmeta.template={arg1}'])
        fargs = sum([['--filter', f] for f in flt], [])
        r = self._engine_run(eng, ['ps', '-a'] + fargs + ['--format', '{{.Names}}'])
        for n in [x for x in (r.get('stdout') or '').split() if x]:
            self._engine_run(eng, ['rm', '-f', n])
            print(f'  removed container: {n}')
        if self._is_true(images):
            r = self._engine_run(eng, ['images'] + fargs + ['--format', '{{.Repository}}:{{.Tag}}'])
            for im in [x for x in (r.get('stdout') or '').split() if x and not x.startswith('<none>')]:
                rr = self._engine_run(eng, ['rmi', im])
                print(f'  removed image: {im}' if rr.get('returncode', 1) == 0 else f'  kept image (in use?): {im}')
        return {'return': 0}
