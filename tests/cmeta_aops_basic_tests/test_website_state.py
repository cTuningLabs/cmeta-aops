"""Licensed under Apache-2.0; see COPYRIGHT and LICENSE in the project root."""

import json
import os
from pathlib import Path
import shutil

import cmeta
import pytest


@pytest.fixture
def cm(tmp_path):
    instance = cmeta.CMeta(home=str(tmp_path / 'orchestrator'))
    result = instance.access(dict(category='repo', command='plug', arg1=str(Path(__file__).resolve().parents[2]), con=False))
    assert result['return'] == 0
    return instance


def test_state_is_protected_from_ordinary_removal(cm):
    created = cm.access(dict(category='state', command='get', arg1='local:website-test', con=False))
    assert created['return'] == 0
    assert created['cmeta']['permanent'] is True
    path = Path(created['artifact']['path'])
    (path / 'important.txt').write_text('keep')
    removed = cm.access(dict(category='state', command='delete', arg1='local:website-test', force=True, quiet=True, con=False))
    assert removed['return'] == 0 and (path / 'important.txt').read_text() == 'keep'


def test_native_private_home_and_source_edits_survive_prepare(cm, tmp_path):
    source = tmp_path / 'recipes'
    task = source / 'task/probe-website'
    task.mkdir(parents=True)
    (source / '_cmr.yaml').write_text('artifact: movable-recipes,438c6849fd014ade\ncategory: repo,f4f792ab40c7498f\n')
    runner = source / 'task/portable-runner'
    shutil.copytree(Path(__file__).resolve().parents[2] / 'task/run-website', runner,
                    ignore=shutil.ignore_patterns('__pycache__'))
    meta = (runner / '_cmeta.yaml').read_text().replace('b6c8dbe5108a4320', '0269b9fb66a8415c')
    (runner / '_cmeta.yaml').write_text(meta)
    (task / '_cmeta.yaml').write_text('artifact: 982e69ab994a4a0b\ncategory: task,c36be4b9314a45e0\n')
    (task / '_desc.yaml').write_text('cache: false\ndeployment:\n  name: probe\n  mode: native\n  params: {}\n')
    (task / 'message.txt').write_text('original')
    (task / 'api_v1.py').write_text('''from task_c36be4b9314a45e0.api.ctask import InitCTask
import json, os
from pathlib import Path
class CTask(InitCTask):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,module_file_path=__file__,**kwargs)
    def run(self,ctx,action='run',state_cref='',backup_cref=''):
        root=Path(json.loads(os.environ['CMETA_ARTIFACT_MOUNTS'])['state']['path'])
        (root/'observed.json').write_text(json.dumps({'home':str(self.cm.home_path),'source':__file__,
            'message':Path(__file__).with_name('message.txt').read_text()}))
        return {'return':0}
''')
    assert cm.access(dict(category='repo', command='plug', arg1=str(source), con=False))['return'] == 0
    request = dict(category='task', command='run', arg1='portable-runner,0269b9fb66a8415c', website='task::probe-website',
                   deployment='unit', mode='native', quiet=True, con=False)
    prepared = cm.access(dict(request, action='prepare'))
    assert prepared['return'] == 0, prepared
    root = Path(prepared['path'])
    assert json.loads((root / 'deployment.json').read_text())['worker'] == 'src/task/portable-runner/api_v1.py'
    edited = root / 'src/task/probe-website/message.txt'
    edited.write_text('deployed edit')
    assert cm.access(dict(request, action='prepare'))['return'] == 0
    assert edited.read_text() == 'deployed edit' and (task / 'message.txt').read_text() == 'original'
    executed = cm.access(dict(request, action='run'))
    assert executed['return'] == 0, executed
    assert cm.access(dict(request, action='status'))['return'] == 0
    observed = json.loads((root / 'volumes/app/observed.json').read_text())
    assert Path(observed['home']).resolve() == (root / 'CMETA').resolve()
    assert Path(observed['source']).is_relative_to(root)
    assert observed['message'] == 'deployed edit'
    assert Path(cm.home_path).resolve() != Path(observed['home']).resolve()
    extra = root / 'CMETA/repos/extra-private'
    extra.mkdir(parents=True)
    (extra / '_cmr.yaml').write_text('artifact: extra-private,d288c915cad04e96\ncategory: repo,f4f792ab40c7498f\n')
    private = cmeta.CMeta(home=str(root / 'CMETA'))
    assert private.access(dict(category='repo', command='plug', arg1=str(extra), con=False))['return'] == 0
    moved = cm.access(dict(category='state', command='move', arg1='local:website-probe-unit',
                           arg2='local:website-probe-moved', con=False, quiet=True))
    assert moved['return'] == 0, moved
    executed = cm.access(dict(request, action='run', state_cref='state::local:website-probe-moved'))
    assert executed['return'] == 0, executed
    relocated = Path(cm.home_path) / 'repos/local/state/website-probe-moved'
    observed = json.loads((relocated / 'volumes/app/observed.json').read_text())
    assert Path(observed['source']).is_relative_to(relocated)
    assert observed['message'] == 'deployed edit'
    registered = json.loads((relocated / 'CMETA/repos.json').read_text())
    assert str((relocated / 'CMETA/repos/extra-private').resolve()) in registered


def test_global_repositories_run_the_recipe_in_place_with_its_data(cm, tmp_path):
    source = tmp_path / 'recipes'
    task = source / 'task/probe-in-place'
    task.mkdir(parents=True)
    (source / '_cmr.yaml').write_text('artifact: in-place-recipes,5b7e0c2a9d114f3e\ncategory: repo,f4f792ab40c7498f\n')
    (task / '_cmeta.yaml').write_text('artifact: 7c1d2e3f4a5b6c7d\ncategory: task,c36be4b9314a45e0\n')
    (task / '_desc.yaml').write_text('cache: false\ndeployment:\n  name: probe\n  mode: native\n  params: {}\n'
                                     '  data: result::local:website-probe-data\n')
    (task / 'message.txt').write_text('original')
    (task / 'api_v1.py').write_text('''from task_c36be4b9314a45e0.api.ctask import InitCTask
import json, os
from pathlib import Path
class CTask(InitCTask):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,module_file_path=__file__,**kwargs)
    def run(self,ctx,action='run',state_cref=''):
        mounts=json.loads(os.environ['CMETA_ARTIFACT_MOUNTS'])
        (Path(mounts['data']['path'])/'event.log').write_text('written by the site')
        (Path(mounts['state']['path'])/'observed.json').write_text(json.dumps({'home':str(self.cm.home_path),
            'source':__file__,'message':Path(__file__).with_name('message.txt').read_text(),'data':mounts['data']['path']}))
        return {'return':0}
''')
    assert cm.access(dict(category='repo', command='plug', arg1=str(source), con=False))['return'] == 0
    request = dict(category='task', command='run', arg1='run-website,b6c8dbe5108a4320', website='task::probe-in-place',
                   deployment='unit', mode='native', repositories='global', quiet=True, con=False)
    prepared = cm.access(dict(request, action='prepare'))
    assert prepared['return'] == 0, prepared
    root = Path(prepared['path'])
    manifest = json.loads((root / 'deployment.json').read_text())
    assert manifest['repositories'] == [] and manifest['worker'] == ''
    assert not any((root / name).exists() for name in ('src', 'inputs', 'CMETA'))

    # The recipe runs where it is: an edit is what the next start runs
    (task / 'message.txt').write_text('edited in place')
    executed = cm.access(dict(request, action='run'))
    assert executed['return'] == 0, executed
    observed = json.loads((root / 'volumes/app/observed.json').read_text())
    assert observed['message'] == 'edited in place'
    assert Path(observed['source']).resolve() == (task / 'api_v1.py').resolve()
    assert Path(observed['home']).resolve() == Path(cm.home_path).resolve()
    data = Path(cm.home_path) / 'repos/local/result/website-probe-data'
    assert Path(observed['data']).resolve() == data.resolve()
    assert (data / 'event.log').read_text() == 'written by the site'

    # A state without copies is never run on copies
    refused = cm.access(dict(request, action='run', repositories='isolated'))
    assert refused['return'] != 0 and 'in place' in refused['error']


def test_state_volume_subpaths_are_contained(cm, tmp_path):
    loaded = cm.access(dict(category='task', command='load', arg1='get-host--docker', con=False))
    assert loaded['return'] == 0
    import importlib.util
    path = Path(__file__).resolve().parents[2] / 'task/get-host--docker/api_v1.py'
    spec = importlib.util.spec_from_file_location('state_mount_resolver', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    resolver = object.__new__(module.CTask); resolver.cm = cm
    mount = resolver._artifact_mounts({'app': 'state::local:website-volumes/volumes/app'}, '/home/cmeta')[0]
    assert Path(mount['path']).parts[-3:] == ('website-volumes', 'volumes', 'app')
    for reference in ('state::local:website-volumes/../outside', 'state::local:website-volumes//bad',
                      'result::local:website-volumes/subdir'):
        with pytest.raises(ValueError):
            resolver._artifact_mounts({'app': reference}, '/home/cmeta')
    root = Path(mount['path']).parents[1]
    outside = tmp_path / 'outside'; outside.mkdir()
    try:
        (root / 'escape').symlink_to(outside, target_is_directory=True)
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314:
            pytest.skip('Directory links require Windows developer mode')
        raise
    with pytest.raises(ValueError, match='escapes'):
        resolver._artifact_mounts({'app': 'state::local:website-volumes/escape/subdir'}, '/home/cmeta')
