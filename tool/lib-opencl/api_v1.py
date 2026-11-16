"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup lib-opencl": what a C or C++ program needs to build against OpenCL for the opencl target
(task target--opencl finds the devices, tool/opencl the ICD loader the drivers register with):

- the Khronos OpenCL headers (CL/cl.h ...) of the pinned release of KhronosGroup/OpenCL-Headers, in
  install/include of the tool's cache entry, on every OS (a macOS program includes <OpenCL/opencl.h> of
  the SDK and finds the Khronos headers too);
- the library to link:
  - Windows: install/lib/OpenCL.lib, the import library of the OpenCL.dll that the GPU drivers install,
    made from the export list of the Khronos ICD loader of the same release (loader/windows/OpenCL.def)
    by the archiver of the program's C compiler (lib.exe of MSVC, llvm-lib of clang) - the loader is
    not built;
  - Linux: the ICD loader of the system (the one tool/opencl found, else libOpenCL.so or libOpenCL.so.1
    in the library folders; cx tool setup opencl --install installs it), by its path;
  - macOS: the OpenCL framework of the SDK (OpenCL.tbd, by its path; xcrun --show-sdk-path);
  - Android (android-gpu ...): a stub libOpenCL.so with every function of that export list, built once per
    target triple by the program's NDK compiler - only to link against: the device loads its own
    libOpenCL.so (the same soname) at run time, as CK's lib-opencl-1.2-stubs-android did.
setup-compile adds the include folder (-I) and the library (lib_names: a path every linker takes as it
is). iOS has no OpenCL.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import _sha256, default_version
from tool_c393ba5c6fa14f66.api.common_static_lib import download, safe_members, c_compiler

# GitHub's archives of the release tags (the projects publish no other release files)
HEADERS = {'url': 'https://github.com/KhronosGroup/OpenCL-Headers/archive/refs/tags/v{version}.tar.gz',
           'file': 'OpenCL-Headers-{version}.tar.gz',
           'dir': 'OpenCL-Headers-{version}',
           'sha256': {'2026.05.29': 'd9e6c48357de5002da11ce45de600e0c3ffe6ab4f628a3b9fe2b38603161658a'}}

LOADER = {'url': 'https://github.com/KhronosGroup/OpenCL-ICD-Loader/archive/refs/tags/v{version}.tar.gz',
          'file': 'OpenCL-ICD-Loader-{version}.tar.gz',
          'dir': 'OpenCL-ICD-Loader-{version}',
          'def': 'loader/windows/OpenCL.def',
          'sha256': {'2026.05.29': '48fd0c5181db7cd046f4f731d5955694892e10998d49d09ee0d997e7e04fd939'}}

# Where a Linux system keeps its ICD loader (the development name first: a link takes either)
LINUX_LOADER_NAMES = ['libOpenCL.so', 'libOpenCL.so.1']
LINUX_LOADER_DIRS = ['/usr/lib/x86_64-linux-gnu', '/usr/lib/aarch64-linux-gnu', '/usr/lib64', '/usr/lib',
                     '/usr/local/lib', '/usr/local/cuda/lib64', '/opt/rocm/lib']

# The machine of an import library, from host.os.uarch
MACHINES = {'amd64': 'x64', 'arm64': 'arm64', 'x86': 'x86'}


def extract(archive, prefix, dest):
    """The files of a tar archive under prefix ("dir/sub/"), into dest without the prefix: their number."""
    n = 0
    with tarfile.open(archive) as t:
        for m in safe_members(t):
            if not m.isfile() or not m.name.startswith(prefix):
                continue
            target = os.path.join(dest, *m.name[len(prefix):].split('/'))
            os.makedirs(os.path.dirname(target), exist_ok = True)
            with t.extractfile(m) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out)
            n += 1
    return n


def extract_file(archive, name, target):
    """One file of a tar archive (its full name) into target: True when it is there."""
    with tarfile.open(archive) as t:
        for m in safe_members(t):
            if m.isfile() and m.name == name:
                with t.extractfile(m) as src, open(target, 'wb') as out:
                    shutil.copyfileobj(src, out)
                return True
    return False


def import_lib_args(compiler, def_path, out_path, machine):
    """The command that makes OpenCL.lib from OpenCL.def with the archiver of the C compiler: (args, error)."""
    path = compiler.get('path') or ''
    tool_lib = ((compiler.get('features') or {}).get('paths') or {}).get('tool_lib') or ''
    if re.split(r'[\\/]', tool_lib)[-1].lower() == 'lib.exe':      # a Windows path, on any OS
        archiver = tool_lib
    else:
        archiver = os.path.join(os.path.dirname(path), 'llvm-lib.exe')
        if not os.path.isfile(archiver):
            return None, f'no lib.exe or llvm-lib.exe next to the C compiler "{path}" to make OpenCL.lib'
    return [archiver, '/nologo', f'/def:{def_path}', '/name:OpenCL.dll', f'/machine:{machine}', f'/out:{out_path}'], None


def stub_source(def_text):
    """The C source of a stub libOpenCL.so from the loader's export list (OpenCL.def): (source, number of functions)."""
    names = []
    for line in def_text.splitlines():
        words = line.split(';', 1)[0].split()
        if words and re.fullmatch(r'cl[A-Za-z0-9_]+', words[0]) and words[0] not in names:
            names.append(words[0])
    lines = ['/* A stub of libOpenCL.so to link against (cMeta tool/lib-opencl, from the export list of the Khronos',
             '   ICD loader): the device loads its own libOpenCL.so, of the same soname, at run time */']
    lines += [f'void {n}(void) {{}}' for n in names]
    return '\n'.join(lines) + '\n', len(names)


def linux_loader(opencl_path = None, dirs = LINUX_LOADER_DIRS):
    """The ICD loader to link on Linux: the one tool/opencl found, else the first in the library folders."""
    if opencl_path and os.path.isfile(opencl_path) and os.path.basename(opencl_path).startswith('libOpenCL.so'):
        return opencl_path
    for name in LINUX_LOADER_NAMES:
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None


def macos_framework():
    """The OpenCL framework of the macOS SDK to link (OpenCL.tbd), or None."""
    sdks = []
    try:
        p = subprocess.run(['xcrun', '--show-sdk-path'], capture_output = True, text = True, timeout = 60,
                           stdin = subprocess.DEVNULL)
        if p.returncode == 0 and p.stdout.strip():
            sdks.append(p.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    sdks += ['/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk',
             '/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk']
    for sdk in sdks:
        tbd = os.path.join(sdk, 'System', 'Library', 'Frameworks', 'OpenCL.framework', 'OpenCL.tbd')
        if os.path.isfile(tbd):
            return tbd
    return None


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _fetch(self, ctx, params, spec, version, sha256, space, con):
        """A release archive of the spec, checked against its SHA-256: {'path'} or an error."""
        url = spec['url'].format(version = version)
        filename = spec['file'].format(version = version)
        if con:
            print(f'{space}INFO: downloading {url} ...')
        r = download(self, ctx, params, url, 'download', filename)
        if r['return'] > 0:
            return self.cm.error(f'could not download {url}: {r.get("error")}')
        digest = _sha256(r['path'])
        if digest != sha256:
            os.remove(r['path'])
            return self.cm.error(f'SHA-256 mismatch for {filename}: expected {sha256}, got {digest}')
        return {'return': 0, 'path': r['path'], 'url': url}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The headers (every OS) and OpenCL.lib (Windows) into the tool's cache entry (install/).
        """
        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        c = params.get('control', {})
        con, verbose = c.get('con', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''
        _with = params.get('with', {})

        version = params.get('version_simple') or default_version(self)
        if not version:
            return self.cm.error('lib-opencl pins no default_version in its _desc.yaml: give --version=<YYYY.MM.DD>')

        sha_headers = (_with.get('sha256') or HEADERS['sha256'].get(version) or '').lower()
        if not sha_headers:
            return self.cm.error(f'no SHA-256 is pinned for the OpenCL headers {version}: give --with.sha256=<SHA-256 '
                                 f'of {HEADERS["file"].format(version = version)}> (pinned: {", ".join(sorted(HEADERS["sha256"]))})')

        root = os.getcwd()
        install = os.path.join(root, 'install')
        shutil.rmtree(install, ignore_errors = True)
        include = os.path.join(install, 'include')
        os.makedirs(include)

        # The headers: CL/*.h and the licence
        r = self._fetch(ctx, params, HEADERS, version, sha_headers, space, con)
        if r['return'] > 0:
            return r
        top = HEADERS['dir'].format(version = version) + '/'
        if not extract(r['path'], top + 'CL/', os.path.join(include, 'CL')):
            return self.cm.error(f'no CL/ folder in {r["path"]}')
        extract_file(r['path'], top + 'LICENSE', os.path.join(install, 'LICENSE.OpenCL-Headers'))
        source = {'version': version,
                  'headers': {'url': r['url'], 'sha256': sha_headers}}

        # The export list of the ICD loader (every OS: Windows makes OpenCL.lib of it, an Android target a stub)
        sha_loader = (_with.get('sha256_loader') or LOADER['sha256'].get(version) or '').lower()
        if not sha_loader:
            return self.cm.error(f'no SHA-256 is pinned for the OpenCL ICD loader {version}: give '
                                 f'--with.sha256_loader=<SHA-256 of {LOADER["file"].format(version = version)}>')
        r = self._fetch(ctx, params, LOADER, version, sha_loader, space, con)
        if r['return'] > 0:
            return r
        lib = os.path.join(install, 'lib')
        os.makedirs(lib)
        top = LOADER['dir'].format(version = version) + '/'
        def_path = os.path.join(lib, 'OpenCL.def')
        if not extract_file(r['path'], top + LOADER['def'], def_path):
            return self.cm.error(f'no {LOADER["def"]} in {r["path"]}')
        extract_file(r['path'], top + 'LICENSE', os.path.join(install, 'LICENSE.OpenCL-ICD-Loader'))
        source['loader'] = {'url': r['url'], 'sha256': sha_loader, 'def': LOADER['def']}

        # Windows: the import library of OpenCL.dll from that export list
        if uname == 'windows':
            rc = c_compiler(self, ctx, params)
            if rc['return'] > 0:
                return rc
            uarch = (_global['host']['os'].get('uarch') or 'amd64').lower()
            machine = MACHINES.get(uarch, 'x64')
            out_path = os.path.join(lib, 'OpenCL.lib')
            args, error = import_lib_args(rc['compiler'], def_path, out_path, machine)
            if error:
                return self.cm.error(error)
            if verbose:
                print(f'{space}RUN: ' + ' '.join(args))
            p = subprocess.run(args, capture_output = True, text = True, cwd = lib, stdin = subprocess.DEVNULL)
            if p.returncode != 0 or not os.path.isfile(out_path):
                return self.cm.error(f'making OpenCL.lib failed:\n{" ".join(args)}\n{(p.stderr or p.stdout).strip()[-2000:]}')
            source['import_lib'] = {'archiver': args[0], 'machine': machine}

        with open(os.path.join(install, '_source.json'), 'w', encoding = 'utf-8') as f:
            json.dump(source, f, indent = 2)
        shutil.rmtree(os.path.join(root, 'download'), ignore_errors = True)

        return {'return': 0, 'install_cmd': None, 'found_path': os.path.join(include, 'CL', 'cl.h')}

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        The release, include folder and (Windows) OpenCL.lib of an installation (install/include/CL/cl.h).
        """
        found = {}
        for path in paths:
            include = os.path.dirname(os.path.dirname(path))
            install = os.path.dirname(include)
            try:
                with open(os.path.join(install, '_source.json'), encoding = 'utf-8') as f:
                    source = json.load(f)
            except (OSError, ValueError):
                continue
            features = {'paths': {'root': install, 'qroot': self.cm.q(install),
                                  'include': include, 'qinclude': self.cm.q(include), 'includes': [include]}}
            lib = os.path.join(install, 'lib', 'OpenCL.lib')
            if os.path.isfile(lib):
                features['paths'].update({'lib': os.path.dirname(lib), 'qlib': self.cm.q(os.path.dirname(lib)),
                                          'opencl_lib': lib})
                features['lib_names'] = [lib]
            found[path] = {'output': source.get('version') or 'default', 'features': features}
        return {'return': 0, 'found_paths_with_versions': found}

    ############################################################
    def _android_stub(self, ctx, install):
        """
        A stub libOpenCL.so for the Android target of the program (its NDK compiler and target triple), built
        once into install/android/<triple>/ from the loader's export list: {'path'} or an error.
        """
        _global = ctx['tasks']['global']
        compiler = (_global.get('compiler-c') or {}).get('path')
        target_arch = ((_global.get('android-ndk-clang') or {}).get('features') or {}).get('target_arch') or {}
        triple, flags = target_arch.get('clang_target'), target_arch.get('flags') or ''
        if not compiler or not triple:
            return self.cm.error('lib-opencl: an Android target needs the NDK C compiler of the program '
                                 '(global compiler-c and android-ndk-clang) to build its stub libOpenCL.so')

        out_dir = os.path.join(install, 'android', triple)
        lib = os.path.join(out_dir, 'libOpenCL.so')
        if os.path.isfile(lib):
            return {'return': 0, 'path': lib}

        def_path = os.path.join(install, 'lib', 'OpenCL.def')
        if not os.path.isfile(def_path):
            return self.cm.error(f'lib-opencl: no {def_path} (an installation older than the Android stub): '
                                 'cx tool setup lib-opencl --new')
        with open(def_path, encoding = 'utf-8', errors = 'replace') as f:
            text, n = stub_source(f.read())
        if not n:
            return self.cm.error(f'lib-opencl: no OpenCL function in {def_path}')

        os.makedirs(out_dir, exist_ok = True)
        src = os.path.join(out_dir, 'opencl_stub.c')
        with open(src, 'w', encoding = 'utf-8') as f:
            f.write(text)
        args = [compiler] + shlex.split(flags) + ['-shared', '-fPIC', '-Wl,-soname,libOpenCL.so', '-o', lib, src]
        p = subprocess.run(args, capture_output = True, text = True, cwd = out_dir, stdin = subprocess.DEVNULL)
        if p.returncode != 0 or not os.path.isfile(lib):
            return self.cm.error(f'building the stub libOpenCL.so failed:\n{" ".join(args)}\n'
                                 f'{(p.stderr or p.stdout).strip()[-2000:]}')
        return {'return': 0, 'path': lib}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        The library to link on Linux and macOS, found on this machine at each use (not cached), and the stub
        of an Android target (built once per target triple into the tool's cache entry).
        """
        if result.get('return', 0) > 0 or params.get('version_check', False):
            return {'return': 0}

        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        compute = (_global.get('target') or {}).get('compute') or []
        features = result.setdefault('features', {})
        paths = features.setdefault('paths', {})

        if any(str(c).startswith('ios-') for c in compute):
            return self.cm.error('lib-opencl: iOS has no OpenCL (its GPU API is Metal)')

        if any(str(c).startswith('android-') for c in compute):
            r = self._android_stub(ctx, paths.get('root') or '')
            if r['return'] > 0:
                return r
            paths['opencl_lib'] = r['path']
            features['lib_names'] = [r['path']]
            return {'return': 0}

        if uname == 'linux':
            loader = linux_loader((_global.get('opencl') or {}).get('path'))
            if not loader:
                return self.cm.error('lib-opencl: no OpenCL ICD loader (libOpenCL.so) on this system: '
                                     'cx tool setup opencl --install')
            paths['opencl_lib'] = loader
            features['lib_names'] = [loader]
        elif uname == 'darwin':
            tbd = macos_framework()
            if not tbd:
                return self.cm.error('lib-opencl: no OpenCL framework in the macOS SDK (OpenCL.tbd): '
                                     'install the Command Line Tools (xcode-select --install)')
            paths['opencl_lib'] = tbd
            features['lib_names'] = [tbd]

        return {'return': 0}
