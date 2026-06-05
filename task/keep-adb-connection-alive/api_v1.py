"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

# TO BE UPDATED WITH "cmd" or running tool "adb" (with timeout, env, etc) !!!

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            env: dict = {},
            ip: str = None,
            period: str = None,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **devices** (list): List of dicts with keys `serial` and `state`
                  for each attached Android device.


                  os: ['Windows', 'Linux', 'macOS']
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        if ip is None:
            return self.cm.error(f'ip is not defined in "{__file__}"') 

        if period is None:
            period = 10

        period = int(period)     

        adb_path = ctx_tasks['global']['adb']['qpath']

        cmd = f'{adb_path} connect {ip}'

        while True:

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
                  'print_extra_line': False,
                  'fail_if_nonzero_return_code': False,
                  'capture_output': True,
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']
            stdout = rx.get('stdout').strip().rstrip('\n')
            if stdout:
                stdout += '\n'
            stdout += rx.get('stderr').strip().rstrip('\n')

            if con:
                print ('')
                print (f'Return code: {returncode}')

                print ('')
                print (f'Output: {stdout}')

                print (f'Sleeping for {period} sec ...')

            time.sleep(period)

        return {'return':0}


