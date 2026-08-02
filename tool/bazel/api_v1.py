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
        Download a prebuilt Bazel binary from GitHub releases (any OS/arch).
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL bazel api_v1 install")

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        uname = _global['host']['os']['uname']            # windows | linux | darwin
        uarch = _global['host']['os']['uarch']            # amd64 | arm64
        exe   = _global['host']['vars']['file_ext_exe']   # ".exe" on Windows else ""

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            # Default pinned version when the user didn't request one
            version = '7.4.1'
            version_simple = version

        if not version_simple:
            # Only exact/simple versions map to a release asset.
            # Return 16 + the original cmd so setup can fall back to install_cmd (none here).
            return {
                'return': 16,
                'error': f'custom install for "bazel" needs an exact version in "{__file__}"',
                'install_cmd': cmd,
            }

        con     = params.get('control', {}).get('con', False)
        quiet   = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space   = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env     = params.get('env')
        timeout = params.get('timeout')

        # Map cMeta OS/arch -> Bazel asset naming
        if uarch == 'amd64':
            uarch2 = 'x86_64'
        elif uarch == 'arm64':
            uarch2 = 'arm64'
        else:
            uarch2 = None

        uos = {'windows': 'windows', 'linux': 'linux', 'darwin': 'darwin'}.get(uname)

        if not uos or not uarch2:
            return {
                'return': 16,
                'error': f'custom install for "bazel" could not build a download URL for {uname}/{uarch}',
                'install_cmd': cmd,
            }

        asset = f'bazel-{version_simple}-{uos}-{uarch2}{exe}'
        url   = f'https://github.com/bazelbuild/bazel/releases/download/{version_simple}/{asset}'

        directory = 'content'
        # Save under a stable name so detection (names: bazel{{ext}}) finds it
        path_to_tool = os.path.join(os.getcwd(), directory, 'bazel' + exe)

        if con:
            print ('')
            print (f'{space}INFO: Current path: {os.getcwd()}')
            print (f'{space}INFO: Bazel download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_tool}')
            print ('')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'filename': 'bazel' + exe,        # rename the versioned asset -> "bazel"
              'env': env,
              'timeout': timeout,
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'unzip': False,                   # single binary, nothing to extract
              'clean': True,
              'check_file': path_to_tool,
              'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
          'return': 0,
          'install_cmd': None,                  # tell setup NOT to run a shell install
          'found_path': path_to_tool,
        }
