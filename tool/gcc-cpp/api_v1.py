"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
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
        path_to_gcc = ctx['tasks']['global']['gcc']['path']

        found_paths = []

        j = path_to_gcc.rfind('gcc')
        if j>0:
            path_to_gcc_cpp = path_to_gcc[:j] + 'g++' + path_to_gcc[j+3:]
            if os.path.isfile(path_to_gcc_cpp):
                found_paths.append(path_to_gcc_cpp)

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

        for p in paths:
            # Parsing standard output
            features = p.setdefault('features', {})

            path_tool = p['path']
            path_bin = os.path.dirname(path_tool)

            path_tool_lib = os.path.join(path_bin, 'ar')
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

