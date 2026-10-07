"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A conda environment as the python of a request (--use.python.with.conda, 0.43.3): tool/python's rules (no
detection without a venv path, only the environment at the venv path with one, never a named interpreter;
such entries are never shared and are the only ones a conda request takes; the features of a conda env carry
its folders instead of an activation script), and the provenance record's view of an environment cMeta made
(kind, name, who made it, the packages conda installed). Offline: planted folders, a fake engine.
"""

import importlib.util
import json
import os
import pathlib
import types

import pytest

WIN = os.name == 'nt'
BIN = 'Scripts' if WIN else 'bin'
PY = 'python.exe' if WIN else 'python'
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def touch(path):
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text('')
    return path


@pytest.fixture(scope = 'module')
def py():
    path = REPO_ROOT / 'tool' / 'python' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8').replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                                                     'class InitCTool: pass')
    ns = {'__name__': 'tool_python', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


@pytest.fixture(scope = 'module')
def prov():
    path = REPO_ROOT / 'category' / 'task' / 'api' / 'provenance.py'
    spec = importlib.util.spec_from_file_location('provenance_conda_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conda_request_rules(py, tmp_path):
    tool = object.__new__(py['CTool'])
    tool.cm = types.SimpleNamespace(debug = False, error = lambda msg, code = 1: {'return': code, 'error': msg})
    params = {'with': {'conda': 'true', 'conda_packages': '', 'channel': None}}
    assert tool.check_params({'tasks': {}}, params)['return'] == 0
    assert params['with'] == {'venv': True, 'pip': True, 'conda': True} and params['skip_detect'] is True

    venv_path = str(tmp_path / 'build' / 'venv-cpu')
    params = {'with': {'conda': True, 'venv_path': venv_path}}
    assert tool.check_params({'tasks': {}}, params)['return'] == 0
    assert params['paths'] == [py['conda_env_python_dir'](os.path.join(venv_path, '.conda-env'))]
    assert 'skip_detect' not in params

    r = tool.check_params({'tasks': {}}, {'with': {'conda': True}, 'tool_path': str(tmp_path / 'python')})
    assert r['return'] == 1 and 'cannot both be given' in r['error']
    params = {'with': {'conda': 'no'}}
    tool.check_params({'tasks': {}}, params)
    assert 'conda' not in params['with'] and 'skip_detect' not in params

    entry = tmp_path / 'entry'
    conda_made = {'path': str(entry), 'cmeta': {'params': {'venv_path': str(entry), 'conda_env': str(entry / '.conda-env')}}}
    own = {'path': str(entry), 'cmeta': {'params': {'venv_path': str(entry)}}}
    assert not py['shareable'](conda_made) and py['shareable'](own)
    r = tool.filter_tool_cache_artifacts({}, [own, conda_made], [conda_made], {'name': 'python', 'with': {'conda': True}})
    assert r == {'return': 0, 'artifacts': [conda_made], 'tmp_artifacts': [conda_made]}
    assert tool.filter_tool_cache_artifacts({}, [own, conda_made], [], {'name': 'python'})['artifacts'] == [own]


def test_check_features_gives_a_conda_environment_its_folders_instead_of_an_activation(py, tmp_path):
    env = tmp_path / 'entry' / '.conda-env'
    env_py = touch(env / BIN / PY)

    def access(d):
        if d.get('arg1', '').startswith('detect-python-env'):
            return {'return': 0, 'is_virtual': True, 'kind': 'conda-env', 'env_path': str(env), 'script_path': None}
        raise AssertionError('no activation script is run for a conda environment')

    tool = object.__new__(py['CTool'])
    tool.cm = types.SimpleNamespace(debug = False, access = access, catch_error = lambda r: r.get('return', 0) > 0,
                                    utils = types.SimpleNamespace(files = types.SimpleNamespace(quote_path = lambda p: p)))
    ctx = {'control': {'con': False}, 'tasks': {'global': {'host': {'vars': {'call_script': 'call'}}}}}
    r = tool.check_features(ctx, [{'path': str(env_py)}], {'with': {'venv': True, 'pip': False, 'conda': True}})
    f = r['paths'][0]['features']
    assert f['venv'] is True and f['conda_env'] == str(env) and 'cmd_venv_activate_scipt' not in f
    assert f['venv_extra_env']['CONDA_PREFIX'] == str(env)
    first = f['venv_extra_env']['PATH'].split(os.pathsep)[0]
    assert first == (os.path.join(str(env), 'Scripts') if WIN else os.path.join(str(env), 'bin'))


def test_provenance_sees_a_conda_environment_made_by_cmeta(prov, tmp_path):
    env = tmp_path / 'entry' / '.conda-env'
    (env / 'conda-meta').mkdir(parents = True)
    for name, ver in (('python', '3.12.11'), ('numpy', '2.3.1'), ('pip', '25.2')):
        (env / 'conda-meta' / f'{name}-{ver}-h0.json').write_text(json.dumps({'name': name, 'version': ver, 'build': 'h0'}))
    (env / '.cmeta-conda-env.json').write_text(json.dumps({'made_by': 'conda 26.7.2', 'conda': '/opt/mf/condabin/conda'}))
    python = touch(env / BIN / PY)
    e = prov.python_environment(str(python))
    assert e['kind'] == 'conda-env' and e['name'] == '.conda-env'
    assert e['made_by'] == 'conda 26.7.2' and e['conda'] == '/opt/mf/condabin/conda'
    assert prov.python_environment_text(e) == 'the conda environment .conda-env made by conda 26.7.2'
    assert prov.conda_packages(str(env)) == {'numpy': '2.3.1', 'pip': '25.2', 'python': '3.12.11'}
    assert prov.conda_packages(str(tmp_path / 'nothing')) == {}

    # a base: condabin/ next to conda-meta/; an environment under envs/ keeps its name and has no maker
    base = tmp_path / 'mf'
    (base / 'conda-meta').mkdir(parents = True)
    (base / 'condabin').mkdir()
    assert prov.python_environment(str(touch(base / BIN / PY)))['kind'] == 'conda'
    (base / 'envs' / 'work' / 'conda-meta').mkdir(parents = True)
    e = prov.python_environment(str(touch(base / 'envs' / 'work' / BIN / PY)))
    assert e['kind'] == 'conda-env' and e['name'] == 'work' and 'made_by' not in e
    assert prov.python_environment_text(e) == 'the conda environment work'
