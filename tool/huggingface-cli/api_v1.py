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
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL huggingface_cli api_v1 check_params")

        result = {'return':0}

        python_path_bin = ctx['tasks']['global']['python']['path_bin']

        huggingface_cli_path = os.path.join(python_path_bin, 'huggingface-cli' + ctx['tasks']['global']['host']['vars']['file_ext_exe'])

        params['tool_path'] = huggingface_cli_path

        return result
