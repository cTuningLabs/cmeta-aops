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
            ctx: dict,           # cMeta context
            local: bool = False,
            env: dict = {},
            timeout: int = None,
    ):

        """
        Clone git repo.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK setup-git run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''
        clean = ctx_tasks['run_control'].get('clean', False)
        update = ctx_tasks['run_control'].get('update', False)

        result = {'return':0}

        path_to_git_bin = ctx_tasks['global']['git']['qpath']

        cur_dir = os.getcwd()

        if con:
            print ('')

            x = 'local ' if local else ''
            y = f' ({cur_dir})' if local else ''
            print (f'Current {x}configuration{y}:')

        # Print current config
        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'run',
              'ctx': ctx,
              'arg1': 'get-git-config,da2513e34cb04f77',
              'local': local,
              'env': env,
              'con': con, 
              'quiet': quiet,
              'verbose': verbose, 
              'quiet': quiet,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        cmds = []

        cmd = f'{path_to_git_bin} config --list'
        if local: cmd += ' --local'
        cmds.append(cmd)

        for cmd in cmds:
            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'con': con, 
                  'quiet': quiet,
                  'verbose': verbose, 
                  'quiet': quiet,
                  'text_cmd': 'RUN:',
    #              'print_env_keys': [], 
                  'print_extra_line': True,
                  'fail_if_nonzero_return_code': False,
                  'capture_output': True,
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']
            if returncode>0:
                err = f'CMD "{cmd}" failed with return code {returncode}'
                return self.cm.error(err, 99)



        ###################################################################
        # Prepare result
        return result
