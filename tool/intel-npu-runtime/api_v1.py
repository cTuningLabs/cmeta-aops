"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup intel-npu-runtime": the user-space driver of the Intel NPU for Linux (see
_desc.yaml) - the system's when it has one, else Intel's release packages unpacked into the cache
without root and exported through LD_LIBRARY_PATH. The kernel driver (intel_vpu) and the NPU
firmware come with the distribution.
"""

import glob
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_deb import extract_deb, sha256_of

GITHUB = 'https://github.com'
UBUNTU = 'https://archive.ubuntu.com/ubuntu'
VERSION = '1.38.0'

# Intel's archive of the driver packages for each Ubuntu release, with GitHub's sha256 digest,
# and its download size (MB); unpacked, the driver and its compiler take about 135 MB
TARBALLS = {
    '24.04': ('intel/linux-npu-driver/releases/download/v1.38.0/linux-npu-driver-v1.38.0.20260910-34487311128-ubuntu2404.tar.gz',
              '1efcd4b60c22abee751d8f2705962cbcc2a569de45c7e0e670cf08afbfcdc1d2'),
    '26.04': ('intel/linux-npu-driver/releases/download/v1.38.0/linux-npu-driver-v1.38.0.20260910-34487311128-ubuntu2604.tar.gz',
              '83685e6d92f4db1ca65e442846d487c7feb1335634b33994292ceb38f933bcc7'),
}
TARBALL_MB = {'24.04': 56, '26.04': 58}

# The packages unpacked from it: the Level Zero driver of the NPU and the compiler in driver.
# (intel-fw-npu goes to /lib/firmware, which needs root; the distributions ship NPU firmware.)
PACKAGES = ('intel-level-zero-npu', 'intel-driver-compiler-npu')

# The Level Zero loader (as tool/intel-gpu-runtime pins it; its 24.04 build suits 26.04 too)
LEVEL_ZERO = ('oneapi-src/level-zero/releases/download/v1.34.0/libze1_1.34.0+u24.04_amd64.deb',
              '45210e4549cd965ad7b9f160eefe53cbcdba01af341bea7ac7ba0aedeeb613ba')

# oneTBB, which the compiler needs, from the Ubuntu release's own archive (the sha256 of its apt
# index), when the system has no libtbb.so.12
TBB = {
    '24.04': ('pool/universe/o/onetbb/libtbb12_2021.11.0-2ubuntu2_amd64.deb',
              '78e2c79f5749fc5c55b32f9745e07d5c3480be574fd4d64bb0325cbec4206b06'),
    '26.04': ('pool/universe/o/onetbb/libtbb12_2022.3.0-2_amd64.deb',
              '9e58d374ec6f5c3a690f5a427819d7d762030d474aa3ea91f52d0c7226ff2741'),
}

# The glibc that the 24.04 build needs (release_for() picks the 26.04 build on 26.04 and later only)
GLIBC_MIN = (2, 38)

MARKER = 'cmeta-intel-npu-runtime.json'
LIB_DIR = 'usr/lib/x86_64-linux-gnu'
DRIVER_LIB = LIB_DIR + '/libze_intel_npu.so.1'
COMPILER_LIB = LIB_DIR + '/libopenvino_intel_npu_compiler.so'
SYSTEM_LIB_DIRS = ('/usr/lib/x86_64-linux-gnu', '/usr/lib64', '/usr/lib', '/usr/local/lib')
FIRMWARE_DIRS = ('/lib/firmware/updates/intel/vpu', '/lib/firmware/intel/vpu')


def release_for(version_id):
    """The Ubuntu build to unpack for this distribution release: 24.04 or 26.04 (any newer one),
    else the 24.04 build (it needs glibc 2.38 or newer)."""
    v = str(version_id or '')
    if v in TARBALLS:
        return v
    nums = [int(x) for x in re.findall(r'\d+', v)[:2]]
    return '26.04' if nums and nums >= [26, 4] else '24.04'


def glibc_of(libc_ver):
    """The glibc version (major, minor) from platform.libc_ver(), or None (musl, or unknown)."""
    lib, version = libc_ver
    m = re.match(r'(\d+)\.(\d+)', version or '') if lib == 'glibc' else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def system_lib(name, dirs = SYSTEM_LIB_DIRS):
    """A system library by its file name, or None."""
    return next((os.path.join(d, name) for d in dirs if os.path.exists(os.path.join(d, name))), None)


def firmware_files(dirs = FIRMWARE_DIRS):
    """The NPU firmware files the kernel can load (also compressed: .zst, .xz)."""
    found = []
    for d in dirs:
        found += sorted(glob.glob(os.path.join(d, 'vpu_*_v*.bin*')))
    return found


def npu_access(accel = '/dev/accel'):
    """The NPU device nodes and whether this user can open them (the render group)."""
    return {n: os.access(n, os.R_OK | os.W_OK) for n in sorted(glob.glob(os.path.join(accel, 'accel*')))}


def package_version():
    """The version of the system's NPU driver package (dpkg), or None."""
    if not shutil.which('dpkg-query'):
        return None
    try:
        r = subprocess.run(['dpkg-query', '-W', '-f', '${Version}', 'intel-level-zero-npu'],
                           capture_output = True, text = True, timeout = 20)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r'(\d+\.\d+\.\d+)', r.stdout.strip()) if r.returncode == 0 else None
    return m.group(1) if m else None


def root_of(lib):
    """The unpacked root of a cMeta install for its libze_intel_npu.so.1 (where the marker is), or None."""
    root = lib
    for _ in DRIVER_LIB.split('/'):
        root = os.path.dirname(root)
    return root if os.path.isfile(os.path.join(root, MARKER)) else None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _entry(self, lib):
        """A detected driver: its library, version and how to use it."""
        root = root_of(lib)
        if root:
            with open(os.path.join(root, MARKER), encoding = 'utf-8') as f:
                marker = json.load(f)
            return {'path': lib, 'detected_version': marker['version'],
                    'features': {'kind': 'cmeta', 'root': root, 'release': marker.get('release'),
                                 'lib_dirs': [os.path.join(root, LIB_DIR)]}}
        version = package_version()
        if not version:
            return None
        return {'path': lib, 'detected_version': version, 'features': {'kind': 'system', 'root': None, 'lib_dirs': []}}

    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        The Level Zero driver of the NPU (libze_intel_npu.so.1) that this setup unpacked (this
        cache entry, or --tool_path) or of the system (with its dpkg version). Features: kind
        (cmeta | system), root, lib_dirs, release.
        """

        uname = ctx['tasks']['global']['host']['os']['uname']
        if uname != 'linux':
            return {'return': 0, 'parsed_paths_with_versions': []}

        if params.get('tool_path'):
            libs = [os.path.abspath(params['tool_path'])]
        else:
            libs = sorted(glob.glob(os.path.join(os.getcwd(), 'content', '*', DRIVER_LIB)))
            lib = system_lib('libze_intel_npu.so.1')
            if lib:
                libs.append(lib)

        parsed = [e for e in (self._entry(lib) for lib in libs if os.path.isfile(lib)) if e]

        return {'return': 0, 'parsed_paths_with_versions': parsed}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        Export an unpacked driver for the steps that follow (also when replayed from the cache):
        its libraries (the NPU driver, its compiler, the Level Zero loader, oneTBB) on
        LD_LIBRARY_PATH. Say when the NPU device cannot be opened (the render group) or when no
        NPU firmware is installed.
        """

        features = result.get('features', {})
        if features.get('kind') == 'cmeta' and result.get('path'):
            env = {'+LD_LIBRARY_PATH': [d for d in features.get('lib_dirs', []) if os.path.isdir(d)]}
            result.setdefault('_aggregate', {}).setdefault('env', {}).update(env)

        con = ctx['control'].get('con', False)
        if con:
            denied = [n for n, ok in npu_access().items() if not ok]
            if denied:
                print ('')
                print (f'WARNING: the Intel NPU driver is ready, but this user cannot open {", ".join(denied)}: '
                       f'add it to the render group (sudo usermod -aG render $USER, then log in again)')
            if not firmware_files():
                print ('')
                print (f'WARNING: no NPU firmware in {" or ".join(FIRMWARE_DIRS)}: install linux-firmware, or '
                       f'Intel\'s intel-fw-npu {VERSION} (sudo dpkg -i), then reboot')

        return {'return': 0, 'result': result}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Intel's driver packages for this Ubuntu release (Level Zero NPU driver, compiler), the
        Level Zero loader and, when the system has none, oneTBB: each checked against its sha256
        and unpacked into this cache entry (content/<version>/), without root.
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if uname == 'windows':
            return self.cm.error('on Windows the Intel NPU driver comes from Windows Update or Intel\'s driver '
                                 'package: install or update "Intel(R) AI Boost"')
        if uname != 'linux' or uarch != 'amd64':
            return self.cm.error(f'Intel publishes the Linux NPU driver for x86_64 only (here {uname}/{uarch})')

        glibc = glibc_of(platform.libc_ver())
        if glibc and glibc < GLIBC_MIN:
            return self.cm.error(f'the Intel NPU driver {VERSION} needs glibc {GLIBC_MIN[0]}.{GLIBC_MIN[1]} or newer '
                                 f'(Ubuntu 24.04 and later): this system has glibc {glibc[0]}.{glibc[1]}')

        version_id = _global['host'].get('os_extra', {}).get('version_id')
        if not version_id and os.path.isfile('/etc/os-release'):
            m = re.search(r'^VERSION_ID="?([^"\n]+)', open('/etc/os-release').read(), re.M)
            version_id = m.group(1) if m else None
        release = release_for(version_id)

        tbb_needed = not system_lib('libtbb.so.12')

        if con:
            print ('')
            print (f'{space}INFO: Intel NPU driver {VERSION} (the Ubuntu {release} build: a {TARBALL_MB[release]} MB download, '
                   f'about 135 MB unpacked) from {GITHUB}/intel/linux-npu-driver'
                   + (', with oneTBB from Ubuntu' if tbb_needed else ''))

        work = os.getcwd()
        downloads = os.path.join(work, 'downloads')
        root = os.path.join(work, 'content', VERSION)

        def fetch(url, sha):
            name = url.rsplit('/', 1)[-1]
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'download-file,03fed13e2e0447cf', 'url': url, 'directory': 'downloads',
                                'filename': name, 'env': params.get('env'), 'timeout': params.get('timeout'),
                                'con': con, 'quiet': quiet, 'verbose': verbose})
            if self.cm.catch_error(r): return r
            path = os.path.join(downloads, name)
            digest = sha256_of(path)
            if digest != sha:
                return self.cm.error(f'{name}: sha256 {digest} is not the published {sha}')
            return {'return': 0, 'path': path, 'sha256': digest}

        tar_path, tar_sha = TARBALLS[release]
        r = fetch(f'{GITHUB}/{tar_path}', tar_sha)
        if self.cm.catch_error(r): return r
        try:
            with tarfile.open(r['path']) as t:
                debs = [m for m in t.getmembers() if m.name.endswith('.deb')
                        and os.path.basename(m.name).split('_')[0] in PACKAGES]
                for m in debs:
                    try:
                        t.extract(m, downloads, filter = 'data')
                    except TypeError:   # Python < 3.12
                        t.extract(m, downloads)
        except (OSError, tarfile.TarError) as e:
            return self.cm.error(f'cannot unpack {r["path"]}: {e}')
        if len(debs) != len(PACKAGES):
            return self.cm.error(f'{r["path"]} lacks some of {", ".join(PACKAGES)}')

        unpacked = {os.path.basename(tar_path): tar_sha}
        for m in debs:
            deb = os.path.join(downloads, m.name)
            try:
                extract_deb(deb, root)
            except (OSError, ValueError, RuntimeError, tarfile.TarError) as e:
                return self.cm.error(f'cannot unpack {os.path.basename(deb)}: {e}')
            unpacked[os.path.basename(deb)] = sha256_of(deb)

        extra = [(f'{GITHUB}/{LEVEL_ZERO[0]}', LEVEL_ZERO[1])]
        if tbb_needed:
            extra.append((f'{UBUNTU}/{TBB[release][0]}', TBB[release][1]))
        for url, sha in extra:
            r = fetch(url, sha)
            if self.cm.catch_error(r): return r
            try:
                extract_deb(r['path'], root)
            except (OSError, ValueError, RuntimeError, tarfile.TarError) as e:
                return self.cm.error(f'cannot unpack {os.path.basename(r["path"])}: {e}')
            unpacked[os.path.basename(r['path'])] = r['sha256']

        lib = os.path.join(root, DRIVER_LIB)
        if not os.path.isfile(lib) or not os.path.isfile(os.path.join(root, COMPILER_LIB)):
            return self.cm.error(f'the Intel NPU driver {VERSION} was unpacked but {root} lacks its driver or compiler')

        with open(os.path.join(root, MARKER), 'w', encoding = 'utf-8') as f:
            json.dump({'version': VERSION, 'release': release, 'sha256': unpacked, 'tbb': tbb_needed}, f, indent = 2)

        shutil.rmtree(downloads, ignore_errors = True)
        return {'return': 0, 'install_cmd': None, 'found_path': lib}
