"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The development files of Augeas: augeas.h has no version of its own, so the version is the one of
the pkg-config file installed with it (augeas.pc, "Version: 1.14.1"). A header without that file is
not taken: the build of python-augeas finds Augeas through pkg-config.
"""

import glob
import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# Where a distribution or brew puts augeas.pc, under the prefix of the include folder
PC_DIRS = ['lib/pkgconfig', 'lib64/pkgconfig', 'lib/*/pkgconfig', 'share/pkgconfig']


def pc_file(header):
    """augeas.pc of the installation that holds this augeas.h, or None."""

    prefix = os.path.dirname(os.path.dirname(header))

    for d in PC_DIRS:
        for p in sorted(glob.glob(os.path.join(prefix, d, 'augeas.pc'))):
            if os.path.isfile(p):
                return p

    return None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        The version of each augeas.h found: the "Version:" line of its augeas.pc.
        """

        found_paths_with_versions = {}

        for path in paths:
            pc = pc_file(path[1:] if path.startswith('!') else path)
            if not pc:
                continue

            r = self.cm.utils.files.read_file(pc)
            if self.cm.catch_error(r): return r

            m = re.search(r'^Version:\s*(\S+)', r['data'], re.MULTILINE)
            if not m:
                continue

            include = os.path.dirname(path[1:] if path.startswith('!') else path)

            features = {'paths': {'include': include, 'qinclude': self.cm.q(include), 'includes': [include],
                                  'pkgconfig': os.path.dirname(pc)}}

            found_paths_with_versions[path] = {'output': m.group(1), 'features': features}

        return {'return': 0, 'found_paths_with_versions': found_paths_with_versions}
