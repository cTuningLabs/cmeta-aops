"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-ai and the harness tasks around the AI gateways, with stand-ins for the engine: the choice of a run, the settings
handed to Claude Code, the login through a gateway, the line every run prints and the run reference. The gateways
themselves - the category ai.gateway and the task set-ai-gateway - are tested in test_ai_gateway.py; where they are not
found a run is a login run (test_without_the_gateways_*).
"""
import os

import pytest


def test_run_claude_merges_the_gateway_settings_into_one_settings_flag(tmp_path, task_namespace):
    """Claude Code reads one --settings: the gateway's go into run-ai's file or the user's JSON, or come alone."""
    import json
    merge = task_namespace('run-claude')['_with_settings']
    add = {'apiKeyHelper': 'helper', 'disableClaudeAiConnectors': True}

    # the flags by their names, wherever they are: the value of --settings, and the others as they came
    def settings(flags):
        return json.loads(flags[flags.index('--settings') + 1])

    def others(flags):
        k = flags.index('--settings')
        return flags[:k] + flags[k + 2:]

    flags, err = merge(['--add-dir', 'x'], add)
    assert err == '' and settings(flags) == add and others(flags) == ['--add-dir', 'x']
    path = tmp_path / 'run.claude.settings.json'
    path.write_text(json.dumps({'autoMemoryDirectory': 'D:/p/!AI/memory'}), encoding='utf-8')
    flags, err = merge(['--settings', str(path), '--session-id', 's'], add)
    assert err == '' and settings(flags) == dict(add, autoMemoryDirectory='D:/p/!AI/memory') and others(flags) == ['--session-id', 's']
    assert json.loads(path.read_text(encoding='utf-8')) == {'autoMemoryDirectory': 'D:/p/!AI/memory'}      # the file stays as it was
    flags, err = merge(['--settings={"model": "m", "apiKeyHelper": "old"}'], add)
    assert err == '' and settings(flags) == dict(add, model='m') and others(flags) == []
    flags, err = merge(['--settings', '{not json'], add)
    assert 'cannot be read' in err and flags == ['--settings', '{not json']
    assert 'not a JSON object' in merge(['--settings', '[1]'], add)[1]


def test_run_ai_runs_a_harness_without_gateway_support_on_its_login_under_the_general_default(task_namespace):
    """On a machine with the gateway on by default (config run_ai_gateway), "cxai --harness=vibe" stopped with "no
    gateway support" (2026-11-01): the default is for claude, codex and opencode - another harness runs on its own
    login, with a note. A gateway chosen for it (a flag, the project, config run_ai_gateway_<harness>) stays an error."""
    cls = task_namespace('run-ai')['CTask']
    task = cls.__new__(cls)
    answer = {}

    class CM:
        def access(self, p):
            # the AI gateways are plugged here (set-ai-gateway is found)
            if p.get('command') == 'find':
                return {'return': 0, 'artifacts': [{'path': 'set-ai-gateway'}]}
            # the gateway a run is to go through must be on this machine (ai.gateway list): acme is
            if p.get('command') == 'list':
                return {'return': 0, 'gateways': [{'alias': 'acme', 'auth': 'x-api-key (acme-key)'}]}
            return dict(answer)

        def error(self, text):
            return {'return': 1, 'error': text}

    task.cm = CM()
    answer.update({'return': 0, 'gateway': 'acme', 'how': 'config run_ai_gateway', 'general': True})
    name, how, err, note = task._gateway_choice({}, 'vibe', '', '', False)
    assert (name, err) == ('login', None) and 'vibe takes no gateway' in how and 'acme' in note and 'vibe' in note
    assert task._gateway_choice({}, 'claude', '', '', False) == ('acme', 'config run_ai_gateway', None, '')
    assert task._gateway_choice({}, 'codex', '', '', False)[0] == 'acme'

    answer.update({'how': 'the flag --gateway'})
    del answer['general']
    assert task._gateway_choice({}, 'vibe', 'acme', '', False) == ('acme', 'the flag --gateway', None, '')   # the run refuses it


def test_a_login_through_a_gateway_is_a_login_run_for_the_harness_tasks(task_namespace, monkeypatch):
    """own_login: run-claude and run-codex clean the environment as for a login run - the user's own keys would go in
    the login's place - and a login kept as a token stays; the gateway's address is set after."""
    for harness, task_name in (('claude', 'run-claude'), ('codex', 'run-codex')):
        cls = task_namespace(task_name)['CTask']
        task = cls.__new__(cls)

        class CM:
            answer = {}

            def access(self, p):
                if p.get('command') == 'find':          # the AI gateways are plugged here (set-ai-gateway is found)
                    return {'return': 0, 'artifacts': [{'path': 'set-ai-gateway'}]}
                return dict(self.answer)

        task.cm = CM()
        ctx = {'control': {'con': False}}

        for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'OPENAI_API_KEY', 'CODEX_API_KEY'):
            monkeypatch.setenv(name, 'the-users-own')
        monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'a-login-kept-as-a-token')
        monkeypatch.setenv('CMETA_AI_GATEWAY_VARS', '')

        CM.answer = {'return': 0, 'gateway': 'through', 'how': 'the flag --gateway', 'own_login': True,
                     'env': {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:9/pass'} if harness == 'claude' else {}}
        r = task._gateway(ctx, harness, 'through', '', False)
        assert r['return'] == 0
        if harness == 'claude':
            assert 'ANTHROPIC_API_KEY' not in os.environ and os.environ['ANTHROPIC_BASE_URL'] == 'http://127.0.0.1:9/pass'
            assert os.environ['CLAUDE_CODE_OAUTH_TOKEN'] == 'a-login-kept-as-a-token'
        else:
            assert 'OPENAI_API_KEY' not in os.environ and 'CODEX_API_KEY' not in os.environ


RUN = 'project=work::my%20work,0123456789abcdef;conversation=20261119-1200;run=20261119-120000'


def test_run_ai_names_its_run_and_says_what_it_talks_to(task_namespace):
    """The run reference: project, conversation and run, each percent-encoded, empty parts left out. And the line
    every run prints: the login, or a gateway with its address, where it passes the traffic on, and who pays."""
    ns = task_namespace('run-ai')
    assert ns['run_reference']('work::my work,0123456789abcdef', '20261119-1200', '20261119-120000') == RUN
    assert ns['run_reference']('D:/a folder', '', '20261119-120000') == 'project=D:/a%20folder;run=20261119-120000'

    rows = {'local-acme': {'alias': 'local-acme', 'auth': 'x-api-key (acme-key)', 'upstream': 'acme',
                           'base_url': 'http://127.0.0.1:8401/local-acme'},
            'local-login': {'alias': 'local-login', 'auth': 'login', 'base_url': 'http://127.0.0.1:8401/local-login',
                            'upstream': 'anthropic: https://api.anthropic.com, openai: https://chatgpt.com/backend-api/codex'},
            'llama': {'alias': 'llama', 'auth': 'none', 'base_url': 'http://127.0.0.1:8686', 'upstream': ''}}

    class CM:
        def access(self, p):
            row = rows.get(p.get('arg1'))
            return {'return': 0, 'gateways': [row] if row else []}

    cls = ns['CTask']
    task = cls.__new__(cls)
    task.cm = CM()
    assert task._gateway_line('codex', 'login', 'config run_ai_gateway_codex') == \
        'none - codex on its own login, its own account pays (config run_ai_gateway_codex)'
    assert task._gateway_line('claude', 'local-acme', 'the flag --gateway') == \
        'local-acme (the flag --gateway) - http://127.0.0.1:8401/local-acme -> acme; a key: x-api-key (acme-key)'
    line = task._gateway_line('claude', 'local-login', 'the default')
    assert line.startswith('local-login (the default) - http://127.0.0.1:8401/local-login -> anthropic: https://api.anthropic.com')
    assert line.endswith("; the harness's own login, its own account pays")
    assert task._gateway_line('opencode', 'llama', 'the default') == 'llama (the default) - http://127.0.0.1:8686; no key'


class NoGateways:
    """An engine where no repository provides the AI gateways: set-ai-gateway is not found, and nothing else is asked."""
    def __init__(self):
        self.asked = []

    def access(self, p):
        self.asked.append(p)
        if p.get('command') == 'find':
            return {'return': 16, 'error': 'not found'}
        raise AssertionError('nothing but the task\'s find is asked without the gateways: %s' % p)

    def error(self, text):
        return {'return': 1, 'error': text}


def test_without_the_gateways_a_harness_runs_on_its_login_and_a_gateway_asked_for_says_why(ctask_helpers):
    """ctask.choose_gateway: no repository provides set-ai-gateway - a login run; a gateway named (--gateway=<alias>,
    -gw bare or with an alias) is an error naming what is missing; --gateway=login is a login run."""
    h = ctask_helpers('choose_gateway', 'NO_GATEWAYS', 'gateway_asked')
    ctx = {'control': {'con': False}}
    for gateway, gw in (('', ''), ('login', ''), ('LOGIN', None)):
        r = h['choose_gateway'](NoGateways(), ctx, 'claude', gateway, gw, False)
        assert r == {'return': 0, 'gateway': 'login', 'how': 'no AI gateways on this machine'}, (gateway, gw)
    for gateway, gw in (('acme', ''), ('', True), ('', 'acme')):
        r = h['choose_gateway'](NoGateways(), ctx, 'codex', gateway, gw, False)
        assert r['return'] == 1 and r['error'] == h['NO_GATEWAYS'] and 'set-ai-gateway' in r['error'], (gateway, gw)
    assert not h['gateway_asked']('', 'False') and h['gateway_asked']('', True)

    # with them: set-ai-gateway decides
    class With(NoGateways):
        def access(self, p):
            self.asked.append(p)
            if p.get('command') == 'find':
                return {'return': 0, 'artifacts': [{'path': 'set-ai-gateway'}]}
            return {'return': 0, 'gateway': 'acme', 'how': 'the flag --gateway'}
    cm = With()
    assert h['choose_gateway'](cm, ctx, 'claude', 'acme', '', False)['gateway'] == 'acme'
    assert any(p.get('arg1') == 'set-ai-gateway,e10aa0a00edd4a2c' and p.get('gateway') == 'acme' for p in cm.asked)


def test_without_the_gateways_run_ai_runs_on_the_login_unless_a_gateway_was_named(task_namespace):
    """run-ai: no AI gateways here - a login run; a gateway named by a flag, by the project (ai_gateway) or by its
    last run (run_ai_config.gateway) stops the run with the reason and that name, never the login in its place; the
    flags that need the gateways (-gw bare, --gw_default, --gw_unset) say so too."""
    cls = task_namespace('run-ai')['CTask']
    task = cls.__new__(cls)
    task.cm = NoGateways()
    task._read_desc = lambda path: {'ai_gateway': 'acme'} if path == 'declares' else {}

    assert task._gateway_choice({}, 'claude', '', '', False) == ('login', 'no AI gateways on this machine', None, '')
    assert task._gateway_choice({}, 'claude', 'login', '', False)[0] == 'login'
    for args, kw, word in ((('claude', 'acme', '', False), {}, 'the flag'),
                           (('claude', '', True, False), {}, 'the flag -gw'),
                           (('claude', '', '', False), {'project_path': 'declares'}, "the project's ai_gateway"),
                           (('codex', '', '', False), {'recorded': 'acme-gone'}, 'its last run')):
        name, how, err, note = task._gateway_choice({}, *args, **kw)
        assert name == '' and err['return'] == 1 and 'set-ai-gateway' in err['error'] and word in err['error'], (args, kw, err)
    # -ln is a login run whatever is recorded, and asks nothing more
    assert task._gateway_choice({}, 'claude', '', '', True, recorded='acme-gone') == ('login', 'the flag -ln', None, '')

    for gw, gw_default, gw_unset in ((True, '', False), ('', True, False), ('', '', True)):
        out = task._gateway_flags({}, 'claude', '', gw, False, gw_default, gw_unset, False)
        assert out[3] and 'set-ai-gateway' in out[3]['error'], (gw, gw_default, gw_unset)


def test_the_models_a_run_can_take_through_a_gateway(task_namespace):
    """--list_models (what the pages' AI context reads): a gateway that passes the harness's own login on lists the
    harness's own models (the user, 2026-11-19: "it's a pass through"); a key's gateway its catalog; a catalog that
    does not answer (a model server that is down) says why instead of an empty list."""
    cls = task_namespace('run-ai')['CTask']
    task = cls.__new__(cls)
    own = {'flags': {'model': ['--model', '{{model}}']}, 'models': [{'name': 'own-model-1'}, {'name': 'own-model-2'}]}
    task._load_models = lambda h: (dict(own), 'tool/claude/_desc_models.yaml', '')
    task._harness_refs = lambda h: ('run-claude,0', 'claude,0')
    rows = {'pass': {'alias': 'pass', 'auth': 'login'}, 'acme': {'alias': 'acme', 'auth': 'x-api-key (k)'},
            'down': {'alias': 'down', 'auth': 'none'}}
    answers = {'acme': {'return': 0, 'models': {'anthropic': ['acme-model']}, 'catalogs': {'anthropic': 'http://acme/v1/models'}, 'errors': {}},
               'down': {'return': 0, 'models': {}, 'catalogs': {'anthropic': 'http://127.0.0.1:9/v1/models'},
                        'errors': {'anthropic': 'http 0 from http://127.0.0.1:9/v1/models: refused'}}}

    class CM:
        def access(self, p):
            if p.get('command') == 'list':
                return {'return': 0, 'gateways': [rows[p['arg1']]] if p.get('arg1') in rows else []}
            if p.get('command') == 'models':
                assert p['arg1'] != 'pass', 'a login pass-through has no catalog to ask'
                return answers[p['arg1']]
            return {'return': 1, 'error': 'unexpected %s' % p}

    task.cm = CM()
    text = task._list_models('claude', False, {'claude': 'pass'})['text']
    assert 'cxt run-ai --harness=claude --model=own-model-1' in text and 'through the gateway pass, which passes the login on' in text
    text = task._list_models('claude', False, {'claude': 'acme'})['text']
    assert 'cxt run-ai --harness=claude --model=acme-model' in text and 'own-model-1' not in text
    text = task._list_models('claude', False, {'claude': 'down'})['text']
    assert 'no models: the catalog of the anthropic wire: http 0 from http://127.0.0.1:9/v1/models: refused' in text
    assert 'cxt run-ai --harness=claude --model=' not in text


def test_an_agent_that_run_ai_started_says_so_in_its_generator_record(task_namespace, monkeypatch):
    """cmeta_task: run-ai, the harness and the run in CMETA_GENERATOR - the project by its UIDs alone (its name may be
    private while the artifacts that carry the record are public); nothing of it outside run-ai."""
    import importlib.util
    import json
    from pathlib import Path
    import sys
    import types
    # the record is built inside the function, which imports the task category's helpers by the package name the
    # engine gives them: the real ctask.py under that name, for this test only
    spec = importlib.util.spec_from_file_location('ctask_for_generator', str(Path(__file__).parents[2] / 'category' / 'task' / 'api' / 'ctask.py'))
    ctask = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ctask)
    for name, module in (('task_c36be4b9314a45e0', types.ModuleType('task_c36be4b9314a45e0')),
                         ('task_c36be4b9314a45e0.api', types.ModuleType('task_c36be4b9314a45e0.api')),
                         ('task_c36be4b9314a45e0.api.ctask', ctask)):
        monkeypatch.setitem(sys.modules, name, module)
    run = 'project=work,0123456789abcdef::my%20private%20work,fedcba9876543210;conversation=20261119-1200;run=20261119-120000'
    for harness in ('claude', 'codex'):
        gen = task_namespace('run-' + harness)['_agent_generator']
        monkeypatch.setenv('CMETA_AI_RUN', run)
        rec = gen('no-such-harness-binary', ['--model', 'm'])
        assert rec['method'] == 'agent' and rec['cmeta_task'] == 'run-ai' and rec['harness'] == harness, rec
        assert rec['ai_run'] == {'project': '0123456789abcdef::fedcba9876543210', 'conversation': '20261119-1200',
                                 'run': '20261119-120000'}, rec
        assert 'private' not in json.dumps(rec)
        monkeypatch.setenv('CMETA_AI_RUN', 'project=D:/some/folder;run=20261119-120000')
        assert gen('no-such-harness-binary', [])['ai_run'] == {'run': '20261119-120000'}
        monkeypatch.delenv('CMETA_AI_RUN')
        rec = gen('no-such-harness-binary', [])
        assert 'cmeta_task' not in rec and 'ai_run' not in rec and 'harness' not in rec, rec
