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

        _with = params.setdefault('with', {})

        compute = _with.get('compute')
        if not compute:
            compute = ctx['tasks']['global'].get('target',{}).get('compute')
        if not compute:
            compute = ['cpu']

        if type(compute) == str:
            compute = compute.split(',')

        _with['compute'] = compute
        ctx['tasks']['local']['compute'] = compute

        if 'android-cpu' in compute:
            name += '.so'
        else:
            if 'compiler-c' in ctx['tasks']['global']:
                name += ctx['tasks']['global']['compiler-c']['features']['vars']['file_ext_dlib']
            else:
                name += ctx['tasks']['global']['host']['vars']['file_ext_dlib']

        ctx['tasks']['local']['tool_name'] = name

        # Check if Android
        k = 'target--android-cpu'
        target_abi = _with.get('android_abi')
        if not target_abi:
            if k in ctx['tasks']['global']:
                target_abi = ctx['tasks']['global'][k]['features']['ro.product.cpu.abi']

        ctx['tasks']['local']['target_abi'] = target_abi

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
        _debug_info = _with.get('debug_info', False)


        for path in paths:
             filename_without_ext = os.path.splitext(os.path.basename(path))[0]
             libname = filename_without_ext[3:] if filename_without_ext.startswith('lib') else filename_without_ext

             path_dynamic_lib = os.path.dirname(path)
             path_home = os.path.dirname(path_dynamic_lib)

             path_lib = os.path.join(path_home, 'static')

             path_include = os.path.join(path_home, 'include')
             
             # Check versions
             path_cmeta_info = os.path.join(path_home, '_cmeta_info.json')

             version = None

             if os.path.isfile(path_cmeta_info):
                 r = self.cm.utils.files.read_file(path_cmeta_info)
                 if self.cm.catch_error(r): return r

                 s = r['data']

                 version = s.get('version')

             if not version:
                 version = 'default'

             # Prepare paths
             paths = {
                 'root': path_home,
                 'qroot': self.cm.q(path_home),
             }

             if os.path.isdir(path_include):
                 paths['include'] = path_include
                 paths['qinclude'] = self.cm.q(path_include)
                 paths['includes'] = [path_include]

             paths['dynamic_lib'] = path_dynamic_lib
             paths['qdynamic_lib'] = self.cm.q(path_dynamic_lib)
             paths['dynamic_libs'] = [path_dynamic_lib]

             if os.path.isdir(path_lib):
                 paths['lib'] = path_lib
                 paths['qlib'] = self.cm.q(path_lib)
                 paths['libs'] = [path_lib]
                 paths['qlibs'] = [self.cm.q(path_lib)]

                 paths['libs_static'] = [path_lib]

             if _debug_info:
                 paths['libs_debug'] = [path_dynamic_lib]
                 paths['libs_static_debug'] = [path_lib]

             # Lib names
             lib_names = [libname]
             lib_names_static = [libname]

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

        if result['return'] == 0 and not params.get('version_check', False):
            _with = params.get('with', {})

            # High-level program compilation flag that also passed here
            _static = _with.get('static', False)

            features = result['features']

            path_dyn_lib = features['paths'].get('dynamic_lib')
            if not _static and path_dyn_lib and os.path.isdir(path_dyn_lib):
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

