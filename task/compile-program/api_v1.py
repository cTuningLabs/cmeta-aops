"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            name: str = None,
            program_tags: str = None,
            program_api_ver: str = None,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK compile-program run")

        result = {'return':0}

        selected_program = ctx['tasks']['global']['select-program']


        return result

