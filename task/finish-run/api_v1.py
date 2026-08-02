"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform

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
        """

        return {'return':0}

    ############################################################
    def run(self, 
            ctx, 
            **params,
    ):
        """
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        result = {'return':0}

        chdir = params.get('chdir')

        if chdir:
            work_dir = chdir
        else:
            work_dir = os.getcwd()

        result_files = params.get('result_files', [])
        result_files_data = {}

        if result_files:
            for k in result_files:
                f = result_files[k]

                path = os.path.join(work_dir, f)

                r = self.cm.utils.files.read_file(path)
                if self.cm.catch_error(r, fail16=True): return r

                result_files_data[k] = r['data']

        if result_files_data:
            result['add_to_local'] = {'result_files_data': result_files_data}

        print_files = params.get('print_files', [])
        print_line = params.get('print_line', False)

        if print_files:
            for f in print_files:
                path = os.path.join(work_dir, f)

                print ('')
                x = f'{space}' if verbose else ''
                print (f'{x}INFO: print file "{f}":')
                print ('')
                r = self.cm.utils.files.read_file(path)
                if self.cm.catch_error(r, fail16=True): return r

                if print_line:
                    print ('*'*80)
                print (r['data'])
                if print_line:
                    print ('*'*80)
                else:
                    print ('')

        return result

