"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import copy

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


                  os: ['Windows', 'Linux', 'macOS']
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if 'rocm' not in ctx['tasks']['global']:
            return self.cm.error(f'ROCm target not found in "{__file__}" ({__name__})')

        result = {
          'return':0,
          'features': ctx['tasks']['global']['rocm']['features'],
        }

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _result = {'return':0}

        _with = params.get('with', {})

        ver = _with.get('ver')

        if ver:
            result['features']['ver'] = ver

        _result['result'] = result

        return _result
