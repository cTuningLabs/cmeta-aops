"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict,
                     cparams: dict = {},
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK venv init")

        r = self.cm.check_params(params, [
                'with', 'here', 'version',
            ], __name__)
        if self.cm.catch_error(r): return r

        result = {'return':0}

        version = params.get('version')

        if version:
            con = ctx['control'].get('con', False)
            verbose = ctx['control'].get('verbose', False)

            space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

            _global = ctx['tasks']['global']

            timeout = params.get('timeout')
            env = params.get('env', {})

            # Add version if supported
            uv_qpath = _global['tool--uv']['qpath']

            cmd = uv_qpath + ' python list --all-versions'
            ii = {'category': 'task,c36be4b9314a45e0',
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': cmd,
                  'env': env,
                  'timeout': timeout,
                  'con': con, 
                  'verbose': verbose, 
                  'text_cmd': f'{space}RUN:', 
                  'capture_output': True,
                  'fail_if_nonzero_return_code': True, 
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            versions = rx['stdout']

            params['version'] = resolve_with_uv(versions, version)

        
        if params.get('here') or params.get('with',{}).get('here'):
            cparams['path'] = ctx['origin']['pwd']

        return result

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs,
    ):

        """
        Clone git repo.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        quiet = ctx['control'].get('quiet', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        _params = {}

        _global = ctx['tasks']['global']

        result = {'return':0}

        version = kwargs.get('version')
        timeout = kwargs.get('timeout')
        env = kwargs.get('env', {})

        # Add version if supported
        uv_qpath = _global['tool--uv']['qpath']

        ##################################################################
        install_cmd = uv_qpath + ' venv --seed'

        if quiet:
            install_cmd += ' --clear'

        if version:
            install_cmd += f' --python {version}'

        # Run setup
        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'cmd,c9ba0a88df394d7f',
              'ctx': ctx,
              'cmd': install_cmd,
              'env': env,
              'timeout': timeout,
              'con': con, 
              'verbose': verbose, 
              'text_cmd': f'RUN:', 
              # Important to be able to continue processing detect/install/build
              'fail_if_nonzero_return_code': True, 
              'print_cur_dir': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        # Check paths
        cur_dir = os.getcwd()

        path_to_venv = os.path.join(cur_dir, '.venv')

        found = False
        for x in ['bin', 'Scripts']:
            xx = os.path.join(path_to_venv, x)
            if os.path.isdir(xx):
                path_to_scripts = xx
                found = True
                break

        if not found:
            return self.cm.error(f'Path to scripts not found in venv: {path_venv}')

        result['path_to_venv'] = path_to_venv
        result['qpath_to_venv'] = self.cm.utils.files.quote_path(path_to_venv)

        result['path_to_scripts'] = path_to_scripts
        result['qpath_to_scripts'] = self.cm.utils.files.quote_path(path_to_scripts)

        if version:
            result['python_version'] = version

        if os.name == 'nt':
            path_to_activate_script = os.path.join(path_to_scripts, 'activate.bat')
            path_to_python = os.path.join(path_to_scripts, 'python.exe')
        else:
            path_to_activate_script = os.path.join(path_to_scripts, 'activate')
            path_to_python = os.path.join(path_to_scripts, 'python')

        if not os.path.isfile(path_to_activate_script):
            return self.cm.error(f'Path to activation script not found in venv: {path_to_activate_script}')

        result['path_to_activate_script'] = path_to_activate_script
        result['qpath_to_activate_script'] = self.cm.utils.files.quote_path(path_to_activate_script)

        if not os.path.isfile(path_to_python):
            return self.cm.error(f'Path to python not found in venv: {path_to_python}')

        result['path_to_python'] = path_to_python
        result['qpath_to_python'] = self.cm.utils.files.quote_path(path_to_activate_script)

        _params['version'] = version

        result['_update_params'] = _params    

        return result


##################################################################
import re
import subprocess
from functools import lru_cache
from packaging.specifiers import SpecifierSet
from packaging.version import Version


_OPERATOR_PATTERN = re.compile(r"[<>=!~]")


def normalize_specifier(spec: str) -> str:
    if spec is None: 
        spec = ''

    spec = spec.strip()

    if _OPERATOR_PATTERN.search(spec):
        return spec

    parts = spec.split(".")

    # Major only: "3"
    if len(parts) == 1:
        major = int(parts[0])
        return f">={major}.0a0,<{major + 1}"

    # Major.Minor: "3.15"
    if len(parts) == 2:
        major = int(parts[0])
        minor = int(parts[1])
        return f">={major}.{minor}.0a0,<{major}.{minor + 1}"

    # Full patch exact
    return f"=={spec}"

@lru_cache
def get_uv_cpython_versions(stdout) -> list[Version]:
    versions = set()

    for line in stdout.splitlines():
        line = line.strip()

        # Only CPython
        if not line.startswith("cpython-"):
            continue

        # Extract version part
        match = re.match(r"cpython-([^-]+)-", line)
        if not match:
            continue

        raw_version = match.group(1)

        # Ignore freethreaded builds (local versions)
        if "+" in raw_version:
            continue

        try:
            versions.add(Version(raw_version))
        except Exception:
            continue

    return sorted(versions)


def resolve_with_uv(stdout: str, spec: str) -> str:
    normalized = normalize_specifier(spec)
    spec_set = SpecifierSet(normalized)

    versions = get_uv_cpython_versions(stdout)

    # First: all matching versions
    matching = [v for v in versions if v in spec_set]

    if not matching:
        raise ValueError(f"No matching Python version for '{spec}'")

    # Prefer stable versions
    stable = [v for v in matching if not v.is_prerelease]

    if stable:
        return str(max(stable))

    # Fallback to prereleases (pip-like behavior)
    return str(max(matching))
