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
    def find_paths(self,
                   ctx: dict,
                   params: dict = {},
    ):
        """
        """
        path_to_tool = ctx['tasks']['global']['clang']['path']

        found_paths = []

        j = path_to_tool.rfind('clang')
        if j>0:
            path_to_tool2 = path_to_tool[:j] + 'clang++' + path_to_tool[j+5:]

            if os.path.isfile(path_to_tool2):
                found_paths.append(path_to_tool2)

        return {'return':0, 'found_paths':found_paths}
