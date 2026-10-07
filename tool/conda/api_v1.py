"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

conda through Miniforge (https://github.com/conda-forge/miniforge, BSD-3-Clause: the community
distribution of conda with conda-forge as its only channel). A conda already on the machine (Miniforge,
Miniconda, Anaconda, Homebrew's) is detected first by the declarations in _desc.yaml; otherwise the
pinned Miniforge release for this OS and CPU is installed here (install ladder tier 1): the installer
downloaded with the download-file task, its SHA-256 verified against the per-asset file upstream
publishes, then run silently into content/miniforge3 of the cache entry - user-level, no administrator
rights, nothing registered with the OS, nothing put on the PATH or into the shell's profile.

The version is conda's own (26.7.2); Miniforge tags it with an installer build number (26.7.2-0),
0 unless BUILDS says otherwise. Linux and macOS run the .sh installer with -b -p <prefix>, Windows
the .exe with /S /D=<prefix>.
"""

import os
import shutil

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import _fetch_one

DEFAULT_VERSION = '26.7.2'
BUILDS = {'26.7.2': '0'}                  # conda version -> Miniforge installer build (0 when not listed)

URL = 'https://github.com/conda-forge/miniforge/releases/download/{tag}/Miniforge3-{tag}-{os}-{arch}{suffix}'
OS = {'linux': 'Linux', 'darwin': 'MacOSX', 'windows': 'Windows'}
ARCH = {'linux': {'amd64': 'x86_64', 'arm64': 'aarch64'},
        'darwin': {'amd64': 'x86_64', 'arm64': 'arm64'},
        'windows': {'amd64': 'x86_64'}}
INSTALL_DIR = 'miniforge3'


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
        Download the pinned Miniforge installer for this OS and CPU, verify it and run it silently
        into the cache entry; returns found_path = the conda of that installation.
        """
        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']
        c = params.get('control', {})
        con = c.get('con', False)
        verbose = c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        version = params.get('version')
        version_simple = params.get('version_simple')
        if not version:
            version = version_simple = DEFAULT_VERSION
        if not version_simple:
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'the Miniforge download needs an exact conda version (got "{version}")'}
        if uname not in OS or uarch not in ARCH.get(uname, {}):
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'Miniforge publishes no installer for {uname}/{uarch}'}

        tag = f'{version_simple}-{BUILDS.get(version_simple, "0")}'
        windows = uname == 'windows'
        v = {'version': version_simple, 'tag': tag, 'os': OS[uname], 'arch': ARCH[uname][uarch],
             'suffix': '.exe' if windows else '.sh', 'exe': '', 'host_exe': '.exe' if windows else '', 'uname': uname}
        # The POSIX installer refuses to run unless its own name ends in .sh (its guard against being sourced)
        item = {'name': 'miniforge-installer' if windows else 'miniforge-installer.sh', 'url': URL,
                'checksum': {'file': '{url}.sha256'}}

        directory = 'content'
        os.makedirs(os.path.join(os.getcwd(), directory), exist_ok = True)
        r = _fetch_one(self, ctx, params, item, v, directory, con, space)
        if r['return'] > 0:
            return r
        installer = r['path']

        prefix = os.path.join(os.getcwd(), directory, INSTALL_DIR)
        if os.path.isdir(prefix):
            shutil.rmtree(prefix, ignore_errors = True)     # a half-done earlier attempt

        q = self.cm.utils.files.quote_path
        if windows:
            # NSIS: /D must be the last option and must not be quoted
            cmd_line = f'{q(installer)} /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D={prefix}'
            conda = os.path.join(prefix, 'condabin', 'conda.bat')
        else:
            cmd_line = f'bash {q(installer)} -b -p {q(prefix)}'
            conda = os.path.join(prefix, 'condabin', 'conda')

        if con:
            print(f'{space}INFO: installing Miniforge {tag} into {prefix} ...')
        rr = self.cm.utils.sys.run(cmd_line, capture_output = not verbose, con = con, verbose = verbose,
                                   print_cmd = verbose, fail_on_error = False, logger = self.logger)
        if rr.get('return', 0) > 0:
            return rr
        if rr.get('returncode', 0) != 0:
            err = (rr.get('stderr') or rr.get('stdout') or '').strip().splitlines()
            return self.cm.error(f'the Miniforge installer returned {rr.get("returncode")}' + (f': {err[-1]}' if err else ''))
        if not os.path.isfile(conda):
            return self.cm.error(f'the Miniforge installer finished but {conda} is not there')

        try:
            os.remove(installer)                            # ~100 MB that the installation does not need any more
        except OSError:
            pass

        return {'return': 0, 'install_cmd': None, 'found_path': conda}
