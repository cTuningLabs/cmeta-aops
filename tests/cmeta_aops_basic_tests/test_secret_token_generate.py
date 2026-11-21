"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx secret generate on a token secret (a sandbox home, never a real secret): a random value in its token file, the value
never in the answer, its SHA-256 there; a second generate refused without --force, a new value with it; a token taken
from a variable, or sealed by a password, refused.
"""

import hashlib
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    from cmeta import CMeta

    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))
    vault = tmp_path / 'vault'
    vault.mkdir()
    (vault / '_cmr.yaml').write_text('artifact: test-vault,e7b2c3d4e5f60719\ncategory: repo,f4f792ab40c7498f\nsecrets: true\n')
    for alias, uid, desc in (('client-key', 'f7b2c3d4e5f60719', 'kind: token\ntoken:\n  file: files/token\n'),
                             ('from-env', 'f7b2c3d4e5f6071a', 'kind: token\ntoken:\n  env: SOME_VARIABLE\n'),
                             ('sealed', 'f7b2c3d4e5f6071b', 'kind: token\npassword_protected: true\ntoken:\n  file: files/token.sealed\n')):
        folder = vault / 'secret' / alias
        folder.mkdir(parents=True)
        (folder / '_cmeta.yaml').write_text('artifact: %s,%s\ncategory: secret,9d63451ea1f14010\n' % (alias, uid))
        (folder / '_desc.yaml').write_text(desc)
    c = CMeta(home=str(tmp_path / 'home'))
    for repo in (REPO_ROOT, vault):
        r = c.access({'category': 'repo', 'command': 'plug', 'arg1': str(repo), 'con': False})
        assert r['return'] == 0, r
    return c, vault


def generate(c, alias, **params):
    params.update({'category': 'secret,9d63451ea1f14010', 'command': 'generate', 'arg1': alias, 'con': False, 'quiet': True})
    return c.access(params)


def test_a_token_secret_gets_a_random_value_and_only_its_sha256_is_told(cm):
    c, vault = cm
    token = vault / 'secret' / 'client-key' / 'files' / 'token'

    r = generate(c, 'client-key')
    assert r['return'] == 0, r
    value = token.read_text(encoding='utf-8').strip()
    assert len(value) >= 40 and r['sha256'] == hashlib.sha256(value.encode()).hexdigest()
    assert value not in str(r)

    assert generate(c, 'client-key')['return'] == 1                          # not over an existing value without --force
    r = generate(c, 'client-key', force=True)
    assert r['return'] == 0 and token.read_text(encoding='utf-8').strip() != value

    r = generate(c, 'from-env')
    assert r['return'] == 1 and 'SOME_VARIABLE' in r['error']
    r = generate(c, 'sealed')
    assert r['return'] == 1 and 'password' in r['error']


def check(c, alias, **params):
    params.update({'category': 'secret,9d63451ea1f14010', 'command': 'check', 'arg1': alias, 'con': False, 'quiet': True})
    r = c.access(params)
    assert r['return'] == 0, r
    return [row for row in r['rows'] if row[1] == 'token file'][0]


def test_check_says_open_for_a_file_others_can_read_until_fix(cm):
    # 2026-11-21: cx secret check said "ok" beside the note "readable by ..."; a file others can read is OPEN now
    import os
    import platform
    c, vault = cm
    assert generate(c, 'client-key')['return'] == 0
    assert check(c, 'client-key')[2] == 'ok'                                   # generate makes it owner-only

    token = vault / 'secret' / 'client-key' / 'files' / 'token'
    token.unlink()
    token.write_text('a-value-written-by-hand' + chr(10), encoding='utf-8')    # the folder's permissions: others may read
    if platform.system() != 'Windows':
        os.chmod(token, 0o644)
    row = check(c, 'client-key')
    if 'readable' not in row[3] and 'mode' not in row[3]:
        pytest.skip('this test folder lets nobody else read a new file: nothing to show (%s)' % row[3])
    assert row[2] == 'OPEN', row

    row = check(c, 'client-key', fix=True)
    assert row[2] == 'ok' and row[3].startswith('tightened'), row
    assert check(c, 'client-key')[2] == 'ok'
