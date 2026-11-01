"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The login/gateway switch: the choice set-ai-gateway makes (the flag, the project, the config, the default), and what
the ai.gateway category gives each harness (the environment, Codex's words, OpenCode's providers) - with a gateway
artifact and a token secret made in the test home; no network (the catalog is unreachable on purpose).
"""
import os
import uuid

import pytest

SECRET_UID = 'secret,9d63451ea1f14010'


def gateway(cm, tmp_path, name, **extra):
    """A gateway artifact in the test home's local repository, with a token secret beside it."""
    r = cm.access({'category': 'secret', 'command': 'get', 'arg1': 'local:' + name + '-key'})
    assert r['return'] == 0, r
    files = os.path.join(r['artifact']['path'], 'files')
    os.makedirs(files, exist_ok=True)
    with open(os.path.join(files, 'token'), 'w') as f:
        f.write('sk-test-' + name + '\n')
    cm.utils.files.safe_write_file(os.path.join(r['artifact']['path'], '_desc.yaml'), {'kind': 'token', 'token': {'file': 'files/token'}})
    r = cm.access({'category': 'ai.gateway', 'command': 'get', 'arg1': 'local:' + name})
    assert r['return'] == 0, r
    desc = {'description': 'a test gateway', 'base_url': 'http://127.0.0.1:9', 'wires': {'anthropic': '/anthropic', 'openai': '/openai/v1'},
            'auth': {'header': 'x-api-key', 'secret': name + '-key'},
            'models': {'claude': {'opus': 'claude-opus-x', 'haiku': 'claude-haiku-x', 'default': 'claude-opus-x'},
                       'codex': {'default': 'gpt-x'}, 'opencode': {'default': 'claude-haiku-x'}}}
    desc.update(extra)
    cm.utils.files.safe_write_file(os.path.join(r['artifact']['path'], '_desc.yaml'), desc)
    return name


def test_connect_gives_each_harness_what_it_needs(cm, tmp_path):
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8])
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0, r
    assert r['env']['ANTHROPIC_BASE_URL'] == 'http://127.0.0.1:9/anthropic' and r['env']['CMETA_AI_GATEWAY_KEY'] == 'sk-test-' + name
    assert r['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'] == 'claude-opus-x' and r['model'] == 'claude-opus-x' and r['args'] == []
    assert 'ANTHROPIC_DEFAULT_SONNET_MODEL' not in r['env'] and r['wire'] == 'anthropic'
    # the key reaches Claude Code through an apiKeyHelper, never as ANTHROPIC_API_KEY (its warning beside a claude.ai login)
    assert 'ANTHROPIC_API_KEY' not in r['env'] and 'ANTHROPIC_AUTH_TOKEN' not in r['env']
    assert set(r['claude_settings']) == {'apiKeyHelper', 'disableClaudeAiConnectors'} and r['claude_settings']['disableClaudeAiConnectors'] is True
    assert "os.environ.get('CMETA_AI_GATEWAY_KEY', '')" in r['claude_settings']['apiKeyHelper'] and 'sk-test' not in r['claude_settings']['apiKeyHelper']
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'codex', 'model': 'gpt-y', 'con': False})
    assert r['return'] == 0, r
    words = ' '.join(r['args'])
    assert 'model_provider="%s"' % name in words and 'base_url="http://127.0.0.1:9/openai/v1"' in words
    assert 'env_key="CMETA_AI_GATEWAY_KEY"' in words and 'env_http_headers.x-api-key="CMETA_AI_GATEWAY_KEY"' in words
    assert 'wire_api="responses"' in words and r['env'] == {'CMETA_AI_GATEWAY_KEY': 'sk-test-' + name} and r['model'] == 'gpt-y'
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'opencode', 'con': False})
    assert r['return'] == 0, r
    prov = r['opencode_config']['provider']
    assert set(prov) == {name, name + '-openai'}
    assert prov[name]['npm'] == '@ai-sdk/anthropic' and prov[name]['options']['baseURL'] == 'http://127.0.0.1:9/anthropic/v1'
    assert prov[name]['options']['apiKey'] == 'sk-test-' + name
    assert prov[name + '-openai']['options']['headers'] == {'x-api-key': 'sk-test-' + name} and r['model'] == name + '/claude-haiku-x'
    # a bearer gateway with the openai wire only: Codex gets no header words, OpenCode the key as apiKey
    name2 = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], wires={'openai': '/v1'}, auth={'header': 'bearer', 'secret': None})
    cm.utils.files.safe_write_file(os.path.join(cm.access({'category': 'ai.gateway', 'command': 'find', 'arg1': name2, 'con': False})['artifacts'][0]['path'], '_desc.yaml'),
                                   {'base_url': 'http://127.0.0.1:9', 'wires': {'openai': '/v1'}, 'auth': {'header': 'bearer', 'secret': name2 + '-key'}, 'models': {'codex': {'default': 'gpt-x'}}})
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name2, 'harness': 'codex', 'con': False})
    assert r['return'] == 0 and 'env_http_headers' not in ' '.join(r['args']) and 'env_key="CMETA_AI_GATEWAY_KEY"' in ' '.join(r['args'])
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name2, 'harness': 'claude', 'con': False})
    assert r['return'] > 0 and 'needs the anthropic wire' in r['error']
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name2, 'harness': 'opencode', 'con': False})
    assert r['return'] == 0 and list(r['opencode_config']['provider']) == [name2]
    assert r['opencode_config']['provider'][name2]['options']['apiKey'] == 'sk-test-' + name2
    # a bearer gateway with the anthropic wire: Claude Code takes the token as ANTHROPIC_AUTH_TOKEN (no warning), no helper
    name3 = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], auth={'header': 'bearer', 'secret': None})
    cm.utils.files.safe_write_file(os.path.join(cm.access({'category': 'ai.gateway', 'command': 'find', 'arg1': name3, 'con': False})['artifacts'][0]['path'], '_desc.yaml'),
                                   {'base_url': 'http://127.0.0.1:9', 'wires': {'anthropic': ''}, 'auth': {'header': 'bearer', 'secret': name3 + '-key'}})
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name3, 'harness': 'claude', 'con': False})
    assert r['return'] == 0 and r['env']['ANTHROPIC_AUTH_TOKEN'] == 'sk-test-' + name3 and 'CMETA_AI_GATEWAY_KEY' not in r['env']
    assert r['claude_settings'] == {'disableClaudeAiConnectors': True}


def test_a_gateway_that_does_not_answer_is_an_error_with_its_start_command(cm, tmp_path):
    """A declared catalog is probed: nothing listens on port 9, so connect fails naming the URL and provided_by."""
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], catalog='/v1/models',
                   provided_by={'task': 'run-llama-cpp-server', 'params': {'port': 9}})
    for harness in ('claude', 'codex', 'opencode'):
        r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': harness, 'con': False})
        assert r['return'] > 0 and 'does not answer' in r['error'] and '127.0.0.1:9' in r['error'], r
        assert 'start it: cx task run run-llama-cpp-server --port=9' in r['error']
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'set-ai-gateway', 'harness': 'claude', 'gateway': name, 'con': False, 'quiet': True})
    assert r['return'] > 0 and 'does not answer' in r['error']


def test_connect_without_a_key_and_without_the_secret(cm, tmp_path):
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], auth={'header': 'none'}, wires={'anthropic': '', 'openai': '/v1'})
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0 and r['env']['ANTHROPIC_BASE_URL'] == 'http://127.0.0.1:9' and r['env']['CMETA_AI_GATEWAY_KEY'] == 'local'
    assert 'apiKeyHelper' in r['claude_settings']
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'codex', 'con': False})
    assert r['return'] == 0 and r['env'] == {} and 'env_key' not in ' '.join(r['args'])
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], auth={'header': 'x-api-key', 'secret': 'no-such-secret-' + uuid.uuid4().hex[:6]})
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] > 0 and 'is not on this machine' in r['error'] and '--secrets' in r['error']


def test_the_choice_in_order(cm, tmp_path, task_namespace, monkeypatch):
    cls = task_namespace('set-ai-gateway')['CTask']
    task = cls.__new__(cls)
    task.cm = cm
    cfg = {}
    task._config = lambda: cfg
    assert task.choose('claude') == ('login', 'the default', '')
    assert task.choose('claude', ln=True) == ('login', 'the flag -ln', '')
    assert task.choose('claude', gateway='acme') == ('acme', 'the flag --gateway', '')
    assert task.choose('claude', gateway='LOGIN') == ('login', 'the flag --gateway', '')
    assert task.choose('claude', gw='llama-cpp-local') == ('llama-cpp-local', 'the flag --gateway', '')
    assert task.choose('claude', gw=True)[2].startswith('-gw asks for the configured gateway')
    cfg.update({'run_ai_gateway_name': 'acme'})
    assert task.choose('claude', gw=True) == ('acme', 'the flag -gw (config run_ai_gateway_name)', '')
    assert task.choose('claude') == ('login', 'the default', '')                    # the name alone switches nothing on
    assert task.choose('claude', project='acme') == ('acme', "the project's _desc.yaml (ai_gateway)", '')
    cfg.update({'run_ai_gateway': 'true'})
    assert task.choose('claude') == ('acme', 'config run_ai_gateway', '')
    cfg.update({'run_ai_gateway_codex': 'login'})
    assert task.choose('codex') == ('login', 'config run_ai_gateway_codex', '')
    assert task.choose('claude') == ('acme', 'config run_ai_gateway', '')
    assert task.choose('codex', project='acme') == ('acme', "the project's _desc.yaml (ai_gateway)", '')
    assert task.choose('claude', project='login') == ('login', "the project's _desc.yaml (ai_gateway)", '')
    assert task.choose('codex', ln=True) == ('login', 'the flag -ln', '')
    cfg.clear()
    cfg.update({'run_ai_gateway': True})
    assert task.choose('claude')[2].startswith('config::default has run_ai_gateway on but no run_ai_gateway_name')


def test_the_task_with_login_returns_the_choice_only(cm, tmp_path, task_namespace):
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'set-ai-gateway', 'harness': 'claude', 'ln': True, 'con': False, 'quiet': True})
    assert r['return'] == 0 and r['gateway'] == 'login' and 'env' not in r
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8])
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'set-ai-gateway', 'harness': 'codex', 'gateway': name, 'con': False, 'quiet': True})
    assert r['return'] == 0 and r['gateway'] == name and r['env'] == {'CMETA_AI_GATEWAY_KEY': 'sk-test-' + name} and r['model'] == 'gpt-x'
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'set-ai-gateway', 'harness': 'codex', 'gateway': name, 'connect': False, 'con': False, 'quiet': True})
    assert r['return'] == 0 and r['gateway'] == name and 'env' not in r
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'set-ai-gateway', 'harness': 'claude', 'gateway': name, 'con': False, 'quiet': True})
    assert r['return'] == 0 and 'apiKeyHelper' in r['claude_settings'] and r['env']['CMETA_AI_GATEWAY_KEY'] == 'sk-test-' + name


def test_run_claude_merges_the_gateway_settings_into_one_settings_flag(tmp_path, task_namespace):
    """Claude Code reads one --settings: the gateway's go into run-ai's file or the user's JSON, or come alone."""
    import json
    merge = task_namespace('run-claude')['_with_settings']
    add = {'apiKeyHelper': 'helper', 'disableClaudeAiConnectors': True}
    flags, err = merge(['--add-dir', 'x'], add)
    assert err == '' and flags[0] == '--settings' and json.loads(flags[1]) == add and flags[2:] == ['--add-dir', 'x']
    path = tmp_path / 'run.claude.settings.json'
    path.write_text(json.dumps({'autoMemoryDirectory': 'D:/p/!AI/memory'}), encoding='utf-8')
    flags, err = merge(['--settings', str(path), '--session-id', 's'], add)
    assert err == '' and json.loads(flags[1]) == dict(add, autoMemoryDirectory='D:/p/!AI/memory') and flags[2:] == ['--session-id', 's']
    assert json.loads(path.read_text(encoding='utf-8')) == {'autoMemoryDirectory': 'D:/p/!AI/memory'}      # the file stays as it was
    flags, err = merge(['--settings={"model": "m", "apiKeyHelper": "old"}'], add)
    assert err == '' and json.loads(flags[1]) == dict(add, model='m') and len(flags) == 2
    flags, err = merge(['--settings', '{not json'], add)
    assert 'cannot be read' in err and flags == ['--settings', '{not json']
    assert 'not a JSON object' in merge(['--settings', '[1]'], add)[1]


def test_the_general_default_is_marked(cm, task_namespace):
    """config run_ai_gateway is this machine's default for every harness: set-ai-gateway says so ("general"), unlike a
    choice made for the run, the project or the harness."""
    cls = task_namespace('set-ai-gateway')['CTask']
    task = cls.__new__(cls)
    task.cm = cm
    cfg = {'run_ai_gateway': True, 'run_ai_gateway_name': 'acme'}
    task._config = lambda: cfg
    ctx = {'control': {'con': False}}
    r = task.run(ctx, harness='vibe', connect=False)
    assert r['gateway'] == 'acme' and r['general'] is True
    assert 'general' not in task.run(ctx, harness='vibe', gateway='acme', connect=False)
    assert 'general' not in task.run(ctx, harness='vibe', project='acme', connect=False)
    cfg['run_ai_gateway_vibe'] = 'acme'
    assert 'general' not in task.run(ctx, harness='vibe', connect=False)


def test_run_ai_runs_a_harness_without_gateway_support_on_its_login_under_the_general_default(task_namespace):
    """On a machine with the gateway on by default (config run_ai_gateway), "cxai --harness=vibe" stopped with "no
    gateway support" (2026-11-01): the default is for claude, codex and opencode - another harness runs on its own
    login, with a note. A gateway chosen for it (a flag, the project, config run_ai_gateway_<harness>) stays an error."""
    cls = task_namespace('run-ai')['CTask']
    task = cls.__new__(cls)
    answer = {}

    class CM:
        def access(self, p):
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
