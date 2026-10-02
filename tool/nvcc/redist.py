"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

NVIDIA's CUDA redistributable archives (developer.download.nvidia.com/compute/cuda/redist): every
component of every CUDA release since 11.0.3, as an archive per platform, listed with its sha256
in redistrib_<release>.json. Unpacked into one folder they make a CUDA toolkit of any version,
without root and without the installer.
"""

import hashlib
import json
import os
import re
import shutil
import tarfile
import urllib.request
import zipfile

BASE = 'https://developer.download.nvidia.com/compute/cuda/redist'

# Written into the root of a toolkit made from the archives: its release and components
MARKER = 'cmeta-cuda-redist.json'

# What nvcc needs to compile and link CUDA programs. Since 13.0, cccl (was cuda_cccl), cuda_crt and
# libnvvm (both were part of cuda_nvcc) are components of their own; the names that a release lacks
# are skipped.
COMPILER = ('cuda_nvcc', 'cuda_cudart', 'cuda_cccl', 'cccl', 'cuda_crt', 'libnvvm', 'cuda_profiler_api')

# The components of the libraries and tools programs ask for (--with.cuda_libs, lib-cuda's lib_names);
# cudart comes with the compiler
LIBRARIES = {
    'cublas': ('libcublas',), 'cublaslt': ('libcublas',),
    'cufft': ('libcufft', 'libnvjitlink'), 'cufftw': ('libcufft', 'libnvjitlink'),
    'curand': ('libcurand',),
    'cusparse': ('libcusparse', 'libnvjitlink'),
    'cusolver': ('libcusolver', 'libcublas', 'libcusparse', 'libnvjitlink'),
    'npp': ('libnpp',), 'nvjpeg': ('libnvjpeg',), 'cufile': ('libcufile',),
    'nvrtc': ('cuda_nvrtc',), 'nvjitlink': ('libnvjitlink',), 'nvml': ('cuda_nvml_dev',),
    'cupti': ('cuda_cupti',), 'nvtx': ('cuda_nvtx',), 'nvtx3': ('cuda_nvtx',), 'opencl': ('cuda_opencl',),
    'cuobjdump': ('cuda_cuobjdump',), 'nvdisasm': ('cuda_nvdisasm',), 'cuxxfilt': ('cuda_cuxxfilt',),
    'nvprune': ('cuda_nvprune',),
}

# The oldest GPU architecture (compute capability x 10) each CUDA major version builds for: CUDA 12
# dropped Kepler (sm_35, sm_37), CUDA 13 Maxwell, Pascal and Volta (sm_50 to sm_70)
MIN_ARCH = {11: 35, 12: 50, 13: 75}

PLATFORMS = {('linux', 'amd64'): 'linux-x86_64', ('linux', 'arm64'): 'linux-sbsa',
             ('windows', 'amd64'): 'windows-x86_64'}

# nvcc.profile on Linux takes the headers and libraries from targets/<target>/, as the installer
# lays them out; the archives have them in include/ and lib/
TARGETS = {'linux-x86_64': 'x86_64-linux', 'linux-sbsa': 'sbsa-linux'}


def key(version):
    return tuple(int(x) for x in re.findall(r'\d+', str(version)))


def major_minor(version):
    return key(version)[:2]


def platform_of(uname, uarch):
    """NVIDIA's name of this platform (linux-x86_64, linux-sbsa, windows-x86_64), or None."""
    return PLATFORMS.get((uname, uarch))


def fetch(url, timeout = 60):
    with urllib.request.urlopen(url, timeout = timeout) as r:
        return r.read()


def releases(index_html = None):
    """The CUDA releases of the redist index (11.0.3 ... 13.x.y), oldest first."""
    if index_html is None:
        index_html = fetch(BASE + '/').decode('utf-8', 'replace')
    found = set(re.findall(r'redistrib_(\d+\.\d+\.\d+)\.json', index_html))
    return sorted(found, key = key)


def manifest(release):
    return json.loads(fetch(f'{BASE}/redistrib_{release}.json').decode('utf-8'))


def nvcc_version(m):
    return (m.get('cuda_nvcc') or {}).get('version')


def exact_version(version):
    """12.9.86 (an nvcc version) for '12.9.86' or '==12.9.86', else None (a prefix or a range)."""
    v = str(version or '').strip()
    v = v[2:] if v.startswith('==') else v
    return v if re.fullmatch(r'\d+\.\d+\.\d+', v) else None


def incompatible(release, driver_cuda = None, gpu_arch_min = None):
    """Why programs built with this CUDA release cannot run here, or None: a newer major version than
    the driver runs, or a GPU older than the oldest architecture of the release."""
    major = key(release)[0]
    if driver_cuda and major > key(driver_cuda)[0]:
        return (f'CUDA {release} needs a driver for CUDA {major} (this driver runs CUDA {driver_cuda}): '
                f'update the NVIDIA driver')
    if gpu_arch_min and MIN_ARCH.get(major, 0) > int(gpu_arch_min):
        return (f'CUDA {major} builds for sm_{MIN_ARCH[major]} and newer, the GPU is sm_{gpu_arch_min}'
                f' - an older CUDA toolkit supports it')
    return None


def choose(all_releases, wanted = None, matches = None, driver_cuda = None, gpu_arch_min = None, nvcc_of = None):
    """
    The release to install. wanted is what nvcc --version should show: an exact version (12.9.86), a
    prefix (12.9, 12) or a range (>=12.4,<12.7, checked against the release, 12.4.1, and then its
    nvcc). matches(wanted, version) checks a prefix or a range; nvcc_of(release) is the nvcc version
    of a release (its manifest). The release must run on the driver (driver_cuda: the CUDA version
    nvidia-smi shows) and build for the GPU (gpu_arch_min: its compute capability x 10).

    Without a request, the newest release the driver fully runs (its major.minor at most the
    driver's). A request may get a newer minor version than the driver's, which runs through CUDA's
    minor version compatibility, with a warning.

    Returns (release, warning) or (None, why).
    """
    wanted = str(wanted or '').strip()
    exact = exact_version(wanted)
    if exact:
        candidates = [r for r in all_releases if major_minor(r) == major_minor(exact)]
        if exact in all_releases and nvcc_of and nvcc_of(exact) != exact:
            mm = '.'.join(exact.split('.')[:2])
            return None, (f'{exact} is a CUDA release, whose nvcc is {nvcc_of(exact)}: ask for '
                          f'--version={nvcc_of(exact)} or --version={mm}')
    elif wanted:
        candidates = [r for r in all_releases if matches(wanted, r)]
    else:
        candidates = list(all_releases)
    if not candidates:
        return None, (f'no CUDA release matches {wanted} (NVIDIA lists {all_releases[0]} to {all_releases[-1]})'
                      if all_releases else 'NVIDIA lists no CUDA release')

    def why_not(release, strict):
        why = incompatible(release, driver_cuda, gpu_arch_min)
        if not why and strict and driver_cuda and major_minor(release) > major_minor(driver_cuda):
            why = f'CUDA {release} is newer than what the driver runs (CUDA {driver_cuda})'
        if not why and wanted and nvcc_of:
            v = nvcc_of(release)
            if not (v == exact if exact else bool(v) and matches(wanted, v)):
                why = f'CUDA {release} has nvcc {v}, not {wanted}'
        return why

    why = None
    for strict in ((True, False) if wanted else (True,)):
        for release in reversed(candidates):
            why = why_not(release, strict)
            if not why:
                warning = None if strict else (
                    f'CUDA {release} is newer than what the driver runs (CUDA {driver_cuda}): its programs run '
                    f'through CUDA minor version compatibility (no PTX JIT, no features of a newer driver)')
                return release, warning
    return None, why


def lib_components(names):
    """The components of the libraries asked for by name (cublas, $cublas, libcublas, cublasLt), in
    order; a name of no component (cudart, which comes with the compiler) gives none."""
    out = []
    for name in names or []:
        n = str(name).strip().lstrip('$').lower()
        if n.startswith('lib'):
            n = n[3:]
        for c in LIBRARIES.get(n, ()):
            if c not in out:
                out.append(c)
    return out


def components(m, platform, names = COMPILER):
    """The archives of these components for a platform: [(component, relative_path, sha256, size)]."""
    out = []
    for name in names:
        entry = m.get(name)
        a = entry.get(platform) if isinstance(entry, dict) else None
        if not isinstance(a, dict) or 'relative_path' not in a:
            continue
        if name not in [n for n, _, _, _ in out]:
            out.append((name, a['relative_path'], a.get('sha256'), int(a.get('size') or 0)))
    return out


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def unpack_into(archive, root):
    """Unpack a component archive (<component>-<platform>-<version>-archive/ inside) into the toolkit
    root, merging its bin, include, lib, nvvm ... with those of the other components. A damaged
    archive raises ValueError."""
    tmp = root + '.unpacking'
    shutil.rmtree(tmp, ignore_errors = True)
    os.makedirs(tmp)
    try:
        if archive.endswith('.zip'):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                try:
                    t.extractall(tmp, filter = 'data')
                except TypeError:   # Python < 3.12
                    t.extractall(tmp)
    except (tarfile.TarError, zipfile.BadZipFile, EOFError) as e:
        shutil.rmtree(tmp, ignore_errors = True)
        raise ValueError(f'{os.path.basename(archive)}: {e}') from e
    tops = os.listdir(tmp)
    src = os.path.join(tmp, tops[0]) if len(tops) == 1 and os.path.isdir(os.path.join(tmp, tops[0])) else tmp
    for dirpath, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        dst_dir = os.path.normpath(os.path.join(root, rel))
        os.makedirs(dst_dir, exist_ok = True)
        # symbolic links to folders are listed with the folders: move them as links
        for name in [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))] + filenames:
            dst = os.path.join(dst_dir, name)
            if os.path.lexists(dst) and not os.path.isdir(dst):
                os.remove(dst)
            os.replace(os.path.join(dirpath, name), dst)
    shutil.rmtree(tmp, ignore_errors = True)


def link_targets(root, platform):
    """targets/<target>/include and lib as links to include/ and lib/, where nvcc.profile looks for
    them on Linux."""
    target = TARGETS.get(platform)
    if not target:
        return None
    d = os.path.join(root, 'targets', target)
    os.makedirs(d, exist_ok = True)
    for name in ('include', 'lib'):
        link = os.path.join(d, name)
        if not os.path.lexists(link):
            os.symlink(os.path.join('..', '..', name), link)
    return d


def version_json(m, release, unpacked):
    """version.json as NVIDIA's installer writes it: the release and the components unpacked."""
    data = {'cuda': {'name': 'CUDA SDK', 'version': release}}
    for name in unpacked:
        entry = m.get(name) or {}
        data[name] = {'name': entry.get('name', name), 'version': entry.get('version')}
    return data
