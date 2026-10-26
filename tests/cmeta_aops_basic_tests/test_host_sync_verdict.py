"""
cx host sync, the run that finishes and proves it (the host category, offline):

- what rclone's bisync said when it failed is read into a kind: a stale lock, its delete guard (which side, how
  many), a pair that needs a new baseline, a transient error, anything else;
- what a captured run moved is counted from rclone's own lines, for a bisync (the queue with its direction), a resync
  (two phases) and a one-way copy;
- the combined listing of rclone check is read into counts and the conflict copies it holds, and told in one line;
- two versions of a memory index merge as a line union, and the conflict copies of an index are settled on both sides
  through copyto and rm (recorded here, no host reached);
- the robust sync repairs in order - the lock dropped, the deletes forced only when the side that lost them is still a
  repository, a new pair seeded from this machine, a transient error tried again - and gives up on the rest;
- the banner says STATUS: SUCCESS or FAILED in large letters, the summary wrapped under it.

Nothing of the user's cMeta is touched: the engine runs on a home under tmp_path, the host is never reached.
"""

import importlib.util
import logging
import os
import pathlib
import threading

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

LOCK = 'NOTICE: Failed to bisync: prior lock file found: C:\\x\\bisync\\pair.lck'
TOO_MANY = ('ERROR : Safety abort: too many deletes (>50%, 5090 of 6472) on Path1 "D:\\repo\\". Run with --force if desired.\n'
            'NOTICE: Bisync aborted. Please try again.\nNOTICE: Failed to bisync: too many deletes')
NEEDS_RESYNC = 'ERROR : Bisync critical error: cannot find prior Path1 or Path2 listings, likely due to critical error on prior run\nNOTICE: Bisync aborted. Must run --resync to recover.'
TRANSIENT = 'Errors:                 1 (retrying may help)\nNOTICE: Failed to bisync: a transient thing'


@pytest.fixture()
def host(tmp_path, monkeypatch):
    """The host category as the engine makes it, on a home of the test; its remote calls recorded, never made."""
    from cmeta import CMeta

    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))
    c = CMeta(home=str(tmp_path / 'home'))

    spec = importlib.util.spec_from_file_location('category_host_verdict_under_test', str(REPO_ROOT / 'category' / 'host' / 'api' / 'v1.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    h = module.Category.__new__(module.Category)
    h.cm = c
    h.cmeta = yaml.safe_load((REPO_ROOT / 'category' / 'host' / '_cmeta.yaml').read_text(encoding='utf-8-sig'))
    h.logger = logging.getLogger('host-verdict-under-test')
    h._key_cache, h._host_cache, h._adb_batch, h._adb_locks = {}, {}, None, {}
    h._adb_lock = threading.Lock()
    h.calls = []
    h._shell = lambda host: 'bash'
    h._cmd_run = lambda ctx, host, cmd, **kw: (h.calls.append(('cmd', cmd)) or {'return': 0, 'cmd': cmd})
    h._run_local = lambda cmd, **kw: (h.calls.append(('run', cmd)) or {'return': 0, 'returncode': 0, 'stdout': ''})
    h._rclone = lambda ctx, host, command, local, remote, **kw: (h.calls.append(('rclone', command, local, remote)) or {'return': 0, 'output': ''})
    return h


HOST = {'alias': 'far-away', 'uid': 'a8b2c3d4e5f60718', 'type': 'ssh', 'desc': {}, 'state': {}}


def test_what_rclone_said_becomes_a_kind(host):
    assert host._bisync_failure(LOCK) == ('lock', None)
    assert host._bisync_failure(TOO_MANY) == ('too-many-deletes', ('Path1', 5090, 6472))
    assert host._bisync_failure(NEEDS_RESYNC) == ('needs-resync', None)
    assert host._bisync_failure(TRANSIENT) == ('transient', None)
    assert host._bisync_failure('NOTICE: Failed to bisync: something new') == ('other', None)
    assert host._bisync_failure('') == ('other', None)


def test_what_a_bisync_moved_is_counted_with_its_direction(host):
    text = ('2026/10/26 NOTICE: - Path1    Queue copy to Path2       - :sftp:/r/a.md\n'
            '2026/10/26 NOTICE: - Path1    Queue copy to Path2       - :sftp:/r/b.md\n'
            '2026/10/26 NOTICE: - Path2    Queue copy to Path1       - D:\\repo\\c.md\n'
            '2026/10/26 NOTICE: - Path1    Queue delete              - D:\\repo\\gone.md\n')
    n = host._moved(text)
    assert n == {'to_host': 2, 'to_here': 1, 'deleted_host': 0, 'deleted_here': 1}
    assert host._moved_text(n) == '2 to host, 1 here, 1 deleted here'
    assert host._moved_text(host._moved('')) == 'nothing to move'


def test_what_a_resync_moved_is_counted_per_phase(host):
    text = ('NOTICE: - Path2    Resync is copying files to         - Path1\n'
            'INFO  : x/back.md: Copied (new)\n'
            'NOTICE: - Path1    Resync is copying files to         - Path2\n'
            'INFO  : a.md: Copied (new)\nINFO  : b.md: Copied (replaced existing)\nINFO  : c.md: Copied (new)\n')
    assert host._moved(text) == {'to_host': 3, 'to_here': 1, 'deleted_host': 0, 'deleted_here': 0}


def test_what_a_one_way_copy_moved_is_counted_from_its_lines(host):
    text = 'INFO  : a.md: Copied (new)\nINFO  : b.md: Copied (replaced existing)\nINFO  : old.md: Deleted\n'
    assert host._moved(text) == {'to_host': 2, 'to_here': 0, 'deleted_host': 1, 'deleted_here': 0}


def test_the_combined_listing_of_the_check_is_read(host, tmp_path):
    f = tmp_path / 'check.txt'
    f.write_text('= a.md\n- b.md\n+ c.md\n* d.md\n= work/x/MEMORY.md.conflict1\n= work/x/MEMORY.md.conflict2\n! e.md\n', encoding='utf-8')
    n = host._check_summary(str(f))
    assert (n['equal'], n['missing_host'], n['missing_here'], n['differ'], n['errors']) == (3, 1, 1, 1, 1)
    assert n['conflicts'] == ['work/x/MEMORY.md.conflict1', 'work/x/MEMORY.md.conflict2']
    assert not n['ok']
    assert host._check_text(n) == 'DIFFERENCES: 1 missing there, 1 missing here, 1 differ, 1 unreadable; 2 conflict copies to look at'

    f.write_text('= a.md\n= b.md.conflict1\n= b.md.conflict2\n', encoding='utf-8')
    n = host._check_summary(str(f))
    assert n['ok'] and host._check_text(n) == 'identical (3); 2 conflict copies to look at'   # old copies on both sides: in step

    f.write_text('= a.md\n= b.md\n', encoding='utf-8')
    n = host._check_summary(str(f))
    assert n['ok'] and host._check_text(n) == 'identical (2)'

    n = host._check_summary(str(tmp_path / 'missing.txt'))
    assert n['errors'] == -1 and not n['ok'] and host._check_text(n) == 'not read'


def test_two_indexes_merge_as_a_line_union(host):
    assert host._merge_index_lines('- x\n- y\n', '- y\n- z\n') == '- x\n- y\n- z\n'
    assert host._merge_index_lines('', '- z\n') == '- z\n'
    assert host._merge_index_lines('- x\n', '') == '- x\n'
    assert host._merge_index_lines('# Memory index\n\n- x\n', '# Memory index\n\n- w\n') == '# Memory index\n\n- x\n- w\n'


def test_index_conflicts_are_merged_and_settled_on_both_sides(host, tmp_path):
    local = tmp_path / 'repo'
    folder = local / 'work' / 'item' / '!AI' / 'memory'
    folder.mkdir(parents=True)
    (folder / 'MEMORY.md.conflict1').write_text('- a\n- b\n', encoding='utf-8')
    (folder / 'MEMORY.md.conflict2').write_text('- b\n- c\n', encoding='utf-8')
    (local / 'notes.md.conflict1').write_text('x', encoding='utf-8')
    entry = {'local': str(local), 'remote': '/home/u/CMETA/repos/repo', 'method': 'bisync'}
    conflicts = ['work/item/!AI/memory/MEMORY.md.conflict1', 'work/item/!AI/memory/MEMORY.md.conflict2', 'notes.md.conflict1']

    merged = host._settle_index_conflicts({}, HOST, 'repo', entry, conflicts, con=False, verbose=False)

    assert merged == ['work/item/!AI/memory/MEMORY.md']
    assert (folder / 'MEMORY.md').read_text(encoding='utf-8') == '- a\n- b\n- c\n'
    assert not (folder / 'MEMORY.md.conflict1').exists() and not (folder / 'MEMORY.md.conflict2').exists()
    assert (local / 'notes.md.conflict1').exists()                         # not an index: left for a person
    copyto = [c for c in host.calls if c[0] == 'rclone']
    assert copyto == [('rclone', 'copyto', str(folder / 'MEMORY.md'), '/home/u/CMETA/repos/repo/work/item/!AI/memory/MEMORY.md')]
    rms = [c[1] for c in host.calls if c[0] == 'cmd']
    assert len(rms) == 2 and all(c.startswith('rm -f ') and 'MEMORY.md.conflict' in c for c in rms)


def robust(host, answers, intact=True, empty=False):
    """The robust sync over a _sync_repo that answers from a list; what it was called with is kept."""
    seen = []

    def fake_sync_repo(ctx, h, name, entry, **kw):
        seen.append(dict(kw))
        r = answers.pop(0)
        return dict(r)

    host._sync_repo = fake_sync_repo
    host._side_intact = lambda ctx, h, entry, side: intact
    host._remote_empty = lambda ctx, h, entry: empty
    entry = {'local': 'x', 'remote': '/r', 'method': 'bisync'}
    r = host._sync_repo_robust({}, HOST, 'repo', entry, resync=False, resync_mode='newer', unlock=False, dry_run=False,
                               con=False, verbose=False, backup=False, retries=2)
    return r, seen


def test_the_robust_sync_drops_a_lock_then_forces_real_deletes(host):
    r, seen = robust(host, [{'return': 1, 'error': 'rclone bisync returned 1', 'output': LOCK},
                            {'return': 1, 'error': 'rclone bisync returned 1', 'output': TOO_MANY},
                            {'return': 0, 'output': 'NOTICE: - Path1    Queue delete - D:\\repo\\gone.md\n'}])
    assert r['return'] == 0
    assert [k['unlock'] for k in seen] == [False, True, True]
    assert [k['force'] for k in seen] == [False, False, True]
    assert seen[2]['backup'] is True                                      # the host keeps what the forced run deletes
    assert r['notes'] == ['a stale lock dropped', '5090 of 6472 files gone from this machine: the deletes forced (the host keeps its copies in its sync-backup artifact)']
    assert r['moved']['deleted_here'] == 1 and r['both_sides'] == []


def test_a_file_changed_on_both_sides_is_named(host):
    text = ('NOTICE: - WARNING  New or changed in both paths       - same.md\n'           # new on both sides and equal: no rename
            'NOTICE: - Path1    Renaming Path1 copy          - D:\\repo\\work/x/MEMORY.md.conflict1\n'
            'INFO  : work/x/MEMORY.md: Moved (server-side) to: work/x/MEMORY.md.conflict1\n'
            'INFO  : work/x/MEMORY.md: Moved (server-side) to: work/x/MEMORY.md.conflict2\n'
            'INFO  : notes.md: Moved (server-side) to: notes.md.conflict1\n')
    r, seen = robust(host, [{'return': 0, 'output': text}])
    assert r['return'] == 0 and r['both_sides'] == ['work/x/MEMORY.md', 'notes.md']


def test_the_robust_sync_never_forces_deletes_of_a_wiped_side(host):
    r, seen = robust(host, [{'return': 1, 'error': 'rclone bisync returned 1', 'output': TOO_MANY}], intact=False)
    assert r['return'] == 1 and len(seen) == 1
    assert 'not a repository any more' in r['error'] and 'nothing forced' in r['error']


def test_the_robust_sync_seeds_a_new_pair_from_this_machine(host):
    r, seen = robust(host, [{'return': 1, 'error': 'rclone bisync returned 1', 'output': NEEDS_RESYNC},
                            {'return': 0, 'output': ''}], empty=True)
    assert r['return'] == 0
    assert seen[1]['resync'] is True and seen[1]['resync_mode'] == 'path1'
    assert r['notes'] == ['a new pair: seeded from this machine (--resync --resync_mode=path1)']


def test_the_robust_sync_asks_a_person_when_both_sides_hold_files(host):
    r, seen = robust(host, [{'return': 1, 'error': 'rclone bisync returned 1', 'output': NEEDS_RESYNC}], empty=False)
    assert r['return'] == 1 and len(seen) == 1
    assert '--resync --resync_mode=path1 --dry_run' in r['error']


def test_the_robust_sync_tries_a_transient_error_again_and_gives_up_on_the_rest(host, monkeypatch):
    import time as time_module
    monkeypatch.setattr(time_module, 'sleep', lambda s: None)
    r, seen = robust(host, [{'return': 1, 'error': 'rclone bisync returned 1', 'output': TRANSIENT},
                            {'return': 0, 'output': ''}])
    assert r['return'] == 0 and len(seen) == 2 and r['notes'] == ['tried again']

    r, seen = robust(host, [{'return': 1, 'error': 'rclone bisync returned 1', 'output': 'NOTICE: Failed to bisync: new words'}])
    assert r['return'] == 1 and len(seen) == 1 and r['notes'] == []


def test_the_banner_says_it_in_large_letters(host):
    good = host._banner(True, 'STATUS: SUCCESS - 12 repositories synced and checked')
    lines = good.split('\n')
    assert lines[0] == '=' * 100 and lines[-1] == '=' * 100 and lines[1] == 'STATUS:'
    assert len(lines) == 2 + 5 + 1 + 1 and 'STATUS: SUCCESS - 12 repositories synced and checked' in lines
    assert all(len(l) <= 100 for l in lines)

    bad = host._banner(False, 'STATUS: FAILED - 2 problem(s) - 3 repositories ok: ' + 'a' * 150 + ' | host / repo: the check: DIFFERENCES: 1 differ')
    assert all(len(l) <= 100 for l in bad.split('\n'))
    assert bad.count('#') > good.count('#') - 200               # both words drawn in block letters
