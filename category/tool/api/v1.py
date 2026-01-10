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
    def detect_(self, state, arg1, exe_path=None, path=None, paths=[]):
        """
        """
        import platform

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

        self.cm.j(desc)

        # cMeta platform detection: only windows, linux, macos
        r = self.cm.utils.sys.get_min_raw_host_info()
        if r['return']>0: return r

        host_os = r['os'].lower()

        # Resolve exe_path
        if exe_path is None:
            exes = desc['exe']

            exe = exes.get(host_os, exes['default'])

            # Detect OS and adjust exe extension
            if host_os == 'windows':
                exe = exe.replace('{{exe_ext_win}}', '.exe')
            else:
                exe = exe.replace('{{exe_ext_win}}', '')

            search_paths = paths.copy()

            if path is not None:
                search_paths = [path]
            else:
                if len(paths)>0:
                    search_paths = paths
              
            if len(search_paths) == 0:
                search_paths = [os.getcwd()]

            for spath in search_paths:
                candidate = os.path.join(spath, exe)
                if os.path.isfile(candidate):
                    exe_path = candidate
                    break

        if exe_path is None:
            return {'return':1, 'error': f'failed to find {exe}'}    

    
        print (exe_path)

        return {'return':0}
