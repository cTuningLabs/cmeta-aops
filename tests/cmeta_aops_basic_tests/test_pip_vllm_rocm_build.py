"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/pip-vllm on ROCm: the build folder of a release is read from vLLM's own listing (rocm100 for 0.34.0 - the
rocm723 once assumed was not there, and pip took PyPI's CUDA wheel without a word: "Device string must not be
empty" on an MI300X, 2026-11-26), and an index is never made without it. Offline: the tool's helpers.
"""

import os

import pytest

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'tool', 'pip-vllm')


def helpers():
    path = os.path.join(TOOL, 'api_v1.py')
    with open(path, encoding = 'utf-8') as f:
        src = f.read().replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool', 'class InitCTool:\n    pass')
    ns = {'__name__': 'pip_vllm_under_test', '__file__': path}
    exec(compile(src, path, 'exec'), ns)
    return ns


LISTING_0340 = '<html><body><h1>Index</h1><a href="rocm100/">rocm100/</a><br/></body></html>'


def test_the_rocm_builds_of_a_release_listing():
    h = helpers()
    assert h['rocm_builds_in'](LISTING_0340) == ['rocm100']
    assert h['rocm_builds_in']('<a href="rocm723/">rocm723/</a> <a href="rocm100/">rocm100/</a>') == ['rocm100', 'rocm723']
    assert h['rocm_builds_in']('<a href="amd-aiter/">amd-aiter/</a>') == [] and h['rocm_builds_in'](None) == []


def test_the_rocm_index_takes_the_build_it_is_given():
    vllm_indexes = helpers()['vllm_indexes']
    indexes, note = vllm_indexes('0.34.0', ['rocm'], 'linux', None, 'rocm100')
    assert indexes == ['https://wheels.vllm.ai/rocm/0.34.0/rocm100'] and 'rocm100' in note
    with pytest.raises(ValueError):
        vllm_indexes('0.34.0', ['rocm'], 'linux')           # never a folder assumed
    with pytest.raises(ValueError):
        vllm_indexes('0.34.0', ['rocm'], 'windows', None, 'rocm100')

    # the other targets are as they were
    assert vllm_indexes('0.34.0', ['cpu'], 'linux')[0][0] == 'https://wheels.vllm.ai/0.34.0/cpu'
    assert vllm_indexes('0.34.0', ['xpu'], 'linux')[0][0] == 'https://wheels.vllm.ai/0.34.0/xpu'
