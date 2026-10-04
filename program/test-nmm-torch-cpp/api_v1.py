"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import sys

from program_22788f3c30d04e6d.api.cprogram import InitCProgram


class CProgram(InitCProgram):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)


    ############################################################
    def customize_compile(self,
                          ctx: dict,
                          desc: dict = {},
                          **misc,
    ):
        _local  = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        compute = _global.get('target', {}).get('compute', [])

        params = misc.get('params', {})
        _compile = params.get('compile')
        if not _compile:
            _compile = {}

        debug_info  = _compile.get('debug_info', False)
        build_type  = 'Debug' if debug_info else 'Release'
        _local['build_type'] = build_type

        # -----------------------------------------------------------------------
        # libtorch install prefix exposed by tool/torch-cpp check_features
        torch_cpp  = _global.get('torch-cpp', {})
        torch_home = torch_cpp.get('features', {}).get('paths', {}).get('home', '')

        # -----------------------------------------------------------------------
        # cmake -D flags for the test binary
        d = {}
        d['CMAKE_BUILD_TYPE']   = build_type
        d['CMAKE_MAKE_PROGRAM'] = _global['ninja'].get('path') or _global['ninja']['qpath'].strip('"').strip("'")

        if 'compiler-c' in _global:
            d['CMAKE_C_COMPILER'] = _global['compiler-c'].get('path') or _global['compiler-c']['qpath'].strip('"').strip("'")
        if 'compiler-cpp' in _global:
            cxx = _global['compiler-cpp'].get('path') or _global['compiler-cpp']['qpath'].strip('"').strip("'")
            if uname == 'windows' and _global['compiler-cpp'].get('features', {}).get('id') == 'Intel':
                cxx = d.get('CMAKE_C_COMPILER', cxx)
            # PyTorch's prebuilt LibTorch for Windows is built with MSVC: its CMake config adds MSVC
            # options (/EHsc, /bigobj) that the GNU-style clang++ rejects; clang-cl, next to it, takes
            # them (same ABI)
            if uname == 'windows' and torch_cpp.get('features', {}).get('build') == 'prebuilt' and \
               os.path.basename(cxx).lower() in ('clang++.exe', 'clang.exe'):
                clang_cl = os.path.join(os.path.dirname(cxx), 'clang-cl.exe')
                if os.path.isfile(clang_cl):
                    cxx = clang_cl
            d['CMAKE_CXX_COMPILER'] = cxx

        # CMAKE_PREFIX_PATH tells find_package(Torch) where TorchConfig.cmake lives; Torch_DIR too,
        # since CMake keeps the Torch_DIR it found first in its cache (another libtorch, e.g. a CUDA
        # build after a CPU one, would otherwise not be seen)
        if torch_home:
            d['CMAKE_PREFIX_PATH'] = torch_home
            for _sub in (('share', 'cmake', 'Torch'), ('lib', 'cmake', 'Torch')):
                _torch_dir = os.path.join(torch_home, *_sub)
                if os.path.isfile(os.path.join(_torch_dir, 'TorchConfig.cmake')):
                    d['Torch_DIR'] = _torch_dir
                    break

        # The backend of the target for the #ifdef guards of program.cpp (USE_MPS: Apple GPUs)
        for _key, _define in (('cuda', 'USE_CUDA'), ('rocm', 'USE_ROCM'), ('metal', 'USE_MPS'), ('xpu', 'USE_XPU')):
            if _key in compute:
                d[_define] = 'ON'

        # --cxx_standard=<n>: the C++ standard of the program (default: the one LibTorch's CMake
        # config asks for, 17 or 20)
        if params.get('cxx_standard'):
            d['CMETA_CXX_STANDARD'] = str(params['cxx_standard'])

        # A CUDA build of libtorch enables CUDA in its CMake config: the CUDA compiler of cMeta, and
        # NVTX3 from the CUDA toolkit (without USE_SYSTEM_NVTX it looks in its own source tree, then
        # for nvToolsExt, which newer CUDA toolkits no longer have)
        if 'cuda' in compute:
            if 'nvcc' in _global:
                d['CMAKE_CUDA_COMPILER'] = _global['nvcc'].get('path') or _global['nvcc']['qpath'].strip('"').strip("'")
            d['USE_SYSTEM_NVTX'] = 'ON'

        _local['cmake_d_vars'] = ' '.join(
            f'-D{k}={self.cm.q(str(v))}' for k, v in d.items()
        )

        # -----------------------------------------------------------------------
        # Source directory containing CMakeLists.txt
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
        _local['cmake_src_path'] = self.cm.q(src_dir)

        # -----------------------------------------------------------------------
        # Check file: the compiled test binary (produced by Ninja in target_path)
        target_path = _local['target_path']
        exe_name = 'program.exe' if uname == 'windows' else 'program'
        _local['target_path_exe'] = os.path.join(target_path, exe_name)

        # Add libtorch lib dir to PATH at compile time (needed if cmake runs any tests)
        if torch_home:
            torch_lib = os.path.join(torch_home, 'lib')
            _local.setdefault('run_time_env', {})['TORCH_LIB'] = torch_lib

        _local['skip_template_compile'] = True

        return {'return': 0}
