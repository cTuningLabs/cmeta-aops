"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The named volumes of a docker instance (instance_volumes of a container template, get-host--docker): each instance
gets its own, a host path or a target outside the container's own folders is refused.
"""

import importlib.util


from pathlib import Path

import pytest


@pytest.fixture(scope='module')
def mounts(tmp_path_factory):
    # The UID import is normally registered by cMeta dispatch.
    import cmeta
    cm = cmeta.CMeta(home=str(tmp_path_factory.mktemp('instance-volumes-home')))
    root = Path(__file__).resolve().parents[2]
    plugged = cm.access({'category': 'repo', 'command': 'plug', 'arg1': str(root), 'con': False})
    assert plugged['return'] == 0
    found = cm.access({'category': 'task', 'command': 'load', 'arg1': 'get-host--docker', 'con': False})
    assert found['return'] == 0
    path = Path(__file__).resolve().parents[2] / 'task/get-host--docker/api_v1.py'
    spec = importlib.util.spec_from_file_location('docker_volumes_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.instance_volume_mounts


def test_default_has_no_new_mounts(mounts):
    assert mounts([], 'first', '/home/cmeta') == []


def test_each_instance_gets_separate_volume(mounts):
    template = [{'name': '{instance}-cmeta', 'target': '{home}/CMETA'}]
    first = mounts(template, 'first', '/home/cmeta')
    second = mounts(template, 'second', '/home/cmeta')
    assert first == [{'name': 'first-cmeta', 'target': '/home/cmeta/CMETA'}]
    assert first[0]['name'] != second[0]['name']
    assert template[0]['name'] == '{instance}-cmeta'


@pytest.mark.parametrize('volumes', [
    {}, ['bad'], [{'name': '/host/data', 'target': '/home/cmeta'}],
    [{'name': 'good', 'target': '/'}], [{'name': 'good', 'target': '/a/../b'}],
    [{'name': 'good', 'target': 'relative'}], [{'name': '{unknown}', 'target': '/data'}],
    [{'name': 'one', 'target': '/data'}, {'name': 'two', 'target': '/data/'}],
])
def test_malformed_or_ambiguous_mounts_fail(mounts, volumes):
    with pytest.raises(ValueError):
        mounts(volumes, 'first', '/home/cmeta')


def test_selected_local_result_without_repository_exposure(mounts, tmp_path):
    import cmeta
    cm = cmeta.CMeta(home=str(tmp_path / 'home'))
    root = Path(__file__).resolve().parents[2]
    assert cm.access(dict(category='repo', command='plug', arg1=str(root), con=False))['return'] == 0
    cls = mounts.__globals__['CTask']
    task = object.__new__(cls)
    task.cm = cm
    selected = task._artifact_mounts({'state': 'result::local:website-example-state'}, '/home/cmeta')
    assert len(selected) == 1 and selected[0]['mode'] == 'rw'
    path = Path(selected[0]['path'])
    assert path.name == 'website-example-state' and path.parent.name == 'result'
    assert selected[0]['inside'] == '/home/cmeta/artifacts/state'
    assert Path(cm.home_path) != path and path.parent.parent != path
    assert task._artifact_mounts({'state': {'cref': 'result::local:website-example-state', 'mode': 'ro'}}, '/home/cmeta')[0]['path'] == str(path)
    with pytest.raises(ValueError):
        task._artifact_mounts({'input': {'cref': 'result::local:missing-input', 'mode': 'ro'}}, '/home/cmeta')
    for declaration in ('config::local:task', '/home/user', 'result::local:state/../config', 'crypt::private'):
        with pytest.raises(ValueError):
            task._artifact_mounts({'state': declaration}, '/home/cmeta')


def test_result_on_external_disk_remains_indexed(mounts, tmp_path):
    import cmeta
    cm = cmeta.CMeta(home=str(tmp_path / 'home'))
    root = Path(__file__).resolve().parents[2]
    assert cm.access(dict(category='repo', command='plug', arg1=str(root), con=False))['return'] == 0
    created = cm.access(dict(category='result', command='get', arg1='local:website-external-state',
                             meta={'permanent': True}, con=False))
    assert created['return'] == 0
    path = Path(created['artifact']['path'])
    target = tmp_path / 'persistent-disk-state'
    path.rename(target)
    try:
        path.symlink_to(target, target_is_directory=True)
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314:
            pytest.skip('Windows account cannot create directory links')
        raise
    reindexed = cm.access(dict(category='result', command='reindex', arg1='local:website-external-state', con=False))
    assert reindexed['return'] == 0
    cls = mounts.__globals__['CTask']
    task = object.__new__(cls); task.cm = cm
    selected = task._artifact_mounts({'state': 'result::local:website-external-state'}, '/home/cmeta')
    assert Path(selected[0]['path']) == target.resolve()

def test_artifact_volume_is_stable_and_lost_storage_is_refused(mounts, tmp_path, monkeypatch):
    import json
    import cmeta
    cm = cmeta.CMeta(home=str(tmp_path / 'volume-home'))
    root = Path(__file__).resolve().parents[2]
    assert cm.access(dict(category='repo', command='plug', arg1=str(root), con=False))['return'] == 0
    module = mounts.__globals__
    resolver = object.__new__(module['CTask']); resolver.cm = cm
    declaration = {'state': {'cref': 'state::local:owned-volume/volumes/app', 'storage': 'volume'}}
    selected = resolver._artifact_mounts(declaration, '/home/cmeta')
    second = resolver._artifact_mounts(declaration, '/home/cmeta')
    assert selected[0]['volume'] == second[0]['volume']
    other = resolver._artifact_mounts({'state': dict(declaration['state'], cref='state::local:owned-volume/volumes/other')}, '/home/cmeta')
    assert other[0]['volume'] != selected[0]['volume']
    volumes, creates = {}, []
    def engine_run(engine, args, timeout=60):
        if args[:2] == ['volume', 'inspect']:
            value = volumes.get(args[-1])
            return (0, json.dumps([value]), '') if value else (1, '', 'No such volume')
        assert args[:2] == ['volume', 'create']
        creates.append(args[-1])
        labels = dict(args[i + 1].split('=', 1) for i, word in enumerate(args) if word == '--label')
        volumes[args[-1]] = {'Labels': labels}
        return 0, args[-1], ''
    monkeypatch.setitem(module, 'engine_run', engine_run)
    module['ensure_artifact_volumes']('docker', selected)
    module['ensure_artifact_volumes']('docker', second)
    assert len(creates) == 1
    marker = Path(selected[0]['path']) / '.cmeta-volume.json'
    assert json.loads(marker.read_text())['volume'] == selected[0]['volume']
    with pytest.raises(ValueError, match='represents a Linux volume'):
        resolver._artifact_mounts({'state': declaration['state']['cref']}, '/home/cmeta')
    volumes.clear()
    with pytest.raises(ValueError, match='refusing to create empty'):
        module['ensure_artifact_volumes']('docker', selected)
    assert len(creates) == 1 and marker.exists()


def test_volume_refuses_existing_files_and_foreign_ownership(mounts, tmp_path, monkeypatch):
    import json
    import cmeta
    cm = cmeta.CMeta(home=str(tmp_path / 'guard-home'))
    root = Path(__file__).resolve().parents[2]
    assert cm.access(dict(category='repo', command='plug', arg1=str(root), con=False))['return'] == 0
    module = mounts.__globals__
    resolver = object.__new__(module['CTask']); resolver.cm = cm
    declaration = {'state': {'cref': 'state::local:guarded-volume/volumes/app', 'storage': 'volume'}}
    selected = resolver._artifact_mounts(declaration, '/home/cmeta')
    data = Path(selected[0]['path']) / 'important.txt'
    data.write_text('existing live files')
    with pytest.raises(ValueError, match='empty state subdirectory'):
        resolver._artifact_mounts(declaration, '/home/cmeta')
    data.unlink()
    monkeypatch.setitem(module, 'engine_run', lambda *a, **k: (0, json.dumps([{'Labels': {'cmeta.artifact': 'foreign'}}]), ''))
    with pytest.raises(ValueError, match='another artifact'):
        module['ensure_artifact_volumes']('docker', selected)
    assert not (Path(selected[0]['path']) / '.cmeta-volume.json').exists()
    with pytest.raises(ValueError, match='protected state'):
        resolver._artifact_mounts({'state': {'cref': 'result::local:wrong-kind', 'storage': 'volume'}}, '/home/cmeta')


def test_old_bind_mount_identity_is_unchanged(mounts):
    identity = mounts.__globals__['artifact_mount_identity']
    old = dict(key='state', cref='state::local:example', path='/srv/state', inside='/state', mode='rw')
    assert identity([old]) == identity([dict(old, storage='bind')])
    assert identity([old]) != identity([dict(old, storage='volume', volume='owned-volume')])


def test_host_up_refuses_missing_or_foreign_state_volume(tmp_path):
    import json
    from types import SimpleNamespace
    path = Path(__file__).resolve().parents[2] / 'category/host/api/v1.py'
    spec = importlib.util.spec_from_file_location('host_volume_guard', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    category = object.__new__(module.Category)
    category.cm = SimpleNamespace(error=lambda message: {'return': 1, 'error': message})
    category._declared_command = lambda *a: None
    category._engine = lambda h: 'docker'
    host = dict(type='docker', alias='example', status='missing', desc={
        'access': {'container': 'example', 'image': 'example-image'},
        'artifact_mounts': [{'storage': 'volume', 'volume': 'owned-volume', 'uid': 'owner', 'subpath': 'volumes/app'}]})
    for response in ({'returncode': 1, 'stdout': ''},
                     {'returncode': 0, 'stdout': json.dumps([{'Labels': {'cmeta.artifact': 'foreign'}}])}):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            return response
        category._run_local = run
        result = category._up_one({}, host, False)
        assert result['return'] == 1
        assert commands == ['docker volume inspect owned-volume']
