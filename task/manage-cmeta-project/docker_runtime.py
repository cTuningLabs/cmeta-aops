"""

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Extracted from the standalone project helpers by Grigori Fursin.
The original notices are retained in the dated project archive.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import shlex
import socket
import subprocess
import time
import urllib.request
import urllib.error

def access(cm, category, command, **params):
    result = cm.access(dict(category=cm._project_categories[category], command=command,
                           con=params.pop('con', True), quiet=True, **params))
    if result.get('return', 1) or result.get('returncode', 0):
        raise RuntimeError(result.get('error') or result.get('stderr') or
                           '{} {} failed'.format(category, command))
    return result


def docker(cm, args, check=True):
    # Older supported engines pass tool-run options into tool setup, which rejects capture_output.
    # Resolve through tool::docker, then use the canonical CMD task to capture/check its output.
    command = getattr(cm, '_project_docker_command', None)
    if command is None:
        tool = access(cm, 'tool', 'setup', arg1=cm._project_dependencies['docker'], con=False)
        command = tool['cmd']
        cm._project_docker_command = command
    quoted = subprocess.list2cmdline(args) if os.name == 'nt' else shlex.join(args)
    result = cm.access(dict(category=cm._project_categories['task'], command='run', arg1=cm._project_dependencies['cmd'],
                            cmd=command + ' ' + quoted, capture_output=True,
                            fail_if_nonzero_return_code=False, con=False, quiet=True))
    if check and (result.get('return', 1) or result.get('returncode', 0)):
        raise RuntimeError(result.get('error') or result.get('stderr') or 'Docker command failed')
    return result


def seed(source, destination):
    """Publish a complete seed atomically. Existing data is never overwritten or merged."""
    if destination.exists():
        marker = destination / SEED_MARKER
        if not marker.is_file() or not any((destination / n).is_file() for n in ('_cmr.yaml', '_cmr.json')):
            raise RuntimeError('Existing Docker repository has no completed seed marker. Preserve/rename it '
                               'and inspect it before retrying: ' + str(destination))
        print('Reusing persistent Docker repository: ' + str(destination), flush=True)
        return json.loads(marker.read_text(encoding='utf-8'))
    if not any((source / n).is_file() for n in ('_cmr.yaml', '_cmr.json')):
        raise RuntimeError('Native local repository is missing: ' + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name('.local-seeding')
    lock = destination.parent / '.local-seeding.lock'
    try:
        handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError('A seed lock exists. Check for another launcher before removing it: ' + str(lock))
    os.close(handle)
    counts = dict(files=0, bytes=0)
    try:
        if staging.exists():
            raise RuntimeError('An interrupted seed remains. Preserve/rename it before retrying: ' + str(staging))
        print('First start: copying local once, excluding top-level cache and tmp ...', flush=True)

        def ignore(directory, names):
            return [n for n in names if n in ('cache', 'tmp')] if Path(directory) == source else []

        def copy(src, dst):
            shutil.copy2(src, dst)
            counts['files'] += 1
            counts['bytes'] += Path(src).stat().st_size
            if counts['files'] % 5000 == 0:
                print('  copied {:,} files'.format(counts['files']), flush=True)
            return dst

        shutil.copytree(source, staging, ignore=ignore, copy_function=copy, symlinks=True)
        record = dict(format=1, source=str(source), created_utc=datetime.now(timezone.utc).isoformat(),
                      excluded=['cache', 'tmp'], **counts)
        (staging / SEED_MARKER).write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        if destination.exists():
            raise RuntimeError('Docker repository appeared during seeding; refusing to replace it')
        staging.rename(destination)
        print('Seed complete: {:,} files, {:.1f} MiB.'.format(counts['files'], counts['bytes'] / 2**20), flush=True)
        return record
    finally:
        lock.unlink()


def seed_empty(home, destination):
    """The persistent local repository of a home: current instance's container: a new, empty repository (its
    data is the instance's state, mounted separately; copying the invoking home's local repo would copy its
    caches and results). Created once; existing data is kept."""
    if destination.exists():
        return seed(None, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name('.local-seeding')
    if staging.exists():
        raise RuntimeError('An interrupted seed remains. Preserve/rename it before retrying: ' + str(staging))
    staging.mkdir()
    identity = Path(home) / 'repos/local/_cmr.yaml'
    if identity.is_file():
        shutil.copy2(identity, staging / '_cmr.yaml')
    else:
        (staging / '_cmr.yaml').write_text('artifact: local,9a3280b14a4285c9\ncategory: repo,f4f792ab40c7498f\n'
                                           'permanent: true\n', encoding='utf-8')
    record = dict(format=1, source='', created_utc=datetime.now(timezone.utc).isoformat(), excluded=['*'], files=0, bytes=0)
    (staging / SEED_MARKER).write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    staging.rename(destination)
    print('First start: created an empty persistent Docker repository: ' + str(destination), flush=True)
    return record


def inspect_owned(cm, name):
    result = docker(cm, ['container', 'inspect', name], check=False)
    if result.get('return', 0) or result.get('returncode', 0):
        if 'No such' in (result.get('stderr') or result.get('error') or ''):
            return None
        raise RuntimeError(result.get('stderr') or result.get('error') or 'Cannot inspect Docker container')
    obj = json.loads(result['stdout'])[0]
    labels = obj.get('Config', {}).get('Labels') or {}
    mounts = {m['Destination']: m['Source'] for m in obj.get('Mounts', [])}

    def normalized(path):
        return str(path).replace('\\', '/').rstrip('/').casefold() if os.name == 'nt' else str(path).rstrip('/')

    if labels.get('cmeta.template') != RECIPE_ALIAS or normalized(mounts.get(INSIDE + '/repos/local', '')) != normalized(DATA):
        raise RuntimeError('Container name is used by another project; refusing to change it: ' + name)
    return obj


def source_repositories(directory=None):
    """Mount physical project repositories; the native local repo has its own Docker replacement."""
    directory = (directory or ROOT / 'repos').resolve()
    paths = []
    for path in sorted(directory.iterdir()):
        if not path.is_dir() or path.name.casefold() == 'local':
            continue
        if not any((path / n).is_file() for n in ('_cmr.yaml', '_cmr.json')):
            continue
        if not path.resolve().is_relative_to(directory):
            raise RuntimeError('A source repository points outside this project: ' + str(path))
        paths.append(path)
    return paths


def run(cm, request, values):
    """Run any declared container recipe with the standalone project's repositories."""
    from runtime import find, contained, artifact_file, expand
    global ROOT, DATA, LOGS, INSIDE, RECIPE_ALIAS, SEED_MARKER
    ROOT = Path(request['root']).resolve()
    # What belongs to this machine: the project home itself, or a home: current instance's state artifact
    MUTABLE = Path(request.get('mutable') or ROOT).resolve()
    shared = bool(request.get('shared'))
    cm._project_categories = request['categories']
    cm._project_dependencies = request['dependencies']
    profile = request['profile']
    definition = profile.get('docker') or {}
    if not definition.get('container'):
        raise ValueError('This project does not declare a Docker container template')
    DATA = contained(MUTABLE, definition.get('local', 'docker/repos/local'))
    LOGS = contained(MUTABLE, definition.get('logs', 'docker/logs'))
    INSIDE = definition.get('home', '/home/cmeta/CMETA')
    SEED_MARKER = definition.get('seed_marker', '.cmeta-project-seed.json')
    recipe = find(cm, request['categories'], definition['container'], 'container')
    RECIPE_ALIAS = recipe['cmeta_ref_parts']['artifact_alias']
    recipe_ref = RECIPE_ALIAS + ',' + recipe['cmeta_ref_parts']['artifact_uid']
    options = request['options']
    name = options.get('name') or definition.get('name') or profile['name'] + '-' + profile['instance']
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        raise ValueError('Invalid container name')
    port = int(values.get('port') or definition.get('port', 8000))
    inside_port = int(definition.get('container_port', port))
    if not 1 <= port <= 65535 or not 1 <= inside_port <= 65535:
        raise ValueError('Port must be between 1 and 65535')
    daemon = docker(cm, ['version', '--format', '{{.Server.Os}}'])
    if (daemon.get('stdout') or '').strip() != 'linux':
        raise ValueError('This project template requires Linux containers')
    existing = inspect_owned(cm, name)
    action = request['action']
    if action in ('status', 'stop', 'logs'):
        if existing is None:
            return {'return': 0, 'running': False, 'name': name, 'data': str(DATA)}
        if action == 'stop':
            docker(cm, ['stop', '--time', '30', name])
            print('Stopped ' + name + '; data retained at ' + str(DATA), flush=True)
        elif action == 'logs':
            result = docker(cm, ['logs', '--tail', '80', name])
            print((result.get('stdout') or '') + (result.get('stderr') or ''))
        result = dict(name=name, running=action != 'stop' and existing['State']['Running'],
                      data=str(DATA), logs=str(LOGS), container_home=INSIDE)
        print(json.dumps(result, indent=2))
        return dict(result, **{'return': 0})
    owns_port = existing and existing['State']['Running'] and any(
        p.get('HostPort') == str(port) for bindings in existing['NetworkSettings'].get('Ports', {}).values()
        for p in (bindings or []))
    if not owns_port:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise ValueError('Port {} is in use; stop its server or choose --params.port'.format(port))
    if shared:
        seed_empty(cm.home_path, DATA)
    else:
        seed(ROOT / 'repos/local', DATA)
    LOGS.mkdir(parents=True, exist_ok=True)
    for destination, source in definition.get('build_files', {}).items():
        source = artifact_file(cm, request['categories'], ROOT, source)
        destination = contained(Path(recipe['path']) / 'files', destination)
        if source.resolve() != destination:
            shutil.copy2(source, destination)
    template = dict(definition.get('template') or {})
    use = request.get('use') or {}
    for key in ('python', 'cmeta'):
        version = options.get(key) or use.get(key, {}).get('version')
        if version:
            if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', str(version)):
                raise ValueError('Image version overrides must be numeric')
            template[key + '_version'] = str(version)
    if os.name != 'nt':
        template.update(uid=str(os.getuid()), gid=str(os.getgid()))
    env_values = dict(values)
    env_values.setdefault('public_url', '')  # Preserve the application's configured public origin.
    env_values.setdefault('env_file', '')
    env_values.setdefault('config', 'local')
    env_file = str(values.get('env_file') or '')
    if env_file and '{' not in env_file and not Path(env_file).is_absolute():
        # A dotenv name inside the application task (the cTuning profiles)
        task = find(cm, request['categories'], profile['task'])
        file = contained(Path(task['path']), env_file)
        if not file.is_file():
            raise ValueError('Dotenv file is missing inside the application task')
    env = {k: str(v).format(**env_values) for k, v in definition.get('env', {}).items()}
    volumes = [str(DATA) + ':' + INSIDE + '/repos/local', str(LOGS) + ':/home/cmeta/logs']
    if shared:
        # the repositories the instance declares, as found in the invoking home (its global repositories)
        sources = [(name, Path(path)) for name, path in request.get('sources') or []]
    else:
        sources = [(p.name, p) for p in source_repositories()]
    volumes.extend(str(p) + ':' + INSIDE + '/repos/' + name + ':ro' for name, p in sources)
    # The state's data is shared with native runs (plain files outside any local repository, so no cache entry
    # of one side reaches the other); the secrets are read-only
    inside = {'cmeta_home': INSIDE, 'secrets': '/home/cmeta/secrets', 'state': '/home/cmeta/state'}
    if request.get('state'):
        volumes.append(str(Path(request['state']) / 'data') + ':' + inside['state'])
    secrets = Path(request.get('secrets') or '')
    if request.get('secrets') and secrets.is_dir():
        volumes.append(str(secrets) + ':' + inside['secrets'] + ':ro')
    # Any recipe can start the declared task with these (the cTuning recipe keeps its own CTUNING_DOCKER_* names)
    task_params = expand(dict(values, host='0.0.0.0', port=inside_port), inside)
    env['CMETA_WEBSITE_TASK'] = str(profile['task']).partition('::')[2] or str(profile['task'])
    env['CMETA_WEBSITE_PARAMS'] = json.dumps(task_params)
    rendered = ROOT / 'docker/rendered'
    rendered.mkdir(parents=True, exist_ok=True)
    access(cm, 'container', 'render', arg1=recipe_ref, engine='docker', template=template,
           out=str(rendered), con=False)
    print('Source repositories: ' + ', '.join(name for name, _ in sources), flush=True)
    access(cm, 'container', 'start', arg1=recipe_ref, engine='docker', template=template,
           name=name, port=[str(port) + ':' + str(inside_port)], volume=volumes,
           env=env, rebuild=bool(options.get('rebuild')))
    deadline = time.monotonic() + float(options.get('wait', 180))
    while time.monotonic() < deadline:
        current = inspect_owned(cm, name)
        if not current or not current['State']['Running']:
            break
        try:
            with urllib.request.urlopen('http://localhost:{}/'.format(port), timeout=4) as response:
                if response.status == 200:
                    url = (env_values['public_url'] or 'http://localhost:' + str(port)).rstrip('/') + '/'
                    print('Persistent data: ' + str(DATA) + '\nBrowse: ' + url, flush=True)
                    return {'return': 0, 'name': name, 'url': url, 'data': str(DATA)}
        except (OSError, urllib.error.HTTPError):
            pass
        time.sleep(2)
    raise RuntimeError('Website did not become ready; inspect ' + str(LOGS))


