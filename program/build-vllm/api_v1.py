"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re

from program_22788f3c30d04e6d.api.cprogram import InitCProgram
from program_22788f3c30d04e6d.api.common_build import default_max_jobs

TORCH_INDEX = 'https://download.pytorch.org/whl'

# AMD's Python distribution of ROCm, stable channel (tool/rocm): the development files of a ROCm (hipcc, headers)
ROCM_INDEX = 'https://stable.repo.amd.com/rocm/whl-next/'


def release_of_checkout(checkout):
    """The vLLM release of a checkout: v0.34.0 -> 0.34.0 (v0.10.1.post1 too); a branch or a commit -> None."""
    m = re.match(r'v(\d+\.\d+\.\d+(?:\.post\d+)?)$', str(checkout or '').strip())
    return m.group(1) if m else None


def package_name(line):
    """The package a requirement line names, normalised (Jinja2>=3 -> jinja2, setuptools_scm -> setuptools-scm); None for
    a comment, an empty line or an option."""
    s = line.split('#', 1)[0].strip()
    if not s or s.startswith('-'):
        return None
    m = re.match(r'([A-Za-z0-9][A-Za-z0-9._-]*)', s)
    return re.sub(r'[-_.]+', '-', m.group(1)).lower() if m else None


def requirements_over_wheel(lines, installed, base_dir):
    """
    vLLM's requirements/build/rock.txt for a build on top of vLLM's own ROCm wheel: its index lines and every package
    already installed left out - the wheel's torch, triton, amdsmi ... stay, as the wheel was built with them - and a
    -r include made absolute (the file is written beside the build). installed: the normalised names in the venv.
    """
    out = []
    for line in lines:
        s = line.strip()
        if s.startswith('-r '):
            out.append('-r ' + os.path.normpath(os.path.join(base_dir, s[3:].strip())))
        elif s.startswith('--'):
            continue
        else:
            name = package_name(s)
            if name and name not in installed:
                out.append(s)
    return out


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

        requirements = None
        if device == 'rocm':
            # ROCm: the build starts from vLLM's own ROCm wheel of the same release - its torch, triton and aiter for
            # one ROCm (tool pip-vllm, then customize_vllm_rocm): a release, not a branch
            release = release_of_checkout(params.get('checkout'))
            if not release:
                return self.cm.error(f"the ROCm build starts from vLLM's own ROCm wheel of the same release: "
                                     f'--checkout=v<release> (v0.34.0), not "{params.get("checkout")}"')
            _local['vllm_release'] = release
        else:
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
            elif device == 'rocm':
                # the AMD GPUs to compile for: --gpu_targets, else this machine's (tool rocm: gfx942 of an MI300X)
                gfx = str(params.get('gpu_targets') or '').strip() or ';'.join(_global.get('rocm', {}).get('features', {}).get('gfx', []))
                if not gfx:
                    return self.cm.error('no AMD GPU found to build for (tool rocm): --gpu_targets=<gfx942;...> names them')
                env['PYTORCH_ROCM_ARCH'] = gfx

        # Host compilers for CMake
        for key, glob_key in (('CC', 'compiler-c'), ('CXX', 'compiler-cpp')):
            path = _global.get(glob_key, {}).get('path')
            if path:
                env[key] = path

        for k, v in (params.get('compile', {}) or {}).get('env', {}).items():
            env[k] = str(v)

        if con:
            print ('')
            print (f'INFO: vLLM source build: {device}, {requirements or "on top of vLLM" + chr(39) + "s own ROCm wheel"}')
            for k in sorted(env):
                print (f'  {k}={env[k]}')

        _local['vllm_build_env'] = env
        if requirements:
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


    ############################################################
    def customize_vllm_rocm(self,
                            ctx: dict,
                            desc: dict = {},
                            **misc,
    ):
        """
        ROCm, after tool pip-vllm put vLLM's own ROCm wheel of the release into the venv (its torch, triton and aiter
        for one ROCm): the development files of that same ROCm join it - AMD's "rocm[libraries,devel]" of the version
        the wheel brought (hipcc, the headers) - and the build takes them (ROCM_HOME and ROCM_PATH: "rocm-sdk path
        --root", its bin on PATH). The build requirements: vLLM's own requirements/build/rock.txt without what the venv
        has (the wheel's torch stack stays). The source build then replaces the wheel's vLLM.
        """

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']
        con = ctx['control'].get('con', False)

        python = _global['python']['path']
        qpython = self.cm.q(python)
        run = lambda cmd, capture = True: self.cm.utils.sys.run(cmd, capture_output = capture, fail_on_error = False, logger = self.logger)

        r = run(f'{qpython} -c "import importlib.metadata as m; print(m.version(\'rocm\'))"')
        version = (r.get('stdout') or '').strip() if r.get('returncode') == 0 else ''
        if not re.match(r'\d+\.\d+', version):
            return self.cm.error(f'vLLM\'s ROCm wheel brought no "rocm" package into {python}: the ROCm of its torch is not known')

        if con:
            print('')
            print(f'INFO: the development files of ROCm {version} (the ROCm of vLLM\'s wheel), from {ROCM_INDEX}')
        r = run(f'{qpython} -m pip install --extra-index-url {ROCM_INDEX} "rocm[libraries,devel]=={version}"', capture = False)
        if r.get('returncode') != 0:
            return self.cm.error(f'"rocm[libraries,devel]=={version}" did not install from {ROCM_INDEX}')

        sdk = os.path.join(os.path.dirname(python), 'rocm-sdk')
        r = run(f'{self.cm.q(sdk)} path --root')
        root = ((r.get('stdout') or '').strip().splitlines() or [''])[0].strip() if r.get('returncode') == 0 else ''
        if not root or not os.path.isfile(os.path.join(root, 'bin', 'hipcc')):
            return self.cm.error(f'"{sdk} path --root" names no ROCm with hipcc ({root or "nothing"})')

        env = _local['vllm_build_env']
        env['ROCM_HOME'] = env['ROCM_PATH'] = root
        env['+PATH'] = list(env.get('+PATH') or []) + [os.path.join(root, 'bin')]

        # vLLM's build requirements of AMD's distribution, without what the venv has
        src = _global['clone-git-to-cache-src-vllm']['path_to_git_repo']
        rock = os.path.join(src, 'requirements', 'build', 'rock.txt')
        if not os.path.isfile(rock):
            return self.cm.error(f'no requirements/build/rock.txt in {src}: this release has no build of AMD\'s distribution')
        r = run(f'{qpython} -m pip list --format=json')
        try:
            import json
            installed = {re.sub(r'[-_.]+', '-', p['name']).lower() for p in json.loads(r.get('stdout') or '[]')}
        except ValueError:
            return self.cm.error(f'"pip list" of {python} did not answer')
        with open(rock, encoding = 'utf-8') as f:
            lines = requirements_over_wheel(f.read().splitlines(), installed, os.path.dirname(rock))
        path = os.path.join(_local['target_path'], 'tmp-cmeta-vllm-build-requirements-rocm.txt')
        with open(path, 'w', encoding = 'utf-8') as f:
            f.write('\n'.join(lines) + '\n')

        _local['vllm_build_requirements'] = self.cm.q(path)
        _local['vllm_index_flags'] = ''

        if con:
            print(f'INFO: ROCm {version} for the build: {root}; the build requirements: {path}')
            for k in ('ROCM_HOME', 'PYTORCH_ROCM_ARCH', 'VLLM_TARGET_DEVICE', 'MAX_JOBS'):
                print(f'  {k}={env.get(k, "")}')

        return {'return': 0}
