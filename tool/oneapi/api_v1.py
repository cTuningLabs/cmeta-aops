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
    def update_paths(self,
                     ctx: dict,
                     paths: dict,
                     params: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL oneapi api_v1 update_paths")

        new_paths = []

        for path in paths:
            if 'common' not in path and 'latest' not in path:
                new_paths.append(path)

        return {'return':0, 'paths':new_paths}

