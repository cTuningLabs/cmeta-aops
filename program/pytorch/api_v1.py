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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)


    ############################################################
    def customize1(self,
                   ctx: dict,
                   **misc
    ):
        params = misc.get('params', {})

        # Allow the caller to override which Python source files to run
        run_src = params.get('run_src_file_names')
        if run_src:
            if isinstance(run_src, str):
                run_src = [run_src]
            ctx['tasks']['local']['run_src_file_names'] = run_src

        return {'return': 0}
