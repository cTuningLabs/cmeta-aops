"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        new_paths = []

        for p in paths:
            features = p.setdefault('features', {})
            paths = features.setdefault('paths', {})

            path = p['path']

            path_bin = os.path.dirname(path)
            path_home = os.path.dirname(path_bin)

            paths['bin'] = path_bin
            paths['qbin'] = self.cm.q(path_bin)

            paths['home'] = path_home
            paths['qhome'] = self.cm.q(path_home)

            new_paths.append(p)

        return {'return':0, 'paths':new_paths}


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
            self.logger.debug("RUNNING TOOL llvm api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version = params.get('version')
        version_simple = params.get('version_simple')
        version_major = params.get('version_major')

        if not version:
            version = self.cdesc['default_version']
            version_simple = version
            version_major = version_simple[:2]

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install for LLVM can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        url = None
        filename = None

        if uname == 'windows':
            if uarch == 'amd64':
                uarch2 = 'x86_64'
                filename = f'clang+llvm-{version_simple}-{uarch2}-pc-windows-msvc.tar.xz'
        elif uname == 'linux':
            if uarch == 'amd64':
                uarch2 = 'X64'
                filename = f'LLVM-{version_simple}-Linux-{uarch2}.tar.xz'
        elif uname == 'darwin':
            if uarch == 'arm64':
                uarch2 = 'ARM64'
                filename = f'LLVM-{version_simple}-macOS-{uarch2}.tar.xz'

        if not filename:
            return {
                'return': 16, 
                'error': f'custom install for LLVM could not create download URL',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        url = f'https://github.com/llvm/llvm-project/releases/download/llvmorg-{version_simple}/{filename}'

        directory = 'content'
        path_to_clang = os.path.join(os.getcwd(), directory, 'bin', 'clang' + _global['host']['vars']['file_ext_exe'])

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: LLVM download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_clang}')

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
              'strip_folders': 1,
              'check_file': path_to_clang,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
          'return': 0, 
          'install_cmd': None, 
          'found_path': path_to_clang, 
          'version': version,
        }


