"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The development files of Augeas: augeas.h has no version of its own, so the version is the one of
the pkg-config file installed with it (augeas.pc, "Version: 1.14.1"). A header without that file is
not taken. The features give the include folder and the library folder (beside the pkgconfig folder):
the build of python-augeas asks pkg-config for libxml2 only, so a pip tool that builds it passes them
on (common_pyvenv's c_libraries) - needed where they are not the compiler's own, as Homebrew's.
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


def library_folder(pc_dir):
    """The folder of the library beside a pkgconfig folder: lib, lib64 or lib/<triplet>; share/pkgconfig: <prefix>/lib."""

    lib = os.path.dirname(pc_dir)
    if os.path.basename(lib).startswith('lib') or os.path.basename(os.path.dirname(lib)).startswith('lib'):
        return lib
    return os.path.join(os.path.dirname(lib), 'lib')


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

            pc_dir = os.path.dirname(pc)
            lib = library_folder(pc_dir)

            features = {'paths': {'include': include, 'qinclude': self.cm.q(include), 'includes': [include],
                                  'pkgconfig': pc_dir, 'lib': lib, 'libs': [lib]}}

            found_paths_with_versions[path] = {'output': m.group(1), 'features': features}

        return {'return': 0, 'found_paths_with_versions': found_paths_with_versions}
