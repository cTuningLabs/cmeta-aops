"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import subprocess
import sys

from tool_c393ba5c6fa14f66.api.ctool import InitCTool


def has_c_headers(path_tool):
    """True when this gcc finds the C library's headers (it preprocesses #include <stdio.h>); True when it cannot
    be told (the gcc does not start here), as before."""
    try:
        r = subprocess.run([path_tool, '-E', '-x', 'c', '-'], input=b'#include <stdio.h>\n', stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return True
    return r.returncode == 0

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

        new_paths = []
        con = ctx['control'].get('con', False)

        for p in paths:
            # Parsing standard output
            features = p.setdefault('features', {})

            path_tool = p['path']
            path_bin = os.path.dirname(path_tool)

            # A gcc without its binutils (ar, as, ld) next to it builds nothing: not a candidate, so that the setup
            # installs the whole toolchain - before, the run stopped here (Azure Linux 3.0, whose gcc package came
            # without binutils into an instance made before the template listed them, 2026-10-17)
            path_tool_lib = os.path.join(path_bin, 'ar')
            if not os.path.isfile(path_tool_lib):
                if con:
                    print(f'cMeta warning: {path_tool} has no "ar" next to it (binutils missing) - not used')
                continue

            # Nor without the C library's headers (Linux): an Azure Linux instance had gcc and binutils but no
            # glibc-devel, and every C program stopped at "stdio.h: No such file" (2026-10-17)
            if sys.platform.startswith('linux') and not has_c_headers(path_tool):
                if con:
                    print(f'cMeta warning: {path_tool} finds no C library headers (stdio.h: glibc-devel, libc6-dev or '
                          f'musl-dev missing) - not used')
                continue

            _paths = {
               'bin': path_bin,
               'tool_lib': path_tool_lib,
               'qtool_lib': self.cm.q(path_tool_lib),
            }

            features_paths = features.setdefault('paths',{})
            features_paths.update(_paths)

            new_paths.append(p)

        return {'return':0, 'paths':new_paths}

