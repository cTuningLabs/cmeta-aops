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
            self.logger.debug("RUNNING TOOL rclone api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            # Pinned in _desc.yaml so that bumping it needs no code change
            version = self.cdesc['default_version']
            version_simple = version

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install for rclone can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        # Map cMeta uname/uarch onto rclone's release asset naming.
        # Kept as plain lookups so that an unknown OS or architecture falls
        # through to the soft 16 below instead of leaving names unbound.
        uext = '.zip'
        uos = {'windows': 'windows', 'linux': 'linux', 'darwin': 'osx'}.get(uname)
        uarch2 = {'amd64': 'amd64', 'arm64': 'arm64'}.get(uarch)

        if not uos or not uarch2:
            return {
                'return': 16,
                'error': f'custom install for rclone could not create a download URL for {uname}/{uarch}',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        filename = f'rclone-v{version_simple}-{uos}-{uarch2}{uext}'

        # Both mirrors are passed to task/download-file, which walks them in
        # order and stops at the first success (templates live in _desc.yaml).
        urls = [t.format(version = version_simple, filename = filename)
                for t in self.cdesc['download_url_templates']]

        directory = 'content'

        path_to_tool = os.path.join(os.getcwd(), directory, 'rclone' + _global['host']['vars']['file_ext_exe'])

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            for url in urls:
                print (f'{space}INFO: Download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_tool}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'directory': directory,
              'url': urls,
              'env': env,
              'timeout': timeout,
              'con': con, 
              'quiet': quiet, 
              'verbose': verbose, 
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 1,
              'check_file': path_to_tool,
              'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
          'return': 0, 
          'install_cmd': None, 
          'found_path': path_to_tool,
        }


