"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/pytorchvision: torchvision in the Python of the run - detected when it is there, built from source by
program/build-pytorchvision against the torch of that Python otherwise (the mirror of tool/pytorch).
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool


def site_packages_of(path):
    """The site-packages folder of a detected torchvision ({site}/torchvision/__init__.py), or None."""
    if os.path.basename(path) == '__init__.py':
        return os.path.dirname(os.path.dirname(path))
    return None


def python_homes(ctx):
    """The folders of the Python of the run under which the package's __init__.py is searched (the names of _desc.yaml)."""
    python = ctx.get('tasks', {}).get('global', {}).get('python', {}) or {}
    return [p for p in (python.get('path_home'), python.get('path_bin')) if p]


class CTool(InitCTool):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


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
            # torchvision's git tags are v0.22.1, v0.29.1, ...; without a version the program pairs
            # the checkout with the torch it finds
            result['add_to_local'] = {'checkout': f'v{version}'}

        return result


    ############################################################
    def build(self,
              ctx: dict,
              params: dict = {},
    ):
        """
        Runs after build_uses (the build program installed torchvision into the Python of the run): the
        detection that follows must look in that Python, not in the entry's build folder, which
        task/setup/build.py hands it by default (<entry>/build/**) - the package is not there.
        """
        return {'return': 0, 'found_paths': python_homes(ctx)}


    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict = {},
    ):
        new_paths = []

        for p in paths:
            path_site = site_packages_of(p['path'])
            if not path_site:
                continue

            features = p.setdefault('features', {})
            path_features = features.setdefault('paths', {})
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
            path_site = site_packages_of(path)
            if not path_site:
                continue
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
