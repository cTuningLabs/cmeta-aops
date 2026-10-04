"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup torch-cpp-prebuilt": LibTorch, the PyTorch C++ distribution, from PyTorch's prebuilt
archives (https://download.pytorch.org/libtorch/) instead of a local build. The archive of the
release (--version, default in _desc.yaml) for this system, CPU and build is downloaded into the
cache, checked against its SHA-256 pinned below and unpacked; tool/torch-cpp --with.build=prebuilt
uses it.

The build ("variant") is cpu or a CUDA build (cu118, cu126, cu128). For --with.compute=cuda it is the
newest CUDA build that has code for every GPU of this machine (their compute capability, from
tool/cuda) and whose CUDA version the driver supports; --with.variant=<build> picks one. macOS has one
build, for the CPU and for Apple GPUs (MPS).
"""

import os
import stat
import urllib.parse
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256
from tool_c393ba5c6fa14f66.api.common_libtorch import found_paths_with_versions, add_path_features

BASE = 'https://download.pytorch.org/libtorch'

# The archives of each release: (system, CPU, build) -> (file, SHA-256 of the file). The URL is
# <BASE>/<build>/<file> with "+" as %2B. PyTorch publishes no checksums: the digests are those of
# the archives as downloaded.
ARCHIVES = {
    '2.7.1': {
        ('linux', 'amd64', 'cpu'): ('libtorch-cxx11-abi-shared-with-deps-2.7.1+cpu.zip',
                                    '63d572598c8d532128a335018913e795c1bbb32602ce378896dc8cfbb5590976'),
        ('linux', 'amd64', 'cu118'): ('libtorch-cxx11-abi-shared-with-deps-2.7.1+cu118.zip',
                                      '65a33ca2751af31c0a6ae8b6e8b727c242ae1c41d294da97471de9c95ecb5406'),
        ('linux', 'amd64', 'cu126'): ('libtorch-cxx11-abi-shared-with-deps-2.7.1+cu126.zip',
                                      '4a7ffb0c0f6c3b02fb14e7790143dfb2fbb2973c41f107357da57bcddd196077'),
        ('linux', 'amd64', 'cu128'): ('libtorch-cxx11-abi-shared-with-deps-2.7.1+cu128.zip',
                                      'ae513b437ae99150744ef1d06b02a4ecbbb9275c9ffe540c88909623e3293041'),
        ('windows', 'amd64', 'cpu'): ('libtorch-win-shared-with-deps-2.7.1+cpu.zip',
                                      'a294845080d67ff579073b7b6e17e7da1cc856dde6e63fca2d71498b482580f8'),
        ('windows', 'amd64', 'cu118'): ('libtorch-win-shared-with-deps-2.7.1+cu118.zip',
                                        '186aa930c1510482153be939e573937fc6682ad527ba86500f50266c8f418428'),
        ('windows', 'amd64', 'cu126'): ('libtorch-win-shared-with-deps-2.7.1+cu126.zip',
                                        '3d63369698dd145ae11c4a0629c51014a05b4bead4a5aac76f784cfaa7543b8b'),
        ('windows', 'amd64', 'cu128'): ('libtorch-win-shared-with-deps-2.7.1+cu128.zip',
                                        'bdbf643d648e2bf9e8603472d6c6ff4bae5f79a49fe4776f215b4c45c90a7f19'),
        ('windows', 'arm64', 'cpu'): ('libtorch-win-arm64-shared-with-deps-2.7.1+cpu.zip',
                                      'f9dd47c792c900601f08265ddc0186036e01503ada7895f0c7c90f8af64fbc4b'),
        ('darwin', 'arm64', 'cpu'): ('libtorch-macos-arm64-2.7.1.zip',
                                     'aa89ac85b91c83d0f976f8d135330d51e38ab777b26ec24f312fd58d079314cb'),
    },
}

# The CUDA builds of each release per system: their CUDA version (x10) and the GPU architectures
# (compute capability x10) their CUDA library has code for (cuobjdump --list-elf of libtorch_cuda.so,
# torch_cuda.dll). Code for X.y also runs on X.z, z >= y.
CUDA_BUILDS = {
    '2.7.1': {
        ('linux', 'cu118'): (118, [37, 50, 60, 70, 75, 80, 86]),
        ('linux', 'cu126'): (126, [50, 60, 70, 75, 80, 86, 89, 90]),
        ('linux', 'cu128'): (128, [50, 52, 60, 61, 70, 75, 80, 86, 89, 90, 100, 101, 120]),
        ('windows', 'cu118'): (118, [37, 50, 60, 61, 70, 75, 80, 86, 90]),
        ('windows', 'cu126'): (126, [50, 60, 61, 70, 75, 80, 86, 89, 90]),
        ('windows', 'cu128'): (128, [50, 60, 61, 70, 75, 80, 86, 89, 90, 100, 120]),
    },
}

LIBRARY = {'windows': 'torch.dll', 'darwin': 'libtorch.dylib'}


def compute_list(compute):
    """--with.compute as a list (cpu by default)."""
    if isinstance(compute, str):
        compute = [c.strip() for c in compute.split(',') if c.strip()]
    return list(compute or ['cpu'])


def requested_compute(ctx, _with):
    """--with.compute, else the compute of the program's target, else cpu."""
    return compute_list(_with.get('compute') or ctx['tasks']['global'].get('target', {}).get('compute'))


def runs_on(archs, cc):
    """Whether code for the GPU architectures `archs` (86, 120, ...) runs on compute capability `cc`."""
    return any(a // 10 == cc // 10 and a % 10 <= cc % 10 for a in archs)


def choose_variant(version, system, compute, gpus = None, driver_cuda = None, variant = None):
    """
    The build to download for a release, system (uname, uarch) and compute: (build, None) or
    (None, error). gpus: the compute capabilities (x10) of the GPUs; driver_cuda: the driver's CUDA
    version (x10); variant: the build asked for.
    """
    archives = ARCHIVES.get(version)
    if not archives:
        return None, f'no prebuilt LibTorch {version} is known (known: {", ".join(sorted(ARCHIVES))})'
    builds = sorted(b for (s, a, b) in archives if (s, a) == tuple(system))
    if not builds:
        return None, f'no prebuilt LibTorch {version} for {system[0]} {system[1]}'
    if variant:
        if variant not in builds:
            return None, f'no LibTorch {version} build "{variant}" for {system[0]} {system[1]} (builds: {", ".join(builds)})'
        return variant, None

    other = [c for c in compute if c not in ('cpu', 'cuda', 'metal')]
    if other:
        return None, f'no prebuilt LibTorch for {", ".join(other)} here: build it from source (tool/torch-cpp)'
    if 'cuda' not in compute:
        return ('cpu', None) if 'cpu' in builds else (None, f'no CPU build of LibTorch {version} for {system[0]} {system[1]}')

    cuda = {b: v for (s, b), v in CUDA_BUILDS.get(version, {}).items() if s == system[0]}
    candidates = [b for b in builds if b in cuda]
    if not candidates:
        return None, f'no CUDA build of LibTorch {version} for {system[0]} {system[1]}'
    if gpus:
        candidates = [b for b in candidates if all(runs_on(cuda[b][1], cc) for cc in gpus)]
        if not candidates:
            ccs = ', '.join(f'{cc // 10}.{cc % 10}' for cc in sorted(set(gpus)))
            return None, (f'no CUDA build of LibTorch {version} has code for the GPUs here (compute capability '
                          f'{ccs}): ' + '; '.join(f'{b}: ' + ' '.join(f'{a // 10}.{a % 10}' for a in cuda[b][1])
                                                  for b in sorted(cuda)))
    if driver_cuda:
        supported = [b for b in candidates if cuda[b][0] <= driver_cuda]
        # CUDA's minor version compatibility: a 12.x runtime also runs with an older 12.x driver
        same_major = [b for b in candidates if cuda[b][0] // 10 == driver_cuda // 10]
        candidates = supported or same_major
        if not candidates:
            return None, f'the NVIDIA driver supports CUDA {driver_cuda // 10}.{driver_cuda % 10}, older than the CUDA builds of LibTorch {version}'
    return max(candidates, key = lambda b: cuda[b][0]), None


def archive(version, system, variant):
    """(url, file, sha256) of a build."""
    name, sha256 = ARCHIVES[version][(system[0], system[1], variant)]
    return f'{BASE}/{variant}/{urllib.parse.quote(name)}', name, sha256


def extract(path, dest):
    """Unpack a zip, keeping the permissions and symbolic links of the files (POSIX)."""
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            mode = (info.external_attr >> 16) & 0xFFFF
            target = os.path.join(dest, info.filename)
            if os.name != 'nt' and stat.S_ISLNK(mode):
                os.makedirs(os.path.dirname(target), exist_ok = True)
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(z.read(info).decode(), target)
                continue
            z.extract(info, dest)
            if os.name != 'nt' and not info.is_dir() and mode & 0o777:
                os.chmod(target, mode & 0o777)


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        _with = params.setdefault('with', {})
        _with['compute'] = requested_compute(ctx, _with)
        variant = str(_with.get('variant') or '').strip().lower()
        if variant:
            _with['variant'] = variant
        else:
            _with.pop('variant', None)
        return {'return': 0}

    ############################################################
    def variant(self, ctx, params):
        """The build of this setup: (version, build, None) or (None, None, error)."""
        _global = ctx['tasks']['global']
        host = _global['host']['os']
        system = (host['uname'], str(host.get('uarch', '')).lower())

        version = params.get('version_simple') or params.get('version') or self.cdesc['default_version']
        if version not in ARCHIVES:
            return None, None, (f'the prebuilt LibTorch needs a known release, such as {self.cdesc["default_version"]} '
                                f'(known: {", ".join(sorted(ARCHIVES))})')

        _with = params.get('with', {})
        features = _global.get('cuda', {}).get('features', {})
        gpus = [int(d['compute_cap_int']) for d in features.get('devices', []) if d.get('compute_cap_int')]
        driver_cuda = features.get('versions', {}).get('cuda_version_int')
        variant = str(_with.get('variant') or '').strip().lower() or None

        build, error = choose_variant(version, system, requested_compute(ctx, _with), gpus = gpus,
                                      driver_cuda = driver_cuda, variant = variant)
        return version, build, error

    ############################################################
    def customize_tool_cache_artifact(self,
                                      ctx: dict,
                                      result: dict,
                                      params: dict,
                                      cache_tags: list,
                                      cache_params: dict,
                                      cache_features: dict,
                                      **misc,
    ):
        """
        The build is part of the cache identity: one entry per build (cpu, cu126, ...).
        """
        version, build, error = self.variant(ctx, params)
        if error:
            return self.cm.error(error)
        cache_params.setdefault('with', {})['variant'] = build
        return {'return': 0}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Download, check and unpack the archive of the build.
        """
        con = params.get('control', {}).get('con', False)
        version, build, error = self.variant(ctx, params)
        if error:
            return self.cm.error(error)

        host = ctx['tasks']['global']['host']['os']
        system = (host['uname'], str(host.get('uarch', '')).lower())
        url, name, sha256 = archive(version, system, build)
        if con:
            print(f'INFO: LibTorch {version} ({build}) from {url}')

        r = _download(self, ctx, params, url, 'download', name)
        if r['return'] > 0:
            return r
        digest = _sha256(r['path'])
        if digest != sha256:
            os.remove(r['path'])
            return self.cm.error(f'SHA-256 mismatch for {name}: expected {sha256}, got {digest}')

        content = os.path.join(os.getcwd(), 'content')
        extract(r['path'], content)
        os.remove(r['path'])

        lib = os.path.join(content, 'libtorch', 'lib', LIBRARY.get(system[0], 'libtorch.so'))
        if not os.path.isfile(lib):
            return self.cm.error(f'no {os.path.basename(lib)} in {name}')
        return {'return': 0, 'install_cmd': None, 'found_path': lib}

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: list,
                        params: dict = {},
    ):
        found = found_paths_with_versions(paths, params.get('with', {}))
        return {'return': 0, 'found_paths_with_versions': found} if found else {'return': 0}

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict = {},
    ):
        """
        home, lib, include of the unpacked LibTorch; its lib folder for the run time library path.
        """
        paths = add_path_features(self, paths)
        version, build, error = self.variant(ctx, params)
        for p in paths:
            features = p.setdefault('features', {})
            features['paths']['found_dynamic_lib_paths'] = [features['paths']['lib']]
            if build:
                features['variant'] = build
        return {'return': 0, 'paths': paths}
