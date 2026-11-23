"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
Authors: Grigori Fursin.

Offline tests of the pins of a run (category/task/api/ctask.py: pins, use_words - 2026-11-23): what
"--use.<storage key>.<param>=<value>" put into the context is copied for a sub-run of its own and written back as the
command line words of a run in another process - words the engine's own command line reads into the same dict.
"""

import importlib.util
import pathlib

import pytest

from cmeta.utils import cli

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = 'module')
def ctask():
    path = REPO_ROOT / 'category' / 'task' / 'api' / 'ctask.py'
    spec = importlib.util.spec_from_file_location('ctask_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_back(words):
    """The words through the engine's command line, as a task's command line gives them."""
    r = cli.parse_cmd(['task', 'run', 'x'] + list(words))
    assert r['return'] == 0, r
    return r['params'].get('use') or {}


def test_pins_are_a_copy_of_the_runs_use(ctask):
    ctx = {'tasks': {'use': {'python': {'version': '3.12'}}, 'global': {'python': {'path': '/x'}}}}
    got = ctask.pins(ctx)
    assert got == {'python': {'version': '3.12'}}
    got['python']['version'] = '3.14'
    assert ctx['tasks']['use']['python']['version'] == '3.12'       # a copy: a variant's pin never changes the caller's
    assert ctask.pins({}) == {} and ctask.pins(None) == {} and ctask.pins({'tasks': {}}) == {}


def test_the_pins_given_for_the_run_are_kept_apart_from_the_machines_defaults(ctask):
    # as the task engine leaves them: "use" = the machine's defaults + the run's pins, "use_run" = the run's pins alone
    ctx = {'tasks': {'use': {'python': {'tool_path': 'C:/here/python.exe', 'version': '3.12'}}, 'use_run': {'python': {'version': '3.12'}}}}
    assert ctask.run_pins(ctx) == {'python': {'version': '3.12'}}
    assert ctask.use_words(ctask.run_pins(ctx)) == ['--use.python.version=3.12']       # no path of this machine goes along
    assert ctask.run_pins({'tasks': {'use': {'python': {'tool_path': 'x'}}}}) == {} and ctask.run_pins(None) == {}


def test_asking_for_the_runs_pins_says_they_go_where_this_engine_does_not_see(ctask):
    # (the engine then does not judge, at the end of the outermost run, which pins no task took)
    ctx = {'tasks': {'use_run': {'python': {'version': '3.12'}}}}
    got = ctask.run_pins(ctx)
    assert ctx['tasks']['pins_not_judged'] is True
    got['python']['version'] = 'changed'
    assert ctx['tasks']['use_run'] == {'python': {'version': '3.12'}}                 # a copy
    nothing = {'tasks': {'use': {'python': {'tool_path': 'x'}}}}
    assert ctask.run_pins(nothing) == {} and 'pins_not_judged' not in nothing['tasks']


def test_the_engine_records_the_pins_given_for_the_run():
    # the place of the task engine that keeps them (a text check: the engine itself needs a cMeta home to run)
    src = (REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py').read_text(encoding = 'utf-8')
    assert "ctx_tasks['use_run'] = self.cm.utils.common.deep_merge(ctx_tasks.get('use_run') or {}, copy.deepcopy(use), append_lists=True)" in src


def test_words_are_read_back_by_the_command_line_into_the_same_pins(ctask):
    use = {'python': {'version': '3.12.13'},
           'nvcc': {'version': '12.9', 'with': {'debug': True, 'lto': False}},
           'compiler-cpp': {'name': 'gcc-cpp', 'tags': ['a', 'b']},
           'mlpstorage': {'with': {'ref': 'v3.0'}, 'none': None}}
    words = ctask.use_words(use)
    assert set(words) == {'--use.python.version=3.12.13', '--use.nvcc.version=12.9', '--use.nvcc.with.debug', '--use.nvcc.with.lto-',
                          '--use.compiler-cpp.name=gcc-cpp', '--use.compiler-cpp.tags,=a,b', '--use.mlpstorage.with.ref=v3.0'}
    back = read_back(words)
    assert back == {'python': {'version': '3.12.13'}, 'nvcc': {'version': '12.9', 'with': {'debug': True, 'lto': False}},
                    'compiler-cpp': {'name': 'gcc-cpp', 'tags': ['a', 'b']}, 'mlpstorage': {'with': {'ref': 'v3.0'}}}
    assert ctask.use_words({}) == [] and ctask.use_words(None) == []


def test_numbers_travel_as_their_text(ctask):
    # a number given from Python is written as its text; the task that takes it types it by its own signature
    assert ctask.use_words({'uv': {'jobs': 4, 'ratio': 0.5}}) == ['--use.uv.jobs=4', '--use.uv.ratio=0.5']


@pytest.mark.parametrize('use', [{'a.b': {'x': 1}}, {'a': {'x=y': 1}}, {'a': {'x y': 1}}, {'a': {'x-': 1}},
                                 {'a': {'x': ['p,q']}}, {'a': {'x': object()}}, {'a': {'x': [{'k': 1}]}}])
def test_what_a_command_line_cannot_carry_is_refused(ctask, use):
    with pytest.raises(ValueError):
        ctask.use_words(use)
