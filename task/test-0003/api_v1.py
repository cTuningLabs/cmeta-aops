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
            flag1 = None,
    ):

        """
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

        _global = state['tasks']['global']
        _local = state['tasks']['local']

        path_repo1 = _local['test-0003-clone-git']['path_to_git_repo']
        path_repo2 = _local['test-0003-clone-git2']['path_to_git_repo']
        path_repo3 = _local['test-0003-clone-git3']['path_to_git_repo']

        print (flag1)

        if con:
            print ('')
            print ('Test passed!')

        result = {'return':0,
                  'path_repo1': path_repo1,
                  'path_repo2': path_repo2,
                  'path_repo3': path_repo3,
        }

        return result
