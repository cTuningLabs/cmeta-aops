"""Website deployment state. Licensed under Apache-2.0; see COPYRIGHT and LICENSE."""

import copy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid

from cmeta import CMeta
from cmeta.utils.files import PathLock


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.part')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def contained(root, relative):
    parts = str(relative).replace('\\', '/').split('/')
    if any(not part or part in ('.', '..') or ':' in part for part in parts):
        raise ValueError('Deployment paths must be ordinary relative paths')
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Deployment path escapes its state artifact')
    return path


def copy_once(source, destination, repository=False):
    """Preserve deployed edits; publish a completed copy atomically."""
    if destination.exists():
        return
    excluded = {'.git', '.venv', '__pycache__', '!AI', '__symlinks', '.claude'}
    stage = destination.with_name(destination.name + '.incomplete')
    if stage.exists():
        raise ValueError('Inspect interrupted source copy before retrying: ' + str(stage))
    destination.parent.mkdir(parents=True, exist_ok=True)
    def ignored(path, names):
        blocked = excluded | ({'cache', 'result', 'state', 'tmp', 'log'} if repository and Path(path) == source else set())
        return [n for n in names if n in blocked or n.endswith('.pyc')]
    shutil.copytree(source, stage, symlinks=False, ignore=ignored)
    stage.rename(destination)


def checked(cm, request):
    result = cm.access(dict(request, con=False, quiet=True))
    if cm.catch_error(result, fail16=True):
        raise ValueError(result.get('error', 'cMeta operation failed'))
    return result


def export_native(root, profile):
    """Capture declared Linux executables and their libraries without installing host services."""
    final = root / 'tools/native'
    if (final / 'native.json').exists():
        return 0
    stage = root / 'tools/native.incomplete'
    stage.mkdir(parents=True, exist_ok=True)
    binaries = []
    for relative, source in profile.get('files', {}).items():
        destination = contained(stage, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = Path(source)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
            binaries.extend(p for p in source.rglob('*') if p.is_file())
        else:
            shutil.copy2(source, destination)
            binaries.append(source)
    for pattern in profile.get('elf_paths', []):
        binaries.extend(root.glob(pattern))
    libraries = stage / 'lib'
    libraries.mkdir(exist_ok=True)
    glibc = re.compile(r'^(?:libc|libm|libpthread|libdl|librt|libresolv|libutil|libanl|libnss_.*)\.so|^ld-linux')
    env = os.environ.copy()
    python_libraries = list((root / 'volumes/app/runtime').glob('*/payload/python/lib'))
    env['LD_LIBRARY_PATH'] = ':'.join(map(str, python_libraries)) + ':' + env.get('LD_LIBRARY_PATH', '')
    for binary in set(binaries):
        with binary.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        result = subprocess.run(['ldd', str(binary)], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for name in re.findall(r'(?:=>\s+|^\s*)(/[^\s]+)', result.stdout.decode('utf-8', errors='replace'), re.M):
            library = Path(name)
            if not glibc.match(library.name):
                shutil.copy2(library.resolve(), libraries / library.name)
    for name in profile.get('mysql_wrappers', []):
        path = stage / 'mysql/bin' / name
        path.write_text('#!/bin/sh\n\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
            'export LD_LIBRARY_PATH="$root/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
            'exec "$root/libexec/' + name + '" "$@"\n', encoding='utf-8')
        path.chmod(0o755)
    for relative in profile.get('files', {}):
        if relative.startswith('bin/'):
            name = Path(relative).name
            executable = stage / 'libexec' / name
            executable.parent.mkdir(exist_ok=True)
            (stage / relative).rename(executable)
            launcher = stage / relative
            launcher.write_text('#!/bin/sh\n\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
                'export LD_LIBRARY_PATH="$root/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
                'exec "$root/libexec/' + name + '" "$@"\n', encoding='utf-8')
            launcher.chmod(0o755)
    if (stage / 'php/php.ini').exists():
        with (stage / 'php/php.ini').open('a', encoding='utf-8') as stream:
            stream.write('\nextension_dir="${CMETA_WEBSITE_NATIVE_ROOT}/php/extensions"\n')
    loads = stage / 'apache/loads'
    if loads.is_dir():
        text = '\n'.join(p.read_text().replace('/usr/lib/apache2/modules', '${CMETA_WEBSITE_NATIVE_ROOT}/apache/modules')
                         for p in sorted(loads.glob('*.load')))
        (stage / 'apache/modules.load').write_text(text, encoding='utf-8')
    write(stage / 'native.json', dict(format=1, environment=profile.get('environment', {}), platform=sys.platform))
    stage.rename(final)
    print('cMeta info: native software captured in ' + str(final))
    return 0


def worker(root, request_name):
    """Run the staged task with one selected home; caller's orchestrator is unchanged."""
    root = Path(root).resolve()
    manifest = read(root / 'deployment.json')
    request = read(contained(root, request_name))
    if request['action'] == 'export-native':
        return export_native(root, manifest.get('native_export') or {})
    mounts = json.loads(os.environ.get('CMETA_ARTIFACT_MOUNTS') or '{}')
    if not mounts:
        mounts = request['mounts']
    os.environ['CMETA_ARTIFACT_MOUNTS'] = json.dumps(mounts)
    os.environ['CMETA_WEBSITE_WORKSPACE'] = str(root)

    isolated = request['repositories'] == 'isolated'
    home = root / 'CMETA' if isolated else Path(request['orchestrator_home'])
    if isolated and (home / 'repos.json').exists():
        # The private index is derived. Rebase its registered paths when moving between host/container
        # namespaces, retaining every registered repository inside the deployment.
        with PathLock(root / 'repositories.lock'):
            registered = read(home / 'repos.json')
            old_root = next((p.replace('\\', '/')[:-len('/CMETA/repos/local')]
                             for p in registered if p.replace('\\', '/').endswith('/CMETA/repos/local')), None)
            internal = str(Path(sys.modules[CMeta.__module__].__file__).parent / 'internal-repo')
            relocated = old_root and old_root != str(root).replace('\\', '/')
            stale_internal = [name for name in registered if name.replace('\\', '/').endswith('/internal-repo') and name != internal]
            if relocated or stale_internal or internal not in registered:
                rebased = {internal: {}}
                for name, settings in registered.items():
                    normalized = name.replace('\\', '/')
                    if normalized.endswith('/internal-repo'):
                        continue
                    if relocated and normalized.startswith(old_root + '/'):
                        destination = contained(root, normalized[len(old_root) + 1:])
                        rebased[str(destination)] = {k: v for k, v in settings.items() if k != 'unreachable'}
                    elif relocated:
                        raise ValueError('A private repository is outside this deployment; copy it inside before moving: ' + name)
                    else:
                        rebased[name] = settings
                write(home / 'repos.json', rebased)
                if (home / 'index').exists():
                    (home / 'index').rename(root / 'diagnostics' / ('index-before-' + uuid.uuid4().hex))
    os.environ['CMETA_HOME'] = str(home)
    os.environ.pop('CMETA_INTERNAL_REPO_PATH', None)
    native = root / 'tools/native'
    if request.get('mode') == 'native' and (native / 'native.json').exists():
        os.environ['CMETA_WEBSITE_NATIVE_ROOT'] = str(native)
        for key, paths in read(native / 'native.json')['environment'].items():
            if key.startswith('+'):
                name = key[1:]
                os.environ[name] = os.pathsep.join(str(contained(native, p)) for p in paths) + os.pathsep + os.environ.get(name, '')
            else:
                os.environ[key] = str(contained(native, paths))
    cm = CMeta(home=str(home))
    if isolated:
        with PathLock(root / 'repositories.lock'):
            for relative in manifest['repositories']:
                repository = contained(root, relative)
                identity = cm.utils.files.safe_read_yaml_or_json(str(repository / '_cmr'))
                if identity.get('return'):
                    raise ValueError(identity.get('error', 'Missing repository identity'))
                reference = identity['data']['artifact']
                existing = cm.access(dict(category=manifest['categories']['repo'], command='find', arg1=reference, con=False))
                if existing.get('return') not in (0, 16):
                    raise ValueError(existing.get('error', 'Cannot inspect deployed repository'))
                matches = existing.get('artifacts') or []
                if matches and Path(matches[0]['path']).resolve() == repository:
                    continue
                if matches:
                    checked(cm, dict(category=manifest['categories']['repo'], command='unplug', arg1=reference))
                checked(cm, dict(category=manifest['categories']['repo'], command='plug',
                                 arg1=str(repository)))
    options = dict(manifest['params'], **request.get('params', {}))
    options.update(action=request['action'], state_cref=mounts['state']['cref'])
    if request['action'] == 'backup':
        options['backup_cref'] = mounts['backups']['cref']
    result = cm.access(dict(category=manifest['categories']['task'], command='run',
                            arg1=manifest['task'], quiet=True, **options))
    if result.get('return'):
        print('cMeta notice: ' + result.get('error', 'Website task failed'), file=sys.stderr)
    return result.get('return', 1)


if __name__ != '__main__':
    from task_c36be4b9314a45e0.api.ctask import InitCTask

    class CTask(InitCTask):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, module_file_path=__file__, **kwargs)

        def access(self, kind, command, **params):
            return checked(self.cm, dict(category=self.cmeta['uses_categories'][kind], command=command, **params))

        def find(self, cref):
            kind, separator, reference = str(cref).partition('::')
            if not separator:
                kind, reference = 'task', str(cref)
            kind = kind.split(',')[0]
            if kind not in self.cmeta['uses_categories'] or '/' in reference or '\\' in reference:
                raise ValueError('Expected a root website/task/container/result reference')
            matches = self.access(kind, 'find', arg1=reference)['artifacts']
            if len(matches) != 1:
                raise ValueError('Reference must resolve to exactly one artifact: ' + cref)
            return kind, matches[0]

        def desc(self, artifact):
            result = self.cm.utils.files.safe_read_yaml_or_json(str(Path(artifact['path']) / '_desc'))
            if result.get('return'):
                raise ValueError(result.get('error', 'Missing deployment description'))
            return result.get('data') or {}

        def seed_repo(self, destination, alias):
            if not (destination / '_cmr.yaml').exists():
                destination.mkdir(parents=True, exist_ok=True)
                (destination / '_cmr.yaml').write_text(
                    'artifact: ' + alias + ',' + uuid.uuid4().hex[:16] + '\n'
                    'category: ' + self.cmeta['uses_categories']['repo'] + '\nauthors: Grigori Fursin\n', encoding='utf-8')

        def prepare(self, root, artifact, profile, state_cref, backups):
            with PathLock(root / 'prepare.lock'):
                path = root / 'deployment.json'
                if path.exists():
                    manifest = read(path)
                    if manifest['task'].split(',')[-1] != artifact['cmeta_ref_parts']['artifact_uid']:
                        raise ValueError('This state belongs to another task; select another deployment')
                    self.describe_state(root, manifest)
                    return manifest
                # Resolve category ownership rather than pinning the AOPS repository's name.
                category = self.access('category', 'find', arg1=self.cmeta['uses_categories']['task'])['artifacts'][0]
                owner = category['cmeta_ref_parts']['repo_uid']
                tooling = self.access('repo', 'find', arg1=owner)['artifacts'][0]
                if tooling.get('cmeta', {}).get('secrets'):
                    raise ValueError('A secrets repository cannot be used as deployed tooling')
                alias = tooling['cmeta_ref_parts']['artifact_alias']
                tooling_relative = 'CMETA/repos/' + alias
                copy_once(Path(tooling.get('full_path') or tooling['path']), root / tooling_relative, repository=True)
                self.seed_repo(root / 'src', 'website-' + root.name + '-source')
                self.seed_repo(root / 'inputs', 'website-' + root.name + '-inputs')
                refs = ['task::' + artifact['cmeta_ref_parts']['artifact_alias'] + ',' + artifact['cmeta_ref_parts']['artifact_uid']]
                _, runner = self.find('task::' + self.cmeta['artifact'])
                runner_ref = 'task::' + runner['cmeta_ref_parts']['artifact_alias'] + ',' + runner['cmeta_ref_parts']['artifact_uid']
                refs.append(runner_ref)
                if profile.get('container'):
                    refs.append(profile['container'])
                for cref in refs:
                    kind, selected = self.find(cref)
                    selected_alias = selected['cmeta_ref_parts']['artifact_alias']
                    copy_once(Path(selected['path']), root / 'src' / kind / selected_alias)
                    # The selected source must occur once in the private index, even when its owner is the tooling repo.
                    duplicate = root / tooling_relative / kind / selected_alias
                    if duplicate.is_dir():
                        shutil.rmtree(duplicate)
                for cref in profile.get('inputs', []):
                    kind, selected = self.find(cref)
                    if kind != 'result':
                        raise ValueError('Website inputs must be completed result histories')
                    copy_once(Path(selected['path']), root / 'inputs/result' / selected['cmeta_ref_parts']['artifact_alias'])
                (root / 'volumes/app').mkdir(parents=True, exist_ok=True)
                manifest = dict(format=1, task=refs[0].partition('::')[2], container=profile.get('container'),
                    name=profile['name'], params=profile.get('params', {}), state_cref=state_cref,
                    backups=backups, repositories=[tooling_relative, 'src', 'inputs'],
                    worker='src/task/' + runner['cmeta_ref_parts']['artifact_alias'] + '/api_v1.py',
                    categories=self.cmeta['uses_categories'], native_export=profile.get('native_export', {}))
                write(path, manifest)
                self.describe_state(root, manifest)
                print('cMeta info: prepared state ' + state_cref + '\nSource: ' + str(root / 'src'))
                return manifest

        def describe_state(self, root, manifest):
            if not (root / '_desc.yaml').exists():
                descriptor = {
                    'description': 'Mutable deployed website: ' + manifest['name'],
                    'deployment': {'task': 'task::' + manifest['task'], 'container': manifest.get('container'),
                                   'backups': manifest['backups'], 'repositories': manifest['repositories']},
                    'layout': self.cdesc['layout'],
                    'connections': ['task::' + manifest['task'], manifest['backups']]}
                saved = self.cm.utils.files.safe_write_file(str(root / '_desc.yaml'), descriptor)
                if saved.get('return'):
                    raise ValueError(saved.get('error', 'Cannot write state description'))

        def run(self, ctx, website: str = '', action: str = 'run', deployment: str = 'prototype',
                state_cref: str = '', mode: str = '', repositories: str = '', storage: str = '',
                params: dict = {}, detach: bool = False, venv: bool = False,
                worker_request: str = '', workspace: str = '', project_home: str = '',
                current: bool = False, current_env: bool = False, **options):
            try:
                # Explicit standalone/current-home execution does not enter the older state-copy workflow.
                project_definition = False
                if website and not project_home and not current:
                    _, candidate = self.find(website)
                    project_definition = bool(self.desc(candidate).get('project'))
                if project_home or current or project_definition:
                    selected_action = action
                    for flag in ('status', 'stop', 'logs'):
                        if options.pop(flag, False):
                            selected_action = flag
                    return self.access('task', 'run', arg1=self.cdesc['dependencies']['project'],
                        action=selected_action, project_home=project_home,
                        definition=website, current=current or (project_definition and not project_home),
                        current_env=current_env, mode=mode or 'native', params=params,
                        venv=venv, use=ctx.get('tasks', {}).get('use') or {},
                        **(dict(options, detach=True) if detach else options))
                if worker_request:
                    root = Path(workspace).resolve()
                    manifest = read(root / 'deployment.json')
                    code = subprocess.call([sys.executable, str(contained(root, manifest['worker'])), str(root), worker_request])
                    return {'return': code, **({'error': 'Website worker failed; inspect its diagnostics'} if code else {})}
                kind, selected = self.find(website)
                description = self.desc(selected)
                if kind == 'website':
                    task = description.get('deployment', {}).get('task') or description.get('task_automation', {}).get('task')
                    if not task:
                        raise ValueError('Website description needs deployment.task')
                    kind, selected = self.find(task)
                    description = self.desc(selected)
                if kind != 'task' or not description.get('deployment'):
                    raise ValueError('The website task needs a deployment block in _desc.yaml')
                profile = description['deployment']
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', deployment):
                    raise ValueError('deployment must contain ordinary letters, digits, hyphens or underscores')
                state_cref = state_cref or 'state::local:website-' + profile['name'] + '-' + deployment
                state_kind, separator, reference = state_cref.partition('::')
                if not separator or state_kind.split(',')[0] != 'state' or '/' in reference or '\\' in reference:
                    raise ValueError('state-cref must name a root state artifact')
                if action == 'plan':
                    print(json.dumps(dict(state=state_cref, deployment=deployment, profile=profile,
                         modes=['native', 'docker'], repositories=repositories), indent=2))
                    return {'return': 0}
                state = self.access('state', 'get', arg1=reference)['artifact']
                root = Path(state['path']).resolve()
                backup_ref = 'result::local:website-' + profile['name'] + '-' + deployment + '-snapshots'
                if (root / 'deployment.json').exists():
                    backup_ref = read(root / 'deployment.json')['backups']
                backup = self.access('result', 'get', arg1=backup_ref.partition('::')[2],
                                     meta={'permanent': True, 'tags': ['website-backups', profile['name']]})['artifact']
                backup_root = Path(backup['path']).resolve()
                manifest = self.prepare(root, selected, profile, state_cref, backup_ref)
                active = read(root / 'execution.json') if (root / 'execution.json').exists() else {}
                repositories = repositories or active.get('repositories') or 'isolated'
                params = dict(active.get('params') or {}, **params)
                mode = mode or active.get('mode') or profile.get('mode', 'docker')
                if action == 'export-native':
                    mode = 'docker'
                storage = storage or active.get('storage') or ('volume' if sys.platform == 'win32' and mode == 'docker' else 'bind')
                if storage not in ('bind', 'volume') or (storage == 'volume' and mode != 'docker'):
                    raise ValueError('storage=volume requires Docker mode; native execution uses bind storage')
                if active.get('storage') and storage != active['storage']:
                    raise ValueError('Storage cannot change in place; restore a backup into a separate deployment')
                if action == 'status' and active.get('stopped'):
                    print(json.dumps(dict(state=state_cref, path=str(root), running=False, mode=active.get('mode')), indent=2))
                    return {'return': 0, 'running': False, 'state': state_cref}
                if action == 'run' and active.get('mode') and mode != active['mode'] and not active.get('stopped'):
                    raise ValueError('Stop this deployment before switching native/Docker execution')
                if action == 'prepare':
                    return {'return': 0, 'state': state_cref, 'path': str(root), 'source': str(root / 'src')}
                if profile.get('platform') == 'linux' and sys.platform != 'linux' and (mode != 'docker' or storage != 'volume'):
                    raise ValueError('This captured website requires Linux storage and binaries. Run this same command on a Linux/WSL host with --on=<host>; Windows can prepare/sync its portable inputs and source.')
                mounts = {
                    'workspace': dict(cref=state_cref, path=str(root), host_path=str(root), mode='rw', source_os=sys.platform, native=True),
                    'state': dict(cref=state_cref + '/volumes/app', path=str(root / 'volumes/app'), host_path=str(root / 'volumes/app'), mode='rw', source_os=sys.platform, native=True),
                    'backups': dict(cref=backup_ref, path=str(backup_root), host_path=str(backup_root), mode='rw', source_os=sys.platform, native=True)}
                diagnostic = root / 'diagnostics'
                diagnostic.mkdir(exist_ok=True)
                request_name = 'diagnostics/request-' + uuid.uuid4().hex + '.json'
                write(root / request_name, dict(action=action, mode=mode, repositories=repositories,
                    params=params, mounts=mounts, orchestrator_home=str(self.cm.home_path)))
                log = diagnostic / (Path(request_name).stem + '.log')
                if action == 'run':
                    write(root / 'execution.json', dict(mode=mode, repositories=repositories, storage=storage, params=params, stopped=False))
                if mode == 'native':
                    python = sys.executable
                    if venv:
                        environment = root / '.venv'
                        executable = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
                        if not executable.exists():
                            subprocess.check_call([python, '-m', 'venv', str(environment)])
                        use = copy.deepcopy(ctx['tasks'].get('use') or {})
                        use.setdefault('python', {})['tool_path'] = str(executable)
                        self.access('task', 'run', arg1=self.cdesc['dependencies']['setup'],
                                    name=self.cdesc['dependencies']['cmeta'], use=use)
                        python = str(executable)
                    argv = [python, str(contained(root, manifest['worker'])), str(root), request_name]
                    env = os.environ.copy()
                    env.pop('CMETA_ARTIFACT_MOUNTS', None)
                    if detach and action == 'run':
                        with log.open('ab') as output:
                            options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if os.name == 'nt' else {'start_new_session': True}
                            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output, stderr=output, env=env, **options)
                        print('cMeta info: native website process ' + str(process.pid) + '\nLog: ' + str(log))
                        return {'return': 0, 'pid': process.pid, 'log': str(log), 'state': state_cref}
                    code = subprocess.call(argv, env=env)
                    if action == 'stop' and not code:
                        write(root / 'execution.json', dict(active, stopped=True))
                    return {'return': code, 'state': state_cref, **({'error': 'Native website action failed'} if code else {})}
                if mode != 'docker' or repositories != 'isolated':
                    raise ValueError('Docker execution uses isolated deployed repositories')
                owner = self.access('category', 'find', arg1=self.cmeta['uses_categories']['task'])['artifacts'][0]['cmeta_ref_parts']['repo_uid']
                resolved = self.access('task', 'run', arg1=self.cdesc['dependencies']['resolver'],
                    name=manifest['container'].partition('::')[2], instance=root.name, repos=owner, data='none',
                    ports=str(params.get('port', manifest['params'].get('port', 8128))),
                    artifacts={'workspace': state_cref,
                               'state': dict(cref=state_cref + '/volumes/app', storage=storage), 'backups': backup_ref})
                inside = '/home/cmeta/artifacts/workspace'
                words = ['cx', 'task', 'run', 'run-website,' + self.cmeta['artifact'].split(',')[-1],
                         '--workspace=' + inside, '--worker_request=' + request_name, '-q']
                command = shlex.join(words)
                # A moved launcher need not live in the tooling owner's repository.
                bootstrap = ('cx task find ' + shlex.quote(self.cmeta['artifact']) + ' -q >/dev/null 2>&1 || '
                             'cx repo plug ' + shlex.quote(inside + '/src') + ' -q\n')
                if detach and action == 'run':
                    inner_log = inside + '/diagnostics/' + log.name
                    command = 'nohup ' + command + ' > ' + shlex.quote(inner_log) + ' 2>&1 < /dev/null &\nsleep 3\n'
                script = diagnostic / (Path(request_name).stem + '.sh')
                with script.open('w', encoding='utf-8', newline='\n') as stream:
                    stream.write('#!/bin/bash\nset -eu\n\n' + bootstrap + command + '\n')
                result = self.access('host', 'run', arg1=resolved['host'], script=str(script))
                if action == 'stop':
                    self.access('host', 'down', arg1=resolved['host'])
                    write(root / 'execution.json', dict(active, stopped=True))
                print('cMeta info: state ' + state_cref + '\nPath: ' + str(root) + '\nLog: ' + str(log))
                if storage == 'volume':
                    print('cMeta info: application files use the registered Linux volume; see ' + str(root / 'volumes/app/.cmeta-volume.json'))
                return dict(result, state=state_cref, path=str(root), log=str(log))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                return self.cm.error(str(error))


if __name__ == '__main__':
    try:
        sys.exit(worker(sys.argv[1], sys.argv[2]))
    except (OSError, ValueError) as error:
        print('cMeta notice: ' + str(error), file=sys.stderr)
        sys.exit(1)
