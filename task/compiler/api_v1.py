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
    def init(self,
             ctx: dict,
             params: dict,
    ):
        r = self.cm.check_params(params, [
                'lang',
                'extra_tags',
                'extra_match',
            ], __name__)
        if self.cm.catch_error(r): return r

        return {'return':0}

    ############################################################
    def run(self,
            ctx: dict,          # cMeta context
            lang: str = None,   # string or list of compute (task::target-{name})
            extra_tags = None,  # extra tags to force specific compiler, etc (clang, gcc-cpp, msvc, etc)
            extra_match = None, # extra match dict
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        if not lang:
            return self.cm.error(f'"lang" is not specified in "{__file__}"')

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        uname = ctx['tasks']['global']['host']['os']['uname']

        tool_tags = [f'lang-{lang}']

        tool_match = {} if extra_match is None or extra_match == '' else extra_match
        supports_os = tool_match.setdefault('supports_os', [])
        if uname not in supports_os: supports_os.append(uname)

        if extra_tags and type(extra_tags) == str:
            extra_tags = self.cm.utils.common.split(extra_tags)

        if extra_tags:
            tool_tags += extra_tags

        ###########################################################################################
        # SELECT TOOL ARTIFACT

        p = {'category': self.cmeta['uses_categories']['utils'],
             'command': 'select_artifact',
             'select_category': self.cmeta['uses_categories']['tool'],
             'select_tags': tool_tags,
             'select_match': tool_match,
             'con': con,
             'quiet': quiet,
             'verbose': verbose,
             'space': space,
        }

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): return r

        artifact = r['artifact']

        tool_name = artifact['cmeta_ref_parts']['artifact_alias']

        ###########################################################################################
        # SETUP TOOL

        # Don't forget CXT here to update global context for further tasks and tools in a higher level pipeline
        p = {'ctx': ctx,
             'category': self.category_alias + ',' + self.category_uid,
             'command': 'run',
             'arg1': 'setup,a2f9b61079ce4333',
             'name': tool_name,
             'con': con,
             'quiet': quiet,
             'verbose': verbose,
        }

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): return r

        ###########################################################################################
        # COPY TO RESULT AND UNIFY IF NEEDED
        result = r

        return result
