"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
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
            filedesc: str = None,
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

        result = {'return':0}

        if filename and os.path.isfile(filename):
            # Here local file is forced to bypass all the logic of downloading, etc
            path = filename

            result['path'] = path
            result['qpath'] = self.cm.q(path)

            path_root = path
            if os.path.isfile(path):
                path_root = os.path.dirname(path)

            result['path_root'] = path
            result['qpath_root'] = self.cm.q(path)

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

            # Backward compatibility: datasets that ship their data inside a "files" subdirectory
            path_to_files = os.path.join(artifact_path, 'files')

            if os.path.isdir(path_to_files):
                # Check files
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

                result['path'] = path
                result['qpath'] = self.cm.q(path)

            else:
                # Select among _desc* descriptions and prepare the dataset via "uses" (same as model)
                files = [
                    f for f in os.listdir(artifact_path)
                    if f.startswith("_desc")
                ]

                if len(files) == 0:
                    return self.cm.error(f'dataset descriptions not found in "{artifact_path}" ("{__file__}")')

                if filedesc:
                    filedesc = '_desc-' + filedesc
                    if filedesc not in files:
                        return self.cm.error(f'dataset file "{filedesc}" not found in "{artifact_path}" ("{__file__}")')

                    path_desc = os.path.join(artifact_path, filedesc)
                else:
                    fs = sorted(files)
                    ifs = 0

                    if len(fs) > 1 and con and not quiet:
                        print ('')
                        print (f'{space}Available dataset files:')

                        print ('')
                        for n in range(0, len(fs)):
                            x = fs[n][6:]
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

                    path_desc = os.path.join(artifact_path, fs[ifs])

                # Load file
                r = self.cm.utils.files.read_file(path_desc)
                if self.cm.catch_error(r, fail16=True):
                    r['return'] = 1 # Force fail if file not found
                    return r

                _desc = r['data']

                _uses = _desc.get('uses')
                result_from_ctx = _desc.get('result_from_ctx')

                if _uses:
                    if con and verbose:
                        print ('')
                        print (f'{space}Preparing dataset ...')

                    p = {'category': self.category_alias + ',' + self.category_uid,
                         'command': 'use',
                         'con': con,
                         'quiet': quiet,
                         'verbose': verbose,
                         'ctx': ctx,
                         'desc': _uses,
                         'local': None, #ctx['tasks']['local'],
                         'task_artifact_alias': self.artifact_alias,
                         'task_artifact_uid': self.artifact_uid,
                         'task_artifact_path': self.artifact_path,
#                         'self_desc': _desc,
                        }

                    r = self.cm.access(p)

#                    rx = self.cm.utils.files.write_file('d:\\xyz.json', {'ctx':ctx, 'result':r}, safe_dump = True)
#                    if self.cm.catch_error(rx): return rx

                    if self.cm.catch_error(r): return r

                    if result_from_ctx:
                        r = self.cm.utils.common.expand_string(result_from_ctx, ctx['tasks'])
                        if self.cm.catch_error(r): return r

                        result = r['value']

                        result['return'] = 0

        return result
