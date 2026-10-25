"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx host key": the key file cx uses to reach a host as this machine finds it - the host's declared "access: key"
as a path or as a reference <category>::<artifact>/<file> (the artifact when it is here, else the copy a secret holds,
else ~/.ssh) - and the public key beside it; a reference in place of the host; the errors. Offline: the categories
the resolution asks are answered by the test.
"""

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
REF = 'fgg.crypt::ssh-x/2026/id_ed25519'


@pytest.fixture
def host(tmp_path):
    """The host category with the hosts of `hosts` and the answers of the utils and secret categories in `answers`."""
    spec = importlib.util.spec_from_file_location('host_key_under_test', REPO_ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    c = module.Category.__new__(module.Category)
    c.hosts = {}
    c.answers = {}
    c.calls = []

    def access(p):
        c.calls.append(p)
        return c.answers[(p['category'].split(',')[0], p['command'])]

    c.cm = SimpleNamespace(error=lambda s: {'return': 1, 'error': s}, catch_error=lambda r: r['return'] > 0, access=access)
    c.cmeta = {'uses_categories': {'utils': 'utils,234ce5e3262e4d52', 'secret': 'secret,9d63451ea1f14010'}}
    c._key_cache = {}
    c._select = lambda ctx, ref, *a, **kw: {'return': 0, 'hosts': c.hosts.get(ref, [])}
    return c


def keys(folder, name='id_ed25519', public=True):
    """A private key file and, when asked, its .pub beside it; returns the private key's path."""
    folder.mkdir(parents=True, exist_ok=True)
    private = folder / name
    private.write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nx\n-----END OPENSSH PRIVATE KEY-----\n')
    if public:
        (folder / (name + '.pub')).write_text('ssh-ed25519 AAAA test\n')
    return private


def test_host_key_as_a_path(host, tmp_path):
    private = keys(tmp_path / 'keys')
    host.hosts['lab'] = [{'alias': 'lab', 'desc': {'access': {'key': str(private)}}}]
    r = host.key_({'control': {}}, 'lab')
    assert r == {'return': 0, 'ref': str(private), 'path': str(private), 'public': str(private) + '.pub'}
    assert host.calls == []

    # no public key beside it
    private = keys(tmp_path / 'alone', public=False)
    host.hosts['alone'] = [{'alias': 'alone', 'desc': {'access': {'key': str(private)}}}]
    r = host.key_({'control': {}}, 'alone')
    assert r['return'] == 0 and r['public'] is None

    # a .pub named directly is its own public key
    host.hosts['pub'] = [{'alias': 'pub', 'desc': {'access': {'key': str(tmp_path / 'keys' / 'id_ed25519.pub')}}}]
    r = host.key_({'control': {}}, 'pub')
    assert r['return'] == 0 and r['public'] == r['path']


def test_host_key_as_a_reference(host, tmp_path):
    """The artifact the reference names is here: the file inside it."""
    art = tmp_path / 'crypt' / 'ssh-x'
    private = keys(art / '2026')
    host.hosts['lab'] = [{'alias': 'lab', 'desc': {'access': {'key': REF}}}]
    host.answers[('utils', 'find_by_cid')] = {'return': 0, 'artifacts': [{'path': str(art)}]}
    r = host.key_({'control': {}}, 'lab')
    assert r == {'return': 0, 'ref': REF, 'path': str(private), 'public': str(private) + '.pub'}
    assert [p['command'] for p in host.calls] == ['find_by_cid'] and host.calls[0]['arg1'] == 'fgg.crypt::ssh-x'

    # the same reference in place of a host, from the cache now
    r2 = host.key_({'control': {}}, REF)
    assert r2 == r and len(host.calls) == 1


def test_host_key_through_a_secret(host, tmp_path, monkeypatch):
    """The artifact is not on this machine: the copy a secret holds, found by "cx secret which"."""
    copy = keys(tmp_path / 'secret' / 'files')
    host.answers[('utils', 'find_by_cid')] = {'return': 0, 'artifacts': []}
    host.answers[('secret', 'which')] = {'return': 0, 'secret': 'git-x', 'path': str(copy)}
    r = host.key_({'control': {}}, REF)
    assert r == {'return': 0, 'ref': REF, 'path': str(copy), 'public': str(copy) + '.pub'}
    assert [p['command'] for p in host.calls] == ['find_by_cid', 'which'] and host.calls[1]['arg1'] == REF

    # no secret either, and nothing in ~/.ssh: an error that names the three places
    host._key_cache.clear()
    host.calls.clear()
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    host.answers[('secret', 'which')] = {'return': 16, 'error': 'no secret holds a copy'}
    r = host.key_({'control': {}}, 'fgg.crypt::ssh-x/2026/id_other')
    assert r['return'] == 1 and 'not on this machine' in r['error'] and 'cx secret which' in r['error']


def test_host_key_errors(host, tmp_path):
    assert 'cx host key <host>' in host.key_({'control': {}}, '')['error']
    assert host.key_({'control': {}}, 'nowhere')['error'] == 'no host matches "nowhere"'
    host.hosts['two'] = [{'alias': 'a', 'desc': {}}, {'alias': 'b', 'desc': {}}]
    assert host.key_({'control': {}}, 'two')['error'] == '"two" matches 2 hosts'
    host.hosts['bare'] = [{'alias': 'bare', 'desc': {'access': {'address': 'x'}}}]
    assert 'declares no access.key' in host.key_({'control': {}}, 'bare')['error']
    host.hosts['gone'] = [{'alias': 'gone', 'desc': {'access': {'key': str(tmp_path / 'missing')}}}]
    assert 'key file not found' in host.key_({'control': {}}, 'gone')['error']
    assert 'must be <category>::<artifact>/<file' in host.key_({'control': {}}, 'fgg.crypt::ssh-x')['error']


def test_run_openssh_names_the_command():
    """The task's documentation names --host and the references; its _cmeta.yaml names the categories asked."""
    import yaml
    text = (REPO_ROOT / 'task/run-openssh/api_v1.py').read_text(encoding='utf-8')
    assert '--host=' in text and 'secret::<alias>' in text and "'command': 'key'" in text
    cmeta = yaml.safe_load((REPO_ROOT / 'task/run-openssh/_cmeta.yaml').read_text(encoding='utf-8'))
    assert cmeta['uses_categories']['host'].startswith('host,') and cmeta['uses_categories']['secret'].startswith('secret,')
