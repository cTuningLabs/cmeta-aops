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
            path_target = os.path.dirname(path_bin)
            path_home = os.path.dirname(path_target)

            _paths = {
               'bin': path_bin,
               'qbin': self.cm.q(path_bin),

               'target': path_target,
               'qtarget': self.cm.q(path_target),

               'home': path_home,
               'qhome': self.cm.q(path_home),
            }

            features_paths = features.setdefault('paths',{})
            features_paths.update(_paths)

            new_paths.append(p)

        return {'return':0, 'paths':new_paths}

