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

import yaml

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_deb import ar_members, extract_deb, sha256_of, zstd_decompress

GITHUB = 'https://github.com'
DESC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_desc.yaml')


def load_lines(desc_path = DESC):
    """
    The release lines of _desc.yaml (releases:), in their order: {<version>: {'for', 'default', 'device_id_prefixes',
    'packages': [{'path', 'sha256', 'provides'}]}}.
    """
    with open(desc_path, encoding = 'utf-8') as f:
        lines = (yaml.safe_load(f) or {}).get('releases') or {}
    return {str(version): line or {} for version, line in lines.items()}


LINES = load_lines()

# The packages of each line as (GitHub path, sha256); the default line (Gen12 and later) and the line older GPUs'
# device ids name (legacy1)
RELEASES = {version: [(p['path'], p.get('sha256')) for p in line.get('packages') or []] for version, line in LINES.items()}
MODERN = next(v for v, line in LINES.items() if line.get('default'))
LEGACY = next((v for v, line in LINES.items() if line.get('device_id_prefixes')), None)

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


def line_for(device_ids, lines = None):
    """
    The release line for these Intel GPUs: a line whose device_id_prefixes name every one of them (legacy1: Gen8-Gen11),
    else the default line (also when nothing is known, as in WSL2, where the GPU is behind /dev/dxg).
    """
    lines = LINES if lines is None else lines
    ids = [str(d).lower().replace('0x', '') for d in device_ids]
    for version, line in lines.items():
        prefixes = tuple(str(p).lower() for p in line.get('device_id_prefixes') or [])
        if ids and prefixes and all(d.startswith(prefixes) for d in ids):
            return version
    return next(v for v, line in lines.items() if line.get('default'))


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


def provided(version, lines = None):
    """What the packages of a line provide (provides: of _desc.yaml): [{'file', 'env', 'dir'}], relative to its root."""
    lines = LINES if lines is None else lines
    return [dict(p['provides']) for p in (lines.get(version) or {}).get('packages') or [] if p.get('provides')]


def version_key(path):
    """The numbers in a file name, for "the newest" of <name>-<version> files."""
    return [int(n) for n in re.findall(r'[0-9]+', os.path.basename(path))]


def command_link(root, rel_path):
    """
    A file a package provides, in an unpacked runtime: a command the package names <name>-<version> (its
    update-alternatives make <name>, which an unpacking without root does not run) gets a link <name> beside it, to
    the newest one. -> its path, or None when the runtime has neither. A file of that name that is there is kept.
    """
    plain = os.path.join(root, rel_path)
    if os.path.isfile(plain):
        return plain
    versioned = sorted((p for p in glob.glob(plain + '-*') if os.path.isfile(p)), key = version_key)
    if not versioned:
        return None
    os.symlink(os.path.basename(versioned[-1]), plain)
    return plain


def provide(root, version, lines = None):
    """The files the packages of a line provide, in an unpacked runtime, links made (command_link). -> those missing."""
    return [p['file'] for p in provided(version, lines) if not command_link(root, p['file'])]


def exports(root, version, lines = None):
    """
    The variables an unpacked line is used through by the steps that follow, besides its libraries and its ICD:
    {<variable>: [folders]} - the folder of each file its packages provide (dir:, else the file's own), the files
    that are there only.
    """
    env = {}
    for p in provided(version, lines):
        path = os.path.join(root, p['file'])
        if os.path.isfile(path):
            folder = os.path.join(root, p['dir']) if p.get('dir') else os.path.dirname(path)
            if folder not in env.setdefault(p['env'], []):
                env[p['env']].append(folder)
    return env


def missing_packages(marker):
    """
    The packages of the marker's release line that its install did not unpack: those added to the line after the
    runtime was unpacked (the offline compiler, the Level Zero headers - 2026-11-24/25), which its next use unpacks
    beside the others. A line no longer known: nothing to compare with.
    """
    listed = RELEASES.get(str(marker.get('version')))
    if not listed:
        return []
    had = set(marker.get('packages') or [])
    return [p for p, _ in listed if p not in had]


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
        driver and loader), its ICD in OCL_ICD_FILENAMES and the folders of what its packages
        provide (provides: of _desc.yaml - ocloc on PATH, the Level Zero headers on CPATH). A
        runtime unpacked before a package was added to its line gets it first. Say when the GPU
        device cannot be opened (the render group).
        """

        con = ctx['control'].get('con', False)
        features = result.get('features', {})
        if features.get('kind') == 'cmeta' and result.get('path'):
            root = features.get('root') or root_of(result['path'])
            r = self.complete(ctx, params, root)
            if r['return'] > 0 and con:
                print ('')
                print (f'WARNING: {r["error"]} - the runtime is used as it is')
            env = {'+LD_LIBRARY_PATH': [d for d in features.get('lib_dirs', []) if os.path.isdir(d)],
                   '+OCL_ICD_FILENAMES': [result['path']]}
            for variable, folders in exports(root, r.get('version') or result.get('version')).items():
                env['+' + variable] = folders
            result.setdefault('_aggregate', {}).setdefault('env', {}).update(env)

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
            what = LINES[version].get('for') or 'its GPUs'
            ids = ', '.join(f'8086:{d}' for _, d in gpus) or 'no Intel GPU on the PCI bus (WSL2?)'
            print (f'{space}INFO: Intel GPU runtime {version} ({what}; {ids})')

        root = os.path.join(os.getcwd(), 'content', version)
        r = self._unpack(ctx, params, os.getcwd(), root, RELEASES[version])
        if r['return'] > 0:
            return r
        pinned = r['sha256']

        lib = next((os.path.join(root, p) for p in ICD_LIBS if os.path.isfile(os.path.join(root, p))), None)
        if not lib:
            return self.cm.error(f'the Intel GPU runtime {version} was unpacked but {root} has no libigdrcl')

        # What the packages provide (provides: of _desc.yaml), with the links of their versioned commands
        missing = provide(root, version)
        if missing:
            return self.cm.error(f'the Intel GPU runtime {version} was unpacked but {root} has no {", ".join(missing)}')

        # The ICD file too, for tools that read OCL_ICD_VENDORS instead of OCL_ICD_FILENAMES
        vendors = os.path.join(root, 'etc', 'OpenCL', 'vendors')
        os.makedirs(vendors, exist_ok = True)
        with open(os.path.join(vendors, 'intel.icd'), 'w', encoding = 'utf-8') as f:
            f.write(lib + '\n')
        with open(os.path.join(root, MARKER), 'w', encoding = 'utf-8') as f:
            json.dump({'version': version, 'packages': [p for p, _ in RELEASES[version]], 'sha256': pinned,
                       'gpus': [f'{a} 8086:{d}' for a, d in gpus]}, f, indent = 2)

        return {'return': 0, 'install_cmd': None, 'found_path': lib}

    ############################################################
    def _unpack(self,
                ctx: dict,
                params: dict,
                entry: str,
                root: str,
                packages: list,
    ):
        """
        Download packages [(GitHub path, sha256)] into <entry>/downloads, check them against their sha256 and unpack
        them into root, without root rights. -> {'return': 0, 'sha256': {<package file>: <its sha256>}}
        """
        c = params.get('control') or ctx.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)

        downloads = os.path.join(entry, 'downloads')
        pinned = {}
        cwd = os.getcwd()
        os.chdir(entry)
        try:
            for path, sha in packages:
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
        finally:
            os.chdir(cwd)
            shutil.rmtree(downloads, ignore_errors = True)
        return {'return': 0, 'sha256': pinned}

    ############################################################
    def complete(self,
                 ctx: dict,
                 params: dict,
                 root: str,
    ):
        """
        An unpacked runtime with every package its line has now: those added after it was unpacked are unpacked
        beside the others (its marker records them), then the links of what they provide are made.
        -> {'return': 0, 'version': <line>} or an error that says what is missing
        """
        marker_path = os.path.join(root or '', MARKER)
        try:
            with open(marker_path, encoding = 'utf-8') as f:
                marker = json.load(f)
        except (OSError, ValueError) as e:
            return {'return': 1, 'error': f'the Intel GPU runtime in {root} has no readable {MARKER} ({e})'}
        version = str(marker.get('version'))

        missing = missing_packages(marker)
        if missing:
            c = ctx.get('control', {})
            if c.get('con', False):
                print ('')
                print (f'INFO: the Intel GPU runtime {version} in {root}: unpacking what its line has gained since '
                       f'({", ".join(p.rsplit("/", 1)[-1] for p in missing)})')
            entry = os.path.dirname(os.path.dirname(root))          # <entry>/content/<version>
            r = self._unpack(ctx, params, entry, root, [(p, sha) for p, sha in RELEASES[version] if p in missing])
            if r['return'] > 0:
                return {'return': 1, 'error': f'the Intel GPU runtime {version} lacks {", ".join(missing)}: {r.get("error")}'}
            marker['packages'] = list(marker.get('packages') or []) + missing
            marker.setdefault('sha256', {}).update(r['sha256'])
            with open(marker_path, 'w', encoding = 'utf-8') as f:
                json.dump(marker, f, indent = 2)

        lacking = provide(root, version)
        if lacking:
            return {'return': 1, 'error': f'the Intel GPU runtime {version} in {root} has no {", ".join(lacking)}', 'version': version}
        return {'return': 0, 'version': version}
