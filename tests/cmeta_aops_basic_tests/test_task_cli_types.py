"""
The words of the command line, read by what a task's run() expects (cMeta 0.37+): on a run started from the
command line, the words given to a task - on its command line or through --use.<key>.<param> for a sub-task -
become booleans for the parameters run() annotates bool, and the parameters a task describes in its _desc
(`cli_params`: a type, allowed values, a range) are converted and checked. The Python API passes Python values
and is not read; `cli_types: false` in a task's _desc and CMETA_CLI_TYPES=off keep the words text.

The tasks of the test live in a repository of their own, made here and plugged into the test home.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import subprocess
import sys

import pytest

import cmeta.utils

# The reading is the engine's: an older engine has no helper and the words stay text (the task category says so)
pytestmark = pytest.mark.skipif(not hasattr(cmeta.utils, 'typed_params_from_cli'),
                                reason='needs cMeta 0.37 or newer (utils.typed_params_from_cli)')

CHILD_UID = 'c5c5c5c5c5c5c501'
PARENT_UID = 'c5c5c5c5c5c5c502'
OFF_UID = 'c5c5c5c5c5c5c503'
PARENT_CODE_UID = 'c5c5c5c5c5c5c504'

# The child reads its parameters by annotation (as strings: `from __future__ import annotations`) and records them
CHILD_API = '''from __future__ import annotations

import json

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx, flag: bool = False, other: bool = None, count: int = 0, mode: str = None, free = None, out: str = None,
            unparsed = None):
        got = {'flag': flag, 'other': other, 'count': count, 'mode': mode, 'free': free}
        if unparsed is not None:
            got['unparsed'] = unparsed

        if out:
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(got, f)

        return {'return': 0, 'got': got}
'''

PARENT_API = '''from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx):
        return {'return': 0}
'''

# A parent whose CODE calls the child: its values are Python values, a text for a bool parameter is a text
PARENT_CODE_API = '''from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx, out: str = None):
        return self.cm.access({'category': 'task', 'command': 'run', 'arg1': 'c5-child,%s', 'ctx': ctx,
                               'flag': 'C:\\\\a path', 'count': '7', 'out': out, 'con': False, 'quiet': True})
''' % CHILD_UID


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


@pytest.fixture(scope='module')
def tasks(cm, tmp_path_factory):
    """A repository with a child task (bool annotations, described parameters), a parent that uses it, and a task
    with the reading switched off, plugged into the test home."""
    repo = tmp_path_factory.mktemp('repo-c5')

    write(repo / '_cmr.yaml', 'artifact: repo-c5-tasks,3333333333333333\ncategory: repo,f4f792ab40c7498f\n')

    for alias, uid, api, desc in (
            ('c5-child', CHILD_UID, CHILD_API, 'cli_params:\n  count: int\n  mode:\n    values: [fast, full]\n'),
            ('c5-parent', PARENT_UID, PARENT_API, f'uses:\n  - task: c5-child,{CHILD_UID}\n'),
            ('c5-parent-code', PARENT_CODE_UID, PARENT_CODE_API, 'cli_types: true\n'),
            ('c5-off', OFF_UID, CHILD_API, 'cli_types: false\n')):
        write(repo / 'task' / alias / '_cmeta.yaml', f'artifact: {uid}\ncategory: task,c36be4b9314a45e0\n')
        write(repo / 'task' / alias / '_desc.yaml', desc)
        write(repo / 'task' / alias / 'api_v1.py', api)

    r = cm.access({'category': 'repo', 'command': 'plug', 'arg1': str(repo), 'con': False})
    assert r['return'] == 0, r.get('error')

    return repo


def words_of(params):
    """The command line that gives these parameters: --key=value, --key / --key-, --use.<key>.param=value."""
    words = []
    for k, v in params.items():
        if k == 'use':
            words += [f'--use.{key}.{p}={pv}' for key, sub in v.items() for p, pv in sub.items()]
        elif v is True:
            words.append(f'--{k}')
        elif v is False:
            words.append(f'--{k}-')
        else:
            words.append(f'--{k}={v}')
    return words


def run(cm, task, from_cli=True, **params):
    request = {'category': 'task', 'command': 'run', 'arg1': task, 'con': False, 'quiet': True}
    request.update(params)

    if from_cli:
        # What cmeta/cli.py adds to the request it makes: the words of the command line
        request['_cli'] = {'cmd': ['task', 'run', task] + words_of(params)}

    return cm.access(request)


def test_the_python_api_is_not_read(cm, tasks):
    r = run(cm, 'c5-child', from_cli=False, flag='no', other='yes', count='7', mode='fast', free='no')

    assert r['return'] == 0, r.get('error')
    assert r['got'] == {'flag': 'no', 'other': 'yes', 'count': '7', 'mode': 'fast', 'free': 'no'}


def test_the_words_of_the_command_line_are_read(cm, tasks):
    r = run(cm, 'c5-child', flag='no', other='YES', count='7', mode='fast', free='no')

    assert r['return'] == 0, r.get('error')
    assert r['got'] == {'flag': False, 'other': True, 'count': 7, 'mode': 'fast', 'free': 'no'}

    # The flags are what they were
    r = run(cm, 'c5-child', flag=True, other=False)
    assert r['got']['flag'] is True and r['got']['other'] is False


def test_the_words_of_use_reach_a_sub_task(cm, tasks, tmp_path):
    out = tmp_path / 'child.json'

    # --use.c5-child.flag=no --use.c5-child.count=7 --use.c5-child.out=<file> on the parent's command line
    r = run(cm, 'c5-parent', use={'c5-child': {'flag': 'no', 'other': 'on', 'count': '7', 'free': 'no', 'out': str(out)}})

    assert r['return'] == 0, r.get('error')
    assert json.loads(out.read_text(encoding='utf-8')) == {'flag': False, 'other': True, 'count': 7, 'mode': None, 'free': 'no'}


def test_a_value_passed_by_code_to_a_sub_task_is_not_read(cm, tasks, tmp_path):
    out = tmp_path / 'child-by-code.json'

    # The parent's code calls the child with a path for its bool parameter and a text for its int one: both stay as
    # given (before, the path was read as a bool and stopped the run); the --use word of the command line is read
    r = run(cm, 'c5-parent-code', out=str(out), use={'c5-child': {'other': 'on'}})

    assert r['return'] == 0, r.get('error')
    got = json.loads(out.read_text(encoding='utf-8'))
    assert got['flag'] == 'C:\\a path' and got['count'] == '7'
    assert got['other'] is True


def test_errors_name_the_task(cm, tasks):
    for params, text in ((dict(flag='auto'), 'Invalid bool value \'auto\' for \'flag\' of task "c5-child": use yes/no, true/false, on/off, 1/0 or the flags --flag / --flag-'),
                         (dict(count='x'), 'Invalid int value \'x\' for \'count\' of task "c5-child"'),
                         (dict(mode='slow'), 'Invalid value \'slow\' for \'mode\' of task "c5-child": must be one of fast, full')):
        r = run(cm, 'c5-child', **params)

        assert r['return'] > 0 and r['error'] == text, r

    # A bad word for a sub-task stops the parent's run the same way
    r = run(cm, 'c5-parent', use={'c5-child': {'flag': 'auto'}})
    assert r['return'] > 0 and 'for \'flag\' of task "c5-child"' in r['error'], r


def test_the_switches(cm, tasks, monkeypatch):
    r = run(cm, 'c5-off', flag='no', count='7')
    assert r['return'] == 0 and r['got']['flag'] == 'no' and r['got']['count'] == '7'

    monkeypatch.setenv('CMETA_CLI_TYPES', 'off')
    r = run(cm, 'c5-child', flag='no', count='7')
    assert r['return'] == 0 and r['got']['flag'] == 'no' and r['got']['count'] == '7'


###################################################################################################
# The same through the real command line: cx and cxt in a child process (the engine's own parsing of the
# words, the argv it keeps in ctx['origin']['cli'], the exit code and the message), every form of a word

ENTRY = 'import sys; from cmeta.cli import {0}; sys.exit({0}())'


def cli(words, tmp_path, entry='main_cx', env=None):
    """Runs cx (or cxt) with these words in the test home; returns (exit code, output, what the child task got)."""
    out = tmp_path / 'got.json'
    if out.exists():
        out.unlink()

    environ = dict(os.environ)
    environ.update(env or {})
    r = subprocess.run([sys.executable, '-c', ENTRY.format(entry)] + [w.replace('{out}', str(out)) for w in words],
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environ,
                       cwd=str(tmp_path), timeout=300)
    text = r.stdout.decode('utf-8', errors='replace')
    got = json.loads(out.read_text(encoding='utf-8')) if out.exists() else None
    return r.returncode, text, got


CHILD_WORDS = [
    # --key=value: bool words in any case, the described int and values, a parameter without annotation stays text
    (['--flag=no', '--other=YES', '--count=7', '--mode=fast', '--free=no'],
     {'flag': False, 'other': True, 'count': 7, 'mode': 'fast', 'free': 'no'}),
    (['--flag=off', '--other=1', '--count=0'], {'flag': False, 'other': True, 'count': 0, 'mode': None, 'free': None}),
    (['--flag=TRUE', '--other=false'], {'flag': True, 'other': False, 'count': 0, 'mode': None, 'free': None}),

    # The flags are booleans already: --x is True, --x- is False
    (['--flag', '--other-'], {'flag': True, 'other': False, 'count': 0, 'mode': None, 'free': None}),

    # key=value without dashes
    (['flag=no', 'count=7'], {'flag': False, 'other': None, 'count': 7, 'mode': None, 'free': None}),
]


@pytest.mark.parametrize('words, expected', CHILD_WORDS, ids=[' '.join(w) for w, _ in CHILD_WORDS])
def test_cx_reads_the_words(cm, tasks, tmp_path, words, expected):
    code, text, got = cli(['task', 'run', 'c5-child', '--out={out}', '-q'] + words, tmp_path)

    assert code == 0, text
    assert got == expected


def test_cxt_reads_the_words(cm, tasks, tmp_path):
    code, text, got = cli(['c5-child', '--out={out}', '-q', '--flag=no', '--count=3'], tmp_path, entry='main_cxt')

    assert code == 0, text
    assert got['flag'] is False and got['count'] == 3


def test_cx_reads_the_use_words_of_a_sub_task(cm, tasks, tmp_path):
    code, text, got = cli(['task', 'run', 'c5-parent', '-q', '--use.c5-child.out={out}', '--use.c5-child.flag=no',
                           '--use.c5-child.count=7', '--use.c5-child.mode=full'], tmp_path)

    assert code == 0, text
    assert got == {'flag': False, 'other': None, 'count': 7, 'mode': 'full', 'free': None}


def test_cx_keeps_the_values_a_parent_s_code_passes(cm, tasks, tmp_path):
    """The parent's code gives the child a path for its bool parameter (download-file's check_file, 2026-10-14)."""
    code, text, got = cli(['task', 'run', 'c5-parent-code', '--out={out}', '-q', '--use.c5-child.other=on'], tmp_path)

    assert code == 0, text
    assert got['flag'] == 'C:\\a path' and got['count'] == '7' and got['other'] is True


def test_cx_keeps_the_values_of_an_at_file(cm, tasks, tmp_path):
    """An @file holds the values of a request (Python values once read): its texts stay texts, a word next to it
    on the command line is read."""
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'flag': 'no', 'count': '5'}), encoding='utf-8')

    code, text, got = cli(['task', 'run', 'c5-child', '--out={out}', '-q', f'@{request}'], tmp_path)
    assert code == 0, text
    assert got['flag'] == 'no' and got['count'] == '5'

    code, text, got = cli(['task', 'run', 'c5-child', '--out={out}', '-q', f'@{request}', '--count=6'], tmp_path)
    assert code == 0, text
    assert got['flag'] == 'no' and got['count'] == 6


def test_cx_does_not_read_the_words_after_two_dashes(cm, tasks, tmp_path):
    code, text, got = cli(['task', 'run', 'c5-child', '--out={out}', '-q', '--', '--mode=slow', '--flag=maybe'], tmp_path)

    assert code == 0, text
    assert got['mode'] is None and got['flag'] is False and got['unparsed'] == ['--mode=slow', '--flag=maybe']


@pytest.mark.parametrize('words, message', [
    (['--flag=auto'], 'Invalid bool value \'auto\' for \'flag\' of task "c5-child"'),
    (['--count=many'], 'Invalid int value \'many\' for \'count\' of task "c5-child"'),
    (['--mode=slow'], 'Invalid value \'slow\' for \'mode\' of task "c5-child": must be one of fast, full'),
])
def test_cx_stops_on_a_wrong_word_and_names_the_task(cm, tasks, tmp_path, words, message):
    code, text, got = cli(['task', 'run', 'c5-child', '--out={out}', '-q'] + words, tmp_path)

    assert code != 0 and got is None
    assert message in text, text


def test_cx_stops_on_a_wrong_use_word_of_a_sub_task(cm, tasks, tmp_path):
    code, text, got = cli(['task', 'run', 'c5-parent', '-q', '--use.c5-child.out={out}', '--use.c5-child.flag=auto'], tmp_path)

    assert code != 0 and got is None
    assert 'for \'flag\' of task "c5-child"' in text, text


def test_cx_with_the_reading_switched_off(cm, tasks, tmp_path):
    code, text, got = cli(['task', 'run', 'c5-child', '--out={out}', '-q', '--flag=no', '--count=7'], tmp_path,
                          env={'CMETA_CLI_TYPES': 'off'})
    assert code == 0, text
    assert got['flag'] == 'no' and got['count'] == '7'

    code, text, got = cli(['task', 'run', 'c5-off', '--out={out}', '-q', '--flag=no'], tmp_path)
    assert code == 0, text
    assert got['flag'] == 'no'
