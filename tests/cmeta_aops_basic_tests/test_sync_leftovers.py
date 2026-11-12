"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The named syncs (task::sync) and the folders a two-way run leaves behind - emptied of every file it carries, held on a
side by files its filters leave out: after a run that was not a first one, task::sync asks the host category
(sync_leftovers, the step of cx host sync) to move them aside into the run's folder of each side's sync-backup artifact.
Here: what task::sync sends, and the host category's command reached through the engine, on two local folders.
"""
from pathlib import Path
import os
import time

import pytest

OLD = time.time() - 86400


def make(root, rel, when=OLD):
    path = Path(root, *rel.split('/'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x')
    os.utime(path, (when, when))
    return path


def listing(path, names):
    lines = ['# bisync listing v1 from 2026-11-12T14:09:59.052450000+0000']
    lines += [f'-       10 - - 2026-11-12T10:00:00.000000000+0000 "{n}"' for n in names]
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def pair(workdir, old, new):
    """The listings rclone leaves in a named sync's workdir after a run: before (-old) and after, both sides."""
    workdir.mkdir(parents=True, exist_ok=True)
    base = workdir / 'C__x_a..C__x_b'
    for side in (1, 2):
        listing(f'{base}.path{side}.lst-old', old)
        listing(f'{base}.path{side}.lst', new)


def plan(tmp_path, remote=True):
    dest = (dict(path=':sftp:CMETA/repos', remote=True, host='host::lab', ssh='ssh u@lab', host_repos='~/CMETA/repos')
            if remote else dict(path=str(tmp_path / 'b'), remote=False, host='local'))
    return dict(alias='site', uid='0123456789abcdef', state_ref='local:sync--site--0123456789abcdef', mode='bisync',
                source=dict(path=str(tmp_path / 'a'), remote=False, host='local'), destination=dest,
                filters=['- **/sync--*/**', '- *.sqlite-wal', '+ /notes/**', '- **'], transfers=1, bwlimit='',
                max_delete=50, resync_mode='path1', remove_empty_dirs=False)


def test_transfer_says_where_the_backups_of_the_run_went(cm, tmp_path, task_namespace):
    ns = task_namespace('sync')
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = cm
    task.access = lambda category, command, **p: {'artifact': {'path': str(tmp_path / 'art')}}
    task.task = lambda ctx, ref, **p: {'path': 'rclone'}
    task.command = lambda ctx, argv, env: {'returncode': 0}

    moved = task.transfer({'control': {}}, plan(tmp_path), tmp_path / 'wd', tmp_path / 'run.log', False, True, 'run1')

    assert moved == {'local_art': {'path': str(tmp_path / 'art')}, 'remote_art': 'CMETA/repos/local/result/sync-backup--site--0123456789abcdef',
                     'rclone': 'rclone', 'env': {'RCLONE_SFTP_SSH': 'ssh u@lab'}}


@pytest.mark.parametrize('moved_there', [True, False])
def test_the_host_category_is_asked_with_both_sides(cm, tmp_path, task_namespace, moved_there):
    ns = task_namespace('sync')
    task = ns['CTask'].__new__(ns['CTask'])
    asked, marked = [], []
    task.cm = type('cm', (), {'access': staticmethod(lambda p: asked.append(p) or
                                                     {'return': 0, 'notes': ['1 folder(s) left behind ...'],
                                                      'moved': {'2': moved_there}})})()
    task.cmeta = {'uses_categories': {'host': 'host,e4e49c251c814f6d'}}
    task.mark_backup = lambda ctx, rclone, env, local_art, remote_art, run_id: marked.append((remote_art, run_id))
    moved = {'local_art': {'path': str(tmp_path / 'art')}, 'remote_art': 'CMETA/repos/local/result/sync-backup--site--0123456789abcdef',
             'rclone': 'rclone', 'env': {}}

    notes = task.leftovers({'control': {'con': False}}, plan(tmp_path), tmp_path / 'wd', 'run1', moved,
                           'INFO  : - Path2    Queue delete    - Path1    notes/work/2026/x.md')

    assert notes == ['1 folder(s) left behind ...']
    p = asked[0]
    assert p['category'] == 'host,e4e49c251c814f6d' and p['command'] == 'sync_leftovers' and p['workdir'] == str(tmp_path / 'wd')
    assert p['deleted'] is True and p['partial'] is True and p['filters'] == plan(tmp_path)['filters']
    assert p['sides'][0] == {'where': 'this machine', 'host': 'local', 'root': str(tmp_path / 'a'),
                             'dest': str(tmp_path / 'art' / 'run1')}
    assert p['sides'][1] == {'where': 'lab', 'host': 'host::lab', 'root': 'CMETA/repos',
                             'dest': 'CMETA/repos/local/result/sync-backup--site--0123456789abcdef/run1'}
    assert marked == ([('CMETA/repos/local/result/sync-backup--site--0123456789abcdef', 'run1')] if moved_there else [])


def test_a_first_run_or_a_run_without_deletes_is_said_so(cm, tmp_path, task_namespace):
    """execute() asks only after a two-way run that was not a first one; the run's own words say whether it deleted."""
    ns = task_namespace('sync')
    source = (Path(ns['__file__'])).read_text(encoding='utf-8')
    assert "if plan['mode'] == 'bisync' and not initial and moved else []" in source
    task = ns['CTask'].__new__(ns['CTask'])
    asked = []
    task.cm = type('cm', (), {'access': staticmethod(lambda p: asked.append(p) or {'return': 0, 'notes': [], 'moved': {}})})()
    task.cmeta = {'uses_categories': {'host': 'host,e4e49c251c814f6d'}}
    moved = {'local_art': {'path': str(tmp_path / 'art')}, 'remote_art': None, 'rclone': 'rclone', 'env': {}}
    task.leftovers({'control': {}}, plan(tmp_path, remote=False), tmp_path / 'wd', 'run1', moved, 'INFO  : Bisync successful')
    assert asked[0]['deleted'] is False and [s['host'] for s in asked[0]['sides']] == ['local', 'local']
    assert [s['where'] for s in asked[0]['sides']] == ['this machine (the source)', 'this machine (the destination)']


def test_the_command_through_the_engine_moves_what_a_named_sync_left_behind(cm, tmp_path):
    a, b, wd = tmp_path / 'a', tmp_path / 'b', tmp_path / 'wd'
    pair(wd, ['notes/keep/a.md', 'notes/work/2026/i/_cmeta.yaml'], ['notes/keep/a.md'])
    make(a, 'notes/keep/a.md')
    make(b, 'notes/keep/a.md')
    make(b, 'notes/work/2026/i/!AI/codex/logs_2.sqlite-wal')          # left there, the folder deleted on the other side
    make(b, 'other-repo/notes.md')                                    # outside the selection: never touched
    sides = [{'where': 'the source', 'host': 'local', 'root': str(a), 'dest': str(tmp_path / 'bk-a')},
             {'where': 'the destination', 'host': 'local', 'root': str(b), 'dest': str(tmp_path / 'bk-b')}]

    r = cm.access({'category': 'host', 'command': 'sync_leftovers', 'workdir': str(wd), 'sides': sides,
                   'filters': plan(tmp_path)['filters'], 'deleted': True, 'partial': True, 'con': False})

    assert r['return'] == 0, r
    assert r['moved'] == {'1': False, '2': True} and any('moved aside on the destination: notes/work' in n for n in r['notes'])
    assert not (b / 'notes' / 'work').exists() and (tmp_path / 'bk-b' / 'notes' / 'work' / '2026' / 'i' / '!AI' / 'codex' / 'logs_2.sqlite-wal').is_file()
    assert (b / 'other-repo' / 'notes.md').is_file() and (b / 'notes' / 'keep' / 'a.md').is_file()


def test_a_folder_holding_the_syncs_own_artifacts_stays(cm, tmp_path):
    # a result folder emptied of what the sync carries still holds the pair's backups: this side's own, never moved
    b, wd = tmp_path / 'b', tmp_path / 'wd'
    pair(wd, ['notes/result/r1/_cmeta.yaml', 'notes/keep/a.md'], ['notes/keep/a.md'])
    make(b, 'notes/keep/a.md')
    make(b, 'notes/result/sync-backup--site--0123456789abcdef/_cmeta.json')
    make(b, 'notes/result/sync-backup--site--0123456789abcdef/run1/x.md')
    sides = [{'where': 'the source', 'host': 'local', 'root': str(tmp_path / 'a'), 'dest': str(tmp_path / 'bk-a')},
             {'where': 'the destination', 'host': 'local', 'root': str(b), 'dest': str(tmp_path / 'bk-b')}]
    filters = ['- **/result/sync-backup--*/**', '+ /notes/**', '- **']

    r = cm.access({'category': 'host', 'command': 'sync_leftovers', 'workdir': str(wd), 'sides': sides,
                   'filters': filters, 'deleted': True, 'partial': True, 'con': False})

    assert r['return'] == 0 and r['moved'] == {'1': False, '2': False} and r['notes'] == []
    assert (b / 'notes' / 'result' / 'sync-backup--site--0123456789abcdef' / 'run1' / 'x.md').is_file()


def test_without_listings_nothing_is_looked_at(cm, tmp_path):
    r = cm.access({'category': 'host', 'command': 'sync_leftovers', 'workdir': str(tmp_path / 'none'), 'sides': [],
                   'filters': [], 'deleted': True, 'con': False})
    assert r == {'return': 0, 'notes': [], 'moved': {}}
