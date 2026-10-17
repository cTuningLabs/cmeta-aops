"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

An instance (get-host--docker, get-host--wsl) sees its repositories live, but its index knows only what it saw when
it indexed them: a repository where an artifact was added here afterwards is reindexed inside when the instance is
reused (2026-10-17: "cx tool setup openshell --on=docker:ubuntu" did not find a tool added that afternoon). The
signature is the modification times of the repository's folder and its first-level folders.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel):
    path = REPO_ROOT / rel
    ns = {'__name__': path.parent.name.replace('-', '_'), '__file__': str(path)}
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), ns)
    return ns


@pytest.fixture(scope='module')
def ctask():
    return load('category/task/api/ctask.py')


@pytest.mark.parametrize('task', ['task/get-host--docker/api_v1.py', 'task/get-host--wsl/api_v1.py'])
def test_the_instance_tasks_use_the_shared_helpers(task):
    src = (REPO_ROOT / task).read_text(encoding='utf-8')
    assert 'from task_c36be4b9314a45e0.api.ctask import InitCTask, changed_mounts, write_signatures' in src
    assert 'def tree_signature' not in src


def test_a_new_artifact_marks_its_repository(ctask, tmp_path):
    m = ctask
    repo = tmp_path / 'repo'
    (repo / 'tool' / 'old').mkdir(parents=True)
    (repo / 'task').mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    instance = tmp_path / 'host-artifact'
    instance.mkdir()
    mounts = [{'repo': 'repo', 'path': str(repo)}, {'repo': 'other', 'path': str(other)}]

    assert [x['repo'] for x in m['changed_mounts'](str(instance), mounts)] == ['repo', 'other']   # never indexed

    # The folder's time as if it was made a while ago: a file system updates it only in a later tick of its clock
    # (NTFS kept the same value for a folder made within the same few milliseconds), as an edit here always is
    import os
    old = os.stat(repo / 'tool').st_mtime_ns - 5 * 10**9
    os.utime(repo / 'tool', ns=(old, old))
    m['write_signatures'](str(instance), mounts)
    assert m['changed_mounts'](str(instance), mounts) == []

    (repo / 'tool' / 'openshell').mkdir()                                  # a tool added here
    assert [x['repo'] for x in m['changed_mounts'](str(instance), mounts)] == ['repo']
    m['write_signatures'](str(instance), mounts)
    assert m['changed_mounts'](str(instance), mounts) == []
