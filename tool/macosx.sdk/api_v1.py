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
            self.logger.debug("RUNNING TOOL macosx.sdk api_v1 init")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = ctx['tasks']['global']['host']['os']['uname']

        if uname != 'darwin':
            return self.cm.error(f'macosx.sdk works only on MacOS (darwin) in "{__file__}"')

        return {'return':0}

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL macosx.sdk api_v1 check_params")

        result = {'return':0}

        return result


    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL macosx.sdk api_v1 update_paths")

        parsed_paths_with_versions = []

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        space = ctx['control'].get('space', '')

        _with = params.get('with', {})
        venv = _with.get('venv')
        pip = _with.get('pip')
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        cmd = 'xcrun --sdk macosx --show-sdk-path'

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'ctx': ctx,
              'arg1': 'cmd,c9ba0a88df394d7f',
              'cmd': cmd,
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

        xpath = rx.get('stdout').strip().split('\n')

        if len(xpath)>0:
            path = xpath[0]
            if path and os.path.isdir(path):
                if con and verbose:
                    print (f'{space}INFO: MacOSX SDK found at "{path}"')

                path_to_version = os.path.join(path, 'SDKSettings.json')

                r = self.cm.utils.files.read_file(path_to_version)
                if r['return'] == 0:
                    data = r['data']

                    if 'Version' in data:
                       detected_version = data['Version']

                       tool = {
                         'path': path_to_version, # to be able to check existance
                         'detected_version': detected_version,
                         'features': {
                            'paths': {
                              'home': path,
                              'version': path_to_version,
                            },
                            'sdk_settings': data
                         },
                       }

                       parsed_paths_with_versions.append(tool)

                       if con and verbose:
                           print (f'{space}INFO: MacOSX SDK version detected "{detected_version}"')

        return {'return':0, 'parsed_paths_with_versions':parsed_paths_with_versions}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _with = params.get('with',{})

        _result = {'return':0}

        if _with.get('add_env', False):
            features_paths = result['features']['paths']

            path_home = features_paths['home']

            _aggregate = result.setdefault('_aggregate', {})
            _aggregate_env = _aggregate.setdefault('env',{})

            _aggregate_env['SDKROOT'] = path_home

            _result['result'] = result

        return _result
