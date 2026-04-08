"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
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
        directory = params.get('directory')
 
        if not filename:
            return self.cm.error(f'filename is not defined ("{__file__})"')

        if os.path.isfile(filename):
            return self.cm.error(f'file "{filename}" already exists ("{__file__}")')

        if not directory:
            return self.cm.error(f'directory is not defined ("{__file__}")')

        if not os.path.isdir(directory):
            return self.cm.error(f'directory "{directory}" doesn\'t exist  not defined in "{__file__}"')

        return result

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            filename: str = None,
            directory: str = None,
            skip_dirs: list = None,  # directories to skip from zipping
            skip_files: list = None,  # files to skip from zipping
    ):

        """
        Untar file.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK zip run api_v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        uname = ctx['tasks']['global']['host']['os']['uname']

        _local = {}

        zip_path = os.path.abspath(filename)

        # Zip the directory
        r = self.cm.utils.files.zip_directory(
            directory,
            zip_path,
            skip_directories = skip_dirs,
            skip_files = skip_files,
        )
        if r['return']>0: return r

        if con:
            print(f'Directory successfully zipped to "{zip_path}"')

        qpath = self.cm.utils.files.quote_path(zip_path)

        filesize = os.path.getsize(zip_path)

        return {'return':0, 'path':zip_path, 'qpath':qpath, 'zip_file_size':filesize}
