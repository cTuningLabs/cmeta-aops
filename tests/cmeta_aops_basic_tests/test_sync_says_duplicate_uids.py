"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A sync says when the reindex after it finds one artifact UID in two folders (`duplicates` of "cx repo reindex",
a cMeta after 0.45.6): cx host sync for this machine's side and for the lines of the host's own reindex, a named
sync for a home of this process. An engine that lists none changes nothing. Offline: cMeta's access and the
commands are stand-ins.
"""

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TWICE = {'category': 'note', 'uid': 'aaaaaaaaaaaaaaaa', 'kept': '/repos/first/note/a', 'kept_repo': 'first',
         'left_out': '/repos/second/note/a', 'left_out_repo': 'second'}


def load(rel_path, name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def host_module():
    return load('category/host/api/v1.py', 'host_sync_duplicates_under_test')


def host(host_module, answer):
    """The host category whose engine answers "repo reindex" with `answer`; a sync that changed a _cmr file here."""
    c = host_module.Category.__new__(host_module.Category)
    c.asked = []
    c.cm = SimpleNamespace(access=lambda p: c.asked.append((p['category'], p['command'])) or dict(answer))
    c._sync_changed_meta = lambda h, entry, side: ['_cmr.yaml']
    return c


def test_host_sync_lists_the_folders_this_machines_reindex_left_out(host_module, capsys):
    c = host(host_module, {'return': 0, 'duplicates': [TWICE]})
    c._index_here({'alias': 'lab'}, 'second', {'local': '/repos/second'}, True)

    out = capsys.readouterr().out
    assert c.asked == [('repo', 'reindex')] and 'INDEX (here): cx repo reindex second - ok' in out
    assert 'cMeta warning:' in out and 'aaaaaaaaaaaaaaaa' in out
    assert '/repos/first/note/a' in out and '/repos/second/note/a' in out and 'cx repo reindex second' in out


def test_an_engine_that_lists_none_changes_nothing(host_module, capsys):
    c = host(host_module, {'return': 0})
    c._index_here({'alias': 'lab'}, 'second', {'local': '/repos/second'}, True)
    assert 'cMeta warning' not in capsys.readouterr().out

    c = host(host_module, {'return': 0, 'duplicates': [TWICE]})
    c._index_here({'alias': 'lab'}, 'second', {'local': '/repos/second'}, False)
    assert capsys.readouterr().out == ''


def test_host_sync_passes_on_what_the_hosts_own_reindex_said(host_module, capsys):
    c = host_module.Category.__new__(host_module.Category)
    c.cm = SimpleNamespace(catch_error=lambda r: r['return'] > 0)
    c._shell = lambda h: 'bash'
    c._sh_path = lambda p: p
    c._cmd_run = lambda ctx, h, cmd: {'return': 0, 'cmd': 'ssh lab ' + cmd}
    said = ('Indexing again: /repos/second\n'
            'cMeta warning: note artifact aaaaaaaaaaaaaaaa is in two folders: "/repos/first/note/a" is in the index, '
            '"/repos/second/note/a" is left out of it\n'
            'cMeta warning: 1 folder(s) left out of the index: one UID names one artifact.\n'
            'cMeta warning: something else\n')
    c._run_local = lambda cmd, **kw: {'returncode': 0, 'stdout': said}

    r = c._index_on_host({}, {'alias': 'lab'}, 'second', '/repos/second', True, False)
    out = capsys.readouterr().out

    assert r['return'] == 0 and 'INDEX (lab):' in out
    assert out.count('(lab) cMeta warning:') == 2 and 'something else' not in out and 'Indexing again' not in out


def test_a_named_sync_lists_them_for_a_home_of_this_process(tmp_path, capsys, task_namespace):
    cls = task_namespace('sync')['CTask']
    task = cls.__new__(cls)
    task.cm = SimpleNamespace(home_path=str(tmp_path), access=lambda p: {'return': 0, 'duplicates': [TWICE]})

    done = task.reindex({'control': {'con': True}},
                        [{'remote': False, 'home': str(tmp_path), 'host': None, 'side': 'destination', 'repos': ['second']}])
    out = capsys.readouterr().out

    assert done[0]['ok'] == ['second'] and done[0]['duplicates'] == [TWICE]
    assert 'reindexed second' in out and 'cMeta warning:' in out and '/repos/second/note/a' in out
