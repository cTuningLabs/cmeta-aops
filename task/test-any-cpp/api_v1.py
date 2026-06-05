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
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize storage_key and cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        r = self.cm.check_params(params, [
                'flags', 
            ], __name__)
        if self.cm.catch_error(r): return r

        flags = params.get('flags')

        ctx['tasks']['local']['flags'] = flags

        return {'return':0}

