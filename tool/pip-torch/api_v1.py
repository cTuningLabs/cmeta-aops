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

        # Call function in tool::pip / api_v1.py
        return self.task_setup_tool_code._common_compute_init(
            ctx, 
            params, 
            skip_extras = True,
            cuda_vers = ['13.0', '12.9', '12.8', '12.6', '12.4', '12.1', '11.8'],
        )

