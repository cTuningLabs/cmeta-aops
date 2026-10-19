"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

manage-cmeta-project with home: current (one site per machine, 2026-10-19): the instance folder keeps only
project.yaml and its scripts, the invoking cMeta home and its repositories run the site, and the instance's
state artifact keeps what belongs to the machine ({state}, {secrets}, the runtime files of a background start).
"""

import importlib.util
import json
import os
from pathlib import Path
import time

import cmeta
import pytest

AOPS = Path(__file__).resolve().parents[2]
MANAGER = 'manage-cmeta-project,9df2b3a416e84c75'


@pytest.fixture
def shared_fixture(tmp_path, monkeypatch):
    monkeypatch.delenv('CMETA_INTERNAL_REPO_PATH', raising=False)
    monkeypatch.delenv('CMETA_TOOL_EXTRA_PATHS', raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'controller'))
    cm = cmeta.CMeta(home=str(tmp_path / 'controller'))
    assert cm.access(dict(category='repo', command='plug', arg1=str(AOPS), con=False))['return'] == 0
    recipes = tmp_path / 'site-recipes'
    (recipes / '_cmr.yaml').parent.mkdir(parents=True)
    (recipes / '_cmr.yaml').write_text('artifact: site-recipes,5be1c3a2e0d94f17\ncategory: repo,f4f792ab40c7498f\n')
    for name, uid, body in (
            ('site-probe', '7a2c9e41b3d84f60', "(Path(self.cm.home_path)/'observed.json').write_text(json.dumps("
                                               "dict(home=str(self.cm.home_path), message=message)))"),
            ('site-sleeper', '3f81d0c6a95e4b27', 'time.sleep(60)')):
        app = recipes / 'task' / name
        app.mkdir(parents=True)
        (app / '_cmeta.yaml').write_text('artifact: ' + uid + '\ncategory: task,c36be4b9314a45e0\n')
        (app / '_desc.yaml').write_text('cache: false\nstore_global: false\n')
        (app / 'api_v1.py').write_text('''from task_c36be4b9314a45e0.api.ctask import InitCTask
import json, time
from pathlib import Path
class CTask(InitCTask):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,module_file_path=__file__,**kwargs)
    def run(self,ctx,message=''):
        BODY
        return {'return':0}
'''.replace('BODY', body))
    assert cm.access(dict(category='repo', command='plug', arg1=str(recipes), con=False))['return'] == 0
    profile = dict(name='probe-site', home='current', task='task::site-probe,7a2c9e41b3d84f60',
                   state='state::local:website-probe-site',
                   repositories=[dict(name='site-recipes,5be1c3a2e0d94f17')],
                   params=dict(message='{state}|{secrets}'),
                   syncs=['host::my-vm', 'sync::bisync-probe-data-with-my-vm,0123456789abcdef'])
    return cm, tmp_path / 'website-probe' / 'CMETA', profile


def call(cm, **kwargs):
    return cm.access(dict(category='task', command='run', arg1=MANAGER, con=False, quiet=True, **kwargs))


def test_bootstrap_writes_only_project_yaml_scripts_and_the_state(shared_fixture):
    cm, root, profile = shared_fixture
    result = call(cm, action='bootstrap', project_home=str(root), profile=profile)
    assert result['return'] == 0, result
    assert (root / 'project.yaml').is_file()
    assert not (root / 'repos').exists() and not (root / 'repos.json').exists()
    names = sorted(p.name for p in root.iterdir() if p.is_file())
    assert '__run_server.bat' in names and '__run_server_nohup.sh' in names and '___sync_all.bat' in names
    assert '__cx.bat' not in names and '__setup_venv.bat' not in names
    script = (root / '__run_server.bat').read_text()
    assert 'set "CMETA_HOME' not in script and '--project-home="%PROJECT_ROOT%"' in script
    assert '--detach' in (root / '__run_server_nohup.sh').read_text()
    state = Path(cm.home_path) / 'repos/local/state/website-probe-site'
    assert all((state / name).is_dir() for name in ('data', 'secrets', 'runtime'))


def test_run_uses_the_invoking_home_and_resolves_the_placeholders(shared_fixture):
    cm, root, profile = shared_fixture
    assert call(cm, action='bootstrap', project_home=str(root), profile=profile)['return'] == 0
    result = call(cm, action='run', project_home=str(root))
    assert result['return'] == 0, result
    observed = json.loads((Path(cm.home_path) / 'observed.json').read_text())
    state = Path(cm.home_path) / 'repos/local/state/website-probe-site'
    assert Path(observed['home']) == Path(cm.home_path)
    assert observed['message'] == str(state / 'data') + '|' + str(state / 'secrets')
    assert not (root / 'observed.json').exists()


def test_a_missing_repository_is_named_at_bootstrap(shared_fixture):
    cm, root, profile = shared_fixture
    profile = dict(profile, repositories=profile['repositories'] + [dict(name='not-plugged-here')])
    result = call(cm, action='bootstrap', project_home=str(root), profile=profile)
    assert result['return'] != 0 and 'not-plugged-here' in result['error']
    optional = dict(profile, repositories=profile['repositories'][:1] + [dict(name='not-plugged-here', required=False)])
    assert call(cm, action='bootstrap', project_home=str(root), profile=optional)['return'] == 0


def test_sync_all_lists_the_declared_steps_in_order(shared_fixture):
    cm, root, profile = shared_fixture
    assert call(cm, action='bootstrap', project_home=str(root), profile=profile)['return'] == 0
    bat = (root / '___sync_all.bat').read_text()
    sh = (root / '___sync_all.sh').read_text()
    assert bat.index('call cx host sync my-vm') < bat.index('call cxt sync bisync-probe-data-with-my-vm,0123456789abcdef')
    assert '--require-initialized --live %*' in bat and 'set "CMETA_HOME' not in bat
    assert 'cx host sync my-vm $host_flags' in sh and '--require-initialized --live "$@"' in sh


def test_project_homes_keep_their_scripts_byte_for_byte(tmp_path):
    spec = importlib.util.spec_from_file_location('project_scripts_test', AOPS / 'task/manage-cmeta-project/scripts.py')
    scripts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scripts)
    files = scripts.project_files()
    assert set(files) >= {'__run_server.bat', '__cx.bat', '__source.ps1', '__run_server_nohup.sh'}
    assert 'set "CMETA_HOME=%%~fI"' in files['__run_server.bat']
    assert scripts.sync_files({}) == {}


def test_docker_seed_of_a_current_home_is_an_empty_repository(tmp_path):
    spec = importlib.util.spec_from_file_location('project_docker_seed_test', AOPS / 'task/manage-cmeta-project/docker_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SEED_MARKER = '.seed.json'
    home = tmp_path / 'home'
    (home / 'repos/local/cache/big').mkdir(parents=True)
    (home / 'repos/local/_cmr.yaml').write_text('artifact: local,9a3280b14a4285c9\n')
    destination = tmp_path / 'state/docker/repos/local'
    module.seed_empty(home, destination)
    assert (destination / '_cmr.yaml').read_text() == 'artifact: local,9a3280b14a4285c9\n'
    assert not (destination / 'cache').exists()
    (destination / 'kept.txt').write_text('container data')
    module.seed_empty(home, destination)
    assert (destination / 'kept.txt').read_text() == 'container data'


def test_background_start_status_and_stop(shared_fixture):
    cm, root, profile = shared_fixture
    profile = dict(profile, task='task::site-sleeper,3f81d0c6a95e4b27')
    assert call(cm, action='bootstrap', project_home=str(root), profile=profile)['return'] == 0
    started = call(cm, action='run', project_home=str(root), detach=True)
    assert started['return'] == 0 and started['running'], started
    runtime = Path(cm.home_path) / 'repos/local/state/website-probe-site/runtime'
    assert int((runtime / 'server.pid').read_text()) == started['pid']
    again = call(cm, action='run', project_home=str(root), detach=True)
    assert again['return'] == 0 and again.get('already') and again['pid'] == started['pid']
    status = call(cm, action='status', project_home=str(root))
    assert status['return'] == 0 and status['running'], status
    stopped = call(cm, action='stop', project_home=str(root))
    assert stopped['return'] == 0 and not stopped['running'], stopped
    deadline = time.monotonic() + 15
    while call(cm, action='status', project_home=str(root))['running'] and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not call(cm, action='status', project_home=str(root))['running']
