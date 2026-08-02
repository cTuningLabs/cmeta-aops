"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL huggingface_cli api_v1 check_params")

        result = {'return':0}

        python_path_bin = ctx['tasks']['global']['python']['path_bin']

        huggingface_cli_path = os.path.join(python_path_bin, 'hf' + ctx['tasks']['global']['host']['vars']['file_ext_exe'])

        params['tool_path'] = huggingface_cli_path

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _with = params.get('with',{})

        _result = {'return':0}

        path_file_cache_list = ctx['tasks'].get('global', {}).get('init', {}).get('hf',{}).get('cache')
        if path_file_cache_list:
            path_file_cache = None

            for x in path_file_cache_list.split(os.pathsep):
                if os.path.isdir(x):
                    path_file_cache = x
                    break
                else:
                    try:
                       os.makedirs(x, exist_ok=True)
                       path_file_cache = x
                       break
                    except:
                       pass

            if path_file_cache:
                _aggregate = result.setdefault('_aggregate', {})
                _aggregate_env = _aggregate.setdefault('env',{})

                _aggregate_env['HF_HOME'] = path_file_cache

                _result['result'] = result

        return _result
