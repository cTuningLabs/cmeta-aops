"""

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Child-process runtime for manage-cmeta-project. State belongs to the selected home.
"""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from cmeta import CMeta


def checked(result):
    if result.get('return', 1) or result.get('returncode', 0):
        raise RuntimeError(result.get('error') or result.get('stderr') or 'cMeta operation failed')
    return result


def contained(root, relative):
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise ValueError('Path must remain inside the project: ' + str(relative))
    return path


def repositories(root):
    directory = root / 'repos'
    if not directory.is_dir():
        return []
    return [contained(directory, p.name) for p in sorted(directory.iterdir()) if p.is_dir()
            and any((p / n).is_file() for n in ('_cmr.yaml', '_cmr.json'))]


def shared_home(profile):
    """home: current - the website runs in the invoking cMeta home (one site per machine). Its instance folder
    holds only project.yaml and the scripts; its repositories are the home's own."""
    return str((profile or {}).get('home') or 'project') == 'current'


def expand(value, mapping):
    """Replace {state}, {secrets}, {cmeta_home} and {root} in the strings of params; other braces stay."""
    if isinstance(value, str):
        for key, text in mapping.items():
            value = value.replace('{' + key + '}', text)
        return value
    if isinstance(value, dict):
        return {k: expand(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, mapping) for v in value]
    return value


def instance_state(cm, categories, profile):
    """The protected state artifact of an instance (created with its folders on first use), or None."""
    reference = profile.get('state')
    if not reference:
        return None
    kind, sep, alias = str(reference).partition('::')
    if not sep or kind.split(',')[0] != 'state' or '/' in alias or '\\' in alias:
        raise ValueError('state must name a root state artifact, e.g. state::local:website-<site>')
    artifact = checked(cm.access(dict(category=categories['state'], command='get', arg1=alias, con=False)))['artifact']
    path = Path(artifact['path']).resolve()
    for name in ('data', 'secrets', 'runtime'):
        (path / name).mkdir(exist_ok=True)
    if os.name != 'nt':
        (path / 'secrets').chmod(0o700)
    return path


def mutable_root(root, state, shared):
    """Where an instance keeps what belongs to this machine (runtime files, secrets, the Docker local repo): a
    project home itself; for a current-home instance its state artifact, outside every synced repository."""
    if not shared:
        return root
    if state is None:
        raise ValueError('A home: current instance needs state: state::local:website-<site> in project.yaml')
    return state


def runtime_dir(root, state, shared):
    return (state / 'runtime') if shared else (root / '.setup/runtime')


def secrets_dir(root, state, shared):
    return (state / 'secrets') if shared else (root / '.setup/secrets')


def pid_alive(pid):
    """True while the process exists (Windows: its exit code is still STILL_ACTIVE)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_tree(pid, wait=15):
    """Stop a background server and every process under it (its uvicorn child too), then wait for it."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        import signal
        listing = subprocess.run(['ps', '-e', '-o', 'pid=,ppid='], stdout=subprocess.PIPE, text=True).stdout
        children = {}
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) == 2:
                children.setdefault(int(parts[1]), []).append(int(parts[0]))
        tree, todo = [], [int(pid)]
        while todo:
            current = todo.pop()
            tree.append(current)
            todo.extend(children.get(current, []))
        for target in reversed(tree):
            try:
                os.kill(target, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + wait
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    return not pid_alive(pid)


def read_pid(path):
    try:
        return int(path.read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return 0


def tail(path, lines=80):
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 64 * 1024))
            text = f.read().decode('utf-8', errors='replace')
    except OSError:
        return ''
    return '\n'.join(text.splitlines()[-lines:])


def register(cm, root):
    """Rebuild relocatable standalone registrations, including this interpreter's own engine."""
    import cmeta
    checked(cm.repos.init())
    paths = repositories(root)
    paths.append(Path(cmeta.__file__).resolve().parent / 'internal-repo')
    read = checked(cm.utils.files.safe_read_file(cm.repos_config_path, lock=True, keep_locked=True))
    previous = read['data']
    by_name = {Path(p).name: meta for p, meta in previous.items()}
    checked(cm.utils.files.safe_write_file(cm.repos_config_path,
        {str(p): previous.get(str(p), by_name.get(p.name, {})) for p in paths},
        file_lock=read['file_lock'], atomic=True, sort_keys=False))
    checked(cm.repos.index(clean=True))
    return [str(p) for p in paths]


def find(cm, categories, reference, default='task'):
    kind, sep, alias = str(reference).partition('::')
    if not sep:
        kind, alias = default, str(reference)
    kind = kind.split(',')[0]
    result = checked(cm.access(dict(category=categories[kind], command='find', arg1=alias, con=False)))
    if len(result['artifacts']) != 1:
        raise ValueError('Expected one artifact: ' + reference)
    return result['artifacts'][0]


def artifact_file(cm, categories, root, value):
    if '::' not in value:
        return contained(root, value)
    reference, sep, relative = value.partition('/')
    artifact = find(cm, categories, reference)
    return contained(Path(artifact['path']), relative) if sep else Path(artifact['path'])


def environment(root, python, current=False):
    env = os.environ.copy()
    env['CMETA_HOME'] = str(root)
    if not current:
        env.pop('CMETA_INTERNAL_REPO_PATH', None)
        env.pop('CMETA_TOOL_EXTRA_PATHS', None)
        env['UV_PYTHON_INSTALL_DIR'] = str(root / '.setup/tools/python')
        env['UV_CACHE_DIR'] = str(root / '.setup/tools/uv-cache')
    executable = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if Path(python).resolve() == executable.resolve():
        env['VIRTUAL_ENV'] = str(root / '.venv')
        env['PATH'] = str(executable.parent) + os.pathsep + env.get('PATH', '')
    return env


def execute(args, env, cwd, capture=False):
    completed = subprocess.run([str(a) for a in args], env=env, cwd=str(cwd),
                               stdout=subprocess.PIPE if capture else None,
                               text=True, encoding='utf-8', errors='replace')
    if completed.returncode:
        raise RuntimeError('Command failed with exit code {}: {}'.format(completed.returncode, args[0]))
    return completed.stdout if capture else None


def child_request(python, request, env, root):
    child = subprocess.Popen([str(python), '-u', __file__], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, env=env, cwd=str(root), text=True,
                             encoding='utf-8', errors='replace')
    child.stdin.write(json.dumps(request))
    child.stdin.close()
    result = None
    for line in child.stdout:
        if line.startswith('CMETA_PROJECT_RESULT='):
            result = json.loads(line.partition('=')[2])
        else:
            print(line, end='', flush=True)
    code = child.wait()
    if result:
        return checked(result)
    raise RuntimeError('Selected project interpreter returned no result (exit {})'.format(code))


def bootstrap(cm, request):
    root, profile = Path(request['root']), request['profile']
    checked(cm.repos.init())
    for item in profile.get('repositories', []):
        name = item['name'].split(',')[0]
        if name in ('local', '.', '..') or '/' in name or '\\' in name:
            raise ValueError('Invalid bootstrap repository name: ' + name)
        destination = contained(root / 'repos', name)
        if destination.exists():
            if not any((destination / n).is_file() for n in ('_cmr.yaml', '_cmr.json')):
                raise ValueError('Existing directory is not a repository: ' + str(destination))
            continue
        if item.get('source'):
            source = Path(os.path.expanduser(item['source'])).resolve()
            if destination.is_relative_to(source):
                raise ValueError('Bootstrap destination must not be inside its source repository: ' + name)
            if not any((source / n).is_file() for n in ('_cmr.yaml', '_cmr.json')):
                raise ValueError('Bootstrap source is not a repository: ' + str(source))
            stage = destination.with_name(destination.name + '.incomplete')
            if stage.exists():
                raise ValueError('Inspect the incomplete bootstrap copy: ' + str(stage))
            shutil.copytree(source, stage, ignore=shutil.ignore_patterns('__pycache__', '.venv', '__symlinks'))
            stage.rename(destination)
        elif item.get('url') or item.get('zip_file'):
            args = dict(category=request['categories']['repo'], command='pull', arg1=item['name'],
                        quiet=True, con=True)
            args.update({k: item[k] for k in ('url', 'zip_file', 'checkout', 'depth') if k in item})
            checked(cm.access(args))
        elif item.get('required', True):
            raise ValueError('Provide repository {} under {} or declare its url/source/zip_file before bootstrap'.format(name, root / 'repos'))
    register(cm, root)


def shared_repositories(cm, request, pull=False):
    """[(folder name, path)] of the repositories a current-home instance declares, found in the invoking home.
    With pull (bootstrap), a missing one that declares url/zip_file is fetched like cx repo pull does; a
    missing required one is an error that names it."""
    found, missing = [], []
    for item in request['profile'].get('repositories', []):
        name = str(item['name'])
        r = cm.access(dict(category=request['categories']['repo'], command='find', arg1=name, con=False))
        artifacts = r.get('artifacts') or [] if r.get('return', 1) == 0 else []
        if not artifacts and pull and (item.get('url') or item.get('zip_file')):
            args = dict(category=request['categories']['repo'], command='pull', arg1=name, quiet=True, con=True)
            args.update({k: item[k] for k in ('url', 'zip_file', 'checkout', 'depth') if k in item})
            checked(cm.access(args))
            r = cm.access(dict(category=request['categories']['repo'], command='find', arg1=name, con=False))
            artifacts = r.get('artifacts') or [] if r.get('return', 1) == 0 else []
        if artifacts:
            # the repository's root (with its _cmr.yaml, which may name a subdir), mounted under its alias
            path = Path(artifacts[0]['path']).resolve()
            alias = (artifacts[0].get('cmeta_ref_parts') or {}).get('artifact_alias') or path.name
            found.append((alias, path))
        elif item.get('required', True):
            missing.append(name)
    if missing:
        raise ValueError('Plug these repositories into this cMeta home first (cx repo get / plug): ' + ', '.join(missing))
    return found


def config(cm, request):
    root, profile = Path(request['root']), request['profile']
    values = parameters(profile, request)
    replacements = dict(cmeta_home=str(root), port=values.get('port', ''))
    for name, meta in profile.get('runtime_config', {}).items():
        meta = {k: v.format(**replacements) if isinstance(v, str) else v for k, v in meta.items()}
        checked(cm.access(dict(category=request['categories']['config'], command='set',
                               arg1='local:' + name, meta=meta, quiet=True, con=False)))


def parameters(profile, request):
    values = copy.deepcopy(profile.get('params') or {})
    defaults = profile.get('os_params', {}).get('windows' if os.name == 'nt' else 'linux', {})
    values.update(defaults)
    values.update(request.get('params') or {})
    options = request.get('options') or {}
    for key in ('host', 'port', 'config', 'env_file', 'public_url'):
        if key in options:
            values[key] = options[key]
    return values


def setup(cm, request):
    root, profile = Path(request['root']), request['profile']
    if request['current']:
        if request['venv']:
            raise ValueError('Use --project-home for a project venv; --current preserves the selected interpreter')
        return
    if not request['venv']:
        return
    options, use = request['options'], request.get('use', {})
    python_version = str(options.get('python') or use.get('python', {}).get('version') or profile.get('python') or '')
    cmeta_version = str(options.get('cmeta') or use.get('cmeta', {}).get('version') or profile.get('cmeta') or '')
    target = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    env = environment(root, sys.executable)
    uv = [sys.executable, '-m', 'cmeta', 'tool', 'run', request['dependencies']['uv'], '-q', '--']
    existing_cmeta = ''
    if target.is_file():
        probe = ('import importlib.util,json,platform; '
                 'imported=__import__("cmeta") if importlib.util.find_spec("cmeta") else None; '
                 'print(json.dumps([platform.python_version(), getattr(imported,"__version__","")]))')
        installed, existing_cmeta = json.loads(execute([target, '-c', probe], env, root, True))
        if python_version and installed.split('.')[:len(python_version.split('.'))] != python_version.split('.'):
            raise ValueError('Existing venv uses Python {}; preserve/move it before selecting {}'.format(installed, python_version))
    else:
        if (root / '.venv').exists():
            raise ValueError('Existing .venv is incomplete or belongs to another OS; preserve/move it before setup')
        create = ['venv', '--seed']
        if python_version:
            install = ['python', 'install', python_version, '--no-bin']
            if os.name == 'nt':
                install.append('--no-registry')
            execute(uv + install, env, root)
            create += ['--managed-python', '--python', python_version]
        else:
            # An optional venv inherits the invoking interpreter unless explicitly overridden.
            create += ['--python', sys.executable]
        execute(uv + create + [str(root / '.venv')], env, root)
    package = cmeta_requirement(cmeta_version, existing_cmeta)
    install = uv + ['pip', 'install', '--python', str(target), package]
    requirements = profile.get('requirements_latest' if options.get('latest_deps') else 'requirements')
    if requirements:
        path = artifact_file(cm, request['categories'], root, requirements)
        if not path.is_file():
            raise ValueError('Requirements file missing: ' + str(path))
        install += ['-r', str(path)]
    if cmeta_version == 'latest':
        install += ['--upgrade-package', 'cmeta']
    execute(install, env, root)
    record = root / '.setup/runtime'
    record.mkdir(parents=True, exist_ok=True)
    freeze = execute(uv + ['pip', 'freeze', '--python', str(target)], env, root, True)
    (record / 'requirements-resolved.txt').write_text(freeze, encoding='utf-8')
    follow = dict(request, action='reindex', venv=False, _selected=True)
    child_request(target, follow, environment(root, target), root)


def cmeta_requirement(requested='', existing=''):
    """Keep an existing project version, or copy the invoking installation into a new venv."""
    import cmeta
    if requested or existing:
        version = requested or existing
        return 'cmeta' if version == 'latest' else 'cmeta==' + version
    # A development checkout may be ahead of PyPI. Install a non-editable copy so the
    # project does not depend on the orchestrator checkout after installation.
    from importlib.metadata import distribution
    from urllib.parse import urlparse
    from urllib.request import url2pathname
    direct = json.loads(distribution('cmeta').read_text('direct_url.json') or '{}')
    url = urlparse(direct.get('url', ''))
    if direct.get('dir_info', {}).get('editable') and url.scheme == 'file':
        source = Path(url2pathname(url.path))
        if (source / 'pyproject.toml').is_file() or (source / 'setup.py').is_file():
            return str(source)
    return 'cmeta==' + cmeta.__version__


def native_control(action, runtime):
    """status, stop and logs of a server started in the background (--detach, or __run_server_nohup.sh)."""
    if runtime is None:
        raise ValueError('status/stop/logs of a native server need a project instance (--project-home)')
    pid_file, log_file = runtime / 'server.pid', runtime / 'server.log'
    pid = read_pid(pid_file)
    alive = pid_alive(pid)
    if action == 'stop':
        if alive:
            print('Stopping the background server (process {} and its children) ...'.format(pid), flush=True)
            if not kill_tree(pid):
                raise RuntimeError('The server process {} did not stop'.format(pid))
            print('Stopped.', flush=True)
        else:
            print('No background server runs (no live process recorded in {})'.format(pid_file), flush=True)
        alive = False
    elif action == 'logs':
        print(tail(log_file), flush=True)
    result = dict(running=alive, pid=pid if alive else 0, log=str(log_file))
    print(json.dumps(result, indent=2), flush=True)
    return dict(result, **{'return': 0})


def detach(request, runtime):
    """Start the native run in the background: its output goes to server.log, its process id to server.pid.
    A second start while that process lives only reports it. No service is installed."""
    runtime.mkdir(parents=True, exist_ok=True)
    pid_file, log_file = runtime / 'server.pid', runtime / 'server.log'
    old = read_pid(pid_file)
    if pid_alive(old):
        print('Already running: PID {}; log: {}'.format(old, log_file), flush=True)
        return {'return': 0, 'running': True, 'pid': old, 'log': str(log_file), 'already': True}
    child = dict(request, options={k: v for k, v in request['options'].items() if k != 'detach'}, _selected=True)
    with open(log_file, 'ab') as log:
        if os.name != 'nt':
            os.chmod(log_file, 0o600)
        kwargs = dict(stdin=subprocess.PIPE, stdout=log, stderr=log, cwd=str(request['root']))
        if os.name == 'nt':
            flags = 0x00000200 | 0x08000000          # its own process group, a hidden console (no window)
            try:
                process = subprocess.Popen([sys.executable, '-u', __file__], creationflags=flags | 0x01000000, **kwargs)
            except OSError:                          # a job object that forbids breaking away
                process = subprocess.Popen([sys.executable, '-u', __file__], creationflags=flags, **kwargs)
        else:
            process = subprocess.Popen([sys.executable, '-u', __file__], start_new_session=True, **kwargs)
        process.stdin.write(json.dumps(child).encode('utf-8'))
        process.stdin.close()
    pid_file.write_text(str(process.pid), encoding='utf-8')
    time.sleep(2)
    if process.poll() is not None:
        raise RuntimeError('The background server stopped at once; see ' + str(log_file) + ':\n' + tail(log_file, 20))
    print('Started: PID {}; log: {}'.format(process.pid, log_file), flush=True)
    return {'return': 0, 'running': True, 'pid': process.pid, 'log': str(log_file)}


def application(cm, request):
    profile, root = request['profile'], Path(request['root'])
    values = parameters(profile, request)
    action = request['action']
    shared = shared_home(profile) and not request['current']
    if action == 'plan':
        return dict(return_code=0, **{'return': 0}, home=str(root), mode=request['mode'],
                    task=profile.get('task'), params=values, current=request['current'], shared=shared)
    state = None if request['current'] else instance_state(cm, request['categories'], profile)
    if not request['current']:
        mutable_root(root, state, shared)
    secrets = secrets_dir(root, state, shared)
    if request['mode'] == 'docker':
        if request['current']:
            raise ValueError('Docker project execution requires --project-home; use the existing state deployment mode for current-home Docker')
        import docker_runtime
        request = dict(request, mutable=str(mutable_root(root, state, shared)), state=str(state) if state else '',
                       shared=shared, secrets=str(secrets))
        if shared:
            request['sources'] = [[name, str(path)] for name, path in shared_repositories(cm, request)]
        return docker_runtime.run(cm, request, values)
    mapping = {'cmeta_home': str(cm.home_path), 'root': str(root), 'secrets': str(secrets)}
    if state:
        mapping['state'] = str(state / 'data')
    values = expand(values, mapping)
    runtime = None if request['current'] else runtime_dir(root, state, shared)
    if action in ('status', 'stop', 'logs'):
        return native_control(action, runtime)
    if action not in ('run', 'prepare'):
        raise ValueError('Native {} is not declared by this application; use its task directly'.format(action))
    if action == 'run' and request['options'].get('detach'):
        if runtime is None:
            raise ValueError('--detach needs a project instance (--project-home)')
        return detach(request, runtime)
    task = profile.get('task')
    if not task:
        raise ValueError('Project definition needs task')
    _, sep, task = task.partition('::') if '::' in task else ('', '', task)
    call = dict(category=request['categories']['task'], command='run', arg1=task, quiet=True, con=True, **values)
    if request.get('use'):
        call['use'] = request['use']
    if action == 'prepare':
        call.update(profile.get('prepare_params') or {'prepare_only': True})
    if values.get('port'):
        print('Browse: ' + str(values.get('public_url') or 'http://localhost:' + str(values['port'])).rstrip('/') + '/', flush=True)
    return checked(cm.access(call))


def run_shared(request, root):
    """A home: current instance: the invoking cMeta home and Python run it. Its folder keeps project.yaml and
    the scripts generated for this kind; its state artifact keeps what belongs to this machine."""
    profile, action = request['profile'], request['action']
    if action not in ('init', 'bootstrap', 'adopt', 'setup') and not (root / 'project.yaml').is_file():
        raise ValueError('Initialize/adopt this project before running it')
    if request['venv'] or action == 'update-git-repos':
        raise ValueError('A home: current instance uses the invoking Python and the repositories of its cMeta home: '
                         'update them as you update that home (cx host sync, cx repo pull)')
    cm = CMeta(home=request.get('home') or None)
    import scripts
    if action in ('init', 'bootstrap', 'adopt', 'setup'):
        shared_repositories(cm, request, pull=action in ('init', 'bootstrap'))
        instance_state(cm, request['categories'], profile)
        root.mkdir(parents=True, exist_ok=True)
        manifest = root / 'project.yaml'
        if not manifest.exists():
            profile.setdefault('format', 1)
            profile.setdefault('instance', uuid.uuid4().hex[:16])
            checked(cm.utils.files.safe_write_file(str(manifest), profile, atomic=True, sort_keys=False))
        if request['generate_scripts']:
            scripts.generate(root, profile)
        return {'return': 0, 'home': str(cm.home_path), 'root': str(root), 'action': action}
    if action == 'scripts':
        scripts.generate(root, profile)
    elif action == 'reindex':
        for name, _ in shared_repositories(cm, request):
            checked(cm.access(dict(category=request['categories']['repo'], command='reindex', arg1=name, con=False)))
    elif action == 'config':
        config(cm, request)
    elif action == 'info':
        import cmeta
        state = instance_state(cm, request['categories'], profile)
        result = dict(home=str(cm.home_path), root=str(root), state=str(state) if state else '', kind='current home',
                      python=sys.executable, python_version=sys.version.split()[0], cmeta_version=cmeta.__version__,
                      task=profile['task'])
        print(json.dumps(result, indent=2))
        return dict(result, **{'return': 0})
    else:
        return application(cm, request)
    return {'return': 0, 'home': str(cm.home_path), 'root': str(root), 'action': action}


def run(request):
    root = Path(request['root']).resolve()
    profile, action = request['profile'], request['action']
    if not profile.get('name') or not profile.get('task'):
        raise ValueError('Project definition requires name and task')
    if action == 'plan':
        result = application(None, request)
        print(json.dumps(result, indent=2))
        return result
    if shared_home(profile) and not request['current']:
        return run_shared(request, root)
    if not request['current'] and action not in ('init', 'bootstrap', 'adopt', 'setup') and not (root / 'project.yaml').is_file():
        raise ValueError('Initialize/adopt this project before running it')
    if request['current'] and action in ('init', 'bootstrap', 'adopt', 'scripts', 'update-git-repos'):
        raise ValueError(action + ' requires a standalone --project-home')
    root.mkdir(parents=True, exist_ok=True)
    python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    selected = (str(python) if not request['current'] and not request['current_env'] and python.is_file() else sys.executable)
    if action not in ('init', 'bootstrap', 'adopt', 'setup') and not request.get('_selected') and Path(selected).resolve() != Path(sys.executable).resolve():
        return child_request(selected, dict(request, _selected=True), environment(root, selected, request['current']), root)
    os.environ.update(environment(root, selected, request['current']))
    if not request['current']:
        os.environ.pop('CMETA_INTERNAL_REPO_PATH', None)
        os.environ.pop('CMETA_TOOL_EXTRA_PATHS', None)
    cm = CMeta(home=str(root))
    if action in ('init', 'bootstrap', 'adopt', 'setup'):
        if action in ('init', 'bootstrap'):
            bootstrap(cm, request)
        elif not request['current']:
            register(cm, root)
        if not request['current']:
            manifest = root / 'project.yaml'
            if not manifest.exists():
                profile.setdefault('format', 1)
                profile.setdefault('instance', uuid.uuid4().hex[:16])
                checked(cm.utils.files.safe_write_file(str(manifest), profile, atomic=True, sort_keys=False))
            if request['generate_scripts']:
                import scripts
                scripts.generate(root, profile)
        setup(cm, request)
        if not request['current'] and not request['venv'] and Path(selected).resolve() != Path(sys.executable).resolve():
            # Adoption from an outer engine must leave the project's own builtin
            # repository registered, not an external orchestrator installation.
            child_request(selected, dict(request, action='reindex', _selected=True),
                          environment(root, selected), root)
        return {'return': 0, 'home': str(root), 'action': action}
    if action == 'scripts':
        import scripts
        scripts.generate(root, profile)
    elif action == 'reindex':
        if request['current']:
            checked(cm.access({'reindex': True, 'con': False}))
        else:
            register(cm, root)
    elif action == 'config':
        config(cm, request)
    elif action == 'info':
        import cmeta
        result = dict(home=str(root), python=sys.executable, python_version=sys.version.split()[0],
                      cmeta_version=cmeta.__version__, task=profile['task'])
        print(json.dumps(result, indent=2))
        return dict(result, **{'return': 0})
    elif action == 'update-git-repos':
        import git_repos
        git_repos.ROOT = root
        git_repos.reindex = lambda *args: register(cm, root)
        args = []
        for key in ('repo', 'branch', 'release', 'checkout'):
            if request['options'].get(key):
                args += ['--' + key, str(request['options'][key])]
        if request['options'].get('status') or request['options'].get('dry_run'):
            args += ['--status']
        git_repos.update_git_repos(args, selected, os.environ.copy())
    else:
        return application(cm, request)
    return {'return': 0, 'home': str(root), 'action': action}


if __name__ == '__main__':
    try:
        result = run(json.load(sys.stdin))
    except (OSError, ValueError, RuntimeError) as exc:
        result = {'return': 1, 'error': str(exc)}
    print('CMETA_PROJECT_RESULT=' + json.dumps(result, default=str), flush=True)
    raise SystemExit(result.get('return', 1))
