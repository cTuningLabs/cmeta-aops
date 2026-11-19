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


def test_a_run_keeps_its_login_or_its_gateway(run_ai, tmp_path):
    """run_ai_config.gateway (2026-11-18): the gateway a run went through - or "login" - is recorded with its harness
    and taken by the next run without a flag, whatever this machine's config says by then: a session is never moved
    to another account without a word. It survives the recording of last_seen."""
    CTask = run_ai['CTask']
    t = CTask.__new__(CTask)
    project = tmp_path / 'work-item'
    project.mkdir()
    (project / '_desc.yaml').write_text(DESC, encoding='utf-8')
    t._resolve_project = lambda project_arg, con, space, ai_dir: (str(project), 'work::work-item', 'test')

    note = t._record_run_config(str(project), {'harness': 'claude', 'model': '', 'effort': '', 'gateway': 'acme'})
    assert 'gateway acme' in note
    assert t._saved_run_config('', None, None, '', '!AI') == {'harness': 'claude', 'gateway': 'acme'}
    assert t._record_run_config(str(project), {'harness': 'claude', 'gateway': 'acme'}) == ''

    # the login is a choice like another, and is kept as one
    assert 'gateway login' in t._record_run_config(str(project), {'harness': 'claude', 'gateway': 'login'})
    data = yaml.safe_load((project / '_desc.yaml').read_text(encoding='utf-8'))
    assert data['run_ai_config'] == {'harness': 'claude', 'gateway': 'login'} and data['ai_gateway'] == 'login'

    # what the session reports of itself is written into the same block: the gateway stays
    t._record_run_config(str(project), {'harness': 'claude', 'gateway': 'acme'})
    t._record_last_seen(str(project), 'claude', {'model': 'claude-opus-x', 'effort': 'high', 'since': '2026-11-18T10:00:00'})
    data = yaml.safe_load((project / '_desc.yaml').read_text(encoding='utf-8'))
    assert data['run_ai_config']['gateway'] == 'acme' and data['run_ai_config']['last_seen']['model'] == 'claude-opus-x'


def test_the_gateway_flags_of_a_run(run_ai, monkeypatch):
    """--gw_default makes the gateway this machine's default and the run's; --gw_unset removes the default; a bare
    -gw asks a person at a terminal and takes the default where nobody can be asked; flags that say opposite things
    are an error; a dry run changes nothing."""
    CTask = run_ai['CTask']
    t = CTask.__new__(CTask)
    calls = []

    class CM:
        def access(self, p):
            if p.get('command') == 'find':          # the AI gateways are plugged here (set-ai-gateway is found)
                return {'return': 0, 'artifacts': [{'path': 'set-ai-gateway'}]}
            calls.append(p)
            if p.get('command') == 'pick':
                return {'return': 0, 'gateway': 'picked'}
            if p.get('command') == 'default':
                return {'return': 0, 'removed': ['run_ai_gateway', 'run_ai_gateway_name']} if p.get('unset') else \
                    {'return': 0, 'written': {'run_ai_gateway': True, 'run_ai_gateway_name': p['arg1']}}
            return {'return': 1, 'error': 'unexpected call'}

        def error(self, text):
            return {'return': 1, 'error': text}

    t.cm = CM()
    ctx = {'control': {'quiet': False}}

    def flags(**k):
        del calls[:]
        p = dict(gateway='', gw='', ln=False, gw_default='', gw_unset=False, con=True, dry_run=False)
        p.update(k)
        return t._gateway_flags(ctx, 'claude', p['gateway'], p['gw'], p['ln'], p['gw_default'], p['gw_unset'], p['con'], p['dry_run'])

    # nothing asked: nothing done; a named gateway goes on as --gateway
    assert flags() == ('', '', [], None) and calls == []
    assert flags(gw='acme') == ('acme', '', [], None) and calls == []
    assert flags(gateway='acme') == ('acme', '', [], None)

    # --gw_default=<alias>: the run's gateway, and this machine's default
    gateway, gw, notes, err = flags(gw_default='acme')
    assert (gateway, gw, err) == ('acme', '', None) and 'default gateway of this machine: acme' in notes[0]
    assert [c['command'] for c in calls] == ['default'] and calls[0]['arg1'] == 'acme' and calls[0]['harness'] == 'claude'

    # --gw_unset: the default is removed, the run goes on with what then applies
    gateway, gw, notes, err = flags(gw_unset=True)
    assert (gateway, gw, err) == ('', '', None) and 'removed (run_ai_gateway, run_ai_gateway_name)' in notes[0]
    assert calls[0]['unset'] is True

    # a bare -gw: a person at a terminal chooses ...
    monkeypatch.setattr(run_ai['sys'].stdin, 'isatty', lambda: True, raising=False)
    assert flags(gw=True) == ('picked', '', [], None) and calls[0]['command'] == 'pick'
    gateway, gw, notes, err = flags(gw_default=True)
    assert gateway == 'picked' and [c['command'] for c in calls] == ['pick', 'default'] and calls[1]['arg1'] == 'picked'
    # ... a run nobody watches (-q, no console, no terminal) takes this machine's default, as a bare -gw always did
    ctx['control']['quiet'] = True
    assert flags(gw=True) == ('', True, [], None) and calls == []
    assert 'needs its gateway' in flags(gw_default=True)[3]['error']
    ctx['control']['quiet'] = False
    assert flags(gw=True, con=False) == ('', True, [], None)
    monkeypatch.setattr(run_ai['sys'].stdin, 'isatty', lambda: False, raising=False)
    assert flags(gw=True) == ('', True, [], None) and calls == []

    # flags that say opposite things
    for k in (dict(ln=True, gw='acme'), dict(ln=True, gw=True), dict(ln=True, gw_default='acme'),
              dict(gw_unset=True, gw_default='acme'), dict(gw_default='acme', gw='other'), dict(gw_default='acme', gateway='other')):
        assert flags(**k)[3]['return'] > 0 and calls == [], k

    # a dry run says what would change, and changes nothing
    gateway, gw, notes, err = flags(gw_default='acme', dry_run=True)
    assert gateway == 'acme' and 'would make it acme' in notes[0] and calls == []
    gateway, gw, notes, err = flags(gw_unset=True, dry_run=True)
    assert 'would remove it' in notes[0] and calls == []


def test_a_recorded_gateway_that_is_gone_is_an_error_not_another_account(run_ai):
    """The gateway a project ran with last, missing on this machine: the run stops and names it and its record -
    it never goes on with another gateway or the login by itself."""
    CTask = run_ai['CTask']
    t = CTask.__new__(CTask)
    here = {'acme'}
    seen = {}

    class CM:
        def access(self, p):
            if p.get('command') == 'find':          # the AI gateways are plugged here (set-ai-gateway is found)
                return {'return': 0, 'artifacts': [{'path': 'set-ai-gateway'}]}
            if p.get('command') == 'list':
                return {'return': 0, 'gateways': [{'alias': p['arg1'], 'auth': 'x-api-key (k)'}] if p['arg1'] in here else []}
            seen.update(p)
            # what set-ai-gateway answers: the flag, else the record, else the config
            name, how = (p['gateway'], 'the flag --gateway') if p['gateway'] else \
                (p['recorded'], "the project's run_ai_config (its last run; -ln or -gw=<alias> changes it)") if p['recorded'] else ('login', 'the default')
            return {'return': 0, 'gateway': 'login' if p['ln'] else name, 'how': 'the flag -ln' if p['ln'] else how}

        def error(self, text):
            return {'return': 1, 'error': text}

    t.cm = CM()

    # the record is handed to the choice, and a gateway that is here goes through
    assert t._gateway_choice({}, 'claude', '', '', False, '', 'acme')[:2] == ('acme', "the project's run_ai_config (its last run; -ln or -gw=<alias> changes it)")
    assert seen['recorded'] == 'acme'

    name, how, err, note = t._gateway_choice({}, 'claude', '', '', False, '', 'gone-gateway')
    assert name == '' and err['return'] > 0
    assert 'gone-gateway' in err['error'] and 'this project ran with last' in err['error'] and 'run_ai_config.gateway' in err['error']
    assert '-ln' in err['error'] and '-gw=<alias>' in err['error']

    # the two ways out
    assert t._gateway_choice({}, 'claude', '', '', True, '', 'gone-gateway')[:3] == ('login', 'the flag -ln', None)
    assert t._gateway_choice({}, 'claude', 'acme', '', False, '', 'gone-gateway')[:3] == ('acme', 'the flag --gateway', None)

    # a gateway named by a flag that is not here: said the same way, without the record
    err = t._gateway_choice({}, 'claude', 'typo', '', False)[2]
    assert err['return'] > 0 and '"typo" (the flag --gateway) is not on this machine' in err['error']


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
