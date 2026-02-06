import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            state: dict,        # cMeta state
    ):

        """
        Test dummy3.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK test-dummy3 run")

        con = state['control'].get('con', False)
        verbose = state['control'].get('verbose', False)

        space = '  ' * state['tasks']['nested_call']

        _params = {}

        state_results = state['tasks']['results']

        result_host = state_results['host']
        result_python = state_results['python']

        print (result_host)
        print (result_python)

        ENV = result_host['ENV']

        tool_python_exe_path = result_python['tool_python_exe_path']

        cmd = tool_python_exe_path + ' --version'

        default_env = {}

        r = self.cm.utils.sys.run(cmd, env=ENV, envs=default_env, con=con, verbose=verbose)
        if r['return']>0: return r

        rc = r['returncode']
        
        print (rc)

        result = {'return':0}

        return result
