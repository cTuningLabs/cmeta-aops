"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
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
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK test-clang-cpp run")

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

        compiler = ctx['tasks']['global']['clang-cpp']
        compiler_path = compiler['path']
        compiler_qpath = compiler['qpath']

        if not os.path.isdir('tmp'):
            os.makedirs('tmp')

        host = ctx_tasks['global']['host']
        uname = host['os']['uname']

        for source_file in [f'test-{uname}.cpp', 'test.cpp']:
            src_file = os.path.join(task_path, 'src', source_file)
            if os.path.isfile(src_file):
                break

        exe_file = 'test' + host['vars']['file_ext_exe']

        cmds = [
          compiler_qpath + f' {src_file} -v -o ' + os.path.join('tmp', exe_file),
          os.path.join('tmp', exe_file),
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


        print ('='*80)
        print (f'CLANG PATH: {compiler_path}')
        print ('='*80)

        return result

