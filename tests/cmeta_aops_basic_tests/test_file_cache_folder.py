"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The file cache (the keys file_cache and hf.cache of config::task: one place, or several separated as PATH is) and the
place a run takes - file_cache_folder of the task API, asked by get-hf-model, get-hf-dataset, clone-git-to-cache and
tool/hf. A machine kept its models on a USB drive with a folder of its own disk as the second place; while the drive
was away a model was downloaded a second time to the second place and nothing said so. The rule since:

  - a place that is there is used; one whose last folder is missing is made (that folder only);
  - a place that is away is passed over for the next one, and the run says so;
  - what is asked for is taken from the place that has it already;
  - no place of the list there: the run stops and says what to do.
"""

import importlib.util
import os
import pathlib
import string
import sys
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def ctask():
    """The task API's helpers, loaded fresh for each test (the lines said once per process start empty)."""
    spec = importlib.util.spec_from_file_location('ctask_file_cache', str(REPO_ROOT / 'category' / 'task' / 'api' / 'ctask.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def places(*folders):
    return os.pathsep.join(str(f) for f in folders)


def test_a_place_that_is_there_is_used(ctask, tmp_path, capsys):
    cache = tmp_path / 'cache'
    cache.mkdir()
    r = ctask.file_cache_folder(str(cache), 'get-hf-model/x', con = True)
    assert r == {'return': 0, 'path': str(cache), 'away': {}, 'note': ''}
    assert capsys.readouterr().out == ''                               # nothing to say
    assert ctask.file_cache_folder('') == {'return': 0, 'path': '', 'away': {}, 'note': ''}     # no file cache at all
    assert ctask.file_cache_folder(None)['path'] == ''


def test_only_the_last_folder_of_a_place_is_made(ctask, tmp_path):
    """A folder missing where its parent is there is made; a place two folders deep in nothing is away - a path of
    a drive that is not mounted never becomes a folder of the machine's own disk."""
    new = tmp_path / 'file-cache'
    r = ctask.file_cache_folder(str(new))
    assert r['return'] == 0 and r['path'] == str(new) and new.is_dir()

    deep = tmp_path / 'usb-drive' / 'file-cache'
    r = ctask.file_cache_folder(str(deep))
    assert r['return'] == 1 and not (tmp_path / 'usb-drive').exists()
    assert str(deep) in r['error'] and 'does not exist' in r['error']
    assert 'name a second place' in r['error'] and '--meta.file_cache=' in r['error']     # what to do


def test_a_place_that_is_away_is_passed_over_and_said(ctask, tmp_path, capsys):
    away, second = tmp_path / 'usb-drive' / 'file-cache', tmp_path / 'second'
    second.mkdir()
    r = ctask.file_cache_folder(places(away, second), 'get-hf-model/x', con = True, space = '  ')
    assert r['return'] == 0 and r['path'] == str(second) and list(r['away']) == [str(away)]
    assert str(away) in r['note'] and 'is not available' in r['note'] and 'using ' + str(second) in r['note']
    out = capsys.readouterr()
    assert out.out == '  WARNING: ' + r['note'] + '\n' and out.err == ''          # a warning on stdout, once
    ctask.file_cache_folder(places(away, second), 'get-hf-dataset/y', con = True)
    assert capsys.readouterr().out == ''                              # a run asks several times: said once
    assert ctask.file_cache_folder(places(away, second))['note'] == r['note']     # the caller still gets it


def test_no_place_there_stops_the_run(ctask, tmp_path):
    a, b = tmp_path / 'usb-1' / 'cache', tmp_path / 'usb-2' / 'cache'
    r = ctask.file_cache_folder(places(a, b), key = 'hf.cache')
    assert r['return'] == 1 and set(r['away']) == {str(a), str(b)}
    assert 'no place of the file cache is available' in r['error'] and str(a) in r['error'] and str(b) in r['error']
    assert 'hf.cache' in r['error'] and '--meta.hf.cache=' in r['error']          # the key the places come from
    assert not (tmp_path / 'usb-1').exists() and not (tmp_path / 'usb-2').exists()


def test_what_is_asked_for_is_taken_where_it_is(ctask, tmp_path, capsys):
    """The model is in the second place (downloaded while the first was away): it is used from there, no second
    download into the first; another model, which no place has, goes to the first."""
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    (second / 'get-hf-model' / 'org@model').mkdir(parents = True)
    r = ctask.file_cache_folder(places(first, second), os.path.join('get-hf-model', 'org@model'), con = True)
    assert r['path'] == str(second) and r['note'] == '' and capsys.readouterr().out == ''
    assert ctask.file_cache_folder(places(first, second), os.path.join('get-hf-model', 'org@other'))['path'] == str(first)

    # a place that would have to be made is not made when another one has what is asked for
    new = tmp_path / 'new'
    assert ctask.file_cache_folder(places(new, second), os.path.join('get-hf-model', 'org@model'))['path'] == str(second)
    assert not new.exists()

    # the first away, the third has it: the third, and the line about the first
    away = tmp_path / 'usb-drive' / 'cache'
    third = tmp_path / 'third'
    (third / 'git-src' / 'main').mkdir(parents = True)
    r = ctask.file_cache_folder(places(away, first, third), os.path.join('git-src', 'main'))
    assert r['path'] == str(third) and str(away) in r['note']


def test_a_file_in_the_place_of_a_folder(ctask, tmp_path):
    f = tmp_path / 'not-a-folder'
    f.write_text('x', encoding = 'utf-8')
    r = ctask.file_cache_folder(str(f))
    assert r['return'] == 1 and 'it is a file, not a folder' in r['error']
    assert ctask.file_cache_place(str(f)) == ('away', 'it is a file, not a folder')
    assert ctask.file_cache_place(str(tmp_path)) == ('there', '')
    assert ctask.file_cache_place(str(tmp_path / 'new')) == ('to make', '')


@pytest.mark.skipif(os.name != 'nt', reason = 'drive letters')
def test_a_drive_letter_that_does_not_exist_is_not_waited_for(ctask, tmp_path):
    free = next((c for c in reversed(string.ascii_uppercase) if not os.path.exists(c + ':\\')), None)
    if free is None:
        pytest.skip('every drive letter is taken')
    place = free + ':\\cmeta-file-cache-windows'
    assert ctask.file_cache_place(place) == ('away', 'the drive %s: is not connected' % free)

    second = tmp_path / 'second'
    second.mkdir()
    started = time.monotonic()
    r = ctask.file_cache_folder(places(place, second))
    assert time.monotonic() - started < 2                              # a letter that is not there: no moment given
    assert r['path'] == str(second) and 'the drive %s: is not connected' % free in r['note']
    assert 'the drive %s: is not connected' % free in ctask.file_cache_folder(place)['error']


def test_a_drive_that_does_not_answer_yet_is_given_a_moment(ctask, tmp_path, monkeypatch):
    """Windows after a standby: the drive is there, "the device is not ready" for a second or two."""
    usb, second = tmp_path / 'usb', tmp_path / 'second'
    usb.mkdir()
    second.mkdir()
    real, asked, slept = ctask.file_cache_place, [], []

    def waking(place):
        if place == str(usb):
            asked.append(place)
            if len(asked) < 3:
                return 'not ready', 'the drive X: does not answer'
        return real(place)

    monkeypatch.setattr(ctask, 'file_cache_place', waking)
    monkeypatch.setattr(ctask.time, 'sleep', lambda seconds: slept.append(seconds))
    r = ctask.file_cache_folder(places(usb, second))
    assert r['path'] == str(usb) and r['note'] == '' and len(asked) == 3 and len(slept) == 2

    # it never answers: after the moment it is passed over, as a place that is away
    monkeypatch.setattr(ctask, 'file_cache_place',
                        lambda place: ('not ready', 'the drive X: does not answer') if place == str(usb) else real(place))
    r = ctask.file_cache_folder(places(usb, second), wait = 0.0)
    assert r['path'] == str(second) and 'does not answer' in r['note']
    assert 'does not answer' in ctask.file_cache_folder(str(usb), wait = 0.0)['error']


def test_not_ready_is_read_from_the_error_of_the_drive(ctask, monkeypatch):
    """ERROR_NOT_READY (21) of the drive's root is "does not answer"; any other error is "not connected"."""
    def stat(path, code):
        e = OSError(code, 'the device is not ready')
        e.winerror = code
        raise e

    monkeypatch.setattr(ctask.os.path, 'isdir', lambda p: False)
    monkeypatch.setattr(ctask.os.path, 'abspath', lambda p: p)
    monkeypatch.setattr(ctask.os.path, 'splitdrive', lambda p: ('X:', p[2:]))
    monkeypatch.setattr(ctask.os, 'stat', lambda p: stat(p, 21))
    assert ctask.file_cache_place('X:\\cache') == ('not ready', 'the drive X: does not answer')
    monkeypatch.setattr(ctask.os, 'stat', lambda p: stat(p, 3))
    assert ctask.file_cache_place('X:\\cache') == ('away', 'the drive X: is not connected')


# --------------------------------------------------------------------------- the tasks and the tool that ask

class FakeCM:
    debug = False

    def __init__(self):
        self.calls = []

    def error(self, text, code = 1):
        return {'return': code, 'error': text}

    def catch_error(self, r, fail16 = False):
        return r['return'] > 0 and (r['return'] != 16 or fail16)

    def q(self, path):
        # as the engine's: a path with a space, a comma or a plus in double quotes
        return '"' + path + '"' if not path.startswith('"') and (' ' in path or ',' in path or '+' in path) else path

    def access(self, ii):
        self.calls.append(ii)
        return {'return': 0, 'path_to_git_repo': os.path.join(ii['path'], 'src')}


def make(task_namespace, name):
    cls = task_namespace(name)['CTask']
    task = cls.__new__(cls)
    task.cm = FakeCM()
    task.category_alias, task.category_uid = 'task', 'c36be4b9314a45e0'
    return task


@pytest.mark.parametrize('name, params, folder', [
    ('get-hf-model', {'repo': 'org/model-GGUF', 'filename': 'model-q4.gguf'}, 'org@model-GGUF--gguf'),
    ('get-hf-dataset', {'repo': 'org/data', 'filename': 'train.parquet'}, 'org@data'),
])
def test_a_download_goes_to_the_place_that_is_there(task_namespace, tmp_path, capsys, name, params, folder):
    away, second = tmp_path / 'usb-drive' / 'cache', tmp_path / 'second'
    second.mkdir()
    task = make(task_namespace, name)

    ctx = {'control': {'con': True}, 'tasks': {'local': {}, 'global': {'init': {'file_cache': places(away, second)}}}}
    assert task.check_params(ctx, dict(params), {})['return'] == 0
    assert ctx['tasks']['local']['directory'] == os.path.join(str(second), name, folder)
    assert 'WARNING: the file cache %s is not available' % away in capsys.readouterr().out

    # the folder as one word of the download's command line: quoted when its path holds a space
    assert ctx['tasks']['local']['qdirectory'] == task.cm.q(ctx['tasks']['local']['directory'])
    spaced = tmp_path / 'First Last' / 'cache'
    spaced.mkdir(parents = True)
    ctx = {'control': {'con': True}, 'tasks': {'local': {}, 'global': {'init': {'file_cache': str(spaced)}}}}
    assert task.check_params(ctx, dict(params), {})['return'] == 0
    assert ctx['tasks']['local']['qdirectory'] == '"' + os.path.join(str(spaced), name, folder) + '"'

    # the only place away: the run stops with what to do - no download into a folder called "None"
    ctx = {'control': {'con': True}, 'tasks': {'local': {}, 'global': {'init': {'file_cache': str(away)}}}}
    r = task.check_params(ctx, dict(params), {})
    assert r['return'] == 1 and 'is not available' in r['error'] and 'name a second place' in r['error']
    assert 'directory' not in ctx['tasks']['local']

    # the files are in the second place already (the first is there too): taken from there
    first = tmp_path / 'first'
    first.mkdir()
    (second / name / folder).mkdir(parents = True)
    ctx = {'control': {'con': True}, 'tasks': {'local': {}, 'global': {'init': {'file_cache': places(first, second)}}}}
    assert task.check_params(ctx, dict(params), {})['return'] == 0
    assert ctx['tasks']['local']['directory'] == os.path.join(str(second), name, folder)

    # a data repository keeps the files inside its entry: the file cache is not asked
    ctx = {'control': {}, 'tasks': {'local': {'in_data_repository': True},
                                    'global': {'init': {'file_cache': str(away)}}}}
    assert task.check_params(ctx, dict(params), {})['return'] == 0
    assert ctx['tasks']['local']['directory'] == 'content'


def test_a_clone_goes_to_the_place_that_is_there(task_namespace, tmp_path):
    away, second = tmp_path / 'usb-drive' / 'cache', tmp_path / 'second'
    second.mkdir()

    def run(file_cache, **more):
        task = make(task_namespace, 'clone-git-to-cache')
        ctx = {'control': {'con': False, 'quiet': True, 'verbose': False},
               'tasks': {'nested_call': 0, 'global': {'init': {'file_cache': file_cache}}, 'cparams': {},
                         'run_control': {'cur_dir': str(tmp_path), 'work_dir': str(tmp_path)}}}
        r = task.run(ctx, name = 'src-x', url = 'https://github.com/org/x', **more)
        return r, task.cm.calls

    r, calls = run(places(away, second), checkout = 'main')
    assert r['return'] == 0 and calls[0]['path'] == os.path.join(str(second), 'git-src-x', 'main')
    assert os.path.isdir(calls[0]['path']) and not (tmp_path / 'usb-drive').exists()

    # another checkout of the same repository, the first place back: it goes to the first place ...
    first = tmp_path / 'first'
    first.mkdir()
    r, calls = run(places(first, second), checkout = 'v2')
    assert calls[0]['path'] == os.path.join(str(first), 'git-src-x', 'v2')
    # ... and the checkout that is in the second place is taken from there
    r, calls = run(places(first, second), checkout = 'main')
    assert calls[0]['path'] == os.path.join(str(second), 'git-src-x', 'main')
    # the folder of a version and a checkout, as before
    r, calls = run(str(first), version = '1.2', version_to_dir = True, checkout = 'main')
    assert calls[0]['path'] == os.path.join(str(first), 'git-src-x', '1.2-main')

    r, calls = run(str(away), checkout = 'main')
    assert r['return'] == 1 and 'is not available' in r['error'] and calls == []       # nothing is cloned elsewhere


def test_the_hugging_face_cache_follows_the_same_rule(ctask, tmp_path, monkeypatch, capsys):
    """tool/hf sets HF_HOME to the first place of hf.cache that is there, and says which key to change."""
    path = REPO_ROOT / 'tool' / 'hf' / 'api_v1.py'
    source = path.read_text(encoding = 'utf-8').replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                                                      'InitCTool = object')
    namespace = {'__file__': str(path), '__name__': 'tool_hf_under_test'}
    exec(compile(source, str(path), 'exec'), namespace)

    # the task API as the tool imports it at the call: stand-ins for this test only
    package, api = type(sys)('task_c36be4b9314a45e0'), type(sys)('task_c36be4b9314a45e0.api')
    package.api, api.ctask = api, ctask
    for name, module in (('task_c36be4b9314a45e0', package), ('task_c36be4b9314a45e0.api', api),
                         ('task_c36be4b9314a45e0.api.ctask', ctask)):
        monkeypatch.setitem(sys.modules, name, module)

    tool = namespace['CTool'].__new__(namespace['CTool'])
    tool.cm = FakeCM()
    away, second = tmp_path / 'usb-drive' / 'cache' / 'hf-cache', tmp_path / 'second'
    second.mkdir()

    def home(cache):
        ctx = {'control': {'con': True}, 'tasks': {'global': {'init': {'hf': {'cache': cache}}}}}
        return tool.finish_dynamic_result(ctx, {}, {})

    r = home(places(away, second / 'hf-cache'))
    assert r['return'] == 0 and r['result']['_aggregate']['env']['HF_HOME'] == str(second / 'hf-cache')
    assert (second / 'hf-cache').is_dir() and 'WARNING: the file cache %s is not available' % away in capsys.readouterr().out

    r = home(str(away))
    assert r['return'] == 1 and '--meta.hf.cache=' in r['error']
    assert home('') == {'return': 0}                                   # no hf.cache: Hugging Face's own folder
