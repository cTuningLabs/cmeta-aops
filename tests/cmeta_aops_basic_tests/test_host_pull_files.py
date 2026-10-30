"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx host pull --files from a container or a WSL instance brings the matching files of a folder, with their sub-folders,
and touches nothing else in the local folder. Before 2026-10-17 the whole folder was copied into the local folder and
every file there that did not match was then deleted - also the files that were there before the pull (the local
folder is the current directory by default); and a WSL instance copied the whole folder, which fails on names that
differ by case only when the local folder is on NTFS (the collect of a test-on-hosts round).
"""

import importlib.util
import os
import pathlib
import re
import shutil
from types import SimpleNamespace

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

CTX = {'control': {}}


def host_category(run=None):
    path = REPO_ROOT / "category" / "host" / "api" / "v1.py"
    spec = importlib.util.spec_from_file_location("category_host_pull_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    category = module.Category.__new__(module.Category)
    category.cm = SimpleNamespace(error=lambda message: {'return': 1, 'error': message},
                                  utils=SimpleNamespace(files=SimpleNamespace(quote_path=lambda p: '<' + p + '>')))
    if run is not None:
        category._run_local = run
    return category


def fake_docker(root):
    """docker cp out of a container whose files are those under root: '<c>:<path>/.' (a folder's contents) or '<c>:<path>'."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        m = re.match(r'^docker cp [^:]+:(\S+) <(.*)>$', cmd)
        source, dest = m.group(1), m.group(2)
        contents = source.endswith('/.')
        path = root.joinpath(*[p for p in (source[:-2] if contents else source).split('/') if p])
        if contents:
            if not path.is_dir():
                return {'returncode': 1, 'stderr': 'not a directory'}
            shutil.copytree(path, dest, dirs_exist_ok=True)
        elif path.is_dir():
            shutil.copytree(path, os.path.join(dest, path.name), dirs_exist_ok=True)
        elif path.is_file():
            shutil.copy2(path, dest)
        else:
            return {'returncode': 1, 'stderr': 'no such file'}
        return {'returncode': 0}

    return run, calls


def make(base, *names):
    for name in names:
        p = base.joinpath(*name.split('/'))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(name, encoding='utf-8')


def files_under(base):
    return sorted(str(p.relative_to(base)).replace(os.sep, '/') for p in base.rglob('*') if p.is_file())


DOCKER = {'alias': 'inst', 'type': 'docker', 'desc': {'access': {'user': 'u', 'container': 'inst'}}}
WSL = {'alias': 'inst-wsl', 'type': 'wsl', 'desc': {'access': {'user': 'u', 'distro': 'inst-wsl'}}}


def test_only_the_matching_files_come_and_the_local_ones_stay(tmp_path):
    container = tmp_path / 'container'
    make(container, 'home/u/work/steps.txt', 'home/u/work/step-1.log', 'home/u/work/sub/step-2.log',
         'home/u/work/big/data.bin', 'home/u/work/Notes.TXT')
    local = tmp_path / 'local'
    make(local, 'keep.me', 'old/keep.txt', 'old/other.log')

    run, calls = fake_docker(container)
    r = host_category(run)._copy_instance(CTX, DOCKER, 'work', str(local), into=False, files=['step-*.log', 'steps.txt'])
    assert r['return'] == 0, r

    assert files_under(local) == ['keep.me', 'old/keep.txt', 'old/other.log', 'step-1.log', 'steps.txt', 'sub/step-2.log']
    assert not any(n.startswith('.cmeta-pull-') for n in os.listdir(local))           # the landing folder is gone

    # the container's folder went into a landing folder inside the local one, not into the local folder itself
    landing = calls[0].split('<', 1)[1].rstrip('>')
    assert calls[0].startswith('docker cp inst:/home/u/work/. ')
    assert os.path.dirname(landing) == str(local) and os.path.basename(landing).startswith('.cmeta-pull-')


def test_without_files_the_whole_folder_comes_as_before(tmp_path):
    container = tmp_path / 'container'
    make(container, 'home/u/work/steps.txt', 'home/u/work/big/data.bin')
    local = tmp_path / 'local'
    make(local, 'keep.me')

    run, calls = fake_docker(container)
    r = host_category(run)._copy_instance(CTX, DOCKER, 'work', str(local), into=False, files=[])
    assert r['return'] == 0, r
    assert files_under(local) == ['big/data.bin', 'keep.me', 'steps.txt']
    assert calls == [f'docker cp inst:/home/u/work/. <{local}>']                        # straight into the local folder


def test_a_file_named_by_itself_comes_whatever_its_name(tmp_path):
    container = tmp_path / 'container'
    make(container, 'home/u/work/result.json')
    local = tmp_path / 'local'
    local.mkdir()

    run, _ = fake_docker(container)
    r = host_category(run)._copy_instance(CTX, DOCKER, 'work/result.json', str(local), into=False, files=['*.log'])
    assert r['return'] == 0, r
    assert files_under(local) == ['result.json']


def test_a_failed_copy_leaves_no_landing_folder_and_the_local_files(tmp_path):
    local = tmp_path / 'local'
    make(local, 'keep.me')

    run, _ = fake_docker(tmp_path / 'empty-container')
    r = host_category(run)._copy_instance(CTX, DOCKER, 'work', str(local), into=False, files=['*.log'])
    assert r['return'] == 1 and 'failed' in r['error']
    assert files_under(local) == ['keep.me'] and os.listdir(local) == ['keep.me']


def test_wsl_copies_only_the_matching_files(tmp_path):
    category = host_category()
    r = category._copy_instance(CTX, WSL, 'work', str(tmp_path), into=False, files=['step-*.log', 'steps.txt'], dry_run=True)
    assert r['return'] == 0
    cmd = r['cmds'][0]
    assert cmd.startswith('wsl.exe -d inst-wsl --user u -- sh -c "')
    assert "find . -type f \\( -name 'step-*.log' -o -name steps.txt \\) -exec cp --parents -t " in cmd
    assert 'cp -r' not in cmd

    # without --files: the whole folder, as before
    r = category._copy_instance(CTX, WSL, 'work', str(tmp_path), into=False, files=[], dry_run=True)
    assert 'cp -r /home/u/work/. ' in r['cmds'][0] and 'find' not in r['cmds'][0]


def test_without_a_declared_user_a_relative_path_is_under_the_instances_home(tmp_path):
    """A container that declares no user (a bare ubuntu image runs as root) took a relative --to under "/": a
    test-on-hosts round pushed its runner to /cmeta-tests while its launcher looked in $HOME/cmeta-tests and never
    started (2026-10-30). The home is the instance's own ($HOME of its default user), as an ssh login's is."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd.endswith('printenv HOME'):
            return {'returncode': 0, 'stdout': '/root\n'}
        return {'returncode': 0}

    bare = {'alias': 'bare', 'type': 'docker', 'desc': {'access': {'container': 'cmeta-bare'}}}
    (tmp_path / 'runner.py').write_text('x')
    r = host_category(run)._copy_instance(CTX, bare, str(tmp_path / 'runner.py'), 'cmeta-tests/r1/runner.py', into=True, dry_run=True)
    assert calls == ['docker exec cmeta-bare printenv HOME']
    assert r['remote'] == '/root/cmeta-tests/r1/runner.py'
    assert r['cmds'][0] == 'docker exec cmeta-bare mkdir -p /root/cmeta-tests/r1'

    # a declared user decides as before, without asking the container; an instance that does not answer keeps "/"
    calls.clear()
    assert host_category(run)._copy_instance(CTX, DOCKER, 'work', str(tmp_path), into=False, dry_run=True)['remote'] == '/home/u/work'
    assert calls == []
    quiet = host_category(lambda cmd, **kw: {'returncode': 1, 'stderr': 'no such container'})
    assert quiet._copy_instance(CTX, bare, 'work', str(tmp_path), into=False, dry_run=True)['remote'] == '/work'


def test_a_dry_run_makes_no_landing_folder(tmp_path):
    r = host_category()._copy_instance(CTX, DOCKER, 'work', str(tmp_path), into=False, files=['*.log'], dry_run=True)
    assert r['return'] == 0 and r['dry_run']
    assert os.listdir(tmp_path) == []
