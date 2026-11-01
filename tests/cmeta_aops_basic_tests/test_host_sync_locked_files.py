"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx host sync and a file another process holds (2026-11-01). A bisync that cannot read a file (a SQLite lock, an open
document) copies everything else, holds the deletions back, and ends with a critical error that drops the pair's
listings: dead until a resync, which would bring deleted files back. The robust sync (the host category, offline):
- rclone's words name the files; the pre-run listings rclone renamed to .lst-err go back as .lst;
- the files are probed a few times (a lock may be short): readable again -> a plain run; still held -> a run without
  them (anchored filter rules), so that the deletions and the rest go through, and their pre-run entries return to
  the new listings in binary (LF), so that they are one ordinary change at the next run, never "new on both sides";
- the result names the skipped files; the check after the sync does not count them as a difference;
- without .lst-err to put back, the pair goes the old way (a person decides about a resync).
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

UNREADABLE = ('ERROR : logs/x.sqlite-maintenance.lock: Failed to calculate src hash: hash: failed to read: read '
              '/repo/logs/x.sqlite-maintenance.lock: The process cannot access the file because another process has locked a portion of the file.\n'
              'NOTICE: logs/x.sqlite-maintenance.lock.12fbb344.partial: Removing partially written file on error\n'
              'INFO  : a.txt: Copied (replaced existing)\n'
              'INFO  : b.txt: Copied (new)\n'
              'ERROR : logs/x.sqlite-maintenance.lock: Failed to copy: read /repo/logs/x.sqlite-maintenance.lock: The process cannot access the file\n'
              'ERROR : notes/open doc.md: Failed to copy: open /repo/notes/open doc.md: permission denied\n'
              'ERROR : Local file system at //?/D:/host: not deleting files as there were IO errors\n'
              'ERROR : Bisync critical error: read /repo/logs/x.sqlite-maintenance.lock: The process cannot access the file\n'
              'ERROR : Bisync aborted. Must run --resync to recover.\n'
              'NOTICE: Failed to bisync with 3 errors: last error was: bisync aborted\n')
LISTING_HEADER = b'# bisync listing v1 from 2026-11-01T17:32:15.180136200+0000\n'
ENTRY = {'a.txt': b'-       20 - - 2026-11-01T17:32:15.015339500+0000 "a.txt"\n',
         'logs/x.sqlite-maintenance.lock': b'-        0 - - 2026-11-01T17:32:15.015339500+0000 "logs/x.sqlite-maintenance.lock"\n',
         'notes/open doc.md': b'-       99 - - 2026-11-01T17:32:15.016421100+0000 "notes/open doc.md"\n'}


@pytest.fixture()
def host(tmp_path, monkeypatch):
    """The host category as the engine makes it, on a home of the test; its remote calls recorded, never made."""
    from cmeta import CMeta
    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))
    c = CMeta(home=str(tmp_path / 'home'))
    spec = importlib.util.spec_from_file_location('category_host_locked_under_test', str(REPO_ROOT / 'category' / 'host' / 'api' / 'v1.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    h = module.Category.__new__(module.Category)
    h.cm = c
    h.cmeta = yaml.safe_load((REPO_ROOT / 'category' / 'host' / '_cmeta.yaml').read_text(encoding='utf-8-sig'))
    h.logger = logging.getLogger('host-locked-under-test')
    h._key_cache, h._host_cache, h._adb_batch, h._adb_locks = {}, {}, None, {}
    h._adb_lock = threading.Lock()
    h.calls = []
    return h


HOST = {'alias': 'far-away', 'uid': 'a8b2c3d4e5f60718', 'type': 'ssh', 'desc': {}, 'state': {}}


def test_the_files_rclone_could_not_read_are_named(host):
    assert host._unreadable_files(UNREADABLE) == ['logs/x.sqlite-maintenance.lock', 'notes/open doc.md']
    assert host._bisync_failure(UNREADABLE) == ('unreadable', ['logs/x.sqlite-maintenance.lock', 'notes/open doc.md'])
    # the words of the next run of a dead pair stay what they were
    assert host._bisync_failure('ERROR : Bisync critical error: cannot find prior Path1 or Path2 listings\nMust run --resync')[0] == 'needs-resync'


def test_the_filter_rule_of_a_file_is_anchored_and_escaped(host):
    assert host._exclude_rule('logs/x.sqlite-maintenance.lock') == '/logs/x.sqlite-maintenance.lock'
    assert host._exclude_rule('notes/open doc.md') == '/notes/open doc.md'
    assert host._exclude_rule('odd [1]*?.txt') == '/odd ' + chr(92) + '[1' + chr(92) + ']' + chr(92) + '*' + chr(92) + '?.txt'


def test_the_probe_waits_for_a_short_lock_and_gives_up_on_a_long_one(host, tmp_path, monkeypatch):
    import time as time_module
    naps = []
    monkeypatch.setattr(time_module, 'sleep', lambda s: naps.append(s))
    (tmp_path / 'ok.txt').write_text('fine')
    # a file that is not here (the host's side) cannot be probed: still unreadable; a readable one is not
    assert host._still_unreadable(str(tmp_path), ['ok.txt', 'gone/elsewhere.txt'], tries=3, pause=1) == ['gone/elsewhere.txt']
    assert naps == [1, 1]
    assert host._still_unreadable(str(tmp_path), ['ok.txt'], tries=3, pause=1) == []


def test_the_listings_go_back_and_the_excluded_entries_return_in_lf(host, tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    for side in ('path1', 'path2'):
        (work / f'pair.{side}.lst-err').write_bytes(LISTING_HEADER + b''.join(ENTRY.values()))
        (work / f'pair.{side}.lst-new').write_bytes(LISTING_HEADER)
    # a leftover of a pair synced since (its .lst is there), and one of another repository: neither is touched
    (work / 'synced-since.path1.lst-err').write_bytes(LISTING_HEADER)
    (work / 'synced-since.path1.lst').write_bytes(LISTING_HEADER)
    (work / 'D__repos_other..host_repos_other.path1.lst-err').write_bytes(LISTING_HEADER)
    os.utime(work / 'pair.path1.lst-err', (1_000_000_000, 1_000_000_000))      # the rename keeps the old time: no filter on it

    listings = host._listings_back(str(work), 'pair')
    assert sorted(os.path.basename(p) for p in listings) == ['pair.path1.lst', 'pair.path2.lst']
    assert not list(work.glob('pair.*.lst-err'))
    assert (work / 'synced-since.path1.lst-err').exists() and (work / 'D__repos_other..host_repos_other.path1.lst-err').exists()
    assert host._listings_back(str(work), 'pair') == {}                                # nothing left to put back

    # the run without the two files wrote new listings with a.txt only; their entries come back, LF-terminated
    for side in ('path1', 'path2'):
        (work / f'pair.{side}.lst').write_bytes(LISTING_HEADER + ENTRY['a.txt'])
    n = host._entries_back(listings, ['logs/x.sqlite-maintenance.lock', 'notes/open doc.md'])
    assert n == 4
    data = (work / 'pair.path2.lst').read_bytes()
    assert data == LISTING_HEADER + ENTRY['a.txt'] + ENTRY['logs/x.sqlite-maintenance.lock'] + ENTRY['notes/open doc.md']
    assert b'\r' not in data
    assert host._entries_back(listings, ['logs/x.sqlite-maintenance.lock']) == 0       # already there


def unreadable(local):
    return UNREADABLE.replace('/repo/', str(local).replace(chr(92), '/') + '/')


def robust(host, answers, workdir, local, still):
    """The robust sync over a _sync_repo that answers from a list; what it was called with is kept."""
    seen = []

    def fake_sync_repo(ctx, h, name, entry, **kw):
        seen.append(dict(kw))
        return dict(answers.pop(0))

    host._sync_repo = fake_sync_repo
    host._bisync_workdir = lambda h, entry: str(workdir)
    host._still_unreadable = lambda root, files, tries=3, pause=5: [f for f in files if f in still]
    host._side_intact = lambda ctx, h, entry, side: True
    host._remote_empty = lambda ctx, h, entry: False
    entry = {'local': str(local), 'remote': '/r', 'method': 'bisync', 'blacklist': []}
    r = host._sync_repo_robust({}, HOST, 'repo', entry, resync=False, resync_mode='newer', unlock=False, dry_run=False,
                               con=False, verbose=False, backup=False, retries=2)
    return r, seen


def dead_pair(workdir):
    """The work dir as a failed run leaves it: .lst-err (the pre-run listings, with their old time) and .lst-new, no
    .lst. The listing names carry the repository's name ("repo"), as rclone writes the two paths into them."""
    workdir.mkdir(exist_ok=True)
    for side in ('path1', 'path2'):
        (workdir / f'D__x_repo..host_r_repo.{side}.lst-err').write_bytes(LISTING_HEADER + b''.join(ENTRY.values()))
        os.utime(workdir / f'D__x_repo..host_r_repo.{side}.lst-err', (1_000_000_000, 1_000_000_000))
        (workdir / f'D__x_repo..host_r_repo.{side}.lst-new').write_bytes(LISTING_HEADER)


def test_a_file_still_held_is_skipped_and_the_result_names_it(host, tmp_path):
    work = tmp_path / 'work'
    dead_pair(work)
    seen = []

    def sync_repo(ctx, h, name, entry, **kw):
        seen.append(dict(kw))
        if len(seen) == 1:
            return {'return': 1, 'error': 'rclone bisync returned 7', 'output': unreadable(tmp_path)}
        for side in ('path1', 'path2'):                     # the run without the files: new listings without them
            (work / f'D__x_repo..host_r_repo.{side}.lst').write_bytes(LISTING_HEADER + ENTRY['a.txt'])
        return {'return': 0, 'output': 'NOTICE: - Path2    Queue delete - D:\\repo\\gone.md\n'}

    host._sync_repo = sync_repo
    host._bisync_workdir = lambda h, entry: str(work)
    host._still_unreadable = lambda root, files, tries=3, pause=5: list(files)
    entry = {'local': str(tmp_path), 'remote': '/r', 'method': 'bisync', 'blacklist': []}
    r = host._sync_repo_robust({}, HOST, 'repo', entry, resync=False, resync_mode='newer', unlock=False, dry_run=False,
                               con=False, verbose=False, backup=False, retries=2)
    assert r['return'] == 0
    assert seen[0]['exclude'] == [] and seen[1]['exclude'] == ['/logs/x.sqlite-maintenance.lock', '/notes/open doc.md']
    assert r['skipped'] == ['logs/x.sqlite-maintenance.lock', 'notes/open doc.md']
    assert r['notes'] == ['2 file(s) copied before the run stopped',
                          '2 file(s) another process holds skipped this run, synced next time: logs/x.sqlite-maintenance.lock, notes/open doc.md']
    assert r['moved']['deleted_host'] == 1
    # the listings: back in place, the skipped files' pre-run entries in them, LF
    assert not list(work.glob('*.lst-err'))
    data = (work / 'D__x_repo..host_r_repo.path1.lst').read_bytes()
    assert ENTRY['logs/x.sqlite-maintenance.lock'] in data and ENTRY['notes/open doc.md'] in data and b'\r' not in data


def test_a_short_lock_is_waited_out_and_the_run_goes_again_plainly(host, tmp_path):
    work = tmp_path / 'work'
    dead_pair(work)
    answers = [{'return': 1, 'error': 'rclone bisync returned 7', 'output': unreadable(tmp_path)}, {'return': 0, 'output': ''}]
    r, seen = robust(host, answers, work, tmp_path, still=[])
    assert r['return'] == 0 and 'skipped' not in r
    assert [k['exclude'] for k in seen] == [[], []]
    assert r['notes'] == ['2 file(s) copied before the run stopped', '2 file(s) another process held were readable again: tried again']
    assert sorted(p.name for p in work.glob('*.lst')) == ['D__x_repo..host_r_repo.path1.lst', 'D__x_repo..host_r_repo.path2.lst']   # the listings back


def test_a_file_held_on_the_host_cannot_be_probed_and_is_skipped(host, tmp_path):
    work = tmp_path / 'work'
    dead_pair(work)
    text = UNREADABLE                                          # the error paths are the host's (/repo/...), not ours
    assert host._unreadable_here(text, str(tmp_path)) == set()
    assert host._unreadable_here(unreadable(tmp_path), str(tmp_path)) == {'logs/x.sqlite-maintenance.lock', 'notes/open doc.md'}
    answers = [{'return': 1, 'error': 'rclone bisync returned 7', 'output': text}, {'return': 0, 'output': ''}]
    r, seen = robust(host, answers, work, tmp_path, still=[])    # the probe would say readable: not asked for the host's files
    assert r['return'] == 0 and r['skipped'] == ['logs/x.sqlite-maintenance.lock', 'notes/open doc.md']
    assert seen[1]['exclude'] == ['/logs/x.sqlite-maintenance.lock', '/notes/open doc.md']


def test_without_listings_to_put_back_the_pair_goes_to_a_person(host, tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    answers = [{'return': 1, 'error': 'rclone bisync returned 7', 'output': UNREADABLE}]
    r, seen = robust(host, answers, work, tmp_path, still=['logs/x.sqlite-maintenance.lock'])
    assert r['return'] == 1 and len(seen) == 1 and 'needs a new baseline' in r['error']


def test_the_check_does_not_count_a_skipped_file_as_a_difference(host, tmp_path):
    combined = tmp_path / 'check.txt'
    combined.write_text('= a.txt\n* logs/x.sqlite-maintenance.lock\n- notes/open doc.md\n= b.txt\n', encoding='utf-8')
    n = host._check_summary(str(combined))
    assert not n['ok'] and n['differ'] == 1 and n['missing_host'] == 1
    n = host._check_summary(str(combined), ignore=['logs/x.sqlite-maintenance.lock', 'notes/open doc.md'])
    assert n['ok'] and n['equal'] == 2 and n['skipped'] == 2 and n['differ'] == 0 and n['missing_host'] == 0


def test_a_sync_entry_may_name_the_local_folder_of_a_repository_plugged_elsewhere(host, tmp_path):
    """Default: <this machine's repositories folder>/<name>; a repository plugged from elsewhere (a test session's
    sandbox, another drive) names its folder with local:, ~ and variables expanded."""
    h = {'alias': 'x', 'desc': {'sync': {'repos_path': '/home/u/CMETA/repos', 'repos': [
        'plain', {'elsewhere': {'local': str(tmp_path / 'repo'), 'method': 'bisync'}}, {'home': {'local': '~/r'}}]}}}
    e = host._sync_entries(h)
    assert e['plain']['local'] == str(host.cm.repos_path / 'plain') and e['plain']['remote'] == '/home/u/CMETA/repos/plain'
    assert e['elsewhere']['local'] == str(tmp_path / 'repo') and e['elsewhere']['remote'] == '/home/u/CMETA/repos/elsewhere'
    assert e['home']['local'] == os.path.expanduser('~/r')


def test_listings_left_in_place_are_the_baseline_too(host, tmp_path):
    """rclone in --resilient mode, or a host-side file it could not open, fails without dropping the listings: they
    are the pre-run baseline, the recovery goes on from them (seen live on 2026-11-01 with a chmod 000 on the host)."""
    work = tmp_path / 'work'
    work.mkdir()
    for side in ('path1', 'path2'):
        (work / f'pair.{side}.lst').write_bytes(LISTING_HEADER + b''.join(ENTRY.values()))
    text = '\n'.join(['ERROR : notes/open doc.md: Failed to copy: failed to open source object: Open failed: permission denied',
                      'ERROR : Bisync critical error: failed to open source object: Open failed: permission denied',
                      'ERROR : Bisync aborted. Must run --resync to recover.', ''])
    assert host._unreadable_files(text) == ['notes/open doc.md'] and host._unreadable_here(text, str(tmp_path)) == set()
    seen = []

    def sync_repo(ctx, h, name, entry, **kw):
        seen.append(dict(kw))
        if len(seen) == 1:
            return {'return': 1, 'error': 'rclone bisync returned 7', 'output': text}
        for side in ('path1', 'path2'):
            (work / f'pair.{side}.lst').write_bytes(LISTING_HEADER + ENTRY['a.txt'] + ENTRY['logs/x.sqlite-maintenance.lock'])
        return {'return': 0, 'output': ''}

    host._sync_repo = sync_repo
    host._bisync_workdir = lambda h, entry: str(work)
    entry = {'local': str(tmp_path), 'remote': '/r', 'method': 'bisync', 'blacklist': []}
    r = host._sync_repo_robust({}, HOST, 'repo', entry, resync=False, resync_mode='newer', unlock=False, dry_run=False,
                               con=False, verbose=False, backup=False, retries=2)
    assert r['return'] == 0 and r['skipped'] == ['notes/open doc.md'] and seen[1]['exclude'] == ['/notes/open doc.md']
    assert ENTRY['notes/open doc.md'] in (work / 'pair.path2.lst').read_bytes()
