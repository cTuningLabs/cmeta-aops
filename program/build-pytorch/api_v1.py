"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
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
                          **params,
    ):
        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        compute = _global['target']['compute']
        uname = _global['host']['os']['uname']

        sub_params = params.get('sub_params', {})
        _compile = sub_params.get('compile') or {}

        debug_info = _compile.get('debug_info', False)
        strict_compute = _compile.get('strict_compute')

        # compile.d: originally cmake -D flags; we translate ON/OFF → 1/0 for setup.py env vars
        d = _compile.get('d') or {}

        # -----------------------------------------------------------------------
        # Venv site-packages: where pip will install torch
        python_qpath = _global['python']['qpath']
        python_path = _global['python'].get('path') or python_qpath.strip('"').strip("'")
        python_root = os.path.dirname(os.path.dirname(python_path))

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
            return '1' if str(v).upper() in ('ON', '1', 'TRUE', 'YES') else '0'

        for k, v in d.items():
            v_str = str(v)
            upper = v_str.upper()
            if upper in ('ON', 'OFF', 'TRUE', 'FALSE', 'YES', 'NO'):
                env[k] = '1' if upper in ('ON', 'TRUE', 'YES') else '0'
            else:
                env[k] = v_str

        # Compute backends (override whatever came from d)
        env['USE_CUDA']  = _to_01('cuda'  in compute)
        env['USE_ROCM']  = _to_01('rocm'  in compute)
        env['USE_MPS']   = _to_01('metal' in compute)
        env['USE_XPU']   = _to_01('xpu'   in compute)
        if 'cuda' in compute:
            env.setdefault('USE_CUDNN', '1')
        elif strict_compute:
            env.setdefault('USE_CUDNN', '0')

        # Build type / misc
        env.setdefault('DEBUG', '1' if debug_info else '0')
        env.setdefault('CMAKE_BUILD_TYPE', 'Debug' if debug_info else 'Release')
        env.setdefault('BUILD_TEST', '0')
        env.setdefault('MAX_JOBS', str(os.cpu_count() or 8))
        env.setdefault('PYTHONUNBUFFERED', '1')

        # Ninja: setup.py reads CMAKE_GENERATOR to pick the cmake generator
        env.setdefault('CMAKE_GENERATOR', 'Ninja')
        ninja_path = _global['ninja'].get('path') or _global['ninja']['qpath'].strip('"').strip("'")
        env.setdefault('CMAKE_MAKE_PROGRAM', ninja_path)

        # cmake and ninja live in cMeta tool cache dirs, not on system PATH.
        # PyTorch's setup.py searches PATH for "cmake" by name, so we must
        # prepend those dirs explicitly.
        cmake_path = _global['cmake'].get('path') or _global['cmake']['qpath'].strip('"').strip("'")
        extra_dirs = [os.path.dirname(p) for p in (cmake_path, ninja_path) if p]
        extra_dirs = list(dict.fromkeys(d for d in extra_dirs if d))  # dedupe, preserve order
        existing_path = os.environ.get('PATH', '')
        env['PATH'] = os.pathsep.join(extra_dirs + ([existing_path] if existing_path else []))

        # C/C++ compilers — passed to cmake via env vars that setup.py forwards
        if 'compiler-c' in _global:
            cc_path = _global['compiler-c'].get('path') or _global['compiler-c']['qpath'].strip('"').strip("'")
            env.setdefault('CMAKE_C_COMPILER', cc_path)
        if 'compiler-cpp' in _global:
            cxx_path = _global['compiler-cpp'].get('path') or _global['compiler-cpp']['qpath'].strip('"').strip("'")
            if uname == 'windows' and _global['compiler-cpp'].get('features', {}).get('id') == 'Intel':
                env.setdefault('CMAKE_CXX_COMPILER', env.get('CMAKE_C_COMPILER', cxx_path))
            else:
                env.setdefault('CMAKE_CXX_COMPILER', cxx_path)

        # MKL: pip-installed mkl-devel puts headers/libs inside site-packages/mkl/
        if uname in ('windows', 'linux') and any(c in compute for c in ('cpu', 'xpu')):
            _mkl_dir = os.path.join(venv_site, 'mkl')
            if os.path.isdir(_mkl_dir):
                env.setdefault('INTEL_MKL_DIR', _mkl_dir)
                env.setdefault('INTEL_OMP_DIR', _mkl_dir)
            env.setdefault('CMAKE_PREFIX_PATH', venv_site)

        # CUDA compiler path
        if 'cuda' in compute and 'nvcc' in _global:
            nvcc_path = _global['nvcc'].get('path') or _global['nvcc']['qpath'].strip('"').strip("'")
            cuda_home = os.path.dirname(os.path.dirname(nvcc_path))
            env.setdefault('CUDA_HOME', cuda_home)

        # OpenMP (Clang-provided, Linux / macOS)
        if 'lib-openmp' in _global:
            omp_path = _global['lib-openmp'].get('path') or _global['lib-openmp']['qpath'].strip('"').strip("'")
            env.setdefault('OpenMP_omp_LIBRARY', omp_path)

        _local['pip_install_env'] = env

        # -----------------------------------------------------------------------
        # Check file: torch/__init__.py in venv after pip install
        _local['target_path_exe'] = os.path.join(venv_site, 'torch', '__init__.py')
        _local['target_path_lib'] = venv_site

        # PYTHONPATH: venv site-packages (pip installs there; also already in sys.path)
        _local.setdefault('run_time_env', {})['PYTHONPATH'] = venv_site

        _local['skip_template_compile'] = True

        return {'return': 0}
