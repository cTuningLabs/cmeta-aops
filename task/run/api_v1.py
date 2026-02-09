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
            state: dict,        # cMeta state
            cmd: str = "",
            env: dict = {},
            timeout: int = 10,
            capture_output: bool = False,
            fail_if_nonzero_return_code: bool = True,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


        """

        con = state['control'].get('con', False)
        verbose = state['control'].get('verbose', False)

        space = '  ' * state['tasks']['nested_call']

        result = {'return':0}

        ######################################################################
        global_env = state['tasks']['global']['host']['env']

        result = self.cm.utils.sys.run(cmd, env = env, genv = global_env, timeout = timeout, capture_output = capture_output,
                                  con = con, verbose = verbose, text_cmd = 'RUN', space = space)
        if result['return']>0: return self.cm._error2(result, self.cm)

        returncode = result['returncode']

        if fail_if_nonzero_return_code and returncode>0:
            err = f'CMD "{cmd}" failed with return code {returncode}'
            return self.cm._error(err, 99, None, self.cm.fail_on_error)

        return result
