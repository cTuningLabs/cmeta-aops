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
            # The first place of the Hugging Face cache that is there, by the rule of the file cache: a drive that is
            # away is passed over and the run says so; none there stops it (file_cache_folder of the task category)
            from task_c36be4b9314a45e0.api.ctask import file_cache_folder

            r = file_cache_folder(path_file_cache_list, key = 'hf.cache',
                                  con = ctx.get('control', {}).get('con', False))
            if r['return'] > 0:
                return self.cm.error(r['error'])

            _aggregate = result.setdefault('_aggregate', {})
            _aggregate_env = _aggregate.setdefault('env',{})

            _aggregate_env['HF_HOME'] = r['path']

            _result['result'] = result

        return _result
