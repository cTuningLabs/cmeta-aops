"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A conda base or a conda environment as the python of a request (the corner cases found on 2026-10-07):
detect-python-env calls a venv (bin/activate), a conda base (condabin/) and - on Windows, where python.exe
sits at the root - a conda root virtual, and a conda environment (envs/<name>, no condabin) not;
tool/python's check_features never takes the interpreter a venv is to be made on (python_base) as the venv
itself, even where it is "virtual" (a conda base on Linux and macOS). Offline: planted folders, a fake engine.
"""

import os
import types

import pytest

WIN = os.name == 'nt'
BIN = 'Scripts' if WIN else 'bin'
PY = 'python.exe' if WIN else 'python'
ACTIVATE = 'activate.bat' if WIN else 'activate'
CONDA = 'conda.bat' if WIN else 'conda'


@pytest.fixture(scope = 'module')
def detect(task_namespace):
    return task_namespace('detect-python-env')


def touch(path):
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text('')
    return path


def run_detect(ns, python_path):
    t = ns['CTask'].__new__(ns['CTask'])
    t.cm = types.SimpleNamespace(debug = False, error = lambda msg, code = 1: {'return': code, 'error': msg})
    return t.run({'control': {}, 'tasks': {'nested_call': 0}}, python_path = str(python_path))


def test_detect_python_env_layouts(detect, tmp_path):
    """One classifier for the detection and the provenance record: venv (pyvenv.cfg; an older virtualenv by its
    activate script), conda-base (conda-meta/ and condabin/), conda-env (conda-meta/ alone, under envs/ or
    anywhere), system; the root is the folder above bin/, or the python's own folder (a conda root on Windows)."""
    # a venv: pyvenv.cfg at the root, the activate script next to the python
    venv_py = touch(tmp_path / 'venv' / BIN / PY)
    touch(tmp_path / 'venv' / BIN / ACTIVATE)
    (tmp_path / 'venv' / 'pyvenv.cfg').write_text('home = somewhere\n')
    r = run_detect(detect, venv_py)
    assert r['is_virtual'] and r['kind'] == 'venv' and os.path.normcase(r['env_path']) == os.path.normcase(str(tmp_path / 'venv'))
    assert os.path.normcase(r['script_path']) == os.path.normcase(str(tmp_path / 'venv' / BIN / ACTIVATE))

    # an older virtualenv: the activate script alone
    old_py = touch(tmp_path / 'old' / BIN / PY)
    touch(tmp_path / 'old' / BIN / ACTIVATE)
    assert run_detect(detect, old_py)['kind'] == 'venv'

    # a conda environment: conda-meta/ and no condabin/ - under envs/ of a base, or anywhere ("conda create -p",
    # cMeta's .conda-env in a python entry); no activation script
    env_py = touch(tmp_path / 'mf' / 'envs' / 'x' / BIN / PY)
    (tmp_path / 'mf' / 'envs' / 'x' / 'conda-meta').mkdir(parents = True)
    r = run_detect(detect, env_py)
    assert r['is_virtual'] and r['kind'] == 'conda-env' and r['script_path'] is None
    made_py = touch(tmp_path / 'entry' / '.conda-env' / BIN / PY)
    (tmp_path / 'entry' / '.conda-env' / 'conda-meta').mkdir(parents = True)
    assert run_detect(detect, made_py)['kind'] == 'conda-env'

    # a conda base, POSIX layout: python in bin/, conda-meta/ and condabin/ at the root
    base_py = touch(tmp_path / 'mf' / BIN / PY)
    (tmp_path / 'mf' / 'conda-meta').mkdir(parents = True)
    touch(tmp_path / 'mf' / 'condabin' / CONDA)
    r = run_detect(detect, base_py)
    assert r['is_virtual'] and r['kind'] == 'conda-base' and os.path.normcase(r['env_path']) == os.path.normcase(str(tmp_path / 'mf'))

    # a conda base, Windows layout: python.exe at the root, next to condabin\ and conda-meta\ (virtual there too)
    root_py = touch(tmp_path / 'mc' / PY)
    (tmp_path / 'mc' / 'conda-meta').mkdir(parents = True)
    touch(tmp_path / 'mc' / 'condabin' / CONDA)
    r = run_detect(detect, root_py)
    assert r['is_virtual'] and r['kind'] == 'conda-base' and os.path.normcase(r['env_path']) == os.path.normcase(str(tmp_path / 'mc'))

    # a system python: nothing around it
    r = run_detect(detect, touch(tmp_path / 'usr' / BIN / PY))
    assert not r['is_virtual'] and r['kind'] == 'system'
    assert run_detect(detect, tmp_path / 'none' / PY)['return'] == 1


@pytest.fixture(scope = 'module')
def py():
    import pathlib
    path = pathlib.Path(__file__).resolve().parents[2] / 'tool' / 'python' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8').replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                                                     'class InitCTool: pass')
    ns = {'__name__': 'tool_python', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def test_check_features_never_takes_the_base_interpreter_as_the_venv(py, tmp_path):
    """A conda base is "virtual" (condabin/), so before 2026-10-07 a request naming it (python_base) accepted it
    as its venv on Linux and macOS and made none; now the base is left aside and only a real venv is taken."""
    base = touch(tmp_path / 'mf' / BIN / PY)
    venv_py = touch(tmp_path / 'entry' / '.venv' / BIN / PY)
    virtual = {str(base): True, str(venv_py): True}

    def access(d):
        if d.get('arg1', '').startswith('detect-python-env'):
            return {'return': 0, 'is_virtual': virtual[d['python_path']], 'script_path': None}
        return {'return': 0, 'returncode': 0, 'env_added': {}}

    tool = object.__new__(py['CTool'])
    tool.cm = types.SimpleNamespace(debug = False, access = access, catch_error = lambda r: r.get('return', 0) > 0,
                                    utils = types.SimpleNamespace(files = types.SimpleNamespace(quote_path = lambda p: p)))
    ctx = {'control': {'con': False}, 'tasks': {'global': {'host': {'vars': {'call_script': 'call'}}}}}

    params = {'python_base': str(base), 'with': {'venv': True, 'pip': False}}
    r = tool.check_features(ctx, [{'path': str(base)}, {'path': str(venv_py)}], params)
    assert [p['path'] for p in r['paths']] == [str(venv_py)]

    # without python_base the same "virtual" base is a venv like any other (an activated conda base is extended by design)
    r = tool.check_features(ctx, [{'path': str(base)}], {'with': {'venv': True, 'pip': False}})
    assert [p['path'] for p in r['paths']] == [str(base)]

    # no venv wanted: the interpreter itself, base or not
    r = tool.check_features(ctx, [{'path': str(base)}], {'python_base': str(base), 'with': {'venv': False, 'pip': False}})
    assert [p['path'] for p in r['paths']] == [str(base)] and r['paths'][0]['features'] == {'is_virtual': True, 'venv': False}


def test_a_venv_path_with_a_named_interpreter_keeps_both(py, tmp_path):
    """A program's venv path plus --use.python.tool_path=<conda python>: before 2026-10-07 the interpreter was
    dropped (the venv at that path was then made on a uv-managed python); now python_base is set and the
    detection looks into the venv of that path."""
    base = touch(tmp_path / 'mf' / BIN / PY)
    tool = object.__new__(py['CTool'])
    tool.cm = types.SimpleNamespace(debug = False, error = lambda msg, code = 1: {'return': code, 'error': msg})
    ctx = {'tasks': {}}
    params = {'tool_path': str(base), 'with': {'venv_path': str(tmp_path / 'build' / 'venv-cpu')}}
    assert tool.check_params(ctx, params)['return'] == 0
    assert params['python_base'] == os.path.normpath(str(base)) and 'tool_path' not in params
    assert params['paths'] == [str(tmp_path / 'build' / 'venv-cpu' / '.venv' / BIN)]
    assert ctx['tasks']['use']['venv']['path'] == str(tmp_path / 'build' / 'venv-cpu')


def test_venv_home_and_a_venv_made_on_another_base_is_left_aside(py, tmp_path):
    base = touch(tmp_path / 'mf' / BIN / PY)
    on_base = touch(tmp_path / 'a' / '.venv' / BIN / PY)
    (tmp_path / 'a' / '.venv' / 'pyvenv.cfg').write_text(f'home = {base.parent}\nversion = 3.14.7\n')
    on_other = touch(tmp_path / 'b' / '.venv' / BIN / PY)
    (tmp_path / 'b' / '.venv' / 'pyvenv.cfg').write_text(f'home = {tmp_path / "uv" / "cpython" / BIN}\n')
    assert os.path.normcase(py['venv_home'](str(on_base))) == os.path.normcase(str(base.parent))
    assert py['venv_home'](str(base)) is None

    def access(d):
        if d.get('arg1', '').startswith('detect-python-env'):
            return {'return': 0, 'is_virtual': d['python_path'] != str(base), 'script_path': None}
        return {'return': 0, 'returncode': 0, 'env_added': {}}

    tool = object.__new__(py['CTool'])
    tool.cm = types.SimpleNamespace(debug = False, access = access, catch_error = lambda r: r.get('return', 0) > 0,
                                    utils = types.SimpleNamespace(files = types.SimpleNamespace(quote_path = lambda p: p)))
    ctx = {'control': {'con': False}, 'tasks': {'global': {'host': {'vars': {'call_script': 'call'}}}}}
    params = {'python_base': str(base), 'with': {'venv': True, 'pip': False}}
    r = tool.check_features(ctx, [{'path': str(on_other)}, {'path': str(on_base)}, {'path': str(base)}], params)
    assert [p['path'] for p in r['paths']] == [str(on_base)]
    # a plain request takes any venv
    r = tool.check_features(ctx, [{'path': str(on_other)}, {'path': str(on_base)}], {'with': {'venv': True, 'pip': False}})
    assert [p['path'] for p in r['paths']] == [str(on_other), str(on_base)]


def test_a_venv_python_that_resolves_to_the_base_is_still_the_venv(py, tmp_path, monkeypatch):
    """On Linux and macOS a venv's python is a symlink to the base interpreter: same_path() resolves it,
    so the venv just made on a conda base looked like the base and was refused (seen 2026-10-07 on Ubuntu:
    one venv per run, every run failing). A python with a pyvenv.cfg is a venv, whatever it resolves to."""
    base = touch(tmp_path / 'mf' / BIN / PY)
    venv_py = touch(tmp_path / 'entry' / '.venv' / BIN / PY)
    (tmp_path / 'entry' / '.venv' / 'pyvenv.cfg').write_text(f'home = {base.parent}\n')
    # a same_path that resolves the venv python to the base, as realpath does with the symlink
    monkeypatch.setitem(py, 'same_path', lambda a, b: os.path.normcase(a) == os.path.normcase(b) or
                        {os.path.normcase(a), os.path.normcase(b)} == {os.path.normcase(str(base)), os.path.normcase(str(venv_py))})

    def access(d):
        if d.get('arg1', '').startswith('detect-python-env'):
            return {'return': 0, 'is_virtual': d['python_path'] == str(venv_py), 'script_path': None}
        return {'return': 0, 'returncode': 0, 'env_added': {}}

    tool = object.__new__(py['CTool'])
    tool.cm = types.SimpleNamespace(debug = False, access = access, catch_error = lambda r: r.get('return', 0) > 0,
                                    utils = types.SimpleNamespace(files = types.SimpleNamespace(quote_path = lambda p: p)))
    ctx = {'control': {'con': False}, 'tasks': {'global': {'host': {'vars': {'call_script': 'call'}}}}}
    r = tool.check_features(ctx, [{'path': str(base)}, {'path': str(venv_py)}],
                            {'python_base': str(base), 'with': {'venv': True, 'pip': False}})
    assert [p['path'] for p in r['paths']] == [str(venv_py)]
