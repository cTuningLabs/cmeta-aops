"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize_tool_cache_artifact(self,
                                      ctx,
                                      result,
                                      params,
                                      cache_tags,
                                      cache_params,
                                      cache_features,
                                      cache_meta,
        ):

        result = {'return':0}

        cache_meta['skip_cache_version_check'] = True

        return result


    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL rust api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            version = '25.9.0'
            version_simple = version

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install for "node-js" can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        url = None
        filename = None

        if uarch == 'amd64':
            uarch2 = 'x64'
        elif uarch == 'arm64':
            uarch2 = 'arm64'

        if uname == 'windows':
            uos = 'win'
            uext = '.zip'
            sub_directory = None
        elif uname == 'linux':
            uos = 'linux'
            uext = '.tar.xz'
            sub_directory = 'bin'
        elif uname == 'darwin':
            uos = 'darwin'
            uext = '.tar.gz'
            sub_directory = 'bin'

        if not uarch2:
            return {
                'return': 16, 
                'error': f'custom install for "node-js" could not create download URL',
            }

        filename = f'node-v{version_simple}-{uos}-{uarch2}{uext}'

        url = f'https://nodejs.org/dist/v{version_simple}/{filename}'

        directory = 'content'
        path_to_tool = os.path.join(os.getcwd(), directory)
        if sub_directory:
            path_to_tool = os.path.join(path_to_tool, sub_directory)
        path_to_tool = os.path.join(path_to_tool, 'node' + _global['host']['vars']['file_ext_exe'])

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: Download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_tool}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'env': env,
              'timeout': timeout,
              'con': con, 
              'quiet': quiet, 
              'verbose': verbose, 
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 1,
              'check_file': path_to_tool,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
          'return': 0, 
          'install_cmd': None, 
          'found_path': path_to_tool,
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

        self.cm.j(result)

        path_bin = result['path_bin']

        path_home = os.path.dirname(path_bin)
        qpath_home = self.cm.utils.files.quote_path(path_home)

        result['path_home'] = path_home
        result['qpath_home'] = qpath_home

        if _with.get('add_env', True):
            _aggregate = result.setdefault('_aggregate', {})
            _aggregate_env = _aggregate.setdefault('env',{})

            _aggregate_env['NODEJS_HOME'] = path_home

            _path = _aggregate_env.setdefault('+PATH', [])
            if path_bin not in _path: 
                _path.insert(0, path_bin)

            _result['result'] = result

        return _result
