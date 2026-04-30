"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import copy

from cmeta.category import InitCategory

class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def test_(self, ctx, arg1=None, flag1=False):
        """
        """

        self.logger.debug("RUNNING API v1 test_")

        print (f'arg1={arg1}')
        print (f'flag1={flag1}')

        return {'return':0}

    ############################################################
    def test2(self, params):
        """
        """

        self.logger.debug("RUNNING API v1 test2")

        import json
        print (json.dumps(params, indent=2))

        return {'return':0}

    ############################################################
    def find_path_(self, ctx, path = None, paths = None, space = None, context={}, desc={}):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING tool find_path v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx.setdefault('tasks', {})

        if space is None:
            nested_call = ctx_tasks.setdefault('nested_call', 0)
            space = '  ' * nested_call if verbose else ''

        if not paths:
            paths = []

        # Resolve exe_path
        found_paths = []

        if not path and 'path' in desc:
            path = desc['path']

            r = self.cm.utils.common.expand_string(path, context)
            if self.cm.catch_error(r): return r
            path = r['string']

        if path and os.path.isfile(path):
            found_paths = [path]

        else:
            if path and not os.path.isdir(path):
                return {'return':1, 'error': f'tool "{path}" doesn\'t exist'}

            if type(paths) == str:
                paths = paths.split(os.pathsep)

            if path:
                search_paths = [path]
            else:
                search_paths = paths.copy()

            if len(search_paths) == 0:
                search_paths = [os.getcwd()]

                env_paths = os.environ.get('PATH','').strip()
                if env_paths != '':
                    search_paths += env_paths.split(os.pathsep)

            names = desc.get('names', [])

            for name in names:

                r = self.cm.utils.common.expand_string(name, context)
                if self.cm.catch_error(r): return r
                name = r['string']

                if con and verbose:
                    print ('')
                    print (f'{space}SEARCH: file {name} ...')

                find_without_ext = False
                if name.endswith('.'):
                    find_without_ext = True
                    name = name[:-1]

                for spath in search_paths:
                    spath = spath.strip()

                    if not spath:
                        continue

                    candidate = os.path.join(spath, name)

                    # Handle wildcards in name
                    if '*' in spath or '?' in spath or '*' in name or '?' in name:
                        import glob

                        pattern = os.path.join(spath, name)
                        matches = glob.iglob(pattern, recursive = True)
                  
                        for match in matches:
                            if os.path.isfile(match) and match not in found_paths:
                                to_add = True

                                if find_without_ext:
                                    if os.path.splitext(match)[1] != "":
                                        to_add = False

                                if to_add:
                                    match = os.path.normpath(match)

                                    for _match in found_paths:
                                        if os.path.normcase(_match) == os.path.normcase(match):
                                            to_add = False
                                            break

                                    if to_add:
                                        found_paths.append(match)

                    elif os.path.isfile(candidate):
                        candidate = os.path.normpath(candidate)

                        to_add = True
                        for _candidate in found_paths:
                            if os.path.normcase(_candidate) == os.path.normcase(candidate):
                                to_add = False
                                break

                        if to_add:
                            found_paths.append(candidate)

        return {'return':0, 'found_paths': found_paths}

    ############################################################
    def setup(self, params):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING tool api v1 setup")

        p = self._prepare_input_from_params(params, base = False)

        p['category'] = self.cmeta['uses_categories']['task']
        p['command'] = 'run'
        p['name'] = params.get('arg1')
        p['arg1'] = self.cmeta['uses_artifacts']['tool::setup']

        return self.cm.access(p)

    ############################################################
    def run(self, params):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING tool api v1 run")

        ctx = params['ctx']

        p = self._prepare_input_from_params(params)

        unparsed = p.pop('unparsed', [])

        # Setup tool
        p.update({'category': self.cmeta['uses_categories']['task'],
                  'command': 'run',
                  'ctx': ctx,
        })

        pp = copy.deepcopy(p)

        p['arg1'] = self.cmeta['uses_artifacts']['tool::setup']
        p['name'] = params.get('arg1')

        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        cmd = r['cmd']

        for param in unparsed:
            param = param.strip()
            if ' ' in param and not param.startswith('"'):
                param = '"' + param + '"'

            cmd += ' ' + param
        
        # Clean some params (needed for "setup tool" task but not for "cmd" task)

        for k in ['detect','install', 'build', 'skip_install', 'skip_detect', 'skip_build',
                  'name', 'tool_tags', 'tool_api_ver', 'tool_path', 'paths', 'with',
                  'version']:
            if k in pp:
                del(pp[k])

        pp['arg1'] = self.cmeta['uses_artifacts']['tool::cmd']
        pp['cmd'] = cmd
        pp['ctx'] = ctx
        pp['print_extra_line'] = True

        r = self.cm.access(pp)
        self.cm.catch_error(r)

        return r
