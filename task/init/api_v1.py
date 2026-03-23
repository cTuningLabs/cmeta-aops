from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    ############################################################
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        return {'return':0}

    ############################################################
    def run(self,
            ctx: dict,              # cMeta context
            default_cache_repo: str = None,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        # It just stores init config

        result = {'return':0}

        if default_cache_repo:
            result[default_cache_repo] = default_cache_repo

        return result
