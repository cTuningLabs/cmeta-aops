import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            env: dict = {},
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.cm.utils.files.write_file('tmp-ctx.json', ctx)

        self.logger.debug("RUNNING TASK test-dummy3 run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        ctx_tasks_control = ctx['tasks']['run_control']

        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        nvcc = ctx['tasks']['global']['nvcc']

        if not os.path.isdir('tmp'):
            os.makedirs('tmp')

        src_file = os.path.join(task_path, 'src', 'list_devices.cu')

        cmds = [nvcc['qpath'] + f' {src_file} -o tmp/list_devices', 'tmp\list_devices.exe']

        for cmd in cmds:
            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'con': con, 
                  'verbose': verbose, 
                  'text_cmd': 'RUN:',
#                  'print_env_keys': ['PATH'],
                  'print_extra_line': True,
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']
            if returncode>0:
                return {'return':99, 'error': f'cmd "{cmd}" failed with return code "{returncode}"'}


        return result
