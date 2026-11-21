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

    # What the project ran with last (run-ai's record) goes before what it declares and before this machine's config -
    # a gateway or the login alike - and after a flag
    cfg.clear()
    cfg.update({'run_ai_gateway': 'true', 'run_ai_gateway_name': 'acme', 'run_ai_gateway_codex': 'login'})
    how = "the project's run_ai_config (its last run; -ln or -gw=<alias> changes it)"
    assert task.choose('claude', recorded='other') == ('other', how, '')
    assert task.choose('claude', recorded='login') == ('login', how, '')
    assert task.choose('codex', recorded='other', project='acme') == ('other', how, '')
    assert task.choose('claude', gateway='third', recorded='other') == ('third', 'the flag --gateway', '')
    assert task.choose('claude', ln=True, recorded='other') == ('login', 'the flag -ln', '')
    assert task.choose('claude', gw=True, recorded='other') == ('acme', 'the flag -gw (config run_ai_gateway_name)', '')

    # -ln and a gateway flag together say opposite things: an error, where -ln used to win without a word
    for both in (dict(gateway='acme'), dict(gw='acme'), dict(gw=True)):
        choice, _, err = task.choose('claude', ln=True, **both)
        assert choice == '' and err.startswith('-ln (the tool\'s own login) and -gw / --gateway'), both
    assert task.choose('claude', ln=True, gateway='login') == ('login', 'the flag -ln', '')


def test_this_machine_default_is_shown_set_and_removed(cm, tmp_path):
    """cx ai.gateway default: the keys of config::default the harness runs read - set for a gateway of this machine,
    removed with --unset; where a harness has a key of its own, that key is the one a default for it changes, and a
    key that pins a harness to its login is never removed."""
    def config():
        r = cm.access({'category': 'config', 'command': 'read', 'arg1': 'default', 'con': False})
        data = r.get('config_cmeta', {}) if r['return'] == 0 else {}
        return {k: v for k, v in data.items() if k.startswith('run_ai_gateway')}

    def default(**p):
        return cm.access(dict({'category': 'ai.gateway', 'command': 'default', 'con': False}, **p))

    before = config()
    try:
        cm.access({'category': 'config', 'command': 'unset', 'arg1': 'default', 'con': False,
                   'meta': {k: '' for k in before}}) if before else None
        name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8])
        other = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8])

        r = default()
        assert r['return'] == 0 and r['default'] == '' and r['harness'] == {} and config() == {}

        r = default(arg1=name)
        assert r['return'] == 0 and r['default'] == name and r['written'] == {'run_ai_gateway': True, 'run_ai_gateway_name': name}
        assert config() == {'run_ai_gateway': True, 'run_ai_gateway_name': name}
        # the task that chooses reads the same keys
        r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'set-ai-gateway', 'harness': 'claude', 'connect': False, 'con': False, 'quiet': True})
        assert r['return'] == 0 and r['gateway'] == name and r['how'] == 'config run_ai_gateway'

        # a harness without a key of its own: the general default changes; with one: that key
        r = default(arg1=other, harness='codex')
        assert r['written'] == {'run_ai_gateway': True, 'run_ai_gateway_name': other}
        cm.access({'category': 'config', 'command': 'set', 'arg1': 'default', 'meta': {'run_ai_gateway_codex': 'login'}, 'con': False})
        r = default(arg1=name, harness='codex')
        assert r['written'] == {'run_ai_gateway_codex': name} and r['harness'] == {'codex': name} and r['default'] == other

        # what is no gateway of this machine is refused, and "login" is no gateway
        assert default(arg1='no-such-gateway-' + uuid.uuid4().hex[:6])['return'] > 0
        r = default(arg1='login')
        assert r['return'] > 0 and '--unset' in r['error']
        assert default(arg1=name, unset=True)['return'] > 0
        assert config()['run_ai_gateway_name'] == other

        # --unset: the default goes, and the harness's own key when it names a gateway ...
        r = default(unset=True, harness='codex')
        assert r['return'] == 0 and sorted(r['removed']) == ['run_ai_gateway', 'run_ai_gateway_codex', 'run_ai_gateway_name']
        assert config() == {} and r['default'] == ''
        # ... never one that pins the harness to its login
        cm.access({'category': 'config', 'command': 'set', 'arg1': 'default', 'con': False,
                   'meta': {'run_ai_gateway': True, 'run_ai_gateway_name': name, 'run_ai_gateway_codex': 'login'}})
        r = default(unset=True, harness='codex')
        assert sorted(r['removed']) == ['run_ai_gateway', 'run_ai_gateway_name'] and config() == {'run_ai_gateway_codex': 'login'}
        assert default(unset=True)['removed'] == []
    finally:
        left = config()
        if left:
            cm.access({'category': 'config', 'command': 'unset', 'arg1': 'default', 'meta': {k: '' for k in left}, 'con': False})
        if before:
            cm.access({'category': 'config', 'command': 'set', 'arg1': 'default', 'meta': before, 'con': False})


def test_the_gateways_to_choose_from(cm, tmp_path, monkeypatch, capsys):
    """cx ai.gateway pick: a numbered list of the gateways a harness can use, the default marked, one question -
    a number, a name or Enter for the default."""
    import builtins
    name = gateway(cm, tmp_path, 'gw-pick-a-' + uuid.uuid4().hex[:6])
    openai_only = gateway(cm, tmp_path, 'gw-pick-b-' + uuid.uuid4().hex[:6], wires={'openai': '/v1'})
    own = passthrough(cm, 'gw-pick-c-' + uuid.uuid4().hex[:6], base_url='http://127.0.0.1:9/pass',
                      wires={'anthropic': '/anthropic', 'openai': '/openai'}, auth={'header': 'login'})
    answers = []
    monkeypatch.setattr(builtins, 'input', lambda prompt='': answers.pop(0))

    def pick(answer, **p):
        answers.append(answer)
        return cm.access(dict({'category': 'ai.gateway', 'command': 'pick', 'arg1': 'gw-pick-*', 'con': True}, **p))

    r = pick('1', harness='claude')
    assert r['return'] == 0 and r['gateways'] == sorted([name, own]) and r['gateway'] == sorted([name, own])[0]
    shown = capsys.readouterr().out
    assert name in shown and own in shown and openai_only not in shown and 'own login' in shown and 'sk-test' not in shown

    # by its name; every wire for a harness that takes both; a login only for the harnesses with a recipe
    assert pick(own, harness='codex')['gateway'] == own
    assert pick('2', harness='opencode')['gateways'] == sorted([name, openai_only])
    assert sorted(pick('1')['gateways']) == sorted([name, openai_only, own])

    # what is none of the list, and nothing without a default: no gateway is guessed
    assert pick('99', harness='claude')['return'] > 0
    assert pick('', harness='claude')['return'] > 0
    monkeypatch.setattr(builtins, 'input', lambda prompt='': (_ for _ in ()).throw(EOFError()))
    r = cm.access({'category': 'ai.gateway', 'command': 'pick', 'arg1': 'gw-pick-*', 'harness': 'claude', 'con': True})
    assert r['return'] > 0 and 'nobody to ask' in r['error']


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


def passthrough(cm, name, **desc):
    """A gateway artifact of the test home with this _desc.yaml and nothing else: a pass-through names no secret."""
    r = cm.access({'category': 'ai.gateway', 'command': 'get', 'arg1': 'local:' + name})
    assert r['return'] == 0, r
    cm.utils.files.safe_write_file(os.path.join(r['artifact']['path'], '_desc.yaml'), desc)
    return name


def test_a_gateway_that_passes_the_harness_own_login_on(cm, tmp_path):
    """auth.header "login": the harness keeps its own account, the artifact changes only the address - no key is read,
    no variable or setting of a key is made, and the run is marked a login run (own_login) for the task that starts it."""
    name = passthrough(cm, 'gw-' + uuid.uuid4().hex[:8], base_url='http://127.0.0.1:9/pass',
                       wires={'anthropic': '/anthropic', 'openai': '/openai'}, auth={'header': 'login'})
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0, r
    assert r['env'] == {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:9/pass/anthropic'} and r['args'] == [] and r['model'] == ''
    assert 'claude_settings' not in r and r['own_login'] is True
    assert any('own login' in n for n in r['notes']) and not any('connectors' in n for n in r['notes'])

    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'codex', 'con': False})
    assert r['return'] == 0, r
    words = ' '.join(r['args'])
    assert 'base_url="http://127.0.0.1:9/pass/openai"' in words and 'requires_openai_auth=true' in words
    assert 'env_key' not in words and 'env_http_headers' not in words and r['env'] == {} and r['own_login'] is True and r['model'] == ''

    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'opencode', 'con': False})
    assert r['return'] > 0 and 'own login' in r['error'] and 'opencode has none' in r['error']

    # the hello of "test" has no login to send
    r = cm.access({'category': 'ai.gateway', 'command': 'test', 'arg1': name, 'con': False})
    assert r['return'] > 0 and 'own login' in r['error']

    # the task that chooses hands the mark on; a key's gateway has none
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'set-ai-gateway', 'harness': 'claude', 'gateway': name, 'con': False, 'quiet': True})
    assert r['return'] == 0 and r['own_login'] is True and r['env'] == {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:9/pass/anthropic'}
    other = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8])
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'set-ai-gateway', 'harness': 'claude', 'gateway': other, 'con': False, 'quiet': True})
    assert r['return'] == 0 and 'own_login' not in r

    # the listing says what it is
    r = cm.access({'category': 'ai.gateway', 'command': 'list', 'arg1': name, 'con': False})
    assert r['return'] == 0 and r['gateways'][0]['auth'] == 'login'


def test_a_local_pass_through_that_is_down_names_its_start_command(cm, tmp_path):
    """A pass-through for a login has no catalog to read: when it names the task that provides it, its address must at
    least accept a connection - else the error says how to start it. Without provided_by nothing is asked."""
    name = passthrough(cm, 'gw-' + uuid.uuid4().hex[:8], base_url='http://127.0.0.1:9/pass', wires={'anthropic': '/anthropic', 'openai': '/openai'},
                       auth={'header': 'login'}, provided_by={'task': 'run-some-server', 'params': {'port': 9}})
    for harness in ('claude', 'codex'):
        r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': harness, 'con': False})
        assert r['return'] > 0 and 'nothing listens on 127.0.0.1:9' in r['error'], r
        assert 'start it: cx task run run-some-server --port=9' in r['error']

    # the same kind of address answering: a listener of the test
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        up = passthrough(cm, 'gw-' + uuid.uuid4().hex[:8], base_url='http://127.0.0.1:%d/pass' % s.getsockname()[1],
                         wires={'anthropic': ''}, auth={'header': 'login'}, provided_by={'task': 'run-some-server'})
        r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': up, 'harness': 'claude', 'con': False})
        assert r['return'] == 0 and r['own_login'] is True, r


def test_a_pass_through_takes_what_it_does_not_say_from_its_upstream(cm, tmp_path):
    """upstream: <alias> - the wires, the key and the models of that gateway, under the pass-through's own address: one
    place to change them. What the pass-through says itself wins; an address as upstream brings nothing."""
    parent = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8])
    name = passthrough(cm, 'gw-' + uuid.uuid4().hex[:8], base_url='http://127.0.0.1:9/through', upstream=parent)
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0, r
    assert r['env']['ANTHROPIC_BASE_URL'] == 'http://127.0.0.1:9/through/anthropic' and r['env']['CMETA_AI_GATEWAY_KEY'] == 'sk-test-' + parent
    assert r['model'] == 'claude-opus-x' and 'apiKeyHelper' in r['claude_settings'] and 'own_login' not in r
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'codex', 'con': False})
    assert r['return'] == 0 and 'base_url="http://127.0.0.1:9/through/openai/v1"' in ' '.join(r['args']) and r['model'] == 'gpt-x'
    r = cm.access({'category': 'ai.gateway', 'command': 'list', 'arg1': name, 'con': False})
    assert r['gateways'][0]['wires'] == 'anthropic,openai' and r['gateways'][0]['auth'] == 'x-api-key (%s-key)' % parent

    own = passthrough(cm, 'gw-' + uuid.uuid4().hex[:8], base_url='http://127.0.0.1:9/own', upstream=parent, wires={'anthropic': ''},
                      models={'claude': {'default': 'claude-own'}})
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': own, 'harness': 'claude', 'con': False})
    assert r['return'] == 0 and r['env']['ANTHROPIC_BASE_URL'] == 'http://127.0.0.1:9/own' and r['model'] == 'claude-own'
    assert 'ANTHROPIC_DEFAULT_OPUS_MODEL' not in r['env'] and r['env']['CMETA_AI_GATEWAY_KEY'] == 'sk-test-' + parent

    for upstream in ('https://example.org/api', {'anthropic': 'https://example.org'}, 'no-such-gateway-' + uuid.uuid4().hex[:6]):
        bare = passthrough(cm, 'gw-' + uuid.uuid4().hex[:8], base_url='http://127.0.0.1:9/bare', upstream=upstream)
        r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': bare, 'harness': 'claude', 'con': False})
        assert r['return'] > 0 and 'needs the anthropic wire' in r['error'], r


RUN = 'project=work::my%20work,0123456789abcdef;conversation=20261119-1200;run=20261119-120000'


def test_a_gateway_that_asks_is_told_which_run_a_request_comes_from(cm, tmp_path, monkeypatch):
    """run_header: the harness sends run-ai's CMETA_AI_RUN in that header with every request - Claude Code through
    ANTHROPIC_CUSTOM_HEADERS, Codex through its provider's env_http_headers (the variable's name on the command line,
    never its value), OpenCode through its providers' headers. Nothing without the header, the variable, or with a
    header name that is not one word."""
    monkeypatch.setenv('CMETA_AI_RUN', RUN)
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], run_header='X-Cmeta-Run')

    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0, r
    assert r['env']['ANTHROPIC_CUSTOM_HEADERS'] == 'x-cmeta-run: ' + RUN

    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'codex', 'con': False})
    assert r['return'] == 0, r
    words = ' '.join(r['args'])
    assert 'model_providers.%s.env_http_headers.x-cmeta-run="CMETA_AI_RUN"' % name in words and RUN not in words
    assert 'env_http_headers.x-api-key="CMETA_AI_GATEWAY_KEY"' in words and r['env']['CMETA_AI_RUN'] == RUN

    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'opencode', 'con': False})
    assert r['return'] == 0, r
    providers = r['opencode_config']['provider']
    assert len(providers) == 2 and all(p['options']['headers']['x-cmeta-run'] == RUN for p in providers.values())

    # outside run-ai (no CMETA_AI_RUN): nothing is sent
    monkeypatch.delenv('CMETA_AI_RUN')
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0 and 'ANTHROPIC_CUSTOM_HEADERS' not in r['env']

    # a gateway that does not ask (a company's, a vendor's), or a name that is not one header word: never sent
    monkeypatch.setenv('CMETA_AI_RUN', RUN)
    for extra in ({}, {'run_header': 'x-cmeta-run: injected'}, {'run_header': 'x cmeta'}):
        other = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], **extra)
        for harness in ('claude', 'codex', 'opencode'):
            r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': other, 'harness': harness, 'con': False})
            assert r['return'] == 0, r
            assert 'ANTHROPIC_CUSTOM_HEADERS' not in r['env'] and 'CMETA_AI_RUN' not in r['env'] and 'CMETA_AI_RUN' not in ' '.join(r['args'])
            assert RUN not in str(r.get('opencode_config'))


def test_a_gateway_that_asks_its_clients_for_a_key(cm, tmp_path, monkeypatch):
    """client_key: a gateway server reached over a network checks a key of its own before anything else. Each harness
    sends it its own way - Claude Code a line of ANTHROPIC_CUSTOM_HEADERS, Codex a variable its provider names, OpenCode
    its providers' headers -, a task that asks a model itself gets it in request_headers; never on a command line, and
    never in place of the credential the gateway passes on."""
    monkeypatch.setenv('CMETA_AI_RUN', RUN)
    holder = 'gwc-' + uuid.uuid4().hex[:8]
    gateway(cm, tmp_path, holder)                          # its secret <holder>-key holds the client key
    value = 'sk-test-' + holder
    name = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], run_header='x-cmeta-run',
                   client_key={'header': 'X-Cmeta-Gateway-Key', 'secret': holder + '-key'})

    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'claude', 'con': False})
    assert r['return'] == 0, r
    assert r['env']['ANTHROPIC_CUSTOM_HEADERS'].split(chr(10)) == ['x-cmeta-gateway-key: ' + value, 'x-cmeta-run: ' + RUN]
    assert r['env']['CMETA_AI_GATEWAY_KEY'] == 'sk-test-' + name and r['client_key_header'] == 'x-cmeta-gateway-key'
    assert r['request_headers'] == {'x-api-key': 'sk-test-' + name, 'x-cmeta-gateway-key': value, 'x-cmeta-run': RUN}

    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'codex', 'con': False})
    assert r['return'] == 0, r
    words = ' '.join(r['args'])
    assert 'model_providers.%s.env_http_headers.x-cmeta-gateway-key="CMETA_AI_GATEWAY_CLIENT_KEY"' % name in words
    assert value not in words and r['env']['CMETA_AI_GATEWAY_CLIENT_KEY'] == value

    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': name, 'harness': 'opencode', 'con': False})
    assert r['return'] == 0, r
    assert all(p['options']['headers']['x-cmeta-gateway-key'] == value for p in r['opencode_config']['provider'].values())

    # a pass-through of the harness's own login: the client key goes with it, and no credential of a secret
    login = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], auth={'header': 'login'},
                    client_key={'header': 'x-cmeta-gateway-key', 'secret': holder + '-key'})
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': login, 'harness': 'claude', 'con': False})
    assert r['return'] == 0 and r['own_login'] is True, r
    # (this one names no run_header: the run is not sent)
    assert r['env']['ANTHROPIC_CUSTOM_HEADERS'] == 'x-cmeta-gateway-key: ' + value
    assert r['request_headers'] == {'x-cmeta-gateway-key': value} and 'CMETA_AI_GATEWAY_KEY' not in r['env']

    # the listing names the client key's secret, never its value
    rows = {x['alias']: x for x in cm.access({'category': 'ai.gateway', 'command': 'list', 'con': False})['gateways']}
    assert rows[name]['auth'].endswith('+ client key (%s-key)' % holder) and value not in str(rows)

    # a client key whose secret is not here, or a header that is a credential's own: an error, nothing started
    for bad, words in (({'header': 'x-cmeta-gateway-key', 'secret': 'no-such-' + uuid.uuid4().hex[:6]}, 'is not on this machine'),
                       ({'header': 'authorization', 'secret': holder + '-key'}, 'a header of its own'),
                       ('x-cmeta-gateway-key', 'must be')):
        other = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], client_key=bad)
        r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': other, 'harness': 'claude', 'con': False})
        assert r['return'] > 0 and words in r['error'] and value not in r['error'], r


def test_connect_gives_a_plain_client_the_wires_and_the_thinking_switch(cm, tmp_path):
    """connect returns the wires with what a pass-through inherits (a task that asks a model itself builds its address
    from them), and thinking_off - how a request turns an open model's reasoning off - only where a gateway, or the
    upstream of a pass-through, declares it (2026-11-21)."""
    off = {'chat_template_kwargs': {'enable_thinking': False}}
    server = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8], thinking_off=off)
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': server, 'harness': 'codex', 'con': False})
    assert r['return'] == 0 and r['wires'] == {'anthropic': '/anthropic', 'openai': '/openai/v1'} and r['thinking_off'] == off, r

    through = passthrough(cm, 'gw-' + uuid.uuid4().hex[:8], base_url='http://127.0.0.1:9/through', upstream=server)
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': through, 'harness': 'codex', 'con': False})
    assert r['return'] == 0 and r['wires'] == {'anthropic': '/anthropic', 'openai': '/openai/v1'} and r['thinking_off'] == off, r
    assert r['base_url'] == 'http://127.0.0.1:9/through'

    vendor = gateway(cm, tmp_path, 'gw-' + uuid.uuid4().hex[:8])
    r = cm.access({'category': 'ai.gateway', 'command': 'connect', 'arg1': vendor, 'harness': 'codex', 'con': False})
    assert r['return'] == 0 and 'thinking_off' not in r, r
