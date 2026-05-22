"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform

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
        """

        return {'return':0}

    ############################################################
    def run(self, 
            ctx, 
            **params,
    ):
        """
        """

        result = {'return':0}

        chdir = params.get('chdir')

        if chdir:
            work_dir = chdir
        else:
            work_dir = os.getcwd()

        result_files = params.get('result_files', [])
        result_files_data = {}

        if result_files:
            for k in result_files:
                f = result_files[k]

                path = os.path.join(work_dir, f)

                r = self.cm.utils.files.read_file(path)
                if self.cm.catch_error(r, fail16=True): return r

                result_files_data[k] = r['data']

        if result_files_data:
            result['add_to_local'] = {'result_files_data': result_files_data}

        return result
