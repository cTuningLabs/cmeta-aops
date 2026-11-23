"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-ai --main_screen and --autocompact, and the harness's own settings a run records (2026-11-23): where each decision
comes from (the flag, the terminal's own request, this machine's config, the harness), how Claude Code is told its
auto-compact window by its version (the block autocompact of run-claude's _desc.yaml), which settings of a harness the
run reference carries (the block run_settings) - nothing else of its settings file. Offline: no harness is started.
"""

import json
import os

import pytest

from test_run_ai_prompt_cache import CLAUDE, CODEX, run_ai_task


# ---------------------------------------------------------------------------------------------- the screen
def test_the_screen_from_the_flag_the_terminal_and_the_config(task_namespace, repo_root):
    ns, task = run_ai_task(task_namespace, repo_root)

    def ask(asked=None, environ=None, config=None):
        task.cm.config = dict(config or {})
        return task._main_screen('claude', asked, environ=environ or {})

    assert ask() == (None, '')                                                 # nothing asks: the harness decides
    assert ask(True)[0] is True and 'the flag --main_screen' in ask(True)[1]
    assert ask('no')[0] is False and ask('no')[1].endswith('=no')
    terminal = {'CMETA_NO_ALT_SCREEN': '1'}                                    # a session of /ai.sessions
    assert ask(environ=terminal)[0] is True and 'this terminal asks' in ask(environ=terminal)[1]
    assert ask(False, environ=terminal)[0] is False                            # the flag before the terminal
    assert ask(config={'main_screen': 'yes'})[0] is True and 'config task-run-ai main_screen' in ask(config={'main_screen': 'yes'})[1]
    assert ask(config={'main_screen': 'no'})[0] is None                        # the config off: the harness decides
    assert ask(environ=terminal, config={'main_screen': 'no'})[0] is True      # the terminal before the config


# ---------------------------------------------------------------------------------------------- the auto-compact window
def test_the_window_from_the_flag_then_the_config(task_namespace, repo_root):
    ns, task = run_ai_task(task_namespace, repo_root)

    def ask(asked='', harness='claude', ref=CLAUDE, config=None):
        task.cm.config = dict(config or {})
        return task._autocompact(harness, ref, asked)

    assert ask() == ('', '', '')                                               # nothing asked: the harness's own
    assert ask('400k') == ('400k', 'the flag --autocompact', '')
    assert ask('auto')[0] == 'auto' and ask('1.2M')[0] == '1.2M'
    assert ask(config={'autocompact': '300k'})[:2] == ('300k', 'config task-run-ai autocompact')
    assert ask('500k', config={'autocompact': '300k'})[0] == '500k'           # the flag before the config
    assert ask(config={'autocompact': '0'}) == ('', '', '')                   # 0: the harness's own

    # what the harness does not take stops the run before anything is written
    value, where, err = ask('50k')
    assert value == '' and '50,000 tokens' in err and 'at least 100,000' in err
    assert 'auto, or a number of tokens' in ask('big')[2]

    # a harness whose task declares no way: the flag is an error, the config is not applied
    assert 'knows no way to tell the harness "codex"' in ask('400k', 'codex', CODEX)[2]
    value, where, err = ask(harness='codex', ref=CODEX, config={'autocompact': '400k'})
    assert (value, err) == ('', '') and 'the harness decides' in where


def test_claude_code_is_told_its_window_by_its_version(task_namespace):
    ns = task_namespace('run-claude')
    tokens, request = ns['autocompact_tokens'], ns['autocompact_request']
    assert tokens('auto') == ('auto', '') and tokens('400k') == ('400000', '') and tokens('1.2M') == ('1200000', '')
    assert tokens('400000') == ('400000', '') and tokens('200') == ('200000', '')     # Claude Code's own shorthand
    assert 'at least 100k' in tokens('50k')[1] and 'auto, or a number' in tokens('lots')[1]

    r = request('400k', '2.1.330')
    assert r['return'] == 0 and r['flags'] == ['--autocompact', '400000'] and r['way'] == 'autocompact-flag'
    assert request('auto', '2.1.304')['flags'] == ['--autocompact', 'auto']
    r = request('400k', '2.1.303')                                             # before Claude Code had the option
    assert r['return'] == 1 and '2.1.303' in r['error'] and '2.1.304' in r['error'] and 'auto-compact window' in r['error']
    assert request('50k', '2.1.330')['return'] == 1
    assert request('400k', '2.1.330', ways=[])['return'] == 1


# ---------------------------------------------------------------------------------------------- the settings recorded
def test_a_harness_records_its_own_settings_and_nothing_else(task_namespace, repo_root, tmp_path):
    ns, task = run_ai_task(task_namespace, repo_root)
    block = task._harness_block(CLAUDE, 'run_settings')
    assert block['file'] == '~/.claude/settings.json' and block['home_env'] == 'CLAUDE_CONFIG_DIR'

    home = tmp_path / 'claude'
    home.mkdir()
    (home / 'settings.json').write_text(json.dumps({
        'autoCompactWindow': {'claude-opus-5-5': 400000}, 'idleCompaction': False, 'tui': 'default', 'effortLevel': 'high',
        'apiKeyHelper': 'a command that prints a key', 'permissions': {'allow': ['Bash(*)']},
        'env': {'CLAUDE_CODE_SUBAGENT_EFFORT': 'low', 'ANTHROPIC_AUTH_TOKEN': 'never-recorded'}}), encoding='utf-8')
    pairs = ns['harness_settings'](block, environ={'CLAUDE_CONFIG_DIR': str(home), 'CLAUDE_CODE_SUBAGENT_EFFORT': 'medium'})
    got = dict(pairs)
    assert got == {'h_compact': '{"claude-opus-5-5":400000}', 'h_idle_compact': 'no', 'h_effort': 'high', 'h_tui': 'default',
                   'h_sub_effort': 'medium'}                                   # the run's environment before the file's
    assert 'never-recorded' not in json.dumps(pairs) and 'a command' not in json.dumps(pairs)
    assert [k for k, _ in pairs] == ['h_compact', 'h_idle_compact', 'h_effort', 'h_tui', 'h_sub_effort']

    # the file's own env block when the run's environment says nothing; a long value is cut
    (home / 'settings.json').write_text(json.dumps({'autoCompactWindow': 'x' * 90, 'env': {'CLAUDE_CODE_SUBAGENT_EFFORT': 'low'}}), encoding='utf-8')
    got = dict(ns['harness_settings'](block, environ={'CLAUDE_CONFIG_DIR': str(home)}))
    assert got == {'h_compact': 'x' * 40, 'h_sub_effort': 'low'}

    # no file, a file that is no JSON, no block: nothing
    assert ns['harness_settings'](block, environ={'CLAUDE_CONFIG_DIR': str(tmp_path / 'none')}) == []
    (home / 'settings.json').write_text('{ no json', encoding='utf-8')
    assert ns['harness_settings'](block, environ={'CLAUDE_CONFIG_DIR': str(home)}) == []
    assert ns['harness_settings'](None) == [] and task._harness_block('run-openclaw,0', 'run_settings') is None


def test_codex_records_its_config_toml(task_namespace, repo_root, tmp_path):
    pytest.importorskip('tomllib')
    ns, task = run_ai_task(task_namespace, repo_root)
    block = task._harness_block(CODEX, 'run_settings')
    home = tmp_path / 'codex'
    home.mkdir()
    (home / 'config.toml').write_text('model_reasoning_effort = "xhigh"\nmodel_auto_compact_token_limit = 300000\n'
                                      '[tui]\nalternate_screen = "never"\n[model_providers.x]\nenv_key = "SECRET"\n', encoding='utf-8')
    got = dict(ns['harness_settings'](block, environ={'CODEX_HOME': str(home)}))
    assert got == {'h_effort': 'xhigh', 'h_compact': '300000', 'h_alt_screen': 'never'}


def test_the_run_reference_goes_on_with_the_screen_the_window_and_the_harness(task_namespace):
    ns = task_namespace('run-ai')
    ref = ns['run_reference']('work::w,0123456789abcdef', '20261123-160000', '20261123-160000',
                              [('cache_minutes', 60), ('mode', 'interactive'), ('screen', 'main'), ('autocompact', '400k'),
                               ('h_compact', '{"claude-opus-5-5":400000}'), ('h_idle_compact', 'no')])
    assert ref.endswith(';screen=main;autocompact=400k;h_compact=%7B%22claude-opus-5-5%22:400000%7D;h_idle_compact=no')
    assert ref.count(';') == 8                      # nine pairs
