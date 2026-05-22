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

        name = self.cdesc['name']

        # FGG: extension depends on target / compiler and not just on host
        # For example Android on Windows will have .so and not .dll ...

        if 'android-cpu' in params.get('with', {}).get('compute',[]):
            name += '.so'
        else:
            if 'compiler' in ctx['tasks']['global']:
                name += ctx['tasks']['global']['compiler']['features']['vars']['file_ext_dlib']
            else:
                name += ctx['tasks']['global']['host']['vars']['file_ext_dlib']

        ctx['tasks']['local']['tool_name'] = name

        # Check if Android
        k = 'target--android-cpu'
        if k in ctx['tasks']['global']:
            ctx['tasks']['local']['target_abi'] = ctx['tasks']['global'][k]['features']['ro.product.cpu.abi']

        return {'return': 0}

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        """

        _static = params.get('with',{}).get('static', False)

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        found_paths_with_versions =  {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        _with = params.get('with', {})
        _static = _with.get('static', False)
        _add_debug = _with.get('add_debug', False)


        for path in paths:
             filename_without_ext = os.path.splitext(os.path.basename(path))[0]
             libname = filename_without_ext[3:] if filename_without_ext.startswith('lib') else filename_without_ext

             path_lib = os.path.dirname(path)
             path_home = os.path.dirname(path_lib)

             path_include = os.path.join(path_home, 'include')
             path_includes = [path_include]
             
             path_cmeta_info = os.path.join(path_home, '_cmeta_info.json')

             version = None

             if os.path.isfile(path_cmeta_info):
                 r = self.cm.utils.files.read_file(path_cmeta_info)
                 if self.cm.catch_error(r): return r

                 s = r['data']

                 version = s.get('version')

             if not version:
                 version = 'default'

             _path_lib = path_lib

             _libs = {}

             if _static:
                 if _add_debug:
                     _libs['libs_static_debug'] = [path_lib]
                 else:
                     _libs['libs_static'] = [path_lib]
             else:
                 if _add_debug:
                     _libs['libs_debug'] = [path_lib]

             # Default libs
             path_libs = [path_lib]
             qpath_libs = [self.cm.q(path_lib)]

             lib_names = [libname]

             lib_names_static = []
             if _static:
                 lib_names_static = [libname]

             paths = {
                 'root': path_home,
                 'qroot': self.cm.q(path_home),
             }

             # FGG: bin is only needed on Windows for DLLs ...
             if not _static:
                 paths['dynamic_lib'] = path_lib
                 paths['qdynamic_lib'] = self.cm.q(path_lib)
                 paths['dynamic_libs'] = [path_lib]

             if os.path.isdir(path_include):
                 paths['include'] = path_include
                 paths['qinclude'] = self.cm.q(path_include)

             if path_includes:
                 paths['includes'] = path_includes

             if os.path.isdir(path_lib):
                 paths['lib'] = path_lib
                 paths['qlib'] = self.cm.q(path_lib)

             if path_libs:
                 paths['libs'] = path_libs

             if _libs:
                 paths.update(_libs)

             features = {
               'paths': paths,
               'lib_names': lib_names,
             }

             if lib_names_static:
                 features['lib_names_static'] = lib_names_static

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

            features = result['features']

            path_dyn_lib = features['paths'].get('dynamic_lib')

            if path_dyn_lib and os.path.isdir(path_dyn_lib):
                features['paths']['found_dynamic_lib_paths'] = [path_dyn_lib]

                found_dynamic_libs = []

                if 'compiler' in ctx['tasks']['global']:
                    ext = ctx['tasks']['global']['compiler']['features']['vars']['file_ext_dlib']
                else:
                    ext = ctx['tasks']['global']['host']['vars']['file_ext_dlib']

                for l in features.get('lib_names', []):
                    path = os.path.join(path_dyn_lib, f'lib{l}{ext}')
                    if os.path.isfile(path):
                        if path not in found_dynamic_libs:
                            found_dynamic_libs.append(path)

                if found_dynamic_libs:
                    features['paths']['found_dynamic_libs'] = found_dynamic_libs

        return {'return':0}
