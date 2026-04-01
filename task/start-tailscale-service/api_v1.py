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
    ):

        """
        Untar file.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK untar-file run api_v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        uname = ctx['tasks']['global']['host']['os']['uname']

        path_to_tailscale = ctx['tasks']['global']['tailscale']['qpath']

        if con and not quiet:
            print ('')
            print ('WARNING: make sure that you run start-tailscale-service in the Desktop terminal since it may open browser to log in to tailscale!')
            print ('')
            x = input('Press Enter to continue: ')

        cmd = 'sudo brew services start tailscale'

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
              'fail_if_nonzero_return_code': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return rx
