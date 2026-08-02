"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
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

             path_includes = [path_include]

             path_home = os.path.dirname(path_include)

             path_bin = os.path.join(path_home, 'bin')

             path_lib = os.path.join(path_home, 'lib')

             if uname == 'windows':
                 path_lib = os.path.join(path_lib, 'VC', uarch)
             else:
                 found_lib = False

                 for x in ['lib64', 'lib']:
                     path_lib = os.path.join(path_home, x)
                     if os.path.isdir(path_lib):
                         matches = list(Path(path_lib).rglob("libssl.a"))
                         if matches:
                             found_lib = True
                             break

                         matches = list(Path(path_lib).rglob("libssl.so"))
                         if matches:
                             found_lib = True
                             break

                 if not found_lib:
                     continue

                 path_lib = os.path.dirname(matches[0])

             _path_lib = path_lib

             _libs = {}

             if os.path.isdir(_path_lib):
                 if uname == 'windows':
                     path_lib_dynamic = os.path.join(_path_lib, 'MD')
                     if os.path.isdir(path_lib_dynamic):
                         path_lib = path_lib_dynamic # Default lib

                     path_lib_dynamic_debug = os.path.join(_path_lib, 'MDd')
                     if os.path.isdir(path_lib_dynamic_debug):
                         _libs['libs_debug'] = [path_lib_dynamic_debug]

                     path_lib_static = os.path.join(_path_lib, 'MT')
                     if os.path.isdir(path_lib_static):
                         _libs['libs_static'] = [path_lib_static]

                     path_lib_static_debug = os.path.join(_path_lib, 'MTd')
                     if os.path.isdir(path_lib_static_debug):
                         _libs['libs_static_debug'] = [path_lib_static_debug]

             # Default libs
             path_libs = [path_lib]
             qpath_libs = [self.cm.q(path_lib)]

             lib_names = [
               'ssl', 
               'crypto'
             ]

             lib_names_static = []

             if uname == 'windows':
                 lib_names_static = [
                    'ssl_static', 
                    'crypto_static',
                    '$ws2_32',
                    '$crypt32',
                    '$advapi32',
                    '$user32',
                 ]
             elif uname == 'linux':
                 lib_names_static = [
                    'ssl', 
                    'crypto',
                    'z',
                    'm',
                    'zstd',
#                    'jitterentropy',
                 ]

             paths = {
                 'root': path_home,
                 'qroot': self.cm.q(path_home),
             }

             # FGG: bin is only needed on Windows for DLLs ...
             if uname == 'windows' and os.path.isdir(path_bin):
                 paths['dynamic_lib'] = path_bin
                 paths['qdynamic_lib'] = self.cm.q(path_bin)
                 paths['dynamic_libs'] = [path_bin]

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

        if result['return'] == 0 and not params.get('version_check', False):
            _with = params.get('with', {})
            
            if not _with.get('static', False):

                uname = ctx['tasks']['global']['host']['os']['uname']

                features = result['features']

                found_dynamic_libs = []

                if uname == 'windows':
                    path_dyn_lib = features['paths']['dynamic_lib']

                    if os.path.isdir(path_dyn_lib):
                        features['paths']['found_dynamic_lib_paths'] = [path_dyn_lib]

        return {'return':0}

