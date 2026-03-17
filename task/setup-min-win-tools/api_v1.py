import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
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
        r = self.cm.check_params(params, [], __name__)
        if self.cm.catch_error(r): return r

        return {'return':0}

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
    ):

        """
        Clone git repo.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK clone-git-repo run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        _params = {}

        _global = ctx['tasks']['global']

        result = {'return':0}

        path_to_check_file = _global['download-file--min-win-tools']['path_to_check_file']

        path_to_bin = os.path.dirname(path_to_check_file)

        env = {'+PATH':[path_to_bin]}

        result['path_to_bin'] = path_to_bin

        result['_aggregate'] = {'env':env}
        
        return result
