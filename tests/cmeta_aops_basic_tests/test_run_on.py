"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of --on, the task category's delegation of a command line to a host (_run_on): the words as typed,
minus --on and its --on_<name> options, reach "cx host run" as "CMETA_ON=here cx <words>" quoted for a POSIX
shell; docker[:<template>] and podman[:<template>] go through get-host--docker with the options and the compute
word; --on=wsl, an unknown host and a Windows host are refused with a cure; the result is the inner exit code
with run_on (also in ctx['on']); a terminal is asked for only when this run has one.
"""

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class FakeFiles:
    def __init__(self, host_os):
        self.host_os = host_os

    def safe_read_yaml_or_json(self, path):
        return {'return': 0, 'data': {'os': self.host_os, 'type': 'ssh'}}


class FakeUtils:
    def __init__(self, host_os):
        self.files = FakeFiles(host_os)


class FakeCM:
    """The engine as _run_on sees it: host find / run, the task get-host--docker, error()."""

    def __init__(self, hosts=('lab-thinkpad-ubuntu',), host_os='ubuntu', returncode=0):
        self.hosts = hosts
        self.returncode = returncode
        self.calls = []
        self.utils = FakeUtils(host_os)

    def access(self, i):
        self.calls.append(dict(i))
        category, command = i['category'], i['command']

        if category.startswith('task,') and str(i.get('arg1', '')).startswith('get-host--docker'):
            return {'return': 0, 'host': f'pc-{i["engine"]}-{i["name"]}-26.04', 'made': True,
                    'image': f'cmeta/{i["name"]}:26.04-cmeta-latest', 'status': 'running'}

        if category.startswith('host,') and command == 'find':
            if i['arg1'] in self.hosts:
                return {'return': 0, 'artifacts': [{'path': '/hosts/' + i['arg1'],
                                                    'cmeta_ref_parts': {'artifact_alias': i['arg1']}}]}
            return {'return': 0, 'artifacts': []}

        if category.startswith('host,') and command == 'run':
            rc = self.returncode
            return {'return': 0 if rc == 0 else 1, 'outputs': {i['arg1']: {'returncode': rc, 'stdout': '', 'stderr': ''}}}

        raise AssertionError(f'unexpected call: {i}')

    def error(self, text):
        return {'return': 1, 'error': text}


@pytest.fixture(scope='module')
def module():
    path = REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py'
    spec = importlib.util.spec_from_file_location('task_api_v2_run_on_under_test', str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def category(module, **kwargs):
    c = module.Category.__new__(module.Category)
    c.cm = FakeCM(**kwargs)
    c.cmeta = {'artifact': 'c36be4b9314a45e0'}
    return c


def run_on(c, words, ref, params=None):
    ctx = {'origin': {'cli': {'cmd': list(words)}}}
    params = dict(params or {})
    params['on'] = ref
    return ctx, c._run_on(ctx, params, ref, False, False, False)


def host_run(c):
    runs = [i for i in c.cm.calls if i['category'].startswith('host,') and i['command'] == 'run']
    assert len(runs) == 1
    return runs[0]


def instance_request(c):
    made = [i for i in c.cm.calls if i['category'].startswith('task,')]
    assert len(made) == 1 and made[0]['arg1'].startswith('get-host--docker')
    return made[0]


def test_the_words_minus_on_reach_the_host(module):
    c = category(module)
    words = ['program', 'run', 'test-nmm-c-cpu', 'cpu', '-q', '--on=lab-thinkpad-ubuntu', '--on_repos=a,b', '--use.x.y=two words']
    ctx, r = run_on(c, words, 'lab-thinkpad-ubuntu', {'on_repos': 'a,b'})

    assert r['return'] == 0
    run = host_run(c)
    assert run['arg1'] == 'lab-thinkpad-ubuntu'
    assert run['arg2'] == "CMETA_ON=here cx program run test-nmm-c-cpu cpu -q '--use.x.y=two words'"
    assert run['interactive'] is False                   # no terminal under pytest: none asked for there
    assert r['run_on']['host'] == 'lab-thinkpad-ubuntu' and r['run_on']['returncode'] == 0
    assert r['run_on']['terminal'] is False
    assert ctx['on'] is r['run_on']
    assert not any(i['category'].startswith('task,') for i in c.cm.calls)      # a host artifact: no instance made


def test_a_docker_template_goes_through_get_host_docker(module):
    c = category(module)
    words = ['program', 'run', 'test-nmm-nvcc-cuda', 'cuda', '--on=docker:debian', '--on_arch=arm64',
             '--on_template.os_version=13', '--on_new_host']
    ctx, r = run_on(c, words, 'docker:debian', {'compute': 'cuda', 'on_arch': 'arm64',
                                                'on_template': {'os_version': '13'}, 'on_new_host': True})

    assert r['return'] == 0
    made = instance_request(c)
    assert made['name'] == 'debian' and made['engine'] == 'docker' and made['compute'] == 'cuda'
    assert made['arch'] == 'arm64' and made['template'] == {'os_version': '13'} and made['new_host'] is True
    run = host_run(c)
    assert run['arg1'] == 'pc-docker-debian-26.04'
    assert run['arg2'] == 'CMETA_ON=here cx program run test-nmm-nvcc-cuda cuda'
    assert r['run_on']['engine'] == 'docker' and r['run_on']['instance_made'] is True
    assert r['run_on']['image'] == 'cmeta/debian:26.04-cmeta-latest'


def test_podman_takes_the_default_template_and_a_compute_without_overlay_is_cpu(module):
    c = category(module)
    ctx, r = run_on(c, ['task', 'run', 'test-python', '--on=podman'], 'podman', {'compute': 'mps'})

    assert r['return'] == 0
    made = instance_request(c)
    assert made['name'] == 'ubuntu' and made['engine'] == 'podman' and made['compute'] == 'cpu'
    assert host_run(c)['arg1'] == 'pc-podman-ubuntu-26.04'


def test_wsl_is_refused_for_now(module):
    c = category(module)
    ctx, r = run_on(c, ['task', 'run', 'test-python', '--on=wsl'], 'wsl')

    assert r['return'] == 1 and '--on=docker' in r['error']
    assert c.cm.calls == []


def test_an_unknown_host_is_refused_with_the_cure(module):
    c = category(module)
    ctx, r = run_on(c, ['task', 'run', 'test-python', '--on=no-such-host'], 'no-such-host')

    assert r['return'] == 1
    assert 'cx host ls' in r['error'] and '--on=docker:no-such-host' in r['error']


def test_a_windows_host_is_refused_by_this_slice(module):
    c = category(module, hosts=('lab-pc-windows',), host_os='windows')
    ctx, r = run_on(c, ['task', 'run', 'test-python', '--on=lab-pc-windows'], 'lab-pc-windows')

    assert r['return'] == 1 and 'Windows' in r['error']


def test_the_inner_exit_code_is_the_result(module):
    c = category(module, returncode=3)
    ctx, r = run_on(c, ['task', 'run', 'test-python', '--on=lab-thinkpad-ubuntu'], 'lab-thinkpad-ubuntu')
    assert r['return'] == 3 and 'exit code 3' in r['error']
    assert r['run_on']['returncode'] == 3

    c = category(module, returncode=300)                 # outside what a process can return: 1
    ctx, r = run_on(c, ['task', 'run', 'test-python', '--on=lab-thinkpad-ubuntu'], 'lab-thinkpad-ubuntu')
    assert r['return'] == 1


def test_without_a_command_line_nothing_is_delegated(module):
    c = category(module)
    r = c._run_on({'origin': {}}, {'on': 'lab-thinkpad-ubuntu'}, 'lab-thinkpad-ubuntu', False, False, False)

    assert r['return'] == 1 and 'command line' in r['error']
    assert c.cm.calls == []
