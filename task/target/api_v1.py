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


    ############################################################
    def run(self,
            ctx: dict,            # cMeta context
            compute: list = None, # string or list of compute (task::target-{name})
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

        if '#target' in ctx_tasks['global']:
            # runner is already running and called from somewhere again
            return {'return':0}

        # Set lock
        ctx_tasks['global']['#target'] = {}

        # Check target compute
        if not compute:
            compute = ['cpu']
        elif type(compute) == str:
            xcompute = []
            for x in compute.split(','):
                x = x.strip().lower()
                if x != '': 
                    xcompute.append(x)
            compute = xcompute

        # Prepare dependencies
        uses = []
        _local = {}

        for c in compute:
            compute_use = {
              'task': f'target-{c}',
            }

            uses.append(compute_use)

        # Resolve as standard dependency
        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'use',
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'ctx': ctx,
              'desc': uses,
              'local': _local,
              'task_artifact_alias': self.artifact_alias,
              'task_artifact_uid': self.artifact_uid,
              'task_artifact_path': self.artifact_path,
             }

        r = self.cm.access(ii)
        if self.cm.catch_error(r): return r

        # Prepare result
        result = {
          'return': 0,
          'compute': compute,
        }

        features = {}

        for c in compute:
            key = f'target-{c}'

            ft = ctx['tasks']['global'][key]['features']

            features[c] = ft

        result['features'] = features

        # Remove lock
        del (ctx_tasks['global']['#target'])

        return result
