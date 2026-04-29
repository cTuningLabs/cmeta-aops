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

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL openssl api_v1 detect_versions")

        found_paths_with_versions =  {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        uarch = ctx['tasks']['global']['host']['os']['uarch']
        if uarch == 'amd64':
            uarch = 'x64'

        for path in paths:
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

             path_include = os.path.dirname(os.path.dirname(path))

             path_home = os.path.dirname(path_include)

             path_bin = os.path.join(path_home, 'bin')

             path_lib = os.path.join(path_home, 'lib')
             if uname == 'windows':
                 path_lib = os.path.join(path_lib, 'VC', uarch)
             else:
                 matches = list(Path(path_lib).rglob("libssl.a"))
                 if not matches or len(matches)>1:
                     continue

                 path_lib = os.path.dirname(matches[0])

             path_libs = {}

             _path_lib = path_lib

             if os.path.isdir(_path_lib):
                 if uname == 'windows':
                     path_lib_dynamic = os.path.join(_path_lib, 'MD')
                     if os.path.isdir(path_lib_dynamic):
                         path_libs['dynamic'] = path_lib_dynamic
                         path_libs['qdynamic'] = self.cm.q(path_lib_dynamic)
                         path_lib = path_lib_dynamic # Default lib

                     path_lib_dynamic_debug = os.path.join(_path_lib, 'MDd')
                     if os.path.isdir(path_lib_dynamic_debug):
                         path_libs['dynamic_debug'] = path_lib_dynamic_debug
                         path_libs['qdynamic_debug'] = self.cm.q(path_lib_dynamic_debug)

                     path_lib_static = os.path.join(_path_lib, 'MT')
                     if os.path.isdir(path_lib_static):
                         path_libs['static'] = path_lib_static
                         path_libs['qstatic'] = self.cm.q(path_lib_static)

                     path_lib_static_debug = os.path.join(_path_lib, 'MTd')
                     if os.path.isdir(path_lib_static_debug):
                         path_libs['static_debug'] = path_lib_static_debug
                         path_libs['qstatic_debug'] = self.cm.q(path_lib_static_debug)

                 else:
                     path_libs['dynamic'] = path_lib
                     path_libs['qdynamic'] = self.cm.q(path_lib)
                     path_libs['static'] = path_lib
                     path_libs['qstatic'] = self.cm.q(path_lib)


             paths = {
                 'root': path_home,
                 'qroot': self.cm.q(path_home),
             }

             # FGG: bin is only needed on Windows for DLLs ...
             if uname == 'windows' and os.path.isdir(path_bin):
                 paths['bin'] = path_bin
                 paths['qbin'] = self.cm.q(path_bin)

             if os.path.isdir(path_include):
                 paths['include'] = path_include
                 paths['qinclude'] = self.cm.q(path_include)

             if os.path.isdir(path_lib):
                 paths['lib'] = path_lib
                 paths['qlib'] = self.cm.q(path_lib)

             if path_libs:
                 paths['libs'] = path_libs

             features = {'paths': paths}

             found_paths_with_versions[path] = {'output':version, 'features':features}

        return {'return':0, 'found_paths_with_versions':found_paths_with_versions}
