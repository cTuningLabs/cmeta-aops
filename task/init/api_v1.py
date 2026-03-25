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
        It just stores init config

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        result = {'return':0}

        # Check in config::task
        r = self.cm.access({
          'category':'config,cc6bfe174be847ed', 
          'command':'get', 
          'arg1':'task',
        })
        if self.cm.catch_error(r): return r

        cfg = r['config_cmeta']
        if cfg:
            result.update(cfg)

        # Update from API/CLI
        if default_cache_repo:
            result[default_cache_repo] = default_cache_repo

        return result
