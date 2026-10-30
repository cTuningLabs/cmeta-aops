"""
Mistral Vibe as a cMeta tool: installed from PyPI (mistral-vibe) by cMeta's uv into an environment of its own inside
the cache entry - nothing in the user's Python, no PATH change, no administrator rights.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

PACKAGE = 'mistral-vibe'
# Vibe wants a Python 3.12 or later with the GIL: uv's managed CPython of that line is one
PYTHON = '3.12'


def install_command(uv, version = ''):
    """The uv command that installs the package (a version: "mistral-vibe==<version>"); --force replaces an
    environment an earlier attempt left in the entry."""
    return [uv, 'tool', 'install', '--force', '--python', PYTHON, PACKAGE + ('==' + version if version else '')]


def install_env(content, base = None):
    """uv's tool environment and its command folder, both inside the cache entry's content folder."""
    env = dict(os.environ if base is None else base)
    env['UV_TOOL_DIR'] = os.path.join(content, 'uv-tools')
    env['UV_TOOL_BIN_DIR'] = os.path.join(content, 'bin')
    return env


class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        _global = ctx['tasks']['global']
        windows = _global['host']['os']['uname'] == 'windows'

        c = params.get('control', {})
        con = c.get('con', False)
        verbose = c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        version = params.get('version_simple') or ''
        if params.get('version') and not version:
            return {'return': 16, 'install_cmd': cmd,
                    'error': 'Mistral Vibe is installed by its exact release (--version=3.0.4, a PyPI version), not a range'}

        # uv: install_uses set it up; a run without it (an older engine) sets it up here
        uv = (_global.get('uv') or {}).get('path', '')
        if not uv:
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                                'name': 'uv,92f171fc18714ebd', 'ctx': ctx, 'con': con, 'quiet': c.get('quiet', False)})
            if r.get('return', 1) > 0:
                return {'return': 16, 'install_cmd': cmd, 'error': f'uv, which installs Mistral Vibe, could not be set up: {r.get("error", "")}'}
            uv = r.get('path') or (_global.get('uv') or {}).get('path', '')
        if not uv:
            return {'return': 16, 'install_cmd': cmd, 'error': 'no uv to install Mistral Vibe with'}

        content = os.path.join(os.getcwd(), 'content')
        os.makedirs(content, exist_ok = True)
        run_cmd = install_command(uv, version)
        if con:
            print('')
            print(f'{space}INFO: installing Mistral Vibe into this cache entry: {" ".join(run_cmd)}')
            print(f'{space}      (its environment in {os.path.join(content, "uv-tools")}, the command in {os.path.join(content, "bin")})')
            print('')
        try:
            rc = subprocess.call(run_cmd, env = install_env(content, dict(os.environ, **(params.get('env') or {}))))
        except Exception as e:
            return {'return': 16, 'install_cmd': cmd, 'error': f'cannot run uv: {e}'}

        exe = os.path.join(content, 'bin', 'vibe' + ('.exe' if windows else ''))
        if rc == 0 and os.path.isfile(exe):
            if con:
                print(f'{space}INFO: Mistral Vibe: {exe}')
            return {'return': 0, 'install_cmd': None, 'found_path': exe}
        return {'return': 16, 'install_cmd': None, 'error': f'uv exited with code {rc} and installed no command at {exe}'}
