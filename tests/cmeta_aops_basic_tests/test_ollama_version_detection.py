"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/ollama's version rules, applied as task setup applies them (in order, the first rule that matches): "ollama
--version" names the server it reaches first and this binary on a second line when they differ - the binary's own
version must win (2026-10-17: a machine running Ollama 0.40.0 made a downloaded 0.40.5 look like 0.40.0).
"""

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def detected(output):
    rules = yaml.safe_load((REPO_ROOT / 'tool' / 'ollama' / '_desc.yaml').read_text(encoding='utf-8'))['match_version']
    for rule in rules:
        m = re.search(rule['regex'], output, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(rule['group'])
    return None


def test_the_binary_version_wins_over_the_server():
    assert detected('ollama version is 0.40.0\nWarning: client version is 0.40.5') == '0.40.5'


def test_without_a_server_and_with_the_same_server():
    assert detected('Warning: could not connect to a running Ollama instance\nWarning: client version is 0.40.5') == '0.40.5'
    assert detected('ollama version is 0.40.5') == '0.40.5'
