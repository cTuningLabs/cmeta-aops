"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

        self.target_artifact_alias_prefix = 'target-'


    ############################################################
    def run(self,
            ctx: dict,            # cMeta context
            compute: list = None, # string or list of compute (task::target-{name})
            ask: bool = False,    # ask for compute if not specified
            add_env: bool = True, # add global ENV
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        result = {'return':0}

        _global = ctx_tasks['global']

        selected_target = _global['target']

        features = selected_target.get('features', {})

        for compute in features:
            ft = features[compute]

            desc = ft.get('desc', {})

            sdk_uses = desc.get('sdk', {}).get('uses', {})

            p = {'category': self.category_alias + ',' + self.category_uid,
                 'command': 'use',
                 'con': con,
                 'quiet': quiet,
                 'verbose': verbose,
                 'ctx': ctx,
                 'desc': sdk_uses,
                 'local': None,
                 'task_artifact_alias': self.artifact_alias,
                 'task_artifact_uid': self.artifact_uid,
                 'task_artifact_path': self.artifact_path,
                }

            r = self.cm.access(p)
            if self.cm.catch_error(r): return r


        return result
