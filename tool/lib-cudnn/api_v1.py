"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup lib-cudnn": NVIDIA cuDNN for the CUDA toolkit that tool/nvcc set up. A cuDNN
installed on the system (NVIDIA's installer folders on Windows, the toolkit's include folder on
Linux) is detected when its CUDA version matches nvcc's. Otherwise the pinned release of NVIDIA's
public cuDNN redistributable (the archive for this OS, CPU and CUDA major version, SHA-256 checked)
is downloaded into the cache and unpacked: include/, lib/ (and bin/ on Windows). cuDNN's own license
(LICENSE.txt in the archive) applies to its use.
"""

import json
import os
import re
import tarfile
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256

REDIST = 'https://developer.download.nvidia.com/compute/cudnn/redist/'
VERSION = '9.27.0.42'

# NVIDIA's platform names for cMeta's uname and uarch
PLATFORMS = {('linux', 'amd64'): 'linux-x86_64', ('linux', 'arm64'): 'linux-sbsa',
             ('windows', 'amd64'): 'windows-x86_64', ('windows', 'arm64'): 'windows-arm64'}

# cuDNN 9.27.0.42 (redistrib_9.27.0.json, 2026-09-29): the archive and its SHA-256 per platform and
# CUDA major version. Other 9.x versions are read from their redistrib_<version>.json.
ASSETS = {
    'linux-x86_64': {
        12: ('cudnn/linux-x86_64/cudnn-linux-x86_64-9.27.0.42_cuda12-archive.tar.xz',
             'dc45f8c5fd44955c6e950c690ea92c28ea848ffb1fefbaabf3a9d175d961263a'),
        13: ('cudnn/linux-x86_64/cudnn-linux-x86_64-9.27.0.42_cuda13-archive.tar.xz',
             'dd3245ba3aca8593934fc946d08649ad3a5ee8500e8da3870bc23bf7ddccd7f9'),
    },
    'linux-sbsa': {
        12: ('cudnn/linux-sbsa/cudnn-linux-sbsa-9.27.0.42_cuda12-archive.tar.xz',
             '397efa8eb25285ee289ef10274e643218edb7cbe6088cdb453afca1030e149c9'),
        13: ('cudnn/linux-sbsa/cudnn-linux-sbsa-9.27.0.42_cuda13-archive.tar.xz',
             '74912c0c6182d7af2cd35619241674781dd4ca716a5ba87b01157b78ee959001'),
    },
    'windows-x86_64': {
        12: ('cudnn/windows-x86_64/cudnn-windows-x86_64-9.27.0.42_cuda12-archive.zip',
             '93949680d6499ad0f17fc1abb131825c9dd41b460844513f608e840e0c8ce72b'),
        13: ('cudnn/windows-x86_64/cudnn-windows-x86_64-9.27.0.42_cuda13-archive.zip',
             '15595c7b52896262a0e590f02b3b3851c6a2c9046a72047526deaf59a9cbf7d5'),
    },
    'windows-arm64': {
        13: ('cudnn/windows-arm64/cudnn-windows-arm64-9.27.0.42_cuda13-archive.zip',
             'c34d906b19df16d370d31b78b1ee480a07e6f827fdabfea63acb914528a9b85c'),
    },
}


def cuda_major(version):
    """The major version of a CUDA version string ("13.3.73" -> 13), or None."""
    m = re.match(r'\s*(\d+)', str(version or ''))
    return int(m.group(1)) if m else None


def archive_cuda_major(folder):
    """The CUDA major version a redistributable archive folder was built for
    (".../cudnn-linux-x86_64-9.27.0.42_cuda13-archive" -> 13), or None for other folders."""
    m = re.search(r'_cuda(\d+)-archive$', os.path.basename(os.path.normpath(folder)))
    return int(m.group(1)) if m else None


def asset_for(platform, major, version = VERSION, index = None):
    """The redistributable archive for a platform and a CUDA major version: (relative path, sha256),
    or None. The pinned version comes from ASSETS; another version from its redistrib index (the
    parsed JSON of redistrib_<version>.json)."""
    if version == VERSION and index is None:
        entry = ASSETS.get(platform, {}).get(major)
        return tuple(entry) if entry else None
    files = (index or {}).get('cudnn', {}).get(platform, {})
    entry = files.get(f'cuda{major}')
    if isinstance(entry, dict) and entry.get('relative_path') and entry.get('sha256'):
        return (entry['relative_path'], entry['sha256'])
    return None


def detected_version(version):
    """The version as cudnn_version.h reports it: the first three numbers ("9.27.0.42" -> "9.27.0")."""
    return '.'.join(str(version).split('.')[:3])


def index_name(version):
    """redistrib_<version>.json names the version with three components (redistrib_9.27.0.json
    holds 9.27.0.42)."""
    return 'redistrib_' + detected_version(version) + '.json'


# The oldest GPU a cuDNN 9 release runs on (compute capability x 10). The early 9.x releases carry
# Maxwell kernels (5.0; 9.0.0, 9.5.1 and 9.10.2 run on a Maxwell GPU); from MAXWELL_DROPPED on,
# NVIDIA's support matrix says 7.5 (Turing) and newer, and 9.11.1, 9.12.0 and 9.27.0 fail on the same
# GPU: cudnnCreate still succeeds there, the first kernel returns CUDNN_STATUS_EXECUTION_FAILED(_CUDART),
# deep inside a program. The boundary was found by trying NVIDIA's releases on that GPU.
MAXWELL_DROPPED = (9, 11)
GPU_ARCH_MIN_EARLY = 50
GPU_ARCH_MIN = 75


def version_numbers(version):
    """The numbers of a version string ("9.27.0" -> (9, 27, 0)); () when there is none."""
    return tuple(int(x) for x in re.findall(r'\d+', str(version or '')))


def gpu_arch_min_for(cudnn_version):
    """The oldest compute capability (x 10) this cuDNN version runs on, or None for a cuDNN that is
    not 9.x (8.x and older: not described here)."""
    n = version_numbers(cudnn_version)
    if not n or n[0] != 9:
        return None
    return GPU_ARCH_MIN if n[:2] >= MAXWELL_DROPPED else GPU_ARCH_MIN_EARLY


def gpu_too_old(gpu_arch_min, cudnn_version):
    """Why this GPU cannot run this cuDNN (its compute capability x 10 below the version's minimum),
    or None. None also when the GPU or the minimum is unknown."""
    try:
        arch = int(gpu_arch_min)
    except (TypeError, ValueError):
        return None
    need = gpu_arch_min_for(cudnn_version)
    if need is None or arch >= need:
        return None
    hint = (f'; cuDNN releases before {MAXWELL_DROPPED[0]}.{MAXWELL_DROPPED[1]} still run on it '
            f'(--version=9.10.2, for example)' if need == GPU_ARCH_MIN else '')
    return (f'cuDNN {cudnn_version} runs on GPUs of compute capability {need / 10} and newer; this GPU is '
            f'{arch / 10}: its kernels would fail (CUDNN_STATUS_EXECUTION_FAILED). Use a newer GPU{hint}, '
            f'or --with.any_gpu to set cuDNN up anyway (for builds that run elsewhere)')


def find_cudnn_header(root):
    """include/cudnn.h of the unpacked archive under root, or None."""
    for d, dirs, files in os.walk(root):
        if 'cudnn.h' in files and os.path.basename(d) == 'include':
            return os.path.join(d, 'cudnn.h')
    return None


def unpack(archive, dest):
    """Unpack a .tar.xz / .tar.gz / .zip archive into dest (Python's own tarfile and zipfile)."""
    os.makedirs(dest, exist_ok = True)
    if archive.lower().endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive, 'r:*') as t:
            t.extractall(dest)


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL cudnn api_v1 detect_versions")

        found_paths_with_versions = {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        uarch = ctx['tasks']['global']['host']['os']['uarch']
        if uarch == 'amd64':
            uarch = 'x64'

        nvcc = ctx['tasks']['global']['nvcc']
        cuda_version = nvcc['version']

        for path in paths:
             path_include = os.path.dirname(path)

             possible_cuda_ver = os.path.basename(path_include)
             cuda_ver = possible_cuda_ver if bool(re.fullmatch(r"\d[\d.]*", possible_cuda_ver)) else None

             # Prune by cuda ver
             if cuda_ver:
                 cuda_version_split = cuda_version.split('.')
                 cuda_ver_split = cuda_ver.split('.')

                 cuda_major_version = int(cuda_version_split[0])
                 cuda_major_ver = int(cuda_ver_split[0])
                 if cuda_major_ver != cuda_major_version:
                     continue

                 # Check cuda minor version ... (should be lower)
                 cuda_minor_version = int(cuda_version_split[1])
                 cuda_minor_ver = int(cuda_ver_split[1])

                 if cuda_minor_ver > cuda_minor_version:
                     continue

             path_cudnn_version = os.path.join(path_include, 'cudnn_version.h')
             if os.path.isfile(path_cudnn_version):
                 path_home = os.path.dirname(os.path.dirname(path_include)) if cuda_ver else os.path.dirname(path_include)

                 # A redistributable archive (cudnn-<platform>-<version>_cuda<N>-archive) is built
                 # for one CUDA major version: skip it for another toolkit
                 built_for = archive_cuda_major(path_home)
                 if built_for is not None and built_for != cuda_major(cuda_version):
                     continue

                 path_bin = os.path.join(path_home, 'bin')
                 if cuda_ver: 
                     path_bin = os.path.join(path_bin, cuda_ver)
                     if os.path.isdir(path_bin):
                         path_bin2 = os.path.join(path_bin, uarch)
                         if os.path.isdir(path_bin2):
                             path_bin = path_bin2

                 for x in ['lib64', 'lib']:
                     path_lib = os.path.join(path_home, x)
                     if os.path.isdir(path_lib):
                         if cuda_ver: 
                             path_lib2 = os.path.join(path_lib, cuda_ver)
                             if os.path.isdir(path_lib2):
                                 path_lib = path_lib2

                             if os.path.isdir(path_lib):
                                 path_lib2 = os.path.join(path_lib, uarch)
                                 if os.path.isdir(path_lib2):
                                     path_lib = path_lib2
                         elif os.path.isdir(os.path.join(path_lib, uarch)):
                             # The Windows redistributable archive: lib/x64/cudnn.lib
                             path_lib = os.path.join(path_lib, uarch)
                         break


                 r = self.cm.utils.files.read_file(path_cudnn_version)
                 if self.cm.catch_error(r): return r

                 s = r['data']

                 cudnn_version_major = int(re.search(r"#define\s+CUDNN_MAJOR\s+(\d+)", s).group(1))
                 cudnn_version_minor = int(re.search(r"#define\s+CUDNN_MINOR\s+(\d+)", s).group(1))
                 cudnn_version_patch = int(re.search(r"#define\s+CUDNN_PATCHLEVEL\s+(\d+)", s).group(1))
                 version = str(cudnn_version_major) + '.' + str(cudnn_version_minor) + '.' + str(cudnn_version_patch)

                 features = {}

                 paths = {}

                 if uname == 'windows':
                     paths['dynamic_lib'] = path_bin
                     paths['qdynamic_lib'] = self.cm.q(path_bin)
                     paths['dynamic_libs'] = [path_bin]

                 else:
                     paths['dynamic_lib'] = path_lib
                     paths['qdynamic_lib'] = self.cm.q(path_lib)
                     paths['dynamic_libs'] = [path_lib]

                 paths['lib'] = path_lib
                 paths['qlib'] = self.cm.q(path_lib)
                 paths['libs'] = [path_lib]

                 paths['home'] = path_home
                 paths['qhome'] = self.cm.q(path_home)

                 lib_names = []

                 if os.path.isdir(path_include):
                     paths['include'] = path_include
                     paths['qinclude'] = self.cm.q(path_include)

                     paths['includes'] = [path_include]

                 lib_names = [
                    '$cudnn' # $ means that do not add lib prefix ...
                 ]

                 features = {
                   'paths': paths,
                 }

                 if lib_names:
                     features['lib_names'] = lib_names

                 if cuda_version:
                     features['cuda_version'] = cuda_version


                 found_paths_with_versions[path] = {'output':version, 'features':features}

        return {'return':0, 'found_paths_with_versions':found_paths_with_versions}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        NVIDIA's public cuDNN redistributable for this OS, CPU and the CUDA major version of the nvcc
        set up: downloaded into the cache entry, SHA-256 checked, unpacked; found_path is its
        include/cudnn.h, which the detection then reads as any other cuDNN. 16 (the declarative
        install, i.e. install_help_text) where NVIDIA publishes no archive: macOS, other CPUs,
        CUDA 11 and older, a version that is not exact.
        """
        _global = ctx['tasks']['global']
        host = _global['host']['os']
        c = params.get('control', {})
        con = c.get('con', False)

        platform = PLATFORMS.get((host['uname'], host['uarch']))
        if not platform:
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'NVIDIA publishes cuDNN for Linux (x86_64, arm64) and Windows (x64, arm64), not for '
                             f'{host["uname"]} {host["uarch"]}'}

        major = cuda_major(_global.get('nvcc', {}).get('version'))
        if major is None or not any(major in ASSETS.get(p, {}) for p in ASSETS):
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'cuDNN {VERSION} is published for CUDA 12 and 13; the CUDA toolkit set up is '
                             f'{_global.get("nvcc", {}).get("version")}: set up a newer one (cx tool setup nvcc --version=13) '
                             f'or install a matching cuDNN by hand'}

        version = params.get('version')
        version_simple = params.get('version_simple')
        if version and not version_simple:
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'the cuDNN download needs an exact version (--version=9.26.0, for example), not "{version}"'}
        # The version a user asks for is the one cudnn_version.h reports (three numbers, "9.26.0");
        # NVIDIA's index of that version (redistrib_9.26.0.json) names the build (9.26.0.51)
        v = version_simple or VERSION
        if v != VERSION and detected_version(v) == detected_version(VERSION):
            v = VERSION

        index = None
        if v != VERSION:
            r = _download(self, ctx, params, REDIST + index_name(v), 'download', index_name(v))
            if r['return'] > 0:
                return r
            with open(r['path'], encoding = 'utf-8') as f:
                index = json.load(f)
            v = index.get('cudnn', {}).get('version', v)
            if detected_version(v) != detected_version(version_simple or v):
                return self.cm.error(f'{index_name(version_simple)} of NVIDIA holds cuDNN {v}, not {version_simple}')
        asset = asset_for(platform, major, v, index)
        if not asset:
            return {'return': 16, 'install_cmd': cmd,
                    'error': f'cuDNN {v} has no archive for {platform} and CUDA {major}'}
        relative_path, sha256 = asset
        name = relative_path.split('/')[-1]

        if con:
            print(f'INFO: cuDNN {v} for {platform} and CUDA {major}: {REDIST}{relative_path}')

        r = _download(self, ctx, params, REDIST + relative_path, 'download', name)
        if r['return'] > 0:
            return r
        digest = _sha256(r['path'])
        if digest != sha256:
            os.remove(r['path'])
            return self.cm.error(f'SHA-256 mismatch for {name}: expected {sha256}, got {digest}')

        content = os.path.join(os.getcwd(), 'content')
        unpack(r['path'], content)
        os.remove(r['path'])

        header = find_cudnn_header(content)
        if not header:
            return self.cm.error(f'no include/cudnn.h in {name}')
        return {'return': 0, 'install_cmd': None, 'found_path': header}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        if result['return'] == 0 and not params.get('version_check', False):
            _with = params.get('with', {})

#            if not _with.get('static', False):

            features = result['features']

            path_dyn_lib = features['paths']['dynamic_lib']

            if os.path.isdir(path_dyn_lib):
                features['paths']['found_dynamic_lib_paths'] = [path_dyn_lib]

            # The GPU of this machine (task/target--cuda): too old for this cuDNN is an error here,
            # where the message names the cause, rather than a failed kernel inside a program
            if not _with.get('any_gpu'):
                cuda = ctx['tasks']['global'].get('cuda', {}).get('features', {})
                why = gpu_too_old(cuda.get('compute_cap_int_min'), result.get('version'))
                if why:
                    return self.cm.error(why)
            features['gpu_arch_min'] = gpu_arch_min_for(result.get('version'))

        return {'return':0}

