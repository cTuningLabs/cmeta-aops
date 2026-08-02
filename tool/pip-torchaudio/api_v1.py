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

        # Check torch version (if installed) to set compatible torchaudio version.
        if 'version' not in params:

            torch = ctx['tasks']['global'].get('pip-torch')
            if torch:
                torch_version = torch['version']

                # Strip any pre-release / local suffix (e.g. "2.12.0a0+git0d62256" → "2.12.0").
                # Complex versions can't be matched by pip, and torchvision/audio deps would
                # cause pip to reinstall a stable torch over our source build.
                m = re.match(r'^(\d+(?:\.\d+)*)', torch_version)
                version = m.group(1) if m else torch_version
                params['version'] = version

                # If the version had non-numeric extras, add --no-deps so pip doesn't
                # try to resolve (and reinstall) torch as a torchaudio dependency.
                if version != torch_version:
                    _with = params.setdefault('with', {})
                    pf = _with.get('post_flags', '')
                    if '--no-deps' not in pf:
                        _with['post_flags'] = ('--no-deps ' + pf).strip()

        # Call function in tool::pip / api_v1.py
        return self.task_setup_tool_code._common_compute_init(
            ctx, 
            params, 
            skip_extras = True,
            cuda_vers = ['13.0', '12.9', '12.8', '12.6', '12.4', '12.1', '11.8'],
        )
