"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from program_22788f3c30d04e6d.api.cprogram import InitCProgram
from program_22788f3c30d04e6d.api.common_build import default_max_jobs

TORCH_INDEX = 'https://download.pytorch.org/whl'


class CProgram(InitCProgram):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize_vllm(self,
                       ctx: dict,
                       desc: dict = {},
                       **misc,
    ):
        """
        The build environment, requirements file and wheel indexes of a vLLM source build.
        """

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        params = misc.get('params', {})
        compute = _global['target']['compute']
        uname = _global['host']['os']['uname']

        con = ctx['control'].get('con', False)

        if uname == 'windows':
            return self.cm.error('vLLM does not build on Windows: run this program in WSL2 '
                                 '(the same cMeta command) or use the vllm/vllm-openai Docker image')

        device = 'cpu'
        for c in ('cuda', 'rocm', 'xpu'):
            if c in compute:
                device = c
                break

        src = _global['clone-git-to-cache-src-vllm']['path_to_git_repo']

        # The build requirements moved to requirements/build/<device>.txt in v0.20.0
        candidates = [os.path.join(src, 'requirements', 'build', device + '.txt'),
                      os.path.join(src, 'requirements', 'build.txt') if device == 'cuda' else '',
                      os.path.join(src, 'requirements', f'{device}-build.txt'),
                      os.path.join(src, 'requirements-build.txt')]
        requirements = next((c for c in candidates if c and os.path.isfile(c)), None)
        if not requirements:
            return self.cm.error(f'no build requirements for "{device}" in {src}/requirements')

        env = {'VLLM_TARGET_DEVICE': device,
               'CMAKE_BUILD_TYPE': params.get('build_type') or 'Release',
               'PYTHONUNBUFFERED': '1'}

        # The build requirements install cmake and ninja into the venv, and setup.py runs them by
        # name: the venv's bin goes first on PATH (pip itself runs as <venv>/bin/python -m pip)
        path_bin = _global['python'].get('path_bin') or os.path.dirname(_global['python']['path'])
        env['+PATH'] = [path_bin]

        index_flags = ''

        if device == 'cuda':
            nvcc = _global.get('nvcc', {}).get('path')
            if not nvcc:
                return self.cm.error('nvcc was not found: the CUDA build needs the CUDA toolkit')
            cuda_home = os.path.dirname(os.path.dirname(nvcc))
            env['CUDA_HOME'] = cuda_home
            env['+PATH'].append(os.path.join(cuda_home, 'bin'))

            # torch must match the toolkit's CUDA major version: PyPI's torch is the CUDA 13.0
            # build, a CUDA 12 toolkit needs PyTorch's cu129 build (and so vLLM's +cu129 variant)
            nvcc_version = str(_global.get('nvcc', {}).get('version') or '')
            if nvcc_version.startswith('12.'):
                index_flags = f'--extra-index-url {TORCH_INDEX}/cu129'

            arch_list = params.get('cuda_arch_list')
            if not arch_list:
                # The GPUs of this machine (a single architecture shortens the build a lot)
                devices = _global.get('target', {}).get('features', {}).get('cuda', {}).get('devices', [])
                caps = sorted({d.get('compute_cap') for d in devices if d.get('compute_cap')})
                arch_list = ';'.join(caps)
            if arch_list:
                env['TORCH_CUDA_ARCH_LIST'] = arch_list

            nvcc_threads = int(params.get('nvcc_threads') or 1)
            env['NVCC_THREADS'] = str(nvcc_threads)
            env['MAX_JOBS'] = str(params.get('max_jobs') or default_max_jobs(device, nvcc_threads))

        else:
            env['MAX_JOBS'] = str(params.get('max_jobs') or default_max_jobs(device))
            if device == 'cpu' and uname == 'linux':
                # requirements/build/cpu.txt pins torch==<v>+cpu
                index_flags = f'--extra-index-url {TORCH_INDEX}/cpu'
                # A CUDA toolkit on the machine must not turn the CPU build into a CUDA one
                env['CMAKE_ARGS'] = '-DCMAKE_DISABLE_FIND_PACKAGE_CUDA=ON'
            elif device == 'xpu':
                index_flags = f'--extra-index-url {TORCH_INDEX}/xpu'

        # Host compilers for CMake
        for key, glob_key in (('CC', 'compiler-c'), ('CXX', 'compiler-cpp')):
            path = _global.get(glob_key, {}).get('path')
            if path:
                env[key] = path

        for k, v in (params.get('compile', {}) or {}).get('env', {}).items():
            env[k] = str(v)

        if con:
            print ('')
            print (f'INFO: vLLM source build: {device}, {requirements}')
            for k in sorted(env):
                print (f'  {k}={env[k]}')

        _local['vllm_build_env'] = env
        _local['vllm_build_requirements'] = self.cm.q(requirements)
        _local['vllm_index_flags'] = index_flags

        # The installed package (the template checks this file after the build)
        python = _global['python']['path']
        venv = os.path.dirname(os.path.dirname(python))
        pyver = 'python' + '.'.join(str(_global['python'].get('version', '')).split('.')[:2])
        site = os.path.join(venv, 'lib', pyver, 'site-packages')
        _local['target_path_exe'] = os.path.join(site, 'vllm', '__init__.py')
        _local['target_path_lib'] = site

        _local['skip_template_compile'] = True

        return {'return': 0}
