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
    def run(self,
            ctx: dict,              # cMeta context
            mkdir: str = None,
            chdir: str = None,
            files: str = None,
            ask: bool = None,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        result = {'return':0}

        files = [] if files is None else files
        if type(files) == str:
            files = files.split(',')

        cur_dir = os.getcwd()

        if mkdir:
            if con and verbose:
                print ('')
                print (f'{space}INFO: mkdir -p "{chdir}"')

            os.makedirs(mkdir, exist_ok=True)

        if chdir:
            if con and verbose:
                print ('')
                print (f'{space}INFO: cd "{chdir}"')

            os.chdir(chdir)


        for _file in files:
            if con:
                x = ' -f' if not ask else ''
                print (f'{space}INFO: rm{x} "{_file}"')

            if not os.path.isfile(_file):
                continue

            delete = True
            if ask and not quiet:
                x = input(f'{space}        Would you like to delete "{_file}" (Y/n)? ').strip().lower()
                if x in ['n', 'no']:
                    delete = False

            if delete:
                if os.path.isfile(_file):
                    os.remove(_file)
            elif con:
                print    (f'{space}          Skipped!')
                
        result['files'] = files

        return result
