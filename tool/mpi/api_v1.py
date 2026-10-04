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
                       mpiexec and the Intel MPI Benchmarks (IMB-MPI1), no compiler wrappers. On
                       Linux the environment's lib folder goes on LD_LIBRARY_PATH as well: the
                       wheel's programs carry no RPATH. Intel MPI jobs span Linux hosts or Windows
                       hosts, not both (its Windows launchers are powershell and the Hydra service,
                       its Linux bootstrap servers ssh and the schedulers)

Open MPI can also be built from its release tarball (--with.build=source; the default on macOS)
into the same kind of environment, with mpi4py built against it. The source build has PRRTE take
the byte order from the compiler as well, so a macOS node can join Linux nodes in one job (the
5.0.x releases report it as unknown on macOS). It needs a C compiler and make (the Xcode Command
Line Tools on macOS) and takes minutes; --with.build=pip keeps the wheel there. The SHA-256 of the
tarball is pinned for the default release (--with.sha256 gives it for another --version).

The result exports the launcher's folder on PATH; features.python is the environment's Python
(with mpi4py) for `mpiexec -n 4 <python> program.py`; features.build is pip or source.
"""

import os
import shutil
import tarfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_pyvenv import install_pyvenv
from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256

IMPLEMENTATIONS = {
    'openmpi': {'package': 'openmpi', 'default_version': '5.0.11', 'os': ('linux', 'darwin')},
    'mpich': {'package': 'mpich', 'default_version': '5.0.2', 'os': ('linux', 'darwin')},
    'intel': {'package': 'impi-rt', 'default_version': '2021.18.1', 'os': ('linux', 'windows')},
}
DEFAULT = {'linux': 'openmpi', 'darwin': 'openmpi', 'windows': 'intel'}
MPI4PY = 'mpi4py==4.1.2'
PYTHON = '3.12'

# Open MPI from its release tarball (--with.build=source), the default on these systems
SOURCE_BY_DEFAULT = ('darwin',)
OPENMPI_URL = 'https://download.open-mpi.org/release/open-mpi/v{minor}/openmpi-{version}.tar.bz2'
OPENMPI_SHA256 = {'5.0.11': 'e668a3c4acd50c41dc204c8a6dd98a611e0f26af89cf677577fa9be8a2698003'}
# The bundled hwloc, libevent, PMIx and PRRTE, as in the wheel; no Fortran or OpenSHMEM
OPENMPI_CONFIGURE = ('--disable-mpi-fortran --disable-oshmem --with-hwloc=internal --with-libevent=internal '
                     '--with-pmix=internal --with-prrte=internal')
MAKE = 'make,d539463695b8480c'
UV = 'uv,92f171fc18714ebd'


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


def build_kind(uname, mpi, wanted = None):
    """How to install the MPI: ('pip' | 'source', error)."""
    if wanted:
        kind = str(wanted).lower()
        if kind not in ('pip', 'source'):
            return None, f'unknown build "{wanted}": use --with.build=pip|source'
        if kind == 'source' and mpi != 'openmpi':
            return None, f'--with.build=source builds Open MPI only (not {mpi})'
        return kind, None
    return ('source' if mpi == 'openmpi' and uname in SOURCE_BY_DEFAULT else 'pip'), None


def fix_prrte_byte_order(src):
    """PRRTE's topology signature takes the byte order from glibc's __BYTE_ORDER only; add the
    compiler's __BYTE_ORDER__, so macOS reports "le" like Linux. True if the source was changed
    (False when it needs no change or the file is not there)."""
    path = os.path.join(src, '3rd-party', 'prrte', 'src', 'hwloc', 'hwloc_base_util.c')
    if not os.path.isfile(path):
        return False
    with open(path, encoding = 'utf-8') as f:
        text = f.read()
    old = '#else\n    endian = "unknown";\n#endif'
    if old not in text or '__ORDER_LITTLE_ENDIAN__' in text:
        return False
    new = ('#elif defined(__BYTE_ORDER__) && defined(__ORDER_LITTLE_ENDIAN__)\n'
           '#    if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__\n'
           '    endian = "le";\n'
           '#    else\n'
           '    endian = "be";\n'
           '#    endif\n' + old)
    with open(path, 'w', encoding = 'utf-8', newline = '\n') as f:
        f.write(text.replace(old, new, 1))
    return True


def venv_root(path):
    """The Python environment a command belongs to (where pyvenv.cfg is), or None."""
    d = os.path.dirname(os.path.abspath(path))
    for _ in range(4):
        if os.path.isfile(os.path.join(d, 'pyvenv.cfg')):
            return d
        d = os.path.dirname(d)
    return None


def install_openmpi_source(tool, ctx, params, version):
    """Open MPI built from the release tarball into the tool's Python environment, with mpi4py
    built against it (see the module docstring)."""
    _global = ctx['tasks']['global']
    c = params.get('control', {})
    con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
    space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''
    _with = params.get('with', {})

    sha256 = (_with.get('sha256') or OPENMPI_SHA256.get(version) or '').lower()
    if not sha256:
        return tool.cm.error(f'no SHA-256 is pinned for Open MPI {version}: add --with.sha256=<digest of '
                             f'openmpi-{version}.tar.bz2> (listed on https://www.open-mpi.org/software/ompi/)')

    def setup(name):
        return tool.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                               'ctx': ctx, 'name': name, 'con': con, 'quiet': quiet, 'verbose': verbose})

    def run(command, what, log = None, env = None):
        if con:
            print(f'{space}INFO: {what} ...' + (f' (log: {log})' if log else ''))
        rr = tool.cm.utils.sys.run(command, capture_output = bool(log), env = env or {}, con = con,
                                   verbose = verbose, text_cmd = 'RUN', space = space)
        if rr['return'] > 0:
            return rr
        if log:
            with open(log, 'w', encoding = 'utf-8') as f:
                f.write((rr.get('stdout') or '') + (rr.get('stderr') or ''))
        if rr.get('returncode', 0) != 0:
            tail = ''
            if log:
                with open(log, encoding = 'utf-8') as f:
                    tail = ''.join(f.readlines()[-25:])
            return tool.cm.error(f'{what} failed (return code {rr.get("returncode")})' + (f':\n{tail}' if tail else ''))
        return {'return': 0}

    # make (from the Xcode Command Line Tools on macOS) and uv for the environment
    r = setup(MAKE)
    if r['return'] > 0:
        hint = ' (on macOS: xcode-select --install)' if _global['host']['os']['uname'] == 'darwin' else ''
        return tool.cm.error(f'building Open MPI needs make and a C compiler{hint}: {r.get("error")}')
    make = _global.get('make', {}).get('qpath') or r.get('tool_path')
    r = setup(UV)
    if tool.cm.catch_error(r, fail16 = True):
        return r
    uv = _global.get('uv', {}).get('qpath') or r.get('tool_path')

    root = os.getcwd()
    venv = os.path.join(root, 'venv')
    python = os.path.join(venv, 'bin', 'python')

    # The tarball, checked against its SHA-256, and its sources
    tarball = f'openmpi-{version}.tar.bz2'
    url = OPENMPI_URL.format(minor = '.'.join(version.split('.')[:2]), version = version)
    r = _download(tool, ctx, params, url, 'src', tarball)
    if r['return'] > 0:
        return r
    digest = _sha256(r['path'])
    if digest != sha256:
        os.remove(r['path'])
        return tool.cm.error(f'SHA-256 mismatch for {tarball}: expected {sha256}, got {digest}')
    src = os.path.join(root, 'src', f'openmpi-{version}')
    if os.path.isdir(src):
        shutil.rmtree(src)
    with tarfile.open(r['path']) as t:
        t.extractall(os.path.join(root, 'src'), **({'filter': 'fully_trusted'} if hasattr(tarfile, 'data_filter') else {}))
    fixed = fix_prrte_byte_order(src)
    if con:
        print(f'{space}INFO: PRRTE byte order: ' + ('the compiler\'s macros added' if fixed else 'no change needed'))

    if not os.path.isfile(python):
        r = run(f'{uv} venv --python {PYTHON} "{venv}"', f'creating a Python {PYTHON} environment')
        if r['return'] > 0:
            return r

    jobs = max(1, os.cpu_count() or 1)
    cwd = os.getcwd()
    os.chdir(src)
    try:
        for command, what, log in [
                (f'./configure --prefix="{venv}" {OPENMPI_CONFIGURE}', f'configuring Open MPI {version}', 'build-configure.log'),
                (f'{make} -j{jobs}', f'building Open MPI {version} with {jobs} jobs', 'build-make.log'),
                (f'{make} install', 'installing it into the environment', 'build-install.log')]:
            r = run(command, what, os.path.join(root, log))
            if r['return'] > 0:
                return r
    finally:
        os.chdir(cwd)

    # mpi4py built against this Open MPI
    r = run(f'{uv} pip install --python "{python}" --no-binary mpi4py "{MPI4PY}"', f'building {MPI4PY}',
            os.path.join(root, 'build-mpi4py.log'), env = {'MPICC': os.path.join(venv, 'bin', 'mpicc')})
    if r['return'] > 0:
        return r

    shutil.rmtree(src, ignore_errors = True)

    found = os.path.join(venv, 'bin', 'mpiexec')
    if not os.path.isfile(found):
        return tool.cm.error(f'Open MPI {version} was built but {found} is missing')
    return {'return': 0, 'install_cmd': None, 'found_path': found}


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
        The MPI of this host when --with.mpi does not name one, and how to install it
        (--with.build): both are part of the cache identity. A source build skips the detection
        of a system MPI.
        """
        _with = params.setdefault('with', {})
        uname = ctx['tasks']['global']['host']['os']['uname']
        if not _with.get('mpi'):
            _with['mpi'] = DEFAULT.get(uname, 'openmpi')
        kind, error = build_kind(uname, str(_with['mpi']).lower(), _with.get('build'))
        if error:
            return self.cm.error(error)
        _with['build'] = kind
        if kind == 'source':
            params['skip_detect'] = True
        return {'return': 0}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The chosen MPI from PyPI with mpi4py in the tool's own environment, or Open MPI built from
        its release tarball (--with.build=source).
        """
        uname = ctx['tasks']['global']['host']['os']['uname']
        _with = params.get('with', {})
        name, impl, error = implementation(uname, _with.get('mpi'))
        if error:
            return self.cm.error(error)
        if _with.get('build') == 'source':
            version = params.get('version_simple') or params.get('version') or impl['default_version']
            return install_openmpi_source(self, ctx, params, version)
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
        an MPI in a Python environment, that Python (with mpi4py) as features.python. The Intel
        MPI wheel's programs (mpiexec, the Hydra proxies, IMB-MPI1) carry no RPATH on Linux: the
        environment's lib folder goes on LD_LIBRARY_PATH there.
        """
        path = result.get('path')
        if path:
            features = result.setdefault('features', {})
            env = result.setdefault('_aggregate', {}).setdefault('env', {})
            root = venv_root(path)
            if root:
                exe = '.exe' if os.name == 'nt' else ''
                python = os.path.join(root, 'Scripts' if os.name == 'nt' else 'bin', 'python' + exe)
                if os.path.isfile(python):
                    features['python'] = python
                features['mpi'] = params.get('with', {}).get('mpi')
                features['build'] = params.get('with', {}).get('build') or 'pip'
                uname = ctx.get('tasks', {}).get('global', {}).get('host', {}).get('os', {}).get('uname')
                lib = os.path.join(root, 'lib')
                if features['mpi'] == 'intel' and uname == 'linux' and os.path.isdir(lib):
                    features['lib'] = lib
                    env.setdefault('+LD_LIBRARY_PATH', []).append(lib)
            env.setdefault('+PATH', []).append(os.path.dirname(path))
        return {'return': 0, 'result': result}
