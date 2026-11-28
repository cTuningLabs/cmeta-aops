"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A token secret whose value cMeta makes (--generate) and may show once (--print_key), and a secret made with its
value in one step (cx secret add ... --generate), in a sandbox home with a throwaway vault (never a real secret):

- generate --print_key returns the value that is in the file; without it the answer holds no value;
- store --generate needs no terminal for a plain value, writes it owner-only and tells nothing of it; with
  --print_key the value is in the answer; --print_key without --generate is refused (a typed value is never shown);
  with --password_protected a person is needed, and the sealed file opens with the password to the shown value;
- add with no value word is the common add; with --generate the artifact and its value are made in one step, the
  common command's own words (--yaml, --desc.<key>, --tags) taken as they come; a request that needs a person is
  refused before the artifact is made.
"""

import importlib.util
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SECRET = 'secret,9d63451ea1f14010'


def _module():
    spec = importlib.util.spec_from_file_location('secret_api_v1_generate_under_test',
                                                  REPO_ROOT / 'category' / 'secret' / 'api' / 'v1.py')
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
    vault.mkdir()
    (vault / '_cmr.yaml').write_text('artifact: test-vault,e7b2c3d4e5f60719\ncategory: repo,f4f792ab40c7498f\nsecrets: true\n')

    for alias, uid in (('made-key', 'c7b2c3d4e5f60719'), ('kept-key', 'c7b2c3d4e5f6071a'), ('sealed-key', 'c7b2c3d4e5f6071b')):
        folder = vault / 'secret' / alias
        folder.mkdir(parents=True)
        (folder / '_cmeta.yaml').write_text(f'artifact: {alias},{uid}\ncategory: {SECRET}\n')
        (folder / '_desc.yaml').write_text('kind: token\ntoken:\n  file: files/token\n')

    c = CMeta(home=str(tmp_path / 'home'))
    for repo in (REPO_ROOT, vault):
        r = c.access({'category': 'repo', 'command': 'plug', 'arg1': str(repo), 'con': False})
        assert r['return'] == 0, r

    return c, vault


def secret(c, command, arg1, **params):
    params.update({'category': SECRET, 'command': command, 'arg1': arg1, 'con': False})
    return c.access(params)


def answers(monkeypatch, *typed):
    """A person at a terminal who types these answers, one per prompt."""
    queue = list(typed)

    def fake(prompt=''):
        assert queue, f'one prompt too many: {prompt}'
        return queue.pop(0)

    monkeypatch.setattr(sys, 'stdin', _TTY())
    monkeypatch.setattr('getpass.getpass', fake)
    monkeypatch.setattr('cmeta.utils.sys.read_hidden', fake, raising=False)


def kept_value(vault, alias, name='token'):
    return (vault / 'secret' / alias / 'files' / name).read_text(encoding='utf-8').strip()


############################################################
def test_generate_shows_the_value_only_when_asked(cm):
    c, vault = cm

    r = secret(c, 'generate', 'made-key', quiet=True)
    assert r['return'] == 0, r
    assert 'value' not in r and kept_value(vault, 'made-key') not in str(r)

    r = secret(c, 'generate', 'made-key', force=True, print_key=True, quiet=True)
    assert r['return'] == 0, r
    assert len(r['value']) >= 40 and r['value'] == kept_value(vault, 'made-key')


def test_store_generates_a_plain_value_without_a_terminal(cm):
    c, vault = cm

    r = secret(c, 'store', 'kept-key', generate=True, quiet=True)
    assert r['return'] == 0, r
    value = kept_value(vault, 'kept-key')
    assert r.get('generated') is True and 'value' not in r and value not in str(r) and len(value) >= 40

    r = secret(c, 'store', 'kept-key', generate=True, print_key=True, force=True, quiet=True)
    assert r['return'] == 0, r
    assert r['value'] == kept_value(vault, 'kept-key') != value


def test_a_typed_value_is_never_shown(cm, monkeypatch):
    c, vault = cm

    answers(monkeypatch, 'a-typed-token-of-a-test')
    r = secret(c, 'store', 'kept-key', print_key=True)
    assert r['return'] > 0 and '--generate' in r['error']
    assert not (vault / 'secret' / 'kept-key' / 'files').exists()


def test_a_generated_value_sealed_under_a_password(cm, monkeypatch):
    c, vault = cm

    # a password needs a person: refused in a quiet run, nothing written
    r = secret(c, 'store', 'sealed-key', generate=True, password_protected=True, quiet=True)
    assert r['return'] > 0 and 'terminal' in r['error']
    assert not (vault / 'secret' / 'sealed-key' / 'files').exists()

    answers(monkeypatch, 'a password of a test', 'a password of a test')
    r = secret(c, 'store', 'sealed-key', generate=True, password_protected=True, print_key=True)
    assert r['return'] == 0, r

    sealed = (vault / 'secret' / 'sealed-key' / 'files' / 'token.sealed').read_text(encoding='utf-8')
    assert r['value'] not in sealed
    assert v1.unseal(sealed, 'a password of a test') == r['value']
    assert v1.unseal(sealed, 'another password') is None


def test_add_is_the_common_add_without_a_value_word(cm):
    c, vault = cm

    r = secret(c, 'create', 'test-vault:a-note', yaml=True, desc={'service': 'notes'}, tags='test,note')
    assert r['return'] == 0, r

    folder = vault / 'secret' / 'a-note'
    assert (folder / '_cmeta.yaml').is_file() and not (folder / 'files').exists()
    assert 'service: notes' in (folder / '_desc.yaml').read_text(encoding='utf-8')
    assert 'value' not in r


def test_add_makes_the_artifact_and_its_value_in_one_step(cm):
    c, vault = cm

    r = secret(c, 'create', 'test-vault:a-master', yaml=True, desc={'service': 'files'}, generate=True, print_key=True,
               quiet=True)
    assert r['return'] == 0, r

    folder = vault / 'secret' / 'a-master'
    assert r['value'] == kept_value(vault, 'a-master') and len(r['value']) >= 40

    desc = (folder / '_desc.yaml').read_text(encoding='utf-8')
    assert 'service: files' in desc and 'kind: token' in desc and 'files/token' in desc

    # the alias "add" is the same command
    r = secret(c, 'add', 'test-vault:another-master', yaml=True, generate=True, quiet=True)
    assert r['return'] == 0 and 'value' not in r and len(kept_value(vault, 'another-master')) >= 40


def test_add_asks_for_a_person_before_it_makes_anything(cm):
    c, vault = cm

    for words in ({'password_protected': True}, {'store': True}, {'generate': True, 'password_protected': True}):
        r = secret(c, 'create', 'test-vault:not-made', yaml=True, quiet=True, **words)
        assert r['return'] > 0 and 'terminal' in r['error'], (words, r)
        assert not (vault / 'secret' / 'not-made').exists()

    r = secret(c, 'create', 'test-vault:not-made', yaml=True, print_key=True, quiet=True)
    assert r['return'] > 0 and '--generate' in r['error']
    assert not (vault / 'secret' / 'not-made').exists()
