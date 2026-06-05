"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform
import shutil

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self, 
            ctx, 
            name: str = None,
            dataset_tags: str = None,
            filename: str = None,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK dataset run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        result = {'return':0}

        _global = ctx_tasks['global']


        if filename and os.path.isfile(filename):
            path = filename

        else:
            p = {'category': self.cmeta['uses_categories']['utils'],
                 'command': 'select_artifact',
                 'select_category': self.cmeta['uses_categories']['dataset'],
                 'select_artifact': name,
                 'select_tags': dataset_tags,
                 'con': con,
                 'quiet': quiet,
                 'load_files': ['_desc'],
                 'space': space,
                 'print_extra_line': True,
            }

            r = self.cm.access(p)
            if self.cm.catch_error(r, fail16=True): 
                r['return'] = 1 # Force fail if dataset not found
                return r

            artifact = r['artifact']
            artifact_path = artifact['path']
            artifact_au = r['artifact_au']
            loaded_files = r['loaded_files']

            if con and verbose:
                print ('')
                print (f'{space}INFO: Selected dataset "{artifact_au}"')

            # Check files
            path_to_files = os.path.join(artifact_path, 'files')
            files = []

            if not os.path.isdir(path_to_files):
                return self.cm.error(f'dataset files not found in "{path_to_files}" ("{__file__}")')

            fs = os.listdir(path_to_files)
            if len(fs) == 0:
                return self.cm.error(f'dataset files not found in "{path_to_files}" ("{__file__}")')

            if filename:
                if filename not in fs:
                    return self.cm.error(f'dataset file "{filename}" not found in "{path_to_files}" ("{__file__}")')
    
                path = os.path.join(path_to_files, filename)
            else:
                fs = sorted(fs)
                ifs = 0

                if len(fs) > 1 and con and not quiet:
                    print ('')
                    print (f'{space}Available dataset files:')

                    print ('')
                    for n in range(0, len(fs)):
                        x = fs[n]
                        print (f'{space}{n}) {x}')
                    print ('')

                    while True:
                        x = input('Please select a dataset file or press Enter for 0: ').strip()

                        if x == "":
                            ifs = 0
                            break

                        if x.isdigit() and int(x)>=0 and int(x)<len(fs):
                            ifs = int(x)
                            break

                    print ('')

                path = os.path.join(path_to_files, fs[ifs])

        result = {'return':0}

        result['path'] = path
        result['qpath'] = self.cm.q(path)
 
        return result
