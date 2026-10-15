"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

get-host--docker: a docker (or podman) instance of a container template, recorded as a host artifact - the first
resolver of the "run on any host" design (an instance of a template is a host like any other). What it does:

  1. names the instance after the place: <this host>-<engine>-<template>-<os_version>[-<compute>][-<arch>], this
     host being its fleet alias when this machine has a host artifact, else its hostname (--instance names it);
  2. finds the instance's host artifact: its container running -> returned; stopped -> started; gone -> made again;
  3. else builds the template's image through the container category (cx container build), runs the container
     detached under that name with "sleep infinity", the labels cmeta.container=1 and cmeta.host=<instance>, the
     repositories asked for mounted at <home>/repos/<alias> (the entrypoint plugs them and reindexes; the local
     repository and a repository flagged secrets are never mounted), the GPU run flags of the template's compute
     overlay when asked for, --platform for another architecture;
  4. writes <home>/readme-cmeta.md inside (what it is, how it was made, how to reach it, how to rebuild it);
  5. records the host artifact in the local repository: type docker, access (container, image, run_args - so that
     "cx host up" can make the container again), via = this machine's host artifact, made_from (template, params,
     compute, arch, engine, image, time, cMeta version), mounts, the tag made-by-cmeta.

Everything runs through the engine's own commands (docker run / inspect / start / exec / cp), printed with -v.
"""

import datetime
import os
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

DEFAULT_TEMPLATE = 'ubuntu'
DEFAULT_REPOS = 'ctuninglabs@cmeta-aops'
KEEPALIVE = ['sleep', 'infinity']
ARCHES = {'arm64': 'arm64', 'aarch64': 'arm64', 'amd64': 'amd64', 'x86_64': 'amd64', 'x64': 'amd64'}


def engine_run(engine, args, timeout=600):
    """One engine command: (return code, stdout, stderr) as text; bytes decoded, never text=True."""
    try:
        r = subprocess.run([engine] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, '', str(e)
    return r.returncode, r.stdout.decode('utf-8', errors='replace'), r.stderr.decode('utf-8', errors='replace')


def clean_name(text):
    """A container and artifact name: lower case, letters, digits, dots and dashes."""
    return re.sub(r'[^a-z0-9.]+', '-', str(text).lower()).strip('-.')


def readme(instance, engine, engine_version, image, name, params, compute, arch, carrier, home, mounts, made, cmeta_version):
    """The readme-cmeta.md written into the instance's home."""
    lines = [
        f'# {instance}',
        '',
        f'A cMeta instance of the container template "{name}": a persistent {engine} container made on {made} on the',
        f'machine "{carrier}" by cMeta {cmeta_version} (cx task run get-host--docker), to run cMeta tasks, tools and',
        'programs in a stable environment separate from the machine\'s own cache.',
        '',
        '## How it was made',
        '',
        f'- image: {image} ({engine} {engine_version})',
        f'- template: {name}' + (f', parameters {params}' if params else '') + f', compute {compute}' + (f', architecture {arch}' if arch else ''),
        f'- the container runs "sleep infinity"; the entrypoint plugs the repositories under {home}/repos and reindexes',
        f'- rebuild it: cx container build {name}' + ''.join(f' --template.{k}={v}' for k, v in (params or {}).items()) + (f' --compute={compute}' if compute != 'cpu' else ''),
        '',
        '## What is mounted from the machine',
        '',
    ]
    for m in mounts:
        lines.append(f'- {home}/repos/{m["repo"]}  <-  {m["path"]}')
    if not mounts:
        lines.append('- nothing')
    lines += [
        '',
        '## How to reach it from the machine',
        '',
        f'- cx host run {instance} "cx --version"',
        f'- cx host ssh {instance}',
        f'- cx host down {instance} / cx host up {instance}     (the container keeps its cache across stop and start)',
        f'- cx host destroy {instance} [--image]                      (the container, the artifact, the image)',
        f'- {engine} exec -it {instance} bash -l                   (by hand)',
        '',
        f'The cMeta home inside is {home}/CMETA: its cache is this instance\'s own and is never shared with the machine.',
        '',
    ]
    return '\n'.join(lines)


class CTask(InitCTask):
    """
    A docker instance of a container template as a host artifact.
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
        """This machine as a fleet host (alias, uid, machine cRef) when it has a host artifact, else its hostname."""
        node = platform.node().lower()
        r = self.cm.access({'category': HOST_CATEGORY, 'command': 'find', 'arg1': '*', 'con': False})
        for a in (r.get('artifacts') or []) if r['return'] == 0 else []:
            d = self._desc(a['path'])
            if str((d.get('access') or {}).get('hostname', '')).lower() == node and d.get('type') == 'ssh':
                parts = a['cmeta_ref_parts']
                return parts['artifact_alias'], parts.get('artifact_uid'), d.get('machine')
        return clean_name(node), None, None

    ############################################################
    def run(self,
            ctx: dict,
            name: str = DEFAULT_TEMPLATE,    # the container template (ubuntu, debian, ...)
            template: dict = {},             # --template.<key>=<value>: the template's parameters (os_version, cmeta_version, ...)
            compute: str = 'cpu',            # cpu, or an overlay of the template (cuda): its base image and GPU run flags
            arch: str = '',                  # arm64 / amd64: --platform linux/<arch> (emulated when the engine is another one)
            engine: str = 'docker',          # docker or podman
            instance: str = '',              # the instance's name (default: <this host>-<engine>-<template>-<os_version>[-<compute>][-<arch>])
            repos: str = '',                 # repositories of this machine mounted inside, comma-separated (default: ctuninglabs@cmeta-aops)
            new_host: bool = False,          # another instance of the same place (-2, -3 ...) instead of the existing one
            pull: bool = False,              # pull the base image again when building
            rebuild: bool = False,           # build the image again
    ):
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        code, out, err = engine_run(engine, ['--version'], timeout=30)
        if code != 0:
            return self.cm.error(f'{engine} is not usable here ({err.strip() or out.strip() or "not found"}): cx tool setup {engine} --install')
        m = re.search(r'version v?(\d+\.\d+\.\d+)', out)
        engine_version = m.group(1) if m else out.strip()

        # ---- the template and its parameters
        t = self._find(CONTAINER_CATEGORY, name)
        if not t:
            return self.cm.error(f'container template "{name}" not found (cx container find "*")')
        tdesc = self._desc(t['path'])
        tparams = dict(tdesc.get('template') or {})
        params = {str(k): str(v) for k, v in (template or {}).items()}

        # The uid rule: on a Linux engine a bind mount keeps the machine's ownership, so the user inside gets this
        # user's uid and gid (a system uid cannot even plug a mounted repository: cMeta's lock file next to _cmr.yaml
        # is refused). Docker Desktop and podman machine map the ownership themselves: nothing there.
        if os.name == 'posix' and sys.platform != 'darwin' and hasattr(os, 'getuid'):
            params.setdefault('uid', str(os.getuid()))
            params.setdefault('gid', str(os.getgid()))
        tparams.update(params)
        os_version = str(tparams.get('os_version') or '')
        user = str(tparams.get('user') or 'cmeta')
        home = '/root' if user == 'root' else f'/home/{user}'
        if compute != 'cpu' and compute not in (tdesc.get('compute') or {}):
            return self.cm.error(f'the template "{name}" has no compute overlay "{compute}" (it has: {", ".join((tdesc.get("compute") or {}).keys()) or "none"})')

        arch_norm = ARCHES.get(str(arch).lower(), str(arch).lower()) if arch else ''
        platform_str = f'linux/{arch_norm}' if arch_norm else ''

        # ---- the place and the instance's name
        carrier, carrier_uid, machine = self._carrier()
        base_name = clean_name(instance) if instance else clean_name(f'{carrier}-{engine}-{name}-{os_version}' + (f'-{compute}' if compute != 'cpu' else '') + (f'-{arch_norm}' if arch_norm else ''))
        inst = base_name
        existing = self._find(HOST_CATEGORY, inst)
        if existing and new_host:
            n = 2
            while self._find(HOST_CATEGORY, f'{base_name}-{n}'):
                n += 1
            inst = f'{base_name}-{n}'
            existing = None

        # ---- an existing instance: running, stopped, or gone
        if existing:
            d = self._desc(existing['path'])
            acc = d.get('access') or {}
            container = acc.get('container') or inst
            code, out, err = engine_run(engine, ['inspect', '-f', '{{.State.Status}}', container], timeout=60)
            status = out.strip() if code == 0 else 'missing'
            if status == 'running' or (status != 'missing' and engine_run(engine, ['start', container], timeout=120)[0] == 0):
                if con:
                    print ('')
                    print (f'cMeta info: instance {inst} {"running" if status == "running" else "started"} ({engine} {engine_version}, image {acc.get("image", "?")}); shell: cx host ssh {inst}')
                return {'return': 0, 'host': inst, 'container': container, 'image': acc.get('image', ''), 'made': False,
                        'status': 'running' if status == 'running' else 'started', 'path': existing['path']}
            if con:
                print ('')
                print (f'cMeta info: the container {container} of the instance {inst} is gone - made again')

        # ---- the repositories mounted inside
        mounts = []
        for alias in [x.strip() for x in str(repos or DEFAULT_REPOS).split(',') if x.strip()]:
            if alias == 'local':
                return self.cm.error('the local repository is never mounted into an instance (its cache is this machine\'s)')
            a = self._find(REPO_CATEGORY, alias)
            if not a:
                return self.cm.error(f'repository "{alias}" is not plugged here (cx repo find "*")')
            if (a.get('cmeta') or {}).get('secrets'):
                return self.cm.error(f'repository "{alias}" holds secrets (secrets: true in its _cmr.yaml) and is never mounted into an instance')
            path = a.get('full_path') or a['path']
            mounts.append({'repo': a['cmeta_ref_parts'].get('artifact_alias') or alias, 'path': path, 'inside': f'{home}/repos/{a["cmeta_ref_parts"].get("artifact_alias") or alias}'})

        # ---- the image, through the container category
        rb = self.cm.access({'category': CONTAINER_CATEGORY, 'command': 'build', 'arg1': name, 'engine': engine,
                             'compute': compute, 'template': params, 'platform': platform_str,
                             'pull': bool(pull), 'rebuild': bool(rebuild), 'con': con and not quiet, 'quiet': quiet})
        if rb['return'] > 0:
            return rb
        image = rb.get('image', '')

        # ---- the container, detached and persistent
        run_flags = []
        if compute != 'cpu':
            rf = ((tdesc.get('compute') or {}).get(compute) or {}).get('run_flags') or []
            if isinstance(rf, dict):
                rf = rf.get(engine) or []
            run_flags = [str(x) for x in rf]
        run_args = ['--hostname', inst, '--label', 'cmeta.container=1', '--label', f'cmeta.host={inst}',
                    '--label', f'cmeta.template={name}', '-e', 'CMETA_REINDEX=1']
        if platform_str:
            run_args += ['--platform', platform_str]
        run_args += run_flags
        for mnt in mounts:
            run_args += ['-v', f'{mnt["path"]}:{mnt["inside"]}']

        engine_run(engine, ['rm', '-f', inst], timeout=120)           # a leftover of a failed attempt, if any
        cmd = ['run', '-d', '--name', inst] + run_args + [image] + KEEPALIVE
        if con and verbose:
            print ('')
            print (f'RUN: {engine} ' + ' '.join(cmd))
        code, out, err = engine_run(engine, cmd, timeout=600)
        if code != 0:
            return self.cm.error(f'{engine} run failed: {err.strip() or out.strip()}')

        # ---- wait until the entrypoint has plugged the repositories and reindexed
        first = mounts[0]['repo'] if mounts else ''
        ready = False
        t0 = time.monotonic()
        while time.monotonic() - t0 < 120:
            probe = ['exec', inst, 'sh', '-lc', f'cx repo find {first}' if first else 'cx --version']
            if engine_run(engine, probe, timeout=60)[0] == 0:
                ready = True
                break
            time.sleep(2)
        if not ready:
            code, out, err = engine_run(engine, ['logs', '--tail', '8', inst], timeout=60)
            tail = ' | '.join(l.strip() for l in (out + err).splitlines()[-8:] if l.strip())
            engine_run(engine, ['rm', '-f', inst], timeout=120)
            return self.cm.error(f'the instance {inst} started but cx inside did not see the repository {first or "(none)"} within 120 s; '
                                 f'the container is removed; its last lines: {tail or "(none)"}')

        # ---- the readme inside
        made = datetime.datetime.now().astimezone().isoformat(timespec='minutes')
        cmeta_version = str(getattr(self.cm, 'version', '') or (ctx['tasks'].get('global', {}).get('init', {}) or {}).get('cmeta_version', '') or '')
        text = readme(inst, engine, engine_version, image, name, params, compute, arch_norm, carrier, home, mounts, made, cmeta_version)
        fd, tmp = tempfile.mkstemp(prefix='readme-cmeta-', suffix='.md')
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        try:
            engine_run(engine, ['cp', tmp, f'{inst}:{home}/readme-cmeta.md'], timeout=60)
            if user != 'root':
                engine_run(engine, ['exec', '-u', 'root', inst, 'chown', f'{user}:{user}', f'{home}/readme-cmeta.md'], timeout=60)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

        # ---- the host artifact in the local repository
        if existing:
            apath = existing['path']
        else:
            r = self.cm.access({'category': HOST_CATEGORY, 'command': 'create', 'arg1': f'local:{inst}', 'yaml': True,
                                'tags': ['made-by-cmeta', engine, name], 'con': False})
            if r['return'] > 0:
                return r
            apath = r['path']
        desc = {}
        if machine:
            desc['machine'] = machine
        desc.update({
            'type': 'docker',
            'os': str(tdesc.get('os') or name),
        })
        if carrier_uid:
            desc['via'] = f'host,{HOST_CATEGORY.split(",")[1]}::{carrier},{carrier_uid}'
        desc.update({
            'access': {'container': inst, 'image': image, 'keepalive': ' '.join(KEEPALIVE),
                       'run_args': ' '.join(run_args), 'user': user, 'shell': 'bash -l'},
            'cmeta': {'home': f'{home}/CMETA', 'install': 'uv-tool'},
            'sync': {'default': 'none'},
            'made_from': {'template': name, 'params': params, 'compute': compute, 'arch': arch_norm, 'engine': engine,
                          'engine_version': engine_version, 'image': image, 'image_id': rb.get('image_id', ''),
                          'carrier': carrier, 'made': made, 'cmeta_version': cmeta_version},
            'mounts': mounts,
            'ai': {'notes': f'an instance made by "cx task run get-host--docker {name}" on {made}; its readme is {home}/readme-cmeta.md; '
                            f'remove it with "cx host destroy {inst}" (--image removes the image too)'},
        })
        r = self.cm.utils.files.safe_write_file(os.path.join(apath, '_desc.yaml'), desc, atomic=True, sort_keys=False, logger=self.logger)
        if r['return'] > 0:
            return r

        if con:
            print ('')
            print (f'cMeta info: instance {inst} ready ({engine} {engine_version}, image {image}); shell: cx host ssh {inst}; run: cx host run {inst} "cx --version"')
        return {'return': 0, 'host': inst, 'container': inst, 'image': image, 'made': True, 'status': 'running',
                'path': apath, 'mounts': mounts}
