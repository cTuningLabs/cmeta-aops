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
                          **misc,
    ):
        """
        Assembles CMake -D flags and local paths for a PyTorch from-source build.

        Returns:
            dict: {'return': 0} on success, {'return': >0, 'error': str} on failure.
        """

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']
        _run_control = ctx['tasks']['run_control']

        clean = _run_control.get('clean', False)

        compute = _global['target']['compute']
        uname = _global['host']['os']['uname']

        params = misc.get('params', {})
        _compile = params.get('compile')
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
        # Windows + LLVM clang: cmake's Windows platform module can reset
        # CMAKE_SYSTEM_PROCESSOR to "AMD64" (from PROCESSOR_ARCHITECTURE) via a
        # regular variable that shadows the -D cache value we set.  PyTorch's
        # internal QNNPACK cmake only accepts "x86_64"; MSVC builds avoid it because
        # PyTorch's if(MSVC) guard disables USE_PYTORCH_QNNPACK, but that guard does
        # not fire for GNU-frontend Clang.  Both normalization and an explicit OFF are
        # needed as a belt-and-braces fix.
        if uname == 'windows':
            if 'CMAKE_SYSTEM_PROCESSOR' not in d:
                _proc_map = {'AMD64': 'x86_64', 'ARM64': 'aarch64'}
                _proc = os.environ.get('PROCESSOR_ARCHITECTURE', '').upper()
                if _proc in _proc_map:
                    d['CMAKE_SYSTEM_PROCESSOR'] = _proc_map[_proc]
            # Detect Clang (GNU-frontend) by compiler path and disable PYTORCH_QNNPACK.
            _win_cpath = ''
            for _ckey in ('compiler-cpp', 'compiler-c'):
                if _ckey in _global:
                    _win_cpath = (
                        _global[_ckey].get('path') or
                        _global[_ckey]['qpath'].strip('"').strip("'")
                    ).lower()
                    break
            if 'clang' in _win_cpath:
                d.setdefault('USE_PYTORCH_QNNPACK', 'OFF')

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
        # macOS + custom LLVM: LLVM 22+ uses ABI v2 (std:: namespace, no std::__1::).
        # Apple's system libc++.1.dylib only exports ABI v1 (std::__1::) symbols, so
        # we must use LLVM's own runtime.
        #
        # Strategy: if LLVM ships a real shared libc++.dylib (resolves inside the LLVM
        # lib dir rather than pointing at Apple's /usr/lib/libc++.1.dylib), link
        # everything — both shared libs and executables — against it via -lc++/-lc++abi.
        # That gives ONE shared C++ runtime instance with no multiple-copies issue.
        #
        # Fallback: only a static libc++.a is available.  Embed it in executables only
        # and use -undefined dynamic_lookup for shared libs so their ABI v2 symbols
        # resolve from the executable at load time (single runtime provider).
        if uname == 'darwin' and ('compiler-c' in _global or 'compiler-cpp' in _global):
            _cr = _global.get('compiler-cpp') or _global.get('compiler-c')
            _cp = _cr.get('path') or _cr['qpath'].strip('"').strip("'")
            _llvm_lib = os.path.join(os.path.dirname(os.path.dirname(_cp)), 'lib')
            if os.path.isdir(_llvm_lib):
                _libc_pp    = os.path.join(_llvm_lib, 'libc++.a')
                _libc_dylib = os.path.join(_llvm_lib, 'libc++.dylib')
                # Follow all symlinks: if the resolved path is inside _llvm_lib it's
                # LLVM's own ABI v2 shared libc++ (e.g. libc++.dylib -> libc++.1.dylib
                # within the same dir).  If it escapes to /usr/lib/ it's Apple's ABI v1.
                _is_llvm_dylib = (
                    os.path.isfile(_libc_dylib) and
                    os.path.realpath(_libc_dylib).startswith(os.path.realpath(_llvm_lib))
                )
                if _is_llvm_dylib:
                    # LLVM ships a real shared ABI v2 libc++: use it for everything so the
                    # whole process (executable + all dylibs) shares one runtime instance.
                    # -lc++abi is resolved at link time from the same LLVM lib dir (or falls
                    # back to Apple's system libc++abi.dylib); either way the shared version
                    # is used, which has no TMO static-init-order issue.
                    _lf = f'-L{_llvm_lib} -Wl,-rpath,{_llvm_lib} -lc++ -lc++abi'
                    d.setdefault('CMAKE_EXE_LINKER_FLAGS', _lf)
                    d.setdefault('CMAKE_SHARED_LINKER_FLAGS', _lf)
                    d.setdefault('CMAKE_MODULE_LINKER_FLAGS', _lf)
                elif os.path.isfile(_libc_pp):
                    # Only static libc++.a available.  Embed it in the executable (single
                    # runtime provider); shared libs use -undefined dynamic_lookup so their
                    # ABI v2 symbols resolve from the executable at load time.
                    # Omit -L so -lc++abi falls back to Apple's system libc++abi.dylib
                    # (avoids LLVM's static libc++abi.a whose TMO operator new aborts on
                    # protobuf-style static initializers that call operator new early).
                    _exe_lf = f'-Wl,-rpath,{_llvm_lib} {_libc_pp} -lc++abi'
                    d.setdefault('CMAKE_EXE_LINKER_FLAGS', _exe_lf)
                    d.setdefault('CMAKE_SHARED_LINKER_FLAGS', f'-Wl,-rpath,{_llvm_lib} -undefined dynamic_lookup')
                    d.setdefault('CMAKE_MODULE_LINKER_FLAGS', f'-Wl,-rpath,{_llvm_lib} -undefined dynamic_lookup')
                else:
                    _lf = f'-L{_llvm_lib} -Wl,-rpath,{_llvm_lib} -lc++ -lc++abi'
                    d.setdefault('CMAKE_EXE_LINKER_FLAGS', _lf)
                    d.setdefault('CMAKE_SHARED_LINKER_FLAGS', _lf)
                    d.setdefault('CMAKE_MODULE_LINKER_FLAGS', _lf)

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

        uname   = _global['host']['os']['uname']
        compute = _global['target']['compute']

        # target_path is the cmake --install prefix set during the compile phase
        target_path = _local['target_path']

        # -----------------------------------------------------------------------
        # Test build directory (inside the install tree, ignored by libtorch cmake)
        test_build_path = os.path.join(target_path, 'test-build')
        os.makedirs(test_build_path, exist_ok=True)
        _local['test_build_path'] = test_build_path

        # Remove the stale binary so ninja always relinks with the current linker flags.
        # cmake's ninja backend does not re-link when only cached cmake variables change.
        _stale = os.path.join(test_build_path, 'program.exe' if uname == 'windows' else 'program')
        if os.path.isfile(_stale):
            os.remove(_stale)

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

        if uname == 'darwin' and ('compiler-c' in _global or 'compiler-cpp' in _global):
            _cr = _global.get('compiler-cpp') or _global.get('compiler-c')
            _cp = _cr.get('path') or _cr['qpath'].strip('"').strip("'")
            _llvm_lib = os.path.join(os.path.dirname(os.path.dirname(_cp)), 'lib')
            if os.path.isdir(_llvm_lib):
                _libc_dylib = os.path.join(_llvm_lib, 'libc++.dylib')
                _libc_pp    = os.path.join(_llvm_lib, 'libc++.a')
                _is_llvm_dylib = (
                    os.path.isfile(_libc_dylib) and
                    os.path.realpath(_libc_dylib).startswith(os.path.realpath(_llvm_lib))
                )
                if _is_llvm_dylib:
                    d['CMAKE_EXE_LINKER_FLAGS'] = f'-L{_llvm_lib} -Wl,-rpath,{_llvm_lib} -lc++ -lc++abi'
                elif os.path.isfile(_libc_pp):
                    d['CMAKE_EXE_LINKER_FLAGS'] = f'-Wl,-rpath,{_llvm_lib} {_libc_pp} -lc++abi'
                else:
                    d['CMAKE_EXE_LINKER_FLAGS'] = f'-L{_llvm_lib} -Wl,-rpath,{_llvm_lib} -lc++ -lc++abi'

        # Prefer the *installed* TorchConfig.cmake (share/cmake/Torch/ or lib/cmake/Torch/)
        # over the build-tree TorchConfig.cmake at the prefix root.  cmake's prefix search
        # includes <prefix>/ so it would otherwise pick up the build-tree version first;
        # that file has hardcoded build paths (Caffe2Targets.cmake, public/utils.cmake) that
        # are absent after install.  Setting Torch_DIR bypasses the ambiguous root search.
        _torch_cmake = os.path.join(target_path, 'share', 'cmake', 'Torch')
        if not os.path.isdir(_torch_cmake):
            _torch_cmake = os.path.join(target_path, 'lib', 'cmake', 'Torch')
        if os.path.isdir(_torch_cmake):
            d['Torch_DIR'] = _torch_cmake
        else:
            d['CMAKE_PREFIX_PATH'] = target_path

        # Propagate compute backend flags so #ifdef USE_MPS / USE_ROCM / USE_CUDA
        # guards in program.cpp compile the right detection code.
        _compute_map = {
            'cuda':  'USE_CUDA',
            'rocm':  'USE_ROCM',
            'metal': 'USE_MPS',
            'xpu':   'USE_XPU',
        }
        for _key, _define in _compute_map.items():
            if _key in compute:
                d[_define] = 'ON'

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
