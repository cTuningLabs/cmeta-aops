"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/screen takes every GNU Screen: the version lines of 4.00.03 (macOS's /usr/bin/screen, whose -v exits 1), 4.09 and
5.0 parse with the tool's rule, its exit codes 0 and 1 are declared, and the detection keeps a copy whose version
command exits with a declared code (cmd_get_version_exit_codes; 0 alone by default).
"""

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def desc():
    return yaml.safe_load((REPO_ROOT / 'tool' / 'screen' / '_desc.yaml').read_text(encoding='utf-8'))


def detected(output):
    """The version as task setup reads it: \\r made a line end, the first rule that matches."""
    output = output.replace('\r', '\n').strip()
    for rule in desc()['match_version']:
        m = re.search(rule['regex'], output, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(rule['group'])
    return None


@pytest.mark.parametrize('output, version', [
    ('Screen version 4.00.03 (FAU) 23-Oct-06\r\n', '4.00.03'),
    ('Screen version 4.08.00 (GNU) 05-Feb-20\n', '4.08.00'),
    ('Screen version 4.09.01 (GNU) 20-Aug-23\n', '4.09.01'),
    ('Screen version 5.0.2 (build on 2026-07-11 12:23:56) \n', '5.0.2'),
])
def test_every_version_line_parses(output, version):
    assert detected(output) == version


def test_the_tool_takes_every_version():
    d = desc()
    assert d['cmd_get_version_exit_codes'] == [0, 1]
    assert 'min_version' not in d and 'default_version' not in d


def test_the_detection_keeps_a_declared_exit_code():
    src = (REPO_ROOT / 'task' / 'setup' / 'detect.py').read_text(encoding='utf-8')
    assert "version_exit_codes = desc.get('cmd_get_version_exit_codes') or [0]" in src
    assert 'if returncode in version_exit_codes:' in src and 'if returncode == 0:' not in src
