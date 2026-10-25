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
            'catalog': '/v1/models', 'auth': {'header': 'x-api-key', 'secret': name + '-key'},
            'models': {'claude': {'opus': 'claude-opus-x', 'haiku': 'claude-haiku-x', 'default': 'claude-opus-x'},
                       'codex': {'default': 'gpt-x'}, 'opencode': {'default': 'claude-haiku-x'}}}
    desc.update(extra)
    cm.utils.files.safe_write_file(os.path.join(r['artifact']['path'], '_desc.yaml'), desc)
    return name


def test_connect_gives_each_harness_what_it_needs(cm, tmp_path):
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8])
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0, r
    assert r['env']['ANTHROPIC_BASE_URL'] == 'http://127.0.0.1:9/anthropic' and r['env']['ANTHROPIC_API_KEY'] == 'sk-test-' + name
    assert r['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'] == 'claude-opus-x' and r['model'] == 'claude-opus-x' and r['args'] == []
    assert 'ANTHROPIC_DEFAULT_SONNET_MODEL' not in r['env'] and r['wire'] == 'anthropic'
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


def test_connect_without_a_key_and_without_the_secret(cm, tmp_path):
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], auth={'header': 'none'}, wires={'anthropic': '', 'openai': '/v1'})
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0 and r['env']['ANTHROPIC_BASE_URL'] == 'http://127.0.0.1:9' and r['env']['ANTHROPIC_API_KEY'] == 'local'
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
    assert task.choose('claude', gateway='dapple') == ('dapple', 'the flag --gateway', '')
    assert task.choose('claude', gateway='LOGIN') == ('login', 'the flag --gateway', '')
    assert task.choose('claude', gw='llama-cpp-local') == ('llama-cpp-local', 'the flag --gateway', '')
    assert task.choose('claude', gw=True)[2].startswith('-gw asks for the configured gateway')
    cfg.update({'run_ai_gateway_name': 'dapple'})
    assert task.choose('claude', gw=True) == ('dapple', 'the flag -gw (config run_ai_gateway_name)', '')
    assert task.choose('claude') == ('login', 'the default', '')                    # the name alone switches nothing on
    assert task.choose('claude', project='dapple') == ('dapple', "the project's _desc.yaml (ai_gateway)", '')
    cfg.update({'run_ai_gateway': 'true'})
    assert task.choose('claude') == ('dapple', 'config run_ai_gateway', '')
    cfg.update({'run_ai_gateway_codex': 'login'})
    assert task.choose('codex') == ('login', 'config run_ai_gateway_codex', '')
    assert task.choose('claude') == ('dapple', 'config run_ai_gateway', '')
    assert task.choose('codex', project='dapple') == ('dapple', "the project's _desc.yaml (ai_gateway)", '')
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
