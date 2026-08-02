"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import shutil

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict,
                     cparams: dict,
    ):
        """
        """

        version = params.get('version')
        if not version:
            version = '6.0'

        url = params.get('url')
        if not url:
            url = f'https://github.com/mlcommons/inference_results_v{version}'

        extra_tags = params.get('extra_tags')
        if not extra_tags:
            params['extra_tags'] = 'mlcommons'

        ctx['tasks']['local']['url'] = url
        ctx['tasks']['local']['version'] = version
       
        return {'return':0}

    ############################################################
    def run(self, 
            ctx, 
            **params,
    ):
        """
        """

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        version = _local['version']
        version2 = _local['version'].replace('.', '-')

        key = 'clone-git-to-cache-src-mlperf-inference'

        result_from_git = _global[key]

        path = result_from_git['path_to_git_repo']
        qpath = self.cm.q(path)

        result = {'return':0, 'path': path, 'qpath': qpath, 'result_from_git': result_from_git, 'version': version}

        for k in ['checkout', 'checkout_short', 'url']:
            if k in result_from_git:
                result[k] = result_from_git[k]

        return result
