"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx host sync" and the folders a two-way run leaves behind: a folder deleted on one side stayed on the other when it
still held files the sync leaves out on purpose (its blacklist: SQLite side files, a lock, __pycache__/ ...), which
rclone neither lists nor deletes. After a run, the folders it emptied of every file it carries - from its listings,
before and after - are moved aside, whole, into the run's folder of the sync-backup artifact of that side; a folder
that holds a file the sync carries stays, and one whose files changed lately is looked at again by the next run.
Offline: the rclone and ssh calls are stubbed; the host's part runs here, in a separate Python, as it would there.
"""

import ast
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOST = {'alias': 'lab', 'type': 'ssh', 'desc': {}, 'state': {}}
CTX = {'control': {'con': False}, 'tasks': {'nested_call': 0}}
OLD = time.time() - 86400


def load():
    spec = importlib.util.spec_from_file_location('host_sync_leftovers_under_test', REPO_ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def m():
    return load()


def make(root, rel, when=OLD, text='x'):
    """A file under root (its folders made), dated "when"."""
    path = pathlib.Path(root, *rel.split('/'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (when, when))
    return path


def side(m, root, dirs, patterns=None, **kw):
    p = {'root': str(root), 'dirs': dirs, 'patterns': list(m.DEFAULT_BLACKLIST if patterns is None else patterns),
         'quiet': 600, 'dest': str(pathlib.Path(root).parent / 'backup')}
    p.update(kw)
    return m._sync_leftovers(p)


def ancestors(rel):
    parts = rel.split('/')
    return ['/'.join(parts[:i]) for i in range(1, len(parts))]


# _sync_leftovers: one side

def test_a_folder_held_only_by_left_out_files_is_moved_aside_whole(m, tmp_path):
    root = tmp_path / 'repo'
    codex = 'work/2026/20261111.item/!AI/codex/'
    for f in ('logs_2.sqlite-wal', 'logs_2.sqlite-shm', 'queue_1.sqlite-wal', '.sqlite-maintenance.lock'):
        make(root, codex + f)
    make(root, 'work/20261112.other/_cmeta.yaml')

    r = side(m, root, ancestors(codex + 'x')[1:])                 # work/ itself holds a file the sync carries

    assert [x['dir'] for x in r['moved']] == ['work/2026']        # the topmost emptied folder, its inside with it
    assert r['moved'][0]['files'] == 4 and r['kept'] == [] and r['pending'] == []
    assert len(r['moved'][0]['sample']) == 3 and r['moved'][0]['bytes'] == 4
    assert not (root / 'work' / '2026').exists()
    assert (root / 'work' / '20261112.other' / '_cmeta.yaml').is_file()          # the rest of work/ untouched
    moved = tmp_path / 'backup' / 'work' / '2026' / '20261111.item' / '!AI' / 'codex'
    assert sorted(os.listdir(moved)) == sorted(['logs_2.sqlite-wal', 'logs_2.sqlite-shm', 'queue_1.sqlite-wal',
                                                '.sqlite-maintenance.lock'])
    assert r['moved'][0]['to'] == str(tmp_path / 'backup' / 'work' / '2026')


def test_a_folder_with_a_file_the_sync_carries_stays(m, tmp_path):
    root = tmp_path / 'repo'
    make(root, 'a/b/x.sqlite-wal')
    make(root, 'a/b/notes.md')

    r = side(m, root, ['a', 'a/b'])

    assert r['moved'] == [] and r['kept'][0]['why'] == 'carried' and r['kept'][0]['file'].endswith('notes.md')
    assert (root / 'a' / 'b' / 'notes.md').is_file()


def test_a_recent_change_leaves_the_folder_for_the_next_run(m, tmp_path):
    root = tmp_path / 'repo'
    make(root, 'a/q.sqlite-shm', when=time.time() - 30)

    r = side(m, root, ['a'])

    assert r['moved'] == [] and r['pending'] == ['a'] and r['kept'] == [{'dir': 'a', 'why': 'recent', 'file': 'a/q.sqlite-shm'}]
    assert (root / 'a' / 'q.sqlite-shm').is_file()


def test_empty_folders_are_removed_and_nothing_is_moved(m, tmp_path):
    root = tmp_path / 'repo'
    (root / 'a' / 'b' / 'c').mkdir(parents=True)

    r = side(m, root, ['a', 'a/b'], dest='')

    assert r['moved'] == [{'dir': 'a', 'files': 0, 'bytes': 0, 'sample': [], 'to': ''}]
    assert not (root / 'a').exists() and not (tmp_path / 'backup').exists()


def test_files_without_a_folder_to_go_to_stay(m, tmp_path):
    root = tmp_path / 'repo'
    make(root, 'a/x.sqlite-wal')

    r = side(m, root, ['a'], dest='')

    assert r['moved'] == [] and r['kept'][0]['why'] == 'error' and (root / 'a' / 'x.sqlite-wal').is_file()


def test_a_partial_selection_keeps_the_category_and_moves_the_artifact(m, tmp_path):
    # this machine holds the whole repository: work/ keeps artifacts outside the selection (not blacklisted)
    root = tmp_path / 'repo'
    make(root, 'work/a/__pycache__/m.cpython-314.pyc')
    make(root, 'work/b/README.md')

    r = side(m, root, ['work', 'work/a'], ignore_case=True)

    assert [x['dir'] for x in r['moved']] == ['work/a']
    assert r['kept'] == [{'dir': 'work', 'why': 'carried', 'file': 'work/b/README.md'}]
    assert (root / 'work' / 'b' / 'README.md').is_file() and not (root / 'work' / 'a').exists()


def test_leftovers_join_the_folder_the_runs_backup_holds_already(m, tmp_path):
    # rclone put what the run deleted from work/2026 into the run's backup: the files left there join that folder
    root, dest = tmp_path / 'repo', tmp_path / 'backup'
    make(root, 'work/2026/item/!AI/codex/q.sqlite-wal')
    make(root, 'work/2026/item/x.sqlite-shm')
    make(dest, 'work/2026/item/notes.md')
    make(dest, 'work/2026/item/x.sqlite-shm')                          # a name taken there: the newcomer gets a suffix

    r = side(m, root, ['work/2026', 'work/2026/item'])

    assert [x['dir'] for x in r['moved']] == ['work/2026'] and not (root / 'work' / '2026').exists()
    got = sorted(p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file())
    assert got[:3] == ['work/2026/item/!AI/codex/q.sqlite-wal', 'work/2026/item/notes.md', 'work/2026/item/x.sqlite-shm']
    assert len(got) == 4 and re.match(r'work/2026/item/x\.sqlite-shm\.\d{6}$', got[3])
    assert (root / 'work').is_dir()                                     # only the folder left behind went


def test_a_folder_holding_an_artifact_the_sync_leaves_out_stays(m, tmp_path):
    root = tmp_path / 'repo'
    make(root, 'w/tmp-x/a/_cmeta.yaml')                                 # an artifact under a left-out tmp*/ folder
    make(root, 'w/y/q.sqlite-wal')

    r = side(m, root, ['w', 'w/y'])

    assert r['kept'] == [{'dir': 'w', 'why': 'artifact', 'file': 'w/tmp-x/a/_cmeta.yaml'}]
    assert [x['dir'] for x in r['moved']] == ['w/y'] and (root / 'w' / 'tmp-x' / 'a' / '_cmeta.yaml').is_file()


def test_dry_says_and_moves_nothing(m, tmp_path):
    root = tmp_path / 'repo'
    make(root, 'a/x.sqlite-wal')

    r = side(m, root, ['a'], dry=True)

    assert [x['dir'] for x in r['moved']] == ['a'] and r['moved'][0]['to'] == ''
    assert (root / 'a' / 'x.sqlite-wal').is_file() and not (tmp_path / 'backup').exists()


def test_a_folder_outside_the_root_or_gone_is_never_touched(m, tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    make(tmp_path, 'outside/x.sqlite-wal')

    r = side(m, root, ['../outside', 'gone', ''])

    assert r == {'moved': [], 'kept': [], 'pending': []}
    assert (tmp_path / 'outside' / 'x.sqlite-wal').is_file()


@pytest.mark.parametrize('pattern, rel, left_out', [
    ('*.sqlite-wal', 'd/deep/x.sqlite-wal', True),
    ('*.sqlite-wal', 'd/x.sqlite-wal.txt', False),
    ('.sqlite-maintenance.lock', 'd/a/.sqlite-maintenance.lock', True),
    ('tmp*/', 'd/a/tmp-run/out.txt', True),
    ('tmp*/', 'd/a/atmp/out.txt', False),
    ('.git/', 'd/clone/.git/objects/ab/cd', True),
    ('/top/**', 'd/top/x', False),                  # anchored at the root: d/top is not the root's top
    ('top/**', 'd/top/x', True),
    ('/d/**', 'd/x', True),
    ('{a,b}.lock', 'd/b.lock', True),
    ('{a,b}.lock', 'd/c.lock', False),
    ('[!x]y.txt', 'd/zy.txt', True),
    ('[!x]y.txt', 'd/xy.txt', False),
    ('/d/f\\[1\\].txt', 'd/f[1].txt', True),          # escaped glob characters, as _exclude_rule writes them
    ('?.log', 'd/a.log', True),
    ('?.log', 'd/ab.log', False),
])
def test_the_blacklist_is_read_as_rclone_reads_it(m, tmp_path, pattern, rel, left_out):
    root = tmp_path / 'repo'
    make(root, rel)

    r = side(m, root, ['d'], patterns=[pattern], dry=True)

    assert bool(r['moved']) is left_out


def test_a_partial_repository_compares_without_case(m, tmp_path):
    root = tmp_path / 'repo'
    make(root, 'd/X.SQLITE-WAL')

    assert side(m, root, ['d'], dry=True)['moved'] == []
    assert side(m, root, ['d'], dry=True, ignore_case=True)['moved'][0]['dir'] == 'd'


@pytest.mark.skipif(os.name == 'nt', reason='a symbolic link needs a privilege on Windows')
def test_a_link_holds_nothing_and_goes_with_the_folder(m, tmp_path):
    root = tmp_path / 'repo'
    make(root, 'd/x.sqlite-wal')
    target = make(tmp_path, 'elsewhere/data.txt')
    for link, to in (('link.txt', target), ('dirlink', target.parent)):
        os.symlink(to, root / 'd' / link)
        os.utime(root / 'd' / link, (OLD, OLD), follow_symlinks=False)  # a link of now is a recent change too

    r = side(m, root, ['d'])

    assert r['moved'][0]['files'] == 3 and target.is_file()        # the link moved, never its target
    assert os.path.islink(tmp_path / 'backup' / 'd' / 'dirlink') and (tmp_path / 'elsewhere' / 'data.txt').is_file()


# the listings

def test_names_in_the_listings_come_back_as_they_are(m):
    assert m._go_unquote('plain/name.md') == 'plain/name.md'
    assert m._go_unquote('technical\\u00a0AI !!!/x') == 'technical\u00a0AI !!!/x'
    assert m._go_unquote('say \\"hi\\"/a\\\\b') == 'say "hi"/a\\b'
    assert m._go_unquote('tab\\there') == 'tab\there'


def test_the_folders_a_run_emptied(m):
    old = {'_cmr.yaml', 'work/2026/i/_cmeta.yaml', 'work/2026/i/!AI/log/x.md', 'work/k/_cmeta.yaml', 'gone/a.md'}
    new = {'_cmr.yaml', 'work/k/_cmeta.yaml'}

    assert m.Category._emptied_dirs(old, new) == {'work/2026', 'work/2026/i', 'work/2026/i/!AI', 'work/2026/i/!AI/log', 'gone'}


def listing(path, names):
    lines = ['# bisync listing v1 from 2026-11-12T14:09:59.052450000+0000']
    for n in names:
        q = n.replace('\\', '\\\\').replace('"', '\\"').replace('\u00a0', '\\u00a0')
        lines.append(f'-       10 - - 2026-11-12T10:00:00.000000000+0000 "{q}"')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


# the sync: both sides, through _sync_repo

@pytest.fixture
def sync(tmp_path):
    """The host category of a two-way sync of my-repo with lab: rclone stubbed, the pair's listings written by the test,
    the backup artifact in tmp_path, the host's Python answered by the test (c.host_answer) and its script kept."""
    module = load()
    c = module.Category.__new__(module.Category)
    c.calls, c.ssh, c.scripts = [], [], []
    art = tmp_path / 'local' / 'result' / 'sync-backup--my-repo'
    art.mkdir(parents=True)
    (art / '_cmeta.yaml').write_text('artifact: 0123456789abcdef\n')

    def access(p):
        if p.get('command') == 'reindex':
            return {'return': 0}
        assert p['command'] == 'get' and p['arg1'] == 'local:sync-backup--my-repo'
        c.calls.append({'command': 'get-backup-artifact'})
        return {'return': 0, 'artifact': {'path': str(art)}}

    c.cm = SimpleNamespace(error=lambda s: {'return': 1, 'error': s}, catch_error=lambda r: r['return'] > 0, access=access)
    c.cmeta = {'uses_categories': {'result': 'result,6567e4df4d04488a'}}
    workdir = tmp_path / 'workdir'
    workdir.mkdir()
    c._repo_desc = lambda local: {}
    c._bisync_workdir = lambda h, entry: str(workdir)
    c._index_after_sync = lambda *a, **kw: None
    c._cmd_run = lambda ctx, h, cmd: c.ssh.append(cmd) or {'return': 0, 'cmd': 'ssh lab ' + cmd}
    c.host_answer = None

    def temp_script(script, suffix='.sh'):
        c.scripts.append(script)
        return {'return': 0, 'path': 'script' + suffix}

    def run_local(cmd, **kw):
        if cmd == 'host-python':
            if c.host_answer is None:
                return {'returncode': 1, 'stdout': '', 'stderr': 'python3: not found'}
            return {'returncode': 0, 'stdout': 'motd\n' + module.LEFTOVERS_MARK + json.dumps(c.host_answer) + '\n'}
        return {'returncode': 0}                    # "test -d ..." of the backup's _cmeta: yes, files went there

    c._temp_script = temp_script
    c._cmd_stdin = lambda ctx, h, path: {'return': 0, 'cmd': 'host-python'}
    c._run_local = run_local
    c._index_on_host = lambda *a, **kw: {'return': 0}

    def rclone(ctx, h, command, local, remote_path, **kw):
        c.calls.append({'command': command, 'local': local, 'remote': remote_path})
        return {'return': 0, 'output': c.output}

    c._rclone = rclone
    c.output = 'INFO  : - Path1    Queue delete    - Path2    work/2026/i/_cmeta.yaml'
    local = tmp_path / 'repos' / 'my-repo'
    local.mkdir(parents=True)
    entry = {'method': 'bisync', 'local': str(local), 'remote': '/home/u/CMETA/repos/my-repo',
             'blacklist': list(module.DEFAULT_BLACKLIST)}
    pair = workdir / (c._bisync_pair_prefix(entry) + '_sftp__home_u_CMETA_repos_my-repo')
    return SimpleNamespace(c=c, m=module, local=local, art=art, entry=entry, pair=pair, workdir=workdir)


def listings(s, old, new):
    for side_ in (1, 2):
        listing(pathlib.Path(f'{s.pair}.path{side_}.lst-old'), old)
        listing(pathlib.Path(f'{s.pair}.path{side_}.lst'), new)


def run(s, **kw):
    args = dict(resync=False, resync_mode='newer', unlock=False, dry_run=False, con=False, verbose=False, capture=True)
    args.update(kw)
    return s.c._sync_repo(CTX, HOST, 'my-repo', s.entry, **args)


def test_the_sync_moves_what_it_left_behind_on_both_sides(sync):
    s = sync
    listings(s, ['keep/a.md', 'work/k/_cmeta.yaml', 'work/2026/i/_cmeta.yaml'], ['keep/a.md', 'work/k/_cmeta.yaml'])
    make(s.local, 'keep/a.md')
    make(s.local, 'work/k/_cmeta.yaml')
    make(s.local, 'work/2026/i/!AI/codex/logs_2.sqlite-wal')
    s.c.host_answer = {'moved': [{'dir': 'work/2026', 'files': 5, 'bytes': 900, 'sample': ['logs_2.sqlite-wal'],
                                  'to': '/home/u/CMETA/repos/local/result/sync-backup--my-repo/x/y/work/2026'}],
                       'kept': [], 'pending': []}

    r = run(s)

    assert r['return'] == 0
    # here: work/2026 went whole into <the artifact>/<host>/<run id>/
    assert not (s.local / 'work' / '2026').exists() and (s.local / 'keep' / 'a.md').is_file()
    runs = os.listdir(s.art / 'lab')
    assert len(runs) == 1 and (s.art / 'lab' / runs[0] / 'work' / '2026' / 'i' / '!AI' / 'codex' / 'logs_2.sqlite-wal').is_file()
    # there: the host's Python got the folders, the blacklist and the run's folder of its artifact - the same run id
    params = json.loads(ast.literal_eval(re.search(r'json\.loads\((.*)\)\)\)\)\s*$', s.c.scripts[0], re.M).group(1)))
    assert params['dirs'] == ['work/2026', 'work/2026/i'] and params['ignore_case'] is False
    assert params['root'] == '/home/u/CMETA/repos/my-repo' and params['patterns'] == list(s.m.DEFAULT_BLACKLIST)
    assert params['dest'].endswith('/local/result/sync-backup--my-repo/' + s.m.Category._backup_remote('my-repo', s.entry, runs[0])[0]
                                   + '/' + runs[0])
    assert s.c.scripts[0].startswith('P=$(command -v python3 2>/dev/null)\n') and "cMeta python path" in s.c.scripts[0]
    assert "\"${P:-python}\" - <<'CMETA_SYNC_LEFTOVERS'\n" in s.c.scripts[0]
    # the artifact there got its _cmeta (the backup's own step), and the verdict says what happened on each side
    assert any(x.startswith('test -d ') for x in s.c.ssh)
    assert any('moved aside on this machine: work/2026' in n for n in r['leftovers'])
    assert any('moved aside on lab: work/2026' in n for n in r['leftovers'])
    assert not os.path.exists(f'{s.pair}.leftovers.json')


def test_a_run_that_deleted_nothing_reads_no_listing(sync, monkeypatch):
    s = sync
    listings(s, ['keep/a.md'], ['keep/a.md'])
    s.c.output = 'INFO  : Bisync successful'
    monkeypatch.setattr(s.c, '_listing_names', lambda path: pytest.fail('a listing was read'))

    r = run(s)

    assert r['return'] == 0 and r['leftovers'] == [] and s.c.scripts == []


def test_a_recent_folder_is_looked_at_again_by_the_next_run(sync):
    s = sync
    listings(s, ['keep/a.md', 'w/x/_cmeta.yaml'], ['keep/a.md'])
    wal = make(s.local, 'w/x/q.sqlite-wal', when=time.time() - 5)
    s.c.host_answer = {'moved': [], 'kept': [], 'pending': []}

    r = run(s)

    assert wal.is_file() and any('changed lately' in n for n in r['leftovers'])
    with open(f'{s.pair}.leftovers.json', encoding='utf-8') as f:
        assert json.load(f) == {'1': ['w']}

    # the next run deleted nothing, the file is quiet now: the folder goes, the record with it
    os.utime(wal, (OLD, OLD))
    s.c.output = 'INFO  : Bisync successful'
    s.c.scripts.clear()
    r = run(s)

    assert not (s.local / 'w').exists() and any('moved aside on this machine: w' in n for n in r['leftovers'])
    assert s.c.scripts == []                        # nothing was left on the host: it is not asked
    assert not os.path.exists(f'{s.pair}.leftovers.json')


def test_a_host_that_cannot_look_is_asked_again_next_time(sync):
    s = sync
    listings(s, ['keep/a.md', 'w/x/_cmeta.yaml'], ['keep/a.md'])
    s.c.host_answer = None                          # its Python is missing

    r = run(s)

    assert any('not looked at on lab' in n for n in r['leftovers'])
    with open(f'{s.pair}.leftovers.json', encoding='utf-8') as f:
        assert json.load(f) == {'2': ['w', 'w/x']}


def test_no_backup_artifact_is_made_when_nothing_is_left_here(sync):
    s = sync
    listings(s, ['keep/a.md', 'w/x/_cmeta.yaml'], ['keep/a.md'])
    s.c.host_answer = {'moved': [], 'kept': [], 'pending': []}

    r = run(s)

    assert r['leftovers'] == [] and {'command': 'get-backup-artifact'} not in s.c.calls


@pytest.mark.parametrize('kw', [{'dry_run': True}, {'resync': True}])
def test_a_dry_run_or_a_resync_leaves_every_folder_alone(sync, kw):
    s = sync
    listings(s, ['keep/a.md', 'w/x/_cmeta.yaml'], ['keep/a.md'])
    make(s.local, 'w/x/q.sqlite-wal')

    r = run(s, **kw)

    assert r['return'] == 0 and 'leftovers' not in r and (s.local / 'w' / 'x' / 'q.sqlite-wal').is_file()


def test_with_backup_the_folders_join_what_the_run_deleted(sync):
    s = sync
    listings(s, ['keep/a.md', 'w/x/_cmeta.yaml'], ['keep/a.md'])
    make(s.local, 'w/x/q.sqlite-wal')
    s.c.host_answer = {'moved': [], 'kept': [], 'pending': []}

    r = run(s, backup=True)

    runs = os.listdir(s.art / 'lab')
    assert r['return'] == 0 and len(runs) == 1 and (s.art / 'lab' / runs[0] / 'w' / 'x' / 'q.sqlite-wal').is_file()


# the host's part: the source it is sent runs by itself

def test_the_host_runs_the_function_from_its_own_source(sync, tmp_path):
    s = sync
    root = tmp_path / 'there'
    make(root, 'w/x/q.sqlite-wal')
    make(root, 'k/a.md')
    s.c.host_answer = None
    s.c._sync_leftovers_on_host(CTX, HOST, {'root': str(root), 'dirs': ['w', 'w/x', 'k'], 'patterns': ['*.sqlite-wal'],
                                            'ignore_case': False, 'quiet': 600, 'dest': str(tmp_path / 'bk')}, False)
    script = s.c.scripts[-1]
    code = script.split("<<'CMETA_SYNC_LEFTOVERS'\n", 1)[1].rsplit('CMETA_SYNC_LEFTOVERS\n', 1)[0]

    p = subprocess.run([sys.executable, '-I', '-'], input=code, capture_output=True, text=True, cwd=str(tmp_path), timeout=60)

    assert p.returncode == 0, p.stderr
    line = [x for x in p.stdout.splitlines() if x.startswith(s.m.LEFTOVERS_MARK)][0]
    got = json.loads(line[len(s.m.LEFTOVERS_MARK):])
    assert [x['dir'] for x in got['moved']] == ['w'] and got['kept'][0]['why'] == 'carried'
    assert (tmp_path / 'bk' / 'w' / 'x' / 'q.sqlite-wal').is_file() and not (root / 'w').exists()


def test_a_powershell_host_gets_the_same_code(sync):
    s = sync
    host = dict(HOST, desc={'access': {'shell': 'powershell'}})
    s.c._sync_leftovers_on_host(CTX, host, {'root': 'C:/x', 'dirs': ['a'] * 5000, 'patterns': [], 'quiet': 600,
                                            'dest': 'C:/b'}, False)

    # the code goes into a file there (no 32 KB command line however many folders), in a here-string it cannot end
    script = s.c.scripts[-1]
    code = script.split("@'\n", 1)[1].rsplit("'@)\n", 1)[0]
    assert script.endswith("& $py @pa $f; $rc = $LASTEXITCODE; Remove-Item -Force $f; exit $rc\n") and len(script) > 32768
    assert script.startswith("$py = ((& cx --version 2>$null) | Where-Object { $_ -match 'cMeta python path' }")
    assert code.isascii() and not any(line.startswith("'@") for line in code.splitlines())
    assert 'def _sync_leftovers(p):' in code and code.rstrip().endswith('))))')
