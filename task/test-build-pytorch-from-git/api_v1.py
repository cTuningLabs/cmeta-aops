"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            env: dict = {},
            flags: str = '',
            clean_build: bool = None,
            cmake_vars: dict = {},
            skip_configure: bool = False,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

#        self.cm.utils.files.write_file('tmp-ctx.json', ctx)

        self.logger.debug("RUNNING TASK test-nvcc run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        ctx_tasks_control = ctx['tasks']['run_control']

        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        host = _global['host']
        uname = host['os']['uname']

        path_to_src = _global['clone-git-pytorch']['path_to_git_repo']

        target_compute = _global['target']['compute']

        # Prepare env
        _aggregated = ctx['tasks']['aggregated']

        if env is None: env = {}

#        This doesn't work - setup overrides it ...
#        if 'CMAKE_INSTALL_PREFIX' not in env: env['CMAKE_INSTALL_PREFIX'] = target_path


#        if 'BUILD_TYPE' not in env: env['BUILD_TYPE'] = 'release'
        if 'BUILD_TEST' not in env: env['BUILD_TEST'] = 'OFF'
        if 'CMAKE_GENERATOR' not in env: env['CMAKE_GENERATOR'] = 'Ninja'


# Use it to detect MKL and other python based stuff on Windows
        if '+CMAKE_PREFIX_PATH' not in env:
            if uname == 'windows':
                env['+CMAKE_PREFIX_PATH'] = [os.path.join(_global['python']['path_home'], 'Library'), _global['python']['path_home']]
            elif uname == 'linux':
                env['+CMAKE_PREFIX_PATH'] = [os.path.join(_global['python']['path_home'], 'lib'), _global['python']['path_home']]


#        if 'cpu' in target_compute and 'xpu' not in target_compute:
#            # Point Intel MKL to python
#            if uname == 'linux':
#                env['MKL_DIR'] = _global['python']['path_home']
#                env['MKL_ROOT_DIR'] = _global['python']['path_home']
#                env['MKL_ROOT'] = _global['python']['path_home']
#                env['MKLROOT'] = _global['python']['path_home']

        if 'xpu' in target_compute:
            if uname == 'windows':
                # FGG: I had problems installing KINETO on Windows
                if 'USE_KINETO' not in env: env['USE_KINETO'] = 'OFF'
                if 'TORCH_XPU_ARCH_LIST' not in env: env['TORCH_XPU_ARCH_LIST'] = 'bmg'

        if 'cuda-sdk' in target_compute:
            cuda_home = _global['nvcc']['features']['paths']['home']
            if 'CUDA_PATH' not in env:
                env['CUDA_PATH'] = cuda_home
            if 'CUDA_TOOLKIT_ROOT_DIR' not in env:
                env['CUDA_TOOLKIT_ROOT_DIR'] = cuda_home

            cudnn_home = _global['cudnn']['features']['paths']['home']
            cudnn_include = _global['cudnn']['features']['paths']['include']
            cudnn_lib = _global['cudnn']['features']['paths']['lib']

            env['CUDNN_LIB_DIR'] = cudnn_lib
            env['CUDNN_INCLUDE_DIR'] = cudnn_include


        cmake_vars_from_target = _global['target']['cmake_vars'].copy()
        for k in cmake_vars_from_target:
            if k not in env:
                env[k] = cmake_vars_from_target[k]

        # check cmake path and add it to env if needed
        cmake_bin = _global['cmake']['qpath_bin']

        aenv = _aggregated.get('env',{})
        apath = aenv.get('+PATH', [])

        if cmake_bin not in apath:
            _path = env.setdefault('+PATH',[])
            if cmake_bin not in _path:
                _path.insert(0, cmake_bin)

        if 'OPENSSL_ROOT_DIR' not in env: 
            env['OPENSSL_ROOT_DIR'] = _global['lib-openssl']['features']['paths']['root']

        if 'CMAKE_C_COMPILER' not in env:
            env['CMAKE_C_COMPILER'] = _global['host_c_compiler_for_pytorch_build']['path']

        if 'CMAKE_CXX_COMPILER' not in env:
            env['CMAKE_CXX_COMPILER'] = _global['host_cpp_compiler_for_pytorch_build']['path']

        # ROCm
        #If you're compiling for AMD ROCm then first run this command:
        #
        ## Only run this if you're compiling for ROCm
        #python tools/amd_build/build_amd.py

#        cpu_count = int(_global['host']['os']['python_os_cpu_count']) - 2
#        if cpu_count < 1 :
#            cpu_count = 1
#
#        if 'MAX_JOBS' not in env: env['MAX_JOBS'] = str(cpu_count)

        cmd = _global['python']['qpath'] + f' -m pip install --no-build-isolation -v -e .'

        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'run',
              'ctx': ctx,
              'arg1': 'cmd,c9ba0a88df394d7f',
              'chdir': path_to_src,
              'cmd': cmd,
              'env': env,
              'con': con, 
              'quiet': quiet,
              'verbose': verbose, 
              'text_cmd': 'RUN:',
              'print_extra_line': True,
              'storage_key': 'cmd_before_building',
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        returncode = rx['returncode']
        if returncode>0:
            return {'return':99, 'error': f'cmd "{cmd}" failed with return code "{returncode}"'}


#        'CMAKE_CXX_COMPILER': '{{global.host_cpp_compiler.qpath}}',
#        'CMAKE_C_COMPILER': '{{global.host_c_compiler.qpath}}',
#        'CMAKE_MAKE_PROGRAM':'{{global.ninja.qpath}}',
#        'CMAKE_PREFIX_PATH':'{{global.python.qpath_home}};"{{global.python.path_home}}\\Library"',
#        'CMAKE_INCLUDE_PATH':'"{{global.python.path_home}}\\Library\\include"',
#        'CMAKE_LIB_PATH':'"{{global.python.path_home}}\\Library\\lib"',
#        'INTEL_MKL_DIR':'"{{global.python.path_home}}\\Library"', # On Windows -> Library
#        'INTEL_OMP_DIR':'"{{global.python.path_home}}\\Library"',

        return result
