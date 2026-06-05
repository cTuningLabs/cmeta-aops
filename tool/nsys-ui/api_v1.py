"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        Mostly used to update storage_key
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL nsys-ui api_v1 init")

        result = {'return':0}

        return result

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL nsys-ui api_v1 check_params")

        result = {'return':0}

        nsys_path = ctx['tasks']['global']['nsys']['path']

        nsys_path2 = os.path.dirname(nsys_path)

        nsys_path3 = os.path.dirname(nsys_path2)

        # Search
        cur_dir = os.path.join(nsys_path3, '**')

        ii = {'category': 'tool,c393ba5c6fa14f66',
              'command': 'find_path',
              'paths': [cur_dir],
              'ctx': ctx,
              'context': ctx['tasks'],
              'desc': self.cdesc,
              'con': True,
              'verbose': True,
        }

        r = self.cm.access(ii)
        if self.cm.catch_error(r): return r

        found_paths = r.get('found_paths', [])
        if found_paths:
            params['tool_path'] = found_paths[0]
        else:
            return self.cm.error(f'nsys-ui not found in "{cur_dir}"')

        return result

