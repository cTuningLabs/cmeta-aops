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

        result = {'return':0}

        ######################################################################
        os_name = platform.system()

        result['platform_system'] = os_name
        result['platform_system_lower'] = os_name.lower()

        if os_name.lower() == 'darwin':
            os_name = 'macOS'

        result['os'] = os_name
        result['os_lower'] = os_name.lower()

        return result
