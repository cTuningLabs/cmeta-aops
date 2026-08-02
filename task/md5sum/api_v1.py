"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        result = {'return':0}

        filename = params.get('filename')
 
        if not filename:
            return self.cm.error(f'filename is not defined in "{__file__}" ({__name__})')

        if not os.path.isfile(filename):
            return self.cm.error(f'filename "{filename}" not found in "{__file__}" ({__name__})')

        return result


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            filename: str = None,
            chunk_size: int = None,
    ):

        """
        md5sum file.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK md5sum run api_v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        uname = ctx['tasks']['global']['host']['os']['uname']

        _local = {}

        if chunk_size:
            if type(chunk_size) == str:
                chunk_size = int(chunk_size)
        else:
            chunk_size = 100000

        result = self.cm.utils.files.md5sum(filename, chunk_size)
        if self.cm.catch_error(result): return result

        md5sum = result['md5sum']

        if con:
            print (f'{md5sum} *{filename}')

        return result

