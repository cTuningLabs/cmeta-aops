"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

get-host--wsl: a WSL distribution made from a container template, recorded as a host artifact - the WSL resolver of
the "run on any host" design (Windows only). What it does:

  1. names the instance after the place: <this host>-wsl-<template>-<os_version>, this host being its fleet alias
     when this machine has a host artifact, else its hostname (--instance names it);
  2. finds the instance's host artifact: its distribution registered -> returned (WSL starts it on the next
     command); gone -> made again;
  3. else builds the template's image through the container category (docker by default, --engine=podman), exports
     a container of it as a root file system (create / export / rm) and imports it as a WSL 2 distribution under
     --location (default: the key "location" of the config artifact task-get-host--wsl, else %LOCALAPPDATA%\\cmeta\\wsl);
  4. sets it up inside: /etc/wsl.conf (the template's user as the default user; no Windows PATH appended - every
     missed program lookup would cost 100 ms over the drive bridge), CMETA_HOME and the user's PATH in ~/.profile
     (an image's ENV lines do not survive the export), the repositories of this machine plugged from their
     /mnt/<drive> paths (nothing copied: a WSL distribution sees every drive), a readme-cmeta.md in the home,
     the index;
  5. records the host artifact in the local repository: type wsl, access (distro, user, shell), via = this
     machine's host artifact, made_from (template, params, engine, image, location, time, cMeta version), mounts
     (the /mnt paths), the tags made-by-cmeta and wsl; then probes it (cx host ls shows its OS and versions).

Then: cx host run <instance> "cx --version" | cx host ssh <instance> | cx host down <instance> (wsl --terminate)
      cx host destroy <instance>   (wsl --unregister: the distribution and its disk)

Everything runs through wsl.exe and the engine's own commands, printed with -v. The template's compute overlays
are container images (a GPU inside WSL comes with the Windows driver): only cpu here.
"""

import datetime
import os
import shlex
import platform
import re
import subprocess
import sys
import tempfile
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

CONTAINER_CATEGORY = 'container,ed08f0d107044479'
HOST_CATEGORY = 'host,e4e49c251c814f6d'
REPO_CATEGORY = 'repo,f4f792ab40c7498f'
CONFIG_CATEGORY = 'config,cc6bfe174be847ed'
CONFIG_ARTIFACT = 'task-get-host--wsl'

DEFAULT_TEMPLATE = 'ubuntu'
DEFAULT_REPOS = 'ctuninglabs@cmeta-aops'


def text_of(data):
    """wsl.exe writes UTF-16 on a pipe, the engines UTF-8: either, as text."""
    if b'\x00' in data:
        return data.decode('utf-16-le', errors='replace')
    return data.decode('utf-8', errors='replace')


def run_cmd(args, timeout=600, stdin_text=None):
    """One local command: (return code, stdout, stderr) as text; a script on stdin when given (LF endings)."""
    try:
        r = subprocess.run(list(args), input=stdin_text.encode('utf-8') if stdin_text is not None else None,
                           stdin=None if stdin_text is not None else subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, '', str(e)
    return r.returncode, text_of(r.stdout), text_of(r.stderr)


def wsl_distributions():
    """The registered distributions (wsl -l -q), [] when WSL is not there."""
    code, out, err = run_cmd(['wsl.exe', '-l', '-q'], timeout=60)
    if code != 0:
        return []
    return [line.strip().lstrip('\ufeff') for line in out.splitlines() if line.strip()]


def clean_name(text):
    """A distribution and artifact name: lower case, letters, digits, dots and dashes."""
    return re.sub(r'[^a-z0-9.]+', '-', str(text).lower()).strip('-.')


def mnt_path(path):
    """A Windows path as WSL sees it: D:\\x\\y -> /mnt/d/x/y (the default automount root)."""
    p = os.path.abspath(path).replace('\\', '/')
    if len(p) > 1 and p[1] == ':':
        return '/mnt/' + p[0].lower() + p[2:]
    return p


def readme(instance, image, engine, name, params, carrier, home, user, mounts, made, cmeta_version, location):
    """The readme-cmeta.md written into the distribution's home."""
    lines = [
        f'# {instance}',
        '',
        f'A cMeta instance of the container template "{name}": a WSL 2 distribution made on {made} on the machine',
        f'"{carrier}" by cMeta {cmeta_version} (cx task run get-host--wsl), to run cMeta tasks, tools and programs in a',
        'stable Linux environment separate from the machine\'s own cache.',
        '',
        '## How it was made',
        '',
        f'- the image {image} ({engine}), exported as a root file system and imported as a WSL 2 distribution at {location}',
        f'- template: {name}' + (f', parameters {params}' if params else ''),
        f'- the default user is {user}; /etc/wsl.conf keeps the Windows PATH out; ~/.profile sets CMETA_HOME',
        f'- rebuild the image: cx container build {name}' + ''.join(f' --template.{k}={v}' for k, v in (params or {}).items()),
        '',
        '## What is seen from the machine (plugged from the drive mounts, nothing copied)',
        '',
    ]
    for m in mounts:
        lines.append(f'- {m["inside"]}  <-  {m["path"]}')
    if not mounts:
        lines.append('- nothing')
    lines += [
        '',
        '## How to reach it from the machine',
        '',
        f'- cx host run {instance} "cx --version"',
        f'- cx host ssh {instance}',
        f'- cx host down {instance}                                  (wsl --terminate; the next command starts it again)',
        f'- cx host destroy {instance}                               (wsl --unregister: the distribution and its disk)',
        f'- wsl.exe -d {instance}                                    (by hand)',
        '',
        f'The cMeta home inside is {home}/CMETA: its cache is this instance\'s own and is never shared with the machine.',
        '',
    ]
    return '\n'.join(lines)


class CTask(InitCTask):
    """
    A WSL distribution of a container template as a host artifact.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def _find(self, category, alias):
        """The first artifact of an alias, or None."""
        r = self.cm.access({'category': category, 'command': 'find', 'arg1': alias, 'con': False})
        if r['return'] > 0 or not r.get('artifacts'):
            return None
        return r['artifacts'][0]

    def _desc(self, path):
        r = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(path, '_desc'))
        return (r.get('data') or {}) if r['return'] == 0 else {}

    def _carrier(self):
        """
        This machine as a fleet host (alias, uid, machine cRef) when it has a host artifact - "cx host whoami": by
        the system_id its probe recorded, else by the declared hostname - else its hostname.
        """
        r = self.cm.access({'category': HOST_CATEGORY, 'command': 'whoami', 'con': False})
        if r['return'] == 0 and r.get('host'):
            return r['host'], r.get('uid'), r.get('machine')
        return clean_name(platform.node().lower()), None, None

    def _location(self, location):
        """--location, else the config artifact's key, else %LOCALAPPDATA%\\cmeta\\wsl."""
        if location:
            return str(location)
        r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'read', 'arg1': CONFIG_ARTIFACT, 'con': False})
        cfg = (r.get('config_cmeta') or r.get('meta') or {}) if r.get('return', 1) == 0 else {}
        if cfg.get('location'):
            return str(cfg['location'])
        return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'cmeta', 'wsl')

    ############################################################
    def run(self,
            ctx: dict,
            name: str = DEFAULT_TEMPLATE,    # the container template (ubuntu, debian, ...)
            template: dict = {},             # --template.<key>=<value>: the template's parameters (os_version, cmeta_version, ...)
            distro: str = '',                # an app template (llama-cpp, vllm-cuda ...): the base it is built on (default: the first of its bases)
            compute: str = 'cpu',            # cpu, or cuda: the template's CUDA overlay (its CUDA libraries; WSL gives the distribution the GPU itself)
            engine: str = 'docker',          # the engine that builds and exports the image: docker or podman
            instance: str = '',              # the instance's name (default: <this host>-wsl-<template>[-<base>]-<os_version>[-<compute>])
            repos: str = '',                 # repositories of this machine plugged inside, comma-separated (default: ctuninglabs@cmeta-aops)
            data: str = '',                  # data repositories (config::task cache_repos) plugged inside from their drive mounts: all by default, a subset, "key=alias", or "none"
            location: str = '',              # the folder of the distribution's disk (default: config task-get-host--wsl, key location)
            new_host: bool = False,          # another instance of the same place (-2, -3 ...) instead of the existing one
            pull: bool = False,              # pull the base image again when building
            rebuild: bool = False,           # build the image again
    ):
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        if os.name != 'nt':
            return self.cm.error('get-host--wsl makes WSL distributions: it runs on Windows (elsewhere: get-host--docker)')
        code, out, err = run_cmd(['wsl.exe', '--status'], timeout=60)
        if code != 0:
            return self.cm.error(f'WSL is not usable here ({err.strip() or out.strip() or "wsl.exe not found"}): wsl --install')

        # ---- the template and its parameters
        t = self._find(CONTAINER_CATEGORY, name)
        if not t:
            return self.cm.error(f'container template "{name}" not found (cx container find "*")')
        tdesc = self._desc(t['path'])

        # an app template (a stack) is built on one of its bases: the base gives the OS version, the user and the
        # compute overlays, the app its own parameters and lines (as in get-host--docker)
        bdesc = tdesc
        base_name = ''
        if str(tdesc.get('kind') or 'base').lower() == 'app':
            allowed = [str(x) for x in (tdesc.get('bases') or ['ubuntu'])]
            base_name = str(distro or allowed[0])
            if base_name not in allowed:
                return self.cm.error(f'the app template "{name}" is built on {", ".join(allowed)}, not "{base_name}"')
            b = self._find(CONTAINER_CATEGORY, base_name)
            if not b:
                return self.cm.error(f'the base template "{base_name}" of "{name}" is not found (cx container find "*")')
            bdesc = self._desc(b['path'])
        elif distro:
            return self.cm.error(f'"{name}" is a base template: --distro is for an app template')
        tparams = dict(bdesc.get('template') or {})
        overlays = dict(bdesc.get('compute') or {})
        if bdesc is not tdesc:
            tparams.update(tdesc.get('template') or {})
            overlays.update(tdesc.get('compute') or {})
        compute = str(compute or 'cpu')
        if compute != 'cpu' and compute not in overlays:
            return self.cm.error(f'the template "{name}" has no compute overlay "{compute}" (it has: {", ".join(overlays.keys()) or "none"})')

        params = {str(k): str(v) for k, v in (template or {}).items()}
        tparams.update(params)
        os_version = str(tparams.get('os_version') or '')
        user = str(tparams.get('user') or 'cmeta')
        home = '/root' if user == 'root' else f'/home/{user}'

        # ---- the place and the instance's name
        carrier, carrier_uid, machine = self._carrier()
        stem = clean_name(instance) if instance else clean_name(f'{carrier}-wsl-{name}' + (f'-{base_name}' if base_name else '')
                                                               + f'-{os_version}' + (f'-{compute}' if compute != 'cpu' else ''))
        inst = stem
        existing = self._find(HOST_CATEGORY, inst)
        if existing and new_host:
            n = 2
            while self._find(HOST_CATEGORY, f'{stem}-{n}'):
                n += 1
            inst = f'{stem}-{n}'
            existing = None

        # ---- an existing instance: registered, or gone
        if existing:
            d = self._desc(existing['path'])
            acc = d.get('access') or {}
            distro = str(acc.get('distro') or inst)
            if distro in wsl_distributions():
                if con:
                    print ('')
                    print (f'cMeta info: instance {inst} registered (WSL distribution {distro}); shell: cx host ssh {inst}')
                return {'return': 0, 'host': inst, 'distro': distro, 'image': (d.get('made_from') or {}).get('image', ''),
                        'made': False, 'status': 'registered', 'path': existing['path'],
                        'data_repos': [m['repo'] for m in (d.get('mounts') or []) if m.get('kind') == 'data']}
            if con:
                print ('')
                print (f'cMeta info: the distribution {distro} of the instance {inst} is gone - made again')

        # ---- the repositories plugged inside, from their drive mounts
        mounts = []
        for alias in [x.strip() for x in str(repos or DEFAULT_REPOS).split(',') if x.strip()]:
            if alias == 'local':
                return self.cm.error('the local repository is never plugged into an instance (its cache is this machine\'s)')
            a = self._find(REPO_CATEGORY, alias)
            if not a:
                return self.cm.error(f'repository "{alias}" is not plugged here (cx repo find "*")')
            if (a.get('cmeta') or {}).get('secrets'):
                return self.cm.error(f'repository "{alias}" holds secrets (secrets: true in its _cmr.yaml) and is never given to an instance')
            path = os.path.realpath(a.get('full_path') or a['path'])
            mounts.append({'repo': a['cmeta_ref_parts'].get('artifact_alias') or alias, 'path': path, 'inside': mnt_path(path)})

        # ---- the data repositories of this machine (config::task cache_repos: models, datasets), plugged from their
        # drive mounts; the config inside gets the same keys, pointing at them
        r = self._data_mounts(data)
        if r['return'] > 0:
            return r
        data_mounts, config_keys = r['mounts'], r['keys']

        # the template's own config inside (instance_config: {"task.use.python.tool_path": ...}), as get-host--docker does
        instance_config = dict(bdesc.get('instance_config') or {})
        if bdesc is not tdesc:
            instance_config.update(tdesc.get('instance_config') or {})

        # ---- the image, through the container category
        ib = {'category': CONTAINER_CATEGORY, 'command': 'build', 'arg1': name, 'engine': engine,
              'compute': compute, 'template': params, 'pull': bool(pull), 'rebuild': bool(rebuild),
              'con': con and not quiet, 'quiet': quiet}
        if base_name:
            ib['distro'] = base_name
        rb = self.cm.access(ib)
        if rb['return'] > 0:
            return rb
        image = rb.get('image', '')

        # ---- the root file system: a container of the image, exported
        where = self._location(location)
        folder = os.path.join(where, inst)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            return self.cm.error(f'cannot make the distribution folder {folder}: {e}')
        tar = os.path.join(folder, 'rootfs.tar')
        tmp = f'cmeta-export-{inst}'
        run_cmd([engine, 'rm', '-f', tmp], timeout=120)
        if con:
            print ('')
            print (f'cMeta info: exporting the image {image} as a root file system ({tar})')
        code, out, err = run_cmd([engine, 'create', '--name', tmp, image], timeout=300)
        if code != 0:
            return self.cm.error(f'{engine} create failed: {err.strip() or out.strip()}')
        code, out, err = run_cmd([engine, 'export', '-o', tar, tmp], timeout=1800)
        run_cmd([engine, 'rm', '-f', tmp], timeout=120)
        if code != 0:
            return self.cm.error(f'{engine} export failed: {err.strip() or out.strip()}')

        # ---- the distribution
        if inst in wsl_distributions():
            run_cmd(['wsl.exe', '--terminate', inst], timeout=120)
            run_cmd(['wsl.exe', '--unregister', inst], timeout=300)           # a leftover of a failed attempt
        if con:
            print (f'cMeta info: importing the WSL distribution {inst} into {folder}')
        code, out, err = run_cmd(['wsl.exe', '--import', inst, folder, tar, '--version', '2'], timeout=1800)
        try:
            os.remove(tar)
        except OSError:
            pass
        if code != 0:
            return self.cm.error(f'wsl --import failed: {(err or out).strip()}')

        # ---- the setup inside, as root: the default user, no Windows PATH, CMETA_HOME in the profile
        setup = '\n'.join([
            'set -e',
            'printf "[user]\\ndefault=%s\\n\\n[interop]\\nappendWindowsPath=false\\n" "' + user + '" > /etc/wsl.conf',
            # \$PATH stays literal in the profile (at setup time root's PATH still holds the Windows folders, with spaces and parentheses)
            f'grep -q CMETA_HOME {home}/.profile 2>/dev/null || printf "\\n# cMeta (get-host--wsl)\\nexport CMETA_HOME={home}/CMETA\\nexport PATH={home}/.local/bin:\\$PATH\\n" >> {home}/.profile',
            f'chown {user}:{user} {home}/.profile',
            '',
        ])
        code, out, err = run_cmd(['wsl.exe', '-d', inst, '-u', 'root', '--', 'sh', '-s'], timeout=300, stdin_text=setup)
        if code != 0:
            return self.cm.error(f'the setup inside {inst} failed: {(err or out).strip()}')
        run_cmd(['wsl.exe', '--terminate', inst], timeout=120)              # wsl.conf applies on the next start

        # ---- the repositories plugged, the index, the readme (as the user)
        made = datetime.datetime.now().astimezone().isoformat(timespec='minutes')
        cmeta_version = str(getattr(self.cm, 'version', '') or (ctx['tasks'].get('global', {}).get('init', {}) or {}).get('cmeta_version', '') or '')
        text = readme(inst, image, engine, name, params, carrier, home, user, mounts + data_mounts, made, cmeta_version, folder)
        plug = ['set -e'] + [f'cx repo plug "{m["inside"]}" >/dev/null' for m in mounts + data_mounts] + [
            f'cx config set task --meta.cache_repos.{key}={alias} >/dev/null' for key, alias in config_keys] + [
            f'cx config set {k.split(".", 1)[0]} --meta.{k.split(".", 1)[1]}={shlex.quote(str(v))} >/dev/null'
            for k, v in sorted(instance_config.items()) if '.' in str(k)] + [
            'cx --reindex >/dev/null',
            f"cat > {home}/readme-cmeta.md <<'CMETA_README_END'",
            text,
            'CMETA_README_END',
            '',
        ]
        code, out, err = run_cmd(['wsl.exe', '-d', inst, '--', 'bash', '-l', '-s'], timeout=900, stdin_text='\n'.join(plug))
        if code != 0:
            return self.cm.error(f'plugging the repositories inside {inst} failed: {(err or out).strip()}')

        # ---- the host artifact in the local repository
        if existing:
            apath = existing['path']
        else:
            r = self.cm.access({'category': HOST_CATEGORY, 'command': 'create', 'arg1': f'local:{inst}', 'yaml': True,
                                'tags': ['made-by-cmeta', 'wsl', name], 'con': False})
            if r['return'] > 0:
                return r
            apath = r['path']
        desc = {}
        if machine:
            desc['machine'] = machine
        desc.update({
            'type': 'wsl',
            'os': str(tdesc.get('os') or name),
        })
        if carrier_uid:
            desc['via'] = f'host,{HOST_CATEGORY.split(",")[1]}::{carrier},{carrier_uid}'
        desc.update({
            'access': {'distro': inst, 'user': user, 'shell': 'bash -l'},
            'cmeta': {'home': f'{home}/CMETA', 'install': 'uv-tool'},
            'sync': {'default': 'none'},
            'made_from': {'template': name, 'base': base_name, 'params': params, 'compute': compute, 'engine': engine, 'image': image,
                          'image_id': rb.get('image_id', ''), 'location': folder, 'carrier': carrier, 'made': made,
                          'cmeta_version': cmeta_version},
            'mounts': mounts + data_mounts,
            'ai': {'notes': f'a WSL distribution made by "cx task run get-host--wsl {name}" on {made}; its readme is {home}/readme-cmeta.md; '
                            f'remove it with "cx host destroy {inst}" (the distribution and its disk)'},
        })
        r = self.cm.utils.files.safe_write_file(os.path.join(apath, '_desc.yaml'), desc, atomic=True, sort_keys=False, logger=self.logger)
        if r['return'] > 0:
            return r

        # ---- the probe: "cx host ls" shows the instance's OS and the versions inside (a probe that fails is said, never fatal)
        r = self.cm.access({'category': HOST_CATEGORY, 'command': 'probe', 'arg1': inst, 'con': False})
        if r['return'] > 0 and con:
            print ('')
            print (f'cMeta warning: the probe of {inst} failed ({r.get("error", "")}) - run "cx host probe {inst}" later')

        if con:
            print ('')
            print (f'cMeta info: instance {inst} ready (WSL distribution at {folder}, from {image}); shell: cx host ssh {inst}; run: cx host run {inst} "cx --version"')
        return {'return': 0, 'host': inst, 'distro': inst, 'image': image, 'made': True, 'status': 'registered',
                'path': apath, 'mounts': mounts + data_mounts, 'location': folder, 'data_repos': [m['repo'] for m in data_mounts]}

    ############################################################
    def _data_mounts(self, data):
        """
        The data repositories to plug into a distribution: those of config::task cache_repos (models, datasets),
        all of them, the subset --data names (keys, aliases, or "key=alias" pairs), or none ("none"); each is plugged
        from its /mnt/<drive> path and becomes a config key inside. The local repository and a repository flagged
        secrets are refused, as for --repos.
        """
        wanted = None
        if str(data or '').strip():
            wanted = [x.strip() for x in str(data).split(',') if x.strip()]
            if wanted == ['none']:
                return {'return': 0, 'mounts': [], 'keys': []}
        r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'read', 'arg1': 'task', 'con': False})
        cache_repos = ((r.get('config_cmeta') or {}).get('cache_repos') or {}) if r.get('return', 1) == 0 else {}
        if not isinstance(cache_repos, dict):
            cache_repos = {}
        if wanted is not None:
            for w in list(wanted):
                if '=' in w:
                    key, _, alias = w.partition('=')
                    cache_repos[key.strip()] = alias.strip()
                    wanted[wanted.index(w)] = key.strip()

        mounts, keys = [], []
        for key, alias in cache_repos.items():
            key, alias = str(key), str(alias)
            if wanted is not None and alias not in wanted and key not in wanted:
                continue
            if alias == 'local':
                return self.cm.error(f'config::task cache_repos.{key} names the local repository: a data repository is one of its own (cx repo init <alias>)')
            a = self._find(REPO_CATEGORY, alias)
            if not a:
                return self.cm.error(f'the data repository "{alias}" (config::task cache_repos.{key}) is not plugged here (cx repo find "*")')
            if (a.get('cmeta') or {}).get('secrets'):
                return self.cm.error(f'the data repository "{alias}" holds secrets (secrets: true) and is never given to an instance')
            name = a['cmeta_ref_parts'].get('artifact_alias') or alias
            path = os.path.realpath(a.get('full_path') or a['path'])
            mounts.append({'repo': name, 'key': key, 'path': path, 'inside': mnt_path(path), 'kind': 'data'})
            keys.append((key, name))
        if wanted is not None:
            missing = [w for w in wanted if w not in cache_repos and w not in [str(v) for v in cache_repos.values()]]
            if missing:
                return self.cm.error(f'no data repository "{", ".join(missing)}" in config::task cache_repos (cx config set task --meta.cache_repos.<key>=<alias>)')
        return {'return': 0, 'mounts': mounts, 'keys': keys}
