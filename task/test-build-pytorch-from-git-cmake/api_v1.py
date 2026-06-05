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
        ctx_tasks_control = ctx['tasks']['run_control']
        ctx_tasks['global']['cmake']['qpath']
        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        host = ctx_tasks['global']['host']
        uname = host['os']['uname']

        path_to_src = ctx_tasks['global']['clone-git-pytorch']['path_to_git_repo']
        path_to_build = os.path.join(path_to_src, 'build')

        if not skip_configure:

            cmake_vars.update({
              'CMAKE_CXX_COMPILER': '{{global.host_cpp_compiler.qpath}}',
              'CMAKE_C_COMPILER': '{{global.host_c_compiler.qpath}}',
              'CMAKE_MAKE_PROGRAM':'{{global.ninja.qpath}}',
              'CMAKE_PREFIX_PATH':'{{global.python.qpath_home}};"{{global.python.path_home}}\\Library"',
              'CMAKE_INCLUDE_PATH':'"{{global.python.path_home}}\\Library\\include"',
              'CMAKE_LIB_PATH':'"{{global.python.path_home}}\\Library\\lib"',
              'PYTHON_EXECUTABLE':'{{global.python.qpath}}',
              'INTEL_MKL_DIR':'"{{global.python.path_home}}\\Library"', # On Windows -> Library
              'INTEL_OMP_DIR':'"{{global.python.path_home}}\\Library"',
              'USE_KINETO':'OFF',
            })

            # Check targets


            r = self.cm.utils.common.expand_strings_in_dict(cmake_vars, ctx_tasks)
            if self.cm.catch_error(r): return r

            if uname == 'windows':
                for k in cmake_vars:
                    cmake_vars[k] = cmake_vars[k].replace('\\', '/')

#            cmd = ctx_tasks['global']['cmake']['qpath'] + ' -S .. -B build -G Ninja'
            cmd = ctx_tasks['global']['cmake']['qpath'] + ' -B build -G Ninja'

            cmake_vars_from_target = ctx_tasks['global']['target']['cmake_vars'].copy()
            cmake_vars_from_target.update(cmake_vars)

            if 'CMAKE_BUILD_TYPE' not in cmake_vars_from_target:
                cmake_vars_from_target['CMAKE_BUILD_TYPE'] = 'Release'
            if 'BUILD_TEST' not in cmake_vars_from_target:
                cmake_vars_from_target['BUILD_TEST'] = 'OFF'

            for k in sorted(cmake_vars_from_target):
                cmd += ' -D' + k + '=' + cmake_vars_from_target[k]

            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
#                  'mkdir': path_to_build,
#                  'chdir': path_to_build,
                  'chdir': path_to_src,
                  'cmd': cmd,
                  'env': env,
                  'con': con, 
                  'quiet': quiet,
                  'verbose': verbose, 
                  'text_cmd': 'RUN:',
    #                  'print_env_keys': ['PATH'],
                  'print_extra_line': True,
                  'storage_key': 'cmd_before_building',
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']
            if returncode>0:
                return {'return':99, 'error': f'cmd "{cmd}" failed with return code "{returncode}"'}



        cpu_count = int(ctx_tasks['global']['host']['os']['python_os_cpu_count']) - 2
        if cpu_count < 1 :
            cpu_count = 1

        cmd = ctx_tasks['global']['cmake']['qpath'] + f' --build build --config Release -j {cpu_count}'

        print (cmd)
        input('xyz2')

        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'run',
              'ctx': ctx,
              'arg1': 'cmd,c9ba0a88df394d7f',
#              'chdir': path_to_build,
              'chdir': path_to_src,
              'cmd': cmd,
              'env': env,
              'con': con, 
              'quiet': quiet,
              'verbose': verbose, 
              'text_cmd': 'RUN:',
#                  'print_env_keys': ['PATH'],
              'print_extra_line': True,
              'storage_key': 'cmd_before_building',
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        cmd = ctx_tasks['global']['python']['qpath'] + f' setup.py bdist_wheel'

        print (cmd)
        input('xyz')

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
#                  'print_env_keys': ['PATH'],
              'print_extra_line': True,
              'storage_key': 'cmd_before_building',
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx


        return result

