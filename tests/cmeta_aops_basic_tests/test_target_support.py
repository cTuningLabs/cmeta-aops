"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The "support" block every compute target declares in its _desc.yaml (task/target--<name>: kind, hardware, host_os,
device_os, status) - read by "cx program targets" and the page cserver.cmeta.targets -, the targets the programs
declare, and the words of that page (files/targets.yaml: the OS columns and the kinds cover what the targets use, the
last family takes every program). Offline.
"""

import fnmatch
import importlib.util
import json
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / 'category' / 'cserver.cmeta.targets'

KINDS = {'cpu', 'gpu', 'npu', 'stack', 'app'}
HOST_OS = {'linux', 'windows', 'darwin'}
DEVICE_OS = {'android', 'ios'}


def targets():
    out = {}
    for path in sorted((REPO_ROOT / 'task').glob('target--*/_desc.yaml')):
        out[path.parent.name[len('target--'):]] = yaml.safe_load(path.read_text(encoding = 'utf-8')) or {}
    return out


def settings():
    return yaml.safe_load((PAGE / 'files' / 'targets.yaml').read_text(encoding = 'utf-8'))


def test_there_are_targets():
    assert len(targets()) >= 10


@pytest.mark.parametrize('name', sorted(targets()))
def test_every_target_declares_where_it_works(name):
    s = targets()[name].get('support')
    assert isinstance(s, dict), f'task/target--{name}/_desc.yaml has no "support" block'
    assert s.get('kind') in KINDS
    assert str(s.get('hardware') or '').strip()
    assert s.get('status') in ('supported', 'placeholder')

    host_os = s.get('host_os')
    assert isinstance(host_os, list) and set(host_os) <= HOST_OS
    if s['status'] == 'placeholder':
        assert host_os == [] and not s.get('device_os')
    else:
        assert host_os, 'a supported target names the OS of the machine that drives it'
    if s.get('device_os'):
        assert s['device_os'] in DEVICE_OS


def test_programs_declare_known_targets():
    known = set(targets())
    for path in sorted((REPO_ROOT / 'program').glob('*/_cmeta.json')):
        meta = json.loads(path.read_text(encoding = 'utf-8'))
        for t in (meta.get('constraints') or {}).get('supported_compute') or []:
            assert t in known, f'{path.parent.name}: supported_compute names "{t}", which is no task/target--{t}'


def test_the_page_covers_every_kind_and_os():
    s = settings()
    kinds = set()
    for k in s['kinds']:
        kinds.add(k['id'])
        kinds.update(k.get('also') or [])
        assert k['light'].startswith('#') and k['dark'].startswith('#')
    oss = {o['id'] for o in s['os']}
    for name, d in targets().items():
        sup = d['support']
        assert sup['kind'] in kinds, f'the page has no kind for {name}'
        assert set(sup['host_os']) <= oss
        if sup.get('device_os'):
            assert sup['device_os'] in oss


def test_the_last_family_takes_every_program():
    families = settings()['families']
    assert '*' in families[-1]['match']
    for path in sorted((REPO_ROOT / 'program').glob('*/_cmeta.json')):
        assert any(fnmatch.fnmatch(path.parent.name, m) for f in families for m in f['match'])


def test_only_repos_patterns():
    spec = importlib.util.spec_from_file_location('cserver_cmeta_targets_under_test', PAGE / 'api' / 'v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._listed([], 'any', 'uid')
    assert module._listed(['ctuninglabs@cmeta-aops'], 'cTuningLabs@cmeta-aops', '3cb4ee4f444048f6')
    assert module._listed(['3cb4ee4f444048f6'], 'other-alias', '3cb4ee4f444048f6')
    assert module._listed(['*aops*'], 'ctuninglabs@cmeta-aops', '')
    assert not module._listed(['ctuninglabs@cmeta-aops'], 'private-repo', 'abcdef')
