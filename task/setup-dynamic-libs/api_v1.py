"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import shutil

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self, 
            ctx, 
            **params,
    ):
        """
        """

        result = {'return':0}

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        dynamic_lib_paths = params.get('dynamic_lib_paths', []) # For run-time

        found_dynamic_libs = []
        found_dynamic_lib_paths = []

        for k in ctx['tasks']['global']:
            if k.startswith('lib-'):
                features = ctx['tasks']['global'][k].get('features',{})

                if 'found_dynamic_libs' in features['paths']:
                    for l in features['paths']['found_dynamic_libs']:
                        if l not in found_dynamic_libs:
                            found_dynamic_libs.append(l)

                # Should be here even if static (since libraries may have been compiled as dynamic
                # and not have static libs)
                if 'found_dynamic_lib_paths' in features['paths']:
                    for l in features['paths']['found_dynamic_lib_paths']:
                        if l not in found_dynamic_lib_paths:
                            found_dynamic_lib_paths.append(l)

        if found_dynamic_libs:
            result['found_dynamic_libs'] = found_dynamic_libs

        if found_dynamic_lib_paths:
            result['found_dynamic_lib_paths'] = found_dynamic_lib_paths

        return result

