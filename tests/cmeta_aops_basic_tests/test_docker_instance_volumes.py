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
