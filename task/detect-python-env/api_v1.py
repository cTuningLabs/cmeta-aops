"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import sys
import struct
import copy

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,              # cMeta context
            python_path: str = None
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if python_path and not os.path.isfile(python_path):
            return self.cm.error(f'path "{python_path}" not found')

        result = {'return':0}

        is_windows = platform.system() == "Windows"

        # The environment of the python, classified as the provenance record classifies it (one rule for both,
        # since 2026-10-07): a venv (pyvenv.cfg; an older virtualenv by its activate script), a conda base
        # (conda-meta/ and condabin/), a conda environment (conda-meta/ alone: under envs/ of a base, or
        # anywhere with "conda create -p", cMeta's .conda-env included) or the system's python. The
        # environment's root is the folder above bin/ (Scripts\ on Windows), or the python's own folder
        # (a conda root on Windows, where python.exe sits next to Scripts\ and condabin\).
        path_bin = os.path.dirname(os.path.abspath(python_path))
        path_root = os.path.dirname(path_bin)
        activate = 'Scripts\\activate.bat' if is_windows else 'bin/activate'

        kind = 'system'
        env_path = None
        script_path = None
        for root in (path_root, path_bin):
            act = os.path.join(root, activate)
            if os.path.isfile(os.path.join(root, 'pyvenv.cfg')):
                kind, env_path = 'venv', root
                script_path = act if os.path.isfile(act) else None
                break
            if os.path.isdir(os.path.join(root, 'conda-meta')):
                # a base carries the conda itself (condabin/), its package cache (pkgs/) and its environments (envs/)
                base = any(os.path.isdir(os.path.join(root, d)) for d in ('condabin', 'pkgs', 'envs'))
                kind = 'conda-base' if base else 'conda-env'
                env_path = root
                break
            if os.path.isfile(act):
                kind, env_path, script_path = 'venv', root, act
                break

        is_virtual = kind != 'system'

        result['is_virtual'] = is_virtual
        result['kind'] = kind

        result['python_path'] = python_path

        if is_virtual:
            result['env_path'] = env_path
            result['script_path'] = script_path

        return result

