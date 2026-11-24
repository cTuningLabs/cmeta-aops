"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/powershell (2026-11-24): what its description says - the program it looks for (pwsh, never
Windows PowerShell's powershell.exe), the version it reads from what pwsh prints, the releases it takes from the
tags (no previews), and the system's channel on each system (winget's package on Windows, Homebrew's formula - not a
cask - on macOS, nothing installed on Linux).
"""

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = 'module')
def desc():
    with open(REPO_ROOT / 'tool' / 'powershell' / '_desc.yaml', encoding = 'utf-8') as f:
        return yaml.safe_load(f)


def test_it_looks_for_pwsh_and_not_for_windows_powershell(desc):
    assert desc['names'] == ['pwsh{{global.host.vars.file_ext_exe}}']
    assert desc['cmd_get_version'] == '{{tool_path}} --version'
    assert desc['installs_into_system'] is True


@pytest.mark.parametrize('said, version', [
    ('PowerShell 7.7.0', '7.7.0'),
    ('PowerShell 7.4.13\n', '7.4.13'),
    ('PowerShell 7.8.0-preview.1', '7.8.0-preview.1'),
    ('Windows PowerShell\nCopyright (C) Microsoft Corporation.', None),          # powershell.exe prints no such line
])
def test_the_version_is_read_from_what_pwsh_prints(desc, said, version):
    found = None
    for rule in desc['match_version']:
        m = re.search(rule['regex'], said)
        if m:
            found = m.group(rule['group'])
            break
    assert found == version


def test_the_releases_are_the_plain_version_tags(desc):
    tags = ['aaa\trefs/tags/v7.7.0', 'bbb\trefs/tags/v7.8.0-preview.1', 'ccc\trefs/tags/v7.6.0-rc.1', 'ddd\trefs/tags/v7.4.13',
            'eee\trefs/tags/v7.7.0^{}']
    found = [m.group(1) for line in tags for m in [re.search(desc['cmd_get_versions_regex'], line)] if m]
    assert found == ['7.7.0', '7.4.13']


def test_the_channel_of_each_system(desc):
    install = desc['install_cmd']
    assert '--id=Microsoft.PowerShell' in install['windows'] and '--source winget' in install['windows']
    assert install['windows'].startswith('{{global.winget.qpath}} install ')
    assert install['darwin'] == '{{global.brew.qpath}} install powershell'          # a formula: Homebrew has no such cask
    assert 'linux' not in install                                                   # detected there, not installed
    assert 'snap install powershell --classic' in desc['install_help_text']
    assert '{{global.host.os_env.LOCALAPPDATA}}\\Microsoft\\WindowsApps' in desc['extra_paths']['windows']      # the MSIX package's alias
    assert 'C:\\Program Files\\PowerShell\\7' in desc['extra_paths']['windows']                                  # Microsoft's MSI
    assert '/opt/microsoft/powershell/7' in desc['extra_paths']['linux']
