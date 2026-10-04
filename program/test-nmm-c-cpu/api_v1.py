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
    def customize2(self,
                   ctx: dict,
                   **misc
    ):
        """
        The C math library for sqrt() on Linux, where libm is separate: -lm after the sources (the
        Android build gets it from lib-sysroot-android; macOS and Windows have it in the C run time).
        Without it the dynamic build links only with the optimizations that turn sqrt() into an
        instruction (--compile.fastest); a static build gets -lm from lib-openssl's static libraries.
        """

        compute = ctx['tasks']['global']['target']['compute']
        uname = ctx['tasks']['global']['host']['os']['uname']

        if uname == 'linux' and 'cpu' in compute and not any(c.startswith('android') for c in compute):
            _compile = ctx['tasks']['local']['params'].setdefault('compile', {})
            lib_names = _compile.setdefault('lib_names', [])
            if 'm' not in lib_names:
                lib_names.append('m')

        return {'return':0}
