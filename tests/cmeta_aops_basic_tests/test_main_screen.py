"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The main screen for a harness run whose terminal keeps its history (category/task/api/ctask.py, 2026-11-18). A program
on the alternate screen redraws its window in place, so nothing it shows reaches the history one scrolls back to -
Claude Code's fullscreen renderer and Codex's TUI left only the lines printed before them. A terminal that wants the
whole history sets CMETA_NO_ALT_SCREEN, and each harness run asks its harness for the inline mode: Claude Code by its
own variable, Codex and the TUI of Hermes Agent by a flag - never one the run was given, nor against a choice made there.
"""

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def ctask():
    spec = importlib.util.spec_from_file_location('ctask_main_screen_under_test', str(REPO_ROOT / 'category' / 'task' / 'api' / 'ctask.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ASKED = {'PATH': '/usr/bin', 'CMETA_NO_ALT_SCREEN': '1'}


def test_nothing_changes_when_the_terminal_does_not_ask(ctask):
    for value in (None, '', '0', 'no', 'off', 'false'):
        env = {'PATH': '/usr/bin'} if value is None else {'PATH': '/usr/bin', 'CMETA_NO_ALT_SCREEN': value}
        before = dict(env)
        for harness in ('claude', 'codex', 'hermes', 'opencode'):
            assert ctask.main_screen(harness, ['--tui'], env=env) == ([], '')
        assert env == before
    assert all(ctask.main_screen_asked({'CMETA_NO_ALT_SCREEN': v}) for v in ('1', 'yes', 'TRUE', ' on '))


def test_claude_gets_its_own_variable(ctask):
    env = dict(ASKED)
    flags, how = ctask.main_screen('claude', ['--model', 'opus'], env=env)
    assert flags == [] and 'CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1' in how
    assert env['CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN'] == '1'

    # set by the terminal already (the page sets it too): kept as it is, and said
    env = dict(ASKED, CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN='true')
    assert ctask.main_screen('claude', [], env=env)[1] and env['CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN'] == 'true'

    # the renderer chosen in the run's environment wins
    env = dict(ASKED, CLAUDE_CODE_NO_FLICKER='1')
    assert ctask.main_screen('claude', [], env=env) == ([], '') and 'CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN' not in env


def test_codex_runs_inline_unless_the_run_chose(ctask):
    env = dict(ASKED)
    flags, how = ctask.main_screen('codex', ['-m', 'gpt-6', '-c', 'model_reasoning_effort=high'], env=env)
    assert flags == ['--no-alt-screen'] and 'inline' in how and env == ASKED   # a flag; the environment untouched

    assert ctask.main_screen('codex', ['--no-alt-screen'], env=dict(ASKED)) == ([], '')
    assert ctask.main_screen('codex', ['-c', 'tui.alternate_screen=always'], env=dict(ASKED)) == ([], '')
    assert ctask.main_screen('codex', ['--config=tui.alternate_screen="never"'], env=dict(ASKED)) == ([], '')


def test_hermes_tui_keeps_the_scrollback_and_its_repl_is_inline_already(ctask):
    assert ctask.main_screen('hermes', ['--tui'], env=dict(ASKED))[0] == ['--native']
    assert ctask.main_screen('hermes', ['--tui', '--tui-native'], env=dict(ASKED)) == ([], '')
    assert ctask.main_screen('hermes', ['--tui', '--native'], env=dict(ASKED)) == ([], '')
    assert ctask.main_screen('hermes', ['--model', 'm'], env=dict(ASKED)) == ([], '')


def test_a_harness_without_an_inline_mode_is_left_as_it_is(ctask):
    for harness in ('opencode', 'openclaw', 'gemini', 'agy', '', None):
        env = dict(ASKED)
        assert ctask.main_screen(harness, ['--x'], env=env) == ([], '') and env == ASKED
