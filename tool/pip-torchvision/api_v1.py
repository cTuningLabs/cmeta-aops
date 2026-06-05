"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params2(self,
                      ctx: dict,
                      params: dict,
                      cparams: dict,
    ):
        """
        """

        # Check torch version (if installed) to calculate compatible torchvision version!
        if 'version' not in params:

            torch = ctx['tasks']['global'].get('pip-torch')
            if torch:
                version = torch['version'].split('.')

                version1 = int(version[0])
                version2 = int(version[1])

                xversion = None
                if version1 >=1 and version1 <2:
                    xversion = version2 + 1
                elif version1 >=2 and version1 <3:
                    xversion = version2 + 15

                if xversion:
                    xversion = '0.' + str(xversion)

                    if len(version)>2:
                        version3 = version[2]
                        j = version3.find('+')
                        if j>0:
                            version3 = version3[:j]
                        version3 = int(version3)
                        xversion += '.' + str(version3)

                    params['version'] = xversion

        # Call function in tool::pip / api_v1.py
        return self.task_setup_tool_code._common_compute_init(
            ctx, 
            params, 
            skip_extras = True,
            cuda_vers = ['13.0', '12.9', '12.8', '12.6', '12.4', '12.1', '11.8'],
        )
