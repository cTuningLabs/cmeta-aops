"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/hipcc takes the hipcc of the ROCm selected before it - several ROCm side by side each compile with their own (an
MI300X, 2026-11-26: a run asked for ROCm 10.1 compiled with the system ROCm 10.2's hipcc). Offline: the tool's helpers
on stand-in folders; the links of a system ROCm only where symbolic links can be made.
"""

import os
import sys

import pytest
import yaml

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'tool', 'hipcc')


def helpers():
    path = os.path.join(TOOL, 'api_v1.py')
    with open(path, encoding = 'utf-8') as f:
        src = f.read().replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool', 'class InitCTool:\n    pass')
    ns = {'__name__': 'hipcc_under_test', '__file__': path}
    exec(compile(src, path, 'exec'), ns)
    return ns


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok = True)
    with open(path, 'w') as f:
        f.write('')
    return str(path)


def test_the_hipcc_of_the_selected_rocm_comes_first(tmp_path):
    h = helpers()
    sdk = tmp_path / 'cache' / 'task--setup--rocm--1' / 'content' / 'venv' / 'bin'
    system = tmp_path / 'opt' / 'rocm' / 'core-10.2' / 'bin'
    own = touch(sdk / 'hipcc')
    touch(sdk / 'rocm-sdk')
    other = touch(system / 'hipcc')

    # an SDK of AMD's Python distribution: the hipcc of its bin, whatever the PATH says
    assert h['hipcc_of_rocm'](str(sdk / 'rocm-sdk'), str(sdk)) == own
    assert h['hipcc_of_rocm'](str(sdk / 'rocm-sdk'), '') == own
    # a ROCm without hipcc beside it: nothing (the search of before decides)
    assert h['hipcc_of_rocm'](str(tmp_path / 'usr' / 'bin' / 'rocm-smi'), str(tmp_path / 'usr' / 'bin')) == ''

    # the search of before: the PATH first, then the declared folders, each file once
    assert h['searched']([str(system), str(sdk)], []) == [other, own]
    assert h['searched']([], [str(tmp_path / 'opt' / 'rocm*' / 'core-*' / 'bin')]) == [other]


@pytest.mark.skipif(sys.platform == 'win32', reason = 'symbolic links of a system ROCm (Linux)')
def test_a_system_rocm_found_through_its_links(tmp_path):
    h = helpers()
    core = tmp_path / 'opt' / 'rocm' / 'core-10.2' / 'bin'
    own = touch(core / 'hipcc')
    touch(core / 'rocm-smi')
    alternatives = tmp_path / 'etc' / 'alternatives'
    usr_bin = tmp_path / 'usr' / 'bin'
    alternatives.mkdir(parents = True)
    usr_bin.mkdir(parents = True)
    os.symlink(str(core / 'rocm-smi'), str(alternatives / 'rocm-smi'))
    os.symlink(str(alternatives / 'rocm-smi'), str(usr_bin / 'rocm-smi'))

    chain = h['link_chain'](str(usr_bin / 'rocm-smi'))
    assert chain[0] == str(usr_bin / 'rocm-smi') and chain[-1] == str(core / 'rocm-smi')
    # /usr/bin has no hipcc: the folder the links lead to has
    assert h['hipcc_of_rocm'](str(usr_bin / 'rocm-smi'), str(usr_bin)) == own


def test_the_cache_entry_follows_the_rocm():
    with open(os.path.join(TOOL, '_desc.yaml'), encoding = 'utf-8') as f:
        desc = yaml.safe_load(f)
    rocm = desc['cache_params_use']['all']['rocm']
    assert rocm == {'version': '{{global.rocm.version}}', 'path': '{{global.rocm.path}}'}
