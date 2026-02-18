import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     state: dict,
                     params: dict = {},
    ):
        r = self.cm._check_params(params, [], __name__)
        if r['return']>0: return self.cm._error2(r, self.cm)

        return {'return':0}

    ############################################################
    def run(self,
            state: dict,        # cMeta state
    ):

        """
        Clone git repo.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK clone-git-repo run")

        con = state['control'].get('con', False)
        verbose = state['control'].get('verbose', False)

        space = '  ' * state['tasks']['nested_call']
        clean = state['tasks']['control'].get('clean', False)
        update = state['tasks']['control'].get('update', False)

        _params = {}

        _global = state['tasks']['global']

        result = {'return':0}

        path_to_check_file = _global['download-file--min-win-tools']['path_to_check_file']

        path_to_bin = os.path.dirname(path_to_check_file)

        env = {'+PATH':[path_to_bin]}

        result['path_to_bin'] = path_to_bin

        result['_aggregate'] = {'env':env}
        
        return result
