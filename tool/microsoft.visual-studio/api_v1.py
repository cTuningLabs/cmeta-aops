"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import os
import shutil
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# winget packages of Visual Studio Build Tools by release year (--with.year); the newest first
BUILD_TOOLS_WINGET_IDS = {
    '2026': 'Microsoft.VisualStudio.BuildTools',
    '2022': 'Microsoft.VisualStudio.2022.BuildTools',
    '2019': 'Microsoft.VisualStudio.2019.BuildTools',
    '2017': 'Microsoft.VisualStudio.2017.BuildTools',
}

VCVARS_DIR = os.path.join('VC', 'Auxiliary', 'Build')


def vswhere_installations():
    """
    The installation folders of every Visual Studio 2017+ (any edition, Build Tools included,
    on any drive), as the Visual Studio Installer's vswhere lists them; [] without vswhere.
    """
    candidates = [shutil.which('vswhere')]
    for pf in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles')):
        if pf:
            candidates.append(os.path.join(pf, 'Microsoft Visual Studio', 'Installer', 'vswhere.exe'))
    vswhere = next((c for c in candidates if c and os.path.isfile(c)), None)
    if not vswhere:
        return []
    try:
        out = subprocess.run([vswhere, '-all', '-products', '*', '-property', 'installationPath', '-utf8'],
                             capture_output = True, timeout = 60)
    except Exception:
        return []
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.decode('utf-8', 'replace').splitlines() if line.strip()]


def standard_installations():
    """Visual Studio folders in the usual places: <Program Files[ (x86)]>\\Microsoft Visual Studio\\<year>\\<edition>."""
    roots = [os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'),
             r'D:\Program Files', r'D:\Program Files (x86)']
    found = []
    for root in dict.fromkeys(r for r in roots if r):
        found += sorted(glob.glob(os.path.join(root, 'Microsoft Visual Studio', '*', '*')))
    return found


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def find_paths(self,
                   ctx: dict,
                   params: dict = {},
    ):
        """
        The vcvars scripts of all Visual Studio installations with the C++ tools. vswhere lists
        them wherever they are (Build Tools go to Program Files (x86), Visual Studio 2026 can be
        on another drive); the usual folders are searched too, and the extra_paths of _desc.yaml
        (a recursive search) only when nothing else is found.
        """

        bits = ctx['tasks']['global']['host']['os'].get('bits') or '64'
        name = f'vcvars{bits}.bat'

        found = []
        seen = set()

        def add(path):
            key = os.path.normcase(os.path.normpath(path))
            if key not in seen and os.path.isfile(path):
                seen.add(key)
                found.append(path)

        for install_dir in vswhere_installations() + standard_installations():
            add(os.path.join(install_dir, VCVARS_DIR, name))

        if not found:
            for pattern in self.cdesc.get('extra_paths', {}).get('windows', []):
                for path in glob.glob(os.path.join(pattern, name), recursive = True):
                    add(path)

        return {'return': 0, 'found_paths': found}

    ############################################################
    def customize_install_cmd(self,
                              ctx: dict,
                              install_cmd: str,
                              params: dict,
                              env: dict,
                              timeout,
                              uninstall_cmd: str = None,
    ):
        """
        The winget package of the Build Tools release: the newest (2026) unless --with.year.
        """

        year = str(params.get('with', {}).get('year') or '2026')
        winget_id = BUILD_TOOLS_WINGET_IDS.get(year)
        if not winget_id:
            return self.cm.error(f'unknown Visual Studio Build Tools release "{year}" '
                                 f'(--with.year: {", ".join(BUILD_TOOLS_WINGET_IDS)})')

        return {'return': 0, 'install_cmd': (install_cmd or '').replace('@VS_BUILD_TOOLS@', winget_id)}
