"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The python venv cache isolation: a python request that names no venv (with.venv_path, with.venv_here),
no python (tool_path, with.here) and no path reuses detected pythons, venvs made in their own cache entry
and venvs at places the user chose (--path, --use.venv.path, venv_here), but not the venv a program or a
tool made inside its own cache entry with venv_path; requests that name one match as before, and one with
its own venv path detects a python only in that venv.
Unit tests of tool/python's rules, and checks through the task engine with
cache entries planted in the isolated CMETA_HOME (no venv is made, nothing runs or downloads).
"""

import json
import os
import pathlib
import uuid

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SETUP_TAGS = ['task', 'c36be4b9314a45e0', 'setup', 'a2f9b61079ce4333']
SETUP_CREF = {'artifact_alias': 'setup', 'artifact_uid': 'a2f9b61079ce4333', 'category_alias': 'task',
              'category_uid': 'c36be4b9314a45e0'}
PY = os.path.join('.venv', 'Scripts', 'python.exe') if os.name == 'nt' else os.path.join('.venv', 'bin', 'python')


@pytest.fixture(scope = 'module')
def py():
    path = REPO_ROOT / 'tool' / 'python' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8').replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                                                     'class InitCTool: pass')
    ns = {'__name__': 'tool_python', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def art(path, venv_path = None, **params):
    if venv_path is not None:
        params['venv_path'] = str(venv_path)
    return {'path': str(path), 'cmeta': {'params': params}}


# tool/python's rule

def test_same_path(py, tmp_path):
    a = tmp_path / 'x'
    a.mkdir()
    assert py['same_path'](str(a), str(a) + os.sep)
    assert py['same_path'](str(a), str(tmp_path / 'y' / '..' / 'x'))
    if os.name == 'nt':
        assert py['same_path'](str(a).upper(), str(a).lower())
    assert not py['same_path'](str(a), str(tmp_path / 'y'))


def repo(tmp_path):
    """A fake cMeta repository with a cache: the python entry, a program entry and a user folder."""
    r = tmp_path / 'repo'
    (r / 'cache').mkdir(parents = True)
    (r / '_cmr.yaml').write_text('artifact: fake\n')
    return {'python': r / 'cache' / 'task--setup--python--0123456789abcdef',
            'program': r / 'cache' / 'task--program--build-x' / 'tmp' / 'venv-cpu',
            'other_python': r / 'cache' / 'task--setup--python--fedcba9876543210',
            'user': tmp_path / 'work99'}


def test_cache_entry_of(py, tmp_path):
    f = repo(tmp_path)
    assert py['cache_entry_of'](str(f['program'])) == str(f['program'].parents[1])
    assert py['cache_entry_of'](str(f['python'])) == str(f['python'])
    assert py['cache_entry_of'](str(f['user'])) is None
    assert py['cache_entry_of'](str(tmp_path / 'cache' / 'x')) is None          # no repository above


def test_shareable(py, tmp_path):
    f = repo(tmp_path)
    entry = f['python']
    assert py['shareable'](art(entry, entry))                        # a venv in its own entry
    assert py['shareable'](art(entry))                               # detected: no venv path
    assert py['shareable'](art(entry, f['user']))                    # --path, --use.venv.path, venv_here
    assert not py['shareable'](art(entry, f['program']))             # a program's venv in its entry
    assert not py['shareable'](art(entry, f['other_python']))        # another entry's venv


def test_filter(py, tmp_path):
    f = repo(tmp_path)
    tool = object.__new__(py['CTool'])
    own, det, user = art(f['python'], f['python']), art(f['python']), art(f['python'], f['user'])
    ext = art(f['python'], f['program'])
    tmp_own, tmp_ext = art(f['other_python'], f['other_python']), art(f['other_python'], f['program'])

    r = tool.filter_tool_cache_artifacts({}, [own, ext, det, user], [tmp_ext, tmp_own], {'name': 'python'})
    assert r == {'return': 0, 'artifacts': [own, det, user], 'tmp_artifacts': [tmp_own]}

    # A request that names a venv, a python or a path: the engine keeps its lists
    for params, extra in [({'venv_path': str(f['program'])}, {}),
                          ({'tool_path': str(f['program'] / PY)}, {}),
                          ({}, {'path': str(tmp_path / 'p')})]:
        assert tool.filter_tool_cache_artifacts({}, [own, ext], [tmp_ext], dict(name = 'python', **params), **extra) == \
               {'return': 0}


def test_explicit_venv_path_detects_only_there(py, tmp_path):
    """A request with its own venv path looks for a python only in that venv, so a venv found on PATH
    (an activated one, or cMeta's own) is not recorded as its private venv; an existing venv there is reused."""
    import types
    tool = object.__new__(py['CTool'])
    tool.cm = types.SimpleNamespace(debug = False)
    venv = tmp_path / 'prog' / 'venv-cpu'
    ctx = {'tasks': {}}
    params = {'with': {'venv_path': str(venv)}}
    assert tool.check_params(ctx, params)['return'] == 0
    assert params['paths'] == [str(venv / '.venv' / ('Scripts' if os.name == 'nt' else 'bin'))]
    assert params['venv_path'] == str(venv) and ctx['tasks']['use']['venv']['path'] == str(venv)

    # A python or search paths given by the request win; a plain request searches as before
    for extra in ({'tool_path': str(tmp_path / 'python')}, {'paths': [str(tmp_path / 'y')]}):
        p = dict({'with': {'venv_path': str(tmp_path / 'v')}}, **extra)
        tool.check_params({'tasks': {}}, p)
        assert p.get('paths') == extra.get('paths')
    p = {}
    tool.check_params({'tasks': {}}, p)
    assert 'paths' not in p and 'venv_path' not in p and p['with'] == {'venv': True, 'pip': True}


def test_setup_passes_the_hook_on():
    """task/setup asks the tool; a tool without filter_tool_cache_artifacts keeps every entry."""
    src = (REPO_ROOT / 'task' / 'setup' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert 'def filter_cache_artifacts(' in src and "'filter_tool_cache_artifacts'" in src
    engine = (REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py').read_text(encoding = 'utf-8')
    assert "'filter_cache_artifacts'" in engine


# Through the task engine, with planted cache entries

def plant(cm, version, venv_path = 'own', tool_dir = None, extra = None):
    """A python cache entry of task setup with a fake python; venv_path 'own' = in the entry itself,
    'program' = inside a program's cache entry."""
    uid = uuid.uuid4().hex[:16]
    alias = f'task--setup--python--{uid}'
    cache = pathlib.Path(os.environ['CMETA_HOME']) / 'repos' / 'local' / 'cache'
    entry = cache / alias
    if venv_path == 'own':
        venv_path = entry
    elif venv_path == 'program':
        venv_path = cache / 'task--program--fake-build' / 'tmp' / 'venv-cpu'
    tool_path = pathlib.Path(tool_dir or venv_path or entry) / PY
    params = {'name': 'python', 'version': version, 'tool_path': str(tool_path), 'with': {'pip': True, 'venv': True}}
    if venv_path:
        params['venv_path'] = str(venv_path)
    params.update(extra or {})
    r = cm.access({'category': 'cache', 'command': 'create', 'arg1': f'local:{alias},{uid}', 'tags': SETUP_TAGS,
                   'meta': {'cref': SETUP_CREF, 'params': params}})
    assert r['return'] == 0, r.get('error')
    assert os.path.normcase(r['path']) == os.path.normcase(str(entry))
    tool_path.parent.mkdir(parents = True, exist_ok = True)
    tool_path.write_text('')
    result = {'return': 0, 'version': version, 'path': str(tool_path), 'path_bin': str(tool_path.parent),
              'qpath': str(tool_path), 'qpath_bin': str(tool_path.parent), 'features': {}}
    (entry / 'cmeta-task-cached-result.json').write_text(json.dumps(result), encoding = 'utf-8')
    return str(tool_path)


def setup_python(cm, **params):
    p = {'category': 'tool', 'command': 'setup', 'arg1': 'python', 'quiet': True, 'con': False}
    p.update(params)
    r = cm.access(p)
    assert r['return'] == 0, r.get('error')
    return os.path.normcase(r.get('tool_path') or r.get('path'))


@pytest.fixture(scope = 'module')
def planted(cm, tmp_path_factory):
    """An own venv (3.12), a program's venv inside its cache entry with a higher version (3.14), a
    python without a venv path (3.11) and a venv at a place the user chose (3.13)."""
    work = tmp_path_factory.mktemp('venvs')
    assert (pathlib.Path(os.environ['CMETA_HOME']) / 'repos' / 'local' / '_cmr.yaml').is_file()
    return {'own': plant(cm, '3.12.1'),
            'program': plant(cm, '3.14.9', venv_path = 'program'),
            'detected': plant(cm, '3.11.0', venv_path = None, tool_dir = work / 'active'),
            'user': plant(cm, '3.13.3', venv_path = work / 'work99'),
            'work': work}


def test_plain_request_skips_the_program_venv(cm, planted):
    # Before, the program's venv matched too, and quiet mode took its higher version; the venv at
    # the user's place is the highest version that may be shared
    assert setup_python(cm) == os.path.normcase(planted['user'])


def test_versions_of_plain_requests(cm, planted):
    assert setup_python(cm, version = '3.12') == os.path.normcase(planted['own'])
    assert setup_python(cm, version = '3.11') == os.path.normcase(planted['detected'])
    assert setup_python(cm, version = '3.13') == os.path.normcase(planted['user'])


def test_explicit_requests_match_as_before(cm, planted):
    program = str(pathlib.Path(os.environ['CMETA_HOME']) / 'repos' / 'local' / 'cache' / 'task--program--fake-build' / 'tmp' / 'venv-cpu')
    assert setup_python(cm, **{'with': {'venv_path': program}}) == os.path.normcase(planted['program'])
    assert setup_python(cm, **{'with': {'venv_path': str(planted['work'] / 'work99')}}) == os.path.normcase(planted['user'])
    assert setup_python(cm, tool_path = planted['program']) == os.path.normcase(planted['program'])
    assert setup_python(cm, tool_path = planted['detected']) == os.path.normcase(planted['detected'])
