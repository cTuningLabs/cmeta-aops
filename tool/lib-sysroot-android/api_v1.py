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
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        """

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        found_paths_with_versions = {}

        abi = ctx_tasks['local']['target_abi']

        if abi == 'arm64-v8a':
            clang_abi = 'aarch64'
        elif abi == 'armeabi-v7a':
            clang_abi = 'arm'
        else:
            return self.cm.error(f'could\'t prepare clang abi for "{abi}" in "{__file__}"')

        found_paths_with_versions =  {}

        for path in paths:
            path_lib_arch = os.path.dirname(path)
            lib_arch = os.path.basename(path_lib_arch)

            if lib_arch.startswith(clang_abi+'-'):
                path_lib = os.path.dirname(path_lib_arch)

                path_root = os.path.dirname(path_lib)

                path_include = os.path.join(path_root, 'include')
                path_includes = [path_include]

                version = 'default'

                paths = {
                   'root': path_root,
                   'qroot': self.cm.q(path_root),

                   'include': path_include,
                   'qinclude': self.cm.q(path_include),

                   'includes': path_includes,
                }

                # Check libs
                if os.path.isdir(path_lib):
                    paths['lib'] = path_lib_arch
                    paths['qlib'] = self.cm.q(path_lib_arch)

                    # Default (dynamic or static)
                    paths['libs'] = [path_lib_arch]
                    paths['libs_static'] = [path_lib_arch]

                features = {
                  'paths': paths,
                  'skip_include_paths_during_compilation': True,
                  'skip_lib_paths_during_compilation': True,
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
            _static = _with.get('static', False)

            features = result['features']

            lib_names = []
            k = 'lib_names_static' if _static and 'lib_names_static' in _with else 'lib_names'
            if k in _with: lib_names = _with[k]

            features['lib_names'] = lib_names

            found_dynamic_libs = []
            dynamic_libs = _with.get('dynamic_libs', [])
            dynamic_libs_with_api_level = _with.get('dynamic_libs_with_api_level', [])

            api_level = ctx['tasks']['global']['android-ndk-clang']['features'].get('target_arch',{}).get('api_level')
            path_lib = features['paths']['lib']

            if not _static:
                for l in dynamic_libs:
                    path = os.path.join(path_lib, 'lib' + l + '.so')
                    if os.path.isfile(path):
                        if path not in found_dynamic_libs:
                            found_dynamic_libs.append(path)

            if api_level:
                path_lib_api = os.path.join(path_lib, str(api_level))
                if os.path.isdir(path_lib_api):
                    features['paths']['lib_api_level'] = path_lib_api
                    if path_lib_api not in features['paths']['libs']:
                        features['paths']['libs'].append(path_lib_api)
                    if path_lib_api not in features['paths']['libs_static']:
                        features['paths']['libs_static'].append(path_lib_api)

                    if not _static and dynamic_libs_with_api_level:
                        for l in dynamic_libs_with_api_level:
                            path = os.path.join(path_lib_api, 'lib' + l + '.so')
                            if os.path.isfile(path):
                                if path not in found_dynamic_libs:
                                    found_dynamic_libs.append(path)

            if found_dynamic_libs:
                features['paths']['found_dynamic_libs'] = found_dynamic_libs

        return {'return':0}
