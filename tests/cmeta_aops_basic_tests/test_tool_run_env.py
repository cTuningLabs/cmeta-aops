"""
`cx tool run <tool> --env.+PATH=<dir>`: the library folders a tool found go in front of the "+" variable of the run
(category/tool/api/v1.py, add_dynamic_lib_paths). The command line gives a folder as a text, and the run called
.insert on it (AttributeError) for every tool with dynamic-lib folders; a list (--env.+PATH+=<dir>, cMeta 0.45.3) and
a tuple are taken too (2026-11-23).
"""

import importlib.util
import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _tool_module():
    spec = importlib.util.spec_from_file_location('category_tool_run_env_under_test',
                                                  str(REPO_ROOT / 'category' / 'tool' / 'api' / 'v1.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _tool_module()

LIB1 = os.path.join('opt', 'tool', 'lib')
LIB2 = os.path.join('opt', 'tool', 'lib64')
MINE = os.path.join('home', 'me', 'bin')
MORE = os.path.join('home', 'me', 'more')


def test_no_value_given_gets_the_tool_folders():
    env = {}

    assert tool.add_dynamic_lib_paths(env, '+PATH', [LIB1, LIB2]) == [LIB1, LIB2]
    assert env == {'+PATH': [LIB1, LIB2]}


def test_a_text_of_the_command_line_is_read_as_its_folders():
    # --env.+PATH=<dir>: the text the command line gives (it raised AttributeError: 'str' has no 'insert')
    env = {'+PATH': MINE}

    assert tool.add_dynamic_lib_paths(env, '+PATH', [LIB1]) == [LIB1, MINE]

    # several folders in one text, separated as the engine separates a "+" variable (os.pathsep)
    env = {'+LD_LIBRARY_PATH': MINE + os.pathsep + MORE}

    assert tool.add_dynamic_lib_paths(env, '+LD_LIBRARY_PATH', [LIB1, LIB2]) == [LIB1, LIB2, MINE, MORE]


def test_a_list_is_kept_and_a_folder_is_added_once():
    items = [MINE, LIB1]
    env = {'+DYLD_LIBRARY_PATH': items}

    out = tool.add_dynamic_lib_paths(env, '+DYLD_LIBRARY_PATH', [LIB1, LIB2])

    assert out == [LIB2, MINE, LIB1] and out is items and env['+DYLD_LIBRARY_PATH'] is items


def test_a_tuple_and_an_empty_text():
    env = {'+PATH': (MINE,)}
    assert tool.add_dynamic_lib_paths(env, '+PATH', [LIB1]) == [LIB1, MINE]

    env = {'+PATH': ''}
    assert tool.add_dynamic_lib_paths(env, '+PATH', [LIB1]) == [LIB1]


def test_the_command_line_round_trip():
    # what the engine's parser makes of both forms reaches the helper as it is
    from cmeta.utils.cli import parse_cmd

    one = parse_cmd(['--env.+PATH=' + MINE])['params']['env']
    assert tool.add_dynamic_lib_paths(one, '+PATH', [LIB1]) == [LIB1, MINE]

    two = parse_cmd(['--env.+PATH+=' + MINE, '--env.+PATH+=' + MORE])['params']['env']
    if '+PATH' not in two:
        pytest.skip('this engine has no --key+= (cMeta < 0.45.3)')

    assert two == {'+PATH': [MINE, MORE]}
    assert tool.add_dynamic_lib_paths(two, '+PATH', [LIB1]) == [LIB1, MINE, MORE]
