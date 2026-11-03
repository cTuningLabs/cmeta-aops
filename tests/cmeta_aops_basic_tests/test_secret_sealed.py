"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A token kept with a password (cx secret store --password_protected) and given to a command's environment alone
(cx secret run), in a sandbox home with a throwaway vault (never a real secret):

- seal / unseal: the value comes back with its password only; a wrong password, a changed byte, changed parameters
  or tag are refused; two seals of one value differ; the file holds nothing of the value;
- store refuses without a person at a terminal (no TTY, -q); with one (the prompt answered by the test) it writes
  files/token.sealed owner-only and the keys of _desc.yaml, and --force replaces a value;
- check sees the sealed file without the password, and --unlock says whether a password opens it;
- run gives the value to the command's environment (the command prints its hash, never the value), asks again after
  a wrong password, gives up after three, and never runs the command then; a quiet run is refused for a sealed
  value and works for a plain one; a password_protected secret kept in plain text is refused.

The console window of run (Windows, a caller without a terminal) needs a person and is not run here.
"""

import base64
import hashlib
import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SECRET = 'secret,9d63451ea1f14010'
FAST = {'n': 2 ** 10, 'r': 8, 'p': 1}

TOKEN = 'pypi-AgEIcHlwaS5vcmcCJDAwMDAwMDAwLTAwMDAtMDAwMC0wMDAwLTAwMDAwMDAwMDAwMAACKlszLCJ0ZXN0Il0AAAYgdGVzdA-only-a-test'


def _module():
    spec = importlib.util.spec_from_file_location('secret_api_v1_under_test', REPO_ROOT / 'category' / 'secret' / 'api' / 'v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v1 = _module()


class _TTY:
    """A stdin that says a person is there (the prompts themselves are answered by the test)."""

    def isatty(self):
        return True

    def readline(self):
        return '\n'


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    from cmeta import CMeta

    for var in ('CMETA_HOME', 'CMETA_HOME2', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('CMETA_HOME', str(tmp_path / 'home'))

    vault = tmp_path / 'vault'
    for alias, uid in (('test-token', 'a7b2c3d4e5f60718'), ('plain-token', 'b7b2c3d4e5f60718')):
        (vault / 'secret' / alias).mkdir(parents=True)
        (vault / 'secret' / alias / '_cmeta.yaml').write_text(f'artifact: {alias},{uid}\ncategory: {SECRET}\n')
    (vault / '_cmr.yaml').write_text('artifact: test-vault,e7b2c3d4e5f60719\ncategory: repo,f4f792ab40c7498f\nsecrets: true\n')
    (vault / 'secret' / 'plain-token' / '_desc.yaml').write_text('kind: token\ntoken:\n  file: files/token\n')
    (vault / 'secret' / 'plain-token' / 'files').mkdir()
    (vault / 'secret' / 'plain-token' / 'files' / 'token').write_text('plain-value-for-a-test\n')

    c = CMeta(home=str(tmp_path / 'home'))
    for repo in (REPO_ROOT, vault):
        r = c.access({'category': 'repo', 'command': 'plug', 'arg1': str(repo), 'con': False})
        assert r['return'] == 0, r
    return c, vault


def answers(monkeypatch, *typed):
    """A person at a terminal who types these answers, one per prompt; returns the prompts seen."""
    seen = []
    queue = list(typed)

    def fake(prompt=''):
        seen.append(prompt)
        assert queue, f'one prompt too many: {prompt}'
        return queue.pop(0)

    monkeypatch.setattr(sys, 'stdin', _TTY())
    monkeypatch.setattr('getpass.getpass', fake)
    return seen


def secret(c, command, arg1='test-token', **params):
    params.update({'category': SECRET, 'command': command, 'arg1': arg1, 'con': False})
    return c.access(params)


def env_hash_cmd(name):
    """A command that prints the SHA-256 of a variable of its environment (never the value)."""
    return [sys.executable, '-c', f'import hashlib,os; print("hash", hashlib.sha256(os.environ.get("{name}", "").encode()).hexdigest())']


############################################################
def test_seal_round_trip_and_refusals():
    for value in ('x', TOKEN, 'é' * 700, 'a' * 33):
        text = v1.seal(value, 'short pw', FAST)
        assert v1.unseal(text, 'short pw') == value
        assert v1.unseal(text, 'short pW') is None
        # (a value of one letter may well occur in base64)
        assert (len(value) < 8 or value not in text) and 'short pw' not in text
        assert v1.sealed_head(text)['format'] == v1.SEALED

    text = v1.seal(TOKEN, 'pw', FAST)
    assert text != v1.seal(TOKEN, 'pw', FAST)              # a new salt and nonce each time

    d = json.loads(text)
    data = bytearray(base64.b64decode(d['data']))
    data[5] ^= 1
    changed = dict(d, data=base64.b64encode(bytes(data)).decode())
    assert v1.unseal(json.dumps(changed), 'pw') is None   # a changed byte
    assert v1.unseal(json.dumps(dict(d, n=2 ** 11)), 'pw') is None
    assert v1.unseal(json.dumps(dict(d, tag=d['data'][:44])), 'pw') is None
    with pytest.raises(ValueError):
        v1.unseal(json.dumps(dict(d, n=1000)), 'pw')      # not a power of two
    with pytest.raises(ValueError):
        v1.unseal('plain text', 'pw')
    assert v1.sealed_head('plain-value') is None

    # the default parameters (scrypt n=2^17, 128 MiB) work on this Python
    assert v1.unseal(v1.seal('v', 'pw'), 'pw') == 'v'


def test_store_needs_a_person(cm, monkeypatch, tmp_path):
    c, vault = cm
    r = secret(c, 'store', password_protected=True)
    assert r['return'] > 0 and 'terminal' in r['error']

    answers(monkeypatch)
    r = secret(c, 'store', password_protected=True, quiet=True)
    assert r['return'] > 0 and 'terminal' in r['error']

    # the command line with its input from the null device (an agent's "< NUL"): on Windows NUL says isatty, but it
    # is no console - refused at once instead of a prompt nobody sees
    p = subprocess.run([sys.executable, '-m', 'cmeta', 'secret', 'store', 'test-token', '--password_protected'],
                       env=dict(os.environ, CMETA_HOME=str(tmp_path / 'home')), stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    assert p.returncode == 1 and b'terminal' in p.stdout, p.stdout
    assert not (vault / 'secret' / 'test-token' / 'files').exists()


def test_store_check_and_run(cm, monkeypatch, tmp_path):
    c, vault = cm
    folder = vault / 'secret' / 'test-token'

    # store: the value, the password twice (the engine's own copy of the category: the default scrypt parameters)
    seen = answers(monkeypatch, TOKEN, 'pw-1', 'pw-1')
    r = secret(c, 'store', password_protected=True)
    assert r['return'] == 0, r
    assert len(seen) == 3
    sealed = folder / 'files' / 'token.sealed'
    assert sealed.is_file() and TOKEN not in sealed.read_text()
    if os.name != 'nt':
        assert stat.S_IMODE(sealed.stat().st_mode) == 0o600
    desc = (folder / '_desc.yaml').read_text()
    assert 'kind: token' in desc and 'password_protected: true' in desc and 'file: files/token.sealed' in desc

    # a second store is refused without --force; two different passwords write nothing
    answers(monkeypatch)
    assert secret(c, 'store', password_protected=True)['return'] > 0
    answers(monkeypatch, 'other', 'a', 'b')
    r = secret(c, 'store', password_protected=True, force=True)
    assert r['return'] > 0 and 'differ' in r['error']

    # check: sealed, seen without the password; --unlock with the right and a wrong password
    r = secret(c, 'check')
    row = [x for x in r['rows'] if x[1] == 'token file'][0]
    assert row[2] == 'ok' and 'sealed' in row[3]
    answers(monkeypatch, 'pw-1')
    row = [x for x in secret(c, 'check', unlock=True)['rows'] if x[1] == 'token file'][0]
    assert row[2] == 'ok' and 'opens it' in row[3]
    answers(monkeypatch, 'nope')
    row = [x for x in secret(c, 'check', unlock=True)['rows'] if x[1] == 'token file'][0]
    assert row[2] == 'WRONG PW'

    # run: a wrong password, then the right one; the command sees the value in its environment alone
    log = tmp_path / 'run.log'
    seen = answers(monkeypatch, 'wrong', 'pw-1')
    r = secret(c, 'run', env={'MY_TOKEN': '{secret}', 'MY_USER': '__token__'}, cmd=env_hash_cmd('MY_TOKEN'), log=str(log))
    assert r['return'] == 0, r
    assert len(seen) == 2 and 'MY_TOKEN' not in os.environ
    text = log.read_text()
    assert 'hash ' + hashlib.sha256(TOKEN.encode()).hexdigest() in text and text.strip().endswith('SUCCESS')
    assert TOKEN not in text and TOKEN not in json.dumps(r)

    # three wrong passwords: an error, and the command never ran
    log.unlink()
    answers(monkeypatch, 'a', 'b', 'c')
    r = secret(c, 'run', env={'MY_TOKEN': '{secret}'}, cmd=env_hash_cmd('MY_TOKEN'), log=str(log))
    assert r['return'] > 0 and 'does not open' in r['error']
    assert 'hash ' not in log.read_text()

    # a quiet run never asks: refused
    monkeypatch.setattr(sys, 'stdin', _TTY())
    r = secret(c, 'run', env={'MY_TOKEN': '{secret}'}, cmd=env_hash_cmd('MY_TOKEN'), quiet=True)
    assert r['return'] > 0

    # --force: a new value in plain text; the sealed file goes and password_protected leaves _desc.yaml
    answers(monkeypatch, 'plain-2')
    r = secret(c, 'store', force=True)
    assert r['return'] == 0, r
    assert (folder / 'files' / 'token').is_file() and not sealed.exists()
    assert 'password_protected' not in (folder / '_desc.yaml').read_text()


def test_run_plain_token_and_mistakes(cm, monkeypatch, tmp_path):
    c, vault = cm
    log = tmp_path / 'plain.log'

    # a plain token: no prompt, also in a quiet run
    r = secret(c, 'run', arg1='plain-token', env={'T': 'Bearer {secret}'}, cmd=env_hash_cmd('T'), log=str(log), quiet=True)
    assert r['return'] == 0, r
    assert hashlib.sha256(b'Bearer plain-value-for-a-test').hexdigest() in log.read_text()

    # no variable for the value, no command
    assert secret(c, 'run', arg1='plain-token', env={'T': 'x'}, cmd=env_hash_cmd('T'))['return'] > 0
    assert secret(c, 'run', arg1='plain-token', env={'T': '{secret}'})['return'] > 0

    # the command fails: its exit code is the verdict
    r = secret(c, 'run', arg1='plain-token', env={'T': '{secret}'}, cmd=[sys.executable, '-c', 'raise SystemExit(3)'], log=str(log), quiet=True)
    assert r['return'] > 0 and r.get('exit_code') == 3

    # declared password_protected but kept in plain text: refused, never used
    desc = vault / 'secret' / 'plain-token' / '_desc.yaml'
    desc.write_text('kind: token\npassword_protected: true\ntoken:\n  file: files/token\n')
    answers(monkeypatch)
    r = secret(c, 'run', arg1='plain-token', env={'T': '{secret}'}, cmd=env_hash_cmd('T'), log=str(log))
    assert r['return'] > 0 and 'plain text' in r['error']
    row = [x for x in secret(c, 'check', arg1='plain-token')['rows'] if x[1] == 'token file'][0]
    assert row[2] == 'PLAIN'
