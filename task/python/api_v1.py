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
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call']

        _params = {}

        ctx_results = ctx['tasks']['results']
        result_host = ctx_results['host']

        print (result_host)


        ENV = result_host.setdefault('ENV', {})
        PATH = ENV.setdefault('+PATH', [])
        
        PATH.append('C:\\!Progs\\Python3.9.13')
        PATH.append('C:\\!Progs\\Python3.9.13')

        result = {'return':0}

        result['tool_python_exe_path'] = 'C:\\!Progs\\Python3.9.13\\python.exe'

        return result
