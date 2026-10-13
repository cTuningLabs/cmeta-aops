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

import pytest

import cmeta.utils

# The reading is the engine's: an older engine has no helper and the words stay text (the task category says so)
pytestmark = pytest.mark.skipif(not hasattr(cmeta.utils, 'typed_params_from_cli'),
                                reason='needs cMeta 0.37 or newer (utils.typed_params_from_cli)')

CHILD_UID = 'c5c5c5c5c5c5c501'
PARENT_UID = 'c5c5c5c5c5c5c502'
OFF_UID = 'c5c5c5c5c5c5c503'

# The child reads its parameters by annotation (as strings: `from __future__ import annotations`) and records them
CHILD_API = '''from __future__ import annotations

import json

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx, flag: bool = False, other: bool = None, count: int = 0, mode: str = None, free = None, out: str = None):
        got = {'flag': flag, 'other': other, 'count': count, 'mode': mode, 'free': free}

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
            ('c5-off', OFF_UID, CHILD_API, 'cli_types: false\n')):
        write(repo / 'task' / alias / '_cmeta.yaml', f'artifact: {uid}\ncategory: task,c36be4b9314a45e0\n')
        write(repo / 'task' / alias / '_desc.yaml', desc)
        write(repo / 'task' / alias / 'api_v1.py', api)

    r = cm.access({'category': 'repo', 'command': 'plug', 'arg1': str(repo), 'con': False})
    assert r['return'] == 0, r.get('error')

    return repo


def run(cm, task, from_cli=True, **params):
    request = {'category': 'task', 'command': 'run', 'arg1': task, 'con': False, 'quiet': True}
    request.update(params)

    if from_cli:
        request['_cli'] = {'cmd': ['task', 'run', task]}       # what cmeta/cli.py adds to the request it makes

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
