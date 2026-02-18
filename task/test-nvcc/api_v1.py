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
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.cm.utils.files.write_file('tmp-state.json', state)

        self.logger.debug("RUNNING TASK test-dummy3 run")

        con = state['control'].get('con', False)
        verbose = state['control'].get('verbose', False)

        space = '  ' * state['tasks']['nested_call']

        result = {'return':0}

        nvcc = state['tasks']['global']['setup-tool--nvcc']

        if not os.path.isdir('tmp'):
            os.makedirs('tmp')

        cmds = ['"'+nvcc['path']+'"' + ' src/list_devices.cu -o tmp/list_devices',
                'tmp\list_devices.exe']

        for cmd in cmds:
            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'run',
                  'state': state,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'con': con, 
                  'verbose': verbose, 
                  'text_cmd': 'RUN:',
                  'print_env_keys': ['PATH'],
                  'print_extra_line': True,
            }

            rx = self.cm.access(ii)
            if rx['return']>0: return self.cm._error2(rx, self.cm)

            returncode = rx['returncode']
            if returncode>0:
                return {'return':99, 'error': f'cmd "{cmd}" failed with return code "{returncode}"'}


        return result
