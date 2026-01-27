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
    def detect_(self, state, arg1, file_path=None, path=None, paths=[]):
        """
        """
        self.cm.j(state['category_cmeta'])
        input('xyz')

        self.logger.debug("RUNNING tool detect_ v1")

        con = state['control'].get('con', False)

        # Call base find function to find an artifact with a website
        p = self._prepare_input_from_state(state, base = True)

        p['command'] = 'read'
        p['con'] = False
        p['arg1'] = arg1
        p['load_files'] = ['desc.yaml']

        r = self.cm.access(p)
        if r['return']>0: return r

        artifact = r['artifact']

        tool_path = artifact['path']
        cmeta = artifact['cmeta']
        desc = r['loaded_files']['desc.yaml']['data']

        # cMeta platform detection: only windows, linux, macos
        r = self.cm.utils.sys.get_min_raw_host_info()
        if r['return']>0: return r

        host_os = r['os_lower']

        # Resolve exe_path
        if file_path is None:
            exes = desc['file']

            exe = exes.get(host_os, exes['default'])

            # Detect OS and adjust exe extension
            if host_os == 'windows':
                exe = exe.replace('{{exe_ext_win}}', '.exe')
            else:
                exe = exe.replace('{{exe_ext_win}}', '')

            if type(paths) == str:
                paths = paths.split(os.pathsep)

            search_paths = paths.copy()

            if path is not None:
                search_paths = [path]
            else:
                if len(paths)>0:
                    search_paths = paths
              
            if len(search_paths) == 0:
                search_paths = [os.getcwd()]

                env_paths = os.environ.get('PATH','').strip()
                if env_paths != '':
                    search_paths += env_paths.split(os.pathsep)

            for spath in search_paths:
                candidate = os.path.join(spath, exe)
                if os.path.isfile(candidate):
                    file_path = candidate
                    break

        if file_path is None:
            return {'return':16, 'error': f'failed to find {exe}'}    

        if file_path!='' and not os.path.isfile(file_path):
            return {'return':16, 'error': f'failed to find {file_path}'}    


    
        print (file_path)

        return {'return':0}
