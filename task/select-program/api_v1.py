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
    def run(
            self, 
            ctx, 
            name: str = None,
            program_tags: str = None,
            program_api_ver: str = None,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK select-program run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        result = {'return':0}

        p = {'category': self.cmeta['uses_categories']['utils'],
             'command': 'select_artifact',
             'select_category': self.cmeta['uses_categories']['program'],
             'select_artifact': name,
             'select_tags': program_tags,
             'con': con,
             'quiet': quiet,
             'load_files': ['_desc', '_desc_compile', '_desc_run'],
             'space': space,
             'load_api': True,
             'load_api_ver': program_api_ver,
             'load_api_class': 'CProgram',
        }

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): return r

        artifact = r['artifact']
        loaded_files = r['loaded_files']
        program_api_code = r['api_code']

        # Check common filters (OS, targets, etc)
        target = ctx['tasks']['global']['target']

        self.cm.j(target)


        selected_program = {
            'artifact': artifact, 
            'loaded_files': loaded_files, 
            'api_code':program_api_code,
        }

        return result
