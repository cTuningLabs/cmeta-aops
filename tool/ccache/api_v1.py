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
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL cmake api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            version = '4.13.6'
            version_simple = version

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install for ccache can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        # Upstream assets (4.13+): ccache-<v>-windows-{x86_64,aarch64}.zip,
        # ccache-<v>-linux-{x86_64,aarch64,riscv64}-{glibc,musl-static}.tar.xz and one
        # universal ccache-<v>-darwin.tar.gz; before 4.13 the Linux names had no libc part.
        url = None
        filename = None

        uarch2 = {'amd64': 'x86_64', 'arm64': 'aarch64', 'aarch64': 'aarch64', 'riscv64': 'riscv64'}.get(uarch)

        try:
            new_scheme = [int(x) for x in version_simple.split('.')[:2]] >= [4, 13]
        except ValueError:
            new_scheme = True

        if uname == 'windows' and uarch2 in ('x86_64', 'aarch64'):
            filename = f'ccache-{version_simple}-windows-{uarch2}.zip'
        elif uname == 'linux' and uarch2:
            libc = '-musl-static' if _global['host'].get('os_extra', {}).get('id') == 'alpine' else '-glibc'
            filename = f'ccache-{version_simple}-linux-{uarch2}{libc if new_scheme else ""}.tar.xz'
        elif uname == 'darwin':
            filename = f'ccache-{version_simple}-darwin.tar.gz'

        if not filename:
            return {
                'return': 16,
                'error': f'ccache publishes no prebuilt binary for {uname}/{uarch}',
                'install_cmd': cmd, # fall back to the declarative install, if any
            }

        url = f'https://github.com/ccache/ccache/releases/download/v{version_simple}/{filename}'

        directory = 'content'

        path_to_cmake = os.path.join(os.getcwd(), directory, 'ccache' + _global['host']['vars']['file_ext_exe'])

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: cMake download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_cmake}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
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
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 1,
              'check_file': path_to_cmake,
              'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
          'return': 0, 
          'install_cmd': None, 
          'found_path': path_to_cmake,
        }


