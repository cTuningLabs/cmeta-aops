"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx host sync asks before it harms (2026-11-17). rclone's bisync renamed both copies of a file changed on both sides
while it worked through its list; a run that aborted there (a file another process held) left four files without
their names on both machines, and the session that ran it saw only the last error. Since then, offline here:

- both sides are looked at BEFORE a run changes anything (_sync_side: this machine in this process, the host by its
  own Python - here a second folder): the files both changed since the pair's last good run and that differ now;
- the ones that lose nothing are settled - a copy that is the beginning of the other or holds its every line, a memory
  index - and the others stop the run with a suggestion each (--resolve decides them; sync_conflicts: newer never
  stops);
- the folders of the run-ai sessions that are open on either side are left out of the run, their markers kept, and
  their entries of the last good run go back into the new listings;
- what a FAILED run renamed is put back, each side its own copy; a file another process holds so that it cannot be
  renamed is left out of the run; the listings of the last good run stay the pair's base (no --resync asked for).

Nothing of the user's cMeta is touched: the engine runs on a home under tmp_path, no host is reached, rclone is not run.
"""
import importlib.util
import json
import logging
import os
import pathlib
import shutil
import socket
import threading
import time

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOST = {'alias': 'far-away', 'uid': 'a8b2c3d4e5f60718', 'type': 'ssh', 'desc': {}, 'state': {}}
NOW = time.time()
BASE = NOW - 4 * 86400                          # the pair's last good run
OLD = BASE - 30 * 86400                         # a file both sides had then


@pytest.fixture(scope='module')
def module():
    spec = importlib.util.spec_from_file_location('category_host_conflicts_under_test', str(REPO_ROOT / 'category' / 'host' / 'api' / 'v1.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def host(tmp_path, monkeypatch, module):
    """The host category on a home of the test; the "host" is the folder tmp_path/there, reached as a host would be:
    its side by _sync_side (as its Python would run it), a file by a copy that keeps its time (rclone copyto)."""
    from cmeta import CMeta
    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX', module.OWN_MARKER_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))
    c = CMeta(home=str(tmp_path / 'home'))
    h = module.Category.__new__(module.Category)
    h.cm = c
    h.cmeta = yaml.safe_load((REPO_ROOT / 'category' / 'host' / '_cmeta.yaml').read_text(encoding='utf-8-sig'))
    h.logger = logging.getLogger('host-conflicts-under-test')
    h._key_cache, h._host_cache, h._adb_batch, h._adb_locks = {}, {}, None, {}
    h._adb_lock = threading.Lock()
    h.copied = []

    monkeypatch.setattr(h, '_on_side', lambda ctx, where, params, verbose=False, timeout=600: module._sync_side(params))

    def rclone(ctx, hh, command, local, remote_path, **kw):
        assert command == 'copyto'
        src, dst = (remote_path, local) if kw.get('from_remote') else (local, remote_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        h.copied.append(('here' if kw.get('from_remote') else 'host', os.path.basename(dst)))
        return {'return': 0, 'output': ''}

    monkeypatch.setattr(h, '_rclone', rclone)
    monkeypatch.setattr(h, '_backup_dirs', lambda hh, name, entry, run_id=None: {
        'return': 0, 'artifact': 'sync-backup--' + name, 'run_id': 'run1', 'here': 'hub', 'cmeta_file': '',
        'local': str(tmp_path / 'backup-here'), 'remote': (tmp_path / 'backup-there').as_posix(), 'remote_artifact': ''})
    monkeypatch.setattr(h, '_backup_mark_remote', lambda *a, **k: {'return': 0})
    return h


def put(root, name, text, when):
    path = pathlib.Path(root, *name.split('/'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8') if isinstance(text, str) else text)
    os.utime(path, (when, when))
    return path


def listing(path, files):
    """A listing of rclone's bisync (v1): what a side held at the pair's last good run."""
    lines = ['# bisync listing v1 from 2026-11-13T19:14:44.000000000+0000']
    for name, (size, when) in sorted(files.items()):
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(when)) + '.%09d+0000' % int((when % 1) * 1e9)
        lines.append('- %8d - - %s "%s"' % (size, stamp, name))
    pathlib.Path(path).write_bytes(('\n'.join(lines) + '\n').encode('utf-8'))
    os.utime(path, (BASE, BASE))


@pytest.fixture()
def pair(tmp_path, host):
    """Two sides and the listings of their last good run: every file given to "both" was the same then."""
    here, there, work = tmp_path / 'repos' / 'fgg', tmp_path / 'there' / 'fgg', tmp_path / 'work'
    for d in (here, there, work):
        d.mkdir(parents=True)
    entry = {'method': 'bisync', 'local': str(here), 'remote': there.as_posix(), 'blacklist': ['tmp*/', '*.sqlite-wal'],
             'workdir': str(work), 'artifacts': []}
    state = {'files': {}}

    def both(name, text, when=OLD):
        for root in (here, there):
            put(root, name, text, when)
        state['files'][name] = (len(text.encode('utf-8')), when)

    def base():
        prefix = host._bisync_pair_prefix(entry) + 'there'
        for side in (1, 2):
            listing(work / f'{prefix}.path{side}.lst', state['files'])

    return {'here': here, 'there': there, 'work': work, 'entry': entry, 'both': both, 'base': base,
            'rules': host._filter_list([], entry['blacklist'])}


def look(host, pair, mode='ask', word='', per=None, sessions=False):
    return host._conflicts_before(None, HOST, 'fgg', pair['entry'], pair['rules'], False, mode, word, per or {}, False,
                                  not sessions, False, False)


# --------------------------------------------------------------------------- one side, looked at

def test_the_files_a_side_changed_lately_by_the_rules_of_the_run(module, tmp_path):
    root = tmp_path / 'r'
    put(root, 'work/a/note.md', 'x', NOW - 10)
    put(root, 'work/a/old.md', 'x', OLD)
    put(root, 'work/a/tmp-build/out.bin', 'x', NOW - 10)                 # a folder the run leaves out: not walked
    put(root, 'work/a/state.sqlite-wal', 'x', NOW - 10)                  # a file the run leaves out
    put(root, 'other/b/note.md', 'x', NOW - 10)                          # outside the selection
    put(root, 'work/b/!AI/log/1.running', '{}', NOW - 10)
    rules = ['+ /work/b/!AI/log/*.running', '- /work/b/**', '- tmp*/**', '- *.sqlite-wal', '+ /work/*/**', '- **']
    r = module._sync_side({'do': 'recent', 'root': str(root), 'rules': rules, 'since': BASE})
    assert sorted(r['files']) == ['work/a/note.md', 'work/b/!AI/log/1.running']
    assert r['files']['work/a/note.md'][0] == 1 and abs(r['files']['work/a/note.md'][1] - (NOW - 10)) < 2
    # the names without their case, as a partial repository is synced
    r = module._sync_side({'do': 'recent', 'root': str(root), 'rules': ['+ /WORK/A/**', '- **'], 'since': BASE, 'ignore_case': True})
    assert sorted(r['files']) == ['work/a/note.md', 'work/a/state.sqlite-wal', 'work/a/tmp-build/out.bin']
    assert 'error' in module._sync_side({'do': 'nothing', 'root': str(root)})


def test_the_sessions_that_are_open_on_a_side(module, tmp_path):
    """A marker of run-ai (<artifact>/!AI/log/<stamp>.running): open when it is of this machine and its process
    lives; where it may write is what it says (areas), else its own folder. A marker written before the process that
    has its number now began is not one: the number was given out again (a marker that outlived its session would
    keep a folder out of every sync)."""
    repos = tmp_path / 'repos'
    me = socket.gethostname().split('.')[0].lower()
    shared = repos / 'fgg' / 'fgg.project' / 'cmeta-aops' / '!AI'
    shared.mkdir(parents=True)

    def marker(repo, item, stamp, **fields):
        d = repos / repo / 'work' / item / '!AI' / 'log'
        d.mkdir(parents=True, exist_ok=True)
        (d / (stamp + '.running')).write_text(json.dumps(dict({'stamp': stamp, 'harness': 'claude', 'host': me, 'pid': os.getpid(),
                                                              'started': '2026-11-17T14:45:47'}, **fields)), encoding='utf-8')
        return str(d / (stamp + '.running'))

    old_style = marker('fgg', 'one', '1')                                  # no areas: its own folder
    marker('fgg', 'two', '2', areas=[str(repos / 'fgg' / 'work' / 'two'), str(shared)])
    marker('other-repo', 'three', '3', areas=[str(repos / 'other-repo' / 'work' / 'three'), str(shared)])
    marker('fgg', 'dead', '4', pid=2 ** 22 + 12345)                        # its process is gone
    marker('fgg', 'elsewhere', '5', host='another-machine')               # a marker a sync brought from another machine
    outlived = marker('fgg', 'outlived', '7')                              # written a day before this process began
    os.utime(outlived, (NOW - 86400, NOW - 86400))
    (repos / 'fgg' / 'work' / 'broken' / '!AI' / 'log').mkdir(parents=True)
    (repos / 'fgg' / 'work' / 'broken' / '!AI' / 'log' / '6.running').write_text('not json', encoding='utf-8')

    ask = {'do': 'recent', 'root': str(repos / 'fgg'), 'rules': [], 'since': NOW + 1, 'sessions': True}
    found = {os.path.basename(s['project']): s for s in module._sync_side(ask)['sessions']}
    assert sorted(found) == ['one', 'three', 'two']
    assert found['one']['under'] == ['work/one']
    assert found['two']['under'] == ['work/two', 'fgg.project/cmeta-aops/!AI']
    assert found['three']['under'] == ['fgg.project/cmeta-aops/!AI']       # its own folder is in another repository
    assert found['one']['harness'] == 'claude' and found['one']['started'] == '2026-11-17T14:45:47'
    # the session that runs the sync is not among them
    own = sorted(os.path.basename(s['project']) for s in module._sync_side(dict(ask, own_marker=old_style))['sessions'])
    assert own == ['three', 'two']
    assert 'sessions' not in module._sync_side(dict(ask, sessions=False))


def test_the_facts_of_a_file(module, tmp_path):
    import hashlib
    root = tmp_path / 'r'
    put(root, 'a/log.jsonl', 'line 1\nline 2\nline 3\n', NOW)
    put(root, 'a/bin.dat', b'\x00\x01\x02', NOW)
    r = module._sync_side({'do': 'facts', 'root': str(root), 'names': ['a/log.jsonl', 'a/bin.dat', 'a/none'],
                           'head': {'a/log.jsonl': 7}, 'text_limit': 100})['facts']
    assert r['a/log.jsonl']['size'] == 21 and r['a/log.jsonl']['text'] == 'line 1\nline 2\nline 3\n'
    assert r['a/log.jsonl']['sha1'] == hashlib.sha1(b'line 1\nline 2\nline 3\n').hexdigest()
    assert r['a/log.jsonl']['head'] == hashlib.sha1(b'line 1\n').hexdigest()          # its first 7 bytes
    assert 'text' not in r['a/bin.dat'] and 'head' not in r['a/bin.dat'] and 'error' in r['a/none']
    assert 'text' not in module._sync_side({'do': 'facts', 'root': str(root), 'names': ['a/log.jsonl'], 'text_limit': 5})['facts']['a/log.jsonl']
    assert 'error' in module._sync_side({'do': 'facts', 'root': str(root), 'names': ['../x']})['facts']['../x']


def test_the_steps_on_a_side(module, tmp_path):
    root = tmp_path / 'r'
    put(root, 'a/x.md', 'mine', OLD)
    r = module._sync_side({'do': 'apply', 'root': str(root), 'steps': [
        {'op': 'copy', 'from': 'a/x.md', 'to': str(tmp_path / 'backup' / 'a' / 'x.md')},
        {'op': 'move', 'from': 'a/x.md', 'to': 'a/x.md.conflict1'},
        {'op': 'restore', 'from': 'a/x.md.conflict1', 'to': 'a/x.md'},             # its own copy back under its name
        {'op': 'restore', 'from': 'a/gone.conflict1', 'to': 'a/gone'},             # nothing there: nothing done
    ]})
    assert r == {'done': 4, 'changed': 3}
    assert (root / 'a' / 'x.md').read_text() == 'mine' and not (root / 'a' / 'x.md.conflict1').exists()
    assert abs(os.path.getmtime(tmp_path / 'backup' / 'a' / 'x.md') - OLD) < 2            # a copy keeps the time
    # a rename that was a copy (the delete failed): the name is there, the copy goes; a copy the other side gave goes
    # only when the name is there
    put(root, 'a/x.md.conflict1', 'mine', OLD)
    put(root, 'a/y.md.conflict2', 'theirs', OLD)
    r = module._sync_side({'do': 'apply', 'root': str(root), 'steps': [
        {'op': 'restore', 'from': 'a/x.md.conflict1', 'to': 'a/x.md'}, {'op': 'drop', 'from': 'a/x.md.conflict1', 'to': 'a/x.md'},
        {'op': 'drop', 'from': 'a/y.md.conflict2', 'to': 'a/y.md'}]})
    assert r['changed'] == 1 and sorted(os.listdir(root / 'a')) == ['x.md', 'y.md.conflict2']
    assert 'error' in module._sync_side({'do': 'apply', 'root': str(root), 'steps': [{'op': 'remove', 'from': '../outside'}]})


# --------------------------------------------------------------------------- the helpers

def test_the_rules_are_the_ones_the_run_gives_rclone(host, task_namespace):
    """_filter_list reads the two lists as the task rclone-to-ssh does: one order, one meaning."""
    task = task_namespace('rclone-to-ssh')['CTask']
    t = task.__new__(task)
    for white, black in (([], ['tmp*/', '.git/', '*.sqlite-wal']), (['/work/*/**', '/_cmr.yaml'], ['tmp*/', 'a/!Arc/']), ([], [])):
        assert host._filter_list(white, black) == t._filter_rules(white, None, black, None)['rules']
    assert host._filter_list(['/work/*/**'], ['tmp*/']) == ['- tmp*/**', '+ /work/*/**', '- **']


def test_a_listing_of_the_last_good_run_is_read(host, tmp_path):
    assert host._listing_time('2026-11-17T13:17:28.597684600+0000') == pytest.approx(1794921448.5976846, abs=1e-3)
    assert host._listing_time('2026-11-17T14:17:28+0100') == pytest.approx(1794921448, abs=1e-3)
    assert host._listing_time('2026-11-17T13:17:28Z') == pytest.approx(1794921448, abs=1e-3)
    assert host._listing_time('yesterday') is None
    lst = tmp_path / 'x.path1.lst'
    lst.write_bytes(b'# bisync listing v1 from 2026-11-17T14:40:48.919842900+0000\n'
                    b'-        7 - - 2026-11-17T13:17:28.597684600+0000 "doc.md"\n'
                    b'-       23 - - 2026-11-17T13:17:28.000000000+0000 "sub/a name with spaces.txt"\n'
                    b'-        2 - - 2026-11-17T13:17:28.000000000+0000 "a\\u00a0b.md"\n')
    got = host._base_entries(str(lst), {'doc.md', 'sub/a name with spaces.txt', 'a b.md', 'not-there'})
    assert got['doc.md'][0] == 7 and got['doc.md'][1] == pytest.approx(1794921448.5976846, abs=1e-3)
    assert set(got) == {'doc.md', 'sub/a name with spaces.txt', 'a b.md'}
    assert host._base_entries(str(lst), set()) == {}


def test_the_rules_that_leave_a_session_s_folders_out(host):
    assert host._area_rules(['work/2026 [a] {b}', 'fgg.project/cmeta-aops/!AI']) == [
        '+ /work/2026 \\[a\\] \\{b\\}/!AI/log/*.running', '- /work/2026 \\[a\\] \\{b\\}/**',     # its marker travels
        '- /fgg.project/cmeta-aops/!AI/**']
    assert host._area_rules(['']) == ['+ /**/!AI/log/*.running', '- /**']                     # a whole repository
    assert host._area_rules([]) == []


def test_two_copies_compared(host):
    def fact(text, when, head=None):
        import hashlib
        data = text.encode('utf-8')
        f = {'size': len(data), 'mtime': when, 'sha1': hashlib.sha1(data).hexdigest(), 'text': text}
        if head is not None:
            f['head'] = hashlib.sha1(data[:head]).hexdigest()
        return f

    c = host._compare_copies('a/log.jsonl', fact('1\n2\n3\n', NOW, head=4), fact('1\n2\n', NOW - 900))
    assert (c['kind'], c['safe'], c['suggested']) == ('here-extends', True, 'here')
    c = host._compare_copies('a/log.jsonl', fact('1\n2\n', NOW - 900), fact('1\n2\n3\n', NOW, head=4))
    assert (c['kind'], c['safe'], c['suggested']) == ('host-extends', True, 'host')
    c = host._compare_copies('a/notes.md', fact('b\na\nc\n', NOW - 900), fact('a\nb\n', NOW))
    assert (c['kind'], c['safe'], c['suggested']) == ('here-holds', True, 'here') and '1 more' in c['why']
    c = host._compare_copies('a/notes.md', fact('a\nmine\n', NOW - 900), fact('a\ntheirs\n', NOW))
    assert (c['kind'], c['safe'], c['suggested']) == ('differ', False, 'host')
    assert (c['only_here'], c['only_host']) == (1, 1) and "the host's copy is newer by 15m" in c['why']
    c = host._compare_copies('x/!AI/memory/MEMORY.md', fact('- [A](a.md) - x\n', NOW), fact('- [B](b.md) - y\n', NOW - 5))
    assert (c['kind'], c['safe'], c['suggested']) == ('index', True, 'merge')
    assert host._compare_copies('a/x', fact('same', NOW), fact('same', NOW - 5))['kind'] == 'equal'
    binary = {'size': 9, 'mtime': NOW, 'sha1': 'a' * 40}
    c = host._compare_copies('a/x.sqlite', binary, {'size': 9, 'mtime': NOW - 60, 'sha1': 'b' * 40})
    assert (c['kind'], c['safe'], c['suggested']) == ('differ', False, 'here') and 'not a text' in c['why']


def test_how_resolve_is_read(host, tmp_path):
    assert host._resolve_choices(None) == ('', {}, '') and host._resolve_choices('Suggested') == ('suggested', {}, '')
    assert host._resolve_choices({'a/b.md': 'here', 'c.md': ''}) == ('', {'a/b.md': 'here'}, '')
    f = tmp_path / 'choices.json'
    f.write_text(json.dumps({'conflicts': [{'path': 'a/b.md', 'choice': 'host'}, {'path': 'c.md', 'choice': ''}]}), encoding='utf-8')
    assert host._resolve_choices(str(f)) == ('', {'a/b.md': 'host'}, '')
    assert 'is not one of' in host._resolve_choices({'a/b.md': 'theirs'})[2]
    assert 'is neither' in host._resolve_choices('whatever')[2]
    f.write_text('not json', encoding='utf-8')
    assert 'cannot be read' in host._resolve_choices(str(f))[2]


# --------------------------------------------------------------------------- the look before a run

def test_nothing_to_ask_when_one_side_alone_changed_or_both_to_the_same(host, pair):
    pair['both']('work/a/one.md', 'base\n')
    pair['both']('work/a/same.md', 'base\n')
    pair['both']('work/a/copied.md', 'base\n')
    pair['base']()
    put(pair['here'], 'work/a/one.md', 'base\nchanged here\n', NOW - 100)                 # this machine alone
    for root in (pair['here'], pair['there']):
        put(root, 'work/a/copied.md', 'base\nnew\n', NOW - 200)                           # an interrupted run copied it
    put(pair['here'], 'work/a/same.md', 'base\nsame change\n', NOW - 300)
    put(pair['there'], 'work/a/same.md', 'base\nsame change\n', NOW - 250)                # the same bytes, another time
    put(pair['here'], 'work/a/new.md', 'new here\n', NOW - 50)
    r = look(host, pair)
    assert r['conflicts'] == [] and r['plan'] == [] and r['note'] == '' and r['sessions'] == []


def test_no_listings_of_a_good_run_nothing_to_compare_with(host, pair):
    put(pair['here'], 'work/a/x.md', 'here\n', NOW - 100)
    put(pair['there'], 'work/a/x.md', 'there\n', NOW - 50)
    r = look(host, pair)
    assert r['conflicts'] == [] and 'no listings of a last good run' in r['note']


def test_the_listings_an_abort_renamed_are_the_base(host, pair):
    """12:58 on 2026-11-17: the pair's listings were .lst-err after the abort - they are its base, put back."""
    pair['both']('work/a/x.md', 'base\n')
    pair['base']()
    for f in list(pair['work'].iterdir()):
        f.rename(str(f) + '-err')
    put(pair['here'], 'work/a/x.md', 'base\nhere\n', NOW - 100)
    put(pair['there'], 'work/a/x.md', 'base\nthere\n', NOW - 50)
    r = look(host, pair)
    assert [c['path'] for c in r['conflicts']] == ['work/a/x.md'] and r['note'] == ''
    assert sorted(f.name[-10:] for f in pair['work'].iterdir()) == ['.path1.lst', '.path2.lst']


def stale_copies(pair):
    """What an interrupted run leaves: older copies of this machine's files on the host, both changed since the base."""
    pair['both']('work/a/!AI/sessions/s.jsonl', '{"n": 1}\n')
    pair['both']('work/a/notes.md', '# notes\none\n')
    pair['both']('work/a/!AI/memory/MEMORY.md', '- [One](one.md) - first\n')
    pair['both']('work/a/desc.yaml', 'name: a\nstate: old\n')
    pair['both']('work/a/tmp-x/skip.md', 'left out by the rules\n')
    pair['base']()
    put(pair['there'], 'work/a/!AI/sessions/s.jsonl', '{"n": 1}\n{"n": 2}\n', NOW - 3000)
    put(pair['here'], 'work/a/!AI/sessions/s.jsonl', '{"n": 1}\n{"n": 2}\n{"n": 3}\n', NOW - 100)   # it went on growing
    put(pair['there'], 'work/a/notes.md', '# notes\none\ntwo\n', NOW - 3000)
    put(pair['here'], 'work/a/notes.md', '# notes\nzero\none\ntwo\nthree\n', NOW - 100)       # every line of the other
    put(pair['here'], 'work/a/!AI/memory/MEMORY.md', '- [One](one.md) - first\n- [Two](two.md) - here\n', NOW - 100)
    put(pair['there'], 'work/a/!AI/memory/MEMORY.md', '- [One](one.md) - first\n- [Three](three.md) - there\n', NOW - 50)
    put(pair['here'], 'work/a/desc.yaml', 'name: a\nstate: here\n', NOW - 100)
    put(pair['there'], 'work/a/desc.yaml', 'name: a\nstate: there\n', NOW - 50)              # a line each: a real conflict
    put(pair['here'], 'work/a/tmp-x/skip.md', 'here\n', NOW - 100)
    put(pair['there'], 'work/a/tmp-x/skip.md', 'there\n', NOW - 50)


def test_the_safe_ones_are_planned_and_the_others_wait(host, pair):
    stale_copies(pair)
    r = look(host, pair)
    assert [c['path'] for c in r['conflicts']] == ['work/a/desc.yaml']                    # the run must not start
    c = r['conflicts'][0]
    assert (c['kind'], c['suggested'], c['safe']) == ('differ', 'host', False)
    assert c['here']['size'] == 20 and c['host']['size'] == 21 and '1 line(s) only here, 1 only on the host' in c['why']
    plan = {c['path']: (c['kind'], choice) for c, choice in r['plan']}
    assert plan == {'work/a/!AI/sessions/s.jsonl': ('here-extends', 'here'), 'work/a/notes.md': ('here-holds', 'here'),
                    'work/a/!AI/memory/MEMORY.md': ('index', 'merge')}
    # nothing was changed by the look
    assert (pair['there'] / 'work' / 'a' / 'notes.md').read_text() == '# notes\none\ntwo\n'

    # ask-all: the safe ones wait too
    assert len(look(host, pair, mode='ask-all')['conflicts']) == 4
    # newer: the one without a safe answer is left to rclone's own rule, the safe ones are still planned
    r = look(host, pair, mode='newer')
    assert r['conflicts'] == [] and r['to_rclone'] == 1 and len(r['plan']) == 3


def test_resolve_decides_the_ones_that_wait(host, pair):
    stale_copies(pair)
    r = look(host, pair, word='suggested')
    assert r['conflicts'] == [] and dict((c['path'], ch) for c, ch in r['plan'])['work/a/desc.yaml'] == 'host'
    # a word decides the ones that wait; one that loses nothing is settled as without the word (the index merged)
    r = look(host, pair, word='host')
    plan = dict((c['path'], ch) for c, ch in r['plan'])
    assert plan == {'work/a/desc.yaml': 'host', 'work/a/!AI/sessions/s.jsonl': 'here', 'work/a/notes.md': 'here',
                    'work/a/!AI/memory/MEMORY.md': 'merge'}
    r = look(host, pair, word='later')
    assert r['later'] == ['work/a/desc.yaml'] and len(r['plan']) == 3 and r['conflicts'] == []
    # ask-all showed every one: the word is for every one, the index too
    r = look(host, pair, mode='ask-all', word='here')
    assert {ch for c, ch in r['plan']} == {'here'} and len(r['plan']) == 4
    r = look(host, pair, word='newer')
    assert dict((c['path'], ch) for c, ch in r['plan'])['work/a/desc.yaml'] == 'host'
    r = look(host, pair, per={'work/a/desc.yaml': 'both'})
    assert r['conflicts'] == [] and dict((c['path'], ch) for c, ch in r['plan'])['work/a/desc.yaml'] == 'both'
    r = look(host, pair, per={'work/a/desc.yaml': 'later'})
    assert r['conflicts'] == [] and r['later'] == ['work/a/desc.yaml'] and len(r['plan']) == 3
    # "merge" is a choice for a memory index only
    r = look(host, pair, per={'work/a/desc.yaml': 'merge'})
    assert [c['path'] for c in r['conflicts']] == ['work/a/desc.yaml']


def test_the_plan_is_applied_and_what_it_replaces_is_kept(host, pair, tmp_path):
    stale_copies(pair)
    r = look(host, pair, per={'work/a/desc.yaml': 'host'})
    notes, failed = host._settle_conflicts(None, HOST, 'fgg', pair['entry'], r['plan'], False, False)
    assert failed == {} and len(notes) == 4

    def both(name):
        a, b = pair['here'].joinpath(*name.split('/')), pair['there'].joinpath(*name.split('/'))
        assert a.read_bytes() == b.read_bytes() and abs(os.path.getmtime(a) - os.path.getmtime(b)) < 2, name
        return a.read_text(encoding='utf-8')

    assert both('work/a/!AI/sessions/s.jsonl') == '{"n": 1}\n{"n": 2}\n{"n": 3}\n'
    assert both('work/a/notes.md') == '# notes\nzero\none\ntwo\nthree\n'
    assert both('work/a/desc.yaml') == 'name: a\nstate: there\n'
    assert both('work/a/!AI/memory/MEMORY.md') == '- [One](one.md) - first\n- [Two](two.md) - here\n- [Three](three.md) - there\n'
    # the copies that were replaced, each on its own side
    assert (tmp_path / 'backup-there' / 'work' / 'a' / 'notes.md').read_text() == '# notes\none\ntwo\n'
    assert (tmp_path / 'backup-here' / 'work' / 'a' / 'desc.yaml').read_text() == 'name: a\nstate: here\n'
    assert (tmp_path / 'backup-here' / 'work' / 'a' / '!AI' / 'memory' / 'MEMORY.md').is_file()
    assert (tmp_path / 'backup-there' / 'work' / 'a' / '!AI' / 'memory' / 'MEMORY.md').is_file()
    # the next look finds nothing: both sides hold the same files with the same times
    r = look(host, pair)
    assert r['conflicts'] == [] and r['plan'] == []


def test_keep_both_the_newer_under_the_name(host, pair):
    stale_copies(pair)
    r = look(host, pair, per={'work/a/desc.yaml': 'both'})
    plan = [(c, ch) for c, ch in r['plan'] if ch == 'both']
    notes, failed = host._settle_conflicts(None, HOST, 'fgg', pair['entry'], plan, False, False)
    assert failed == {}
    for root in (pair['here'], pair['there']):
        assert (root / 'work' / 'a' / 'desc.yaml').read_text() == 'name: a\nstate: there\n'           # the newer
        assert (root / 'work' / 'a' / 'desc.yaml.conflict1').read_text() == 'name: a\nstate: here\n'


def test_a_copy_that_cannot_be_put_is_left_out_of_the_run(host, pair, monkeypatch):
    stale_copies(pair)
    r = look(host, pair, word='suggested')
    monkeypatch.setattr(host, '_rclone', lambda *a, **k: {'return': 1, 'error': 'rclone copyto returned 1: permission denied'})
    notes, failed = host._settle_conflicts(None, HOST, 'fgg', pair['entry'], r['plan'], False, False)
    assert notes == [] and len(failed) == 4 and set(failed.values()) == {'rclone copyto returned 1: permission denied'}
    # a file another process holds says so in a few words, whatever the length of rclone's own line
    held = ('rclone copyto returned 1: Attempt 3/3 failed with 1 errors and: rename ' + 'x' * 300
            + ': The process cannot access the file because it is being used by another process.')
    monkeypatch.setattr(host, '_rclone', lambda *a, **k: {'return': 1, 'error': held})
    notes, failed = host._settle_conflicts(None, HOST, 'fgg', pair['entry'], r['plan'], False, False)
    assert notes == [] and set(failed.values()) == {'another process holds the file'}


def test_the_folders_of_open_sessions_are_left_out(host, pair, tmp_path):
    """A session open here on work/a: its folder is not looked at for conflicts and is left out of the run, its
    marker kept; a session of the host on work/b likewise (its marker says the path as it is there)."""
    stale_copies(pair)
    pair['both']('work/b/x.md', 'base\n')
    pair['base']()
    put(pair['here'], 'work/b/x.md', 'base\nhere\n', NOW - 100)
    put(pair['there'], 'work/b/x.md', 'base\nthere\n', NOW - 50)
    me = socket.gethostname().split('.')[0].lower()
    for root, item in ((pair['here'], 'a'), (pair['there'], 'b')):
        log = root / 'work' / item / '!AI' / 'log'
        log.mkdir(parents=True, exist_ok=True)
        (log / '20261117-144547.running').write_text(json.dumps({'harness': 'claude', 'host': me, 'pid': os.getpid(),
                                                                 'started': '2026-11-17T14:45:47'}), encoding='utf-8')
    r = look(host, pair, sessions=True)
    assert r['conflicts'] == [] and r['plan'] == []                               # everything that differs is theirs
    assert sorted((s['where'], s['under'][0]) for s in r['sessions']) == [('far-away', 'work/b'), ('here', 'work/a')]
    assert r['rules_first'] == ['+ /work/a/!AI/log/*.running', '- /work/a/**', '+ /work/b/!AI/log/*.running', '- /work/b/**']
    # --include_sessions: none is left out
    r = look(host, pair, sessions=False)
    assert r['sessions'] == [] and r['rules_first'] == [] and len(r['conflicts']) == 2


def test_the_stop_is_kept_for_a_page_and_for_resolve(host, pair):
    stale_copies(pair)
    r = look(host, pair)
    path = host._remember_conflicts(HOST, 'fgg', pair['entry'], r['conflicts'])
    data = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    assert data['host'] == 'far-away' and data['repository'] == 'fgg' and data['choices'] == ['here', 'host', 'both', 'later']
    assert [(c['path'], c['suggested'], c['choice']) for c in data['conflicts']] == [('work/a/desc.yaml', 'host', '')]
    # filled in, the file is what --resolve takes
    data['conflicts'][0]['choice'] = 'here'
    pathlib.Path(path).write_text(json.dumps(data), encoding='utf-8')
    assert host._resolve_choices(path) == ('', {'work/a/desc.yaml': 'here'}, '')
    assert host._remember_conflicts(HOST, 'fgg', pair['entry'], []) == '' and not os.path.exists(path)
    text = host._conflict_text(r['conflicts'][0], 1, 1, 'far-away / fgg')
    assert text[0] == 'CONFLICT 1 of 1 (far-away / fgg): work/a/desc.yaml' and "keep the host's" in text[3]


# --------------------------------------------------------------------------- after a run

ABORT = '''2026/11/17 12:58:02 NOTICE: - WARNING           New or changed in both paths                - mem/MEMORY.md
2026/11/17 12:58:02 NOTICE: - Path1             Renaming Path1 copy                         - {here}\\mem/MEMORY.md.conflict1
2026/11/17 12:58:02 INFO  : mem/MEMORY.md: Moved (server-side) to: mem/MEMORY.md.conflict1
2026/11/17 12:58:02 NOTICE: - Path1             Queue copy to Path2                         - :sftp{{-4u0A}}:{there}/mem/MEMORY.md.conflict1
2026/11/17 12:58:02 NOTICE: - Path2             Renaming Path2 copy                         - :sftp{{-4u0A}}:{there}/mem/MEMORY.md.conflict2
2026/11/17 12:58:02 INFO  : mem/MEMORY.md: Moved (server-side) to: mem/MEMORY.md.conflict2
2026/11/17 12:58:02 NOTICE: - Path2             Queue copy to Path1                         - {here}\\mem/MEMORY.md.conflict2
2026/11/17 12:58:03 NOTICE: - WARNING           New or changed in both paths                - codex/logs_2.sqlite
2026/11/17 12:58:03 NOTICE: - Path1             Renaming Path1 copy                         - {here}\\codex/logs_2.sqlite.conflict1
2026/11/17 12:58:03 INFO  : codex/logs_2.sqlite: Copied (new) to: codex/logs_2.sqlite.conflict1
2026/11/17 12:58:04 ERROR : codex/logs_2.sqlite: Couldn't delete: remove \\\\?\\{here}\\codex\\logs_2.sqlite: The process cannot access the file because it is being used by another process.
2026/11/17 12:58:04 ERROR : Bisync critical error: {here}\\ rename failed for {here}\\codex/logs_2.sqlite: remove \\\\?\\{here}\\codex\\logs_2.sqlite: The process cannot access the file because it is being used by another process.
2026/11/17 12:58:04 ERROR : Bisync aborted. Must run --resync to recover.
'''


def test_what_a_failed_run_renamed_is_put_back(host, pair):
    """The lines of 12:58 on 2026-11-17: MEMORY.md renamed on both machines, a database held by a daemon copied
    but not deleted, the abort."""
    here, there = pair['here'], pair['there']
    put(here, 'mem/MEMORY.md.conflict1', 'the hub\'s index\n', NOW - 100)        # renamed: the name is gone here
    put(there, 'mem/MEMORY.md.conflict2', 'the host\'s index\n', NOW - 900)      # and there
    put(here, 'codex/logs_2.sqlite', 'held', NOW - 100)                          # a copy was made, the delete failed
    put(here, 'codex/logs_2.sqlite.conflict1', 'held', NOW - 100)
    put(there, 'codex/logs_2.sqlite', 'theirs', NOW - 900)
    text = ABORT.format(here=str(here), there=there.as_posix())
    assert host._renamed(pair['entry'], text) == [(1, 'mem/MEMORY.md.conflict1', 'mem/MEMORY.md'),
                                                  (2, 'mem/MEMORY.md.conflict2', 'mem/MEMORY.md'),
                                                  (1, 'codex/logs_2.sqlite.conflict1', 'codex/logs_2.sqlite')]
    assert host._undo_renames(None, HOST, pair['entry'], text, False, False) == 3
    assert (here / 'mem' / 'MEMORY.md').read_text() == 'the hub\'s index\n'
    assert (there / 'mem' / 'MEMORY.md').read_text() == 'the host\'s index\n'
    assert sorted(os.listdir(here / 'mem')) == ['MEMORY.md'] and sorted(os.listdir(there / 'mem')) == ['MEMORY.md']
    assert sorted(os.listdir(here / 'codex')) == ['logs_2.sqlite']               # the stray copy is gone
    assert host._undo_renames(None, HOST, pair['entry'], text, False, False) == 0        # once is enough


def test_a_copy_already_carried_to_the_other_side_goes_too(host, pair):
    here, there = pair['here'], pair['there']
    put(here, 'mem/MEMORY.md.conflict1', 'the hub\'s\n', NOW - 100)
    put(here, 'mem/MEMORY.md.conflict2', 'the host\'s\n', NOW - 900)             # the run had copied it here already
    put(there, 'mem/MEMORY.md.conflict2', 'the host\'s\n', NOW - 900)
    put(there, 'mem/MEMORY.md.conflict1', 'the hub\'s\n', NOW - 100)
    text = ABORT.format(here=str(here), there=there.as_posix())
    host._undo_renames(None, HOST, pair['entry'], text, False, False)
    assert os.listdir(here / 'mem') == ['MEMORY.md'] and os.listdir(there / 'mem') == ['MEMORY.md']
    assert (here / 'mem' / 'MEMORY.md').read_text() == 'the hub\'s\n' and (there / 'mem' / 'MEMORY.md').read_text() == 'the host\'s\n'


def test_a_held_file_is_its_own_kind_of_failure(host, pair):
    text = ABORT.format(here=str(pair['here']), there=pair['there'].as_posix())
    assert host._held_files(text) == ['codex/logs_2.sqlite']
    assert host._bisync_failure(text) == ('held', ['codex/logs_2.sqlite'])
    # a file that could not be read stays what it was, and a pair without listings too
    assert host._bisync_failure('ERROR : a.db: Failed to copy: read /r/a.db: locked\nMust run --resync')[0] == 'unreadable'
    assert host._bisync_failure('ERROR : Bisync critical error: cannot find prior Path1 or Path2 listings\nMust run --resync')[0] == 'needs-resync'


def test_a_name_taken_from_both_sides_is_put_back(host, pair):
    """Equal times and different bytes: rclone finds no newer copy and renames both, in a run that succeeds."""
    here, there = pair['here'], pair['there']
    for root in (here, there):
        put(root, 'doc.md.conflict1', 'the hub\'s\n', NOW - 300)
        put(root, 'doc.md.conflict2', 'the host\'s\n', NOW - 300)
    text = ('NOTICE: - Path1             Renaming Path1 copy                         - %s\\doc.md.conflict1\n'
            'NOTICE: - Path2             Renaming Path2 copy                         - :sftp{x}:%s/doc.md.conflict2\n'
            % (here, there.as_posix()))
    assert host._names_back(None, HOST, pair['entry'], text, False, False) == ['doc.md']
    for root in (here, there):
        assert (root / 'doc.md').read_text() == 'the hub\'s\n' and len(os.listdir(root)) == 3
    # with a newer copy the name was never gone: nothing to do
    one = 'NOTICE: - Path1             Renaming Path1 copy                         - %s\\other.md.conflict1\n' % here
    assert host._names_back(None, HOST, pair['entry'], one, False, False) == []


def test_the_entries_of_a_folder_left_out_go_back_into_the_listings(host, tmp_path):
    """A run without the folder of an open session lists none of its files; their entries of the last good run go
    back, so that each is one ordinary change at the next run - not new on both sides. A marker that travelled is
    listed already and is not doubled."""
    old = (b'# bisync listing v1 from 2026-11-13T19:14:44.000000000+0000\n'
           b'-        5 - - 2026-11-01T10:00:00.000000000+0000 "work/a/notes.md"\n'
           b'-        7 - - 2026-11-01T10:00:00.000000000+0000 "work/a/!AI/log/1.running"\n'
           b'-        9 - - 2026-11-01T10:00:00.000000000+0000 "work/ab/other.md"\n'
           b'-        3 - - 2026-11-01T10:00:00.000000000+0000 "work/b/x.md"\n'
           b'-        4 - - 2026-11-01T10:00:00.000000000+0000 "later.md"\n')
    new = (b'# bisync listing v1 from 2026-11-17T19:14:44.000000000+0000\n'
           b'-        8 - - 2026-11-17T10:00:00.000000000+0000 "work/a/!AI/log/1.running"\n'
           b'-        9 - - 2026-11-01T10:00:00.000000000+0000 "work/ab/other.md"\n'
           b'-        3 - - 2026-11-01T10:00:00.000000000+0000 "work/b/x.md"\n')
    lst = tmp_path / 'p.path1.lst'
    lst.write_bytes(new)
    assert host._entries_back({str(lst): old}, ['later.md'], prefixes=['work/a']) == 2
    lines = lst.read_bytes().split(b'\n')
    assert b'-        5 - - 2026-11-01T10:00:00.000000000+0000 "work/a/notes.md"' in lines
    assert b'-        4 - - 2026-11-01T10:00:00.000000000+0000 "later.md"' in lines
    assert sum(1 for l in lines if b'1.running' in l) == 1 and b'\r' not in lst.read_bytes()
    assert sum(1 for l in lines if b'work/ab/other.md' in l) == 1                # "work/a" is not "work/ab"
    # a whole repository left out: every entry the new listing lacks
    lst.write_bytes(b'# header\n')
    assert host._entries_back({str(lst): old}, [], prefixes=['']) == 5


def test_the_state_of_a_host_s_syncs_for_the_list(host, pair, monkeypatch):
    entries = {'fgg': pair['entry'], 'aops': dict(pair['entry'])}
    monkeypatch.setattr(host, '_sync_entries', lambda h: entries)
    assert host._sync_state(HOST) == ('-', {})                                   # nothing synced from here yet
    selected = list(entries.items())
    host._remember_sync(HOST, selected, [], True)
    text, facts = host._sync_state(HOST)
    assert text.startswith('ok ') and facts['ok'] and facts['failed'] == []
    # one repository stopped at conflicts, the other went well: the one that is apart is named with its last good run
    host._remember_sync(HOST, selected, ['far-away / fgg: 3 file(s) changed on both sides and different now - nothing was changed'], True)
    text, facts = host._sync_state(HOST)
    assert text.startswith('! fgg (ok ') and not facts['ok'] and facts['failed'][0]['repository'] == 'fgg'
    assert '3 file(s) changed on both sides' in facts['failed'][0]['problem']
    rec = json.loads((pair['work'] / 'cmeta-sync.json').read_text(encoding='utf-8'))
    assert rec['repos']['aops']['ok'] and not rec['repos']['fgg']['ok'] and rec['repos']['fgg']['ok_time']
    # a record of before: the host's last run as a whole
    (pair['work'] / 'cmeta-sync.json').write_text(json.dumps({'last': {'ok': False, 'time': '2026-11-17 12:58:04', 'repos': ['fgg'],
                                                              'problems': ['x']}, 'last_ok': {'time': '2026-11-13 20:09:53'}}), encoding='utf-8')
    assert host._sync_state(HOST)[0] == '! fgg (ok 11-13 20:09)'


def test_how_a_conflict_is_met_comes_from_the_command_then_the_config(host, monkeypatch):
    assert host._sync_conflicts_mode('Newer') == 'newer' and host._sync_conflicts_mode(None) == 'ask'
    monkeypatch.setattr(host.cm, 'access', lambda ii: {'return': 0, 'config_cmeta': {'sync_conflicts': 'newer'}})
    assert host._sync_conflicts_mode('') == 'newer' and host._sync_conflicts_mode('ask-all') == 'ask-all'


# --------------------------------------------------------------------------- the run that goes on, or does not start

def robust(host, pair, answers, **more):
    """The robust sync over a _sync_repo that answers from a list (an answer may be a function of the call)."""
    seen = []

    def fake_sync_repo(ctx, h, name, entry, **kw):
        seen.append(dict(kw))
        answer = answers.pop(0)
        return dict(answer(kw) if callable(answer) else answer)

    host._sync_repo = fake_sync_repo
    host._remote_empty = lambda ctx, h, entry: False
    host._long_names = lambda h, name, entry: []
    r = host._sync_repo_robust({}, HOST, 'fgg', pair['entry'], resync=False, resync_mode='newer', unlock=False, dry_run=False,
                               con=False, verbose=False, backup=False, retries=2, **more)
    return r, seen


def test_a_failed_run_leaves_no_name_missing_and_goes_on_without_the_held_file(host, pair):
    here, there, work = pair['here'], pair['there'], pair['work']
    pair['both']('mem/MEMORY.md', 'base\n')
    pair['both']('codex/logs_2.sqlite', 'base')
    pair['base']()
    for f in list(work.iterdir()):
        f.rename(str(f) + '-err')                                         # as rclone leaves them after its abort
    os.remove(here / 'mem' / 'MEMORY.md')
    os.remove(there / 'mem' / 'MEMORY.md')
    put(here, 'mem/MEMORY.md.conflict1', 'the index of the hub\n', NOW - 100)
    put(there, 'mem/MEMORY.md.conflict2', 'the index of the host\n', NOW - 900)
    put(here, 'codex/logs_2.sqlite.conflict1', 'held', NOW - 100)
    text = ABORT.format(here=str(here), there=there.as_posix())
    r, seen = robust(host, pair, [{'return': 1, 'error': 'rclone bisync returned 7: Bisync aborted. Must run --resync to recover.',
                                   'output': text}, {'return': 0, 'output': ''}])
    assert r['return'] == 0 and len(seen) == 2
    assert seen[1]['exclude'] == ['/codex/logs_2.sqlite'] and r['skipped'] == ['codex/logs_2.sqlite']
    assert r['notes'][0] == '3 name(s) the stopped run had renamed put back'
    assert 'another process holds' in r['notes'][1] and 'codex/logs_2.sqlite' in r['notes'][1]
    assert (here / 'mem' / 'MEMORY.md').is_file() and (there / 'mem' / 'MEMORY.md').is_file()
    assert sorted(f.name[-10:] for f in work.iterdir() if '.lst' in f.name) == ['.path1.lst', '.path2.lst']      # the base is back
    assert b'"codex/logs_2.sqlite"' in next(work.glob('*.path1.lst')).read_bytes()


def test_a_run_rclone_stopped_asks_for_no_resync_when_the_pair_has_its_base(host, pair):
    pair['both']('a.md', 'base\n')
    pair['base']()
    for f in list(pair['work'].iterdir()):
        f.rename(str(f) + '-err')
    said = 'ERROR : Bisync critical error: something new\nERROR : Bisync aborted. Must run --resync to recover.\n'
    r, seen = robust(host, pair, [{'return': 1, 'error': 'rclone bisync returned 7: Bisync aborted. Must run --resync to recover.',
                                   'output': said}])
    assert r['return'] == 1 and len(seen) == 1
    assert 'nothing needs a --resync' in r['error'] and '--resync_mode' not in r['error']
    assert sorted(f.name[-10:] for f in pair['work'].iterdir()) == ['.path1.lst', '.path2.lst']


def test_a_run_without_the_folders_of_open_sessions_keeps_their_base(host, pair):
    pair['both']('work/a/notes.md', 'base\n')
    pair['both']('work/b/x.md', 'base\n')
    pair['both']('later.md', 'base\n')
    pair['base']()

    def run(kw):
        # rclone writes new listings without what the rules left out
        for lst in pair['work'].glob('*.lst'):
            keep = [l for l in lst.read_bytes().split(b'\n') if b'work/a/' not in l and b'later.md' not in l]
            lst.write_bytes(b'\n'.join(keep))
        return {'return': 0, 'output': ''}

    r, seen = robust(host, pair, [run], rules_first=['- /work/a/**'], later=['later.md'], areas=['work/a'])
    assert r['return'] == 0
    assert seen[0]['rules_first'] == ['- /work/a/**'] and seen[0]['exclude'] == ['/later.md']
    for lst in pair['work'].glob('*.lst'):
        names = lst.read_bytes()
        assert b'"work/a/notes.md"' in names and b'"later.md"' in names and b'"work/b/x.md"' in names


def run_sync(host, pair, monkeypatch, **kw):
    """cx host sync of one host with one repository, its run and its check stand-ins."""
    h = dict(HOST, status='up', desc={'sync': {}})
    runs = []

    def fake_robust(ctx, hh, name, entry, **k):
        runs.append(k)
        return {'return': 0, 'notes': [], 'moved': {}, 'both_sides': []}

    monkeypatch.setattr(host, '_select', lambda ctx, *a, **k: {'return': 0, 'hosts': [h]})
    monkeypatch.setattr(host, '_is_explicit', lambda arg1, hosts: True)
    monkeypatch.setattr(host, '_status_all', lambda ctx, hosts, **k: None)
    monkeypatch.setattr(host, '_sync_entries', lambda hh: {'fgg': pair['entry']})
    monkeypatch.setattr(host, '_usable', lambda hh: True)
    monkeypatch.setattr(host, '_sync_repo_robust', fake_robust)
    monkeypatch.setattr(host, '_check_repo', lambda *a, **k: {'ok': True, 'errors': 0, 'equal': 5, 'conflicts': []})
    monkeypatch.setattr(host, '_refresh_state', lambda *a, **k: None)
    monkeypatch.setattr(host, '_remember_index_bases', lambda *a, **k: 0)
    r = host.sync_({'control': {'con': False, 'verbose': False, 'quiet': True}}, 'far-away', **kw)
    return r, runs


def test_the_sync_stops_before_the_run_and_changes_nothing(host, pair, monkeypatch):
    stale_copies(pair)
    r, runs = run_sync(host, pair, monkeypatch)
    assert r['return'] == 1 and r['status'] == 'conflicts' and runs == []                 # rclone was never started
    assert [c['path'] for c in r['conflicts'][0]['conflicts']] == ['work/a/desc.yaml']
    assert r['conflicts'][0]['host'] == 'far-away' and r['conflicts'][0]['repository'] == 'fgg'
    assert os.path.isfile(r['conflicts'][0]['file']) and 'texts' not in r['conflicts'][0]['conflicts'][0]
    assert 'nothing was changed' in r['problems'][0] and r['report'][0][3].startswith('CONFLICTS: 1 file(s)')
    # the safe ones wait with it: nothing at all was touched
    assert (pair['there'] / 'work' / 'a' / 'notes.md').read_text() == '# notes\none\ntwo\n'
    assert not (pair['work'].parent / 'backup-here').exists()
    # the state of the host says which repository is apart
    assert host._sync_state(dict(HOST, desc={'sync': {}}))[0].startswith('! fgg')


def test_the_sync_goes_on_once_every_conflict_is_decided(host, pair, monkeypatch):
    stale_copies(pair)
    r, runs = run_sync(host, pair, monkeypatch, resolve='suggested')
    assert r['return'] == 0 and r['status'] == 'ok' and len(runs) == 1 and r['conflicts'] == []
    assert len(r['settled']) == 4 and runs[0]['later'] == [] and runs[0]['rules_first'] == [] and r['later'] == []
    assert (pair['here'] / 'work' / 'a' / 'desc.yaml').read_text() == 'name: a\nstate: there\n'   # the newer: the host's
    assert '4 conflict(s) settled' in r['summary'] and not list(pair['work'].glob('cmeta-conflicts-*'))
    assert 'conflict(s) settled before the run' in r['report'][0][3]


def test_newer_never_stops_and_a_dry_run_changes_nothing(host, pair, monkeypatch):
    stale_copies(pair)
    r, runs = run_sync(host, pair, monkeypatch, conflicts='newer')
    assert r['return'] == 0 and len(runs) == 1 and len(r['settled']) == 3          # the safe ones; the fourth is rclone's
    assert (pair['here'] / 'work' / 'a' / 'desc.yaml').read_text() == 'name: a\nstate: here\n'    # untouched before the run

    r, runs = run_sync(host, pair, monkeypatch, conflicts='ask', dry_run=True)
    assert r['return'] == 1 and runs == [] and r['conflicts'][0]['file'] == ''     # said, and nothing kept by a dry run
    r, runs = run_sync(host, pair, monkeypatch, conflicts='sometimes')
    assert r['return'] > 0 and 'ask, ask-all, newer' in r['error']
    r, runs = run_sync(host, pair, monkeypatch, resolve='whatever')
    assert r['return'] > 0 and 'is neither' in r['error']


def test_the_sync_leaves_out_an_open_session_and_says_so(host, pair, monkeypatch):
    stale_copies(pair)
    log = pair['here'] / 'work' / 'a' / '!AI' / 'log'
    log.mkdir(parents=True, exist_ok=True)
    marker = log / '20261117-144547.running'
    marker.write_text(json.dumps({'harness': 'claude', 'host': socket.gethostname().split('.')[0].lower(), 'pid': os.getpid(),
                                  'started': '2026-11-17T14:45:47'}), encoding='utf-8')
    r, runs = run_sync(host, pair, monkeypatch)
    assert r['return'] == 0 and len(runs) == 1                                     # its conflicts are not looked at
    assert runs[0]['rules_first'] == ['+ /work/a/!AI/log/*.running', '- /work/a/**'] and runs[0]['areas'] == ['work/a']
    assert len(r['left_out']) == 1 and 'work/a - a session of claude is open here since 2026-11-17 14:45' in r['left_out'][0]
    assert '1 open session(s): their folders left for the next sync' in r['summary']
    # the session that runs the sync says which marker is its own: nothing of it is left out
    monkeypatch.setenv('CMETA_RUN_AI_MARKER', str(marker))
    r, runs = run_sync(host, pair, monkeypatch)
    assert r['return'] == 1 and r['status'] == 'conflicts' and r['left_out'] == []
    monkeypatch.delenv('CMETA_RUN_AI_MARKER')
    r, runs = run_sync(host, pair, monkeypatch, include_sessions=True)
    assert r['status'] == 'conflicts' and r['left_out'] == []


def test_the_banner_can_say_conflicts(host):
    lines = host._banner(False, 'STATUS: CONFLICTS - 3 file(s) wait', word='CONFLICTS!').split('\n')
    assert len(lines) == 2 + 5 + 1 + 1 and all(len(l) <= 100 for l in lines) and lines[2].count('#') > 10


def test_a_file_left_for_later_is_named_in_the_verdict(host, pair, monkeypatch):
    stale_copies(pair)
    r, runs = run_sync(host, pair, monkeypatch, resolve='later')
    assert r['return'] == 0 and r['status'] == 'ok' and len(runs) == 1 and runs[0]['later'] == ['work/a/desc.yaml']
    assert r['later'] == ['far-away / fgg: work/a/desc.yaml']
    assert '1 file(s) left for later (asked again at the next sync)' in r['summary']
    assert (pair['here'] / 'work' / 'a' / 'desc.yaml').read_text() == 'name: a\nstate: here\n'    # as it is on each side


def test_the_files_a_stop_kept_are_listed_again_and_one_is_shown_line_by_line(host, pair, monkeypatch):
    """cx host conflicts: what the stopped runs wait for, from the lists they kept (no host is connected to), and with
    --diff what differs in one of them - a line of the host with "-", a line of this machine with "+"."""
    stale_copies(pair)
    ctx = {'control': {'con': False, 'verbose': False}}
    r, runs = run_sync(host, pair, monkeypatch)                                 # the stop keeps them beside the listings
    assert r['status'] == 'conflicts'
    out = host.conflicts_(ctx)
    assert [(w['host'], w['repository']) for w in out['waiting']] == [('far-away', 'fgg')]
    assert [c['path'] for c in out['waiting'][0]['conflicts']] == ['work/a/desc.yaml'] and os.path.isfile(out['waiting'][0]['file'])
    assert out['waiting'][0]['conflicts'][0]['suggested'] == 'host'
    assert host.conflicts_(ctx, repos='another-repository')['waiting'] == []

    d = host.conflicts_(ctx, 'far-away', repos='fgg', diff='work/a/desc.yaml')
    assert d['return'] == 0 and d['note'] == '' and '-state: there' in d['diff'] and '+state: here' in d['diff']
    assert d['here']['size'] == 20 and d['there']['size'] == 21 and d['diff'][0].startswith('--- far-away (')
    # only a file that waits is shown: the command reads no other file of either side
    bad = host.conflicts_(ctx, 'far-away', repos='fgg', diff='work/a/notes.md')
    assert bad['return'] > 0 and 'waits for a decision' in bad['error']
    # a copy that is not a text is said, not shown
    (pair['here'] / 'work' / 'a' / 'desc.yaml').write_bytes(b'\x00\x01binary')
    assert 'not a text' in host.conflicts_(ctx, 'far-away', repos='fgg', diff='work/a/desc.yaml')['note']
    put(pair['here'], 'work/a/desc.yaml', 'name: a\nstate: here\n', NOW - 100)

    r, runs = run_sync(host, pair, monkeypatch, resolve='suggested')            # decided: nothing waits
    assert r['status'] == 'ok' and host.conflicts_(ctx)['waiting'] == []


# --------------------------------------------------------------------------- what an interrupted run left behind

def interrupted(pair, host, path1, path2):
    """The listings rclone made at the start of a run that then stopped: what each side held at that moment."""
    prefix = host._bisync_pair_prefix(pair['entry']) + 'there'
    for side, files in ((1, path1), (2, path2)):
        new = pair['work'] / f'{prefix}.path{side}.lst-new'
        listing(new, files)
        os.utime(new, (NOW - 7200, NOW - 7200))                          # after the last good run, before now


def test_a_side_lists_only_the_names_asked_for_and_says_when_a_file_is_gone(module, tmp_path):
    root = tmp_path / 'side'
    put(root, 'a/data.bin', 'x' * 10, NOW - 10)
    put(root, 'a/data.bin.0a1b2c3d.partial', 'x' * 4, NOW - 10)
    put(root, 'a/notes.partial', 'a file of that name, not a transfer', NOW - 10)
    r = module._sync_side({'do': 'recent', 'root': str(root), 'rules': [], 'since': NOW - 100, 'match': module.PARTIAL_FILE})
    assert sorted(r['files']) == ['a/data.bin.0a1b2c3d.partial']
    f = module._sync_side({'do': 'facts', 'root': str(root), 'names': ['a/data.bin', 'a/none.bin'], 'stat': True})['facts']
    assert f['a/data.bin']['size'] == 10 and 'sha1' not in f['a/data.bin']                 # nothing was read
    assert f['a/none.bin']['missing'] is True
    # put aside: out of the repository, a folder made for it; a file that is gone is no error
    r = module._sync_side({'do': 'apply', 'root': str(root), 'steps': [
        {'op': 'aside', 'from': 'a/data.bin.0a1b2c3d.partial', 'to': str(tmp_path / 'kept' / 'a' / 'data.bin.0a1b2c3d.partial')},
        {'op': 'aside', 'from': 'a/none.bin', 'to': str(tmp_path / 'kept' / 'a' / 'none.bin')}]})
    assert r == {'done': 2, 'changed': 1} and (tmp_path / 'kept' / 'a' / 'data.bin.0a1b2c3d.partial').is_file()
    assert not (root / 'a' / 'data.bin.0a1b2c3d.partial').exists()


def test_the_temporary_files_of_an_interrupted_transfer_are_leftovers(host, pair):
    """rclone writes a file as <name>.<8 hex>.partial and renames it at the end: a run that is cut leaves it, and the
    next run would carry it to the other side as a new file. One the last good run knew is a file like any other."""
    pair['both']('data/model.bin', 'm' * 50)
    pair['both']('data/old.bin.11223344.partial', 'both sides have had it since the last good run')
    pair['base']()
    put(pair['there'], 'data/model2.bin.6f735d0d.partial', 'm' * 20, NOW - 500)         # the host: a transfer was cut
    put(pair['here'], 'data/model3.bin.01630298.partial', 'm' * 30, NOW - 400)          # and one this way
    put(pair['there'], 'data/old.bin.11223344.partial', 'changed on the host', NOW - 300)
    put(pair['there'], 'data/plain.partial', 'not rclone\'s name', NOW - 300)
    r = look(host, pair)
    assert [(s['side'], s['path'], s['kind']) for s in r['leftovers']] == [
        (1, 'data/model3.bin.01630298.partial', 'partial'), (2, 'data/model2.bin.6f735d0d.partial', 'partial')]
    assert r['conflicts'] == [] and r['plan'] == []
    # nothing was changed by the look
    assert (pair['there'] / 'data' / 'model2.bin.6f735d0d.partial').is_file()


def test_a_file_an_interrupted_run_carried_and_its_own_side_deleted_since_does_not_come_back(host, pair):
    """A new file went to the host, the run stopped before its end (the base never knew the file), and the file was
    deleted here afterwards: the host's copy is no new file of the host - it follows the one it was copied from."""
    pair['both']('work/kept/a.md', 'a\n')
    pair['both']('work/replaced/r.md', 'old\n')
    pair['base']()
    then = dict((n, (s, w)) for n, (s, w) in {'work/kept/a.md': (2, OLD), 'work/replaced/r.md': (4, NOW - 9000),
                                              'work/moved/item.md': (9, NOW - 9000), 'work/moved/still.md': (6, NOW - 9000),
                                              'work/moved/edited.md': (5, NOW - 9000)}.items())
    interrupted(pair, host, then, {'work/kept/a.md': (2, OLD), 'work/replaced/r.md': (4, OLD)})
    # the run carried four files to the host before it stopped; since then, here:
    put(pair['there'], 'work/moved/item.md', 'the item\n', NOW - 9000)                  # ... deleted here (moved away)
    put(pair['there'], 'work/replaced/r.md', 'new\n', NOW - 9000)                       # ... a new version carried, then deleted here
    os.remove(pair['here'] / 'work' / 'replaced' / 'r.md')
    put(pair['there'], 'work/moved/still.md', 'still\n', NOW - 9000)                    # ... still here: nothing to do
    put(pair['here'], 'work/moved/still.md', 'still\n', NOW - 9000)
    put(pair['there'], 'work/moved/edited.md', 'edited on the host since\n', NOW - 100)   # ... changed there since: its own work
    put(pair['there'], 'work/new-there.md', 'made on the host\n', NOW - 200)            # a real new file of the host
    r = look(host, pair)
    assert [(s['side'], s['path'], s['kind']) for s in r['leftovers']] == [
        (2, 'work/moved/item.md', 'gone'), (2, 'work/replaced/r.md', 'gone')]
    assert 'deleted on this machine after an interrupted run had carried it to far-away' in r['leftovers'][0]['why']

    # the other way round: carried here, deleted on the host since
    put(pair['here'], 'work/from-host.md', 'came\n', NOW - 9000)
    interrupted(pair, host, then, {'work/kept/a.md': (2, OLD), 'work/replaced/r.md': (4, OLD), 'work/from-host.md': (5, NOW - 9000)})
    r = look(host, pair)
    assert (1, 'work/from-host.md', 'gone') in [(s['side'], s['path'], s['kind']) for s in r['leftovers']]

    # without the listings of an interrupted run nothing is taken for a leftover: every such file is a new file
    for f in pair['work'].glob('*.lst-new'):
        f.unlink()
    assert look(host, pair)['leftovers'] == []


def test_the_leftovers_are_put_aside_before_the_run_and_named_in_the_verdict(host, pair, monkeypatch, tmp_path):
    pair['both']('data/model.bin', 'm' * 50)
    pair['base']()
    put(pair['there'], 'data/model2.bin.6f735d0d.partial', 'm' * 20, NOW - 500)
    put(pair['there'], 'work/moved/item.md', 'the item\n', NOW - 9000)
    interrupted(pair, host, {'data/model.bin': (50, OLD), 'work/moved/item.md': (9, NOW - 9000)}, {'data/model.bin': (50, OLD)})

    r, runs = run_sync(host, pair, monkeypatch, dry_run=True)                           # a dry run says it and changes nothing
    assert r['leftovers'] == [] and (pair['there'] / 'work' / 'moved' / 'item.md').is_file()

    r, runs = run_sync(host, pair, monkeypatch)
    assert r['return'] == 0 and len(runs) == 1
    assert not (pair['there'] / 'data' / 'model2.bin.6f735d0d.partial').exists() and not (pair['there'] / 'work' / 'moved' / 'item.md').exists()
    kept = tmp_path / 'backup-there'
    assert (kept / 'data' / 'model2.bin.6f735d0d.partial').is_file() and (kept / 'work' / 'moved' / 'item.md').read_text() == 'the item\n'
    assert len(r['leftovers']) == 2 and 'temporary file(s) an interrupted transfer left on far-away put aside' in r['leftovers'][0]
    assert 'work/moved/item.md: deleted on this machine after an interrupted run had carried it to far-away' in r['leftovers'][1]
    assert 'leftovers of an interrupted run put aside' in r['summary']


def test_an_attempt_that_failed_leaves_no_temporary_file_for_the_next_one(host, pair):
    pair['both']('data/a.bin', 'a' * 10)
    pair['base']()

    def first(kw):
        # the transfer was cut: rclone left its temporary file on the host, and the run failed
        put(pair['there'], 'data/big.bin.0a1b2c3d.partial', 'b' * 40, time.time())
        return {'return': 1, 'error': 'rclone bisync returned 1: connection reset', 'output': 'ERROR : data/big.bin: connection reset\n'}

    r, seen = robust(host, pair, [first, {'return': 0, 'output': ''}])
    assert r['return'] == 0 and len(seen) == 2
    assert not (pair['there'] / 'data' / 'big.bin.0a1b2c3d.partial').exists()
    assert any('1 temporary file(s) the stopped transfer left put aside' in n for n in r['notes'])


def test_a_run_that_was_cut_is_tried_again(host, pair, monkeypatch):
    """rclone ended in the middle - its process ended from outside, the machine slept: its output has the start of a
    two-way run and no last word. That is worth another try; a run that never began (a wrong flag) is not."""
    cut = ('2026/11/17 19:29:50 INFO  : Bisyncing with Comparison Settings: \n'
           '2026/11/17 19:29:51 INFO  : Building Path1 and Path2 listings\n'
           '2026/11/17 19:29:52 INFO  : - Path1             Do queued copies to                         - Path2\n')
    assert host._bisync_failure(cut) == ('cut', None)
    assert host._bisync_failure(cut + '2026/11/17 19:29:59 ERROR : Bisync aborted. Please try again.\n')[0] == 'transient'
    assert host._bisync_failure('Fatal error: unknown flag: --no-such-flag\n') == ('other', None)

    import time as time_module
    monkeypatch.setattr(time_module, 'sleep', lambda s: None)
    pair['both']('a.md', 'base\n')
    pair['base']()
    r, seen = robust(host, pair, [{'return': 1, 'error': 'rclone bisync returned 1', 'output': cut}, {'return': 0, 'output': ''}])
    assert r['return'] == 0 and len(seen) == 2 and any('the run was cut before its end' in n for n in r['notes'])
