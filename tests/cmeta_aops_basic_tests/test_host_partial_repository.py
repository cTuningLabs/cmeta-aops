"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A second orchestrator (2026-10-22): a partial repository, a repository of secrets, and the host keys found through the
secrets - in a throwaway cMeta home, with a content repository whose categories are its own, a repository nested in
its folder, and a vault (secrets: true). Never a real key, never a network: rclone and the commands on hosts are
stand-ins that record what they would do.

- The artifact patterns of a partial repository give anchored rclone rules: an artifact's folder, a path inside it
  with its _cmeta and _desc, a wildcard through the category's shard folders, the definitions of the categories the
  repository holds itself - not those of a repository nested in its folder.
- A bisync of a partial repository runs with the rules it was resynced with, and stops when they changed.
- A repository of secrets is never synced and is pushed only by name, with --secrets.
- A host key named by a reference whose artifact is not on this machine is the copy a secret holds (cx secret which);
  cx secret check --fix makes a copy that others can read owner-only.
"""

import os
import pathlib
import stat
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

KEY = b'-----BEGIN OPENSSH PRIVATE KEY-----\nnot a real key\n-----END OPENSSH PRIVATE KEY-----\n'


def put(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # bytes on every Python: write_text(newline=) exists only since 3.10, and LF must stay LF on Windows
    path.write_bytes(text if isinstance(text, bytes) else text.encode('utf-8'))
    return path


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from cmeta import CMeta

    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))

    # a content repository with a category of its own, sharded by the first four characters of an alias
    repos = tmp_path / 'home' / 'repos'          # where a host's sync entries find a repository by its name
    content = repos / 'content'
    put(content / '_cmr.yaml', 'artifact: content,c0a1b2c3d4e5f607\ncategory: repo,f4f792ab40c7498f\n'
                               'sharding_slices:\n  a1b2c3d4e5f60718:\n  - 4\n')
    put(content / 'category' / 'thing' / '_cmeta.yaml', 'artifact: a1b2c3d4e5f60718\ncategory: category,dd9ea50e7f76467f\n')
    for alias, uid in (('2026a', 'b1b2c3d4e5f60711'), ('2026b', 'b1b2c3d4e5f60712'), ('2025x', 'b1b2c3d4e5f60713')):
        put(content / 'thing' / alias[:4] / alias / '_cmeta.yaml', f'artifact: {alias},{uid}\ncategory: thing,a1b2c3d4e5f60718\n')
        put(content / 'thing' / alias[:4] / alias / '!AI' / 'memory' / 'MEMORY.md', '- one\n')
    put(content / 'thing' / '2026' / '2026a' / 'notes.md', 'notes\n')

    # a repository nested in the content folder (as the engine's internal repository inside a source tree): its
    # category is not one of the content repository
    nested = content / 'thing' / '2026' / '2026a' / 'src' / 'inner'
    put(nested / '_cmr.yaml', 'artifact: inner,d0a1b2c3d4e5f607\ncategory: repo,f4f792ab40c7498f\n')
    put(nested / 'category' / 'other' / '_cmeta.yaml', 'artifact: e1b2c3d4e5f60718\ncategory: category,dd9ea50e7f76467f\n')
    put(nested / 'other' / 'o1' / '_cmeta.yaml', 'artifact: o1,f1b2c3d4e5f60711\ncategory: other,e1b2c3d4e5f60718\n')

    # a vault: secrets: true, a secret holding a copy of a key that lives elsewhere (nowhere.crypt is no category here)
    vault = repos / 'vault'
    put(vault / '_cmr.yaml', 'artifact: vault,e7b2c3d4e5f60718\ncategory: repo,f4f792ab40c7498f\nsecrets: true\n')
    secret = vault / 'secret' / 'ssh-test'
    put(secret / '_cmeta.yaml', 'artifact: ssh-test,f7b2c3d4e5f60718\ncategory: secret,9d63451ea1f14010\n')
    put(secret / '_desc.yaml', 'kind: ssh\nssh:\n  key: files/id_test\n  passphrase: none\n'
                               'files:\n  status: imported\n  from: nowhere.crypt::ssh-test/2026\n  names: [id_test]\n')
    key = put(secret / 'files' / 'id_test', KEY)
    if os.name != 'nt':
        os.chmod(key, 0o644)

    # a host to push to (never reached: everything stops before or is recorded)
    hosts = repos / 'hosts'
    put(hosts / '_cmr.yaml', 'artifact: hosts,a7b2c3d4e5f60718\ncategory: repo,f4f792ab40c7498f\n')
    put(hosts / 'host' / 'far-away' / '_cmeta.yaml', 'artifact: far-away,a8b2c3d4e5f60718\ncategory: host,e4e49c251c814f6d\n')
    put(hosts / 'host' / 'far-away' / '_desc.yaml',
        'type: ssh\nos: ubuntu\naccess:\n  address: far-away.invalid\n  user: u\n  key: nowhere.crypt::ssh-test/2026/id_test\n'
        f'sync:\n  repos_path: /home/u/CMETA/repos\n  workdir: {(tmp_path / "workdir").as_posix()}\n'
        '  repos:\n    - content:\n        artifacts: ["thing::2026*/!AI", "thing::2025x"]\n    - vault\n')

    c = CMeta(home=str(tmp_path / 'home'))
    for repo in (REPO_ROOT, content, nested, vault, hosts):
        r = c.access({'category': 'repo', 'command': 'plug', 'arg1': str(repo), 'con': False})
        assert r['return'] == 0, r

    import importlib.util
    spec = importlib.util.spec_from_file_location('category_host_partial_under_test', str(REPO_ROOT / 'category' / 'host' / 'api' / 'v1.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # the category as the engine makes it: its own meta, and what its __init__ sets
    import logging
    import threading
    import yaml
    host = module.Category.__new__(module.Category)
    host.cm = c
    host.cmeta = yaml.safe_load((REPO_ROOT / 'category' / 'host' / '_cmeta.yaml').read_text(encoding='utf-8-sig'))
    host.logger = logging.getLogger('host-under-test')
    host._key_cache, host._host_cache, host._adb_batch, host._adb_locks = {}, {}, None, {}
    host._adb_lock = threading.Lock()

    # the host as _get_host gives it (that reads the engine's own context of a command)
    desc = yaml.safe_load((hosts / 'host' / 'far-away' / '_desc.yaml').read_text(encoding='utf-8'))
    h = {'alias': 'far-away', 'uid': 'a8b2c3d4e5f60718', 'type': 'ssh', 'desc': desc, 'state': {}, 'path': str(hosts / 'host' / 'far-away')}
    host._get_host = lambda ctx, alias, project=None: {'return': 0, 'host': h}
    return {'cm': c, 'host': host, 'h': h, 'content': content, 'vault': vault, 'key': key, 'tmp': tmp_path}


def test_the_patterns_give_anchored_rules_through_the_shards(world):
    host, content = world['host'], str(world['content'])
    r = host._selection_rules(content, ['thing::2026*/!AI', 'thing::2025x', 'thing::2026a/notes.md'])
    assert r['return'] == 0, r
    assert r['rules'] == ['/_cmr.yaml',
                          '/category/thing/',                     # the category is the repository's own
                          '/thing/2026/2026*/_cmeta.*', '/thing/2026/2026*/_desc.*', '/thing/2026/2026*/!AI/',
                          '/thing/2025/2025x/',
                          '/thing/2026/2026a/_cmeta.*', '/thing/2026/2026a/_desc.*', '/thing/2026/2026a/notes.md']

    # a wildcard before the end of the shard: the shard is a glob too; an alias is found without case, as cMeta does
    assert host._selection_rules(content, ['thing::20*'])['rules'][-1] == '/thing/20*/20*/'
    assert host._selection_rules(content, ['thing::2026A'])['rules'][-1] == '/thing/2026/2026a/'

    # glob characters of a literal name are escaped, a comma (the whitelist's separator) is any one character
    assert host._glob('a [b] {c},d') == 'a \\[b\\] \\{c\\}?d' and host._glob('x*', wildcards=True) == 'x*'

    # an artifact or a category that is not there is an error, not an empty selection
    assert 'no artifact "nope"' in host._selection_rules(content, ['thing::nope'])['error']
    assert 'no category "missing"' in host._selection_rules(content, ['missing::x'])['error']
    assert 'is <category>::<artifact>' in host._selection_rules(content, ['just-a-name'])['error']


def test_a_repository_nested_in_the_folder_is_another_repository(world):
    host, content = world['host'], str(world['content'])

    # the nested repository's category and artifact lie in the content folder, but belong to the inner repository
    r = host._selection_rules(content, ['other::o1'])
    assert r['return'] > 0 and 'no artifact "o1"' in r['error']
    r = host._selection_rules(content, ['thing::2026a'])
    assert not any('other' in rule for rule in r['rules'])


def test_a_bisync_runs_with_the_rules_it_was_resynced_with(world, monkeypatch):
    host = world['host']
    calls = []
    monkeypatch.setattr(host, '_rclone', lambda ctx, h, command, local, remote, **kw: calls.append((command, kw)) or {'return': 0})
    monkeypatch.setattr(host, '_after_partial', lambda *a, **kw: calls.append(('after',)) or {'return': 0})
    h = world['h']
    entry = host._sync_entries(h)['content']
    assert entry['artifacts'] == ['thing::2026*/!AI', 'thing::2025x'] and entry['remote'] == '/home/u/CMETA/repos/content'

    def sync(**kw):
        params = dict(resync=False, resync_mode='path1', unlock=False, dry_run=False, con=False, verbose=False)
        params.update(kw)
        return host._sync_repo({'control': {}}, h, 'content', entry, **params)

    # never synced with these rules: a bisync is refused before rclone; --resync runs, records the rules, writes PARTIAL.md
    r = sync()
    assert r['return'] > 0 and 'run once with --resync' in r['error'] and calls == []
    assert sync(resync=True)['return'] == 0
    command, kw = calls[0]
    assert command == 'resync' and kw['whitelist'][-1] == '/thing/2025/2025x/' and '--ignore-case' in kw['extra']
    assert calls[1] == ('after',)
    assert pathlib.Path(host._selection_file(h, 'content', entry)).read_text(encoding='utf-8').splitlines() == kw['whitelist']

    # the same rules: a plain bisync; a dry run records nothing and writes nothing there
    calls.clear()
    assert sync()['return'] == 0 and calls[0][0] == 'bisync' and calls[1] == ('after',)
    calls.clear()
    assert sync(dry_run=True)['return'] == 0 and [c[0] for c in calls] == ['bisync']

    # other rules: refused until a resync
    entry['artifacts'] = ['thing::2026*']
    calls.clear()
    r = sync()
    assert r['return'] > 0 and 'changed since the last sync' in r['error'] and calls == []


def test_a_repository_of_secrets_is_pushed_only_by_name(world, monkeypatch):
    host = world['host']
    calls = []
    monkeypatch.setattr(host, '_rclone', lambda ctx, h, command, local, remote, **kw: calls.append((command, local, remote, kw)) or {'return': 0})
    monkeypatch.setattr(host, '_status_all', lambda ctx, hosts: [x.update(status='up') for x in hosts])
    ctx = {'control': {}}

    # never synced, even when a host lists it
    h = world['h']
    r = host._sync_repo(ctx, h, 'vault', host._sync_entries(h)['vault'], resync=False, resync_mode='path1', unlock=False,
                        dry_run=False, con=False, verbose=False)
    assert r['return'] > 0 and 'never synced' in r['error'] and calls == []

    # pushed by its alias only with --secrets and the secrets named; a dry run copies nothing for real
    for params in ({}, {'secrets': True}, {'artifacts': 'secret::ssh-test'}, {'dirs': 'secret/', 'secrets': True}):
        r = host.push_(ctx, arg1='far-away', arg2='vault', **params)
        assert r['return'] > 0 and 'holds secrets' in r['error'], params
    assert calls == []
    r = host.push_(ctx, arg1='far-away', arg2='vault', artifacts='secret::ssh-test', secrets=True, dry_run=True)
    assert r['return'] == 0, r
    command, local, remote, kw = calls[0]
    assert (command, remote) == ('copy', '/home/u/CMETA/repos/vault')
    assert kw['whitelist'] == ['/_cmr.yaml', '/secret/ssh-test/'] and '--dry-run' in kw['extra']


def test_a_host_key_is_the_copy_a_secret_holds(world, monkeypatch, capsys):
    c, host, key = world['cm'], world['host'], world['key']

    r = c.access({'category': 'secret', 'command': 'which', 'arg1': 'nowhere.crypt::ssh-test/2026/id_test', 'con': False})
    assert r['return'] == 0 and pathlib.Path(r['path']) == key and r['secret'] == 'ssh-test'
    assert c.access({'category': 'secret', 'command': 'which', 'arg1': 'NOWHERE.crypt,1234567890abcdef::ssh-test/2026/id_test',
                     'con': False})['return'] == 0                          # the same place, spelled otherwise
    r = c.access({'category': 'secret', 'command': 'which', 'arg1': 'nowhere.crypt::ssh-test/2026/id_other', 'con': False})
    assert r['return'] == 16

    # the key of the host: no nowhere.crypt artifact here, the secret's copy - and no warning about ~/.ssh
    r = host._key_path('nowhere.crypt::ssh-test/2026/id_test')
    assert r['return'] == 0 and pathlib.Path(r['path']) == key
    assert 'cMeta warning' not in capsys.readouterr().out

    # without a secret, the old fallback: a file of that name in ~/.ssh, with a warning; neither: an error naming both
    home = world['tmp'] / 'user'
    put(home / '.ssh' / 'id_old', KEY)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    r = host._key_path('nowhere.crypt::ssh-test/2026/id_old')
    assert r['return'] == 0 and pathlib.Path(r['path']) == home / '.ssh' / 'id_old'
    assert 'cMeta warning: the key "nowhere.crypt::ssh-test/2026/id_old" is taken from' in capsys.readouterr().out
    r = host._key_path('nowhere.crypt::ssh-test/2026/id_none')
    assert r['return'] > 0 and 'cx secret which' in r['error']


@pytest.mark.skipif(sys.platform == 'win32', reason='the mode bits: Windows has the ACL, covered by test_fix_ssh_key_permissions')
def test_check_fix_makes_a_copied_key_owner_only(world):
    c, key = world['cm'], world['key']
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o644                      # as a copy to another machine may leave it

    r = c.access({'category': 'secret', 'command': 'check', 'arg1': 'ssh-test', 'con': False})
    assert r['return'] == 0 and stat.S_IMODE(os.stat(key).st_mode) == 0o644, 'check alone changes nothing'
    r = c.access({'category': 'secret', 'command': 'check', 'arg1': 'ssh-test', 'fix': True, 'con': False})
    assert r['return'] == 0 and any('tightened' in row[3] for row in r['rows']), r['rows']
    assert stat.S_IMODE(os.stat(key).st_mode) & 0o077 == 0
