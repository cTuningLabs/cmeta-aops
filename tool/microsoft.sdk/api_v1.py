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
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL microsoft.sdk api_v1 detect_versions")

        from pathlib import Path

        found_paths_with_versions = {}

        for path in paths:
            parts = Path(path).parts
            version = parts[parts.index("Include") + 1]

            found_paths_with_versions[path] = {'output':version}

        return {'return':0, 'found_paths_with_versions':found_paths_with_versions}

