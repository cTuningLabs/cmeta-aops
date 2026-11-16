"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_deb import apt_versioned_package

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def customize_install_cmd(self,
                              ctx: dict,
                              install_cmd: str = None,
                              params: dict = {},
                              env: dict = {},
                              timeout: int = None,
                              *misc: dict,
    ):
        """
        A version that the system's g++ does not have (nvcc takes an older host compiler: CUDA 11.8 g++ < 12)
        on Debian or Ubuntu: the newest g++-<major> package of the distribution in that version (g++-11),
        installed beside the system's g++. Without a version or a matching package: the plain package.
        """
        package = apt_versioned_package(self, params.get('version'), 'g++-{major}')
        return {'return': 0, 'package_name': package} if package else {'return': 0}


    ############################################################
    def find_paths(self,
                   ctx: dict,
                   params: dict = {},
    ):
        """
        """
        path_to_gcc = ctx['tasks']['global']['gcc']['path']

        found_paths = []

        j = path_to_gcc.rfind('gcc')
        if j>0:
            path_to_gcc_cpp = path_to_gcc[:j] + 'g++' + path_to_gcc[j+3:]
            if os.path.isfile(path_to_gcc_cpp):
                found_paths.append(path_to_gcc_cpp)

        return {'return':0, 'found_paths':found_paths}


    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        new_paths = []
        con = ctx['control'].get('con', False)

        for p in paths:
            # Parsing standard output
            features = p.setdefault('features', {})

            path_tool = p['path']
            path_bin = os.path.dirname(path_tool)

            # Without binutils next to it: not a candidate, the setup installs the toolchain (see tool/gcc)
            path_tool_lib = os.path.join(path_bin, 'ar')
            if not os.path.isfile(path_tool_lib):
                if con:
                    print(f'cMeta warning: {path_tool} has no "ar" next to it (binutils missing) - not used')
                continue

            _paths = {
               'bin': path_bin,
               'tool_lib': path_tool_lib,
               'qtool_lib': self.cm.q(path_tool_lib),
            }

            features_paths = features.setdefault('paths',{})
            features_paths.update(_paths)

            new_paths.append(p)

        return {'return':0, 'paths':new_paths}

