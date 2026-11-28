"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup libc-static": the static C library of a Linux system (libc.a), which a static link
needs. It is found by asking the C compiler of the run where its libc.a is (-print-file-name: the
compiler's own search, the same one its linker makes); when there is none, the distribution's package
is installed (_desc.yaml: package_name_os_id, with the repository that holds it where that one is not
enabled by default). Nothing is added to a program's link.
"""

import os
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_static_lib import c_compiler

LIBRARY = 'libc.a'


def libc_version():
    """The version of the system's C library when it says one (glibc: "2.39"), else "0"."""

    try:
        text = os.confstr('CS_GNU_LIBC_VERSION') or ''
    except (AttributeError, ValueError, OSError):
        text = ''

    parts = text.split()

    return parts[1] if len(parts) == 2 and parts[0] == 'glibc' else '0'


def static_library_of(cc):
    """The libc.a that the compiler `cc` links, or None: what "<cc> -print-file-name=libc.a" answers
    (the full path when the compiler finds the file, the bare name when it does not)."""

    try:
        p = subprocess.run([cc, '-print-file-name=' + LIBRARY], capture_output = True, text = True, errors = 'replace',
                           stdin = subprocess.DEVNULL, timeout = 60)
    except (OSError, subprocess.SubprocessError):
        return None

    path = (p.stdout or '').strip()

    return os.path.realpath(path) if p.returncode == 0 and os.path.isabs(path) and os.path.isfile(path) else None


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
        The libc.a of the run's C compiler (the program's, else the one cMeta selects), or --tool_path.
        """

        if ctx['tasks']['global']['host']['os']['uname'] != 'linux':
            return {'return': 0, 'parsed_paths_with_versions': []}

        path = params.get('tool_path')

        if not path:
            r = c_compiler(self, ctx, params)
            if r['return'] > 0:
                return r

            path = static_library_of(r['compiler']['path'])

        if not path or not os.path.isfile(path):
            return {'return': 0, 'parsed_paths_with_versions': []}

        return {'return': 0, 'parsed_paths_with_versions': [
            {'path': path, 'detected_version': libc_version(),
             'features': {'paths': {'lib': path, 'lib_dir': os.path.dirname(path)}}}]}

    ############################################################
    def customize_install_cmd(self,
                              ctx: dict,
                              install_cmd: str = None,
                              params: dict = {},
                              env: dict = {},
                              timeout: int = None,
                              *misc: dict,
    ):
        """
        The package of this distribution, with its repository enabled for the install where the
        distribution keeps the package in one that is off by default (package_repo_os_id).
        """

        os_id = str(ctx['tasks']['global']['host'].get('os_extra', {}).get('id', '')).lower()
        repo = (self.cdesc.get('package_repo_os_id') or {}).get(os_id)

        if not repo:
            return {'return': 0}

        name = (self.cdesc.get('package_name_os_id') or {}).get(os_id) or self.cdesc.get('package_name')

        return {'return': 0, 'package_name': f'--enablerepo={repo} {name}'}
