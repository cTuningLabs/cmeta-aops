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
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Downloads the official kubectl binary from dl.k8s.io.
        Falls back to the _desc.yaml install_cmd (snap/brew/winget) if the
        version is not a simple x.y.z string.
        """

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version        = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            version        = '1.31.0'
            version_simple = version

        if not version_simple:
            # Non-simple version (e.g. pre-release): let the yaml install_cmd handle it
            return {
                'return': 16,
                'error': f'custom install for kubectl requires an exact x.y.z version in "{__file__}"',
                'install_cmd': cmd,
            }

        con     = params.get('control', {}).get('con', False)
        quiet   = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        env     = params.get('env')
        timeout = params.get('timeout')

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        # Map cMeta uname/uarch to kubectl's release naming
        if uname == 'windows':
            uos  = 'windows'
            uext = '.exe'
        elif uname == 'linux':
            uos  = 'linux'
            uext = ''
        elif uname == 'darwin':
            uos  = 'darwin'
            uext = ''
        else:
            return {'return': 16, 'error': f'unsupported OS for kubectl download: {uname}'}

        if uarch == 'amd64':
            uarch2 = 'amd64'
        elif uarch == 'arm64':
            uarch2 = 'arm64'
        else:
            return {'return': 16, 'error': f'unsupported architecture for kubectl download: {uarch}'}

        filename = f'kubectl{uext}'
        url = f'https://dl.k8s.io/release/v{version_simple}/bin/{uos}/{uarch2}/{filename}'

        directory       = 'content'
        path_to_kubectl = os.path.join(os.getcwd(), directory, filename)

        if con:
            cur_dir = os.getcwd()
            print('')
            print(f'{space}INFO: Current path: {cur_dir}')
            print(f'{space}INFO: kubectl download URL: {url}')
            print(f'{space}INFO: Check file: {path_to_kubectl}')

        # kubectl is a single binary — no archive to unzip
        ii = {
            'category': 'task,c36be4b9314a45e0',
            'command': 'run',
            'arg1': 'download-file,03fed13e2e0447cf',
            'ctx': ctx,
            'directory': directory,
            'url': url,
            'env': env,
            'timeout': timeout,
            'con': con,
            'quiet': quiet,
            'verbose': verbose,
            'unzip': False,
            'clean': True,
            'check_file': path_to_kubectl,
            'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
            'return': 0,
            'install_cmd': None,
            'found_path': path_to_kubectl,
        }
