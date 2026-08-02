"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        Mostly used to update storage_key
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 init")

        result = {'return':0}

        return result

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 check_params")

        result = {'return':0}

        # Check if venv and set to True by default if none
        _with = params.setdefault('with', {})

        if 'venv' not in _with:
            _with['venv'] = True

        if 'pip' not in _with:
            _with['pip'] = True

        _here = params.get('here')
        if not _here:
            _here = _with.get('here')

        _venv_path = params.get('venv_path')
        if not _venv_path:
            _venv_path = _with.get('venv_path')

        _venv_here = None
        if not _venv_path:
           _venv_here = params.get('venv_here')
           if not _venv_here:
               _venv_here = _with.get('venv_here')

           if _venv_here:
               _venv_path = os.getcwd()

        if _venv_path:
            _venv_path = os.path.abspath(_venv_path)
            params['venv_path'] = _venv_path

        if _venv_path or _venv_here:
            ctx_tasks = ctx.setdefault('tasks', {})
            ctx_tasks_use = ctx_tasks.setdefault('use', {})
            ctx_tasks_use_venv = ctx_tasks_use.setdefault('venv', {})

            if _venv_path:
                ctx_tasks_use_venv['path'] = _venv_path
#            if _venv_here:
#                ctx_tasks_use_venv['here'] = _venv_here

        # Check if here and try to find python in current directory
        if _here:
            cur_dir = os.path.join(os.getcwd(), '**', '.*', '**')

            ii = {'category': 'tool,c393ba5c6fa14f66',
                  'command': 'find_path',
                  'paths': [cur_dir],
                  'ctx': ctx,
                  'context': ctx['tasks'],
                  'desc': self.cdesc,
                  'con': True,
                  'verbose': True,
            }

            r = self.cm.access(ii)
            if self.cm.catch_error(r): return r

            found_paths = r.get('found_paths', [])
            if found_paths:
                # This should force task to search in cache with this path
                # and if it's not found, register it ...
                params['tool_path'] = found_paths[0]
            else:
                return self.cm.error(f'python not found in "{cur_dir}"')

        return result

    ############################################################
    def update_paths(self,
                     ctx: dict,
                     paths: dict,
                     params: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 update_paths")

        import sys
        self_python_path = sys.executable

        if self_python_path in paths:
            paths.remove(self_python_path)

        # ! tells setup to keep this path on top during sorting (priority key)
        paths.insert(0, '!' + self_python_path)

#        # Check if .venv in the current directory
#        path_scripts = 'Scripts' if os.name == 'nt' else 'bin'
#        exe = '.exe' if os.name == 'nt' else ''
#        path_venv_scripts = os.path.join(ctx['origin']['pwd'], '.venv', path_scripts)
#        path_venv_python = os.path.join(path_venv_scripts, 'python'+exe)
#
#        if os.path.isfile(path_venv_python):
#            paths.insert(0, '!' + path_venv_python)


        return {'return':0, 'paths':paths}

    ############################################################
    def sort_paths(self,
                   ctx: dict,
                   paths: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 sort_paths")

        return {'return':0}


    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 check_features")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        con = False if not verbose else con

        _with = params.get('with', {})
        venv = _with.get('venv')
        pip = _with.get('pip')
        env = _with.get('env', {})
        timeout = _with.get('timeout')

#        # Check if .venv in the current directory
#        path_scripts = 'Scripts' if os.name == 'nt' else 'bin'
#        exe = '.exe' if os.name == 'nt' else ''
#        path_venv_scripts = os.path.join(ctx['origin']['pwd'], '.venv', path_scripts)
#        path_venv_python = os.path.join(path_venv_scripts, 'python'+exe)
#
#        if os.path.isfile(path_venv_python):
#            paths.insert(0, '!' + path_venv_python)

        # If venv is True (default), leave only ones with virtual env
        final_paths = []

        for p in paths:
            python_path = p['path']

            features = {}

            to_add = True

            ii = {'category': 'task,c36be4b9314a45e0',
                  'command': 'run',
                  'arg1': 'detect-python-env,8b55a595f3284ceb',
                  'ctx': ctx,
                  'python_path': python_path,
            }

            r = self.cm.access(ii)
            if self.cm.catch_error(r): return r

            is_virtual = r['is_virtual']
            features['is_virtual'] = is_virtual

            if venv:
                to_add = False

                if is_virtual:
                    to_add = True

                    features['venv'] = True
                    features['venv_extra'] = r

                    activate_script_path = r.get('script_path')
                    if activate_script_path:
                        host = ctx['tasks']['global']['host']

                        cmd_activate_script_path = host['vars']['call_script'] + ' ' + activate_script_path

                        features['cmd_venv_activate_scipt'] = cmd_activate_script_path

                        ii = {'category': 'task,c36be4b9314a45e0',
                              'command': 'run',
                              'ctx': ctx,
                              'arg1': 'cmd,c9ba0a88df394d7f',
                              'cmd': cmd_activate_script_path,
                              'env': env,
                              'timeout': timeout,
                              'con': con, 
                              'quiet': quiet, 
                              'verbose': verbose, 
                              'text_cmd': 'RUN:', 
                              'capture_output': True,
                              'capture_env': True,
                              # Important to be able to continue processing detect/install/build
                              'fail_if_nonzero_return_code': False, 
                        }

                        rx = self.cm.access(ii)
                        if self.cm.catch_error(rx): return rx

                        if rx['returncode'] == 0:
                            features['venv_extra_env'] = rx['env_added']

            else:
                features['venv'] = venv

            if to_add and pip:
                # Run check for pip
                pip_cmd = python_path + ' -m pip --version'

                ii = {'category': 'task,c36be4b9314a45e0',
                      'command': 'run',
                      'ctx': ctx,
                      'arg1': 'cmd,c9ba0a88df394d7f',
                      'cmd': pip_cmd,
                      'env': env,
                      'timeout': timeout,
                      'con': con, 
                      'quiet': quiet, 
                      'verbose': verbose, 
                      'text_cmd': 'RUN:', 
                      'capture_output': True,
                      # Important to be able to continue processing detect/install/build
                      'fail_if_nonzero_return_code': False, 
                }

                rx = self.cm.access(ii)
                if self.cm.catch_error(rx): return rx

                returncode = rx['returncode']

                if returncode>0:
                    to_add = False
                else:
                    features['pip'] = True


            if to_add:
                # Check pip and activate ...
                if features:
                    p['features'] = features

                final_paths.append(p)

        return {'return':0, 'paths':final_paths}


    ############################################################
    def post_detect(self,
                    ctx: dict,
                    result: dict,
                    params: dict,
    ):
        """
        """

        if params.get('with',{}).get('activate',False):
            venv_extra_env = result.get('features',{}).get('venv_extra_env',{})
            if venv_extra_env:
                env_added = venv_extra_env.copy()
                for key in self.cdesc['add_env_path_keys']:
                    if key in list(env_added.keys()):
                        env_added['+'+key] = env_added.pop(key).split(os.pathsep)
                result['_aggregate'] = {'env': env_added}

        return {'return':0}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                install_cmd: str = None,
                *misc: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        path_to_python = _global['venv']['path_to_python']

        # venv_path specify root venv that we force append '.venv' to.
        # that's why we need to go 1 level above here
        _update_params = {'venv_path': os.path.dirname(_global['venv']['path_to_venv'])}

        return {
          'return': 0, 
          'install_cmd': None, 
          'found_path': path_to_python, 
          '_update_params': _update_params,
        }

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _result = {'return':0}

        _with = params.get('with',{})

        path_bin = result['path_bin']

        path_home = os.path.dirname(path_bin)
        qpath_home = self.cm.q(path_home)

        result['path_home'] = path_home
        result['qpath_home'] = qpath_home

        return _result

