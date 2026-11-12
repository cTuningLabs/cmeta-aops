"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx host archive (2026-11-11): a whole host as one dated tar.zst on this machine's backup drives. Offline: the stream
comes from a fake host process (a login banner, the start marker, a real zstd-compressed tar, tar's checkpoints and
exit codes on stderr), never from ssh.
- the block: its defaults, a bare ~ of YAML (null) read as the home, the command line's words over it;
- the bash that turns the paths into arrays relative to / (~ is $HOME);
- the stream: the banner before the marker dropped, the bytes written and hashed, tar's exit 1 accepted (files
  changed while read), 2 refused; the archive read back to its end (entries counted), a truncated one refused;
- the copy read back by its sha256; the prune keeps the newest archives of that host only;
- sizes, durations and the "every" words for a person;
- (2026-11-12) GNU tar and zstd set up by cMeta on the host (cx task run setup gnu-tar / zstd there), their
  paths in the script; a host whose cMeta lacks a tool: its PATH with a warning; neither: refused;
- (2026-11-12) the Python archiver of a Windows machine: a full archive, an increment of what changed with
  what was deleted listed first, and the chain restored in order gives the tree back;
- (2026-11-12) cx host restore --archive: the parts of a chain (the newest, one named, --until), in place only
  with --yes, the script sent to the host (tools of cMeta, --listed-incremental for a chain, the folder, the
  names asked for); the untar task's chains (their parts in order, who made them, the Python archiver's
  deletions applied).
Nothing of the user's cMeta is touched: the engine runs on a home under tmp_path.
"""
import datetime
import hashlib
import json
import importlib.util
import io
import logging
import os
import pathlib
import sys
import tarfile
import threading

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HAS_ZSTD = sys.version_info >= (3, 14)


@pytest.fixture()
def host(tmp_path, monkeypatch):
    from cmeta import CMeta
    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))
    c = CMeta(home=str(tmp_path / 'home'))
    spec = importlib.util.spec_from_file_location('category_host_archive_under_test', str(REPO_ROOT / 'category' / 'host' / 'api' / 'v1.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    h = module.Category.__new__(module.Category)
    h.cm = c
    h.cmeta = yaml.safe_load((REPO_ROOT / 'category' / 'host' / '_cmeta.yaml').read_text(encoding='utf-8-sig'))
    h.logger = logging.getLogger('host-archive-under-test')
    h._key_cache, h._host_cache, h._adb_batch, h._adb_locks = {}, {}, None, {}
    h._adb_lock = threading.Lock()
    h.module = module
    return h


HOST = {'alias': 'vm-a', 'uid': 'a8b2c3d4e5f60718', 'type': 'ssh', 'desc': {}, 'state': {}}
TOOLS = {'TAR': '/opt/cmeta/gtar', 'ZSTD': '/opt/cmeta/zstd'}     # where cMeta set the tools up on the host


def test_words_for_a_person(host):
    m = host.module
    # 1000-based (2026-11-12, the user: "GB with 1000-based numbers everywhere"); rclone's binary figures converted
    assert m._size_text(812) == '812 B' and m._size_text(3 * 1024 ** 3) == '3.2 GB' and m._size_text(4e12) == '4.0 TB'
    assert m._si('Transferred: 1.0 MiB / 8.5 MiB, 12%, 1.0 MiB/s') == 'Transferred: 1.0 MB / 8.9 MB, 12%, 1.0 MB/s'
    assert m._dur_text(52) == '52s' and m._dur_text(190) == '3m10s' and m._dur_text(3900) == '1h05m00s'
    # the user's form (2026-11-12): hours, minutes and seconds; one decimal under 10 s
    assert m._dur_text(632.3) == '10m32s' and m._dur_text(9260) == '2h34m20s' and m._dur_text(7.44) == '7.4s'
    assert m._every_seconds('7d') == 7 * 86400 and m._every_seconds('12h') == 12 * 3600 and m._every_seconds('?') == 7 * 86400


def test_the_block_its_defaults_and_the_command_line(host):
    b = host._archive_block({'desc': {}})
    assert b['paths'] == ['~', '/etc', '/var/www', '/root', '/var/spool/cron'] and b['exclude'] == ['~/.cache']
    assert b['to'] == [] and b['keep'] == 1 and b['incremental'] is False and b['every'] == '7d'
    # "paths: [~, /etc]" in YAML gives None for the ~: read as the home it was meant to be
    desc = yaml.safe_load('archive:\n  paths: [~, /etc]\n  to: [BACKUP1, BACKUP2]\n  keep: 2\n')
    b = host._archive_block({'desc': desc})
    assert b['paths'] == ['~', '/etc'] and b['to'] == ['BACKUP1', 'BACKUP2'] and b['keep'] == 2
    b = host._archive_block({'desc': desc}, to='BACKUP3', paths='/srv/data,/etc', exclude='', keep='0')
    assert b['to'] == ['BACKUP3'] and b['paths'] == ['/srv/data', '/etc'] and b['exclude'] == ['~/.cache'] and b['keep'] == 1


def test_the_paths_become_arrays_relative_to_the_root(host):
    s = host._archive_paths_script({'paths': ['~', '/etc', '/var/www', "/srv/it's here"], 'exclude': ['~/.cache']})
    assert 'P=("${HOME#/}" etc var/www ' in s and "srv/it" in s
    assert 'X=("${HOME#/}"/.cache)' in s
    assert 'MISSING+=("/$p")' in s


class FakeProcess:
    """What ssh gives: stdout (a banner, the marker, the archive), stderr (tar's checkpoints and the exit codes)."""

    def __init__(self, stdout, stderr, rc=0):
        self.stdout = io.BufferedReader(io.BytesIO(stdout))
        self.stderr = io.BufferedReader(io.BytesIO(stderr))
        self.returncode = rc

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


def tar_zst(tmp_path, files):
    """A real tar.zst of a few files -> its bytes."""
    src = tmp_path / 'src'
    src.mkdir(exist_ok=True)
    for name, text in files.items():
        (src / name).write_bytes(text.encode('utf-8'))          # bytes: write_text would turn \n into \r\n on Windows
    out = tmp_path / 'made.tar.zst'
    with tarfile.open(out, 'w:zst') as tf:
        for name in files:
            tf.add(src / name, arcname='home/user/' + name)
    return out.read_bytes()


@pytest.mark.skipif(not HAS_ZSTD, reason='tarfile reads zstd from Python 3.14')
def test_the_stream_drops_a_banner_and_writes_the_archive(host, tmp_path):
    data = tar_zst(tmp_path, {'a.txt': 'alpha\n' * 1000, 'b.txt': 'beta\n'})
    out = b'Welcome to the host! (a login script)\n' + host.module.ARCHIVE_MARK + data
    err = b'tar: CMETA-CHECKPOINT 1000\ntar: home/user/x: file changed as we read it\nCMETA-TAR-EXIT 1 0\n'
    host._ssh_popen = lambda h, script: {'return': 0, 'process': FakeProcess(out, err)}
    part = tmp_path / 'vm-a-20261111-1939.tar.zst.part'
    r = host._archive_stream(HOST, host._archive_block({'desc': {}}), str(part), 10 << 20, False, TOOLS)
    assert r['return'] == 0, r
    assert part.read_bytes() == data and r['written'] == len(data) and r['sha256'] == hashlib.sha256(data).hexdigest()
    assert r['read'] == 1000 * host.module.ARCHIVE_RECORD and r['tar_exit'] == 1 and r['warnings'] == 1
    c = host._archive_check(str(part), False, 'vm-a')
    assert c['ok'] and c['entries'] == 2 and c['bytes'] == len('alpha\n' * 1000) + len('beta\n') and c['checked']

    # a truncated archive does not read back
    (tmp_path / 'cut.tar.zst').write_bytes(data[:len(data) // 2])
    assert not host._archive_check(str(tmp_path / 'cut.tar.zst'), False, 'vm-a')['ok']


def test_a_fatal_tar_or_no_archive_is_refused(host, tmp_path):
    data = b'\x28\xb5\x2f\xfd' + b'x' * 100
    for err in (b'tar: Cowardly refusing to create an empty archive\nCMETA-TAR-EXIT 2 0\n', b'CMETA-TAR-EXIT 0 1\n'):
        host._ssh_popen = lambda h, script, err=err: {'return': 0, 'process': FakeProcess(host.module.ARCHIVE_MARK + data, err)}
        r = host._archive_stream(HOST, host._archive_block({'desc': {}}), str(tmp_path / 'x.part'), 1000, False, TOOLS)
        assert r['return'] > 0 and 'tar ended with' in r['error'], r
    host._ssh_popen = lambda h, script: {'return': 0, 'process': FakeProcess(b'Permission denied (publickey).\n', b'', rc=255)}
    r = host._archive_stream(HOST, host._archive_block({'desc': {}}), str(tmp_path / 'y.part'), 1000, False, TOOLS)
    assert r['return'] > 0 and 'no archive came' in r['error'], r


def test_the_copy_reads_back_by_its_sha256(host, tmp_path):
    src = tmp_path / 'one' / 'vm-a-20261111-1939.tar.zst'
    src.parent.mkdir()
    src.write_bytes(b'archive bytes' * 1000)
    (tmp_path / 'one' / (src.name + '.json')).write_text('{"sha256": "x"}', encoding='utf-8')
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    r = host._archive_copy(str(src), str(tmp_path / 'two'), sha, False)
    assert r['return'] == 0 and pathlib.Path(r['path']).read_bytes() == src.read_bytes()
    assert (tmp_path / 'two' / (src.name + '.json')).is_file() and not (tmp_path / 'two' / (src.name + '.part')).exists()
    r = host._archive_copy(str(src), str(tmp_path / 'three'), 'not-the-hash', False)
    assert r['return'] == 1 and not (tmp_path / 'three' / src.name).exists()


def test_the_prune_keeps_the_newest_of_that_host_only(host, tmp_path):
    names = ['vm-a-20261101-0100.tar.zst', 'vm-a-20261108-0100.tar.zst', 'vm-a-20261111-1939.tar.zst',
             'vm-ab-20261101-0100.tar.zst', 'vm-a-notes.tar.zst']
    for n in names:
        (tmp_path / n).write_bytes(b'x')
        (tmp_path / (n + '.json')).write_text('{}', encoding='utf-8')
    gone = host._archive_prune(str(tmp_path), 'vm-a', 1, keep_name='vm-a-20261111-1939.tar.zst')
    assert sorted(os.path.basename(p) for p in gone) == ['vm-a-20261101-0100.tar.zst', 'vm-a-20261108-0100.tar.zst']
    left = sorted(p.name for p in tmp_path.iterdir())
    assert 'vm-a-20261111-1939.tar.zst' in left and 'vm-ab-20261101-0100.tar.zst' in left and 'vm-a-notes.tar.zst' in left
    assert 'vm-a-20261101-0100.tar.zst.json' not in left
    assert host._archive_prune(str(tmp_path), 'vm-a', 2) == []          # keep 2: nothing more to remove


# ---- incremental archives (2026-11-11): chains of a full archive, its increments and tar's snapshot file

def touch(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b'x')
        if not n.endswith('.snar'):
            (folder / (n + '.json')).write_text('{"sha256": ""}', encoding='utf-8')


def test_the_chains_by_their_names(host, tmp_path):
    m = host.module
    assert m._archive_name_parts('vm-a', 'vm-a-20261111-2200.tar.zst') == ('full', '20261111-2200', '20261111-2200')
    assert m._archive_name_parts('vm-a', 'vm-a-20261111-2200+20261112-0300.tar.zst') == ('increment', '20261111-2200', '20261112-0300')
    assert m._archive_name_parts('vm-a', 'vm-a-20261111-2200.snar') == ('snar', '20261111-2200', '20261111-2200')
    for other in ('vm-ab-20261111-2200.tar.zst', 'vm-a-notes.tar.zst', 'vm-a-20261111-2200.tar.zst.json',
                  'vm-a-20261111-2200.tar.zst.part', 'vm-a-20261111-2200+20261112-0300.snar'):
        assert m._archive_name_parts('vm-a', other) is None, other
    touch(tmp_path, 'vm-a-20261101-0100.tar.zst', 'vm-a-20261111-2200.tar.zst', 'vm-a-20261111-2200+20261113-0300.tar.zst',
          'vm-a-20261111-2200+20261112-0300.tar.zst', 'vm-a-20261111-2200.snar', 'vm-ab-20261111-2200.tar.zst')
    chains = m._archive_chains(str(tmp_path), 'vm-a')
    assert [c['chain'] for c in chains] == ['20261101-0100', '20261111-2200']
    assert chains[1] == {'chain': '20261111-2200', 'full': 'vm-a-20261111-2200.tar.zst', 'snar': 'vm-a-20261111-2200.snar',
                         'increments': ['vm-a-20261111-2200+20261112-0300.tar.zst', 'vm-a-20261111-2200+20261113-0300.tar.zst']}
    assert chains[0]['increments'] == [] and chains[0]['snar'] == ''


def test_the_prune_removes_old_chains_whole(host, tmp_path):
    drive = tmp_path / 'drive'
    touch(drive, 'vm-a-20261101-0100.tar.zst', 'vm-a-20261101-0100+20261102-0100.tar.zst', 'vm-a-20261101-0100.snar',
          'vm-a-20261111-2200.tar.zst', 'vm-a-20261111-2200+20261112-0300.tar.zst', 'vm-a-20261111-2200.snar')
    gone = host._archive_prune(str(drive), 'vm-a', 1, keep_name='vm-a-20261111-2200+20261112-0300.tar.zst')
    assert sorted(os.path.basename(p) for p in gone) == ['vm-a-20261101-0100+20261102-0100.tar.zst', 'vm-a-20261101-0100.tar.zst']
    assert sorted(p.name for p in drive.iterdir()) == [
        'vm-a-20261111-2200+20261112-0300.tar.zst', 'vm-a-20261111-2200+20261112-0300.tar.zst.json', 'vm-a-20261111-2200.snar',
        'vm-a-20261111-2200.tar.zst', 'vm-a-20261111-2200.tar.zst.json']


def test_what_a_run_makes_full_or_increment(host, tmp_path):
    block = host._archive_block({'desc': {'archive': {'incremental': True, 'full_every': '30d'}}})
    assert block['incremental'] is True and block['full_every'] == '30d'
    assert host._archive_block({'desc': {}}, incremental='yes')['incremental'] is True
    assert host._archive_block({'desc': {'archive': {'incremental': True}}}, incremental='no')['incremental'] is False
    plan = lambda **kw: host._archive_chain_plan(str(tmp_path), 'vm-a', dict(block, **kw.get('b', {})), kw.get('full', False))
    assert plan()['level'] == 0 and 'first of a new chain' in plan()['reason']                        # nothing yet
    now = datetime.datetime.now().strftime('%Y%m%d-%H%M')
    touch(tmp_path, f'vm-a-{now}.tar.zst')
    assert plan()['level'] == 0 and 'without incremental' in plan()['reason']                          # a full of before
    touch(tmp_path, f'vm-a-{now}.snar', f'vm-a-{now}+{now}.tar.zst')
    p = plan()
    assert p['level'] == 2 and p['chain'] == now and p['snar'].endswith(f'vm-a-{now}.snar')         # the next increment
    assert plan(full=True)['level'] == 0 and plan(b={'incremental': False})['level'] == 0
    old = (datetime.datetime.now() - datetime.timedelta(days=40)).strftime('%Y%m%d-%H%M')
    touch(tmp_path, f'vm-a-{old}.tar.zst', f'vm-a-{old}.snar')                                         # an older chain does not count
    assert plan()['level'] == 2
    for n in os.listdir(tmp_path):
        if now in n:
            os.remove(tmp_path / n)
    assert plan()['level'] == 0 and 'older than full_every' in plan()['reason']


def test_a_drive_that_was_away_gets_the_whole_chain(host, tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    names = ['vm-a-20261111-2200.tar.zst', 'vm-a-20261111-2200+20261112-0300.tar.zst', 'vm-a-20261111-2200+20261113-0300.tar.zst']
    a.mkdir()
    for n in names:
        (a / n).write_bytes(n.encode())
        (a / (n + '.json')).write_text(json.dumps({'sha256': hashlib.sha256(n.encode()).hexdigest()}), encoding='utf-8')
    (a / 'vm-a-20261111-2200.snar').write_bytes(b'state after 0300')
    touch(b, names[0])
    (b / names[0]).write_bytes(names[0].encode())
    r = host._archive_chains_sync('vm-a', ['B', 'A'], {'A': str(a), 'B': str(b)}, False)
    assert r['return'] == 0 and r['chain'] == '20261111-2200' and r['newest'] == names[2] and r['copied'] == ['B'], r
    assert all((b / n).read_bytes() == n.encode() for n in names) and (b / 'vm-a-20261111-2200.snar').read_bytes() == b'state after 0300'
    # once complete, nothing more to copy
    assert host._archive_chains_sync('vm-a', ['A', 'B'], {'A': str(a), 'B': str(b)}, False)['copied'] == []


def test_what_to_expect_from_an_estimate(host, tmp_path, monkeypatch):
    """The archive's size and time from what is read (2026-11-11): the host's own last run, else half and the last
    speed of another host as a rough guide, else half and no time."""
    runs = []
    monkeypatch.setattr(host, '_archive_runs', lambda: runs)
    gib = 1024 ** 3
    e = host._archive_expect('vm-a', 10 * gib)
    assert e['archive'] == 5 * gib and 'seconds' not in e
    runs.append({'host': 'vm-b', 'ok': True, 'read': 20 * gib, 'size': 8 * gib, 'seconds': 400})
    e = host._archive_expect('vm-a', 10 * gib)
    assert e['archive'] == 5 * gib and e['seconds'] == 200 and 'rough guide' in e['seconds_how'] and 'vm-b' in e['seconds_how']
    runs.append({'host': 'vm-a', 'ok': True, 'read': 4 * gib, 'size': 1 * gib, 'seconds': 100})
    runs.append({'host': 'vm-a', 'ok': False, 'error': 'down'})
    e = host._archive_expect('vm-a', 10 * gib)
    assert e['archive'] == int(2.5 * gib) and e['seconds'] == 250 and '25 %' in e['archive_how']


def test_the_estimate_is_kept_for_the_page(host, tmp_path, monkeypatch):
    monkeypatch.setattr(host, '_archive_state_folder', lambda: str(tmp_path))
    block = host._archive_block({'desc': {}})
    host._archive_record_estimate('vm-a', {'bytes': 123, 'missing': ['/var/www']}, block, {'archive': 61})
    host._archive_record_estimate('vm-b', {'bytes': 456, 'missing': []}, block, {'archive': 228})
    e = host._archive_estimates()
    assert e['vm-a']['bytes'] == 123 and e['vm-a']['missing'] == ['/var/www'] and e['vm-b']['expect'] == {'archive': 228}
    assert e['vm-a']['at'] and not (tmp_path / 'estimates.json.part').exists()


def test_the_copy_says_it_reads_the_copy_back(host, tmp_path, capsys):
    src = tmp_path / 'one' / 'vm-a-20261111-2200.tar.zst'
    src.parent.mkdir()
    src.write_bytes(b'x' * 5000)
    r = host._archive_copy(str(src), str(tmp_path / 'two'), hashlib.sha256(src.read_bytes()).hexdigest(), True, label='copy to B2')
    out = capsys.readouterr().out
    assert r['return'] == 0 and 'copy to B2: copied, reading it back to check it' in out and 'read back: the same' in out


def test_an_increment_says_nothing_of_a_full_archive(host, monkeypatch):
    gib = 1024 ** 3
    runs = [{'host': 'vm-a', 'ok': True, 'read': 12 * gib, 'size': 5 * gib, 'seconds': 400, 'level': 0},
            {'host': 'vm-a', 'ok': True, 'read': 70 * 1024 ** 2, 'size': 3 * 1024 ** 2, 'seconds': 15, 'level': 1}]
    monkeypatch.setattr(host, '_archive_runs', lambda: runs)
    e = host._archive_expect('vm-a', 12 * gib)
    assert e['archive'] == 5 * gib and e['seconds'] == 400, e


def test_the_script_takes_the_tools_cmeta_set_up(host, tmp_path):
    seen = {}

    def popen(h, script):
        seen['script'] = script
        return {'return': 0, 'process': FakeProcess(b'', b'', rc=255)}
    host._ssh_popen = popen
    host._archive_stream(HOST, host._archive_block({'desc': {}}), str(tmp_path / 'z.part'), 1000, False, TOOLS)
    assert "TAR=/opt/cmeta/gtar; ZSTD=/opt/cmeta/zstd\n" in seen['script']
    assert 'sudo -n "$TAR" --create' in seen['script'] and '| "$ZSTD" -T0' in seen['script']
    assert 'command -v' not in seen['script']


def answer(path, version):
    return '... the setup prints what it does ...\n' + json.dumps({'return': 0, 'path': path, 'version': version}, indent=2) + '\n'


def test_the_tools_come_from_cmeta_on_the_host(host, monkeypatch):
    calls = []

    def run_(ctx, arg1=None, arg2=None, capture=False, timeout=None, **kw):
        calls.append(arg2)
        out = answer('/usr/bin/tar', '1.35') + 'CMETA-TOOL-END\n' + answer('/usr/bin/zstd', '1.5.5')
        return {'return': 0, 'outputs': {arg1: {'returncode': 0, 'stdout': out, 'stderr': ''}}}
    monkeypatch.setattr(host, '_here', lambda h: False)
    monkeypatch.setattr(host, 'run_', run_)
    r = host._archive_tools(HOST)
    assert r['return'] == 0 and r['TAR'] == '/usr/bin/tar' and r['ZSTD'] == '/usr/bin/zstd' and not r['warning'], r
    assert 'GNU tar 1.35 (/usr/bin/tar)' in r['text'] and 'zstd 1.5.5 (/usr/bin/zstd)' in r['text']
    assert calls and 'cx task run setup gnu-tar,93bb237a0ee04cd6 -q -j' in calls[0] and 'setup zstd,e70d016f472d462e -q -j' in calls[0]


def test_a_host_whose_cmeta_lacks_the_tool_takes_its_path(host, monkeypatch):
    def run_(ctx, arg1=None, arg2=None, capture=False, timeout=None, **kw):
        out = (json.dumps({'return': 16, 'error': 'artifact "gnu-tar,93bb237a0ee04cd6" not found'}) + '\nCMETA-TOOL-END\n'
               + answer('/usr/bin/zstd', '1.5.5'))
        return {'return': 0, 'outputs': {arg1: {'returncode': 0, 'stdout': out, 'stderr': ''}}}
    monkeypatch.setattr(host, '_here', lambda h: False)
    monkeypatch.setattr(host, 'run_', run_)
    monkeypatch.setattr(host, '_ssh_io', lambda h, command, data=None, timeout=900: (0, b'TAR /bin/tar\n', ''))
    r = host._archive_tools(HOST)
    assert r['return'] == 0 and r['TAR'] == '/bin/tar' and r['ZSTD'] == '/usr/bin/zstd', r
    assert 'GNU tar from the PATH' in r['warning'] and 'not found' in r['warning']

    # nothing on the PATH either: refused, saying how to get it
    monkeypatch.setattr(host, '_ssh_io', lambda h, command, data=None, timeout=900: (0, b'', ''))
    r = host._archive_tools(HOST)
    assert r['return'] > 0 and 'cx tool install gnu-tar' in r['error'], r

    # no cMeta there at all (cx not found): both from the PATH
    def run_none(ctx, arg1=None, arg2=None, capture=False, timeout=None, **kw):
        return {'return': 1, 'error': 'command failed', 'outputs': {arg1: {'returncode': 127, 'stdout': '', 'stderr': 'bash: cx: command not found'}}}
    monkeypatch.setattr(host, 'run_', run_none)
    monkeypatch.setattr(host, '_ssh_io', lambda h, command, data=None, timeout=900: (0, b'TAR /usr/bin/tar\nZSTD /usr/bin/zstd\n', ''))
    r = host._archive_tools(HOST)
    assert r['return'] == 0 and r['TAR'] == '/usr/bin/tar' and 'cx: command not found' in r['warning'], r


def test_deleted_names_leave_out_what_is_inside_a_gone_folder(host):
    old = {'C/a': 'd', 'C/a/b': 'd', 'C/a/b/c.txt': [1, 2], 'C/a-x.txt': [1, 2], 'C/keep.txt': [1, 2]}
    assert host.module._archive_deleted(old, {'C/keep.txt'}) == ['C/a', 'C/a-x.txt']
    assert host.module._archive_deleted(old, set(old)) == []


def tree(root):
    """A folder as {relative path: bytes or None (a folder)}."""
    out = {}
    for d, dirs, files in os.walk(root):
        for x in dirs:
            out[os.path.relpath(os.path.join(d, x), root).replace(os.sep, '/')] = None
        for x in files:
            with open(os.path.join(d, x), 'rb') as f:
                out[os.path.relpath(os.path.join(d, x), root).replace(os.sep, '/')] = f.read()
    return out


def restore_chain(module, parts, into):
    """What a restore of a Python archiver's chain does: each part in order, what it deleted removed first."""
    import shutil as _sh
    for part in parts:
        with tarfile.open(part, mode='r|zst') as tf:
            for m in tf:
                if m.name == module.ARCHIVE_META_DIR + '/deleted.txt':
                    for n in tf.extractfile(m).read().decode('utf-8').splitlines():
                        p = os.path.join(into, *n.split('/'))
                        if os.path.isdir(p):
                            _sh.rmtree(p)
                        elif os.path.exists(p):
                            os.remove(p)
                    continue
                tf.extract(m, into, filter='fully_trusted')


@pytest.mark.skipif(not HAS_ZSTD, reason='the test reads zstd through Python 3.14')
def test_the_python_archiver_full_increment_and_restore(host, tmp_path):
    module = host.module
    root = tmp_path / 'data'
    (root / 'sub').mkdir(parents=True)
    (root / 'skip').mkdir()
    (root / 'a.txt').write_bytes(b'alpha\n' * 100)
    (root / 'sub' / 'b.txt').write_bytes(b'beta\n')
    (root / 'skip' / 'c.txt').write_bytes(b'not archived\n')
    (root / 'gone.txt').write_bytes(b'deleted later\n')
    (root / 'old-dir').mkdir()
    (root / 'old-dir' / 'd.txt').write_bytes(b'in a folder deleted later\n')
    block = host._archive_block({'desc': {}}, paths=str(root), exclude=str(root / 'skip'), incremental='yes')

    # the full archive: every file but the excluded one; its snapshot says what is in the chain
    walk = host._archive_walk_py(block, False)
    assert walk['files'] == 4 and walk['bytes'] == len(b'alpha\n' * 100) + 5 + 14 + 26 and not walk['missing']
    full = tmp_path / 'vm-a-20261112-0800.tar.zst'
    r = host._archive_stream_py(walk, str(full) + '.part', walk['bytes'], False, 'vm-a', 0, {}, [], 3)
    assert r['return'] == 0 and r['read'] == walk['bytes'] and r['warnings'] == 0, r
    os.replace(str(full) + '.part', full)
    assert r['sha256'] == hashlib.sha256(full.read_bytes()).hexdigest() and r['written'] == full.stat().st_size
    c = host._archive_check(str(full), False, 'vm-a')
    assert c['ok'] and c['bytes'] == walk['bytes']
    snap = tmp_path / 'vm-a-20261112-0800.snar'
    module._snapshot_write(str(snap), r['snapshot'])
    old = module._snapshot_read(str(snap))
    assert old == json.loads(json.dumps(r['snapshot'])) and module._snapshot_read(str(tmp_path / 'none.snar')) is None

    # what changed: a.txt rewritten, gone.txt and old-dir removed, new/n.txt added; sub/b.txt the same
    (root / 'a.txt').write_bytes(b'alpha changed\n')
    os.remove(root / 'gone.txt')
    import shutil as _sh
    _sh.rmtree(root / 'old-dir')
    (root / 'new').mkdir()
    (root / 'new' / 'n.txt').write_bytes(b'new\n')
    walk2 = host._archive_walk_py(block, False)
    deleted = module._archive_deleted(old, {e[0] for e in walk2['entries']})
    base = module._win_tar_name(str(root))
    assert deleted == [base + '/gone.txt', base + '/old-dir'], deleted
    inc = tmp_path / 'vm-a-20261112-0800+20261112-0900.tar.zst'
    r2 = host._archive_stream_py(walk2, str(inc), 0, False, 'vm-a', 1, old, deleted, 3)
    assert r2['return'] == 0, r2
    with tarfile.open(inc, mode='r|zst') as tf:
        names = [m.name for m in tf]
    assert names[0] == module.ARCHIVE_META_DIR + '/deleted.txt'
    assert sorted(names[1:]) == sorted([base + '/a.txt', base + '/new', base + '/new/n.txt']), names

    # the chain restored in order is the tree as it is now (the excluded folder aside)
    into = tmp_path / 'restored'
    restore_chain(module, [full, inc], str(into))
    expected = {k: v for k, v in tree(root).items() if not k.startswith('skip')}
    assert tree(into / base) == expected


def chain_on_a_drive(tmp_path, alias, names, fmt='gnu-tar'):
    """A drive X1 with the archives of alias in its cmeta_backup folder (each with its .json)."""
    folder = tmp_path / 'X1' / 'cmeta_backup' / alias
    folder.mkdir(parents=True)
    for n in names:
        (folder / n).write_bytes(b'z' * 100)
        if n.endswith('.tar.zst'):
            (folder / (n + '.json')).write_text(json.dumps({'format': fmt, 'incremental': '+' in n or n.endswith('.snar'),
                                                            'finished': '2026-11-12T08:00:00+01:00'}), encoding='utf-8')
    return folder


def test_restore_takes_the_parts_of_a_chain(host, tmp_path, monkeypatch):
    names = ['vm-a-20261101-0800.tar.zst', 'vm-a-20261110-0800.tar.zst', 'vm-a-20261110-0800+20261111-0800.tar.zst',
             'vm-a-20261110-0800+20261112-0800.tar.zst', 'vm-a-20261110-0800.snar']
    chain_on_a_drive(tmp_path, 'vm-a', names)
    monkeypatch.setattr(host, '_drive_roots', lambda: {'X1': {'root': str(tmp_path / 'X1'), 'size': 1, 'free': 1}})
    monkeypatch.setattr(host, '_here', lambda h: False)
    h = dict(HOST, desc={'archive': {'to': ['X1']}})
    ctx = {'control': {'con': False}}
    r = host._restore_archive(ctx, h, True, None, '', None, None, True, False)
    assert r['parts'] == names[1:4], r
    r = host._restore_archive(ctx, h, True, '2026-11-11 12:00', '', None, None, True, False)
    assert r['parts'] == names[1:3], r
    r = host._restore_archive(ctx, h, True, '20261105', '', None, None, True, False)
    assert r['parts'] == names[:1], r
    r = host._restore_archive(ctx, h, names[2], None, '', None, None, True, False)
    assert r['parts'] == names[1:3], r
    r = host._restore_archive(ctx, h, True, '20261030', '', None, None, True, False)
    assert r['return'] > 0 and 'no archive' in r['error'], r
    # in place only with --yes
    r = host._restore_archive(ctx, h, True, None, '', None, None, False, False)
    assert r['return'] > 0 and '--yes' in r['error'] and 'deletes' in r['error'], r


def test_restore_sends_each_part_into_the_hosts_tar(host, tmp_path, monkeypatch):
    names = ['vm-a-20261110-0800.tar.zst', 'vm-a-20261110-0800+20261111-0800.tar.zst']
    folder = chain_on_a_drive(tmp_path, 'vm-a', names)
    monkeypatch.setattr(host, '_drive_roots', lambda: {'X1': {'root': str(tmp_path / 'X1'), 'size': 1, 'free': 1}})
    monkeypatch.setattr(host, '_here', lambda h: False)
    monkeypatch.setattr(host, '_archive_tools', lambda h: {'return': 0, 'TAR': '/opt/cmeta/gtar', 'ZSTD': '/opt/cmeta/zstd',
                                                          'text': 'GNU tar, zstd', 'warning': ''})
    sent = []
    monkeypatch.setattr(host, '_restore_feed', lambda h, script, path, label, con: sent.append((script, path)) or {'return': 0, 'warnings': 0})
    h = dict(HOST, desc={'archive': {'to': ['X1']}})
    r = host._restore_archive({'control': {'con': False}}, h, True, None, 'cmeta-tests/look', '~/work,/etc/nginx', None, False, False)
    assert r['return'] == 0 and [os.path.basename(x[1]) for x in sent] == names, r
    script = sent[1][0]
    assert "TAR=/opt/cmeta/gtar; ZSTD=/opt/cmeta/zstd" in script and 'T="$HOME"/cmeta-tests/look' in script
    assert 'M=("${HOME#/}"/work etc/nginx)' in script
    # into a folder: tar as the host's user (the folder stays the user's to remove), the chain's deletions applied
    assert '| "$TAR" -xpf - --listed-incremental=/dev/null -C "$T" -- "${M[@]}"' in script and 'sudo' not in script
    # in place (--yes): through sudo, the owners as they were; --into=~/x is under the home
    sent.clear()
    host._restore_archive({'control': {'con': False}}, h, True, None, '', None, None, False, True)
    assert 'T=/\n' in sent[0][0] and 'sudo -n "$TAR" -xpf - --numeric-owner --listed-incremental=/dev/null' in sent[0][0]
    sent.clear()
    host._restore_archive({'control': {'con': False}}, h, True, None, '~/r', None, None, False, False)
    assert 'T="$HOME"/r\n' in sent[0][0]
    # a part of the Python archiver is restored on its own (Windows) machine
    (folder / (names[0] + '.json')).write_text(json.dumps({'format': 'python-tar'}), encoding='utf-8')
    r = host._restore_archive({'control': {'con': False}}, h, True, None, 'x', None, None, False, False)
    assert r['return'] > 0 and 'Python archiver' in r['error'], r


def load_untar():
    """The untar task's module with a stand-in for the task base class cMeta gives it."""
    import types
    base = types.ModuleType('task_c36be4b9314a45e0.api.ctask')

    class InitCTask:
        def __init__(self, *a, **k):
            pass
    base.InitCTask = InitCTask
    for name in ('task_c36be4b9314a45e0', 'task_c36be4b9314a45e0.api'):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules['task_c36be4b9314a45e0.api.ctask'] = base
    spec = importlib.util.spec_from_file_location('task_untar_under_test', str(REPO_ROOT / 'task' / 'untar' / 'api_v1.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_untar_finds_the_parts_of_a_chain_and_who_made_them(tmp_path):
    untar = load_untar()
    names = ['vm-a-20261110-0800.tar.zst', 'vm-a-20261110-0800+20261111-0800.tar.zst',
             'vm-a-20261110-0800+20261112-0800.tar.zst', 'vm-b-20261110-0800.tar.zst']
    folder = chain_on_a_drive(tmp_path, 'vm-a', names, fmt='python-tar')
    r = untar.chain_parts(str(folder / names[2]))
    assert [os.path.basename(x) for x in r['parts']] == names[:3]
    r = untar.chain_parts(str(folder / names[2]), until='2026-11-11 23:59')
    assert [os.path.basename(x) for x in r['parts']] == names[:2]
    r = untar.chain_parts(str(folder / names[1]))
    assert [os.path.basename(x) for x in r['parts']] == names[:2]
    assert untar.chain_parts(str(folder / 'other.tar.zst'))['return'] > 0
    os.remove(folder / names[0])
    assert 'full archive' in untar.chain_parts(str(folder / names[2]))['error']
    assert untar.part_format(str(folder / names[1])) == 'python-tar' and untar.part_format(str(tmp_path / 'none')) == 'gnu-tar'
    assert untar._stamp('2026-11-12 08:30') == '20261112-0830' and untar._stamp('20261112') == '20261112'


@pytest.mark.skipif(not HAS_ZSTD, reason='the test reads zstd through Python 3.14')
def test_untar_restores_a_chain_of_the_python_archiver(host, tmp_path):
    module, untar = host.module, load_untar()
    root = tmp_path / 'data'
    (root / 'sub').mkdir(parents=True)
    (root / 'a.txt').write_bytes(b'one\n')
    (root / 'sub' / 'b.txt').write_bytes(b'two\n')
    (root / 'gone.txt').write_bytes(b'three\n')
    block = host._archive_block({'desc': {}}, paths=str(root), exclude='', incremental='yes')
    folder = tmp_path / 'drive'
    folder.mkdir()
    walk = host._archive_walk_py(block, False)
    full = folder / 'vm-a-20261112-0800.tar.zst'
    r = host._archive_stream_py(walk, str(full), walk['bytes'], False, 'vm-a', 0, {}, [], 3)
    old = json.loads(json.dumps(r['snapshot']))
    (root / 'a.txt').write_bytes(b'one, changed\n')
    os.remove(root / 'gone.txt')
    walk2 = host._archive_walk_py(block, False)
    deleted = module._archive_deleted(old, {e[0] for e in walk2['entries']})
    inc = folder / 'vm-a-20261112-0800+20261112-0900.tar.zst'
    host._archive_stream_py(walk2, str(inc), 0, False, 'vm-a', 1, old, deleted, 3)
    for part in (full, inc):
        (folder / (part.name + '.json')).write_text(json.dumps({'format': 'python-tar'}), encoding='utf-8')

    t = untar.CTask.__new__(untar.CTask)
    t.cm = host.cm
    into = tmp_path / 'restored'
    into.mkdir()
    (into / 'stale.txt').write_bytes(b'not touched\n')
    parts = untar.chain_parts(str(inc))['parts']
    total = 0
    for i, part in enumerate(parts):
        x = t._extract_py(part, str(into), False, [], f'part {i + 1}', False, True)
        assert x['return'] == 0, x
        total += x['deleted']
    base = module._win_tar_name(str(root))
    assert total == 1 and tree(into / base) == tree(root) and (into / 'stale.txt').exists()
    # only the names asked for
    only = tmp_path / 'only'
    for part in parts:
        t._extract_py(part, str(only), False, [base + '/sub'], 'p', False, True)
    assert tree(only / base) == {'sub': None, 'sub/b.txt': b'two\n'}
