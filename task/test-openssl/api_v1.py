"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def set_vars(self,
                 ctx: dict,        # cMeta context
                 desc: dict = {},
                 **params,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']

        uparams = params.get('uparams', {})

        _static = uparams.get('static')
        _dynamic = False if _static else True

        _add_debug = uparams.get('add_debug', False)

        if _dynamic:
            key = 'dynamic_build'
        else:
            key = 'static_build'

        if _add_debug:
            key += '_debug'

        build_type_flag = _global['compiler']['features']['flags'].get(key, '')

        _local['build_type_flag'] = build_type_flag

        return {'return':0}
