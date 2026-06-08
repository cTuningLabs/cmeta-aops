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

_SEP = {
    'windows': ';',
    'linux':   ':',
    'darwin':  ':',
}

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
        """
        Assembles CMake -D flags and local paths for a PyTorch from-source build.

        Returns:
            dict: {'return': 0} on success, {'return': >0, 'error': str} on failure.
        """

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        compute = _global['target']['compute']
        uname = _global['host']['os']['uname']

        sub_params = params.get('sub_params', {})
        _compile = sub_params.get('compile')
        if not _compile:
            _compile = {}

        debug_info = _compile.get('debug_info')
        static = _compile.get('static')
        strict_compute = _compile.get('strict_compute')

        d = _compile.get('d')
        if not d:
            d = {}

        # -----------------------------------------------------------------------
        # Build type
        build_type = 'Debug' if debug_info else 'Release'
        _local['build_type'] = build_type
        if 'CMAKE_BUILD_TYPE' not in d:
            d['CMAKE_BUILD_TYPE'] = build_type

        # -----------------------------------------------------------------------
        # Ninja
        if 'CMAKE_MAKE_PROGRAM' not in d:
            d['CMAKE_MAKE_PROGRAM'] = _global['ninja']['qpath']

        # -----------------------------------------------------------------------
        # C / C++ compilers
        if 'cpu' in compute or 'cuda' in compute or 'xpu' in compute:
            cmake_c_compiler = _global['compiler-c']['qpath']
            if 'CMAKE_C_COMPILER' not in d:
                d['CMAKE_C_COMPILER'] = cmake_c_compiler
            if 'CMAKE_CXX_COMPILER' not in d:
                if uname == 'windows' and _global['compiler-cpp']['features'].get('id') == 'Intel':
                    # Known Intel compiler issue on Windows: use C compiler for C++ too
                    d['CMAKE_CXX_COMPILER'] = cmake_c_compiler
                else:
                    d['CMAKE_CXX_COMPILER'] = _global['compiler-cpp']['qpath']

        # -----------------------------------------------------------------------
        # Python — PyTorch 2.x uses find_package(Python/Python3) which requires
        # Python_EXECUTABLE / Python3_EXECUTABLE (new-style cmake variables).
        # The legacy PYTHON_EXECUTABLE is silently ignored (confirmed by cmake warning).
        # Python_ROOT_DIR pins the search root to the venv, preventing cmake from
        # picking up the system Python via PATH.
        python_qpath = _global['python']['qpath']
        python_path = _global['python'].get('path') or python_qpath.strip('"').strip("'")
        # <venv>/ from <venv>/Scripts/python.exe (Windows) or <venv>/bin/python (Linux/macOS)
        python_root = os.path.dirname(os.path.dirname(python_path))

        if 'Python_ROOT_DIR' not in d:
            d['Python_ROOT_DIR'] = self.cm.q(python_root)
        if 'Python3_ROOT_DIR' not in d:
            d['Python3_ROOT_DIR'] = self.cm.q(python_root)
        if 'Python_EXECUTABLE' not in d:
            d['Python_EXECUTABLE'] = python_qpath
        if 'Python3_EXECUTABLE' not in d:
            d['Python3_EXECUTABLE'] = python_qpath
        # Prefer the active virtualenv / venv over any system Python found in PATH
        d.setdefault('Python_FIND_VIRTUALENV', 'FIRST')
        d.setdefault('Python3_FIND_VIRTUALENV', 'FIRST')

        # -----------------------------------------------------------------------
        # MKL — pip-installed mkl-devel puts headers/libs inside site-packages.
        # PyTorch's CMake finds them when CMAKE_PREFIX_PATH includes site-packages.
        # INTEL_MKL_DIR / INTEL_OMP_DIR are set if a mkl/ subdirectory exists
        # (pip package layout), matching the conda Library/ convention the user
        # previously used for INTEL_MKL_DIR / INTEL_OMP_DIR.
        # MKL is available on Windows and Linux x86_64 only (not macOS ARM).
        if uname in ('windows', 'linux') and any(c in compute for c in ('cpu', 'xpu')):
            if uname == 'windows':
                _venv_site = os.path.join(python_root, 'Lib', 'site-packages')
            else:
                _py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
                _venv_site = os.path.join(python_root, 'lib', _py_ver, 'site-packages')
            if 'CMAKE_PREFIX_PATH' not in d:
                d['CMAKE_PREFIX_PATH'] = self.cm.q(_venv_site)
            _mkl_dir = os.path.join(_venv_site, 'mkl')
            if os.path.isdir(_mkl_dir):
                d.setdefault('INTEL_MKL_DIR', self.cm.q(_mkl_dir))
                d.setdefault('INTEL_OMP_DIR', self.cm.q(_mkl_dir))

        # -----------------------------------------------------------------------
        # Install prefix: libtorch + Python bindings land under target_path
        target_path = _local['target_path']
        if 'CMAKE_INSTALL_PREFIX' not in d:
            d['CMAKE_INSTALL_PREFIX'] = self.cm.q(target_path)

        # -----------------------------------------------------------------------
        # Shared vs static
        x = 'OFF' if static else 'ON'
        if 'BUILD_SHARED_LIBS' not in d:
            d['BUILD_SHARED_LIBS'] = x

        # -----------------------------------------------------------------------
        # CUDA
        if 'cuda' in compute:
            if 'CMAKE_CUDA_COMPILER' not in d:
                d['CMAKE_CUDA_COMPILER'] = _global['nvcc']['qpath']
            if 'USE_CUDA' not in d:
                d['USE_CUDA'] = 'ON'
            if 'USE_CUDNN' not in d:
                d['USE_CUDNN'] = 'ON'
        elif strict_compute:
            d.setdefault('USE_CUDA', 'OFF')
            d.setdefault('USE_CUDNN', 'OFF')

        # -----------------------------------------------------------------------
        # ROCm
        if 'rocm' in compute:
            d.setdefault('USE_ROCM', 'ON')
        elif strict_compute:
            d.setdefault('USE_ROCM', 'OFF')

        # -----------------------------------------------------------------------
        # Metal / MPS (Apple Silicon)
        if 'metal' in compute:
            d.setdefault('USE_MPS', 'ON')
        elif strict_compute:
            d.setdefault('USE_MPS', 'OFF')

        # -----------------------------------------------------------------------
        # XPU (Intel GPU)
        if 'xpu' in compute:
            d.setdefault('USE_XPU', 'ON')
        elif strict_compute:
            d.setdefault('USE_XPU', 'OFF')

        # -----------------------------------------------------------------------
        # OpenMP (Clang-provided, Linux / macOS)
        if 'lib-openmp' in _global and 'OpenMP_omp_LIBRARY' not in d:
            d['OpenMP_omp_LIBRARY'] = _global['lib-openmp']['qpath']
            d['OpenMP_C_LIB_NAMES'] = 'omp'
            d['OpenMP_CXX_LIB_NAMES'] = 'omp'

        # -----------------------------------------------------------------------
        # Check file: main shared library produced by cmake --install
        if uname == 'linux':
            libtorch_name = 'libtorch.so'
        elif uname == 'darwin':
            libtorch_name = 'libtorch.dylib'
        else:
            libtorch_name = 'torch.dll'

        target_path_lib = os.path.join(target_path, 'lib')
        target_path_libtorch = os.path.join(target_path_lib, libtorch_name)

        _local['target_path_lib'] = target_path_lib
        _local['target_path_exe'] = target_path_libtorch

        # -----------------------------------------------------------------------
        # PYTHONPATH so downstream Python programs can `import torch` after
        # cmake --install.  PyTorch installs the Python package to:
        #   Windows : {prefix}/Lib/site-packages/torch
        #   Linux   : {prefix}/lib/pythonX.Y/site-packages/torch
        #   macOS   : {prefix}/lib/pythonX.Y/site-packages/torch
        if uname == 'windows':
            torch_site_packages = os.path.join(target_path, 'Lib', 'site-packages')
        else:
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            torch_site_packages = os.path.join(target_path, 'lib', f'python{python_version}', 'site-packages')
        _local.setdefault('run_time_env', {})['PYTHONPATH'] = torch_site_packages

        # -----------------------------------------------------------------------
        _local['cmake_d_vars'] = " ".join(
            f"-D{k}={self.cm.q(str(v))}" for k, v in d.items()
        )
        _local['skip_template_compile'] = True

        return {'return': 0}

    ############################################################
    def customize_test(self,
                       ctx: dict,
                       desc: dict = {},
                       **params,
    ):
        """
        Called during the run phase to compile and run a small C++ sanity-check
        that exercises the LibTorch C++ API against the cmake-installed libtorch.
        """
        _local  = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']

        # target_path is the cmake --install prefix set during the compile phase
        target_path = _local['target_path']

        # -----------------------------------------------------------------------
        # Test build directory (inside the install tree, ignored by libtorch cmake)
        test_build_path = os.path.join(target_path, 'test-build')
        os.makedirs(test_build_path, exist_ok=True)
        _local['test_build_path'] = test_build_path

        # -----------------------------------------------------------------------
        # Source directory (src/CMakeLists.txt + src/program.cpp)
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
        _local['test_cmake_src_path'] = self.cm.q(src_dir)

        # -----------------------------------------------------------------------
        # cmake -D flags for the test binary
        d = {}
        d['CMAKE_BUILD_TYPE'] = 'Release'

        ninja_path = _global['ninja'].get('path') or _global['ninja']['qpath'].strip('"').strip("'")
        d['CMAKE_MAKE_PROGRAM'] = ninja_path

        if 'compiler-c' in _global:
            cc = _global['compiler-c'].get('path') or _global['compiler-c']['qpath'].strip('"').strip("'")
            d['CMAKE_C_COMPILER'] = cc
        if 'compiler-cpp' in _global:
            cxx = _global['compiler-cpp'].get('path') or _global['compiler-cpp']['qpath'].strip('"').strip("'")
            if uname == 'windows' and _global['compiler-cpp'].get('features', {}).get('id') == 'Intel':
                cxx = d.get('CMAKE_C_COMPILER', cxx)
            d['CMAKE_CXX_COMPILER'] = cxx

        # CMAKE_PREFIX_PATH tells find_package(Torch) where TorchConfig.cmake lives
        d['CMAKE_PREFIX_PATH'] = target_path

        _local['test_cmake_d_vars'] = ' '.join(
            f'-D{k}={self.cm.q(str(v))}' for k, v in d.items()
        )

        # -----------------------------------------------------------------------
        # Test binary produced by Ninja directly in test_build_path
        exe_name = 'program.exe' if uname == 'windows' else 'program'
        _local['target_path_exe'] = os.path.join(test_build_path, exe_name)

        # -----------------------------------------------------------------------
        # Add libtorch lib dir to PATH / LD_LIBRARY_PATH / DYLD_LIBRARY_PATH
        # so the test binary can load shared libraries at runtime.
        lib_dir = os.path.join(target_path, 'lib')
        sep = _SEP.get(uname, ':')
        rte = _local.setdefault('run_time_env', {})

        existing_path = os.environ.get('PATH', '')
        rte['PATH'] = f"{lib_dir}{sep}{existing_path}" if existing_path else lib_dir

        if uname == 'linux':
            existing = os.environ.get('LD_LIBRARY_PATH', '')
            rte['LD_LIBRARY_PATH'] = f"{lib_dir}{sep}{existing}" if existing else lib_dir
        elif uname == 'darwin':
            existing = os.environ.get('DYLD_LIBRARY_PATH', '')
            rte['DYLD_LIBRARY_PATH'] = f"{lib_dir}{sep}{existing}" if existing else lib_dir

        return {'return': 0}
