"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx host sync --backup": what a run overwrites or deletes is kept in .cmeta-sync-backups/<repository>/<run id>/ beside
the repos folder of each side - rclone's --backup-dir1/--backup-dir2 for a bisync, --backup-dir for a copy, nothing for
git, nothing without the flag. Offline: the rclone call is captured, never run.
"""

import importlib.util
import pathlib
import re
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOST = {'alias': 'lab', 'type': 'ssh', 'desc': {}, 'state': {}}
CTX = {'control': {'con': False}, 'tasks': {'nested_call': 0}}


@pytest.fixture
def host(tmp_path):
    """The host category with the rclone call captured and the helpers a sync needs stubbed."""
    spec = importlib.util.spec_from_file_location('host_sync_backup_under_test', REPO_ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    c = module.Category.__new__(module.Category)
    c.calls = []
    c.cm = SimpleNamespace(error=lambda s: {'return': 1, 'error': s}, catch_error=lambda r: r['return'] > 0)
    c._repo_desc = lambda local: {}
    c._bisync_workdir = lambda h, entry: str(tmp_path / 'workdir')
    c._selection_file = lambda h, name, entry: str(tmp_path / 'selection.txt')
    c._after_partial = lambda *a, **kw: {'return': 0}

    def rclone(ctx, h, command, local, remote_path, whitelist=None, blacklist=None, extra=None, **kw):
        c.calls.append({'command': command, 'local': local, 'remote': remote_path, 'extra': list(extra or []), 'kw': kw})
        return {'return': 0}

    c._rclone = rclone
    local = tmp_path / 'repos' / 'my-repo'
    local.mkdir(parents=True)
    return c, str(local)


def entry(method, local):
    return {'method': method, 'local': local, 'remote': '/home/u/CMETA/repos/my-repo', 'blacklist': ['.git/**']}


def flags(call, name):
    """The values that follow every occurrence of flag `name` in the captured rclone flags."""
    extra = call['extra']
    return [extra[i + 1] for i, x in enumerate(extra) if x == name]


def test_bisync_backs_up_both_sides(host, tmp_path):
    c, local = host
    r = c._sync_repo(CTX, HOST, 'my-repo', entry('bisync', local), resync=False, resync_mode='newer', unlock=False,
                     dry_run=False, con=False, verbose=False, backup=True)
    assert r['return'] == 0 and len(c.calls) == 1
    call = c.calls[0]
    assert call['command'] == 'bisync'
    d1, = flags(call, '--backup-dir1')
    d2, = flags(call, '--backup-dir2')
    stamp = pathlib.Path(d1).name
    assert re.fullmatch(r'\d{8}-\d{6}', stamp)
    assert pathlib.Path(d1) == tmp_path / 'repos' / '.cmeta-sync-backups' / 'my-repo' / stamp     # beside the repos folder
    assert d2 == f':sftp:/home/u/CMETA/repos/.cmeta-sync-backups/my-repo/{stamp}'                 # the same on the host
    assert '--backup-dir' not in call['extra']


def test_copy_backs_up_the_host_side_only(host):
    c, local = host
    c._sync_repo(CTX, HOST, 'my-repo', entry('copy', local), resync=False, resync_mode='newer', unlock=False,
                 dry_run=True, con=False, verbose=False, backup=True)
    call = c.calls[0]
    assert call['command'] == 'copy' and '--dry-run' in call['extra']
    d, = flags(call, '--backup-dir')
    assert d.startswith(':sftp:/home/u/CMETA/repos/.cmeta-sync-backups/my-repo/')
    assert not flags(call, '--backup-dir1') and not flags(call, '--backup-dir2')


def test_without_the_flag_and_for_git_nothing_changes(host):
    c, local = host
    c._sync_repo(CTX, HOST, 'my-repo', entry('bisync', local), resync=False, resync_mode='newer', unlock=False,
                 dry_run=False, con=False, verbose=False)
    assert not [x for x in c.calls[0]['extra'] if x.startswith('--backup-dir')]
    c._cmd_run = lambda ctx, h, cmd: {'return': 0, 'cmd': cmd}
    c._run_local = lambda cmd, **kw: {'returncode': 0}
    r = c._sync_repo(CTX, HOST, 'my-repo', entry('git', local), resync=False, resync_mode='newer', unlock=False,
                     dry_run=False, con=False, verbose=False, backup=True)
    assert r['return'] == 0 and len(c.calls) == 1                                                  # no rclone call for git


def test_sync_documents_the_flag():
    text = (REPO_ROOT / 'category/host/api/v1.py').read_text(encoding='utf-8')
    assert 'backup=False,' in text and '.cmeta-sync-backups' in text
    readme = (REPO_ROOT / 'category/host/README.md').read_text(encoding='utf-8')
    assert '--backup' in readme
