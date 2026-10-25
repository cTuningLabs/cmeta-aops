"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx host sync --backup": what a run overwrites or deletes is kept in the result artifact sync-backup--<repository> of
each side's local repository - rclone's --backup-dir1 (here, under <host>/<run id>/) and --backup-dir2 (the host, under
<this machine>/<run id>/) for a bisync, --backup-dir on the host for a copy, nothing for git, nothing without the flag;
after a run that put files on the host, the artifact there gets its _cmeta and the host's local repository is reindexed.
Offline: the rclone and ssh calls are captured, never run.
"""

import importlib.util
import pathlib
import re
import socket
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOST = {'alias': 'lab', 'type': 'ssh', 'desc': {}, 'state': {}}
CTX = {'control': {'con': False}, 'tasks': {'nested_call': 0}}


@pytest.fixture
def host(tmp_path):
    """The host category with the result artifact in tmp_path, the rclone and ssh calls captured, the helpers a sync
    needs stubbed."""
    spec = importlib.util.spec_from_file_location('host_sync_backup_under_test', REPO_ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    c = module.Category.__new__(module.Category)
    c.calls, c.ssh = [], []
    art = tmp_path / 'local' / 'result' / 'sync-backup--my-repo'
    art.mkdir(parents=True)
    (art / '_cmeta.yaml').write_text('artifact: 0123456789abcdef\n')

    def access(p):
        assert p['command'] == 'get' and p['arg1'] == 'local:sync-backup--my-repo' and p['meta']['tags'] == ['sync-backup']
        return {'return': 0, 'artifact': {'path': str(art)}}

    c.cm = SimpleNamespace(error=lambda s: {'return': 1, 'error': s}, catch_error=lambda r: r['return'] > 0, access=access)
    c.cmeta = {'uses_categories': {'result': 'result,6567e4df4d04488a'}}
    c._repo_desc = lambda local: {}
    c._bisync_workdir = lambda h, entry: str(tmp_path / 'workdir')
    c._selection_file = lambda h, name, entry: str(tmp_path / 'selection.txt')
    c._after_partial = lambda *a, **kw: {'return': 0}
    c._cmd_run = lambda ctx, h, cmd: c.ssh.append(cmd) or {'return': 0, 'cmd': 'ssh lab ' + cmd}
    c._run_local = lambda cmd, **kw: {'returncode': 1}          # by default: nothing was backed up on the host
    c._index_on_host = lambda ctx, h, name, remote, con, verbose: c.calls.append({'command': 'reindex', 'name': name, 'remote': remote}) or {'return': 0}

    def rclone(ctx, h, command, local, remote_path, whitelist=None, blacklist=None, extra=None, **kw):
        c.calls.append({'command': command, 'local': local, 'remote': remote_path, 'extra': list(extra or []), 'kw': kw})
        return {'return': 0}

    c._rclone = rclone
    local = tmp_path / 'repos' / 'my-repo'
    local.mkdir(parents=True)
    return c, str(local), art


def entry(method, local):
    return {'method': method, 'local': local, 'remote': '/home/u/CMETA/repos/my-repo', 'blacklist': ['.git/**']}


def flags(call, name):
    extra = call['extra']
    return [extra[i + 1] for i, x in enumerate(extra) if x == name]


def here():
    return re.sub(r'[^A-Za-z0-9_.-]', '-', socket.gethostname()).strip('-.') or 'orchestrator'


def test_bisync_backs_up_both_sides_into_result_artifacts(host):
    c, local, art = host
    r = c._sync_repo(CTX, HOST, 'my-repo', entry('bisync', local), resync=False, resync_mode='newer', unlock=False,
                     dry_run=False, con=False, verbose=False, backup=True)
    assert r['return'] == 0
    call = c.calls[0]
    assert call['command'] == 'bisync'
    d1, = flags(call, '--backup-dir1')
    d2, = flags(call, '--backup-dir2')
    stamp = pathlib.Path(d1).name
    assert re.fullmatch(r'\d{8}-\d{6}', stamp)
    assert pathlib.Path(d1) == art / 'lab' / stamp                                                   # here: under the host's name
    assert d2 == f':sftp:/home/u/CMETA/repos/local/result/sync-backup--my-repo/{here()}/{stamp}'  # there: under this machine's
    assert '--backup-dir' not in call['extra']
    # nothing went to the host's folder: the probe said so, no _cmeta copied, no reindex
    assert c.ssh and c.ssh[0].startswith('test -d ') and len(c.calls) == 1


def test_a_backup_on_the_host_marks_its_artifact(host):
    c, local, art = host
    c._run_local = lambda cmd, **kw: {'returncode': 0}           # the host's run folder exists and has no _cmeta yet
    c._sync_repo(CTX, HOST, 'my-repo', entry('bisync', local), resync=False, resync_mode='newer', unlock=False,
                 dry_run=False, con=False, verbose=False, backup=True)
    commands = [x['command'] for x in c.calls]
    assert commands == ['bisync', 'copyto', 'reindex']
    assert c.calls[1]['local'] == str(art / '_cmeta.yaml')
    assert c.calls[1]['remote'] == '/home/u/CMETA/repos/local/result/sync-backup--my-repo/_cmeta.yaml'
    assert c.calls[2]['name'] == 'local' and c.calls[2]['remote'] == '/home/u/CMETA/repos/local'


def test_copy_backs_up_the_host_side_only_and_a_dry_run_marks_nothing(host):
    c, local, art = host
    c._run_local = lambda cmd, **kw: {'returncode': 0}
    c._sync_repo(CTX, HOST, 'my-repo', entry('copy', local), resync=False, resync_mode='newer', unlock=False,
                 dry_run=True, con=False, verbose=False, backup=True)
    call = c.calls[0]
    assert call['command'] == 'copy' and '--dry-run' in call['extra']
    d, = flags(call, '--backup-dir')
    assert d.startswith(f':sftp:/home/u/CMETA/repos/local/result/sync-backup--my-repo/{here()}/')
    assert not flags(call, '--backup-dir1') and not flags(call, '--backup-dir2')
    assert len(c.calls) == 1 and not c.ssh                                                       # a dry run marks nothing


def test_without_the_flag_and_for_git_nothing_changes(host):
    c, local, art = host
    c._sync_repo(CTX, HOST, 'my-repo', entry('bisync', local), resync=False, resync_mode='newer', unlock=False,
                 dry_run=False, con=False, verbose=False)
    assert not [x for x in c.calls[0]['extra'] if x.startswith('--backup-dir')] and not c.ssh
    r = c._sync_repo(CTX, HOST, 'my-repo', entry('git', local), resync=False, resync_mode='newer', unlock=False,
                     dry_run=False, con=False, verbose=False, backup=True)
    assert r['return'] == 1 or len(c.calls) == 1                                                  # git: no rclone call


def test_sync_documents_the_flag():
    text = (REPO_ROOT / 'category/host/api/v1.py').read_text(encoding='utf-8')
    assert 'backup=False,' in text and 'sync-backup--' in text
    readme = (REPO_ROOT / 'category/host/README.md').read_text(encoding='utf-8')
    assert '--backup' in readme and 'sync-backup--<repository>' in readme
