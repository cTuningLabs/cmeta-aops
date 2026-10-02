"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import shlex

from program_22788f3c30d04e6d.api.cprogram import InitCProgram
from program_22788f3c30d04e6d.api import common_llama_cpp

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

        # --model=<file.gguf>, --prompt=<file>: instead of the model and dataset categories, as in
        # program llama-cpp (the same experiment with a release and a source build)
        program_params = params.get('params', {})
        model = program_params.get('model')
        prompt = program_params.get('prompt')
        if model or prompt:
            _use = ctx['tasks'].setdefault('use', {})
            if model:
                _use.setdefault('model', {})['filename'] = os.path.abspath(model)
            if prompt:
                _use.setdefault('dataset', {})['filename'] = os.path.abspath(prompt)

        return {'return':0}

    ############################################################
    def customize_run(self,
                      ctx: dict,
                      **misc
    ):
        """
        The llama.cpp flags of this run from the targets and the offload parameters (--ngl,
        --devices, --split_mode, --tensor_split, --main_gpu, --threads): see common_llama_cpp.
        Set at run time, not with the build: a reused build would otherwise bring back the
        flags of the run that compiled it.
        """

        params = misc.get('params') or ctx['tasks']['local'].get('params', {})
        compute = ctx['tasks']['global']['target']['compute']

        flags, settings = common_llama_cpp.run_flags(compute, params)
        ctx['tasks']['local']['llama_cpp_compute_flags'] = flags
        ctx['tasks']['local']['llama_cpp_settings'] = settings

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

        if 'cpu' in compute or 'cuda' in compute or 'vulkan' in compute:
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

        # HTTPS (llama.cpp's own -hf downloads; cMeta downloads models itself): OpenSSL when it
        # is installed, BoringSSL built along (--compile.boringssl, as the release binaries do),
        # else none - llama.cpp then only warns, as it does without OpenSSL
        if _compile.get('boringssl'):
            d.setdefault('LLAMA_BUILD_BORINGSSL', 'ON')
        elif 'android-cpu' not in compute and 'OPENSSL_ROOT_DIR' not in d and 'LLAMA_OPENSSL' not in d:
            if 'lib-openssl' not in _global:
                common_llama_cpp.optional_access(self.cm, ctx, {
                                'category': 'task,c36be4b9314a45e0', 'command': 'run',
                                'arg1': 'setup,a2f9b61079ce4333', 'name': 'lib-openssl,903191f1fab74064',
                                'ctx': ctx, 'skip_install': True, 'skip_build': True,
                                'con': False, 'quiet': True})
            qroot = _global.get('lib-openssl', {}).get('features', {}).get('paths', {}).get('qroot')
            if qroot:
                d['OPENSSL_ROOT_DIR'] = qroot
            else:
                d['LLAMA_OPENSSL'] = 'OFF'

        if 'lib-openmp' in _global and 'OpenMP_omp_LIBRARY' not in d:
            d['OpenMP_omp_LIBRARY'] = _global['lib-openmp']['qpath']
            d['OpenMP_C_LIB_NAMES'] = 'omp'
            d['OpenMP_CXX_LIB_NAMES'] = 'omp'

        for x in [
                ('cpu', 'GGML_CPU', 'OFF'),
                ('cuda', 'GGML_CUDA', 'OFF'),
                ('metal', 'GGML_METAL', 'OFF'),
                ('vulkan', 'GGML_VULKAN', 'OFF'),
            ]:
            if x[0] in compute:
                if x[1] not in d:
                    d[x[1]] = 'ON'
            elif strict_compute and x[1] not in d:
                d[x[1]] = x[2]

        # Vulkan: the loader library to link with - the LunarG Linux SDK no longer ships it, so
        # CMake's FindVulkan needs it named (the system's libvulkan.so.1)
        if 'vulkan' in compute and 'Vulkan_LIBRARY' not in d:
            loader_lib = _global.get('vulkan-sdk', {}).get('features', {}).get('paths', {}).get('loader_lib')
            if loader_lib:
                d['Vulkan_LIBRARY'] = loader_lib

        # Metal is on by default on macOS: a build for another target (cpu, vulkan through MoltenVK)
        # turns it off, so a CPU benchmark opens no GPU device at all
        if uname == 'darwin' and 'metal' not in compute and 'GGML_METAL' not in d:
            d['GGML_METAL'] = 'OFF'

        _local['target_path_bin'] = target_path_bin
        _local['target_path_llama_cli'] = os.path.join(target_path_bin, target_file_name_with_ext)

        # The run uses llama-completion when the checkout has it (llama-cli is an interactive
        # chat UI since the late-2025 rework), llama-cli in older checkouts
        path_to_git_repo = _global.get('clone-git-to-cache-src-llama-cpp', {}).get('path_to_git_repo')
        run_exe = common_llama_cpp.completion_binary(path_to_git_repo, target_path_bin, target_file_name_ext)
        _local['target_exe'] = run_exe
        _local['target_path_exe'] = os.path.join(target_path_bin, run_exe)

        # Nested CMake projects (ggml-vulkan's vulkan-shaders-gen, built for the host at build time)
        # inherit neither CMAKE_MAKE_PROGRAM nor the compilers: they need ninja (and cmake) on PATH
        # and CC/CXX in the environment, while cMeta's ninja and cmake live in its cache
        build_env = {'+PATH': []}
        for tool in ('ninja', 'cmake'):
            p = _global.get(tool, {}).get('path')
            if p:
                build_env['+PATH'].append(os.path.dirname(p))
        if 'CMAKE_C_COMPILER' in d:
            build_env['CC'] = str(d['CMAKE_C_COMPILER']).strip('"')
        if 'CMAKE_CXX_COMPILER' in d:
            build_env['CXX'] = str(d['CMAKE_CXX_COMPILER']).strip('"')
        _local['llama_cpp_build_env'] = build_env

#        _local['cmake_d_vars'] = " ".join(f"-D{k}={shlex.quote(str(v))}" for k, v in d.items())
        _local['cmake_d_vars'] = " ".join(f"-D{k}={self.cm.q(str(v))}" for k, v in d.items())

        _local['skip_template_compile'] = True

        return {'return':0}

    ############################################################
    def finish_llama_run(self,
                         ctx: dict,
                         desc: dict = {},
                         **misc,
    ):
        """
        After the run: clean output.txt, record llama.cpp's timings in perf.json (result['perf']).
        """

        return common_llama_cpp.finish_llama_run(self, ctx, desc, **misc)

