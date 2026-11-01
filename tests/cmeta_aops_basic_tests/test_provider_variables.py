"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The model providers in the environment of an AI harness (category/task/api/ctask.py, 2026-10-30). A session that ran
through a company gateway handed its key, its URL and its model names to every agent it started: a "login" run of
Claude Code kept ANTHROPIC_DEFAULT_*_MODEL, OpenCode and Hermes saw the gateway's ANTHROPIC_API_KEY, OpenClaw's
claude-cli backend went through the gateway. Now a gateway run names what it puts in, every harness run drops a
parent's gateway, and a login run of claude / codex / opencode also drops what that harness takes its models from -
while the user's own keys stay for the harnesses whose keys are one of their ways in.
"""

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def ctask():
    spec = importlib.util.spec_from_file_location('ctask_providers_under_test', str(REPO_ROOT / 'category' / 'task' / 'api' / 'ctask.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


USER = {'PATH': '/usr/bin', 'GOOGLE_CLOUD_PROJECT': 'my-project', 'GEMINI_API_KEY': 'user-gemini',
        'MISTRAL_API_KEY': 'user-mistral', 'OPENAI_API_KEY': 'user-openai'}


def test_a_parents_gateway_leaves_every_harness_and_the_users_keys_stay(ctask):
    env = dict(USER)
    gateway = {'ANTHROPIC_BASE_URL': 'https://gw', 'ANTHROPIC_API_KEY': 'gw-key', 'ANTHROPIC_DEFAULT_OPUS_MODEL': 'gw-opus'}
    ctask.gateway_into_environment(gateway, env)
    assert env[ctask.GATEWAY_VARS] == 'ANTHROPIC_API_KEY,ANTHROPIC_BASE_URL,ANTHROPIC_DEFAULT_OPUS_MODEL'

    for harness in ('gemini', 'antigravity', 'hermes', 'openclaw'):
        child = dict(env)
        assert ctask.drop_provider_variables(harness, env=child) == sorted(gateway)
        assert child == USER                                            # the gateway and its marker gone, nothing else


def test_a_login_run_drops_what_its_harness_reaches_models_with(ctask):
    inherited = dict(USER, ANTHROPIC_BASE_URL='https://gw', ANTHROPIC_API_KEY='k', ANTHROPIC_DEFAULT_SONNET_MODEL='gw-sonnet',
                     AZURE_OPENAI_ENDPOINT='https://az', CMETA_AI_GATEWAY_KEY='k2', GOOGLE_API_KEY='g', OPENROUTER_API_KEY='o')

    claude = dict(inherited)
    ctask.drop_provider_variables('claude', login=True, env=claude)
    assert not [n for n in claude if n.startswith('ANTHROPIC_')]
    assert claude['MISTRAL_API_KEY'] == 'user-mistral' and claude['OPENAI_API_KEY'] == 'user-openai'   # not Claude's

    codex = dict(inherited)
    ctask.drop_provider_variables('codex', login=True, env=codex)
    assert 'OPENAI_API_KEY' not in codex and 'AZURE_OPENAI_ENDPOINT' not in codex and 'CMETA_AI_GATEWAY_KEY' not in codex
    assert codex['ANTHROPIC_API_KEY'] == 'k'

    opencode = dict(inherited)
    ctask.drop_provider_variables('opencode', login=True, env=opencode)
    assert opencode == {'PATH': '/usr/bin', 'GOOGLE_CLOUD_PROJECT': 'my-project'}   # every provider gone, the project stays


def test_a_gateway_run_keeps_the_users_keys_where_they_do_not_compete(ctask):
    """Codex and OpenCode name the gateway's provider (command line, config): the user's keys stay beside it. Claude
    Code takes the gateway's key through an apiKeyHelper (2026-11-01): the user's ANTHROPIC_API_KEY / _AUTH_TOKEN went
    to the gateway in its place (401 "invalid subscription key", proven live), so its gateway run drops them, a claude.ai
    token and the provider switches too - the user's keys of other providers stay."""
    env = dict(USER, ANTHROPIC_API_KEY='user-anthropic')
    for harness in ('codex', 'opencode'):
        child = dict(env)
        assert ctask.drop_provider_variables(harness, gateway=True, env=child) == [] and child == env

    claude = dict(env, ANTHROPIC_AUTH_TOKEN='t', ANTHROPIC_BASE_URL='https://elsewhere', ANTHROPIC_DEFAULT_SONNET_MODEL='s',
                  CLAUDE_CODE_OAUTH_TOKEN='o', CLAUDE_CODE_USE_BEDROCK='1', CLAUDE_CODE_USE_VERTEX='1')
    assert ctask.drop_provider_variables('claude', gateway=True, env=claude) == sorted(
        ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
         'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX'])
    assert claude == USER

    # a login run keeps the claude.ai login given as a token, never a provider switch
    claude = dict(USER, CLAUDE_CODE_OAUTH_TOKEN='o', CLAUDE_CODE_USE_BEDROCK='1')
    assert ctask.drop_provider_variables('claude', login=True, env=claude) == ['CLAUDE_CODE_USE_BEDROCK']
    assert claude['CLAUDE_CODE_OAUTH_TOKEN'] == 'o'


@pytest.mark.parametrize('task', ['run-claude', 'run-codex', 'run-opencode', 'run-openclaw', 'run-gemini', 'run-agy', 'run-hermes', 'run-vibe'])
def test_every_harness_task_drops_a_parents_gateway(task):
    """Each harness that run-ai drives calls the drop; the three with a gateway put theirs in through the helper."""
    src = (REPO_ROOT / 'task' / task / 'api_v1.py').read_text(encoding='utf-8')
    assert 'drop_provider_variables(' in src
    if task in ('run-claude', 'run-codex', 'run-opencode'):
        assert 'gateway_into_environment(' in src and "os.environ.update({k: str(v) for k, v in (r.get('env')" not in src
    if task == 'run-claude':
        assert "gateway=r['gateway'] != 'login'" in src            # its own Anthropic variables leave a gateway run
