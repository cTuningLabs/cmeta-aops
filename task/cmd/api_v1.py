import os
import platform

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            cmd: str = "",
            env: dict = {},
            genv: dict = {},
            timeout: int = None,
            capture_output: bool = False,
            capture_env: bool = False,
            fail_if_nonzero_return_code: bool = True,
            text_cmd: str = 'RUN:',
            print_env_keys: list = None,
            print_extra_line: bool = False,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


        """

        self.logger.debug("RUNNING TASK run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call']

        _global = ctx['tasks']['global']
        _aggregated = ctx['tasks']['aggregated']

        os_env = _global['host']['os_env']

        envs = _aggregated.get('env', {})

        result = self.cm.utils.sys.run(cmd, 
                                       env = env, 
                                       envs = envs, 
                                       genv = genv, 
                                       os_env = os_env,
                                       timeout = timeout, 
                                       capture_output = capture_output,
                                       capture_env = capture_env,
                                       con = con, 
                                       verbose = verbose, 
                                       text_cmd = text_cmd, 
                                       space = space,
                                       print_env_keys = print_env_keys,
                                       print_extra_line = print_extra_line,
        )
        if self.cm.catch_error(result): return result

        returncode = result['returncode']

        result['env'] = env
        result['cmd'] = cmd

        if fail_if_nonzero_return_code and returncode>0:
            return self.cm.error(f'CMD "{cmd}" failed with return code {returncode}', 99)

        return result
