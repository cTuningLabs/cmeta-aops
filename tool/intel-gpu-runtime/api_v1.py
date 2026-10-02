"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup intel-gpu-runtime": the Intel GPU compute runtime for Linux (see _desc.yaml) -
the system's when it has one, else Intel's release packages unpacked into the cache without
root, exported through LD_LIBRARY_PATH and OCL_ICD_FILENAMES.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import tarfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_deb import ar_members, extract_deb, sha256_of, zstd_decompress

GITHUB = 'https://github.com'
MODERN = '26.35.39758.10'   # Gen12 and later
LEGACY = '24.35.30872.36'   # legacy1: Gen8, Gen9, Gen11

# The packages of each release line: their GitHub path and sha256 (from the releases' checksum
# lists; Intel publishes none for the legacy graphics compiler and the Level Zero loader: those
# are the sha256 of the first download, 2026-10-02)
RELEASES = {
    MODERN: [
        ('intel/compute-runtime/releases/download/26.35.39758.10/intel-opencl-icd_26.35.39758.10-0_amd64.deb',
         '61712caaddeba3d38e4f79e2a0fb23fea25596ca2d72c3144c6eea2331ec4301'),
        ('intel/compute-runtime/releases/download/26.35.39758.10/libze-intel-gpu1_26.35.39758.10-0_amd64.deb',
         'c19a641b953d55aebbf1d51bec364a84bf629f985e02fbbe6dc70224c0e88470'),
        ('intel/compute-runtime/releases/download/26.35.39758.10/libigdgmm12_22.10.0_amd64.deb',
         '6031a63d6e8a12ce61c14efc15f2c8e727061286e3820b8594e6d00615e04d54'),
        ('intel/intel-graphics-compiler/releases/download/v2.41.5/intel-igc-core-2_2.41.5+22716_amd64.deb',
         '0a6e64a663ae65a0fa02d6912ae3b6b37cf85b90c21cc423fd9fef70aaf4f628'),
        ('intel/intel-graphics-compiler/releases/download/v2.41.5/intel-igc-opencl-2_2.41.5+22716_amd64.deb',
         '779e1b9e88098eb25711e9a8f67c2752665bad22f134aa40ed5649f6e1b87058'),
        ('oneapi-src/level-zero/releases/download/v1.34.0/libze1_1.34.0+u24.04_amd64.deb',
         '45210e4549cd965ad7b9f160eefe53cbcdba01af341bea7ac7ba0aedeeb613ba'),
    ],
    LEGACY: [
        ('intel/compute-runtime/releases/download/24.35.30872.36/intel-opencl-icd-legacy1_24.35.30872.36_amd64.deb',
         'bbe71e4f414259e06a10cde72c29a2bd78d41b2bb2f6f8463b1806797fe66e85'),
        ('intel/compute-runtime/releases/download/24.35.30872.36/intel-level-zero-gpu-legacy1_1.5.30872.36_amd64.deb',
         '40dfbd15ab62de036a00824b304a2aa1fa2d81ad60ef83da09cfe3c5a80c429f'),
        ('intel/compute-runtime/releases/download/24.35.30872.36/libigdgmm12_22.5.0_amd64.deb',
         'cc29d14df83cff1b3c6a66baa39257f0211b168ab43a99c2dc62a3734431bc23'),
        ('intel/intel-graphics-compiler/releases/download/igc-1.0.17537.24/intel-igc-core_1.0.17537.24_amd64.deb',
         'c1e1ecdfe2064c047c552651cfdcdafc504f2033afafba65654338b880048b67'),
        ('intel/intel-graphics-compiler/releases/download/igc-1.0.17537.24/intel-igc-opencl_1.0.17537.24_amd64.deb',
         'dd016400f87fa2b6a9fa9fbcca7eb4a2629174a29de679709f9bec5cede88b0e'),
        ('oneapi-src/level-zero/releases/download/v1.34.0/libze1_1.34.0+u24.04_amd64.deb',
         '45210e4549cd965ad7b9f160eefe53cbcdba01af341bea7ac7ba0aedeeb613ba'),
    ],
}

# The first byte of the PCI device ids of Intel's Gen8, Gen9 and Gen11 GPUs, which only the legacy1
# line supports: Broadwell 16xx, Braswell 22xx, Skylake 19xx, Kaby Lake 59xx, Apollo Lake 5Axx,
# Gemini Lake 31xx, Coffee/Whiskey Lake 3Exx, Comet Lake 9Bxx, Amber Lake 87xx, Ice Lake 8Axx,
# Elkhart Lake 45xx, Jasper Lake 4Exx
LEGACY_ID_PREFIXES = ('16', '22', '19', '59', '5a', '31', '3e', '9b', '87', '8a', '45', '4e')

MARKER = 'cmeta-intel-gpu-runtime.json'
LIB_DIRS = ('usr/lib/x86_64-linux-gnu', 'usr/local/lib')   # where the packages put their libraries
ICD_LIB = 'usr/lib/x86_64-linux-gnu/intel-opencl/libigdrcl.so'
# The legacy1 packages name theirs differently (and libze_intel_gpu_legacy1.so.1, intel_legacy1.icd)
ICD_LIBS = (ICD_LIB, 'usr/lib/x86_64-linux-gnu/intel-opencl/libigdrcl_legacy1.so')


def intel_gpus(sys_pci = '/sys/bus/pci/devices'):
    """The Intel display controllers, as (PCI address, device id), from sysfs (no lspci needed)."""
    found = []
    for dev in sorted(glob.glob(os.path.join(sys_pci, '*'))):
        try:
            values = {k: open(os.path.join(dev, k)).read().strip().lower() for k in ('vendor', 'class', 'device')}
        except OSError:
            continue
        if values['vendor'] == '0x8086' and values['class'].startswith('0x03'):
            found.append((os.path.basename(dev), values['device'].replace('0x', '')))
    return found


def line_for(device_ids):
    """The release line for these Intel GPUs: legacy1 when every one is Gen8-Gen11, else 26.35
    (also when nothing is known, as in WSL2, where the GPU is behind /dev/dxg)."""
    ids = [str(d).lower().replace('0x', '') for d in device_ids]
    if ids and all(d[:2] in LEGACY_ID_PREFIXES for d in ids):
        return LEGACY
    return MODERN


def system_icds(vendors = '/etc/OpenCL/vendors'):
    """The Intel OpenCL ICD libraries that the system's ICD loader lists (their .icd files)."""
    found = []
    for icd in sorted(glob.glob(os.path.join(vendors, '*.icd'))):
        try:
            with open(icd, encoding = 'utf-8', errors = 'replace') as f:
                lib = f.read().strip()
        except OSError:
            continue
        if 'igdrcl' not in lib:
            continue
        candidates = [lib] if os.path.isabs(lib) else [
            os.path.join(d, lib) for d in ('/usr/lib/x86_64-linux-gnu/intel-opencl', '/usr/lib/x86_64-linux-gnu',
                                            '/usr/lib64', '/usr/lib/intel-opencl', '/usr/lib', '/usr/local/lib')]
        path = next((p for p in candidates if os.path.isfile(p)), None)
        if path and path not in found:
            found.append(path)
    return found


def package_version():
    """The version of the system's Intel OpenCL package (dpkg or rpm), or None."""
    queries = [['dpkg-query', '-W', '-f', '${Version}', name] for name in ('intel-opencl-icd', 'intel-opencl-icd-legacy1')]
    queries += [['rpm', '-q', '--qf', '%{VERSION}', name] for name in ('intel-compute-runtime', 'intel-opencl')]
    for q in queries:
        if not shutil.which(q[0]):
            continue
        try:
            r = subprocess.run(q, capture_output = True, text = True, timeout = 20)
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.match(r'(\d+\.\d+\.\d+(?:\.\d+)?)', r.stdout.strip()) if r.returncode == 0 else None
        if m:
            return m.group(1)
    return None


def device_access():
    """The GPU device nodes (/dev/dri/renderD*, or /dev/dxg in WSL2) and whether this user can open them."""
    nodes = sorted(glob.glob('/dev/dri/renderD*')) + (['/dev/dxg'] if os.path.exists('/dev/dxg') else [])
    return {n: os.access(n, os.R_OK | os.W_OK) for n in nodes}


def root_of(lib):
    """The unpacked root of a cMeta install for its libigdrcl.so (where the marker is), or None."""
    root = lib
    for _ in ICD_LIB.split('/'):
        root = os.path.dirname(root)
    return root if os.path.isfile(os.path.join(root, MARKER)) else None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _entry(self, lib):
        """A detected runtime: its ICD library, version and how to use it."""
        root = root_of(lib)
        if root:
            with open(os.path.join(root, MARKER), encoding = 'utf-8') as f:
                marker = json.load(f)
            return {'path': lib, 'detected_version': marker['version'],
                    'features': {'kind': 'cmeta', 'root': root, 'legacy': marker['version'] == LEGACY,
                                 'lib_dirs': [os.path.join(root, d) for d in LIB_DIRS]}}
        version = package_version()
        if not version:
            return None
        return {'path': lib, 'detected_version': version,
                'features': {'kind': 'system', 'root': None, 'legacy': version.startswith('24.35') or None,
                             'lib_dirs': []}}

    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        The Intel OpenCL ICD (libigdrcl.so) of a runtime this setup unpacked (this cache entry,
        or --tool_path) or of the system (/etc/OpenCL/vendors, with its dpkg or rpm version).
        Features: kind (cmeta | system), root, lib_dirs, legacy.
        """

        uname = ctx['tasks']['global']['host']['os']['uname']
        if uname != 'linux':
            return {'return': 0, 'parsed_paths_with_versions': []}

        libs = []
        if params.get('tool_path'):
            libs = [os.path.abspath(params['tool_path'])]
        else:
            libs = [p for lib in ICD_LIBS for p in sorted(glob.glob(os.path.join(os.getcwd(), 'content', '*', lib)))]
            libs += system_icds()

        parsed = []
        for lib in libs:
            if os.path.isfile(lib):
                entry = self._entry(lib)
                if entry:
                    parsed.append(entry)

        return {'return': 0, 'parsed_paths_with_versions': parsed}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        Export an unpacked runtime for the steps that follow (also when replayed from the cache):
        its libraries on LD_LIBRARY_PATH (the ICD's graphics compiler and gmmlib, the Level Zero
        driver and loader) and its ICD in OCL_ICD_FILENAMES. Say when the GPU device cannot be
        opened (the render group).
        """

        features = result.get('features', {})
        if features.get('kind') == 'cmeta' and result.get('path'):
            env = {'+LD_LIBRARY_PATH': [d for d in features.get('lib_dirs', []) if os.path.isdir(d)],
                   '+OCL_ICD_FILENAMES': [result['path']]}
            result.setdefault('_aggregate', {}).setdefault('env', {}).update(env)

        con = ctx['control'].get('con', False)
        denied = [n for n, ok in device_access().items() if not ok]
        if denied and con:
            print ('')
            print (f'WARNING: the Intel GPU runtime is ready, but this user cannot open {", ".join(denied)}: '
                   f'add it to the render group (sudo usermod -aG render $USER, then log in again)')

        return {'return': 0, 'result': result}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Intel's release packages of one line (--version, else the line of the Intel GPU), checked
        against their sha256 and unpacked into this cache entry (content/<version>/), without root.
        """

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        c = params.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if uname == 'windows':
            return self.cm.error('on Windows the Intel graphics driver brings the OpenCL and Level Zero runtimes: '
                                 'install or update the Intel graphics driver')
        if uname != 'linux' or uarch != 'amd64':
            return self.cm.error(f'Intel publishes the GPU compute runtime for Linux on x86_64 only (here {uname}/{uarch})')

        gpus = intel_gpus()
        version = str(params.get('version_simple') or params.get('version') or line_for([d for _, d in gpus]))
        if version not in RELEASES:
            return self.cm.error(f'no packages known for the Intel GPU runtime {version} (known: {", ".join(RELEASES)})')

        if con:
            print ('')
            what = 'legacy1, for Gen8-Gen11 GPUs' if version == LEGACY else 'for Gen12 and later GPUs'
            ids = ', '.join(f'8086:{d}' for _, d in gpus) or 'no Intel GPU on the PCI bus (WSL2?)'
            print (f'{space}INFO: Intel GPU runtime {version} ({what}; {ids})')

        work = os.getcwd()
        downloads = os.path.join(work, 'downloads')
        root = os.path.join(work, 'content', version)
        pinned = {}
        for path, sha in RELEASES[version]:
            name = path.rsplit('/', 1)[-1]
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                                'arg1': 'download-file,03fed13e2e0447cf',
                                'url': f'{GITHUB}/{path}', 'directory': 'downloads', 'filename': name,
                                'env': params.get('env'), 'timeout': params.get('timeout'),
                                'con': con, 'quiet': quiet, 'verbose': verbose})
            if self.cm.catch_error(r): return r
            deb = os.path.join(downloads, name)
            digest = sha256_of(deb)
            if sha and digest != sha:
                return self.cm.error(f'{name}: sha256 {digest} is not the published {sha}')
            pinned[name] = digest
            try:
                extract_deb(deb, root)
            except (OSError, ValueError, RuntimeError, tarfile.TarError) as e:
                return self.cm.error(f'cannot unpack {name}: {e}')

        lib = next((os.path.join(root, p) for p in ICD_LIBS if os.path.isfile(os.path.join(root, p))), None)
        if not lib:
            return self.cm.error(f'the Intel GPU runtime {version} was unpacked but {root} has no libigdrcl')

        # The ICD file too, for tools that read OCL_ICD_VENDORS instead of OCL_ICD_FILENAMES
        vendors = os.path.join(root, 'etc', 'OpenCL', 'vendors')
        os.makedirs(vendors, exist_ok = True)
        with open(os.path.join(vendors, 'intel.icd'), 'w', encoding = 'utf-8') as f:
            f.write(lib + '\n')
        with open(os.path.join(root, MARKER), 'w', encoding = 'utf-8') as f:
            json.dump({'version': version, 'packages': [p for p, _ in RELEASES[version]], 'sha256': pinned,
                       'gpus': [f'{a} 8086:{d}' for a, d in gpus]}, f, indent = 2)

        shutil.rmtree(downloads, ignore_errors = True)
        return {'return': 0, 'install_cmd': None, 'found_path': lib}
