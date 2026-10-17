"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

An instance made by get-host--docker or get-host--wsl is found again by its name. Template keys other than the OS
version (another FROM, a CUDA version or flavour, a cmeta-aops checkout) make another image, so the name carries a
short hash of them: before 2026-10-17 `--on_template.cuda_version=12.9.1` and a later `13.3.1` shared one instance,
and the second run silently used the first one's CUDA. Without such keys the names are those of before. And an app
template's compute overlay adds to its base's (llama-cpp's cuda sets the devel flavour; the base's keeps the GPU run
flags): before, it replaced it, and the CUDA stack's instance started without its GPU.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def module(task):
    path = REPO_ROOT / 'task' / task / 'api_v1.py'
    src = path.read_text(encoding='utf-8').replace(
        'from task_c36be4b9314a45e0.api.ctask import InitCTask, changed_mounts, write_signatures',
        'class InitCTask: pass\nchanged_mounts = write_signatures = None')
    ns = {'__name__': f'{task}_under_test', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


@pytest.mark.parametrize('task', ['get-host--docker', 'get-host--wsl'])
def test_the_suffix_of_the_other_template_keys(task):
    suffix = module(task)['template_keys_suffix']

    # the names of before: no keys, or the OS version alone (already in the name)
    assert suffix({}) == '' and suffix({'os_version': '13'}) == ''

    a = suffix({'cuda_version': '12.9.1'})
    b = suffix({'cuda_version': '13.3.1'})
    assert a.startswith('-t') and len(a) == 8 and a != b
    assert suffix({'os_version': '24.04', 'cuda_version': '12.9.1'}) == a           # the OS version is not part of it

    # the order of the keys does not matter
    assert suffix({'from': 'opensuse/tumbleweed', 'cuda_flavour': 'devel'}) == suffix({'cuda_flavour': 'devel', 'from': 'opensuse/tumbleweed'})


def test_docker_and_wsl_name_the_same_keys_alike():
    keys = {'cuda_flavour': 'devel', 'aops_checkout': 'dev'}
    assert module('get-host--docker')['template_keys_suffix'](keys) == module('get-host--wsl')['template_keys_suffix'](keys)


@pytest.mark.parametrize('task', ['get-host--docker', 'get-host--wsl'])
def test_an_app_overlay_adds_to_its_base(task):
    merge = module(task)['merge_overlays']
    base = {'cuda': {'from': 'nvidia/cuda:{{cmeta.cuda_version}}', 'template': {'cuda_version': '13.3.1', 'cuda_flavour': 'base'},
                     'run_flags': {'docker': ['--gpus', 'all']}}}
    app = {'cuda': {'template': {'cuda_flavour': 'devel'}}}

    o = merge(base, app)
    assert o['cuda']['run_flags'] == {'docker': ['--gpus', 'all']}                  # kept: the GPU reaches the instance
    assert o['cuda']['template'] == {'cuda_version': '13.3.1', 'cuda_flavour': 'devel'}
    assert o['cuda']['from'] == 'nvidia/cuda:{{cmeta.cuda_version}}'
    assert base['cuda']['template']['cuda_flavour'] == 'base'                       # the base's description is not changed

    assert merge(base) == base
    assert merge(None, app) == {'cuda': {'template': {'cuda_flavour': 'devel'}}}
    assert set(merge(base, {'rocm': {'from': 'x'}})) == {'cuda', 'rocm'}
