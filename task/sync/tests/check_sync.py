"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Real rclone integration checks. Pass a test-session sandbox as the sole argument.
Uses a private cMeta home, disposable files, and the installed rclone tool.
"""
import hashlib
from contextlib import redirect_stdout
import io
import json
import os
import shutil
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

from cmeta import CMeta


# Rclone combines both endpoint paths into one filename (255-character limit).
root = Path(sys.argv[1]).resolve() / ('s' + uuid.uuid4().hex[:5])
root.mkdir(parents=True)
cm = CMeta(home=str(root / 'CMETA'))
repo = Path(__file__).resolve().parents[3]


def access(**p):
    r = cm.access({'con': False, 'quiet': True, **p})
    assert r['return'] == 0, r
    return r


access(category='repo', command='plug', arg1=str(repo))
category = 'sync,5232474161e24333'


def artifact(name, a, b, **extra):
    r = access(category=category, command='get', arg1='local:' + name)
    path = Path(r['artifact']['path'])
    d = dict(source={'path': str(a)}, destination={'path': str(b)}, **extra)
    assert cm.utils.files.safe_write_file(str(path / '_desc.yaml'), d)['return'] == 0
    return path


def sync(name=None, **p):
    return access(category='task', command='run', arg1='sync', name=name, **p)


def put(path, text, stamp):
    path.write_text(text, encoding='utf-8')
    os.utime(path, (stamp, stamp))


a, b, c = [root / n for n in ('a ! with spaces', 'b', 'c')]
for p in (a, b, c):
    p.mkdir()
for i in range(12):
    put(a / ('file' + str(i)), 'initial-' + str(i), 1700000000)
put(b / 'from-b', 'remote file', 1700000010)
put(b / 'file0', 'initial loser must be backed up', 1699999990)
artifact('ab', a, b)
artifact('bc', b, c)

with patch('builtins.input', return_value='n') as prompt:
    declined = cm.access(dict(category='task', command='run', arg1='sync', name='bc', quiet=False))
assert declined['return'] == 0 and declined['cancelled']
assert prompt.called and not list(c.iterdir())

assert len(sync()['syncs']) == 2
sync('ab', plan=True)
assert not list((root / 'CMETA/repos/local/result').glob('sync--ab--*'))
sync('ab', dry_run=True)
assert not (a / 'from-b').exists()
with redirect_stdout(io.StringIO()) as terminal:
    r = sync('ab', live=True, con=True)
live_output = terminal.getvalue()
full_log = Path(r['results'][0]['log']).read_text(encoding='utf-8')
assert 'Syncing files; live log:' in live_output
assert 'Copied' in live_output and 'file0' in live_output
assert full_log in live_output, 'complete log must be retained and displayed'
state = Path(r['results'][0]['state'])
assert (a / 'from-b').read_text() == 'remote file'
assert (b / 'file0').read_text() == 'initial-0'
assert any(p.read_text() == 'initial loser must be backed up'
           for p in (root / '.cmeta-sync-backups').rglob('file0'))
assert r['results'][0]['initial'] is True

# UID-qualified references reuse the baseline.
renamed = access(category=category, command='read', arg1='local:ab')['artifact']
ref = 'ab,' + renamed['cmeta_ref_parts']['artifact_uid']
assert sync(ref)['results'][0]['state'] == str(state)

sync('bc')
put(c / 'from-c', 'reaches a after reverse leg', 1700000050)
sync(names=['ab', 'bc', 'ab'])
assert (a / 'from-c').read_text() == 'reaches a after reverse leg'
put(a / 'file1', 'edit A', 1700000100)
put(b / 'file2', 'edit B', 1700000200)
(a / 'file3').unlink()

before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (state / 'bisync').iterdir()}
sync('ab', dry_run=True)
after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (state / 'bisync').iterdir()}
assert before == after, 'dry run changed baseline'
assert (b / 'file3').exists()
sync('ab')
assert (b / 'file1').read_text() == 'edit A'
assert (a / 'file2').read_text() == 'edit B'
assert not (b / 'file3').exists()

put(a / 'file4', 'conflict A', 1700000300)
put(b / 'file4', 'conflict from B', 1700000400)
sync('ab')
for p in (a, b):
    assert {'conflict A', 'conflict from B'} <= {f.read_text() for f in p.glob('file4*')}

copy = root / 'copy'
artifact('oneway', a, copy, mode='oneway')
sync('oneway')
put(copy / 'extra', 'retained', 1700000500)
sync('oneway')
assert (copy / 'extra').exists()
artifact('mirror', a, copy, mode='mirror')
sync('mirror')
assert not (copy / 'extra').exists()

# A typo, overlapping endpoints, changed filters and lost state cannot silently
# trigger a fresh baseline. An explicit resync is a separate, reviewed action.
artifact('overlap', a, a / 'nested')
assert cm.access(dict(category='task', command='run', arg1='sync', name='overlap', plan=True))['return']
artifact('ab', a, b, exclude=['*.ignored'])
assert cm.access(dict(category='task', command='run', arg1='sync', name='ab', quiet=True))['return']
sync('ab', resync=True)
baseline = state / 'bisync'
baseline.rename(state / 'saved-baseline')
assert cm.access(dict(category='task', command='run', arg1='sync', name='ab', quiet=True))['return']
(state / 'saved-baseline').rename(baseline)
snapshot = (state / 'state.json').read_bytes()
assert cm.utils.files.safe_write_file(str(state / 'state.json'),
    {'identity': json.loads(snapshot)['identity'], 'status': 'initializing'})['return'] == 0
assert cm.access(dict(category='task', command='run', arg1='sync', name='ab', quiet=True))['return']
(state / 'state.json').write_bytes(snapshot)

# Local repo selection: user data copied; cache/config explicitly excluded.
h1, h2 = root / 'home1', root / 'home2'
for name in ('local/ctuning.user', 'local/cache', 'local/config/default', 'unselected'):
    p = h1 / 'repos' / name
    p.mkdir(parents=True)
    put(p / 'data', name, 1700000000)
artifact('repos', h1, h2, repos=['local'], exclude=['/local/cache/**', '/local/config/default/**'])
sync('repos')
assert (h2 / 'repos/local/ctuning.user/data').exists()
assert not (h2 / 'repos/local/cache/data').exists()
assert not (h2 / 'repos/local/config/default/data').exists()
assert not (h2 / 'repos/unselected/data').exists()

# Category exclusions apply at the repo root, in both directions, and preserve
# existing excluded files even in mirror mode. Nested same-name folders remain.
for index, mode in enumerate(('bisync', 'mirror')):
    x, y = root / ('x' + str(index)), root / ('y' + str(index))
    for home in (x, y):
        for repo_name in ('local', 'team'):
            (home / 'repos' / repo_name / 'log').mkdir(parents=True)
            put(home / 'repos' / repo_name / 'log' / home.name, 'keep only here', 1700000000)
    for repo_name in ('local', 'team'):
        nested = x / 'repos' / repo_name / 'doc/log'
        nested.mkdir(parents=True)
        put(nested / 'data', 'copy nested log normally', 1700000000)
        put(nested / 'unchanged', 'stable file for bisync safety checks', 1700000000)
    name = 'categories-' + mode
    artifact(name, x, y, repos='*', exclude_categories=['log'], mode=mode)
    sync(name)
    for repo_name in ('local', 'team'):
        put(x / 'repos' / repo_name / 'doc/log/data', 'updated nested file', 1700000100)
    sync(name)
    for home, other in ((x, y), (y, x)):
        for repo_name in ('local', 'team'):
            assert (home / 'repos' / repo_name / 'log' / home.name).exists()
            assert not (home / 'repos' / repo_name / 'log' / other.name).exists()
            assert (home / 'repos' / repo_name / 'doc/log/data').read_text() == 'updated nested file'

seed1, seed2 = root / 's1', root / 's2'
for home in (seed1, seed2):
    for category_name in ('ctuning.user', 'config', 'log'):
        (home / 'repos/local' / category_name).mkdir(parents=True)
    for category_name in ('config', 'log'):
        put(home / 'repos/local' / category_name / 'private', home.name, 1700000000)
    for index in range(4):
        put(home / 'repos/local/ctuning.user' / ('stable' + str(index)), 'unchanged', 1700000000)
src = seed1 / 'repos/local/ctuning.user'
dst = seed2 / 'repos/local/ctuning.user'
put(src / 'equal-metadata', 'source', 1700000000)
put(dst / 'equal-metadata', 'target', 1700000000)
put(src / 'newer-at-destination', 'source wins', 1700000000)
put(dst / 'newer-at-destination', 'destination newer', 1700000010)
put(dst / 'destination-only', 'preserve in backup', 1700000000)
artifact('seed', seed1, seed2, repos=['local'], exclude_categories=['log', 'config'], initial_mode='mirror')
sync('seed', dry_run=True, initialize=True)
assert (dst / 'equal-metadata').read_text() == 'target'
assert (dst / 'destination-only').exists()
seed_result = sync('seed', initialize=True)['results'][0]
assert seed_result['initial'] is True
assert (dst / 'equal-metadata').read_text() == 'source'
assert (dst / 'newer-at-destination').read_text() == 'source wins'
assert not (dst / 'destination-only').exists()
assert not (src / 'destination-only').exists()
assert any(p.read_text() == 'preserve in backup'
           for p in (seed2 / '.cmeta-sync-backups').rglob('destination-only'))
for home in (seed1, seed2):
    for category_name in ('config', 'log'):
        assert (home / 'repos/local' / category_name / 'private').read_text() == home.name
put(dst / 'from-destination', 'later bidirectional change', 1700000020)
assert sync('seed', require_initialized=True)['results'][0]['initial'] is False
assert (src / 'from-destination').read_text() == 'later bidirectional change'
put(dst / 'recovery-keeps-this', 'manual resync must not seed again', 1700000030)
sync('seed', resync=True)
assert (src / 'recovery-keeps-this').read_text() == 'manual resync must not seed again'

# A bootstrap failure before baseline commit must not be mistaken for success.
seed3 = root / 's3'
artifact('seed-fail', seed1, seed3, repos=['local'], initial_mode='mirror', exclude_categories=['log', 'config'])
sync_api = next(module.CTask for module in list(sys.modules.values())
                if getattr(module, '__file__', None) and
                Path(module.__file__).resolve() == repo / 'task/sync/api_v1.py')
original_transfer = sync_api.transfer


def fail_baseline(self, ctx, plan, *args, **kwargs):
    if plan['alias'] == 'seed-fail' and plan['mode'] == 'bisync':
        raise ValueError('simulated interruption before baseline commit')
    return original_transfer(self, ctx, plan, *args, **kwargs)


with patch.object(sync_api, 'transfer', fail_baseline):
    failed = cm.access(dict(category='task', command='run', arg1='sync', name='seed-fail', quiet=True, initialize=True))
assert failed['return'] and 'simulated interruption' in failed['error']
blocked = cm.access(dict(category='task', command='run', arg1='sync', name='seed-fail', quiet=True, initialize=True))
assert blocked['return'] and 'initialization was interrupted' in blocked['error']
assert sync('seed-fail', resync=True, initialize=True)['results'][0]['initial'] is True

# A completed first-run command cannot be accidentally used to overwrite again.
blocked = cm.access(dict(category='task', command='run', arg1='sync', name='seed', quiet=True, initialize=True))
assert blocked['return'] and 'already initialized' in blocked['error']

# Emulate legacy cache state, migrate it, and continue without a new baseline.
state_meta = access(category='result', command='read', arg1='local:' + state.name)['artifact']['cmeta']
legacy = access(category='cache', command='get', arg1='local:' + state.name,
                meta={'sync_uid': state_meta['sync_uid'], 'permanent': True})['artifact']
legacy_root = Path(legacy['path'])
for item in ('state.json', 'bisync', 'runs', 'last-result.json'):
    if (state / item).is_dir():
        shutil.copytree(state / item, legacy_root / item)
    elif (state / item).exists():
        shutil.copy2(state / item, legacy_root / item)
state.resolve().relative_to(root.resolve())
access(category='result', command='update', arg1='local:' + state.name, meta={'permanent': False})
access(category='result', command='delete', arg1='local:' + state.name, force=True)
migrated = sync('ab', migrate_state=True)['results'][0]
state = Path(migrated['state'])
assert (state / 'state.json').read_bytes() == (legacy_root / 'state.json').read_bytes()
assert (legacy_root / 'migrated-to-result.json').exists()
assert sync('ab', require_initialized=True)['results'][0]['initial'] is False

# Losing the complete result must stop a normal run, even though both data trees exist.
seed_state = Path(seed_result['state'])
seed_state.resolve().relative_to(root.resolve())
access(category='result', command='update', arg1='local:' + seed_state.name, meta={'permanent': False})
access(category='result', command='delete', arg1='local:' + seed_state.name, force=True)
put(dst / 'must-survive-state-loss', 'destination user data', 1700000040)
blocked = cm.access(dict(category='task', command='run', arg1='sync', name='seed', quiet=True, require_initialized=True))
assert blocked['return'] and 'successful bisync state is missing' in blocked['error']
assert (dst / 'must-survive-state-loss').read_text() == 'destination user data'
blocked = cm.access(dict(category='task', command='run', arg1='sync', name='seed', quiet=True))
assert blocked['return'] and 'requires --initialize' in blocked['error']

# The retained cache archive must not silently resurrect stale state if result is lost.
state.resolve().relative_to(root.resolve())
access(category='result', command='update', arg1='local:' + state.name, meta={'permanent': False})
saved_state = root / 'saved-state'
shutil.copytree(state, saved_state)
access(category='result', command='delete', arg1='local:' + state.name, force=True)
blocked = cm.access(dict(category='task', command='run', arg1='sync', name='ab', quiet=True, require_initialized=True))
assert blocked['return'] and 'stale cache archive' in blocked['error']
# Restore this disposable baseline through its result artifact for remaining checks.
restored = access(category='result', command='get', arg1='local:' + state.name,
                  meta={'sync_uid': state_meta['sync_uid'], 'permanent': True})['artifact']
for item in ('state.json', 'bisync', 'runs', 'last-result.json'):
    if (saved_state / item).is_dir():
        shutil.copytree(saved_state / item, state / item)
    elif (saved_state / item).exists():
        shutil.copy2(saved_state / item, state / item)

# The user's layout nests the second home below an unselected repository.
nested_home = root.parent / ('n' + uuid.uuid4().hex[:5])
(nested_home / 'repos/local').mkdir(parents=True)
(nested_home / 'repos/local/data').write_text('nested-home-check')
inside = nested_home / 'repos/x/p/C'
artifact('nested-repos', nested_home, inside, repos=['local'])
sync('nested-repos')
assert (inside / 'repos/local/data').read_text() == 'nested-home-check'

# Result operational state survives cache cleanup and an explicit result delete.
access(category=category, command='move', arg1='local:ab', arg2='local:ab-renamed')
renamed_run = sync('ab-renamed')
assert renamed_run['results'][0]['state'] == str(state)
assert renamed_run['results'][0]['initial'] is False
access(category='cache', command='delete', arg1='local:*', force=True)
assert state.exists()
access(category='result', command='delete', arg1='local:' + state.name, force=True)
assert state.exists()
# Linked definitions perform real transfers with separate baselines.
u, v, w, x = [root / name for name in ('u', 'v', 'w', 'x')]
u.mkdir()
w.mkdir()
(u / 'stable').write_text('stable')
(w / 'stable').write_text('stable')
artifact('linked-second', w, x)
artifact('linked-first', u, v, also=['linked-second'])
linked = sync('linked-first')
assert [r['name'] for r in linked['results']] == ['linked-first', 'linked-second']
assert linked['results'][0]['state'] != linked['results'][1]['state']
(u / 'from-first').write_text('first pair')
(x / 'from-second').write_text('second pair')
continued = sync('linked-first', require_initialized=True)
assert all(not r['initial'] for r in continued['results'])
assert (v / 'from-first').read_text() == 'first pair'
assert (w / 'from-second').read_text() == 'second pair'

print(json.dumps({'status': 'passed', 'sandbox': str(root),
                  'checks': ['initialize', 'repeat', 'backups', 'two-way edits', 'delete', 'conflict',
                             'ordered chain', 'copy', 'mirror', 'list', 'plan', 'dry-run baseline',
                             'filters', 'category exclusions', 'source mirror bootstrap', 'bootstrap recovery',
                             'overlap', 'changed definition', 'missing baseline',
                             'interrupted initialization', 'renamed definition', 'nested selected repo',
                             'confirmation decline', 'permanent result state', 'legacy cache migration',
                             'first-run repeat refusal', 'complete state loss', 'stale archive refusal',
                             'live file output with retained log', 'linked definition transfers']}, indent=2))
