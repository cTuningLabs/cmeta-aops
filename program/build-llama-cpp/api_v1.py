"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import shlex

from program_22788f3c30d04e6d.api.cprogram import InitCProgram

class CProgram(InitCProgram):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize1(self,
                   ctx: dict,        # cMeta context
                   desc: dict = {},
                   **params,
    ):

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        compute = ctx['tasks']['global']['target']['compute']
        uname = ctx['tasks']['global']['host']['os']['uname']

        if 'cuda' in compute:
            _local['lang'] = 'cuda'

        return {'return':0}

    ############################################################
    def customize_llama_cpp(self,
                            ctx: dict,        # cMeta context
                            desc: dict = {},
                            **misc,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        compute = _global['target']['compute']
        uname = _global['host']['os']['uname']

        params = misc.get('params', {})
        _compile = params.get('compile')
        if not _compile:
            _compile = {}

        debug_info = _compile.get('debug_info')
        static = _compile.get('static')
        fastest = _compile.get('fastest')
        strict_compute = _compile.get('strict_compute')

        d = _compile.get('d')
        if not d: d = {}

        x = 'OFF' if static else 'ON'
        if 'BUILD_SHARED_LIBS' not in d:
            d['BUILD_SHARED_LIBS'] = x

        # Target exe
        target_file_name_ext = ''
        if uname == 'windows' and 'android-cpu' not in compute:
            target_file_name_ext = '.exe'

        _local['print_file'] = 'type' if uname == 'windows' else 'cat'

        target_file_name_with_ext = _local['target_file_name'] + target_file_name_ext

        _local['target_file_name_with_ext' ] = target_file_name_with_ext

        # Target path
        target_path_bin = os.path.join(_local['target_path'], 'bin')
        if debug_info:
            build_type = 'Debug'
        else:
            build_type = 'Release'
#            target_path_bin = os.path.join(target_path_bin, build_type)
        _local['build_type'] = build_type

        if 'CMAKE_BUILD_TYPE' not in d:
            d['CMAKE_BUILD_TYPE'] = build_type

        if 'CMAKE_MAKE_PROGRAM' not in d:
            d['CMAKE_MAKE_PROGRAM'] = _global['ninja']['qpath']

        if 'cpu' in compute or 'cuda' in compute:
            cmake_c_compiler = _global['compiler-c']['qpath']
            if 'CMAKE_C_COMPILER' not in d:
                d['CMAKE_C_COMPILER'] = cmake_c_compiler
            if 'CMAKE_CXX_COMPILER' not in d:
                if uname == 'windows' and ctx['tasks']['global']['compiler-cpp']['features'].get('id') == 'Intel':
                    cmake_cpp_compiler = cmake_c_compiler # Known issue on Windows with Intel
                else:
                    cmake_cpp_compiler = _global['compiler-cpp']['qpath']

                d['CMAKE_CXX_COMPILER'] = cmake_cpp_compiler

            if 'cuda' in compute:
                if 'CMAKE_CUDA_COMPILER' not in d:
                    d['CMAKE_CUDA_COMPILER'] = ctx['tasks']['global']['nvcc']['qpath']

        if fastest and 'GGML_NATIVE' not in d:
            d['GGML_NATIVE'] = 'ON'

        if 'lib-openssl' in _global and 'OPENSSL_ROOT_DIR' not in d:
            d['OPENSSL_ROOT_DIR'] = _global['lib-openssl']['features']['paths']['qroot']

        if 'lib-openmp' in _global and 'OpenMP_omp_LIBRARY' not in d:
            d['OpenMP_omp_LIBRARY'] = _global['lib-openmp']['qpath']
            d['OpenMP_C_LIB_NAMES'] = 'omp'
            d['OpenMP_CXX_LIB_NAMES'] = 'omp'

        for x in [
                ('cpu', 'GGML_CPU', 'OFF'),
                ('cuda', 'GGML_CUDA', 'OFF'),
                ('metal', 'GGML_METAL', 'OFF'),
            ]:
            if x[0] in compute:
                if x[1] not in d:
                    d[x[1]] = 'ON'
            elif strict_compute and x[1] not in d:
                d[x[1]] = x[2]

        _local['target_path_bin'] = target_path_bin
        _local['target_exe'] = target_file_name_with_ext
        _local['target_path_llama_cli'] = os.path.join(target_path_bin, target_file_name_with_ext)
        _local['target_path_exe'] = _local['target_path_llama_cli']

#        _local['cmake_d_vars'] = " ".join(f"-D{k}={shlex.quote(str(v))}" for k, v in d.items())
        _local['cmake_d_vars'] = " ".join(f"-D{k}={self.cm.q(str(v))}" for k, v in d.items())

        _local['skip_template_compile'] = True

        return {'return':0}

