"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of test-on-hosts as a matrix: at a launch a ref of an instance that cannot be made (an image that does
not build - Debian 11 after its end of life) is said and left out while the other refs run; outside a launch the
first failure stops; peek / collect / remove without --hosts take the hosts the launch recorded in round.json, so a
ref is neither made again nor retried.
"""

import json
import os
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


def test_a_peek_or_collect_from_another_directory_says_so_and_leaves_nothing(module, tmp_path, monkeypatch):
    """Without the round's test session in the shell, the round's folder is looked for in the current directory: a peek
    made a test-on-hosts-<id> folder there for its helper script (also inside a repository) and reported this machine's
    part as running, a collect copied nothing without a word (2026-10-17). Now nothing is made and both say where they
    looked."""
    t = task(module)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    t.local_folder = lambda rid: str(elsewhere / f'test-on-hosts-{rid}')

    r = t.peek(False, 'm2', str(elsewhere / 'test-on-hosts-m2'), 'cmeta-tests/test-on-hosts-m2', ['here', 'fgg-t470p-ubuntu'])
    assert r['return'] == 0 and not r['done']
    assert r['hosts']['here']['lines'][0].startswith('unknown: ')
    assert r['hosts']['fgg-t470p-ubuntu']['done']                      # the remote host answered through its script
    assert list(elsewhere.iterdir()) == []                              # no folder made for the helper script

    c = t.collect(False, 'm2', str(elsewhere / 'test-on-hosts-m2'), 'cmeta-tests/test-on-hosts-m2', ['here'], '*.jsonl',
                  str(tmp_path / 'collected'))
    assert c['hosts']['here'].startswith('not found: ')


def test_the_remove_of_this_machines_part_takes_the_read_only_files_of_a_clone(module, tmp_path):
    """A round's cache holds git clones, whose object files are read-only on Windows: shutil.rmtree left them, and the
    round stayed on disk (2026-10-17). The engine's delete (utils.files.safe_delete_directory) removes them."""
    import os
    import stat
    from cmeta import utils

    t = task(module)
    t.cm.utils = type('U', (), {'files': utils.files})()
    local = tmp_path / 'test-on-hosts-m3'
    objects = local / 'here' / 'home' / 'repos' / 'local' / 'cache' / 'clone' / '.git' / 'objects' / 'ab'
    objects.mkdir(parents=True)
    obj = objects / 'cdef'
    obj.write_bytes(b'x')
    os.chmod(obj, stat.S_IREAD)

    r = t.remove(False, 'm3', str(local), 'cmeta-tests/test-on-hosts-m3', ['here'])
    assert r['return'] == 0
    assert not (local / 'here').exists()


def test_the_tarball_leaves_out_links_that_lead_out_of_the_tree(module, tmp_path):
    """A developer's link to another clone (__symlinks/cmeta -> an absolute path) went into the tarball, and the
    tarfile of Python 3.14 refused to unpack it: the round failed on the host (2026-10-29). A link inside the tree
    stays."""
    import tarfile

    tree = tmp_path / 'tree'
    (tree / 'task').mkdir(parents=True)
    (tree / 'task' / 'a.txt').write_text('a')
    (tree / '__symlinks').mkdir()
    try:
        os.symlink(str(tmp_path), tree / '__symlinks' / 'absolute', target_is_directory=True)
        os.symlink('../task', tree / '__symlinks' / 'inside', target_is_directory=True)
        os.symlink('../../elsewhere', tree / '__symlinks' / 'outside', target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f'no symbolic links here: {e}')

    out = tmp_path / 'tree.tar.gz'
    module.tar_tree(str(tree), str(out))
    with tarfile.open(out) as tar:
        names = tar.getnames()
        assert 'tree/task/a.txt' in names and 'tree/__symlinks/inside' in names
        assert 'tree/__symlinks/absolute' not in names and 'tree/__symlinks/outside' not in names
        # what the runner does, with the filter Python 3.14 applies by default where there is one
        if hasattr(tarfile, 'data_filter'):
            tar.extractall(tmp_path / 'unpacked', filter='data')


DESCS = {'win-host': {'type': 'ssh', 'os': 'windows', 'access': {'shell': 'powershell'}},
         'fgg-t470p-ubuntu': {'type': 'ssh', 'os': 'linux', 'access': {'shell': 'bash -l'}}}


class FleetCM(FakeCM):
    """A Windows host (ssh, PowerShell) next to a Linux one: the descs by host, the scripts each host ran (read when
    they run - the task deletes its helper scripts) and the files pushed to each."""

    def __init__(self):
        super().__init__()
        read = lambda _, path: {'return': 0, 'data': DESCS.get(os.path.basename(os.path.dirname(path)), {})}
        self.utils = type('U', (), {'files': type('F', (), {'safe_read_yaml_or_json': read})()})()
        self.ran = {}
        self.pushed = {}

    def access(self, p):
        if p.get('category') == 'host' and p.get('command') == 'find':
            return {'return': 0, 'artifacts': [{'path': f'/hosts/{p["arg1"]}'}]}
        if p.get('category') == 'host' and p.get('command') == 'run':
            self.ran.setdefault(p['arg1'], []).append(pathlib.Path(p['script']).read_text() if p.get('script') else p.get('arg2'))
        if p.get('category') == 'host' and p.get('command') == 'push':
            self.pushed.setdefault(p['arg1'], []).append(p['to'])
        return super().access(p)


def test_a_windows_host_gets_powershell_scripts_and_its_commands_in_a_file(module, tmp_path):
    """The launcher, the peek and the removal were bash scripts for every remote host: a Windows host (its shell
    PowerShell) failed to start a round (2026-10-29). It gets PowerShell scripts, and its commands in commands.json
    next to the runner, so that no quoting of cmd.exe touches them."""
    t = task(module)
    t.cm = FleetCM()
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / '_cmr.yaml').write_text('alias: x\n')
    local = tmp_path / 'test-on-hosts-w1'
    remote = 'cmeta-tests/test-on-hosts-w1'
    hosts = ['win-host', 'fgg-t470p-ubuntu']

    r = t.launch(False, 'w1', str(local), remote, hosts, 'task run upgrade-os --check -q; !echo "a b"', str(tree))
    assert r['return'] == 0
    assert json.loads((local / 'commands.json').read_text()) == ['task run upgrade-os --check -q', '!echo "a b"']
    assert f'{remote}/commands.json' in t.cm.pushed['win-host']
    assert not [to for to in t.cm.pushed['fgg-t470p-ubuntu'] if to.endswith('commands.json')]
    win, linux = t.cm.ran['win-host'][0], t.cm.ran['fgg-t470p-ubuntu'][0]
    assert "Join-Path $HOME 'cmeta-tests\\test-on-hosts-w1'" in win and 'Win32_Process' in win and '@commands.json' in win
    assert linux.startswith('#!/bin/bash') and 'nohup' in linux and '@commands.json' not in linux

    p = t.peek(False, 'w1', str(local), remote, hosts)
    assert p['return'] == 0 and p['done']
    assert 'Test-Path "$ROOT\\DONE"' in t.cm.ran['win-host'][1] and t.cm.ran['fgg-t470p-ubuntu'][1].startswith('#!/bin/bash')

    d = t.remove(False, 'w1', str(local), remote, hosts)
    assert d['removed'] == {'win-host': True, 'fgg-t470p-ubuntu': True}
    assert 'Remove-Item -LiteralPath $ROOT -Recurse -Force' in t.cm.ran['win-host'][2]
    assert t.cm.ran['fgg-t470p-ubuntu'][2] == f'rm -rf ~/{remote}'

    # an instance (a container or a WSL distribution of a Windows machine) is no Windows host
    t.instances = {'win-host': {'engine': 'docker'}}
    assert not t.is_windows('win-host')


def test_this_machines_part_lives_in_here_dir_and_round_json_names_it(module, tmp_path):
    """This machine's part of a round runs in <here_dir>/test-on-hosts-<id> (the key here_dir of task-test-on-hosts, else
    ~/cmeta-tests, like a remote host): inside a test session's sandbox it was too deep for MSVC (2026-10-17). The
    launch records it in round.json, so peek, collect and remove find it from any directory."""
    import os

    class ConfigCM(FakeCM):
        def __init__(self, here):
            super().__init__()
            self.here = here

        def access(self, p):
            if p.get('category') == module.CONFIG_CATEGORY:
                return {'return': 0, 'config_cmeta': {'here_dir': self.here} if self.here else {}}
            return super().access(p)

    assert module.here_dir(ConfigCM(str(tmp_path / 'short'))) == str(tmp_path / 'short')
    assert module.here_dir(ConfigCM(None)) == os.path.join(os.path.expanduser('~'), 'cmeta-tests')

    # a round whose part here is elsewhere: peek reads it where round.json says
    part = tmp_path / 'short' / 'test-on-hosts-m4'
    (part / 'work').mkdir(parents=True)
    (part / 'DONE').write_text('done 2026-10-17T15:00:00Z\n')
    (part / 'work' / 'steps.txt').write_text('1: exit 0 in 1 s: task run test-python -q\n')
    local = tmp_path / 'sandbox' / 'test-on-hosts-m4'
    local.mkdir(parents=True)
    (local / module.ROUND_FILE).write_text(json.dumps({'hosts': ['here'], 'here_root': str(part)}))

    t = task(module)
    t.local_folder = lambda rid: str(local)
    r = t.run({'control': {'con': False}}, action='peek', id='m4')
    assert r['return'] == 0 and r['done'] and r['hosts']['here']['lines'][1].startswith('1: exit 0')
