"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

ai-account-status: the ways a harness's account is read, chosen by the harness's version (the `harnesses` of the
task's _desc.yaml). A harness that changes gets a way added, the older ways stay: these tests hold the rules of the
choice, the declarations of the task as they are, and the version asked from cMeta's own tool detection. Offline:
made-up tools, credentials and provider answers; no network, no login, nothing of a developer's cMeta home.
"""

import json
import os
import re
import types
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

SOURCE = Path(__file__).resolve().parents[2]
TASK = SOURCE / 'task' / 'ai-account-status'


def load():
    """The task's module without the task category (as test_ai_account_status.py loads it)."""
    path = TASK / 'api_v1.py'
    source = path.read_text(encoding='utf-8')
    base_import = 'from task_c36be4b9314a45e0.api.ctask import InitCTask, drop_provider_variables'
    assert base_import in source
    module = types.ModuleType('ai_account_status_ways_under_test')
    module.__file__ = str(path)
    env_source = (SOURCE / 'category/task/api/ctask.py').read_text(encoding='utf-8').split('def gateway_into_environment', 1)[0]
    env_module = types.ModuleType('environment_policy')
    exec(compile(env_source, 'environment_policy', 'exec'), env_module.__dict__)
    module.drop_provider_variables = env_module.drop_provider_variables
    exec(compile(source.replace(base_import, 'InitCTask = object'), str(path), 'exec'), module.__dict__)
    return module, source


m, SOURCE_TEXT = load()
DECLARED = yaml.safe_load((TASK / '_desc.yaml').read_text(encoding='utf-8'))['harnesses']


class FakeCM:
    """cMeta as the task asks it: the log artifact, the config, and the tool detection (counted)."""

    def __init__(self, root, tools):
        self.root, self.tools, self.detections = root, tools, []

    def access(self, params):
        if params['category'] == 'config':
            return {'return': 0, 'config_cmeta': {}}
        if params['category'] == 'log':
            return {'return': 0, 'artifact': {'path': str(self.root)}}
        assert params['category'] == 'task' and params['arg1'] == m.SETUP_TASK, params
        assert params['skip_install'] is True and params['cache'] is False and params['store_global'] is False, params
        self.detections.append(params['name'])
        return dict(self.tools.get(params['name'], {'return': 16, 'error': 'not found'}))


def make_task(tmp_path, tools=None):
    task = object.__new__(m.CTask)
    task.cmeta = {'uses_categories': {'task': 'task', 'log': 'log', 'config': 'config'}}
    task.cm = FakeCM(tmp_path, tools or {})
    return task


def program(tmp_path, name='harness-program', text='v1'):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


##########################################################################################
# The rule of the choice

WAYS = [{'name': 'newest', 'since': '2.0.0'}, {'name': 'middle', 'since': '1.5'}, {'name': 'first'}]


@pytest.mark.parametrize('version, name', [('2.1.327', 'newest'), ('2.0.0', 'newest'), ('10.0', 'newest'),
                                           ('1.9.9', 'middle'), ('1.5', 'middle'), ('1.5.0', 'middle'),
                                           ('1.4.99', 'first'), ('0.1', 'first')])
def test_a_version_takes_the_first_way_that_is_not_above_it(version, name):
    way, note = m.choose_way(WAYS, version)
    assert way['name'] == name and note == ''


def test_an_unknown_version_takes_the_newest_way_and_says_so():
    way, note = m.choose_way(WAYS, '')
    assert way['name'] == 'newest' and 'not known' in note


def test_a_version_the_engine_does_not_compare_takes_the_newest_way_and_says_so():
    way, note = m.choose_way(WAYS, 'nightly-build')
    assert way['name'] == 'newest' and 'not one cMeta compares' in note and 'nightly-build' in note


def test_a_version_below_every_way_is_not_read_and_says_from_which_version():
    way, note = m.choose_way([{'name': 'newest', 'since': '2.0.0'}, {'name': 'older', 'since': '1.5'}], '1.4')
    assert way is None and '1.4' in note and '1.5' in note


def test_no_way_at_all():
    assert m.choose_way([], '1.0') == (None, '')


##########################################################################################
# What the task declares today

def test_each_harness_names_its_cmeta_tool_by_alias_and_uid():
    for harness, entry in DECLARED.items():
        alias, uid = entry['tool'].split(',')
        meta = yaml.safe_load((SOURCE / 'tool' / alias / '_cmeta.yaml').read_text(encoding='utf-8'))
        assert str(meta['artifact']).split(',')[-1] == uid, (harness, entry['tool'])
        assert harness in m.HARNESSES


def test_each_way_has_a_reader_and_the_ways_are_the_newest_first():
    names = []
    for harness, entry in DECLARED.items():
        ways = entry['ways']
        assert ways, harness
        for way in ways:
            assert re.fullmatch(r'[a-z][a-z0-9-]+', way['name']), way
            assert "if way == '%s':" % way['name'] in SOURCE_TEXT, 'no reader for ' + way['name']
            assert isinstance(way.get('reads'), str) and way['reads'].strip(), way['name']
            assert isinstance(way.get('verified'), list), way['name']
            names.append(way['name'])
        # the newest first: every `since` above the one below it; only the last way may be for every version
        since = [str(w.get('since') or '') for w in ways]
        assert all(since[:-1]), (harness, since)
        for newer, older in zip(since, since[1:]):
            if older:
                assert m.compare_versions(newer, older) == {'return': 0, 'comparison': '>'}, (harness, since)
    assert len(names) == len(set(names))


def test_what_was_really_read_names_a_version_a_system_and_a_day():
    for harness, entry in DECLARED.items():
        for way in entry['ways']:
            for v in way['verified']:
                assert set(v) == {'harness', 'os', 'date'}, (way['name'], v)
                assert re.fullmatch(r'[\d.]+', str(v['harness'])) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(v['date'])), v


def test_the_harness_alone_still_finds_its_newest_way():
    # callers of before the ways (_selection(harness, model)) get what they got
    task = make_task(Path('.'))
    with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'made-up-token'}, clear=True):
        identity, fetch, page = task._selection('claude', '')
    assert identity == 'made-up-token' and page == m.PAGES['claude']
    with pytest.raises(m.StatusError) as e:
        task._selection('claude', '', way='a-way-of-tomorrow')
    assert e.value.reason == 'not_supported' and 'a-way-of-tomorrow' in e.value.message
    with pytest.raises(m.StatusError) as e:
        task._selection('gemini', '')
    assert e.value.reason == 'not_supported'


##########################################################################################
# The version, from cMeta's tool detection

def test_the_version_is_asked_once_and_again_when_the_program_changes(tmp_path):
    exe = program(tmp_path)
    tool = DECLARED['claude']['tool']
    task = make_task(tmp_path, {tool: {'return': 0, 'path': str(exe), 'version': '2.1.327'}})

    assert task._harness_version('claude', tool, tmp_path, 1000) == ('2.1.327', str(exe))
    assert task._harness_version('claude', tool, tmp_path, 1100) == ('2.1.327', str(exe))
    assert task.cm.detections == [tool]                                    # kept: the program's file is the same

    exe.write_text('a newer program', encoding='utf-8')                    # the harness updated itself
    task.cm.tools[tool]['version'] = '2.2.0'
    assert task._harness_version('claude', tool, tmp_path, 1200) == ('2.2.0', str(exe))
    assert task.cm.detections == [tool, tool]

    # after the recheck time it is asked again, whatever the file says
    assert task._harness_version('claude', tool, tmp_path, 1200 + m.VERSION_RECHECK + 1) == ('2.2.0', str(exe))
    assert len(task.cm.detections) == 3

    record = json.loads((tmp_path / 'harness' / 'claude.json').read_text(encoding='utf-8'))
    assert set(record) == {'tool', 'path', 'version', 'next_check', 'file'}  # nothing of a login


def test_a_harness_cmeta_does_not_find_is_looked_for_again_only_later(tmp_path):
    tool = DECLARED['codex']['tool']
    task = make_task(tmp_path)
    assert task._harness_version('codex', tool, tmp_path, 1000) == ('', '')
    assert task._harness_version('codex', tool, tmp_path, 1500) == ('', '')
    assert task.cm.detections == [tool]
    assert task._harness_version('codex', tool, tmp_path, 1000 + m.VERSION_RECHECK + 1) == ('', '')
    assert task.cm.detections == [tool, tool]


def test_a_broken_record_is_asked_again(tmp_path):
    exe = program(tmp_path)
    tool = DECLARED['claude']['tool']
    task = make_task(tmp_path, {tool: {'return': 0, 'path': str(exe), 'version': '2.1.327'}})
    (tmp_path / 'harness').mkdir()
    (tmp_path / 'harness' / 'claude.json').write_text('{not json', encoding='utf-8')
    assert task._harness_version('claude', tool, tmp_path, 1000) == ('2.1.327', str(exe))


##########################################################################################
# The answer says which way and which version

USAGE = {'five_hour': {'utilization': 12}, 'seven_day': {'utilization': 35}}


def read(task, **params):
    with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'made-up-token'}, clear=True), \
            patch.object(m, 'get_usage', return_value=USAGE):
        return task.run({}, harness='claude', show_identity=False, **params)


def test_the_answer_names_the_version_and_the_way(tmp_path):
    exe = program(tmp_path)
    task = make_task(tmp_path, {DECLARED['claude']['tool']: {'return': 0, 'path': str(exe), 'version': '2.1.327'}})
    first, second = read(task), read(task)
    for out in (first, second):
        assert out['return'] == 0 and out['available'] is True
        assert out['harness_version'] == '2.1.327' and out['mechanism'] == 'claude-oauth-usage'
        assert out['source'] == 'claude-oauth-usage' and 'mechanism_note' not in out      # the keys of before stay
        assert [w['usedPercent'] for w in out['windows']] == [12, 35]
    assert first['cached'] is False and second['cached'] is True and len(task.cm.detections) == 1


def test_a_harness_that_is_not_found_is_still_read_the_newest_way(tmp_path):
    out = read(make_task(tmp_path))
    assert out['available'] is True and out['harness_version'] == '' and out['mechanism'] == 'claude-oauth-usage'
    assert 'not known' in out['mechanism_note']


def test_a_version_below_every_way_is_an_answer_not_an_error(tmp_path):
    exe = program(tmp_path)
    task = make_task(tmp_path, {DECLARED['claude']['tool']: {'return': 0, 'path': str(exe), 'version': '0.9.0'}})
    ways = {'claude': {'tool': DECLARED['claude']['tool'], 'ways': [{'name': 'claude-oauth-usage', 'since': '1.0.0'}]}}
    with patch.object(m, 'harness_ways', return_value=ways), \
            patch.object(m, 'get_usage', side_effect=AssertionError('nothing is asked for a version no way serves')):
        out = task.run({}, harness='claude', show_identity=False)
    assert out['return'] == 0 and out['available'] is False and out['reason'] == 'harness_version'
    assert '0.9.0' in out['message'] and '1.0.0' in out['message'] and out['harness_version'] == '0.9.0'
    assert 'mechanism' not in out


def test_the_older_way_is_taken_for_the_older_harness(tmp_path):
    # a way of tomorrow above today's: a harness of today keeps today's way, one of tomorrow has no reader here
    exe = program(tmp_path)
    tool = DECLARED['claude']['tool']
    ways = {'claude': {'tool': tool, 'ways': [{'name': 'a-way-of-tomorrow', 'since': '3.0.0'}, {'name': 'claude-oauth-usage'}]}}
    task = make_task(tmp_path, {tool: {'return': 0, 'path': str(exe), 'version': '2.1.327'}})
    with patch.object(m, 'harness_ways', return_value=ways):
        today = read(task)
        exe.write_text('the harness of tomorrow', encoding='utf-8')
        task.cm.tools[tool]['version'] = '3.0.1'
        tomorrow = read(task)
    assert today['available'] is True and today['mechanism'] == 'claude-oauth-usage'
    assert tomorrow['available'] is False and tomorrow['mechanism'] == 'a-way-of-tomorrow' and tomorrow['reason'] == 'not_supported'


def test_a_way_that_starts_the_program_starts_the_one_cmeta_found(tmp_path):
    exe = program(tmp_path, 'codex-as-cmeta-found-it')
    task = make_task(tmp_path, {DECLARED['codex']['tool']: {'return': 0, 'path': str(exe), 'version': '0.170.0'}})
    started = []

    def popen(command, **kwargs):
        started.append(command)
        raise OSError('stop here: the test only looks at what would be started')

    home = tmp_path / 'codex-home'
    home.mkdir()
    with patch.dict(os.environ, {'CODEX_HOME': str(home)}, clear=True), \
            patch.object(m.shutil, 'which', side_effect=AssertionError('the program cMeta found is used, PATH is not searched')), \
            patch.object(m.subprocess, 'Popen', side_effect=popen):
        out = task.run({}, harness='codex', show_identity=False)
    assert started == [[str(exe), 'app-server', '--stdio']]
    assert out['return'] == 0 and out['available'] is False and out['harness_version'] == '0.170.0' and out['mechanism'] == 'codex-app-server'
