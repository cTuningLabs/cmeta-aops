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
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        Mostly used to update storage_key and prepare deps (uses)
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL nvcc api_v1 init")

        uname = ctx['tasks']['global']['host']['os']['uname']

        if uname == 'darwin':
            return self.cm.error(f'tool "nvcc" does not support MacOS')

        compiler_extra_tags = params.get('with', {}).get('compiler_extra_tags')
        compiler_extra_match = params.get('with', {}).get('compiler_extra_match')

        if compiler_extra_match is None or compiler_extra_match == '': 
            compiler_extra_match = {}

        # Add host compiler such as GCC, LLVM, MSVC if needed ...
        supports_nvcc_os = compiler_extra_match.setdefault('supports_nvcc_os', []) 
        if uname not in supports_nvcc_os:
            supports_nvcc_os.append(uname)

        ctx['tasks']['local']['compiler_extra_tags'] = compiler_extra_tags
        ctx['tasks']['local']['compiler_extra_match'] = compiler_extra_match

        return {'return':0}

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL nvcc api_v1 check_features")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        uname = ctx['tasks']['global']['host']['os']['uname']
        uarch = ctx['tasks']['global']['host']['os']['uarch']

        new_paths = []

        compute_cap_int_min = ctx['tasks']['global']['cuda']['features']['compute_cap_int_min']
        compute_cap_int_max = ctx['tasks']['global']['cuda']['features']['compute_cap_int_max']

        for p in paths:
            # Parsing standard output
            features = p.setdefault('features', {})

            path_nvcc = p['path']
            path_bin = os.path.dirname(path_nvcc)

            # Check supported arch
            cmd = self.cm.q(path_nvcc) + ' --list-gpu-arch --list-gpu-code'

            ii = {'category': 'task,c36be4b9314a45e0',
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'timeout': timeout,
                  'con': con, 
                  'quiet': quiet,
                  'verbose': verbose, 
                  'text_cmd': 'RUN:', 
                  'capture_output': True,
                  # Important to be able to continue processing detect/install/build
                  'fail_if_nonzero_return_code': False, 
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']                                            

            if returncode>0:
                # If can't detect capabilities - skip
                continue

            else:
                farch = []
                fcode = []

                for s in rx['stdout'].strip().splitlines():
                    ss = s.split(',')
                    if len(ss) == 2:
                        sa = ss[0]
                        sc = ss[1]

                        if sa.startswith('arch=compute_'):
                            farch.append(int((sa[13:])))
                            if sc.startswith('code=sm_'):
                                fcode.append(int(sc[8:]))

                features['supported_arch'] = farch
                features['supported_arch_min'] = min(farch)
                features['supported_arch_max'] = max(farch)

                features['supported_code'] = fcode
                features['supported_code_min'] = min(fcode)
                features['supported_code_max'] = max(fcode)

                # Prepare common gencode flags based on my device capabilities and NVCC capabilities
                xarch = compute_cap_int_min if compute_cap_int_min < features['supported_arch_max'] else features['supported_arch_max']
                xcode = compute_cap_int_min if compute_cap_int_min < features['supported_code_max'] else features['supported_code_max']

                features['auto_gencode_flag'] = f'-gencode arch=compute_{xarch},code=sm_{xcode}'

            # Finish checking various features

            _paths = {
               'bin': path_bin,
               'bins': [path_bin],
               'libs': [],
               'includes': [],
               'cmakes': [],
            }

            path_home = os.path.dirname(path_bin)
            _paths['home'] = path_home


            path_include = os.path.join(path_home, 'include')
            if os.path.isdir(path_include):
                _paths['include'] = path_include
                _paths['includes'].append(path_include)

            if uname == 'windows' and uarch == 'amd64':
                path_dll = os.path.join(path_bin, 'x64')
                if os.path.isdir(path_dll):
                    _paths['bins'].append(path_dll)

                path_lib = os.path.join(path_home, 'lib', 'x64')
                if os.path.isdir(path_lib):
                    _paths['lib'] = path_lib
                    _paths['libs'].append(path_lib)

                path_cmake = os.path.join(path_home, 'lib', 'cmake')
                if os.path.isdir(path_cmake):
                    _paths['cmake'] = path_cmake
                    _paths['cmakes'].append(path_cmake)

            path_nvvm = os.path.join(path_home, 'nvvm')
            if os.path.isdir(path_nvvm):
                _paths['nvvm'] = path_nvvm

            path_nvvm_bin = os.path.join(path_nvvm, 'bin')
            if os.path.isdir(path_nvvm_bin):
                _paths['nvvm_bin'] = path_nvvm_bin
                _paths['bins'].append(path_nvvm_bin)

            path_nvvm_include = os.path.join(path_nvvm, 'include')
            if os.path.isdir(path_nvvm_include):
                _paths['nvvm_include'] = path_nvvm_include
                _paths['includes'].append(path_nvvm_include)

            if uname == 'windows' and uarch == 'amd64':
                nvvm_path_lib = os.path.join(path_nvvm, 'lib', 'x64')
                if os.path.isdir(nvvm_path_lib):
                    _paths['nvvm_path_lib'] = nvvm_path_lib
                    _paths['libs'].append(nvvm_path_lib)

            features_paths = features.setdefault('paths',{})
            features_paths.update(_paths)

            # Check versions
            file_versions = os.path.join(path_home, 'version.json')
            if os.path.isfile(file_versions):
                r = self.cm.utils.files.read_file(file_versions)
                if self.cm.catch_error(r): return r

                features_versions = features.setdefault('versions', {})
                features_versions.update(r['data'])

            new_paths.append(p)

        return {'return':0, 'paths':new_paths}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _with = params.get('with',{})

        _result = {'return':0}

        if _with.get('add_env', False):
            features_paths = result['features']['paths']

            cuda_home = features_paths['home']
            cuda_bin = features_paths['bin']

            _aggregate = result.setdefault('_aggregate', {})
            _aggregate_env = _aggregate.setdefault('env',{})

            _aggregate_env['CUDA_HOME'] = cuda_home
            _aggregate_env['CUDA_PATH'] = cuda_home

            _path = _aggregate_env.setdefault('+PATH', [])
            if cuda_bin not in _path:
                _path.insert(0, cuda_bin)

            _result['result'] = result

        return _result
