"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

RELEASES = 'https://github.com/facebook/zstd/releases/download'


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
        Windows: the pinned release zip (zstd-v<version>-win64.zip) into this cache entry.
        Other systems return 16 with the declarative install (distribution package, Homebrew).
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        if uname != 'windows' or uarch not in ('amd64', 'x86'):
            return {'return': 16, 'install_cmd': cmd, 'error': 'no zstd release binary for this system'}

        c = params.get('control', {})
        version = params.get('version_simple') or self.cdesc['default_version']
        bits = '64' if uarch == 'amd64' else '32'
        asset = f'zstd-v{version}-win{bits}.zip'

        content = os.path.join(os.getcwd(), 'content')
        path = os.path.join(content, 'zstd.exe')

        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run',
                            'arg1': 'download-file,03fed13e2e0447cf', 'ctx': ctx,
                            'url': f'{RELEASES}/v{version}/{asset}', 'directory': 'content',
                            'unzip': True, 'clean': True, 'clean_after_unzip': True, 'strip_folders': 1,
                            'check_file': path,
                            'con': c.get('con', False), 'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False)})
        if r['return'] > 0:
            return {'return': 16, 'install_cmd': cmd, 'error': f'zstd release download failed: {r.get("error")}'}

        return {'return': 0, 'install_cmd': None, 'found_path': path}
