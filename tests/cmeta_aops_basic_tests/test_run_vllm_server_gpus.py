"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-vllm-server on a GPU of either kind: the image of a start (vLLM's NVIDIA image becomes the same release of its
ROCm image on an AMD GPU; an image the command line names stays) and how docker passes each kind of GPU in - data in
the task's _desc.yaml. Offline: the task's helpers, without the engine or docker.
"""

import os

import yaml

TASK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'task', 'run-vllm-server')


def helpers():
    path = os.path.join(TASK, 'api_v1.py')
    with open(path, encoding = 'utf-8') as f:
        src = f.read().replace('from task_c36be4b9314a45e0.api.ctask import InitCTask', 'class InitCTask:\n    pass')
    ns = {'__name__': 'run_vllm_server_under_test', '__file__': path}
    exec(compile(src, path, 'exec'), ns)
    return ns


def gpus():
    with open(os.path.join(TASK, '_desc.yaml'), encoding = 'utf-8') as f:
        return yaml.safe_load(f)['gpus']


def test_the_image_of_a_start_on_each_kind_of_gpu():
    image_for_gpu, kinds = helpers()['image_for_gpu'], gpus()
    nvidia = kinds['nvidia']['image_repository']
    default = helpers()['BUILT_IN']['image']

    assert default.startswith(nvidia + ':')
    assert image_for_gpu(default, False, kinds['nvidia'], nvidia) == default
    assert image_for_gpu('vllm/vllm-openai:v0.34.0', False, kinds['amd'], nvidia) == 'vllm/vllm-openai-rocm:v0.34.0'

    # an image the command line names stays, and so does a default image of another repository
    assert image_for_gpu('vllm/vllm-openai:v0.34.0', True, kinds['amd'], nvidia) == 'vllm/vllm-openai:v0.34.0'
    assert image_for_gpu('rocm/vllm:latest', False, kinds['amd'], nvidia) == 'rocm/vllm:latest'
    assert image_for_gpu('vllm/vllm-openai', False, kinds['amd'], nvidia) == 'vllm/vllm-openai'


def test_how_docker_passes_each_kind_of_gpu_in():
    kinds = gpus()
    assert set(kinds) == {'nvidia', 'amd'}
    assert kinds['nvidia']['run_flags'][:2] == ['--gpus', 'all']
    amd = kinds['amd']['run_flags']
    assert '/dev/kfd' in amd and '/dev/dri' in amd and 'video' in amd and '--gpus' not in amd
    assert all('--ipc=host' in kinds[k]['run_flags'] for k in kinds)
