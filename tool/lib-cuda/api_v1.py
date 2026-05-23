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

        found_paths_with_versions =  {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        found_paths_with_version = {}

        for path in paths:
             path_lib = os.path.dirname(path)

             if uname == 'windows':
                 # Searching dynamic path
                 arch = os.path.basename(path_lib)
                 path_home = os.path.dirname(os.path.dirname(path_lib))
                 path_bin = os.path.join(path_home, 'bin', arch)
             else:
                 path_home = os.path.dirname(path_lib)
                 path_bin = os.path.join(path_home, 'bin')

             # Check versions
             version = None

             file_versions = os.path.join(path_home, 'version.json')
             if os.path.isfile(file_versions):
                 # FGG: it may happen in Docker containers with CUDA - they don't ship version.json ...

                 r = self.cm.utils.files.read_file(file_versions)
                 if self.cm.catch_error(r): return r

                 d = r['data']

                 version = d.get('cuda',{}).get('version')

             if not version:
                 version = 'default'

             paths = {}

             if uname == 'windows':
                 paths['dynamic_lib'] = path_bin
                 paths['qdynamic_lib'] = self.cm.q(path_bin)
                 paths['dynamic_libs'] = [path_bin]
             else:
                 paths['dynamic_lib'] = path_lib
                 paths['qdynamic_lib'] = self.cm.q(path_lib)
                 paths['dynamic_libs'] = [path_lib]

             paths['lib'] = path_lib
             paths['qlib'] = self.cm.q(path_lib)
             paths['libs'] = [path_lib]

             paths['home'] = path_home
             paths['qhome'] = self.cm.q(path_home)

             path_include = os.path.join(path_home, 'include')

             if os.path.isdir(path_include):
                 paths['include'] = path_include
                 paths['qinclude'] = self.cm.q(path_include)

                 paths['includes'] = [path_include]

             features = {
               'paths': paths,
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

#            if not _with.get('static', False):
# FGG: we need it both for static and dynamic libs

            features = result['features']

            path_dyn_lib = features['paths']['dynamic_lib']

            if os.path.isdir(path_dyn_lib):
                features['paths']['found_dynamic_lib_paths'] = [path_dyn_lib]

            lib_names = _with.get('lib_names')

            if lib_names:
                 features['lib_names'] = lib_names

        return {'return':0}
