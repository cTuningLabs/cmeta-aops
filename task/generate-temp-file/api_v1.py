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
            key: str = None,    
            template: str = None,
    ):

        """
        Generate temp file and record in tasks.local.key

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        r = self.cm.utils.files.gen_temp_filepath(template=template)
        if r['return']>0: return r
        temp_file = r['filepath']

        if con:
            print ('')
            print (f'{space}INFO: generated temp file "{temp_file}"') 

        result['temp_file'] = temp_file

        return result

