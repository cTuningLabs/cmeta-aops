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
  5. records the host artifact in the local repository: type docker, access (container, engine, image, run_args - so
     that "cx host up" can make the container again, with podman when the engine is podman), via = this machine's
     host artifact, made_from (template, params, compute, arch, engine, image, time, cMeta version), mounts, the
     tag made-by-cmeta;
  6. probes it (cx host probe), so that "cx host ls" shows its OS and the cMeta and AOPS versions inside.

The uid rule: on a Linux engine the user inside gets this user's uid and gid (a bind mount keeps the machine's
ownership); rootless podman maps this user to root inside unless told to keep the id (--userns=keep-id).
Everything runs through the engine's own commands (docker run / inspect / start / exec / cp), printed with -v.
"""

import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

CONTAINER_CATEGORY = 'container,ed08f0d107044479'
HOST_CATEGORY = 'host,e4e49c251c814f6d'
REPO_CATEGORY = 'repo,f4f792ab40c7498f'
CONFIG_CATEGORY = 'config,cc6bfe174be847ed'

DEFAULT_TEMPLATE = 'ubuntu'
DEFAULT_REPOS = 'ctuninglabs@cmeta-aops'
KEEPALIVE = ['sleep', 'infinity']
READY_TIMEOUT = 600              # seconds for the entrypoint to plug and index the mounted repositories (minutes on a Docker Desktop bind mount)
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


def template_keys_suffix(params):
    """
    '-t' and a short hash of the template keys other than the OS version (another FROM, a CUDA version or flavour,
    a cmeta-aops checkout): they make another image, so another instance - before 2026-10-17 a request with other
    keys reused the instance made from the first ones. '' without such keys: the names of before. get-host--wsl
    names its instances the same way.
    """
    extra = {str(k): str(v) for k, v in params.items() if str(k) != 'os_version'}
    if not extra:
        return ''
    return '-t' + hashlib.sha256(json.dumps(extra, sort_keys=True).encode('utf-8')).hexdigest()[:6]


def wait_ready(engine, inst, first_repo, con):
    """
    True once the entrypoint has plugged the mounted repositories and built the index: the file ~/.cmeta-ready it
    writes at the end (images built since 2026-10-15); for an older image, the first repository found and no
    "cx --reindex" running. A bind mount through Docker Desktop or podman machine reads thousands of files
    slowly, so the first index takes minutes there (2026-10-15: a run inside started before it was done and
    found no task); a note every 30 s says what is waited for.
    """
    find = f'cx repo find {first_repo}' if first_repo else 'cx --version'
    check = ('if grep -q cmeta-ready "$HOME/entrypoint.sh" 2>/dev/null; then test -f "$HOME/.cmeta-ready"; '
             f'else ! pgrep -f "cx --reindex" >/dev/null 2>&1 && {find} >/dev/null 2>&1; fi')
    t0 = time.monotonic()
    noted = t0
    while time.monotonic() - t0 < READY_TIMEOUT:
        if engine_run(engine, ['exec', inst, 'sh', '-lc', check], timeout=60)[0] == 0:
            return True
        if con and time.monotonic() - noted >= 30:
            print (f'cMeta info: waiting for the instance {inst} to plug and index its repositories ({int(time.monotonic() - t0)} s)')
            noted = time.monotonic()
        time.sleep(2)
    return False


def readme(instance, engine, engine_version, image, name, params, compute, arch, carrier, home, mounts, made, cmeta_version, base=''):
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
        f'- template: {name}' + (f' on {base}' if base else '') + (f', parameters {params}' if params else '') + f', compute {compute}' + (f', architecture {arch}' if arch else ''),
        f'- the container runs "sleep infinity"; the entrypoint plugs the repositories under {home}/repos and reindexes',
        f'- rebuild it: cx container build {name}' + (f' --distro={base}' if base else '') + ''.join(f' --template.{k}={v}' for k, v in (params or {}).items()) + (f' --compute={compute}' if compute != 'cpu' else ''),
        '',
        '## What is mounted from the machine',
        '',
    ]
    for m in mounts:
        lines.append(f'- {m.get("inside") or home + "/repos/" + m["repo"]}  <-  {m["path"]}' + ('  (a data repository: models, datasets)' if m.get('kind') == 'data' else ''))
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

    @staticmethod
    def _keep_user_manager(con):
        """
        Rootless podman on Linux: the containers of a user belong to the user's systemd manager, which stops when the
        user's last session ends unless "linger" is on - an instance started over ssh was stopped with the session
        (seen 2026-10-16 on the T470p: every instance of a test round "Created" again). Linger on for this user
        (loginctl enable-linger, else through a passwordless sudo), said once; a warning with the cure when neither
        works. Undo: loginctl disable-linger.
        """
        user = os.environ.get('USER') or os.environ.get('LOGNAME') or ''
        if not user or user == 'root' or not shutil.which('loginctl'):
            return
        code, out, _ = engine_run('loginctl', ['show-user', user, '-p', 'Linger'], timeout=30)
        if code != 0 or out.strip().lower() == 'linger=yes':
            return
        for cmd in (['loginctl', 'enable-linger', user], ['sudo', '-n', 'loginctl', 'enable-linger', user]):
            if engine_run(cmd[0], cmd[1:], timeout=60)[0] == 0:
                if con:
                    print ('')
                    print (f'cMeta info: linger is on for {user} (loginctl enable-linger): rootless podman instances outlive the '
                           f'session that started them; "loginctl disable-linger" undoes it')
                return
        if con:
            print ('')
            print (f'cMeta warning: linger is off for {user}: a rootless podman instance stops when your last session ends '
                   f'- "sudo loginctl enable-linger {user}" keeps it running')

    @staticmethod
    def _gpu_ready(engine):
        """Linux: the engine can give a container the NVIDIA GPU - docker lists the "nvidia" runtime, podman finds the
        CDI file of the GPUs (what tool/nvidia-container-toolkit sets up)."""
        if engine == 'podman':
            return any(os.path.isfile(p) for p in ('/etc/cdi/nvidia.yaml', '/var/run/cdi/nvidia.yaml', '/run/cdi/nvidia.yaml'))
        try:
            out = subprocess.run(['docker', 'info', '--format', '{{json .Runtimes}}'], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return b'nvidia' in out

    def _carrier(self):
        """
        This machine as a fleet host (alias, uid, machine cRef) when it has a host artifact - "cx host whoami": by
        the system_id its probe recorded, else by the declared hostname - else its hostname.
        """
        r = self.cm.access({'category': HOST_CATEGORY, 'command': 'whoami', 'con': False})
        if r['return'] == 0 and r.get('host'):
            return r['host'], r.get('uid'), r.get('machine')
        return clean_name(platform.node().lower()), None, None

    ############################################################
    def run(self,
            ctx: dict,
            name: str = DEFAULT_TEMPLATE,    # the container template (ubuntu, debian, ...)
            template: dict = {},             # --template.<key>=<value>: the template's parameters (os_version, cmeta_version, ...)
            compute: str = 'cpu',            # cpu, or an overlay of the template (cuda): its base image and GPU run flags
            arch: str = '',                  # arm64 / amd64: --platform linux/<arch> (emulated when the engine is another one)
            engine: str = 'docker',          # docker or podman
            distro: str = '',                # an app template (llama-cpp, vllm-cuda ...): the base it is built on (default: the first of its bases)
            instance: str = '',              # the instance's name (default: <this host>-<engine>-<template>[-<base>]-<os_version>[-<compute>][-<arch>][-t<hash of the other template keys>])
            repos: str = '',                 # repositories of this machine mounted inside, comma-separated (default: ctuninglabs@cmeta-aops)
            data: str = '',                  # data repositories (config::task cache_repos) mounted under <home>/data/<alias>: all by default, a subset, or "none"
            new_host: bool = False,          # another instance of the same place (-2, -3 ...) instead of the existing one
            ports: str = '',                 # ports published on 127.0.0.1 when the instance is made: "8000" or "8080:80", comma-separated (a server run with --on_detach)
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
        if engine == 'podman' and sys.platform.startswith('linux'):
            self._keep_user_manager(con)

        # ---- the template and its parameters; an app template (a stack: llama-cpp, vllm-cuda ...) is built on one of
        # its bases (--base, else the first it lists): the base gives the OS version, the user and the compute
        # overlays, the app adds its own parameters and lines
        t = self._find(CONTAINER_CATEGORY, name)
        if not t:
            return self.cm.error(f'container template "{name}" not found (cx container find "*")')
        tdesc = self._desc(t['path'])
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
        if bdesc is not tdesc:
            tparams.update(tdesc.get('template') or {})
        overlays = dict(bdesc.get('compute') or {})
        if bdesc is not tdesc:
            overlays.update(tdesc.get('compute') or {})
        params = {str(k): str(v) for k, v in (template or {}).items()}
        keys_suffix = template_keys_suffix(params)          # the user's keys only: uid and gid below are this machine's

        # The uid rule: on a Linux engine a bind mount keeps the machine's ownership, so the user inside gets this
        # user's uid and gid (a system uid cannot even plug a mounted repository: cMeta's lock file next to _cmr.yaml
        # is refused). Docker Desktop and podman machine map the ownership themselves: nothing there. Rootless
        # podman maps this user to root inside by default: --userns=keep-id keeps the number (root: a system user)
        keep_id = False
        if os.name == 'posix' and sys.platform != 'darwin' and hasattr(os, 'getuid') and os.getuid() != 0:
            params.setdefault('uid', str(os.getuid()))
            params.setdefault('gid', str(os.getgid()))
            keep_id = engine == 'podman'
        tparams.update(params)
        os_version = str(tparams.get('os_version') or '')
        user = str(tparams.get('user') or 'cmeta')
        home = '/root' if user == 'root' else f'/home/{user}'
        if compute != 'cpu' and compute not in overlays:
            return self.cm.error(f'the template "{name}"{f" on {base_name}" if base_name else ""} has no compute overlay "{compute}" '
                                 f'(it has: {", ".join(overlays.keys()) or "none"})')

        # A CUDA instance on a Linux engine needs the NVIDIA Container Toolkit (docker: the "nvidia" runtime, podman:
        # the CDI file of the GPUs) - asked for explicitly, so a machine without it fails here with the cure instead
        # of a container that starts without its GPU (Docker Desktop on Windows passes the GPU itself)
        if compute == 'cuda' and sys.platform.startswith('linux') and not self._gpu_ready(engine):
            return self.cm.error(f'{engine} here cannot give a container the NVIDIA GPU: the NVIDIA Container Toolkit is '
                                 f'missing or {engine} is not configured for it - '
                                 f'"cx tool setup nvidia-container-toolkit --install" (sudo), then try again')

        arch_norm = ARCHES.get(str(arch).lower(), str(arch).lower()) if arch else ''
        platform_str = f'linux/{arch_norm}' if arch_norm else ''

        # ---- the place and the instance's name
        carrier, carrier_uid, machine = self._carrier()
        stem = clean_name(instance) if instance else clean_name(f'{carrier}-{engine}-{name}' + (f'-{base_name}' if base_name else '')
                                                               + f'-{os_version}' + (f'-{compute}' if compute != 'cpu' else '')
                                                               + (f'-{arch_norm}' if arch_norm else '') + keys_suffix)
        inst = stem
        existing = self._find(HOST_CATEGORY, inst)
        if existing and new_host:
            n = 2
            while self._find(HOST_CATEGORY, f'{stem}-{n}'):
                n += 1
            inst = f'{stem}-{n}'
            existing = None

        # ---- the ports to publish (host:container, on 127.0.0.1): only a container that is made gets them
        published = []
        for p in [x.strip() for x in str(ports or '').split(',') if x.strip()]:
            h, _, c = p.partition(':')
            if not h.isdigit() or (c and not c.isdigit()):
                return self.cm.error(f'--ports: "{p}" is not a port or host:container ports')
            published.append(f'{h}:{c or h}')

        # ---- an existing instance: running, stopped, or gone
        if existing:
            d = self._desc(existing['path'])
            acc = d.get('access') or {}
            missing = [p for p in published if p not in (acc.get('ports') or [])]
            if missing:
                return self.cm.error(f'the instance {inst} was made without the port{"s" if len(missing) > 1 else ""} '
                                     f'{", ".join(missing)} (a container cannot publish a port later): --new_host makes another '
                                     f'instance with them, or cx host destroy {inst} first')
            container = acc.get('container') or inst
            code, out, err = engine_run(engine, ['inspect', '-f', '{{.State.Status}}', container], timeout=60)
            status = out.strip() if code == 0 else 'missing'
            if status == 'running' or (status != 'missing' and engine_run(engine, ['start', container], timeout=120)[0] == 0):
                # a started container runs its entrypoint again (plug, reindex): wait for it as for a new one
                first = ((d.get('mounts') or [{}])[0]).get('repo', '') if status != 'running' else ''
                if status != 'running' and not wait_ready(engine, container, first, con):
                    return self.cm.error(f'the instance {inst} was started but did not get ready within {READY_TIMEOUT} s (cx host ssh {inst} to look)')
                if con:
                    print ('')
                    print (f'cMeta info: instance {inst} {"running" if status == "running" else "started"} ({engine} {engine_version}, image {acc.get("image", "?")}); shell: cx host ssh {inst}')
                return {'return': 0, 'host': inst, 'container': container, 'image': acc.get('image', ''), 'made': False,
                        'status': 'running' if status == 'running' else 'started', 'path': existing['path'], 'ports': acc.get('ports') or [],
                        'data_repos': [m['repo'] for m in (d.get('mounts') or []) if m.get('kind') == 'data']}
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
            # the real path: a link (the Mac's ~/CMETA onto its external drive) is not followed by an engine's VM
            path = os.path.realpath(a.get('full_path') or a['path'])
            mounts.append({'repo': a['cmeta_ref_parts'].get('artifact_alias') or alias, 'path': path, 'inside': f'{home}/repos/{a["cmeta_ref_parts"].get("artifact_alias") or alias}'})

        # ---- the data repositories of this machine (config::task cache_repos: models, datasets - never the tools),
        # mounted under <home>/data/<alias> and plugged inside; the inner config gets the same keys, pointing at them
        r = self._data_mounts(data, home)
        if r['return'] > 0:
            return r
        data_mounts, config_env = r['mounts'], r['env']

        # the template's own config inside its instances (instance_config: {"task.use.python.tool_path": "/opt/venv/bin/python3"}):
        # a stack image tells cMeta inside which Python has its framework; set by the entrypoint like the data keys
        instance_config = dict(bdesc.get('instance_config') or {})
        if bdesc is not tdesc:
            instance_config.update(tdesc.get('instance_config') or {})
        for n, (cfg_key, value) in enumerate(sorted(instance_config.items())):
            config_env.append((str(cfg_key), f'CMETA_INSTANCE_CONFIG_{n}', str(value)))


        # ---- the image, through the container category
        ib = {'category': CONTAINER_CATEGORY, 'command': 'build', 'arg1': name, 'engine': engine,
              'compute': compute, 'template': params, 'platform': platform_str,
              'pull': bool(pull), 'rebuild': bool(rebuild), 'con': con and not quiet, 'quiet': quiet}
        if base_name:
            ib['distro'] = base_name
        rb = self.cm.access(ib)
        if rb['return'] > 0:
            return rb
        image = rb.get('image', '')

        # ---- the container, detached and persistent
        run_flags = []
        if compute != 'cpu':
            rf = (overlays.get(compute) or {}).get('run_flags') or []
            if isinstance(rf, dict):
                rf = rf.get(engine) or []
            run_flags = [str(x) for x in rf]
        for p in published:
            # loopback only: a server of an instance is this machine's until someone exposes it on purpose
            h, _, c = p.partition(':')
            run_flags += ['-p', f'127.0.0.1:{h}:{c}']
        # --init: a small init as PID 1 reaps the orphans of what runs inside (sleep infinity does not): a multi-process
        # program (vLLM's engine) stayed a zombie with live threads and its run never returned (seen 2026-10-17)
        run_args = ['--init', '--hostname', inst, '--label', 'cmeta.container=1', '--label', f'cmeta.host={inst}',
                    '--label', f'cmeta.template={name}', '-e', 'CMETA_REINDEX=1']
        if platform_str:
            run_args += ['--platform', platform_str]
        if keep_id and user != 'root':
            run_args += ['--userns=keep-id']
        run_args += run_flags
        for mnt in mounts + data_mounts:
            run_args += ['-v', f'{mnt["path"]}:{mnt["inside"]}']
        if config_env:
            # the entrypoint sets these config keys inside: task.cache_repos.<key> = the mounted alias
            run_args += ['-e', 'CMETA_CONFIG_FROM_ENV=' + ';'.join(f'{cfg_key}={var}' for cfg_key, var, _ in config_env)]
            for _, var, value in config_env:
                run_args += ['-e', f'{var}={value}']

        engine_run(engine, ['rm', '-f', inst], timeout=120)           # a leftover of a failed attempt, if any
        cmd = ['run', '-d', '--name', inst] + run_args + [image] + KEEPALIVE
        if con and verbose:
            print ('')
            print (f'RUN: {engine} ' + ' '.join(cmd))
        code, out, err = engine_run(engine, cmd, timeout=600)
        if code != 0:
            hint = ''
            if engine == 'podman' and sys.platform == 'darwin' and 'statfs' in (err + out):
                # podman machine shares only the folders it was made with (/Users, /private, /var/folders by default)
                hint = (' - the podman machine does not share that folder: remake it with "podman machine init -v <folder>:<folder>" '
                        '(the Mac mini: its external drive), or use --engine=docker')
            return self.cm.error(f'{engine} run failed: {err.strip() or out.strip()}{hint}')

        # ---- wait until the entrypoint has plugged the repositories and built the index
        first = mounts[0]['repo'] if mounts else ''
        if not wait_ready(engine, inst, first, con):
            code, out, err = engine_run(engine, ['logs', '--tail', '8', inst], timeout=60)
            tail = ' | '.join(l.strip() for l in (out + err).splitlines()[-8:] if l.strip())
            engine_run(engine, ['rm', '-f', inst], timeout=120)
            return self.cm.error(f'the instance {inst} started but its entrypoint did not finish (the repositories plugged and indexed) within {READY_TIMEOUT} s; '
                                 f'the container is removed; its last lines: {tail or "(none)"}')

        # ---- the readme inside
        made = datetime.datetime.now().astimezone().isoformat(timespec='minutes')
        cmeta_version = str(getattr(self.cm, 'version', '') or (ctx['tasks'].get('global', {}).get('init', {}) or {}).get('cmeta_version', '') or '')
        text = readme(inst, engine, engine_version, image, name, params, compute, arch_norm, carrier, home, mounts + data_mounts, made, cmeta_version, base_name)
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
            'access': {'container': inst, 'engine': engine, 'image': image, 'keepalive': ' '.join(KEEPALIVE),
                       'run_args': ' '.join(run_args), 'user': user, 'shell': 'bash -l', 'ports': published},
            'cmeta': {'home': f'{home}/CMETA', 'install': 'uv-tool'},
            'sync': {'default': 'none'},
            'made_from': {'template': name, 'base': base_name, 'params': params, 'compute': compute, 'arch': arch_norm, 'engine': engine,
                          'engine_version': engine_version, 'image': image, 'image_id': rb.get('image_id', ''),
                          'carrier': carrier, 'made': made, 'cmeta_version': cmeta_version},
            'mounts': mounts + data_mounts,
            'ai': {'notes': f'an instance made by "cx task run get-host--docker {name}" on {made}; its readme is {home}/readme-cmeta.md; '
                            f'remove it with "cx host destroy {inst}" (--image removes the image too)'},
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
            print (f'cMeta info: instance {inst} ready ({engine} {engine_version}, image {image}); shell: cx host ssh {inst}; run: cx host run {inst} "cx --version"')
        return {'return': 0, 'host': inst, 'container': inst, 'image': image, 'made': True, 'status': 'running', 'ports': published,
                'path': apath, 'mounts': mounts + data_mounts, 'data_repos': [m['repo'] for m in data_mounts]}

    ############################################################
    def _data_mounts(self, data, home):
        """
        The data repositories to give an instance: the repositories named by the keys of config::task cache_repos
        (models, datasets: what the data tasks keep there), all of them, the subset --data names (keys or aliases),
        or none ("none"). Each becomes a mount under <home>/data/<alias> and one config key inside, set by the
        entrypoint from an environment variable (CMETA_CONFIG_FROM_ENV). The local repository and a repository
        flagged secrets are refused, as for --repos.
        """
        wanted = None
        if str(data or '').strip():
            wanted = [x.strip() for x in str(data).split(',') if x.strip()]
            if wanted == ['none']:
                return {'return': 0, 'mounts': [], 'env': []}
        r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'read', 'arg1': 'task', 'con': False})
        cache_repos = ((r.get('config_cmeta') or {}).get('cache_repos') or {}) if r.get('return', 1) == 0 else {}
        if not isinstance(cache_repos, dict):
            cache_repos = {}
        if wanted is not None:
            # "data=my-models": a key and its repository for this instance, with or without the config key
            for w in list(wanted):
                if '=' in w:
                    key, _, alias = w.partition('=')
                    cache_repos[key.strip()] = alias.strip()
                    wanted[wanted.index(w)] = key.strip()

        mounts, env = [], []
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
                return self.cm.error(f'the data repository "{alias}" holds secrets (secrets: true) and is never mounted into an instance')
            name = a['cmeta_ref_parts'].get('artifact_alias') or alias
            mounts.append({'repo': name, 'key': key, 'path': os.path.realpath(a.get('full_path') or a['path']),
                           'inside': f'{home}/data/{name}', 'kind': 'data'})
            env.append((f'task.cache_repos.{key}', 'CMETA_CACHE_REPO_' + re.sub(r'[^A-Za-z0-9]', '_', key).upper(), name))
        if wanted is not None:
            missing = [w for w in wanted if w not in cache_repos and w not in [str(v) for v in cache_repos.values()]]
            if missing:
                return self.cm.error(f'no data repository "{", ".join(missing)}" in config::task cache_repos (cx config set task --meta.cache_repos.<key>=<alias>)')
        return {'return': 0, 'mounts': mounts, 'env': env}
