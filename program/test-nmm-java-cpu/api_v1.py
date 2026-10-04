"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

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
        With a JDK vendor (--jdk), the compiler step does not use its cache: a cached compiler entry
        would also match the runs without --jdk (an entry matches every request whose parameters
        it contains), which keep the cached compiler of the installed JDK.
        """
        local = ctx['tasks']['local']
        if local.get('params', {}).get('jdk'):
            local['compiler_cache'] = False
        return {'return': 0}

# Can be used for more complex workflow logic

