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
            ask: bool = False,
            compute: str = None,
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

        _global = ctx_tasks['global']

        selected_compute = _global['target']['compute']

        p = {'category': self.cmeta['uses_categories']['utils'],
             'command': 'select_artifact',
             'select_category': self.cmeta['uses_categories']['program'],
             'select_artifact': name,
             'select_tags': program_tags,
#             'select_match':{'constraints':{'target':[]}},
             'select_match':{'constraints':{}},
             'con': con,
             'quiet': quiet,
             'load_files': ['_desc'], #'_desc_compile', '_desc_run'],
             'space': space,
             'load_api': True,
             'load_api_ver': program_api_ver,
             'load_api_class': 'CProgram',
             'print_extra_line': True,
        }

        constraints = {}

        if selected_compute:
            # AND match, i.e. cpu + cuda should match both (for hybrid compute)
            constraints['supported_compute'] = selected_compute

        if constraints:
            p['select_match'] = {'constraints': constraints}

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): 
            if r['return'] == 16 and constraints:
                r['error'] += f' with constraints "{constraints}"'
            r['return'] = 1 # Fail above
            return r

        artifact = r['artifact']
        artifact_au = r['artifact_au']
        loaded_files = r['loaded_files']
        program_api_code = r['api_code']

        if con and verbose:
            print ('')
            print (f'{space}INFO: Selected program "{artifact_au}"')

        selected_program = {
            'path': artifact['path'],
            'artifact': artifact, 
            'artifact_au': artifact_au, 
            'loaded_files': loaded_files, 
            'api_code':program_api_code,
        }

        result['add_to_local'] = {'selected-program': selected_program}

        return result
