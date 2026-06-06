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
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """

        name = self.cdesc['name']

        # FGG: extension depends on target / compiler and not just on host
        # For example Android on Windows will have .so and not .dll ...

        _with = params.setdefault('with', {})

#        if 'static' not in _with:
#            _with['static'] = False
#
#        if 'debug_info' not in _with:
#            _with['debug_info'] = False

        compute = _with.get('compute')
        if not compute:
            compute = ctx['tasks']['global'].get('target',{}).get('compute')
        if not compute:
            compute = ['cpu']

        if type(compute) == str:
            compute = compute.split(',')

        _with['compute'] = compute
        ctx['tasks']['local']['compute'] = compute

        if 'android-cpu' in compute:
            name += ''
        else:
            if 'compiler-c' in ctx['tasks']['global']:
                name += ctx['tasks']['global']['compiler-c']['features']['vars']['file_ext_exe']
            else:
                name += ctx['tasks']['global']['host']['vars']['file_ext_exe']

        ctx['tasks']['local']['tool_name'] = name

        # Check if Android
        k = 'target--android-cpu'
        target_abi = _with.get('android_abi')
        if not target_abi:
            if k in ctx['tasks']['global']:
                target_abi = ctx['tasks']['global'][k]['features']['ro.product.cpu.abi']

        ctx['tasks']['local']['target_abi'] = target_abi

        return {'return': 0}

    ############################################################
    def customize_build(self,
                        ctx,
                        misc
    ):
        """
        """

        result = {'return':0}

        version = misc.get('version')

        if version:
            checkout = f'b{version}'

            result['add_to_local'] = {'checkout': checkout}

        return result


    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        """
        # We need to update paths and dynamic libs here from compilation context
        # before llama-cpp is called to detect version since it may miss dynamic libs

        _static = params.get('with',{}).get('static', False)

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        found_paths_with_versions =  {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        _with = params.get('with', {})
        _static = _with.get('static', False)
        _debug_info = _with.get('debug_info', False)

        target_compute = ctx['tasks']['local']['compute']

        _android_cpu = True if 'android-cpu' in target_compute else False
        _cuda = True if 'cuda' in target_compute else False

        _cpu = False
        if 'cpu' in target_compute:
            _cpu = True
        if _android_cpu: 
            _cpu = False

        found_paths_info = {}

        result = {'return':0}

        for path in paths:
#            Actually, even if compiled as static, it may pick up and link dynamically compiled libs from cMeta!
#            if not _static:
            # Attempt to load cMeta compilation context
            # (if was compiled via cMeta)

            path_bin = os.path.dirname(path)
            path_root = os.path.dirname(path_bin)
            path_repro_compile = os.path.join(path_root, '_repro_ctx_compile.json')

            if os.path.isfile(path_repro_compile):
                r = self.cm.utils.files.read_file(path_repro_compile)
                if r['return'] == 0:
                    _compiled_state = r['data']
                    if _compiled_state.get('result', {}).get('return') == 0:
                        _compiled_state_local = _compiled_state.get('ctx', {}).get('tasks', {}).get('local', {})
                        if _compiled_state_local:
                            sdl = _compiled_state_local.get('setup-dynamic-libs', {})
                            fdlp = sdl.get('found_dynamic_lib_paths')
                            if fdlp:
                                found_paths_info[path] = {'features': {'paths':{'found_dynamic_lib_paths': fdlp}, 'with': _with}}

        if found_paths_info:
            result['found_paths_info'] = found_paths_info

        return result

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL llama-cpp api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        _with = params.setdefault('with', {})

        target = ctx['tasks']['global'].get('target', {})

        compute = _with.get('compute')
        if not compute:
            compute = target.get('compute')
        if not compute:
            compute = ['cpu']
        if type(compute) == str:
            compute = compute.split(',')

        _cuda = 'cuda' in compute
        _metal = 'metal' in compute
        _rocm = 'rocm' in compute

        # Forces sub-version for CUDA, ROCm, etc 
        ver = _with.get('ver')

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            version = self.cdesc['default_version']
            version_simple = version

        if not version_simple:
            return {
                'return': 16,
                'error': f'custom install for llama.cpp can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd,
            }

        # Prepare some vars depending on versions
        iversion_simple = int(version_simple) # can be done for llama.cpp sice it's version is int but not necessarily for others that have x.y.z string structure
        if iversion_simple >= 9365:
           cuda_vers = ['13.3', '12.4']
        elif iversion_simple >= 7313:
           cuda_vers = ['13.1', '12.4']
        else:
           cuda_vers = ['12.4']

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        # CUDA version used when selecting CUDA-enabled binaries
        url = None
        filename = None
        filename2 = None

        if uname == 'windows':
            if uarch == 'arm64':
                filename = f'llama-b{version_simple}-bin-win-cpu-arm64.zip'
            elif uarch == 'amd64':
                if _cuda:
                    compute_features = target.get('features', {}).get('cuda', {})
                    if not ver:
                        ver = compute_features.get('ver')
                    if ver:
                        found = True
                    else:
                        cuda_version = compute_features.get('versions', {}).get('cuda version')

                        found = False

                        if cuda_version:
                            for ver in cuda_vers:
                                r = self.cm.utils.common.compare_versions(cuda_version, ver)
                                if r['return'] == 0 and (r['comparison'] == '>' or r['comparison'] == '='):
                                    found = True
                                    break

                    if found:
                        filename = f'llama-b{version_simple}-bin-win-cuda-{ver}-x64.zip'
                        filename2 = f'cudart-llama-bin-win-cuda-{ver}-x64.zip'
                else:
                    filename = f'llama-b{version_simple}-bin-win-cpu-x64.zip'
        elif uname == 'linux':
            if uarch == 'amd64':
#                if _cuda:
#                    filename = f'llama-b{version_simple}-bin-ubuntu-cuda-cu{cuda_version}-x64.tar.gz'
#                elif _rocm:
#                    filename = f'llama-b{version_simple}-bin-ubuntu-rocm-x64.tar.gz'
#                else:
                filename = f'llama-b{version_simple}-bin-ubuntu-x64.tar.gz'
            elif uarch == 'arm64':
                filename = f'llama-b{version_simple}-bin-linux-arm64.tar.gz'
        elif uname == 'darwin':
            if uarch == 'arm64':
                # Metal is the default backend on Apple Silicon
                filename = f'llama-b{version_simple}-bin-macos-arm64.tar.gz'
            elif uarch == 'amd64':
                filename = f'llama-b{version_simple}-bin-macos-x64.tar.gz'

        if not filename:
            return {
                'return': 16,
                'error': f'custom install for llama.cpp could not create download URL for compute={compute}, uname={uname}, uarch={uarch}',
                'install_cmd': cmd,
            }

        url = f'https://github.com/ggml-org/llama.cpp/releases/download/b{version_simple}/{filename}'

        directory = 'content'
        name = self.cdesc.get('name', 'llama-cli')
        path_to_llama = os.path.join(os.getcwd(), directory, name + _global['host']['vars']['file_ext_exe'])

        if filename2:
            url2 = f'https://github.com/ggml-org/llama.cpp/releases/download/b{version_simple}/{filename2}'

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: llama.cpp download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_llama}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'env': env,
              'timeout': timeout,
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'check_file': path_to_llama,
              'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        ###########################################################################################
        # Attempt to download extra file

        if filename2:

            ii['url'] = url2
            del(ii['clean'])
            del(ii['check_file'])
            del(ii['make_check_file_executable'])

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx


        return {
          'return': 0,
          'install_cmd': None,
          'found_path': path_to_llama,
          'version': version,
        }


