import os

from task_c36be4b9314a45e0.api.v1 import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self, state, url=None):
        """
        """

        self.logger.debug("RUNNING API v1 XYZ test_")

        print (f'url={url}')

        return {'return':0}
