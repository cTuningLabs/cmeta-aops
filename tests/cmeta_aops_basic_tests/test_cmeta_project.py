"""Licensed under Apache-2.0; see COPYRIGHT and LICENSE in the project root."""

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import cmeta
import pytest
import yaml

AOPS = Path(__file__).resolve().parents[2]
MANAGER = 'manage-cmeta-project,9df2b3a416e84c75'


@pytest.fixture
def project_fixture(tmp_path, monkeypatch):
    monkeypatch.delenv('CMETA_INTERNAL_REPO_PATH', raising=False)
    monkeypatch.delenv('CMETA_TOOL_EXTRA_PATHS', raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'controller'))
    cm = cmeta.CMeta(home=str(tmp_path / 'controller'))
    assert cm.access(dict(category='repo', command='plug', arg1=str(AOPS), con=False))['return'] == 0
    recipes = tmp_path / 'movable-recipes'
    app = recipes / 'task/project-probe'
    app.mkdir(parents=True)
    (recipes / '_cmr.yaml').write_text('artifact: movable-recipes,804e4b79d4434a30\ncategory: repo,f4f792ab40c7498f\n')
    (app / '_cmeta.yaml').write_text('artifact: 4d13008738da4b77\ncategory: task,c36be4b9314a45e0\n')
    (app / '_desc.yaml').write_text('cache: false\nstore_global: false\n')
    (app / 'api_v1.py').write_text('''from task_c36be4b9314a45e0.api.ctask import InitCTask
import json, os
from pathlib import Path
class CTask(InitCTask):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,module_file_path=__file__,**kwargs)
    def run(self,ctx,message='',nested=None):
        root=Path(self.cm.home_path)
        (root/'observed.json').write_text(json.dumps(dict(home=str(root), message=message,nested=nested,source=__file__)))
        return {'return':0,'home':str(root)}
''')
    tooling = tmp_path / 'tooling'
    tooling.mkdir()
    (tooling / '_cmr.yaml').write_text('artifact: tooling,3cb4ee4f444048f6\ncategory: repo,f4f792ab40c7498f\n')
    for item in ('category/task', 'task/manage-cmeta-project', 'task/run-website'):
        shutil.copytree(AOPS / item, tooling / item, ignore=shutil.ignore_patterns('__pycache__'))
    profile = dict(name='probe', task='task::project-probe,4d13008738da4b77', repositories=[
        dict(name='tooling', source=str(tooling)), dict(name='movable-recipes', source=str(recipes))])
    assert cm.access(dict(category='repo', command='plug', arg1=str(recipes), con=False))['return'] == 0
    return cm, tmp_path / 'project', profile


def call(cm, **kwargs):
    return cm.access(dict(category='task', command='run', arg1=MANAGER, con=False, quiet=True, **kwargs))


def test_bootstrap_run_relocation_and_repeat_preserve_data(project_fixture):
    cm, root, profile = project_fixture
    request = dict(project_home=str(root), profile=profile)
    created = call(cm, action='bootstrap', **request)
    assert created['return'] == 0, created
    (root / 'repos/local/keep.txt').write_text('retained')
    assert (root / '__run_server.bat').is_file()
    executed = call(cm, action='run', params={'message': 'literal & ! $ spaces', 'nested': {'x': 7}}, **request)
    assert executed['return'] == 0, executed
    observed = json.loads((root / 'observed.json').read_text())
    assert observed['message'] == 'literal & ! $ spaces' and observed['nested'] == {'x': 7}
    assert Path(observed['home']) == root
    assert Path(observed['source']).is_relative_to(root / 'repos')
    assert call(cm, action='bootstrap', **request)['return'] == 0
    assert (root / 'repos/local/keep.txt').read_text() == 'retained'
    destination = root.with_name('relocated-project')
    root.rename(destination)
    assert call(cm, action='reindex', project_home=str(destination))['return'] == 0
    assert call(cm, action='run', project_home=str(destination))['return'] == 0
    assert Path(json.loads((destination / 'observed.json').read_text())['home']) == destination


def test_current_home_has_no_nested_project_or_script_generation(project_fixture):
    cm, root, profile = project_fixture
    previous = os.environ['CMETA_HOME']
    result = call(cm, action='run', current=True, profile=profile, params={'message': 'current'})
    assert result['return'] == 0, result
    assert os.environ['CMETA_HOME'] == previous
    controller = Path(cm.home_path)
    assert Path(json.loads((controller / 'observed.json').read_text())['home']) == controller
    assert not (controller / 'project.yaml').exists()
    assert not (controller / '__run_server.bat').exists()
    assert not root.exists()


def test_project_home_cref_and_contained_subpath(project_fixture):
    cm, root, profile = project_fixture
    added = cm.access(dict(category='website', command='add', arg1='local:project-site', quiet=True, con=False))
    assert added['return'] == 0, added
    result = call(cm, action='bootstrap', project_home='website::project-site/CMETA', profile=profile)
    assert result['return'] == 0, result
    found = cm.access(dict(category='website', command='find', arg1='local:project-site', con=False))
    assert found['return'] == 0, found
    expected = Path(found['artifacts'][0]['path']) / 'CMETA'
    assert (expected / 'project.yaml').is_file()
    assert call(cm, action='run', project_home='website::project-site/CMETA')['return'] == 0
    assert Path(json.loads((expected / 'observed.json').read_text())['home']) == expected
    invalid = call(cm, action='bootstrap', project_home='website::project-site/../escaped', profile=profile)
    assert invalid['return'] != 0


def test_generated_scripts_do_not_overwrite_user_changes(project_fixture):
    cm, root, profile = project_fixture
    assert call(cm, action='bootstrap', project_home=str(root), profile=profile)['return'] == 0
    script = root / '__run_server.bat'
    script.write_text('echo user customization\n')
    result = call(cm, action='scripts', project_home=str(root))
    assert result['return'] != 0
    assert script.read_text() == 'echo user customization\n'


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch self-regeneration semantics')
def test_batch_adapter_can_regenerate_itself_and_preserves_failure_status(project_fixture):
    cm, root, profile = project_fixture
    assert call(cm, action='bootstrap', project_home=str(root), profile=profile)['return'] == 0
    script = root / '__cx.bat'
    data = script.read_bytes().replace(b'@echo off', b'@echo off\r\nrem Previous generated script with a different length.')
    script.write_bytes(data)
    record = root / '.setup/runtime/generated-scripts.json'
    hashes = json.loads(record.read_text())
    hashes['__cx.bat'] = hashlib.sha256(data).hexdigest()
    record.write_text(json.dumps(hashes))
    completed = subprocess.run(['cmd.exe', '/d', '/c', str(script), 'task', 'run', MANAGER,
                                'scripts', '--project-home=' + str(root), '-q'],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert completed.returncode == 0, completed.stdout
    assert completed.stdout.count('Generated project scripts in') == 1, completed.stdout
    failed = subprocess.run(['cmd.exe', '/d', '/c', str(script), 'task', 'run', MANAGER, 'info'],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert failed.returncode != 0, failed.stdout


def test_docker_local_seed_is_once_and_excludes_only_top_level_cache(tmp_path):
    spec = importlib.util.spec_from_file_location('project_docker_test', AOPS / 'task/manage-cmeta-project/docker_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SEED_MARKER = '.seed.json'
    source, destination = tmp_path / 'source', tmp_path / 'docker/local'
    source.mkdir()
    (source / '_cmr.yaml').write_text('artifact: local,1234567812345678\n')
    for name in ('cache/drop', 'tmp/drop', 'users/keep', 'state/app/cache/keep'):
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('original')
    module.seed(source, destination)
    assert not (destination / 'cache').exists() and not (destination / 'tmp').exists()
    assert (destination / 'state/app/cache/keep').exists()
    (destination / 'users/keep').write_text('live user')
    module.seed(source, destination)
    assert (destination / 'users/keep').read_text() == 'live user'


@pytest.mark.parametrize('existing,override', [(False, False), (True, False), (False, True)])
def test_venv_inherits_invoking_runtime_and_preserves_existing(tmp_path, monkeypatch, existing, override):
    spec = importlib.util.spec_from_file_location('project_runtime_test', AOPS / 'task/manage-cmeta-project/runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    target = tmp_path / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if existing:
        target.parent.mkdir(parents=True)
        target.touch()
    commands, packages = [], []
    def execute(args, *other):
        commands.append(args)
        return json.dumps(['3.13.8', '0.37.1']) if '-c' in args else ''
    def requirement(requested, installed):
        packages.append((requested, installed))
        return 'cmeta==' + (requested or installed or cmeta.__version__)
    monkeypatch.setattr(runtime, 'execute', execute)
    monkeypatch.setattr(runtime, 'cmeta_requirement', requirement)
    monkeypatch.setattr(runtime, 'child_request', lambda *args: {'return': 0})
    request = dict(root=str(tmp_path), profile={}, current=False, venv=True, options={},
                   dependencies={'uv': 'uv,92f171fc18714ebd'},
                   use={'python': {'version': '3.12'}, 'cmeta': {'version': '0.37.0'}} if override else {})
    runtime.setup(None, request)
    creates = [args for args in commands if 'venv' in args]
    downloads = [args for args in commands if 'install' in args and 'python' in args]
    if existing:
        assert not creates and not downloads
        assert packages == [('', '0.37.1')]
    elif override:
        assert len(downloads) == 1 and '3.12' in downloads[0]
        assert '--managed-python' in creates[0]
        assert packages == [('0.37.0', '')]
    else:
        assert not downloads
        assert creates[0][creates[0].index('--python') + 1] == sys.executable
        assert '--managed-python' not in creates[0]
        assert packages == [('', '')]
