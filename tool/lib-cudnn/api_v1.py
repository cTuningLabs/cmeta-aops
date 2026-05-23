"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import re

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

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL cudnn api_v1 detect_versions")

        found_paths_with_versions = {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        uarch = ctx['tasks']['global']['host']['os']['uarch']
        if uarch == 'amd64':
            uarch = 'x64'

        nvcc = ctx['tasks']['global']['nvcc']
        cuda_version = nvcc['version']

        for path in paths:
             path_include = os.path.dirname(path)

             possible_cuda_ver = os.path.basename(path_include)
             cuda_ver = possible_cuda_ver if bool(re.fullmatch(r"\d[\d.]*", possible_cuda_ver)) else None

             # Prune by cuda ver
             if cuda_ver:
                 cuda_version_split = cuda_version.split('.')
                 cuda_ver_split = cuda_ver.split('.')

                 cuda_major_version = int(cuda_version_split[0])
                 cuda_major_ver = int(cuda_ver_split[0])
                 if cuda_major_ver != cuda_major_version:
                     continue

                 # Check cuda minor version ... (should be lower)
                 cuda_minor_version = int(cuda_version_split[1])
                 cuda_minor_ver = int(cuda_ver_split[1])

                 if cuda_minor_ver > cuda_minor_version:
                     continue

             path_cudnn_version = os.path.join(path_include, 'cudnn_version.h')
             if os.path.isfile(path_cudnn_version):
                 path_home = os.path.dirname(os.path.dirname(path_include)) if cuda_ver else os.path.dirname(path_include)

                 path_bin = os.path.join(path_home, 'bin')
                 if cuda_ver: 
                     path_bin = os.path.join(path_bin, cuda_ver)
                     if os.path.isdir(path_bin):
                         path_bin2 = os.path.join(path_bin, uarch)
                         if os.path.isdir(path_bin2):
                             path_bin = path_bin2

                 for x in ['lib64', 'lib']:
                     path_lib = os.path.join(path_home, x)
                     if os.path.isdir(path_lib):
                         if cuda_ver: 
                             path_lib2 = os.path.join(path_lib, cuda_ver)
                             if os.path.isdir(path_lib2):
                                 path_lib = path_lib2

                             if os.path.isdir(path_lib):
                                 path_lib2 = os.path.join(path_lib, uarch)
                                 if os.path.isdir(path_lib2):
                                     path_lib = path_lib2
                         break


                 r = self.cm.utils.files.read_file(path_cudnn_version)
                 if self.cm.catch_error(r): return r

                 s = r['data']

                 cudnn_version_major = int(re.search(r"#define\s+CUDNN_MAJOR\s+(\d+)", s).group(1))
                 cudnn_version_minor = int(re.search(r"#define\s+CUDNN_MINOR\s+(\d+)", s).group(1))
                 cudnn_version_patch = int(re.search(r"#define\s+CUDNN_PATCHLEVEL\s+(\d+)", s).group(1))
                 version = str(cudnn_version_major) + '.' + str(cudnn_version_minor) + '.' + str(cudnn_version_patch)

                 features = {}

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

                 lib_names = []

                 if os.path.isdir(path_include):
                     paths['include'] = path_include
                     paths['qinclude'] = self.cm.q(path_include)

                     paths['includes'] = [path_include]

                 lib_names = [
                    '$cudnn' # $ means that do not add lib prefix ...
                 ]

                 features = {
                   'paths': paths,
                 }

                 if lib_names:
                     features['lib_names'] = lib_names

                 if cuda_version:
                     features['cuda_version'] = cuda_version


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

            features = result['features']

            path_dyn_lib = features['paths']['dynamic_lib']

            if os.path.isdir(path_dyn_lib):
                features['paths']['found_dynamic_lib_paths'] = [path_dyn_lib]

        return {'return':0}
