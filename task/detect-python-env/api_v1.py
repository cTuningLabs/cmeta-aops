"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform
import sys
import struct
import copy

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,              # cMeta context
            python_path: str = None
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if python_path and not os.path.isfile(python_path):
            return self.cm.error(f'path "{python_path}" not found')

        result = {'return':0}

        is_windows = platform.system() == "Windows"

        is_virtual = False

        path_bin = os.path.dirname(python_path)
        path_root = os.path.dirname(path_bin)

        if is_windows:
            candidates = [
              'Scripts\\activate.bat', 
              'condabin\\conda.bat',
            ]
        else:
            candidates = [
              'bin/activate', 
              'condabin/conda',
            ]

        for candidate in candidates:
            path = os.path.join(path_root, candidate)
            if os.path.isfile(path):
                is_virtual = True

                env_path = path_root
                script_path = path

                break

        result['is_virtual'] = is_virtual

        result['python_path'] = python_path

        if is_virtual:
            result['env_path'] = env_path
            result['script_path'] = script_path

        return result

