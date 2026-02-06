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

        results = state['tasks']['results']

        path_repo1 = results['test-dummy3-clone-git-repo']['path_to_git_repo']
        path_repo2 = results['test-dummy3-clone-git-repo2']['path_to_git_repo']
        path_repo3 = results['test-dummy3-clone-git-repo3']['path_to_git_repo']

        result = {'return':0,
                  'path_repo1': path_repo1,
                  'path_repo2': path_repo2,
                  'path_repo3': path_repo3,
        }

        return result
