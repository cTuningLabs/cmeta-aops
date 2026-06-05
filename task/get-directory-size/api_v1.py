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
            directory: str = None,
            unit: str = 'MB',
            skip_datetime: bool = True,
            text: str = None,
    ):

        """
        Get directory size

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK get-directory size")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return': 0}

        if not directory:
            directory = os.getcwd()

        r = self.cm.utils.sys.get_dir_size(directory, unit = unit, skip_datetime = skip_datetime)
        if self.cm.catch_error(r): return r
        del(r['return'])

        result['dir_size'] = r

        if con:
            print ('')
            if not text:
                text = 'Directory info:'
            print (f'{space}{text}')

            print ('')
            print (f'{space}  path: {directory}')
            print ('')
            for k in r:
                v = r[k]
                print (f'{space}  {k}: {v}')

        return result

