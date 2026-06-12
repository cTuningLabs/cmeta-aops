"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
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

#        if 'cuda' in compute:
#            ctx['tasks']['local']['src_dir'] = 'src-cuda'
#            ctx['tasks']['local']['run_src_file_names'] = ['program-cuda.py']

        return {'return':0}
