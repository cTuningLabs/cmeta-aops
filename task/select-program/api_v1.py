"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import copy

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(
            self, 
            ctx, 
            name: str = None,
            program_tags: str = None,
            program_api_ver: str = None,
            ask: bool = False,
            compute: str = None,
            cmd: str = None,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK select-program run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        result = {'return':0}

        _global = ctx_tasks['global']

        p = {'category': self.cmeta['uses_categories']['utils'],
             'command': 'select_artifact',
             'select_category': self.cmeta['uses_categories']['program'],
             'select_artifact': name,
             'select_tags': program_tags,
#             'select_match':{'constraints':{'target':[]}},
             'select_match':{'constraints':{}},
             'con': con,
             'quiet': quiet,
             'load_files': ['_desc'],
             'space': space,
             'load_api': True,
             'load_api_ver': program_api_ver,
             'load_api_class': 'CProgram',
             'print_extra_line': True,
        }

        # Check constraints
        constraints = {}

        if compute:
            selected_compute = compute
        else:
            selected_compute = _global.get('target', {}).get('compute')

        if selected_compute:
            # AND match, i.e. cpu + cuda should match both (for hybrid compute)
            if type(selected_compute) == str:
                selected_compute = selected_compute.split(',')
            constraints['supported_compute'] = selected_compute

        if constraints:
            p['select_match'] = {'constraints': constraints}

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): 
            if r['return'] == 16 and constraints:
                r['error'] += f' with constraints "{constraints}"'
            r['return'] = 1 # Fail above
            return r

        artifact = r['artifact']
        artifact_path = artifact['path']
        artifact_au = r['artifact_au']
        loaded_files = r['loaded_files']
        program_api_code = r['api_code']

        if con and verbose:
            print ('')
            print (f'{space}INFO: Selected program "{artifact_au}"')

        # Check inheritance in loaded_files (descriptions)
        for key in loaded_files:
            meta = loaded_files[key]
            data = meta.get('data')
            if data:
                inherits = data.get('inherits')
                if inherits:
                    _data = {}

                    for a in inherits:
                        if a:
                            pp = {
                               'category': self.cmeta['uses_categories']['program'],
                               'command': 'load',
                               'arg1': a,
                               'load_files': [key],
                            }
                            r = self.cm.access(pp)
                            if self.cm.catch_error(r, fail16=True): 
                                if r['return'] == 16 and constraints:
                                    r['error'] += f' when inheriting from {artifact_path} description file'
                                    r['return'] = 1 # Fail above
                                return r

                            _loaded_data = r['loaded_files'][key].get('data',{})

                            self.cm.utils.common.deep_merge(_data, _loaded_data, append_lists=False)

                    self.cm.utils.common.deep_merge(_data, data, append_lists=False)

                    # Check all updates
                    updates = _data.get('updates')

                    r = self.cm.access({'category': 'program,22788f3c30d04e6d',
                                        'command': 'update_desc',
                                        'desc': _data,
                                        'updates': updates})
                    if self.cm.catch_error(r): return r

                    # Check updates per cmd
                    updates_cmd = _data.get('updates_cmd')

                    if updates_cmd:
                        if not cmd:
                            cmds = _data.get('updates_cmd_keys')
                            if not cmds:
                                cmds = sorted(list(updates_cmd.keys()))

                            icmd = 0

                            if len(cmds) > 1 and con and not quiet:
                                print ('')
                                print (f'{space}Available command lines:')

                                print ('')
                                for n in range(0, len(cmds)):
                                    cmd = cmds[n]
                                    print (f'{space}{n}) {cmd}')
                                print ('')

                                while True:
                                    x = input('Please select a command line or press Enter for 0: ').strip()

                                    if x == "":
                                        icmd = 0
                                        break

                                    if x.isdigit() and int(x)>=0 and int(x)<len(cmds):
                                        icmd = int(x)
                                        break

                                print ('')

                            cmd = cmds[icmd]

                        r = self.cm.access({'category': 'program,22788f3c30d04e6d',
                                            'command': 'update_desc',
                                            'desc': _data,
                                            'updates': updates_cmd[cmd]})
                        if self.cm.catch_error(r): return r


                    # Finish desc
                    loaded_files[key]['data'] = _data        

        selected_program = {
            'path': artifact['path'],
            'artifact': artifact, 
            'artifact_au': artifact_au, 
            'loaded_files': loaded_files, 
            'api_code':program_api_code,
        }

        result['add_to_local'] = {'selected-program': selected_program}

        return result

