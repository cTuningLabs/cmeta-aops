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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)


    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        _with = params.setdefault('with', {})

        compute = _with.get('compute')
        if not compute:
            compute = ctx['tasks']['global'].get('target', {}).get('compute')
        if not compute:
            compute = ['cpu']
        if isinstance(compute, str):
            compute = compute.split(',')

        _with['compute'] = compute
        ctx['tasks']['local']['compute'] = compute
        ctx['tasks']['local']['target_abi'] = None

        return {'return': 0}


    ############################################################
    def customize_build(self,
                        ctx: dict,
                        misc: dict,
    ):
        result = {'return': 0}

        version = misc.get('version')
        if version:
            # PyTorch git tags are v2.7.1, v2.12.0, etc.
            result['add_to_local'] = {'checkout': f'v{version}'}

        return result


    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict = {},
    ):
        """
        Expose libtorch install prefix, include dir, and lib dir from the
        cmake --install output of program/build-torch-cpp.

        path = {prefix}/lib/torch.dll   (Windows)
             = {prefix}/lib/libtorch.so (Linux)
             = {prefix}/lib/libtorch.dylib (macOS)
        """
        new_paths = []

        for p in paths:
            features = p.setdefault('features', {})
            path_features = features.setdefault('paths', {})
            path = p['path']

            path_lib = os.path.dirname(path)   # {prefix}/lib/
            path_home = os.path.dirname(path_lib)  # {prefix}/
            path_include = os.path.join(path_home, 'include')

            path_features['home']     = path_home
            path_features['qhome']    = self.cm.q(path_home)
            path_features['lib']      = path_lib
            path_features['qlib']     = self.cm.q(path_lib)
            path_features['include']  = path_include
            path_features['qinclude'] = self.cm.q(path_include)

            new_paths.append(p)

        return {'return': 0, 'paths': new_paths}


    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: list,
                        params: dict = {},
    ):
        found_paths_info = {}
        _with = params.get('with', {})

        for path in paths:
            if not os.path.isfile(path):
                continue

            path_lib  = os.path.dirname(path)
            path_home = os.path.dirname(path_lib)
            path_include = os.path.join(path_home, 'include')

            found_paths_info[path] = {
                'features': {
                    'paths': {
                        'home':     path_home,
                        'lib':      path_lib,
                        'include':  path_include,
                    },
                    'with': _with,
                },
            }

        result = {'return': 0}
        if found_paths_info:
            result['found_paths_info'] = found_paths_info
        return result
