"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Real rclone checks for optional empty-directory cleanup. Run inside a test session:
python check_empty_dirs.py <sandbox> [installed-rclone-executable]
"""
import hashlib
import json
import os
from pathlib import Path
import sys

from cmeta import CMeta


root = Path(sys.argv[1]).resolve()
if len(sys.argv) > 2:
    os.environ['PATH'] = str(Path(sys.argv[2]).parent) + os.pathsep + os.environ.get('PATH', '')
cm = CMeta(home=str(root / 'CMETA'))


def access(**params):
    result = cm.access(dict(con=False, quiet=True, **params))
    assert result['return'] == 0, result
    return result


access(category='repo', command='plug', arg1=str(Path(__file__).resolve().parents[3]))
a, b = root / 'a', root / 'b'
for home in [a, b]:
    local = home / 'repos/local'
    (local / 'ctuning.user.email/retired/empty').mkdir(parents=True)
    (local / 'config/keep-empty').mkdir(parents=True)
    (local / 'cache/keep-empty').mkdir(parents=True)
    (home / 'repos/other/keep-empty').mkdir(parents=True)
    (local / '_cmr.yaml').write_text('repo: fixture\n', encoding='utf-8')
    (local / 'ctuning.user.email/active').mkdir()
    (local / 'ctuning.user.email/active/_cmeta.json').write_text('keep this record', encoding='utf-8')
    (local / 'ctuning.user.email/active/excluded.json').write_text('excluded file stays', encoding='utf-8')
result = access(category='sync', command='get', arg1='local:empty-dirs')
desc = Path(result['artifact']['path']) / '_desc.yaml'
definition = dict(source={'path': str(a)}, destination={'path': str(b)}, repos=['local'],
                  exclude_categories=['config', 'cache'],
                  exclude=['/local/_cmr.*', '**/excluded.json'])
assert cm.utils.files.safe_write_file(str(desc), definition)['return'] == 0


def sync(**params):
    return access(category='task', command='run', arg1='sync', name='empty-dirs', **params)


initial = sync(initialize=True)
state = Path(initial['results'][0]['state'])
for home in [a, b]:
    assert (home / 'repos/local/ctuning.user.email/retired/empty').is_dir(), 'default behavior changed'


def baseline():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (state/'bisync').iterdir()}


before = baseline()
sync(dry_run=True, remove_empty_dirs=True, require_initialized=True)
assert before == baseline(), 'preview modified the successful baseline'
assert (a/'repos/local/ctuning.user.email/retired/empty').is_dir(), 'preview removed a real directory'
definition['remove_empty_dirs'] = True
assert cm.utils.files.safe_write_file(str(desc), definition)['return'] == 0
result = sync(require_initialized=True)
assert not result['results'][0]['initial'], 'directory cleanup reset the file baseline'
for home in [a, b]:
    local = home/'repos/local'
    assert not (local/'ctuning.user.email/retired').exists()
    assert (local/'ctuning.user.email/active/_cmeta.json').read_text() == 'keep this record'
    assert (local/'ctuning.user.email/active/excluded.json').read_text() == 'excluded file stays'
    assert (local/'_cmr.yaml').is_file()
    assert (local/'config/keep-empty').is_dir() and (local/'cache/keep-empty').is_dir()
    assert (home/'repos/other/keep-empty').is_dir()
    assert home.is_dir() and local.is_dir()

# New empty folders are cleaned on subsequent runs, while a CLI opt-out preserves them.
for home in [a, b]:
    (home/'repos/local/ctuning.user.email/later/empty').mkdir(parents=True)
sync(require_initialized=True, remove_empty_dirs=False)
assert (a/'repos/local/ctuning.user.email/later/empty').is_dir()
sync(require_initialized=True)
assert not (a/'repos/local/ctuning.user.email/later').exists()
assert not (b/'repos/local/ctuning.user.email/later').exists()
print(json.dumps({'passed': True, 'default_unchanged': True, 'preview_preserved_data_and_baseline': True,
    'removed_both_sides': True, 'excluded_empty_directories_preserved': True,
    'files_and_roots_preserved': True, 'cli_disable_and_repeat_verified': True}))
