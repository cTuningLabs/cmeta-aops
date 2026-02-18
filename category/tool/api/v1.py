import os
import copy

from cmeta.category import InitCategory

class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def test_(self, state, arg1=None, flag1=False):
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
    def find_path_(self, state, path = None, paths = None, space = None, context={}, desc={}):
        """
        """
        self.logger.debug("RUNNING tool find_path v1")

        con = state['control'].get('con', False)
        quiet = state['control'].get('quiet', False)
        verbose = state['control'].get('verbose', False)

        state_tasks = state.setdefault('tasks', {})

        if space is None:
            nested_call = state_tasks.setdefault('nested_call', 0)
            space = '  ' * nested_call

        if not paths:
            paths = []

        # Resolve exe_path
        found_paths = []

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

            names = desc['names']

            for name in names:

                r = self.cm.utils.common.expand_string(name, context)
                if r['return']>0: return self.cm._error2(r, self.cm)

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
                                    found_paths.append(match)

                    elif os.path.isfile(candidate):
                        if candidate not in found_paths:
                            found_paths.append(candidate)

        return {'return':0, 'found_paths': found_paths}

    ############################################################
    def setup(self, params):
        """
        """

        self.logger.debug("RUNNING tool api v1 setup")

        p = self._prepare_input_from_params(params, base = False)

        p['category'] = self.cmeta['uses_categories']['task']
        p['command'] = 'run'
        p['name'] = params.get('arg1')
        p['arg1'] = self.cmeta['uses_artifacts']['tool::setup-tool']

        return self.cm.access(p)

    ############################################################
    def run(self, params):
        """
        """

        self.logger.debug("RUNNING tool api v1 run")

        state = params['state']

        p = self._prepare_input_from_params(params)

        unparsed = p.pop('unparsed', [])

        # Setup tool
        p.update({'category': self.cmeta['uses_categories']['task'],
                  'command': 'run',
                  'state': state,
        })

        pp = copy.deepcopy(p)

        p['arg1'] = self.cmeta['uses_artifacts']['tool::setup-tool']
        p['name'] = params.get('arg1')

        r = self.cm.access(p)
        if r['return']>0: return self.cm._error2(r, self.cm)

        path = r['path']

        cmd = path

        for param in unparsed:
            param = param.strip()
            if ' ' in param and not param.startswith('"'):
                param = '"' + param + '"'

            cmd += ' ' + param
        
        # Run tool
        pp['arg1'] = self.cmeta['uses_artifacts']['tool::cmd']
        pp['cmd'] = cmd
        pp['state'] = state

        r = self.cm.access(pp)
        if r['return']>0: return self.cm._error2(r, self.cm)

        return r
