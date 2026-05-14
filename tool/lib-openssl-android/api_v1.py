"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import re
from pathlib import Path

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """



        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        k = 'target--android-cpu'

        if k not in _global:
            return self.cm.error(f'target compute "android-cpu" must be selected to install tool in "{__file__}"')

        target_android = _global[k]

        abi = target_android['features']['ro.product.cpu.abi']

        ctx_tasks['local']['target_abi'] = abi

        return {
          'return': 0, 
        }


    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        """

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        abi = ctx_tasks['local']['target_abi']

        xabi = abi

        if not xabi:
            return self.cm.error(f'couldn\'t detect abi for openssl based on "{abi}" in "{__file__}"')

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            version = self.cdesc['default_version']
            version_simple = version

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        filename = f'OpenSSL_{version_simple}_{xabi}.tar.gz'

        url = f'https://github.com/217heidai/openssl_for_android/releases/download/{version_simple}/{filename}'

        directory = 'content'

        path_to_check_file = os.path.join(os.getcwd(), directory, 'include', 'openssl', 'opensslv.h')

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: cMake download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_check_file}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'directory': directory,
              'url': url,
              'env': env,
              'timeout': timeout,
              'con': con, 
              'quiet': quiet, 
              'verbose': verbose, 
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 1,
              'check_file': path_to_check_file,
              'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
          'return': 0, 
          'install_cmd': None, 
          'found_path': path_to_check_file,
        }


    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        """

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL openssl api_v1 detect_versions")

        found_paths_with_versions =  {}

        for path in paths:
             # Detect version from include
             r = self.cm.utils.files.read_file(path)
             if self.cm.catch_error(r): return r

             s = r['data']

             version = None
             try:
                 openssl_version_major = int(re.search(r"OPENSSL_VERSION_MAJOR\s+(\d+)", s).group(1))
                 openssl_version_minor = int(re.search(r"OPENSSL_VERSION_MINOR\s+(\d+)", s).group(1))
                 openssl_version_patch = int(re.search(r"OPENSSL_VERSION_PATCH\s+(\d+)", s).group(1))
                 version = str(openssl_version_major) + '.' + str(openssl_version_minor) + '.' + str(openssl_version_patch)
             except Exception as e:
                 pass

             if not version:
                 continue

             # Set include paths
             path_include = os.path.dirname(os.path.dirname(path))
             path_includes = [path_include]

             path_root = os.path.dirname(path_include)

             paths = {
                'root': path_root,
                'qroot': self.cm.q(path_root),

                'include': path_include,
                'qinclude': self.cm.q(path_include),

                'includes': path_includes,
             }

             # Check libs
             path_lib = os.path.join(path_root, 'lib')

             lib_names = [
               'ssl', 
               'crypto'
             ]

             # Default lib
             if os.path.isdir(path_lib):
                 paths['lib'] = path_lib
                 paths['qlib'] = self.cm.j(path_lib)

                 # Default (dynamic or static)
                 paths['libs'] = [path_lib]
                 paths['libs_static'] = [path_lib]

             features = {
               'paths': paths,
               'lib_names': lib_names,
             }

             found_paths_with_versions[path] = {'output':version, 'features':features}

        return {'return':0, 'found_paths_with_versions':found_paths_with_versions}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        if not params.get('version_check', False):
            _with = params.get('with', {})

            if not _with.get('static', False):

                features = result['features']

                found_dynamic_libs = []

                path_lib = features['paths']['lib']

                for l in features['lib_names']:
                    path = os.path.join(path_lib, f'lib{l}.so')
                    if os.path.isfile(path):
                        if path not in found_dynamic_libs:
                            found_dynamic_libs.append(path)

                if found_dynamic_libs:
                    features['paths']['found_dynamic_libs'] = found_dynamic_libs

        return {'return':0}
