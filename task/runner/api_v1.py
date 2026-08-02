"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


                  os: ['Windows', 'Linux', 'macOS']
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        if '#runner' in ctx_tasks['global']:
            # runner is already running and called from somewhere again
            return {'return':0}

        # Set lock
        ctx_tasks['global']['#runner'] = {}

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        ######################################################################
        os_name = platform.system()

        result['platform_system'] = os_name
        result['platform_system_lower'] = os_name.lower()

        if os_name.lower() == 'darwin':
            os_name = 'macOS'

        result['os'] = os_name
        result['os_lower'] = os_name.lower()

        # Remove lock
        del (ctx_tasks['global']['#runner'])

        return result

