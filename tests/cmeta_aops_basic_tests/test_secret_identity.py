"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

cx secret generate / use / render with a throwaway git identity in a sandbox home (never a real secret): a key pair
without a passphrase made at the files the identity names, a second generate refused without --force, the identity
written into a scratch clone, a commit signed with it and verified, the include file rendered and read back by git.
Needs ssh-keygen and git (OpenSSH 8.2+, git 2.34+ for ssh signatures); skipped where they are missing.
"""

import os
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not shutil.which('ssh-keygen') or not shutil.which('git'), reason='ssh-keygen and git are needed')

DESC = '''kind: git
identity:
  name: Test Identity
  email: test@example.invalid
ssh:
  key: files/id_ed25519_test
  public_key: files/id_ed25519_test.pub
  passphrase: none
  hosts: [github.com]
signing:
  format: ssh
  key: files/id_ed25519_test.pub
  allowed_signers: files/allowed_signers
  sign_commits: true
'''


def git(*args, cwd=None):
    return subprocess.run(['git'] + list(args), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=120).stdout.decode('utf-8', 'replace')


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    from cmeta import CMeta

    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'GIT_CONFIG_GLOBAL'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))
    # git must not read or write the user's own global config here
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(tmp_path / 'global.gitconfig'))

    vault = tmp_path / 'vault'
    (vault / 'secret' / 'test-identity').mkdir(parents=True)
    (vault / '_cmr.yaml').write_text('artifact: test-vault,e7b2c3d4e5f60718\ncategory: repo,f4f792ab40c7498f\nsecrets: true\n')
    (vault / 'secret' / 'test-identity' / '_cmeta.yaml').write_text('artifact: test-identity,f7b2c3d4e5f60718\n'
                                                                    'category: secret,9d63451ea1f14010\n')
    (vault / 'secret' / 'test-identity' / '_desc.yaml').write_text(DESC)

    c = CMeta(home=str(tmp_path / 'home'))
    for repo in (REPO_ROOT, vault):
        r = c.access({'category': 'repo', 'command': 'plug', 'arg1': str(repo), 'con': False})
        assert r['return'] == 0, r
    return c, vault


def secret(c, command, **params):
    params.update({'category': 'secret,9d63451ea1f14010', 'command': command, 'arg1': 'test-identity', 'con': False, 'quiet': True})
    return c.access(params)


def test_generate_use_render(cm, tmp_path):
    c, vault = cm
    files = vault / 'secret' / 'test-identity' / 'files'

    r = secret(c, 'generate', comment='pytest')
    assert r['return'] == 0, r
    assert (files / 'id_ed25519_test').is_file() and (files / 'id_ed25519_test.pub').is_file()
    assert 'ED25519' in r['fingerprint']
    assert secret(c, 'generate')['return'] == 1                       # not over an existing pair without --force

    pub = (files / 'id_ed25519_test.pub').read_text().strip()
    (files / 'allowed_signers').write_text(f'test@example.invalid {pub}\n')

    clone = tmp_path / 'clone'
    git('init', '-q', str(clone))
    r = secret(c, 'use', repo=str(clone))
    assert r['return'] == 0, r
    assert git('config', '--local', 'user.email', cwd=clone).strip() == 'test@example.invalid'
    assert 'IdentitiesOnly=yes' in git('config', '--local', 'core.sshCommand', cwd=clone)

    git('commit', '--allow-empty', '-q', '-m', 'signed', cwd=clone)
    assert 'Good "git" signature' in git('log', '--show-signature', '-1', cwd=clone)

    out = tmp_path / 'test.gitconfig'
    r = secret(c, 'render', out=str(out))
    assert r['return'] == 0, r
    listed = git('config', '-f', str(out), '--list')
    assert 'user.name=Test Identity' in listed and 'commit.gpgsign=true' in listed
    assert 'core.sshcommand=ssh -i "' in listed.lower()

    # the user's global config was never touched
    assert not (tmp_path / 'global.gitconfig').exists() or 'test@example.invalid' not in (tmp_path / 'global.gitconfig').read_text()
