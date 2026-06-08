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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)


    ############################################################
    def customize_compile(self,
                          ctx: dict,
                          desc: dict = {},
                          **params,
    ):
        _local  = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']

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
            d['CMAKE_CXX_COMPILER'] = cxx

        # CMAKE_PREFIX_PATH tells find_package(Torch) where TorchConfig.cmake lives
        if torch_home:
            d['CMAKE_PREFIX_PATH'] = torch_home

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
