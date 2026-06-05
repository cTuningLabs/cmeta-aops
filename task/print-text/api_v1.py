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
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        extra_line = params.get('extra_line')
        use_space = params.get('use_space')
        press_enter = params.get('press_enter')
        skip_enter = params.get('skip_enter')
        force_ask = params.get('force_ask')

        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''


        text = params.get('text')
        if con and text:
            if extra_line:
                print ('')

            x = space + text if use_space else text

            print (x)

        if force_ask or (not quiet and not skip_enter):
            print ('')

            text2 = params.get('text2')
            if not text2:
                text2 = 'Press Enter to continue:'

            x = space + text2 if use_space else text2

            input(x)


        return {'return': 0, 'text': text}


