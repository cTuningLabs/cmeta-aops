"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx host sync (2026-11-11): a file whose name the host cannot hold, the progress of a run, the files copied at once.
- A name longer than a POSIX filesystem holds (255 bytes of UTF-8; NTFS: 255 UTF-16 units) is refused by the host
  ("Bad message" through sftp) and read as a failed copy: the robust sync tells it from a file another process holds,
  leaves it out of the run for good (remembered beside the pair's listings, named in the result), and a file renamed
  shorter syncs again.
- --progress: rclone's statistics blocks (every 10 s, in its log file) become one line each while it runs - the files
  and bytes moved of those to move, %, speed, time left; while the sides are still listed, how far the listing is.
- --transfers=N: rclone copies N files at once (and as many checkers, at least 4).
Nothing of the user's cMeta is touched: the engine runs on a home under tmp_path, the host is never reached.
"""
import importlib.util
import logging
import os
import pathlib
import threading
import time

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# a Russian title of 160 letters: 319 bytes of UTF-8 (too long for Linux), 160 UTF-16 units (fine on NTFS)
LONG = 'Учёные адаптируются к сегодняшнему торжеству наукометрии, но при этом перед научным сообществом встала проблема ' \
       'подделки научных результатов и это очень плохо.htm'
LONG_PATH = 'notes/2013 war/' + LONG
REFUSED = (f'INFO  : a.txt: Copied (new)\n'
           f'ERROR : {LONG_PATH}: Failed to copy: Update Create failed: sftp: "Bad message" (SSH_FX_BAD_MESSAGE)\n'
           f'ERROR : Bisync critical error: Update Create failed: sftp: "Bad message" (SSH_FX_BAD_MESSAGE)\n'
           f'ERROR : Bisync aborted. Must run --resync to recover.\n'
           f'NOTICE: Failed to bisync with 2 errors: last error was: bisync aborted\n')

# two statistics blocks as rclone 1.75 writes them into its log (--stats 10s --stats-log-level NOTICE)
COPYING = ['Transferred:   \t    1.041 MiB / 8.583 MiB, 12%, 1.072 MiB/s, ETA 6s',
           'Checks:                 0 / 0, -, Listed 30',
           'Transferred:            2 / 30, 7%',
           'Elapsed time:         0.9s']
LISTING = ['Transferred:   \t          0 B / 0 B, -, 0 B/s, ETA -',
           'Checks:            120034 / 304749, 39%, Listed 789852',
           'Elapsed time:      1m20.0s']


@pytest.fixture()
def host(tmp_path, monkeypatch):
    """The host category as the engine makes it, on a home of the test; its remote calls replaced."""
    from cmeta import CMeta
    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))
    c = CMeta(home=str(tmp_path / 'home'))
    spec = importlib.util.spec_from_file_location('category_host_long_names_under_test', str(REPO_ROOT / 'category' / 'host' / 'api' / 'v1.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    h = module.Category.__new__(module.Category)
    h.cm = c
    h.cmeta = yaml.safe_load((REPO_ROOT / 'category' / 'host' / '_cmeta.yaml').read_text(encoding='utf-8-sig'))
    h.logger = logging.getLogger('host-long-names-under-test')
    h._key_cache, h._host_cache, h._adb_batch, h._adb_locks = {}, {}, None, {}
    h._adb_lock = threading.Lock()
    h.module = module
    return h


HOST = {'alias': 'far-away', 'uid': 'a8b2c3d4e5f60718', 'type': 'ssh', 'desc': {}, 'state': {}}


def test_a_name_is_too_long_by_the_bytes_of_posix_or_the_units_of_ntfs(host):
    assert len(LONG.encode('utf-8')) > 255 and len(LONG) <= 255
    assert host._name_too_long(LONG_PATH)
    assert not host._name_too_long(LONG_PATH, windows=True)
    assert not host._name_too_long('a/' + 'x' * 255)
    assert host._name_too_long('a/' + 'x' * 256 + '/b.txt')
    assert host._name_too_long('y' * 256, windows=True)


def robust(host, answers, work, local, entry_extra=None):
    """The robust sync over prepared answers of _sync_repo; -> (result, the keywords of each run)."""
    seen = []

    def sync_repo(ctx, h, name, entry, **kw):
        seen.append(dict(kw))
        return dict(answers[len(seen) - 1])

    host._sync_repo = sync_repo
    host._bisync_workdir = lambda h, entry: str(work)
    entry = {'local': str(local), 'remote': '/r', 'method': 'bisync', 'blacklist': [], **(entry_extra or {})}
    r = host._sync_repo_robust({}, HOST, 'repo', entry, resync=True, resync_mode='newer', unlock=False, dry_run=False,
                               con=False, verbose=False, backup=False, retries=2, transfers=8, progress=True)
    return r, seen


def test_a_name_the_host_refuses_is_left_out_for_good_and_named(host, tmp_path):
    work, local = tmp_path / 'work', tmp_path / 'repo'
    (local / 'notes' / '2013 war').mkdir(parents=True)
    try:
        (local / 'notes' / '2013 war' / LONG).write_text('x', encoding='utf-8')
    except OSError:
        # the case is a machine that holds the name (Windows: 255 characters) and a host that refuses it (Linux, macOS:
        # 255 bytes): a file system that refuses it here cannot play the first part
        pytest.skip('this file system refuses the long name too (the case needs a Windows side)')
    r, seen = robust(host, [{'return': 1, 'error': 'rclone resync returned 7', 'output': REFUSED}, {'return': 0, 'output': ''}],
                     work, local)
    assert r['return'] == 0 and len(seen) == 2                       # one more run, not six
    assert seen[0]['exclude'] == [] and seen[1]['exclude'] == ['/' + LONG_PATH]
    assert seen[1]['transfers'] == 8 and seen[1]['progress'] is True
    assert r['long_names'] == [LONG_PATH] and 'skipped' not in r
    assert r['notes'] == [f'1 file(s) left out for good: the name is longer than far-away allows (255 bytes) - {LONG_PATH}']
    remembered = (work / 'cmeta-long-names-repo.txt').read_text(encoding='utf-8')
    assert remembered == LONG_PATH + '\n'

    # the next run leaves it out from the start
    r, seen = robust(host, [{'return': 0, 'output': ''}], work, local)
    assert len(seen) == 1 and seen[0]['exclude'] == ['/' + LONG_PATH] and r['long_names'] == [LONG_PATH] and r['notes'] == []

    # renamed shorter (the long name gone): it syncs again
    os.rename(local / 'notes' / '2013 war' / LONG, local / 'notes' / '2013 war' / 'short.htm')
    r, seen = robust(host, [{'return': 0, 'output': ''}], work, local)
    assert seen[0]['exclude'] == [] and r['long_names'] == []


def test_a_file_another_process_holds_is_still_told_apart(host, tmp_path):
    held = ('ERROR : notes/open doc.md: Failed to copy: open /repo/notes/open doc.md: permission denied\n'
            'ERROR : Bisync aborted. Must run --resync to recover.\n')
    assert host._bisync_failure(held) == ('unreadable', ['notes/open doc.md'])
    assert host._bisync_failure(REFUSED) == ('unreadable', [LONG_PATH])      # the robust sync tells it apart by the name


def test_a_statistics_block_becomes_one_line(host):
    text = host.module._stats_text(COPYING)
    assert text == '0.9s: 2 / 30 files, 1.1 MB of 9.0 MB (12%), 1.1 MB/s, ETA 6s | 30 listed'
    text = host.module._stats_text(LISTING)
    assert text == '1m20.0s: comparing the two sides | 789,852 listed | 120,034 of 304,749 compared'
    assert 'errors: 2' in host.module._stats_text(COPYING[:-1] + ['Errors:                 2 (retrying may help)', 'Elapsed time: 3s'])


def test_the_follower_shows_the_blocks_and_the_errors_while_rclone_writes(host, tmp_path, capsys):
    log = tmp_path / 'rclone.log'
    log.write_text('', encoding='utf-8')
    lines = (['2026/11/11 14:05:19 INFO  : a.txt: Copied (new)',
              '2026/11/11 14:05:20 NOTICE: '] + COPYING +
             ['Transferring:', ' *                                       f02.bin: 87% / 292.969 KiB, 0 B/s, -', '',
              '2026/11/11 14:05:21 ERROR : b.txt: Failed to copy: permission denied',
              '2026/11/11 14:05:30 NOTICE: '] + LISTING + [''])
    with host.module._FollowRclone(str(log), 'notes'):
        with open(log, 'a', encoding='utf-8', newline='\n') as f:
            for line in lines:                       # written in pieces, as rclone does
                f.write(line + '\n')
                f.flush()
                time.sleep(0.01)
        time.sleep(0.5)
    out = capsys.readouterr().out.splitlines()
    assert out == ['    notes 0.9s: 2 / 30 files, 1.1 MB of 9.0 MB (12%), 1.1 MB/s, ETA 6s | 30 listed',
                   '    2026/11/11 14:05:21 ERROR : b.txt: Failed to copy: permission denied',
                   '    notes 1m20.0s: comparing the two sides | 789,852 listed | 120,034 of 304,749 compared']

    # relay_all (a run whose output would be on the terminal anyway): the other lines too, the file list of a block not
    log.write_text('', encoding='utf-8')
    with host.module._FollowRclone(str(log), 'notes', relay_all=True):
        with open(log, 'a', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(lines) + '\n')
        time.sleep(0.5)
    out = capsys.readouterr().out.splitlines()
    assert out[0] == '    2026/11/11 14:05:19 INFO  : a.txt: Copied (new)' and len(out) == 4
    assert not any('f02.bin' in l or 'Transferring' in l for l in out)


def test_a_run_with_progress_logs_into_a_file_read_back_as_its_output(host, tmp_path, capsys):
    calls = []

    def access(ii):
        calls.append(ii)
        log = ii['unparsed'][ii['unparsed'].index('--log-file') + 1]
        with open(log, 'a', encoding='utf-8', newline='\n') as f:
            f.write('2026/11/11 14:05:19 INFO  : a.txt: Copied (new)\n2026/11/11 14:05:20 NOTICE: \n' + '\n'.join(COPYING) + '\n')
        time.sleep(0.5)
        return {'return': 0, 'returncode': 0, 'stdout': '', 'stderr': ''}

    host.cm.access = access
    host._ssh_parts = lambda h: {'return': 0, 'target': 'me@far', 'options': ''}
    r = host._rclone({'control': {}}, HOST, 'bisync', str(tmp_path), '/r', extra=['--transfers=16'], capture=True,
                     progress=True, label='notes')
    assert r['return'] == 0 and 'a.txt: Copied (new)' in r['output']          # the per-file lines still counted
    args = calls[0]['unparsed']
    assert args[:1] == ['--transfers=16'] and '--stats' in args and args[args.index('--stats') + 1] == '10s'
    assert not os.path.exists(args[args.index('--log-file') + 1])               # the log file is gone after the run
    assert capsys.readouterr().out.strip() == 'notes 0.9s: 2 / 30 files, 1.1 MB of 9.0 MB (12%), 1.1 MB/s, ETA 6s | 30 listed'

    # without --progress nothing changes: no log file, no statistics
    calls.clear()
    host.cm.access = lambda ii: calls.append(ii) or {'return': 0, 'returncode': 0, 'stdout': 'INFO  : b.txt: Copied (new)\n', 'stderr': ''}
    r = host._rclone({'control': {}}, HOST, 'bisync', str(tmp_path), '/r', extra=[], capture=True)
    assert '--log-file' not in calls[0]['unparsed'] and r['output'] == 'INFO  : b.txt: Copied (new)\n'


def test_the_files_at_once_reach_rclone(host, tmp_path):
    seen = []
    host._rclone = lambda ctx, h, command, local, remote, **kw: seen.append(kw) or {'return': 0, 'output': ''}
    host._index_after_sync = lambda *a, **k: None
    host._repo_desc = lambda local: {}
    entry = {'local': str(tmp_path), 'remote': '/r', 'method': 'copy', 'blacklist': []}
    host._sync_repo({}, HOST, 'repo', entry, resync=False, resync_mode='newer', unlock=False, dry_run=True, con=False,
                    verbose=False, transfers=16, progress=True)
    host._sync_repo({}, HOST, 'repo', entry, resync=False, resync_mode='newer', unlock=False, dry_run=True, con=False,
                    verbose=False)
    host._sync_repo({}, HOST, 'repo', entry, resync=False, resync_mode='newer', unlock=False, dry_run=True, con=False,
                    verbose=False, transfers=2)
    assert seen[0]['extra'][:2] == ['--transfers=16', '--checkers=16'] and seen[0]['progress'] is True and seen[0]['label'] == 'repo'
    assert seen[1]['extra'][:2] == ['--transfers=4', '--checkers=4'] and seen[1]['progress'] is False
    assert seen[2]['extra'][:2] == ['--transfers=2', '--checkers=4']


def test_a_path_with_commas_reaches_rclone_whole(host, tmp_path):
    """The lists go to rclone-to-ssh as files, one entry per line: its inline form splits at commas, and "War with Nature,
    Russia, etc/..." became three filters, one of them "- Russia" (2026-11-11). The task reads the files as they are."""
    got = []

    def access(ii):
        got.append({k: (open(ii[k], encoding='utf-8').read() if k.endswith('_from') else ii[k])
                    for k in ('whitelist', 'blacklist', 'whitelist_from', 'blacklist_from') if k in ii})
        got[-1]['files'] = [ii[k] for k in ('whitelist_from', 'blacklist_from') if k in ii]
        return {'return': 0, 'returncode': 0, 'stdout': '', 'stderr': ''}

    host.cm.access = access
    host._ssh_parts = lambda h: {'return': 0, 'target': 'me@far', 'options': ''}
    comma = '/notes/201312xx.War with Nature, Russia, etc/' + LONG
    r = host._rclone({'control': {}}, HOST, 'bisync', str(tmp_path), '/r', whitelist=['/notes/', '/a,b.txt'],
                     blacklist=['tmp*/', comma])
    assert r['return'] == 0
    g = got[0]
    assert g['whitelist'] == [] and g['blacklist'] == []
    assert g['whitelist_from'].splitlines() == ['/notes/', '/a,b.txt'] and g['blacklist_from'].splitlines() == ['tmp*/', comma]
    assert not any(os.path.exists(f) for f in g['files'])                     # gone after the run
    # (the task reads such a file line by line, never split at commas: _read_filter_file of rclone-to-ssh)
