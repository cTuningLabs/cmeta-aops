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

        features = ctx['tasks']['global']['cuda']['features']

        result = {
          'return':0,
          'features': features,
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

        # A cached target keeps the features of the run that created the entry, possibly on another
        # machine (a copied or shared CMETA_HOME) or before a GPU or driver change. The cuda tool
        # was set up again in this call ('uses'), so its features describe this machine now.
        tool_features = ctx['tasks']['global'].get('cuda', {}).get('features')
        if tool_features:
            result['features'] = copy.deepcopy(tool_features)

        _with = params.get('with', {})

        ver = _with.get('ver')

        if ver:
            result['features']['ver'] = ver

        _result['result'] = result

        return _result
