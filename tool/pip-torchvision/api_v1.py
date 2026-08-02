"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import re

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
                torch_version = torch['version']
                version = torch_version.split('.')

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

                        m = re.match(r'(\d+)', version3)
                        version3 = int(m.group(1))
                        xversion += '.' + str(version3)

                    params['version'] = xversion

                # Complex version (alpha/dev/local build, e.g. "2.12.0a0+git0d62256"):
                # pip would try to reinstall a stable torch to satisfy torchvision's dep.
                # --no-deps prevents that so our source-built torch is left untouched.
                if re.search(r'\+|a\d|b\d|rc\d|\.dev\d|\.post\d', torch_version):
                    _with = params.setdefault('with', {})
                    pf = _with.get('post_flags', '')
                    if '--no-deps' not in pf:
                        _with['post_flags'] = ('--no-deps ' + pf).strip()

        # Call function in tool::pip / api_v1.py
        return self.task_setup_tool_code._common_compute_init(
            ctx, 
            params, 
            skip_extras = True,
            cuda_vers = ['13.2', '13.0', '12.9', '12.8', '12.6', '12.4', '12.1', '11.8'],
        )
