"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The guard of setup-compile that refuses a toolchain chosen as the compiler (tool/llvm, 0.55.0): a tool with
compiler flags in its features passes, one that declares itself a compiler passes (tool/javac takes the program's
own flags and was refused as a toolchain from 0.55.0 to 0.61.1 - the strict-provenance matrix of 2026-11-01 found
it on every host), anything else is refused. Offline.
"""

import pathlib

import pytest
import yaml


@pytest.fixture(scope = 'module')
def ns(task_namespace):
    return task_namespace('setup-compile')


def test_a_tool_with_flags_or_declared_a_compiler_passes_the_guard(ns):
    is_compiler_tool = ns['is_compiler_tool']
    assert is_compiler_tool({'flags': {'exe_file': '-o '}})
    assert is_compiler_tool({'compiler': True})
    assert is_compiler_tool({'compiler': 'yes'})          # a CLI or YAML value may arrive as a string
    assert not is_compiler_tool({'flags': {}})
    assert not is_compiler_tool({'compiler': False})
    assert not is_compiler_tool({})
    assert not is_compiler_tool(None)


def test_tool_javac_declares_itself_a_compiler():
    desc = pathlib.Path(__file__).resolve().parents[2] / 'tool' / 'javac' / '_desc.yaml'
    features = yaml.safe_load(desc.read_text(encoding = 'utf-8')).get('features') or {}
    assert features.get('all', {}).get('compiler') is True
