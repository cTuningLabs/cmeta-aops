"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    Clone the MLPerf Inference Endpoints benchmark source (mlcommons/endpoints) into the cache
    through clone-git-to-cache and return where it landed.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx,
            **params,
    ):
        """
        """

        _global = ctx['tasks']['global']

        # the storage key clone-git-to-cache uses for this clone (its "name" param)
        result_from_git = _global['clone-git-to-cache-src-mlperf-endpoints']

        path = result_from_git['path_to_git_repo']
        qpath = self.cm.q(path)

        result = {'return':0, 'path': path, 'qpath': qpath, 'result_from_git': result_from_git}

        for k in ['checkout', 'checkout_short', 'url']:
            if k in result_from_git:
                result[k] = result_from_git[k]

        return result
