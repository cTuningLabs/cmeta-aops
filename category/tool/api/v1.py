import os

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
    def which(self, params):
        return self.where_(**params)

    ############################################################
    def find_path_(self, state, arg1, tags = None, path = None, paths = [], space = '', ver = None):
        """
        """
        self.logger.debug("RUNNING tool find_path v1")

        con = state['control'].get('con', False)
        quiet = state['control'].get('quiet', False)
        verbose = state['control'].get('verbose', False)

        # Call base find function to find an artifact with a website
        p = {'category':self.cmeta['uses_categories']['utils'],
             'command':'select_artifact',
             'select_category':state['category'],
             'select_artifact':arg1,
             'select_tags':tags,
             'con':con,
             'quiet':quiet,
             'load_files':['desc'],
             'space':space,
             'load_api': True,
             'load_api_ver': ver,
             'load_api_class': 'CTool',
        }

        r = self.cm.access(p)
        if r['return']>0: 
            ret = r['return']
            if ret == 16: ret = 1
            return self.cm._error(r['error'], ret, None, self.cm.fail_on_error)

        artifact = r['artifact']
        cmeta = artifact['cmeta']
        desc = r['loaded_files']['desc'].get('data', {})

        tool_path = artifact['path']
        tool_api_code = r['api_code']

        artifact_au = r['artifact_au']


        print (tool_api_code)




        # cMeta platform detection: only windows, linux, macos
        r = self.cm.utils.sys.get_min_raw_host_info()
        if r['return']>0: return r

        host_os = r['os_lower']


        substs = {
          'windows':{'file_ext_exe': '.exe'},
          'linux':{'file_ext_exe': '.'},
        }

        
        subst = substs[host_os] if host_os in substs else substs['linux']

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

                r = self.cm.utils.common.expand_string(name, subst)
                if r['return']>0: return self.cm._error2(r, self)

                name = r['string']

                find_without_ext = False
                if name.endswith('.'):
                    find_without_ext = True
                    name = name[:-1]

                for spath in search_paths:
                    candidate = os.path.join(spath, name)

                    # Handle wildcards in name
                    if '*' in name or '?' in name:
                        import glob

                        pattern = os.path.join(spath, name)
                        matches = glob.glob(pattern)
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

        if not found_paths:
            return {'return':16, 'error': f'failed to find tool "{artifact_au}"'}

        if con:
            for path in found_paths:
                s = path
                real_path = os.path.realpath(path)
                if real_path != path:
                    s += f' ({real_path})'

                print (s)

        return {'return':0, 'found_paths': found_paths}
