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
        path_to_tool = ctx['tasks']['global']['icx']['path']

        found_paths = []

        j = path_to_tool.rfind('icx')
        if j>0:
            path_to_tool2 = path_to_tool[:j] + 'icpx' + path_to_tool[j+3:]

            if os.path.isfile(path_to_tool2):
                found_paths.append(path_to_tool2)

        return {'return':0, 'found_paths':found_paths}


    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        new_paths = []

        uname = ctx['tasks']['global']['host']['os']['uname']

        for p in paths:
            # Parsing standard output
            features = p.setdefault('features', {})

            path_tool = p['path']
            path_bin = os.path.dirname(path_tool)

            # Windows: llvm-lib.exe (MSVC-compatible, /OUT: syntax)
            # Linux:   llvm-ar (rcs syntax)
            # Both live in the 'compiler' subdirectory of the icpx bin dir
            if uname == 'windows':
                lib_name = 'llvm-lib.exe'
            else:
                lib_name = 'llvm-ar'

            path_tool_lib = os.path.join(path_bin, 'compiler', lib_name)
            if not os.path.isfile(path_tool_lib):
                return self.cm.error(f'library sub-tool not found in "{path_tool_lib}"')

            _paths = {
               'bin': path_bin,
               'tool_lib': path_tool_lib,
               'qtool_lib': self.cm.q(path_tool_lib),
            }

            features_paths = features.setdefault('paths',{})
            features_paths.update(_paths)

            new_paths.append(p)

        return {'return':0, 'paths':new_paths}
