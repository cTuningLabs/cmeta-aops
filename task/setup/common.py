"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os


def read_tool(self,
        ctx: dict,                  # cMeta context
        name: str = None,           # Tool name
        tool_tags: str = None,      # Tool tags
        tool_api_ver: int = None,   # Tool api ver (if has code)
        skip_uses: bool = False,    # Skip uses in init when we resolve storage key and params
):

    if self.cm.debug:
        self.logger.debug("RUNNING TASK setup read_tool")

    con = ctx['control'].get('con', False)
    quiet = ctx['control'].get('quiet', False)
    verbose = ctx['control'].get('verbose', False)

    ctx_tasks = ctx['tasks']
    nested_call = ctx_tasks.setdefault('nested_call', 0)
    space = '  ' * nested_call if verbose else ''

    _local = {}

    ###########################################################################################
    # SELECT TOOL ARTIFACT

    p = {'category': self.cmeta['uses_categories']['utils'],
         'command': 'select_artifact',
         'select_category': self.cmeta['uses_categories']['tool'],
         'select_artifact': name,
         'select_tags': tool_tags,
         'con': con,
         'quiet': quiet,
         'load_files': ['_desc'],
         'space': space,
         'load_api': True,
         'load_api_ver': tool_api_ver,
         'load_api_class': 'CTool',
    }

    r = self.cm.access(p)
    if self.cm.catch_error(r, fail16=True):
        return r

    artifact = r['artifact']

    cdesc = r['loaded_files']['_desc'].get('data', {})

    tool_api_code = r['api_code']
    if tool_api_code:
        tool_api_code.cmeta = artifact['cmeta']
        tool_api_code.cdesc = cdesc
        tool_api_code.cache_sep = self.cache_sep

    artifact_au = r['artifact_au']

    artifact_print_name = artifact_au
    if 'artifact_print_name' in cdesc:
        artifact_print_name = cdesc['artifact_print_name']

        r = self.cm.utils.common.expand_string(artifact_print_name, ctx_tasks)
        if self.cm.catch_error(r): return r

        artifact_print_name = r['string']

    ###########################################################################################
    # CHECK IF FAIL ON NON WINDOWS
    if cdesc.get('win_only', False) and os.name != 'nt':
        return {'return': 1, 'error': f'the tool "{artifact_print_name}" can run only on Windows'}

    ###########################################################################################
    # CHECK DEPENDENCIES
    if not skip_uses:
        uses = cdesc.get('uses', [])

        if uses:
            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'use',
                  'con': con,
                  'quiet': quiet,
                  'verbose': verbose,
                  'ctx': ctx,
                  'desc': uses,
                  'task_artifact_alias': self.artifact_alias,
                  'task_artifact_uid': self.artifact_uid,
                  'task_artifact_path': self.artifact_path,
                 }

            r = self.cm.access(ii)
            if self.cm.catch_error(r): return r

    return {
        'return': 0,
        'nested_call': nested_call,
        'space': space,
        'local': _local,
        'desc': cdesc,
        'tool_api_code': tool_api_code,
        'artifact_au': artifact_au,
        'artifact_print_name': artifact_print_name,
    }
