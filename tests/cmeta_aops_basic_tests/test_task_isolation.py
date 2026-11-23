"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
Authors: Grigori Fursin.

Offline tests of what keeps the runs of the task engine apart (category/task/api/v2.py, 2026-11-23):
- a run started from inside a task without that task's context takes the pins the outer run was given, and nothing
  else;
- a sub-task that fails on its caller's context gives the caller back what it changed there;
- a storage key asked again in one run with another version than the first request is seen (request_differences);
- a pin given to the outermost run whose storage key no task of the run had is kept and said.
The engine's run() is driven here with a stand-in for _run: the real one needs a cMeta home.
"""

import importlib.util
import os
import pathlib
import types

import pytest

from cmeta.utils import common

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = 'module')
def v2():
    path = REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py'
    spec = importlib.util.spec_from_file_location('task_api_v2_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def engine(v2, runs):
    """The task category with _run replaced: runs(obj, params) is what a task run does."""
    obj = object.__new__(v2.Category)
    obj.cm = types.SimpleNamespace(utils = types.SimpleNamespace(common = common))
    obj._cache_release_attempt = lambda attempt: None
    obj._write_repro = lambda ctx, result: None
    obj._run = lambda params: runs(obj, params)
    return obj


# ---------------------------------------------------------------- the pins of the outer run
def nested(v2, inner_params, outer_use_run = None, shared = False):
    """An outer run that starts an inner one - with a context of its own, or (shared) with the outer's - and what
    the inner one was given."""
    seen = {}

    def runs(obj, params):
        ctx = params['ctx']
        if 'inner' in params:
            seen.update({'use': params.get('use'), 'inherited': ctx.get('use_inherited')})
            return {'return': 0}
        ctx['tasks'] = {'use_run': outer_use_run or {}, 'use': dict(outer_use_run or {})}
        call = dict(inner_params, inner = True, ctx = ctx if shared else {})
        return obj.run(call)

    obj = engine(v2, runs)
    assert obj.run({'ctx': {}})['return'] == 0
    return seen


def test_a_run_of_its_own_takes_the_pins_the_outer_run_was_given(v2):
    seen = nested(v2, {}, {'python': {'version': '3.13'}})
    assert seen['use'] == {'python': {'version': '3.13'}} and seen['inherited'] == {'python': {'version': '3.13'}}


def test_its_own_use_is_over_the_pins_it_takes(v2):
    seen = nested(v2, {'use': {'python': {'version': '3.12'}, 'uv': {'version': '1'}}}, {'python': {'version': '3.13', 'with': {'venv': True}}})
    assert seen['use'] == {'python': {'version': '3.12', 'with': {'venv': True}}, 'uv': {'version': '1'}}


def test_a_list_of_its_own_replaces_the_list_it_would_take(v2):
    # (a task that hands the pins on by hand, as before 2026-11-23, gets no item twice)
    given = {'program': {'flags': ['-O3', '-g'], 'env': {'A': '1'}}}
    assert nested(v2, {'use': {'program': {'flags': ['-O3', '-g']}}}, given)['use'] == given
    assert nested(v2, {'use': {'program': {'flags': ['-O0']}}}, given)['use'] == {'program': {'flags': ['-O0'], 'env': {'A': '1'}}}


def test_nothing_is_taken_without_pins_or_on_a_shared_context_or_when_switched_off(v2, monkeypatch):
    assert nested(v2, {}) == {'use': None, 'inherited': None}
    # the outer run's own context: the pins are there already - the call is left as it is
    assert nested(v2, {}, {'python': {'version': '3.13'}}, shared = True) == {'use': None, 'inherited': None}
    monkeypatch.setenv('CMETA_TASK_INHERIT_PINS', 'off')
    assert nested(v2, {}, {'python': {'version': '3.13'}}) == {'use': None, 'inherited': None}


def test_the_outermost_run_and_a_run_after_it_take_nothing(v2):
    seen = []
    obj = engine(v2, lambda o, params: seen.append(params.get('use')) or {'return': 0})
    obj.run({'ctx': {'tasks': {'use_run': {'x': {'version': '1'}}}}})
    obj.run({'ctx': {}})                       # the first run ended: nothing of it is left for the next one
    assert seen == [None, None]
    assert getattr(v2._ACTIVE, 'runs', []) == []


def test_the_callers_call_is_not_changed(v2):
    call = {'use': {'uv': {'version': '1'}}}

    def runs(obj, params):
        if 'inner' in params:
            return {'return': 0}
        params['ctx']['tasks'] = {'use_run': {'python': {'version': '3.13'}}}
        return obj.run(dict(call, inner = True, ctx = {}))

    engine(v2, runs).run({'ctx': {}})
    assert call == {'use': {'uv': {'version': '1'}}}


# ---------------------------------------------------------------- a sub-task that fails
def failing(v2, tmp_path, how = 'error', switch = None, monkeypatch = None):
    """An outer run whose sub-task, on the same context, changes that context and fails (how: error, exception, ok).
    -> the context after it, the caller's objects, the folder."""
    if switch:
        monkeypatch.setenv('CMETA_TASK_RESTORE', switch)
    mine = {'params': {'mine': 1}, 'cparams': {'c': 1}, 'local': {'x': 2}, 'control': {'con': True}}
    out = {}
    start = os.getcwd()

    def runs(obj, params):
        ctx = params['ctx']
        if 'inner' in params:
            t = ctx['tasks']
            t['params'], t['cparams'], t['local'] = {'theirs': 1}, {}, {}
            ctx['control'] = {'con': False}
            del t['global']['python']                      # as preserve_global_keys takes a result out of the run
            t['global']['new'] = 'made by the sub-task'
            os.chdir(tmp_path)
            if how == 'exception':
                raise RuntimeError('the sub-task broke')
            return {'return': 0} if how == 'ok' else {'return': 1, 'error': 'the sub-task failed'}
        ctx['tasks'] = {'params': mine['params'], 'cparams': mine['cparams'], 'local': mine['local'],
                        'global': {'python': 'the caller\'s python', 'host': 'h'}}
        ctx['control'] = mine['control']
        try:
            out['result'] = obj.run({'ctx': ctx, 'inner': True})
        except RuntimeError as e:
            out['raised'] = str(e)
        out.update({'tasks': dict(ctx['tasks']), 'control': ctx['control'], 'cwd': os.getcwd()})
        return {'return': 0}

    try:
        engine(v2, runs).run({'ctx': {}})
    finally:
        os.chdir(start)
    return out, mine, start


def test_a_failed_sub_task_gives_the_caller_its_state_back(v2, tmp_path):
    out, mine, start = failing(v2, tmp_path)
    assert out['result']['return'] == 1
    t = out['tasks']
    assert t['params'] is mine['params'] and t['cparams'] is mine['cparams'] and t['local'] is mine['local']
    assert out['control'] is mine['control']
    assert t['global'] == {'python': 'the caller\'s python', 'host': 'h', 'new': 'made by the sub-task'}
    assert os.path.samefile(out['cwd'], start)


def test_so_does_one_that_raises(v2, tmp_path):
    out, mine, start = failing(v2, tmp_path, how = 'exception')
    assert out['raised'] == 'the sub-task broke'
    assert out['tasks']['params'] is mine['params'] and out['tasks']['global']['python'] == 'the caller\'s python'
    assert os.path.samefile(out['cwd'], start)


def test_a_sub_task_that_ends_well_is_left_to_the_engines_own_end(v2, tmp_path):
    # (the real _run gives the state back itself when it ends well: run() adds nothing there)
    out, mine, start = failing(v2, tmp_path, how = 'ok')
    assert out['tasks']['params'] == {'theirs': 1} and 'python' not in out['tasks']['global']


def test_switched_off_a_failure_leaves_everything_as_before(v2, tmp_path, monkeypatch):
    out, mine, start = failing(v2, tmp_path, switch = 'off', monkeypatch = monkeypatch)
    assert out['tasks']['params'] == {'theirs': 1} and 'python' not in out['tasks']['global']


def test_the_outermost_run_keeps_what_its_failure_left(v2):
    ctx = {}

    def runs(obj, params):
        params['ctx']['tasks'] = {'params': {'failed': 1}}
        return {'return': 1, 'error': 'x'}

    assert engine(v2, runs).run({'ctx': ctx})['return'] == 1
    assert ctx['tasks']['params'] == {'failed': 1}             # what a person looks at after a failed command


# ---------------------------------------------------------------- the same storage key asked again
def test_what_a_second_request_of_a_storage_key_asks_differently(v2):
    d = v2.request_differences
    first = {'name': 'python', 'version': '3.13.15', 'with': {'venv': True, 'pip': True}}
    assert d(first, {'name': 'python'}) == {}                                       # nothing asked: no difference
    assert d(first, {'name': 'python', 'version': '3.13.15', 'with': {'venv': True}}) == {}
    assert d(first, {'name': 'python', 'version': '3.14.8'}) == {'version': ('3.14.8', '3.13.15')}
    assert d(first, {'name': 'python', 'with': {'venv': False, 'extra': 'x'}}) == {'with.venv': (False, True), 'with.extra': ('x', None)}
    # a version asked where the first request left it open: the first result decides
    assert d({'name': 'python'}, {'name': 'python', 'version': '3.13'}, {'version': '3.13.15'}) == {}
    assert d({'name': 'python'}, {'name': 'python', 'version': '3.13.15'}, {'version': '3.13.15'}) == {}
    assert d({'name': 'python'}, {'name': 'python', 'version': '3.1'}, {'version': '3.13.15'}) == {'version': ('3.1', None)}
    assert d({'name': 'python'}, {'name': 'python', 'version': '3.14'}, {'version': '3.13.15'}) == {'version': ('3.14', None)}
    # a word or a range is not judged here
    assert d({'name': 'python'}, {'name': 'python', 'version': 'latest'}, {'version': '3.13.15'}) == {}
    assert d({'name': 'python'}, {'name': 'python', 'version': '<3.14'}, {'version': '3.13.15'}) == {}
    assert d(None, {'version': '1'}, None) == {'version': ('1', None)} and d({}, None) == {}


def test_a_kept_request_is_what_a_json_file_can_hold(v2):
    # (a context is written to files - --save, a cache entry: keeping the first request must never stop that)
    import json

    class Thing:
        def __repr__(self):
            return '<a thing>'

    kept = v2.plain({'name': 'python', 'version': '3.13', 'with': {'venv': True, 'n': 2, 'x': None}, 'list': ('a', {'b', }),
                     'func': len, 'thing': Thing(), 1: 'a number as a key'})
    assert kept == {'name': 'python', 'version': '3.13', 'with': {'venv': True, 'n': 2, 'x': None}, 'list': ['a', ['b']],
                    'func': '<built-in function len>', 'thing': '<a thing>', '1': 'a number as a key'}
    assert json.loads(json.dumps(kept)) == kept
    # the same request seen again is no difference, whatever it holds
    again = v2.plain({'name': 'python', 'version': '3.13', 'list': ('a', {'b', }), 'thing': Thing()})
    assert v2.request_differences(kept, again) == {}


def test_the_engine_keeps_the_first_request_and_says_a_second_one_with_another_version():
    # the places of _run (a text check: the run itself needs a cMeta home)
    src = (REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py').read_text(encoding = 'utf-8')
    assert src.count("ctx_tasks.setdefault('global_requests', {})[storage_key] = plain(_params)") == 2
    assert "asked = request_differences(first_request, plain(_params), result)" in src
    assert "ctx_tasks.setdefault('reuse_conflicts', [])" in src
    assert "os.environ.get('CMETA_REUSE_CONFLICT')" in src and "'reuse_conflict'" in src


def test_the_word_reuse_conflict_reaches_the_place_the_engine_reads_it(monkeypatch):
    # task/init: --use.init.reuse_conflict=<word>, else CMETA_REUSE_CONFLICT, else the key of config::task - its
    # result is ctx['tasks']['global']['init'], where the engine looks
    path = REPO_ROOT / 'task' / 'init' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8').replace('from task_c36be4b9314a45e0.api.ctask import InitCTask', 'class InitCTask:\n    pass')
    ns = {'__name__': 'task_init', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)

    def init(config = None, **params):
        t = ns['CTask'].__new__(ns['CTask'])
        t.cm = types.SimpleNamespace(access = lambda ii: {'return': 0, 'config_cmeta': dict(config or {})},
                                     catch_error = lambda r: r['return'] > 0)
        return t.run({}, **params)

    monkeypatch.delenv('CMETA_REUSE_CONFLICT', raising = False)
    assert 'reuse_conflict' not in init()
    assert init({'reuse_conflict': 'all'})['reuse_conflict'] == 'all'
    assert init({'reuse_conflict': 'all'}, reuse_conflict = 'error')['reuse_conflict'] == 'error'
    monkeypatch.setenv('CMETA_REUSE_CONFLICT', 'ignore')
    assert init({'reuse_conflict': 'all'})['reuse_conflict'] == 'ignore'
    assert init({'reuse_conflict': 'all'}, reuse_conflict = 'error')['reuse_conflict'] == 'error'
    src = (REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py').read_text(encoding = 'utf-8')
    assert "(ctx_tasks['global'].get('init') or {}).get('reuse_conflict')" in src


# ---------------------------------------------------------------- a pin nothing took
def pinned(v2, use, ran = ('host', 'init', 'python'), inner = None, mark = None, result = None, con = True):
    """An outermost run given pins (use) whose tasks have the storage keys "ran"; inner: the storage keys of a run of
    its own it starts; mark: a key the run sets in its context's tasks. -> its context after it."""
    ctx = {'control': {'con': con}}

    def runs(obj, params):
        c = params['ctx']
        if 'inner' in params:
            c['tasks'] = {'storage_keys': {k: True for k in inner}}
            return {'return': 0}
        c.setdefault('tasks', {})['storage_keys'] = {k: True for k in ran}
        if mark:
            c['tasks'][mark] = True
        if inner is not None:
            obj.run({'ctx': {}, 'inner': True})
        return result or {'return': 0}

    engine(v2, runs).run({'ctx': ctx, 'use': use})
    return ctx


def test_a_pin_whose_storage_key_no_task_had_is_kept_and_said(v2, capsys):
    ctx = pinned(v2, {'python': {'version': '3.13'}, 'pyhton': {'version': '3.12'}})
    assert ctx['tasks']['use_unused'] == ['pyhton']
    out = capsys.readouterr().out
    assert out.count('cMeta info: --use.') == 1
    assert '--use.pyhton was given, and no task of this run has the storage key "pyhton"' in out
    assert 'the storage keys of this run: host, init, python' in out


def test_pins_that_were_taken_are_not_said(v2, capsys):
    ctx = pinned(v2, {'python': {'version': '3.13'}, 'init': {'reuse_conflict': 'error'}})
    assert ctx['tasks']['use_unused'] == [] and 'cMeta info' not in capsys.readouterr().out


def test_a_run_of_its_own_hands_its_storage_keys_up(v2, capsys):
    ctx = pinned(v2, {'gnu-tar': {'version': '1.35'}}, inner = ('gnu-tar', 'host'))
    assert ctx['tasks']['use_unused'] == [] and sorted(ctx['tasks']['storage_keys']) == ['gnu-tar', 'host', 'init', 'python']
    assert 'cMeta info' not in capsys.readouterr().out


def test_pins_that_went_elsewhere_or_a_run_that_failed_are_not_judged(v2, capsys, monkeypatch):
    use = {'nothing-has-this-key': {'version': '1'}}
    assert 'use_unused' not in pinned(v2, use, mark = 'pins_not_judged')['tasks']          # --on, ctask.run_pins, a stop in check_params
    assert 'use_unused' not in pinned(v2, use, result = {'return': 1, 'error': 'x'})['tasks']
    assert 'use_unused' not in pinned(v2, {})['tasks'] and 'use_unused' not in pinned(v2, None)['tasks']
    monkeypatch.setenv('CMETA_TASK_UNUSED_PINS', 'off')
    assert 'use_unused' not in pinned(v2, use)['tasks']
    assert 'cMeta info' not in capsys.readouterr().out


def test_without_a_console_it_is_kept_and_not_printed(v2, capsys):
    assert pinned(v2, {'x': {'version': '1'}}, con = False)['tasks']['use_unused'] == ['x']
    assert capsys.readouterr().out == ''


def test_only_the_outermost_run_judges_and_only_its_own_pins(v2, capsys):
    # (a run of its own inside it takes the pins and says nothing; a pin a task gives its own sub-task is not judged)
    seen = {}

    def runs(obj, params):
        c = params['ctx']
        if 'inner' in params:
            c['tasks'] = {'storage_keys': {'host': True}}
            seen['inner_use'] = params.get('use')
            return {'return': 0}
        c['tasks'] = {'storage_keys': {'host': True, 'python': True}, 'use_run': dict(params['use'], **{'compiler-c': {'name': 'clang'}})}
        obj.run({'ctx': {}, 'inner': True})
        seen['inner_unused'] = 'use_unused' in c['tasks']
        return {'return': 0}

    ctx = {'control': {'con': True}}
    engine(v2, runs).run({'ctx': ctx, 'use': {'python': {'version': '3.13'}}})
    assert seen['inner_use'] == {'python': {'version': '3.13'}, 'compiler-c': {'name': 'clang'}} and seen['inner_unused'] is False
    assert ctx['tasks']['use_unused'] == [] and 'cMeta info' not in capsys.readouterr().out


def test_the_engine_keeps_every_storage_key_and_marks_the_runs_it_does_not_judge():
    # the places of _run (a text check: the run itself needs a cMeta home)
    src = (REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py').read_text(encoding = 'utf-8')
    assert src.count("ctx_tasks.setdefault('storage_keys', {})[storage_key] = True") == 1
    assert src.index("ctx_tasks.setdefault('storage_keys', {})[storage_key] = True") < src.index('# UPDATE PARAMS FROM USE BASED ON STORAGE KEY')
    assert src.count("ctx_tasks['pins_not_judged'] = True") == 2
