"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run_ai_config of a project's _desc.yaml (2026-10-30, the user's idea): the harness, the model and the effort of the
project's last run, which a run without those flags takes again - so a plain "cxai" goes on with the harness the
project works with. A flag changes it; the model and the effort go together and only with their harness. The block is
written in place: the rest of the _desc.yaml, comments included, stays as it was.
"""

import os

import pytest
import yaml


@pytest.fixture(scope='module')
def run_ai(task_namespace):
    return task_namespace('run-ai')


DESC = ('# a work item\n'
        'ai_uses:\n'
        '  - fgg.project::cMeta     # its rules\n'
        'ai_gateway: login\n')


def test_the_block_is_appended_then_replaced_and_the_rest_stays(run_ai):
    text = run_ai['run_ai_config_text'](DESC, {'harness': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high'})
    assert text.startswith(DESC + '\nrun_ai_config:')
    assert yaml.safe_load(text)['run_ai_config'] == {'harness': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high'}

    # again with another harness and no model: the block replaced, the model and the effort gone, nothing else moved
    again = run_ai['run_ai_config_text'](text + 'later: 1\n', {'harness': 'claude'})
    data = yaml.safe_load(again)
    assert data['run_ai_config'] == {'harness': 'claude'} and data['later'] == 1 and data['ai_gateway'] == 'login'
    assert again.count('run_ai_config:') == 1 and '# its rules' in again


def test_a_one_line_value_and_crlf_and_words_yaml_would_change(run_ai):
    text = 'name: x\r\nrun_ai_config: {harness: opencode}\r\nafter: 2\r\n'
    out = run_ai['run_ai_config_text'](text, {'harness': 'gemini', 'effort': 'on', 'model': '3.5'})
    assert '\r\n' in out and '\n' not in out.replace('\r\n', '')
    data = yaml.safe_load(out)
    assert data['run_ai_config'] == {'harness': 'gemini', 'model': '3.5', 'effort': 'on'}   # strings, not a float, not True
    assert data['after'] == 2


def test_a_run_takes_the_saved_harness_and_records_its_own(run_ai, tmp_path):
    """The saved harness for a run without --harness; the model and the effort only with their own harness; a run
    records what it is made with, and nothing when that did not change."""
    CTask = run_ai['CTask']
    t = CTask.__new__(CTask)
    project = tmp_path / 'work-item'
    project.mkdir()
    (project / '_desc.yaml').write_text(DESC, encoding='utf-8')
    t._resolve_project = lambda project_arg, con, space, ai_dir: (str(project), 'work::work-item', 'test')

    assert t._saved_run_config('', None, None, '', '!AI') == {}
    note = t._record_run_config(str(project), {'harness': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high'})
    assert note.startswith('run_ai_config of the project')
    assert t._saved_run_config('', None, None, '', '!AI') == {'harness': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high'}
    assert t._record_run_config(str(project), {'harness': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high'}) == ''
    assert (project / '_desc.yaml').read_text(encoding='utf-8').startswith(DESC)

    # a scratch workspace and a plain folder keep nothing
    assert t._saved_run_config('', True, None, '', '!AI') == {}
    t._resolve_project = lambda project_arg, con, space, ai_dir: (str(project), '', 'a folder')
    assert t._saved_run_config('', None, None, '', '!AI') == {}

    # a project whose _desc is JSON is not converted behind the user's back
    js = tmp_path / 'json-item'
    js.mkdir()
    (js / '_desc.json').write_text('{"a": 1}', encoding='utf-8')
    assert 'not recorded' in t._record_run_config(str(js), {'harness': 'claude'})
    assert sorted(os.listdir(js)) == ['_desc.json']


def test_last_seen_is_recorded_kept_and_never_given_to_the_harness(run_ai, tmp_path):
    """run_ai_config.last_seen (2026-11-03): what the last run's session says it ran with - recorded when it changes,
    kept when the rest of the block is rewritten, read back as a note and never as the model of the next run."""
    CTask = run_ai['CTask']
    t = CTask.__new__(CTask)
    project = tmp_path / 'work-item'
    project.mkdir()
    (project / '_desc.yaml').write_text(DESC, encoding='utf-8')
    t._resolve_project = lambda project_arg, con, space, ai_dir: (str(project), 'work::work-item', 'test')
    t._record_run_config(str(project), {'harness': 'claude'})

    seen = {'model': 'claude-opus-5-5', 'effort': 'max', 'since': '2026-11-03T13:08:52Z'}
    note = t._record_last_seen(str(project), 'claude', seen)
    assert 'last_seen' in note and 'claude-opus-5-5' in note
    cfg = yaml.safe_load((project / '_desc.yaml').read_text(encoding='utf-8'))['run_ai_config']
    assert cfg == {'harness': 'claude', 'last_seen': {'harness': 'claude', 'model': 'claude-opus-5-5', 'effort': 'max',
                                                      'since': '2026-11-03T13:08:52Z'}}       # the time stays a text
    assert (project / '_desc.yaml').read_text(encoding='utf-8').startswith(DESC)
    assert t._record_last_seen(str(project), 'claude', dict(seen, since='2026-11-04T09:00:00Z')) == ''    # unchanged: no write

    # the block rewritten for a run with another model: last_seen stays; read back, it is a note and not a flag
    t._record_run_config(str(project), {'harness': 'claude', 'model': 'claude-fable-5-1'})
    saved = t._saved_run_config('', None, None, '', '!AI')
    assert saved['model'] == 'claude-fable-5-1' and saved['last_seen']['model'] == 'claude-opus-5-5'
    assert t._record_last_seen(str(project), 'claude', {'model': 'claude-fable-5-1', 'since': 'x'}).endswith('(what the session ran with)')
    assert yaml.safe_load((project / '_desc.yaml').read_text(encoding='utf-8'))['run_ai_config']['model'] == 'claude-fable-5-1'
    assert t._record_last_seen(str(project), 'claude', {}) == ''
