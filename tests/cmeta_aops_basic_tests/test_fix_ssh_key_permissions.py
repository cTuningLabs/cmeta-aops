"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

fix-ssh-key-permissions with throwaway files (never a real key): a private key is told by its header; on Linux and
macOS the bits others have are found and cleared; on Windows the ACL becomes the user's alone with SYSTEM and
Administrators - including the rules of others set on the file itself, which /inheritance:r keeps (a key made on
GitHub's Windows runner had one for OWNER RIGHTS, S-1-3-4, and cx secret generate refused it, 2026-10-17).
"""

import os
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

KEY = b'-----BEGIN OPENSSH PRIVATE KEY-----\nnot a real key\n-----END OPENSSH PRIVATE KEY-----\n'


@pytest.fixture(scope='module')
def fix():
    path = REPO_ROOT / 'task' / 'fix-ssh-key-permissions' / 'api_v1.py'
    src = path.read_text(encoding='utf-8').replace('from task_c36be4b9314a45e0.api.ctask import InitCTask',
                                                   'class InitCTask: pass')
    ns = {'__name__': 'fix_ssh_key_permissions_under_test', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def test_a_key_is_told_by_its_header(fix, tmp_path):
    key = tmp_path / 'id_x'
    key.write_bytes(KEY)
    note = tmp_path / 'id_x.txt'
    note.write_bytes(KEY)
    pub = tmp_path / 'id_x.pub'
    pub.write_bytes(b'ssh-ed25519 AAAA test\n')

    assert fix['is_private_key'](str(key)) is True
    assert fix['is_private_key'](str(note)) is False         # notes and scripts are never opened
    assert fix['is_private_key'](str(pub)) is False


@pytest.mark.skipif(os.name == 'nt', reason='POSIX modes')
def test_posix_bits_of_others_are_found(fix, tmp_path):
    key = tmp_path / 'id_x'
    key.write_bytes(KEY)
    key.chmod(0o644)
    assert 'readable by others' in fix['posix_problem'](str(key), fix['KEY_FORBIDDEN'])
    key.chmod(0o600)
    assert fix['posix_problem'](str(key), fix['KEY_FORBIDDEN']) == ''


@pytest.mark.skipif(os.name != 'nt', reason='Windows ACLs')
def test_windows_rules_of_others_set_on_the_file_go_too(fix, tmp_path):
    me = fix['user_sid']()
    assert me.startswith('S-')

    key = tmp_path / 'id_x'
    key.write_bytes(KEY)
    # Rules of the file itself (not inherited) for Everyone and OWNER RIGHTS, as another ssh-keygen may leave them.
    # OWNER RIGHTS with full access: a rule that gives the owner less (R) takes away the owner's own right to change
    # the ACL, and only an elevated process could tighten that file (the runner's administrator could)
    for rule in ('*S-1-1-0:R', '*S-1-3-4:F'):
        subprocess.run(['icacls', str(key), '/grant', rule], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
    others, error = fix['windows_readers'](str(key), me)
    assert 'S-1-3-4' in others and 'S-1-1-0' in others

    assert fix['windows_tighten'](str(key), me, False) == []
    others, error = fix['windows_readers'](str(key), me)
    assert others == [] and error == []
    assert key.read_bytes() == KEY                            # the user still reads it
