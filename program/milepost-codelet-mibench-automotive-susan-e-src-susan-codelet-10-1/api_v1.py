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
        """

        desc = misc.get('desc', {})

        compute = ctx['tasks']['global']['target']['compute']
        uname = ctx['tasks']['global']['host']['os']['uname']

        if 'cuda' in compute:
            ctx['tasks']['local']['src_dir'] = 'src-cuda'
            ctx['tasks']['local']['src_file_names'] = ['gemm.cu']
            ctx['tasks']['local']['lang'] = 'cuda'

#            r = self.cm.access({'category': 'program,22788f3c30d04e6d',
#                                'command': 'update_desc',
#                                'desc': desc,
#                                'updates': desc['updates_cuda']})
#            if self.cm.catch_error(r): return r

        return {'return':0}

