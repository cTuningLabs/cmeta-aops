"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import shlex

from program_22788f3c30d04e6d.api.cprogram import InitCProgram

class CProgram(InitCProgram):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize1(self,
                   ctx: dict,
                   **misc
    ):
        """
        """

        desc = misc.get('desc', {})
        params = misc.get('params', {})

        compute = ctx['tasks']['global']['target']['compute']
        uname = ctx['tasks']['global']['host']['os']['uname']

        model = params.get('model')
        prompt = params.get('prompt')

        if model or prompt:
            _use = ctx['tasks'].setdefault('use', {})
            if model:
                _use.setdefault('model',{})['filename'] = os.path.abspath(model)
            if prompt:
                _use.setdefault('dataset',{})['filename'] = os.path.abspath(prompt)

        return {'return':0}
