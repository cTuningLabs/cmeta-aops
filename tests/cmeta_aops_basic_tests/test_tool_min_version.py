"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

min_version in a tool's _desc.yaml: the detection skips a copy older than it as if it was absent, so the setup
installs a current one. GNU Screen is the first user: -Q (a session's windows) came in 4.2 and macOS ships 4.00.03.
"""

import importlib.util
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def common():
    spec = importlib.util.spec_from_file_location('setup_common_under_test', REPO_ROOT / 'task' / 'setup' / 'common.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def packages():
    from cmeta.packages import Packages

    return Packages.__new__(Packages)        # match_version needs no engine state


def screen_desc():
    return yaml.safe_load((REPO_ROOT / 'tool' / 'screen' / '_desc.yaml').read_text(encoding='utf-8'))


def version_of(output):
    rule = screen_desc()['match_version'][0]
    m = re.search(rule['regex'], output, re.IGNORECASE | re.MULTILINE)
    return m.group(rule['group']) if m else None


def test_screen_declares_the_version_of_its_query():
    assert screen_desc()['min_version'] == '4.2'


def test_older_copies_are_skipped_with_a_note(common, packages):
    found = [{'path': '/usr/bin/screen', 'detected_version': version_of('Screen version 4.00.03 (FAU) 23-Oct-06')},
             {'path': '/usr/bin/screen-debian', 'detected_version': version_of('Screen version 4.09.01 (GNU) 20-Aug-23')},
             {'path': '/opt/homebrew/bin/screen', 'detected_version': version_of('Screen version 5.0.1 (build on 2025-05-12)')}]
    assert [x['detected_version'] for x in found] == ['4.00.03', '4.09.01', '5.0.1']

    kept, notes = common.at_min_version(packages, '4.2', found)
    assert [x['path'] for x in kept] == ['/usr/bin/screen-debian', '/opt/homebrew/bin/screen']
    assert len(notes) == 1 and '/usr/bin/screen' in notes[0] and '4.00.03' in notes[0] and 'min_version 4.2' in notes[0]


def test_only_older_copies_leave_nothing(common, packages):
    kept, notes = common.at_min_version(packages, '4.2', [{'path': '/usr/bin/screen', 'detected_version': '4.00.03'}])
    assert kept == [] and len(notes) == 1


def test_the_detection_applies_min_version_after_the_requested_version():
    src = (REPO_ROOT / 'task' / 'setup' / 'detect.py').read_text(encoding='utf-8')
    filter_at = src.index("r = self.cm.packages.match_version(version, detected_version)")
    min_at = src.index("common.at_min_version(self.cm.packages, min_version, matched_paths_with_versions)")
    empty_at = src.index("if not matched_paths_with_versions:", min_at)
    assert filter_at < min_at < empty_at
