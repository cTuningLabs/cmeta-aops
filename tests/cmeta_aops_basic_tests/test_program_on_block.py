"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the program category's hand-over of a program's own route: the "on:" block of its _desc.yaml
(requires_os, a route per OS, default) reaches the task category as the control word on_block when the command line
names no --on - as PyYAML reads it (the quoted key 'on', or the boolean True a bare on becomes in YAML 1.1); a
command line with --on, or a program without the block, hands nothing over. The route itself is the task
category's (_route_of, test_run_on.py).
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

TASK_CATEGORY = 'task,c36be4b9314a45e0'
RUNNER = 'compile-and-run-program,8d1d3a1d0b1a4a55'


class FakeFiles:
    def __init__(self, desc):
        self.desc = desc

    def safe_read_yaml_or_json(self, path):
        return {'return': 0, 'data': dict(self.desc)}


class FakeCM:
    """The engine as the program category's run() sees it: the program found, its _desc read, the task run recorded."""
    def __init__(self, desc, found=True):
        self.calls = []
        self.debug = False
        self.utils = type('U', (), {'files': FakeFiles(desc)})()
        self.found = found

    def access(self, i):
        self.calls.append(dict(i))
        if i['category'].startswith('program,') and i['command'] == 'find':
            return {'return': 0, 'artifacts': [{'path': '/programs/test-prog'}] if self.found else []}
        return {'return': 0, 'ran': True}

    def catch_error(self, r):
        return r.get('return', 0) > 0


@pytest.fixture(scope='module')
def module():
    path = REPO_ROOT / 'category' / 'program' / 'api' / 'v1.py'
    src = path.read_text(encoding='utf-8').replace('from cmeta.category import InitCategory',
                                                   'class InitCategory:\n    pass')
    ns = {'__file__': str(path), '__name__': 'program_category_under_test'}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def category(module, desc, found=True):
    c = module['Category'].__new__(module['Category'])
    c.cm = FakeCM(desc, found)
    c.logger = None
    c.cmeta = {'artifact': '22788f3c30d04e6d', 'uses_categories': {'task': TASK_CATEGORY},
               'uses_artifacts': {'task::compile-and-run-program': RUNNER}}
    c._prepare_input_from_params = lambda params, extra={}, base=False: {k: v for k, v in params.items() if k != 'ctx'}
    return c


def run(c, **params):
    r = c.run(dict({'ctx': {'control': {}, 'tasks': {}}, 'arg1': 'test-prog', 'arg2': 'cpu'}, **params))
    assert r['return'] == 0
    return c.cm.calls[-1]


BLOCK = {'requires_os': ['linux'], 'windows': 'docker:sglang', 'darwin': 'docker:sglang'}


def test_the_on_block_reaches_the_task_run_as_pyyaml_reads_it(module):
    for key in ('on', True):                               # the quoted key, or the boolean a bare "on:" becomes
        task_run = run(category(module, {key: BLOCK, 'inherits': ['template-c-cpu']}))
        assert task_run['category'] == TASK_CATEGORY and task_run['arg1'] == RUNNER
        assert task_run['name'] == 'test-prog' and task_run['compute'] == 'cpu'
        assert task_run['on_block'] == BLOCK


def test_a_command_line_with_on_overrides_the_block(module):
    c = category(module, {'on': BLOCK})
    task_run = run(c, on='here')
    assert task_run['on'] == 'here' and 'on_block' not in task_run
    assert not [x for x in c.cm.calls if x['command'] == 'find']   # the _desc is not even read


def test_without_a_block_or_a_program_nothing_is_handed_over(module):
    assert 'on_block' not in run(category(module, {'inherits': ['template-c-cpu']}))
    assert 'on_block' not in run(category(module, {'on': 'not a block'}))
    assert 'on_block' not in run(category(module, {'on': BLOCK}, found=False))
