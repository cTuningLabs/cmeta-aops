"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import shutil
import sys

from program_22788f3c30d04e6d.api.cprogram import InitCProgram

class CProgram(InitCProgram):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize1(self,
                   ctx: dict,
                   desc: dict = {},
                   **params,
    ):

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        compute = _global['target']['compute']

        if 'cuda' in compute:
            _local['lang'] = 'cuda'

        return {'return': 0}

    ############################################################
    def customize_pytorch(self,
                          ctx: dict,
                          desc: dict = {},
                          **misc,
    ):
        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']
        _run_control = ctx['tasks']['run_control']

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        clean = _run_control.get('clean', False)

        # pip install always writes cmake intermediates to {git_src}/build/ and ignores BUILD_DIR.
        # Delete that directory when --clean is requested so the next build starts from scratch.
        if clean:
            git_repo = _global.get('clone-git-to-cache-src-pytorch', {}).get('path_to_git_repo', '')
            if git_repo:
                cmake_build = os.path.join(git_repo, 'build')
                if os.path.isdir(cmake_build):
                    if con and verbose:
                        print ('')
                        print (f'{space}INFO: rmtree {cmake_build}')

                    r = self.cm.utils.files.remove_files_and_dirs_in_path(cmake_build)
                    if self.cm.catch_error(r): return r

        compute = _global['target']['compute']
        uname = _global['host']['os']['uname']

        params = misc.get('params', {})
        _compile = params.get('compile')
        if not _compile:
            _compile = {}

        debug_info = _compile.get('debug_info', False)
        strict_compute = _compile.get('strict_compute')

        # compile.d: originally cmake -D flags; we translate ON/OFF → 1/0 for setup.py env vars
        d = _compile.get('d') or {}

        # -----------------------------------------------------------------------
        # Venv site-packages: where pip will install torch
        python_path = _global['python']['path']
        python_root = _global['python']['path_home']

        if uname == 'windows':
            venv_site = os.path.join(python_root, 'Lib', 'site-packages')
        else:
            py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
            venv_site = os.path.join(python_root, 'lib', py_ver, 'site-packages')

        # -----------------------------------------------------------------------
        # Build env vars consumed by PyTorch's setup.py / cmake step.
        # compile.d ON/OFF values are translated to 1/0 (setup.py uses check_env_flag).
        env = {}

        def _to_01(v):
            return '1' if v else '0'

        for k, v in d.items():
            v_str = str(v)
            upper = v_str.upper()
            if upper in ('ON', 'OFF', 'TRUE', 'FALSE', 'YES', 'NO'):
                env[k] = '1' if upper in ('ON', 'TRUE', 'YES') else '0'
            else:
                env[k] = v_str

        # Compute backends (override whatever came from d)
        env['USE_CPU']  = _to_01('cpu'  in compute)
        env['USE_CUDA']  = _to_01('cuda'  in compute)
        env['USE_ROCM']  = _to_01('rocm'  in compute)
        env['USE_MPS']   = _to_01('metal' in compute)
        env['USE_XPU']   = _to_01('xpu'   in compute)


        # Minimalistic build for tests (can be extended later)!
        use_cudnn = params.get('use_cudnn')
        if 'cuda' in compute and use_cudnn:
            env.setdefault('USE_CUDNN', '1')
        elif strict_compute:
            env.setdefault('USE_CUDNN', '0')

        # Build type / misc
        env.setdefault('DEBUG', '1' if debug_info else '0')
        env.setdefault('CMAKE_BUILD_TYPE', 'Debug' if debug_info else 'Release')
        env.setdefault('BUILD_TEST', '1')
        max_jobs = params.get('max_jobs')
        if max_jobs:
            env.setdefault('MAX_JOBS', str(max_jobs))
        env.setdefault('PYTHONUNBUFFERED', '1')

        # Ninja: setup.py reads CMAKE_GENERATOR to pick the cmake generator
        env.setdefault('CMAKE_GENERATOR', 'Ninja')
        ninja_path = _global['ninja']['path']
        env.setdefault('CMAKE_MAKE_PROGRAM', ninja_path)

        # cmake and ninja live in cMeta tool cache dirs, not on system PATH.
        # PyTorch's setup.py searches PATH for "cmake" by name, so we must
        # prepend those dirs explicitly.
        cmake_path = _global['cmake']['path'] #.get('path') or _global['cmake']['qpath'].strip('"').strip("'")

        extra_dirs = [os.path.dirname(p) for p in (cmake_path, ninja_path) if p]
        extra_dirs = list(dict.fromkeys(p for p in extra_dirs if p))  # dedupe, preserve order

        existing_path = env.setdefault('+PATH', [])
        env['+PATH'] = extra_dirs + existing_path



        # C/C++ compilers.
        # cmake reads CC/CXX from env during initial configuration (before cache).
        # CMAKE_C/CXX_COMPILER are also set for older PyTorch versions that forward them as -D flags.

        # HOST SHOULD ALWAYS BE CL on Windows, gcc/clang on Linux and clang on MacOS
        if uname == 'windows':
            if 'xpu' in compute:
                # FGG: I had problems installing KINETO on Windows
                if 'USE_KINETO' not in env: 
                    env['USE_KINETO'] = 'OFF' # various issues
                if 'TORCH_XPU_ARCH_LIST' not in env: 
                    env['TORCH_XPU_ARCH_LIST'] = 'bmg' # reducing compilation time for a test
#                if 'USE_SYSTEM_XNNPACK' not in env:
#                    env['USE_SYSTEM_XNNPACK'] = 'OFF'
#                if 'USE_XNNPACK' not in env:
#                    env['USE_XNNPACK'] = 'OFF'
#                if 'USE_MKLDNN' not in env:
#                    env['USE_MKLDNN'] = 'OFF' # various issues

#                cflags = env.setdefault('CFLAGS', '')
#                cflags += ' -DSLEEF_ENABLE_FLOAT128=OFF -DENABLEFLOAT128=OFF'
#                cflags = cflags.strip()
#                env['CFLAGS'] = cflags

            if params.get('use_mkl'):
                env.setdefault('USE_MKL', '1')
            else:
                env.setdefault('USE_MKL', '0')

            if 'USE_XNNPACK' not in env:
                env['USE_XNNPACK'] = 'OFF' # various issues - though may need for XPU ???
            if 'USE_MKLDNN' not in env:
                env['USE_MKLDNN'] = 'OFF' # various issues - though may need for XPU !!!
            if 'USE_KINETO' not in env: 
                env['USE_KINETO'] = 'OFF' # various issues

            msvc_compiler_path = _global['msvc']['path']

            env.setdefault('CC', msvc_compiler_path)
            env.setdefault('CXX', msvc_compiler_path)
            env.setdefault('CMAKE_C_COMPILER', msvc_compiler_path)
            env.setdefault('CMAKE_CXX_COMPILER', msvc_compiler_path)
            env.setdefault('CL', '/D_CRT_SECURE_NO_WARNINGS')

            if 'compiler-cpp' in _global:
                if _global['compiler-cpp'].get('features', {}).get('id') == 'Intel':
                    cxx_path = _global['compiler-cpp']['path']
#                    cxx_path = os.path.join(_global['compiler-cpp']['path_bin'], 'icx-cl.exe')
                    env.setdefault('CMAKE_CXX_SYCL_COMPILER', cxx_path)
        else:
            # To be improved!
            if 'compiler-c' in _global:
                cc_path = _global['compiler-c']['path']
                env.setdefault('CC', cc_path)
                env.setdefault('CMAKE_C_COMPILER', cc_path)
            if 'compiler-cpp' in _global:
                cxx_path = _global['compiler-cpp']['path']
                if uname == 'windows' and _global['compiler-cpp'].get('features', {}).get('id') == 'Intel':
                    cxx_path = env.get('CC', cxx_path)
                env.setdefault('CXX', cxx_path)
                env.setdefault('CMAKE_CXX_COMPILER', cxx_path)


        # MKL: pip-installed mkl-devel puts headers/libs inside site-packages/mkl/
        if uname in ('windows', 'linux') and any(c in compute for c in ('cpu', 'xpu')) and params.get('use_mkl'):
            _mkl_dir = os.path.join(venv_site, 'mkl')
            if os.path.isdir(_mkl_dir):
                env.setdefault('INTEL_MKL_DIR', _mkl_dir)
                env.setdefault('INTEL_OMP_DIR', _mkl_dir)
            env.setdefault('CMAKE_PREFIX_PATH', venv_site)

        # CUDA compiler path
        if 'cuda' in compute and 'nvcc' in _global:
            nvcc_path = _global['nvcc']['path'] #.get('path') or _global['nvcc']['qpath'].strip('"').strip("'")
            cuda_home = os.path.dirname(os.path.dirname(nvcc_path))

            env.setdefault('CUDA_HOME', cuda_home)
            env.setdefault('CUDA_PATH', cuda_home)

            if use_cudnn:
                cudnn_paths = _global['lib-cudnn']['features']['paths']

                cudnn_home = cudnn_paths['home']

                cudnn_include = cudnn_paths['include']
                cudnn_static_lib = cudnn_paths['lib']
                cudnn_dynamic_lib = cudnn_paths['dynamic_lib']

                env.setdefault('CUDNN_INCLUDE_DIR', cudnn_include)
                env.setdefault('CUDNN_LIBRARY', cudnn_static_lib)

        # OpenMP (Clang-provided, Linux / macOS)
        if 'lib-openmp' in _global:
            omp_path = _global['lib-openmp']['path'] #.get('path') or _global['lib-openmp']['qpath'].strip('"').strip("'")
            env.setdefault('OpenMP_omp_LIBRARY', omp_path)

        # XPU: Kineto enables XPUPTI (GPU profiling) which requires Intel PTI SDK.
        # PTI is a separate optional oneAPI component and may not be installed.
        # Search for its cmake config under the oneAPI root; if absent, disable
        # xpupti via LIBKINETO_NOXPUPTI so the build succeeds without profiling.

        _local['pip_install_env'] = env

        # -----------------------------------------------------------------------
        # Check file: torch/__init__.py in venv after pip install
        _local['target_path_exe'] = os.path.join(venv_site, 'torch', '__init__.py')
        _local['target_path_lib'] = venv_site

        # PYTHONPATH: venv site-packages (pip installs there; also already in sys.path)
        _local.setdefault('run_time_env', {})['PYTHONPATH'] = venv_site

        _local['skip_template_compile'] = True

        return {'return': 0}
