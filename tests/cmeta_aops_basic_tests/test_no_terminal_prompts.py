"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A question of a run when nobody can answer it (a detached job, nohup, a CI step: the standard input is closed
or at its end): input() raises EOFError and the run used to end in a traceback in the middle of an install.
Every prompt goes through ask() of the task API now: no terminal is an error of the run that names the flag
which makes the question unnecessary, never a made-up answer (the default of "install (Y/n)?" may need sudo);
a pause ("Press Enter to continue") is skipped. A piped answer and a terminal are as before, and a quiet run
asks nothing.
"""

import importlib.util
import os
import pathlib
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FAKE = 'zz-noterm-fake'
TASK = 'test-noterm-features'


@pytest.fixture(scope = 'module')
def ask():
    spec = importlib.util.spec_from_file_location('ctask_ask', str(REPO_ROOT / 'category' / 'task' / 'api' / 'ctask.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ask


def no_terminal(monkeypatch, error = EOFError):
    """The standard input of a detached job: input() prints the prompt and raises."""
    def closed(prompt = ''):
        print(prompt, end = '')
        raise error() if error is EOFError else error
    monkeypatch.setattr('builtins.input', closed)


def answers(monkeypatch, *lines):
    it = iter(lines)
    monkeypatch.setattr('builtins.input', lambda prompt = '': next(it))


###################################################################################################
# ask()

def test_an_answer_is_returned_as_typed(ask, monkeypatch):
    answers(monkeypatch, ' Yes ')
    assert ask('Install (Y/n)? ') == {'return': 0, 'answer': ' Yes '}


def test_no_terminal_is_an_error_that_names_the_flag(ask, monkeypatch, capsys):
    no_terminal(monkeypatch)
    r = ask('  INFO: would you like to install tool "x" (Y/n)? ', how = '-q (--quiet) or --install to install without asking')
    assert r['return'] == 1 and r['no_terminal'] is True
    assert 'no answer to "INFO: would you like to install tool "x" (Y/n)?"' in r['error']
    assert 'no terminal' in r['error'] and '-q (--quiet) or --install to install without asking' in r['error']
    assert capsys.readouterr().out.endswith('\n')            # the open prompt line is closed


def test_the_default_flag_is_quiet(ask, monkeypatch):
    no_terminal(monkeypatch)
    assert '-q (--quiet)' in ask('Select: ')['error']


def test_a_pause_is_skipped(ask, monkeypatch):
    no_terminal(monkeypatch)
    assert ask('Press Enter to continue:', optional = True) == {'return': 0, 'answer': '', 'no_terminal': True}


def test_python_without_a_standard_input(ask, monkeypatch):
    no_terminal(monkeypatch, RuntimeError('input(): lost sys.stdin'))
    assert ask('Install (Y/n)? ')['return'] == 1


@pytest.mark.parametrize('error', [OSError(9, 'Bad file descriptor'), OSError(5, 'Input/output error'),
                                   ValueError('I/O operation on closed file.')])
def test_a_standard_input_that_cannot_be_read(ask, monkeypatch, error):
    """An invalid or closed handle (a job without a console on Windows), a terminal that hung up."""
    no_terminal(monkeypatch, error)
    r = ask('Install (Y/n)? ')
    assert r['return'] == 1 and r['no_terminal'] is True


def test_another_error_is_not_swallowed(ask, monkeypatch):
    no_terminal(monkeypatch, RuntimeError('something else'))
    with pytest.raises(RuntimeError, match = 'something else'):
        ask('Install (Y/n)? ')
    no_terminal(monkeypatch, ValueError('something else'))
    with pytest.raises(ValueError, match = 'something else'):
        ask('Install (Y/n)? ')


def test_ctrl_c_is_not_swallowed(ask, monkeypatch):
    no_terminal(monkeypatch, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        ask('Install (Y/n)? ')


def test_a_real_closed_standard_input(ask, monkeypatch):
    """Not a stand-in: a standard input at its end, as `< /dev/null` gives."""
    import io
    monkeypatch.setattr(sys, 'stdin', io.StringIO(''))
    r = ask('Install (Y/n)? ')
    assert r['return'] == 1 and r['no_terminal'] is True
    monkeypatch.setattr(sys, 'stdin', io.StringIO('n\n'))    # a piped answer is read
    assert ask('Install (Y/n)? ') == {'return': 0, 'answer': 'n'}


###################################################################################################
# Through task/setup: the install question

@pytest.fixture(scope = 'module')
def fake_tool(cm):
    """A tool in the throwaway home whose custom install writes a file (nothing is downloaded)."""
    r = cm.access({'category': 'tool', 'command': 'find', 'arg1': FAKE, 'con': False})
    if r['return'] == 16 or not r.get('artifacts'):
        r = cm.access({'category': 'tool', 'command': 'add', 'arg1': f'local:{FAKE}', 'con': False, 'quiet': True, 'yaml': True})
        assert r['return'] == 0, r.get('error')
        tool = pathlib.Path(r['path'])
    else:
        tool = pathlib.Path(r['artifacts'][0]['path'])
    (tool / '_desc.yaml').write_text(textwrap.dedent(f"""
        skip_detect: True
        skip_common_install_uses: True
        names: ['{FAKE}']
        match_version:
          - regex: '([0-9.]+)'
            group: 1
        cmd_get_version: 'echo 1.0'
        """), encoding = 'utf-8')
    (tool / 'api_v1.py').write_text(textwrap.dedent("""
        import os
        from tool_c393ba5c6fa14f66.api.ctool import InitCTool

        class CTool(InitCTool):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, module_file_path = __file__, **kwargs)

            def install(self, ctx, params, cmd = None, *misc):
                os.makedirs('content', exist_ok = True)
                path = os.path.join(os.getcwd(), 'content', 'zz-noterm-fake')
                with open(path, 'wb') as f:
                    f.write(b'0' * 16)
                return {'return': 0, 'install_cmd': None, 'found_path': path}
        """), encoding = 'utf-8')
    return tool


def entries(cm, tag):
    r = cm.access({'category': 'cache', 'command': 'find', 'tags': tag, 'con': False})
    assert r['return'] in (0, 16), r.get('error')
    return r.get('artifacts', []) if r['return'] == 0 else []


def setup_entries(cm):
    return [a for a in entries(cm, 'setup') if a['cmeta'].get('params', {}).get('name', '').startswith(FAKE)]


def states(cm, artifacts):
    r = cm.access({'category': 'cache', 'command': 'classify', 'artifacts': artifacts, 'con': False})
    assert r['return'] == 0, r.get('error')
    return sorted(s['state'] for s in r['states'].values())


@pytest.fixture
def clean_setup(cm, fake_tool):
    def remove():
        for a in setup_entries(cm):
            r = cm.access({'category': 'cache', 'command': 'delete', 'arg1': '*:' + a['cmeta_ref_parts']['artifact_uid'],
                           'force': True, 'con': False})
            assert r['return'] == 0, r.get('error')
    remove()
    yield
    remove()


def setup(cm, **params):
    p = {'category': 'task', 'command': 'run', 'arg1': 'setup', 'name': FAKE, 'con': True, 'quiet': False}
    p.update(params)
    here = os.getcwd()
    try:
        return cm.access(p)
    finally:
        os.chdir(here)


def test_install_question_without_a_terminal(cm, clean_setup, monkeypatch, capsys):
    """The run ends with an error that says how to answer in advance; nothing is installed; the same request
    with -q then resumes the failed attempt in its entry."""
    no_terminal(monkeypatch)
    r = setup(cm)
    out = capsys.readouterr().out
    assert r['return'] > 0, r
    assert 'no terminal' in r['error'] and '-q (--quiet) or --install' in r['error']
    assert 'would you like to install' in out and 'Traceback' not in out
    found = setup_entries(cm)
    assert len(found) == 1 and states(cm, found) == ['failed']
    assert not os.path.isdir(os.path.join(found[0]['path'], 'content'))          # nothing was installed

    r = setup(cm, quiet = True)                                                   # the answer given in advance
    assert r['return'] == 0, r.get('error')
    again = setup_entries(cm)
    assert len(again) == 1 and states(cm, again) == ['ok']
    assert again[0]['cmeta_ref_parts']['artifact_uid'] == found[0]['cmeta_ref_parts']['artifact_uid']
    assert os.path.isfile(os.path.join(again[0]['path'], 'content', FAKE))


def test_install_flag_asks_nothing(cm, clean_setup, monkeypatch):
    no_terminal(monkeypatch)
    r = setup(cm, install = True)
    assert r['return'] == 0, r.get('error')
    assert states(cm, setup_entries(cm)) == ['ok']


def test_a_piped_yes_installs(cm, clean_setup, monkeypatch):
    answers(monkeypatch, 'y')
    r = setup(cm)
    assert r['return'] == 0, r.get('error')
    assert states(cm, setup_entries(cm)) == ['ok']


def test_a_piped_no_is_a_refusal_as_before(cm, clean_setup, monkeypatch, capsys):
    answers(monkeypatch, 'n')
    r = setup(cm)
    assert r['return'] > 0 and 'failed to setup tool' in r['error'] and 'no terminal' not in r['error']
    assert 'Skipped!' in capsys.readouterr().out


###################################################################################################
# Through the task engine: "only one cache entry should exist with such parameters and different features"

TASK_DESC = '''authors: Grigori Fursin
cache: True
cache_params:
  - name
cache_features:
  flavor: "{{params.flavor}}"
'''

TASK_API = '''"""A synthetic task of the cmeta-aops tests: one cache entry per name, the flavor is a feature of it."""
from task_c36be4b9314a45e0.api.ctask import InitCTask


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx: dict, name: str = 'thing', flavor: str = 'a', **kwargs):
        with open('made.txt', 'a') as f:
            f.write(flavor + '\\n')
        return {'return': 0, 'flavor': flavor}
'''


@pytest.fixture(scope = 'module')
def feature_task(cm):
    r = cm.access({'category': 'task', 'command': 'find', 'arg1': TASK, 'con': False})
    if r['return'] == 16 or not r.get('artifacts'):
        r = cm.access({'category': 'task', 'command': 'create', 'arg1': f'local:{TASK}',
                       'meta': {'desc': 'a synthetic task for the prompt tests'}, 'con': False})
        assert r['return'] == 0, r.get('error')
        folder = pathlib.Path(r['path'])
        (folder / '_desc.yaml').write_text(TASK_DESC, encoding = 'utf-8')
        (folder / 'api_v1.py').write_text(TASK_API, encoding = 'utf-8')
    for a in entries(cm, TASK):
        cm.access({'category': 'cache', 'command': 'delete', 'arg1': '*:' + a['cmeta_ref_parts']['artifact_uid'], 'force': True, 'con': False})
    yield
    for a in entries(cm, TASK):
        cm.access({'category': 'cache', 'command': 'delete', 'arg1': '*:' + a['cmeta_ref_parts']['artifact_uid'], 'force': True, 'con': False})


def feature_run(cm, flavor, **params):
    p = {'category': 'task', 'command': 'run', 'arg1': TASK, 'name': 'thing', 'flavor': flavor, 'con': True, 'quiet': False}
    p.update(params)
    here = os.getcwd()
    try:
        return cm.access(p)
    finally:
        os.chdir(here)


def test_feature_update_question_without_a_terminal(cm, feature_task, monkeypatch, capsys):
    r = feature_run(cm, 'a', quiet = True)
    assert r['return'] == 0, r.get('error')
    assert len(entries(cm, TASK)) == 1

    no_terminal(monkeypatch)
    r = feature_run(cm, 'b')                                  # another feature of the one entry: it asks
    out = capsys.readouterr().out
    assert r['return'] > 0, r
    assert 'no terminal' in r['error'] and '-q (--quiet) or --update' in r['error']
    assert 'Update (Y/n)?' in out and 'Traceback' not in out
    found = entries(cm, TASK)
    assert len(found) == 1 and states(cm, found) == ['ok']    # the entry of flavor a is untouched
    assert found[0]['cmeta']['params'].get('flavor') == 'a'

    r = feature_run(cm, 'b', quiet = True)                    # the answer given in advance
    assert r['return'] == 0, r.get('error')
    found = entries(cm, TASK)
    assert len(found) == 1 and found[0]['cmeta']['params'].get('flavor') == 'b'

    answers(monkeypatch, 'n')                                 # a terminal that says no: as before
    r = feature_run(cm, 'c')
    assert r['return'] > 0 and 'cancelled by user' in r['error']
