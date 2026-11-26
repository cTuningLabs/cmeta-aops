"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/rocm knows each ROCm by its release, as the installation says it, so that several side by side are asked for
by release (an MI300X, 2026-11-26: AMD's ROCm 10.2 was known by rocm-smi's own version 4.0.0, the ROCm 10.1 this
tool installed by 10.1.0 - a run without a version took 10.1, and 10.2 could not be asked for). Offline: the tool's
helpers on stand-in folders; the links of a system ROCm only where symbolic links can be made.
"""

import os
import re
import sys

import pytest
import yaml

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'tool', 'rocm')


def helpers():
    path = os.path.join(TOOL, 'api_v1.py')
    with open(path, encoding = 'utf-8') as f:
        src = f.read().replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool', 'class InitCTool:\n    pass')
    ns = {'__name__': 'rocm_under_test', '__file__': path}
    exec(compile(src, path, 'exec'), ns)
    return ns


def write(path, text = ''):
    os.makedirs(os.path.dirname(str(path)), exist_ok = True)
    with open(str(path), 'w') as f:
        f.write(text)
    return str(path)


def detected(output):
    """The version the engine takes from an output: the first regex of match_version that matches (task/setup)."""
    with open(os.path.join(TOOL, '_desc.yaml'), encoding = 'utf-8') as f:
        desc = yaml.safe_load(f)
    for m in desc['match_version']:
        found = re.search(m['regex'], output, re.IGNORECASE | re.MULTILINE)
        if found:
            return found.group(m['group'])
    return None


def test_the_release_file_of_the_installation(tmp_path):
    h = helpers()
    core = tmp_path / 'opt' / 'rocm-6.4.1'
    smi = write(core / 'bin' / 'rocm-smi')
    write(core / '.info' / 'version', '6.4.1-120\n')

    asked = []
    release, folder = h['release_of'](h['link_chain'](smi), lambda exe: asked.append(exe))
    assert (release, folder) == ('6.4.1', str(core / 'bin'))
    # the file says it: no program is run
    assert asked == []


def test_amd_smi_or_rocm_sdk_beside_the_program(tmp_path):
    h = helpers()
    venv_bin = tmp_path / 'cache' / 'task--setup--rocm--1' / 'content' / 'venv' / 'bin'
    smi = write(venv_bin / 'rocm-smi')
    write(venv_bin / 'amd-smi')
    line = 'AMDSMI Tool: 27.1.0+abc | AMDSMI Library version: 27.1.0 | ROCm version: 10.1.0 | amdgpu version: 7.1.3'
    assert h['release_of'](h['link_chain'](smi), lambda exe: line) == ('10.1.0', str(venv_bin))

    sdk_bin = tmp_path / 'python' / 'bin'
    sdk = write(sdk_bin / 'rocm-sdk')
    assert h['release_of'](h['link_chain'](sdk), lambda exe: '10.2.0\n') == ('10.2.0', str(sdk_bin))


def test_an_installation_that_names_no_release(tmp_path):
    h = helpers()
    smi = write(tmp_path / 'usr' / 'bin' / 'rocm-smi')
    assert h['release_of'](h['link_chain'](smi), lambda exe: '') == (None, None)


@pytest.mark.skipif(sys.platform == 'win32', reason = 'symbolic links of a system ROCm (Linux)')
def test_a_system_rocm_found_through_its_links(tmp_path):
    h = helpers()
    core = tmp_path / 'opt' / 'rocm' / 'core-10.2'
    script = write(core / 'libexec' / 'rocm_smi' / 'rocm_smi.py')
    write(core / '.info' / 'version', '10.2.0\n')
    (core / 'bin').mkdir()
    os.symlink(os.path.join('..', 'libexec', 'rocm_smi', 'rocm_smi.py'), str(core / 'bin' / 'rocm-smi'))
    alternatives = tmp_path / 'etc' / 'alternatives'
    usr_bin = tmp_path / 'usr' / 'bin'
    alternatives.mkdir(parents = True)
    usr_bin.mkdir(parents = True)
    os.symlink(str(core / 'bin' / 'rocm-smi'), str(alternatives / 'rocm-smi'))
    os.symlink(str(alternatives / 'rocm-smi'), str(usr_bin / 'rocm-smi'))

    chain = h['link_chain'](str(usr_bin / 'rocm-smi'))
    assert chain[0] == str(usr_bin / 'rocm-smi') and chain[-1] == script
    # the release and the bin of the installation the links lead to, not the folder of rocm_smi.py
    assert h['release_of'](chain, lambda exe: '') == ('10.2.0', str(core / 'bin'))


def test_the_version_is_the_release_when_there_is_one():
    # what detect_versions hands the engine for AMD's ROCm 10.2, and for a rocm-smi without a release
    assert detected('ROCm release: 10.2.0\nROCM-SMI version: 4.0.0+2a0e6e67\nROCM-SMI-LIB version: 7.8.0') == '10.2.0'
    assert detected('ROCM-SMI version: 4.0.0+2a0e6e67\nROCM-SMI-LIB version: 7.8.0') == '4.0.0+2a0e6e67'
    # rocm-sdk alone, and the rocm-smi this tool writes beside amd-smi
    assert detected('ROCm release: 10.1.0\n10.1.0') == '10.1.0'
    assert detected('10.1.0') == '10.1.0'
    assert detected('ROCm release: 10.1.0\nROCM-SMI version: 10.1.0 (amd-smi)') == '10.1.0'
