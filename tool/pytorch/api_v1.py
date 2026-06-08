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
        if type(compute) == str:
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
        new_paths = []

        for p in paths:
            features = p.setdefault('features', {})
            path_features = features.setdefault('paths', {})
            path = p['path']

            if os.path.basename(path) == '__init__.py':
                # pip-installed: {venv_site}/torch/__init__.py
                path_site = os.path.dirname(os.path.dirname(path))  # {venv_site}/
            else:
                # cmake-based (legacy): {build_root}/lib/torch.dll
                path_lib = os.path.dirname(path)
                path_site = os.path.dirname(path_lib)  # {build_root}/
                # Try to read PYTHONPATH from repro ctx saved during the build
                repro_path = os.path.join(path_site, '_repro_ctx_compile.json')
                if os.path.isfile(repro_path):
                    r = self.cm.utils.files.read_file(repro_path)
                    if r['return'] == 0:
                        compiled_local = r['data'].get('ctx', {}).get('tasks', {}).get('local', {})
                        pythonpath = compiled_local.get('run_time_env', {}).get('PYTHONPATH', '')
                        if pythonpath and os.path.isdir(pythonpath):
                            path_site = pythonpath

            path_features['home'] = path_site
            path_features['qhome'] = self.cm.q(path_site)
            path_features['site_packages'] = path_site
            path_features['qsite_packages'] = self.cm.q(path_site)

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

            if os.path.basename(path) == '__init__.py':
                # pip-installed: {venv_site}/torch/__init__.py
                path_site = os.path.dirname(os.path.dirname(path))
            else:
                # cmake-based (legacy): {build_root}/lib/torch.dll
                path_lib = os.path.dirname(path)
                path_site = os.path.dirname(path_lib)
                repro_path = os.path.join(path_site, '_repro_ctx_compile.json')
                if not os.path.isfile(repro_path):
                    continue
                r = self.cm.utils.files.read_file(repro_path)
                if r['return'] != 0:
                    continue
                compiled_local = r['data'].get('ctx', {}).get('tasks', {}).get('local', {})
                pythonpath = compiled_local.get('run_time_env', {}).get('PYTHONPATH', '')
                if not pythonpath:
                    continue
                path_site = pythonpath

            found_paths_info[path] = {
                'features': {
                    'paths': {'site_packages': path_site},
                    'with': _with,
                },
            }

        result = {'return': 0}
        if found_paths_info:
            result['found_paths_info'] = found_paths_info
        return result
