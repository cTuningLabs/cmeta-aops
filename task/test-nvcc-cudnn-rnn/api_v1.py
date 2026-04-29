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

        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        host = ctx_tasks['global']['host']
        uname = host['os']['uname']

        nvcc = ctx['tasks']['global']['nvcc']
        cudnn = ctx['tasks']['global']['cudnn']

        exe_file = 'RNN_v8.0' + host['vars']['file_ext_exe']
        target_exe_file = os.path.join('tmp', exe_file)

        src_dir = os.path.join(task_path, 'RNN_v8.0')
        src_file = os.path.join(src_dir, 'RNN_example.cu')
        qsrc_file = self.cm.q(src_file)

        # Check includes/libs
        includes = [
          src_dir,
          cudnn['features']['paths']['include'],
        ]

        # Check libs
        libs = [
          src_dir,
          cudnn['features']['paths']['lib'],
        ]

        # Assemble flags
        if flags is None: flags = ''

        if flags: 
            flags += ' '

        cpp_compiler_qpath = ctx_tasks['global']['compiler']['qpath']
        flags += f'-ccbin={cpp_compiler_qpath} --allow-unsupported-compiler'

        # Check gencode
        flag1 = ctx_tasks['global']['nvcc']['features']['flags']['gencode_auto']
        if flag1:
            flags += ' ' + flag1

        # Check includes and libs
        for include in includes:
            flags += ' -I' + self.cm.q(include)

        for lib in libs:
            flags += ' -L' + self.cm.q(lib)

        cmd_build = nvcc['qpath'] + f' {qsrc_file} {flags} -lcublas -lcudnn -lcudart -o {target_exe_file}'

        # Check DYNAMIC LIBS/BINS
        cudnn_path_bin = cudnn['features']['paths']['bin']

        if env is None: env = {}
        env_path = env.setdefault('+PATH',[])
        env_path.insert(0, cudnn_path_bin)

        cmds = [
          cmd_build,
          os.path.join('tmp', exe_file)
        ]

        for icmd in range(0, len(cmds)):
            cmd = cmds[icmd]

            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'con': con, 
                  'quiet': quiet,
                  'verbose': verbose, 
                  'text_cmd': 'RUN:',
#                  'print_env_keys': ['PATH'],
                  'print_extra_line': True,
                  'save_script': f'tmp/save-script-{icmd}' + '{{file_ext_bat}}',
                  'storage_key': f'{self.artifact_alias}-cmd-{icmd}',
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']
            if returncode>0:
                return {'return':99, 'error': f'cmd "{cmd}" failed with return code "{returncode}"'}


        return result
