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
            env: dict = {},
    ):

        """
        Test dummy3.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK test-python run")

        con = state['control'].get('con', False)
        verbose = state['control'].get('verbose', False)

        space = '  ' * state['tasks']['nested_call']

        _global = state['tasks']['global']
        _aggregated = state['tasks']['aggregated']

        result = {'return':0}
        





        os_env = _global['host']['os_env']


        envs = _aggregated['env']


        print (envs)
        print (env)

        cmd = 'python --version'
        result['cmd'] = cmd

        r = self.cm.utils.sys.run(cmd, env = env, envs = envs, genv = {}, os_env = os_env, 
                                  con = con, verbose = verbose, space = space)
        if r['return']>0: return r

        rc = r['returncode']
        
        print (rc)


        return result
