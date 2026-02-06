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
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


                  os: ['Windows', 'Linux', 'macOS']
        """

        con = state['control'].get('con', False)
        verbose = state['control'].get('verbose', False)

        space = '  ' * state['tasks']['nested_call']

        _params = {}

        result = {'return':0}

        os_name = platform.system()

        if os_name.lower() == 'darwin':
            os_name = 'macOS'

        result['os'] = os_name

        return result
