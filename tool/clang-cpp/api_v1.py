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
        file_ext_exe = '.exe' if uname == 'windows' else ''

        for p in paths:
            # Parsing standard output
            features = p.setdefault('features', {})

            path_tool = p['path']
            path_bin = os.path.dirname(path_tool)

            path_tool_lib = os.path.join(path_bin, f'llvm-ar{file_ext_exe}')
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
