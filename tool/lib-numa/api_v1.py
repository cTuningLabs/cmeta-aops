"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

LIB_DIRS = ['/usr/lib/*-linux-gnu', '/usr/lib64', '/usr/lib', '/lib/*-linux-gnu', '/lib64', '/lib',
            '/usr/local/lib']


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        libnuma.so.1 in the library directories (or --tool_path); the version is the one of the
        file it resolves to (libnuma.so.1.0.0 -> 1.0.0).
        """

        uname = ctx['tasks']['global']['host']['os']['uname']
        if uname != 'linux':
            return {'return': 0, 'parsed_paths_with_versions': []}

        candidates = [params['tool_path']] if params.get('tool_path') else []
        for d in LIB_DIRS:
            candidates += glob.glob(os.path.join(d, 'libnuma.so.1'))

        parsed = []
        seen = set()
        for p in candidates:
            if not os.path.isfile(p):
                continue
            real = os.path.realpath(p)
            if real in seen:
                continue
            seen.add(real)
            m = re.search(r'libnuma\.so\.(\d+(?:\.\d+)*)$', os.path.basename(real))
            parsed.append({'path': p,
                           'detected_version': m.group(1) if m else '1',
                           'features': {'paths': {'lib': p, 'lib_dir': os.path.dirname(p), 'real': real}}})

        return {'return': 0, 'parsed_paths_with_versions': parsed}
