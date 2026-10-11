"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A folder is recorded under the name the request gave it (folder_as_named of the task API): os.getcwd()
resolves the links of a path on Linux and macOS, so a venv made at <link>/venv was recorded under its physical
path while every later request looked for it under its name - one venv, two pythons, two records of every
package (a home moved to another disk behind a link; /tmp and /var on every Mac). task/venv reports the venv
under the name of the folder it was asked to work in; without a link in the path nothing changes, and Windows
(whose current directory keeps the name it was given) is as before.
"""

import importlib.util
import os
import pathlib
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = 'module')
def folder_as_named():
    spec = importlib.util.spec_from_file_location('ctask_folder_as_named', str(REPO_ROOT / 'category' / 'task' / 'api' / 'ctask.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.folder_as_named


def link_dir(target, link):
    """A link to a folder: a symbolic link, or a junction on Windows (no privilege needed)."""
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(str(target), str(link), target_is_directory = True)


@pytest.fixture
def linked(tmp_path):
    """<tmp>/disk/work, and <tmp>/work that is a link to it."""
    real = tmp_path / 'disk' / 'work'
    real.mkdir(parents = True)
    link = tmp_path / 'work'
    link_dir(real, link)
    return real, link


def same(a, b):
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


###################################################################################################

def test_no_name_is_the_current_directory(folder_as_named, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert folder_as_named(None) == os.getcwd()
    assert folder_as_named('') == os.getcwd()


def test_the_folder_under_its_own_name(folder_as_named, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert same(folder_as_named(str(tmp_path)), tmp_path)
    assert os.path.samefile(folder_as_named(str(tmp_path)), os.getcwd())


def test_the_folder_reached_through_a_link_keeps_the_name_of_the_request(folder_as_named, linked, monkeypatch):
    real, link = linked
    monkeypatch.chdir(link)
    named = folder_as_named(str(link))
    assert same(named, link)                         # not <tmp>/disk/work, which os.getcwd() gives on Linux and macOS
    assert os.path.samefile(named, real)
    # a file made in the current directory is found under the name
    (pathlib.Path(os.getcwd()) / 'made-here.txt').write_text('x')
    assert os.path.isfile(os.path.join(named, 'made-here.txt'))


def test_a_link_deeper_in_the_path(folder_as_named, linked, monkeypatch):
    real, link = linked
    (real / 'a' / 'b').mkdir(parents = True)
    monkeypatch.chdir(link / 'a' / 'b')
    assert same(folder_as_named(str(link / 'a' / 'b')), link / 'a' / 'b')


def test_a_relative_name_is_completed_with_the_directory_of_the_request(folder_as_named, linked, tmp_path, monkeypatch):
    real, link = linked
    monkeypatch.chdir(link)
    assert same(folder_as_named('work', str(tmp_path)), link)
    assert same(folder_as_named(os.path.join('.', 'work', ''), str(tmp_path)), link)


def test_another_folder_is_not_the_current_one(folder_as_named, linked, tmp_path, monkeypatch):
    real, link = linked
    (tmp_path / 'elsewhere').mkdir()
    monkeypatch.chdir(link)
    assert folder_as_named(str(tmp_path / 'elsewhere')) == os.getcwd()
    assert folder_as_named(str(tmp_path / 'missing')) == os.getcwd()


@pytest.mark.skipif(os.name == 'nt', reason = 'the current directory of Windows keeps the name it was given')
def test_getcwd_resolves_the_link(linked, monkeypatch):
    """The premise, on Linux and macOS: os.getcwd() does not give the name the directory was entered by."""
    real, link = linked
    monkeypatch.chdir(link)
    assert os.getcwd() != str(link) and os.path.samefile(os.getcwd(), link)


@pytest.mark.skipif(os.name != 'nt', reason = 'Windows only')
def test_windows_keeps_the_name_by_itself(folder_as_named, linked, monkeypatch):
    real, link = linked
    monkeypatch.chdir(link)
    assert same(os.getcwd(), link)
    assert folder_as_named(str(link)) == os.getcwd()         # the very string of before this function existed


###################################################################################################
# task/venv

class FakeEngine:
    """What task/venv needs of the engine; its sub-task ("uv venv --seed") makes a venv in the current directory."""

    def __init__(self, folder = '.venv'):
        self.utils = types.SimpleNamespace(files = types.SimpleNamespace(quote_path = lambda p: '"' + p + '"'))
        self.folder = folder
        self.cmds = []

    def access(self, ii):
        self.cmds.append(ii.get('cmd'))
        scripts = os.path.join(os.getcwd(), self.folder, 'Scripts' if os.name == 'nt' else 'bin')
        os.makedirs(scripts, exist_ok = True)
        for name in (('activate.bat', 'python.exe') if os.name == 'nt' else ('activate', 'python')):
            open(os.path.join(scripts, name), 'w').close()
        return {'return': 0}

    def catch_error(self, r):
        return r['return'] > 0

    def error(self, text, code = 1):
        return {'return': code, 'error': text}


def venv_task(task_namespace, work_dir, cur_dir):
    CTask = task_namespace('venv')['CTask']
    task = CTask.__new__(CTask)
    task.cm = FakeEngine()
    ctx = {'control': {'con': False, 'verbose': False, 'quiet': True},
           'tasks': {'nested_call': 0, 'global': {'uv': {'qpath': 'uv'}},
                     'run_control': {'work_dir': work_dir, 'cur_dir': cur_dir} if work_dir else {}}}
    return task, ctx


def test_venv_is_reported_under_the_name_of_its_folder(task_namespace, linked, tmp_path, monkeypatch):
    real, link = linked
    task, ctx = venv_task(task_namespace, str(link), str(tmp_path))
    monkeypatch.chdir(link)                          # the task engine enters the folder it was asked to work in
    r = task.run(ctx, version = '3.12.1')
    assert r['return'] == 0, r.get('error')
    assert same(r['path_to_venv'], link / '.venv')
    scripts = link / '.venv' / ('Scripts' if os.name == 'nt' else 'bin')
    assert same(r['path_to_scripts'], scripts)
    assert same(r['path_to_python'], scripts / ('python.exe' if os.name == 'nt' else 'python'))
    assert os.path.isfile(r['path_to_python']) and os.path.isfile(r['path_to_activate_script'])
    # what tool/python records as the venv path of the entry is the folder the request named
    assert same(os.path.dirname(r['path_to_venv']), link)


def test_venv_without_a_named_folder_is_reported_where_it_is(task_namespace, linked, monkeypatch):
    """In a cache entry (no --path): the current directory as before."""
    real, link = linked
    task, ctx = venv_task(task_namespace, None, None)
    monkeypatch.chdir(link)
    r = task.run(ctx)
    assert r['return'] == 0, r.get('error')
    assert r['path_to_venv'] == os.path.join(os.getcwd(), '.venv')


def test_venv_without_a_link_is_as_before(task_namespace, tmp_path, monkeypatch):
    work = tmp_path / 'plain'
    work.mkdir()
    task, ctx = venv_task(task_namespace, str(work), str(tmp_path))
    monkeypatch.chdir(work)
    r = task.run(ctx)
    assert r['return'] == 0, r.get('error')
    assert same(r['path_to_venv'], work / '.venv') and os.path.samefile(r['path_to_venv'], os.path.join(os.getcwd(), '.venv'))


def test_conda_environment_is_reported_under_the_name_of_its_folder(task_namespace, linked, tmp_path, monkeypatch):
    real, link = linked
    task, ctx = venv_task(task_namespace, str(link), str(tmp_path))
    ctx['tasks']['global']['conda'] = {'qpath': 'conda', 'path': 'conda', 'version': '26.7.2'}

    def conda_create(ii):
        prefix = pathlib.Path(os.getcwd()) / '.conda-env'
        python = prefix / 'python.exe' if os.name == 'nt' else prefix / 'bin' / 'python'
        python.parent.mkdir(parents = True, exist_ok = True)
        python.write_text('')
        task.cm.cmds.append(ii.get('cmd'))
        return {'return': 0}

    task.cm.access = conda_create
    monkeypatch.chdir(link)
    r = task.run(ctx, conda = True)
    assert r['return'] == 0, r.get('error')
    assert same(r['path_to_venv'], link / '.conda-env')
    assert same(os.path.dirname(r['path_to_python']), link / '.conda-env' if os.name == 'nt' else link / '.conda-env' / 'bin')
    assert os.path.normcase(str(link / '.conda-env')) in os.path.normcase(task.cm.cmds[-1])       # conda create -p <the named folder>
