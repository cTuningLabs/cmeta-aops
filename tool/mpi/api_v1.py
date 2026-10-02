"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup mpi": an MPI launcher (mpiexec) and its library. A system MPI on the PATH is
detected first (Open MPI, MPICH, Intel MPI, MS-MPI); otherwise a pinned MPI from PyPI goes into
the tool's own Python environment, without root, with mpi4py for MPI programs in Python:

  --with.mpi=openmpi   Open MPI 5.0.11 (Linux, macOS; the default there): mpiexec, mpicc, mpi.h
  --with.mpi=mpich     MPICH 5.0.2 (Linux, macOS): mpiexec (Hydra), mpicc, mpi.h
  --with.mpi=intel     the Intel MPI runtime 2021.18.1 (Linux, Windows; the default on Windows):
                       mpiexec and the Intel MPI Benchmarks (IMB-MPI1), no compiler wrappers

The result exports the launcher's folder on PATH; features.python is the environment's Python
(with mpi4py) for `mpiexec -n 4 <python> program.py`.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_pyvenv import install_pyvenv

IMPLEMENTATIONS = {
    'openmpi': {'package': 'openmpi', 'default_version': '5.0.11', 'os': ('linux', 'darwin')},
    'mpich': {'package': 'mpich', 'default_version': '5.0.2', 'os': ('linux', 'darwin')},
    'intel': {'package': 'impi-rt', 'default_version': '2021.18.1', 'os': ('linux', 'windows')},
}
DEFAULT = {'linux': 'openmpi', 'darwin': 'openmpi', 'windows': 'intel'}
MPI4PY = 'mpi4py==4.1.2'
PYTHON = '3.12'


def implementation(uname, wanted = None):
    """The MPI to install here: (name, spec, error)."""
    name = str(wanted or DEFAULT.get(uname, 'openmpi')).lower()
    impl = IMPLEMENTATIONS.get(name)
    if not impl:
        return name, None, f'unknown MPI "{name}": use --with.mpi={"|".join(IMPLEMENTATIONS)}'
    if uname not in impl['os']:
        others = [n for n, i in IMPLEMENTATIONS.items() if uname in i['os']]
        return name, None, (f'{name} has no PyPI build for {uname}' +
                            (f': use --with.mpi={"|".join(others)}' if others else ''))
    return name, impl, None


def venv_root(path):
    """The Python environment a command belongs to (where pyvenv.cfg is), or None."""
    d = os.path.dirname(os.path.abspath(path))
    for _ in range(4):
        if os.path.isfile(os.path.join(d, 'pyvenv.cfg')):
            return d
        d = os.path.dirname(d)
    return None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        The MPI of this host when --with.mpi does not name one (part of the cache identity).
        """
        _with = params.setdefault('with', {})
        if not _with.get('mpi'):
            uname = ctx['tasks']['global']['host']['os']['uname']
            _with['mpi'] = DEFAULT.get(uname, 'openmpi')
        return {'return': 0}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The chosen MPI from PyPI with mpi4py in the tool's own environment.
        """
        uname = ctx['tasks']['global']['host']['os']['uname']
        name, impl, error = implementation(uname, params.get('with', {}).get('mpi'))
        if error:
            return self.cm.error(error)
        spec = {'name': 'mpiexec', 'package': impl['package'], 'default_version': impl['default_version'],
                'python': PYTHON, 'extra': [MPI4PY], 'bin': {'windows': 'Library/bin'}}
        return install_pyvenv(self, ctx, params, cmd, spec)

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        The launcher's folder on PATH (mpicc and the other MPI programs are next to it) and, for
        an MPI in a Python environment, that Python (with mpi4py) as features.python.
        """
        path = result.get('path')
        if path:
            features = result.setdefault('features', {})
            root = venv_root(path)
            if root:
                exe = '.exe' if os.name == 'nt' else ''
                python = os.path.join(root, 'Scripts' if os.name == 'nt' else 'bin', 'python' + exe)
                if os.path.isfile(python):
                    features['python'] = python
                features['mpi'] = params.get('with', {}).get('mpi')
            result.setdefault('_aggregate', {}).setdefault('env', {}).setdefault('+PATH', []).append(os.path.dirname(path))
        return {'return': 0, 'result': result}
