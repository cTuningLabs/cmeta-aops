"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of test-on-hosts as a matrix: at a launch a ref of an instance that cannot be made (an image that does
not build - Debian 11 after its end of life) is said and left out while the other refs run; outside a launch the
first failure stops; peek / collect / remove without --hosts take the hosts the launch recorded in round.json, so a
ref is neither made again nor retried.
"""

import json
import pathlib
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class FakeFiles:
    def safe_read_yaml_or_json(self, path):
        return {'return': 0, 'data': {'mounts': [{'repo': 'ctuninglabs@cmeta-aops', 'path': '/tree',
                                                   'inside': '/home/cmeta/repos/ctuninglabs@cmeta-aops'}]}}


class FakeCM:
    def __init__(self):
        self.calls = []
        self.utils = type('U', (), {'files': FakeFiles()})()

    def access(self, p):
        self.calls.append(p)
        if p.get('command') == 'run' and p.get('category') == 'task':
            version = (p.get('template') or {}).get('os_version', '')
            if version == '11':
                return {'return': 1, 'error': 'docker build failed for cmeta/debian:11-cmeta-latest'}
            return {'return': 0, 'host': f'here-docker-{p["name"]}-{version}'}
        if p.get('command') == 'find' and p.get('category') == 'host':
            return {'return': 0, 'artifacts': [{'path': '/x'}]}
        if p.get('command') == 'run' and p.get('category') == 'host':
            return {'return': 0, 'outputs': {p['arg1']: {'stdout': 'done 2026-10-16T23:59:00Z\n1: exit 0 in 1 s: task run test-python -q\n'}}}
        return {'return': 0}

    def error(self, text):
        return {'return': 1, 'error': text}


@pytest.fixture(scope='module')
def module():
    path = REPO_ROOT / 'task' / 'test-on-hosts' / 'api_v1.py'
    src = path.read_text(encoding='utf-8').replace('from task_c36be4b9314a45e0.api.ctask import InitCTask',
                                                   'class InitCTask:\n    pass')
    ns = types.ModuleType('test_on_hosts_under_test')
    ns.__file__ = str(path)
    exec(compile(src, str(path), 'exec'), ns.__dict__)
    return ns


def task(module):
    t = module.CTask.__new__(module.CTask)
    t.cm = FakeCM()
    t.instances = {}
    t.failed_refs = {}
    return t


REFS = ['docker:debian --on_template.os_version=11', 'docker:debian --on_template.os_version=12', 'fgg-t470p-ubuntu']


def test_a_launch_leaves_out_a_ref_that_cannot_be_made(module):
    t = task(module)
    r = t.resolve_refs(False, REFS, tolerant=True)
    assert r['return'] == 0
    assert r['hosts'] == ['here-docker-debian-12', 'fgg-t470p-ubuntu']
    assert list(r['failed']) == [REFS[0]] and 'debian:11' in r['failed'][REFS[0]]
    assert r['instances']['here-docker-debian-12']['tree_inside'] == '/home/cmeta/repos/ctuninglabs@cmeta-aops'


def test_otherwise_the_first_failure_stops(module):
    r = task(module).resolve_refs(False, REFS, tolerant=False)
    assert r['return'] == 1 and 'debian:11' in r['error']


def test_peek_without_hosts_takes_the_hosts_of_the_launch(module, tmp_path):
    t = task(module)
    t.local_folder = lambda rid: str(tmp_path / f'test-on-hosts-{rid}')
    (tmp_path / 'test-on-hosts-m1').mkdir()
    (tmp_path / 'test-on-hosts-m1' / module.ROUND_FILE).write_text(json.dumps(
        {'hosts': ['here-docker-debian-12'], 'instances': {'here-docker-debian-12': {'engine': 'docker'}},
         'failed_refs': {REFS[0]: 'docker build failed'}}))

    r = t.run({'control': {'con': False}}, action='peek', id='m1')
    assert r['return'] == 0 and r['done'] and list(r['hosts']) == ['here-docker-debian-12']
    # no instance was made or looked for again: only the peek script ran on the recorded host
    assert not [c for c in t.cm.calls if c.get('category') == 'task']
