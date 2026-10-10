"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import re
import shutil
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask, folder_as_named

CONDA_TOOL = 'conda,6e70b3efba794670'
CONDA_ENV_DIR = '.conda-env'
CONDA_MARKER = '.cmeta-conda-env.json'       # written into the environment: who made it (the provenance record reads it)


def truthy(value):
    """A CLI boolean (True, 'true', 'yes', '1', 'on') - the task engine hands strings over."""
    return value is True or str(value).strip().lower() in ('true', 'yes', '1', 'on')


def conda_python_spec(version):
    """conda's spec of the python package for a cMeta version: 3.12 -> python=3.12, 3.12.4 -> python=3.12.4,
    '>=3.11,<3.14' -> "python>=3.11,<3.14", none -> python."""
    v = str(version or '').strip()
    if not v:
        return 'python'
    if re.search(r'[<>=!~]', v):
        return f'"python{v}"'
    return f'python={v}'


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
                'with', 'here', 'version', 'python', 'conda', 'conda_packages', 'channel',
            ], __name__)
        if self.cm.catch_error(r): return r

        result = {'return':0}

        version = params.get('version')

        # --conda: a conda environment instead of a uv venv (the python inside comes from conda's own
        # python package, so no interpreter is named and no uv version is resolved)
        if 'conda' in params:
            if truthy(params['conda']):
                params['conda'] = True
                if params.get('python'):
                    return self.cm.error('venv: --conda and --python=<interpreter> cannot both be given - a conda '
                                         'environment takes its python from conda', 1)
                if version:
                    params['version'] = str(version).strip()
                return result
            params.pop('conda')
        for key in ('conda_packages', 'channel'):
            if key in params and not params[key]:
                params.pop(key)

        # --python=<interpreter>: the venv is made on that interpreter (a conda / system / any python
        # the user named), so no version is resolved; a version at the same time is a contradiction
        if params.get('python'):
            if version:
                return self.cm.error(f'venv: --python={params["python"]} and --version={version} cannot both be given', 1)
            params['python'] = os.path.abspath(os.path.expanduser(str(params['python'])))
            if not os.path.isfile(params['python']):
                return self.cm.error(f'venv: the interpreter to make the venv on was not found: {params["python"]}', 1)

        if version:
            con = ctx['control'].get('con', False)
            verbose = ctx['control'].get('verbose', False)

            space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

            _global = ctx['tasks']['global']

            timeout = params.get('timeout')
            env = params.get('env', {})

            # Add version if supported
            uv_qpath = _global['uv']['qpath']

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
    def work_dir_as_named(self, ctx):
        """The folder this run works in, under the name the request gave it (folder_as_named of the task API)."""
        control = ctx.get('tasks', {}).get('run_control', {})
        return folder_as_named(control.get('work_dir'), control.get('cur_dir'))

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs,
    ):

        """
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
        python = kwargs.get('python')
        timeout = kwargs.get('timeout')
        env = kwargs.get('env', {})

        if truthy(kwargs.get('conda')):
            return self.conda_env(ctx, kwargs, con = con, quiet = quiet, verbose = verbose, space = space)

        # Add version if supported
        uv_qpath = _global['uv']['qpath']

        ##################################################################
        install_cmd = uv_qpath + ' venv --seed'

        if quiet:
            install_cmd += ' --clear'

        if python:
            # The venv on the interpreter the user named (its version, its base), not on a uv-managed python
            install_cmd += ' --python ' + self.cm.utils.files.quote_path(python)
        elif version:
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
              'quiet': quiet,
              'verbose': verbose, 
              'text_cmd': f'RUN:', 
              # Important to be able to continue processing detect/install/build
              'fail_if_nonzero_return_code': True, 
              'print_cur_dir': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        # Check paths: the venv is reported under the name the request gave its folder (--path, the
        # venv path of a python request), which is where the next request looks for it - os.getcwd()
        # resolves the links of the path on Linux and macOS, and one venv became two pythons there
        cur_dir = self.work_dir_as_named(ctx)

        path_to_venv = os.path.join(cur_dir, '.venv')

        found = False
        for x in ['bin', 'Scripts']:
            xx = os.path.join(path_to_venv, x)
            if os.path.isdir(xx):
                path_to_scripts = xx
                found = True
                break

        if not found:
            return self.cm.error(f'Path to scripts not found in venv: {path_to_venv}')

        result['path_to_venv'] = path_to_venv
        result['qpath_to_venv'] = self.cm.utils.files.quote_path(path_to_venv)

        result['path_to_scripts'] = path_to_scripts
        result['qpath_to_scripts'] = self.cm.utils.files.quote_path(path_to_scripts)

        if version:
            result['python_version'] = version
        if python:
            result['python_base'] = python

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
        result['qpath_to_python'] = self.cm.utils.files.quote_path(path_to_python)

        _params['version'] = version
        if python:
            _params['python'] = python

        result['_update_params'] = _params

        return result

    ############################################################
    def conda_env(self,
                  ctx: dict,
                  kwargs: dict,
                  con: bool = False,
                  quiet: bool = False,
                  verbose: bool = False,
                  space: str = '',
    ):
        """
        A conda environment in .conda-env of the current folder (the sibling of the uv venv in .venv),
        made by the conda cMeta set up - tool/conda: a Miniforge, Miniconda or Anaconda found on the
        machine, else the pinned Miniforge it installs. "conda create -y -p <folder>/.conda-env
        python[=<version>] pip [<conda_packages>] [-c <channel> --override-channels]". The python
        inside is conda's python package (the version requested, or conda's newest); pip is there so
        that the pip tools work unchanged. The environment carries .cmeta-conda-env.json (who made it,
        the command), which the provenance record reads. Returns the same keys as a venv
        (path_to_venv, path_to_python, path_to_scripts), env_kind "conda", made_by and the marker.
        """
        version = kwargs.get('version')
        packages = kwargs.get('conda_packages') or []
        if isinstance(packages, str):
            packages = [x.strip() for x in packages.split(',') if x.strip()]
        channel = kwargs.get('channel')
        timeout = kwargs.get('timeout')
        env = kwargs.get('env', {})
        q = self.cm.utils.files.quote_path

        _global = ctx['tasks']['global']
        if not _global.get('conda'):
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                                'ctx': ctx, 'name': CONDA_TOOL, 'con': con, 'quiet': quiet, 'verbose': verbose})
            if self.cm.catch_error(r): return r
        conda = _global['conda']

        cur_dir = self.work_dir_as_named(ctx)       # the folder as the request named it (see run)
        prefix = os.path.join(cur_dir, CONDA_ENV_DIR)
        if os.path.isdir(prefix):
            shutil.rmtree(prefix, ignore_errors = True)        # conda refuses an existing prefix: a half-made one goes

        cmd = f'{conda["qpath"]} create -y -p {q(prefix)} {conda_python_spec(version)} pip'
        cmd += ''.join(' ' + str(p) for p in packages)
        if channel:
            cmd += f' -c {channel} --override-channels'

        rx = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'cmd,c9ba0a88df394d7f',
                             'ctx': ctx, 'cmd': cmd, 'env': env, 'timeout': timeout, 'con': con, 'quiet': quiet,
                             'verbose': verbose, 'text_cmd': 'RUN:', 'fail_if_nonzero_return_code': True,
                             'print_cur_dir': True})
        if self.cm.catch_error(rx): return rx

        if os.name == 'nt':
            path_to_python = os.path.join(prefix, 'python.exe')
            path_to_scripts = os.path.join(prefix, 'Scripts')
        else:
            path_to_python = os.path.join(prefix, 'bin', 'python')
            path_to_scripts = os.path.join(prefix, 'bin')
        if not os.path.isfile(path_to_python):
            return self.cm.error(f'conda made the environment but its python is not there: {path_to_python}')

        made_by = 'conda ' + str(conda.get('version') or '?')
        marker = {'made_by': made_by, 'conda': conda.get('path'), 'cmd': cmd,
                  'created': time.strftime('%Y-%m-%dT%H:%M:%S'), 'cmeta_task': 'venv --conda'}
        try:
            with open(os.path.join(prefix, CONDA_MARKER), 'w', encoding = 'utf-8') as f:
                json.dump(marker, f, indent = 1)
        except OSError:
            pass

        result = {'return': 0,
                  'env_kind': 'conda',
                  'made_by': made_by,
                  'conda_path': conda.get('path'),
                  'path_to_venv': prefix, 'qpath_to_venv': q(prefix),
                  'path_to_scripts': path_to_scripts, 'qpath_to_scripts': q(path_to_scripts),
                  'path_to_python': path_to_python, 'qpath_to_python': q(path_to_python),
                  'path_to_activate_script': '', 'qpath_to_activate_script': ''}
        if version:
            result['python_version'] = version
        _params = {'version': version or None, 'conda': True}
        if packages:
            _params['conda_packages'] = packages
        if channel:
            _params['channel'] = channel
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

