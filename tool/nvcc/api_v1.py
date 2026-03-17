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
        Mostly used to update storage_key
        """

        result = {'return':0}

        return result

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

        uname = ctx['tasks']['global']['host']['os']['uname']
        uarch = ctx['tasks']['global']['host']['os']['uarch']

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        for p in paths:
            # Parsing standard output
            features = p.setdefault('features', {})

            path_nvcc = p['path']

            path_bin = os.path.dirname(path_nvcc)

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

        return {'return':0, 'paths':paths}

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
            _path.insert(0, cuda_bin)

            _result['result'] = result

        return _result
