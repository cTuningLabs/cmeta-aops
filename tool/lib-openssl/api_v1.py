"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# What the static libssl.a and libcrypto.a of a Linux distribution may refer to (pkg-config --static
# --libs libcrypto lists them), recognized by the symbols they leave undefined, with the tool that
# builds the library when the system has no static archive of it, and what that library needs itself
STATIC_DEPS = [
    {'lib': 'jitterentropy', 'tool': 'lib-jitterentropy,0cb5070cea894819', 'prefixes': ('jent_',),
     'needs': ['pthread']},
    {'lib': 'z', 'tool': 'lib-zlib,c46f457c9da347a7',
     'symbols': {'deflate', 'deflateInit_', 'deflateInit2_', 'deflateEnd', 'inflate', 'inflateInit_',
                 'inflateInit2_', 'inflateEnd', 'compress', 'compress2', 'uncompress', 'zlibVersion'}},
    {'lib': 'zstd', 'tool': 'lib-zstd,cfb5787b19004f19', 'prefixes': ('ZSTD_',)},
]

# Where a linker finds static archives when no compiler can tell (-print-file-name)
SYSTEM_LIB_DIRS = ['/usr/lib/*-linux-gnu', '/usr/lib64', '/usr/lib', '/usr/local/lib', '/lib/*-linux-gnu']

# The static OpenSSL: the archives of Linux and macOS, the libraries of the MT folder on Windows
STATIC_ARCHIVES = ['libssl.a', 'libcrypto.a']
WINDOWS_STATIC_LIBS = ['libssl_static.lib', 'libcrypto_static.lib']

# What gives a Linux system the static archives, by the ID (or an ID_LIKE) of /etc/os-release. Checked
# 2026-10: Debian 12/13 and Ubuntu ship them in libssl-dev, Alpine in openssl-libs-static; no package of
# Fedora 44 or Rocky Linux 9 (BaseOS, AppStream, CRB) provides libcrypto.a
STATIC_PACKAGES = {
    'debian': 'sudo apt-get install libssl-dev  (the development package ships the archives)',
    'ubuntu': 'sudo apt-get install libssl-dev  (the development package ships the archives)',
    'alpine': 'apk add openssl-libs-static',
    'fedora': 'Fedora packages no static OpenSSL (no package provides libcrypto.a): build it from source, below',
    'rhel': 'RHEL-like systems package no static OpenSSL (not in BaseOS, AppStream or CRB): build it from source, below',
    'arch': 'Arch Linux packages no static OpenSSL: build it from source, below',
    'suse': 'openSUSE packages no static OpenSSL: build it from source, below',
    'opensuse': 'openSUSE packages no static OpenSSL: build it from source, below',
}


def is_true(value):
    """A boolean from a with.* value: None, '' and False are False; strings are read."""
    if value in (None, '', False):
        return False
    if isinstance(value, str):
        return value.strip().lower() in ('true', 'yes', '1', 'on')
    return bool(value)


def undefined_symbols(nm, archives, darwin = False):
    """
    The symbols that the objects of the archives refer to and do not define (nm -u), or None. GNU nm
    prints them with a "U" column; macOS nm prints bare names, with the leading underscore of Mach-O
    C symbols, which is stripped so that the symbol lists of STATIC_DEPS apply.
    """
    symbols = set()
    for archive in archives:
        try:
            r = subprocess.run([nm, '-u', archive], capture_output = True, text = True)
        except OSError:
            return None
        if r.returncode != 0 and not r.stdout:
            return None
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-2] == 'U':
                symbol = parts[-1]
            elif darwin and len(parts) == 1 and not line.endswith(':'):
                symbol = parts[0]
            else:
                continue
            if darwin and symbol.startswith('_'):
                symbol = symbol[1:]
            symbols.add(symbol)
    return symbols


def static_archives(lib_dirs):
    """The paths of libssl.a and libcrypto.a in the first folder that has both, else []."""
    for d in lib_dirs:
        paths = [os.path.join(d, a) for a in STATIC_ARCHIVES]
        if all(os.path.isfile(p) for p in paths):
            return paths
    return []


def windows_static_folder(paths):
    """
    Windows: the MT folder (static C run time) of OpenSSL's lib\\VC\\<arch> with both static libraries,
    and that lib folder, as (folder or None, root). The detected lib folder is MD (or the root when
    the installation has no run-time folders).
    """
    lib = paths.get('lib') or ''
    root = os.path.dirname(lib) if os.path.basename(lib) in ('MD', 'MDd', 'MT', 'MTd') else lib
    folder = os.path.join(root, 'MT')
    if root and all(os.path.isfile(os.path.join(folder, l)) for l in WINDOWS_STATIC_LIBS):
        return folder, root
    return None, root


def no_static_archives(uname, os_id = None, id_like = None, where = ''):
    """
    Why a static build stops when the OpenSSL found has no static libraries, and what gives them on
    this system. A static build never falls back to the shared library: it must be what it says.
    """
    where = f' ({where})' if where else ''
    if uname == 'windows':
        return (f'a static build needs OpenSSL\'s static libraries {" and ".join(WINDOWS_STATIC_LIBS)} in lib\\VC\\<arch>\\MT '
                f'of the OpenSSL installation{where}, and this one has none: the OpenSSL developer package has them '
                '("winget install OpenSSL -e --source winget", id ShiningLight.OpenSSL.Dev; the "Light" packages ship no '
                'libraries), then "cx tool setup lib-openssl --update"; or build the program without --compile.static')
    head = f'a static build needs OpenSSL\'s static archives {" and ".join(STATIC_ARCHIVES)}, and the OpenSSL found{where} has none'
    if uname == 'darwin':
        return (head + ' (macOS ships no OpenSSL archives of its own): Homebrew\'s openssl@3 has them ("brew install openssl@3", '
                'then "cx tool setup lib-openssl --update"); or build the program without --compile.static')
    lines = [head + ':']
    key = next((k for k in [os_id or ''] + (id_like or '').split() if k in STATIC_PACKAGES), None)
    if key:
        lines.append(f'  this system ({os_id}): {STATIC_PACKAGES[key]}')
    lines += ['  Debian, Ubuntu: sudo apt-get install libssl-dev; Alpine: apk add openssl-libs-static;',
              '  Fedora, RHEL-likes, Arch Linux and openSUSE package no static OpenSSL',
              '  or build OpenSSL from source ("./Configure no-shared --prefix=<prefix>") and register it:',
              '    cx tool setup lib-openssl --tool_path=<prefix>/include/openssl/opensslv.h',
              '  or build the program without --compile.static']
    return '\n'.join(lines)


def static_deps(symbols):
    """The entries of STATIC_DEPS that the undefined symbols need."""
    return [d for d in STATIC_DEPS
            if symbols & d.get('symbols', set()) or any(s.startswith(d.get('prefixes', ())) for s in symbols)]


def static_lib_names(archives, deps, uname = 'linux'):
    """
    The libraries of a static link of OpenSSL, in link order: libssl.a and libcrypto.a by their paths
    (named, -lssl -lcrypto, a link without -static - nvcc's host link - takes the shared library
    instead), then what they need, each by the path of its static archive ("path") with what it
    needs itself, then the system libraries: libpthread, libdl and libm are part of libc on current
    systems and named for the older ones; macOS has them in libSystem.
    """
    names = list(archives)
    for d in deps:
        if d.get('path') and d['path'] not in names:
            names.append(d['path'])
        names += [n for n in d.get('needs', []) if n not in names]
    system = ['pthread', 'dl', 'm'] if uname == 'linux' else ['m']
    return names + [s for s in system if s not in names]


def find_static_lib(lib, lib_dirs, compiler = None):
    """The static archive lib<lib>.a in the folders or where the compiler's linker finds it, or None."""
    name = f'lib{lib}.a'
    for d in lib_dirs:
        if os.path.isfile(os.path.join(d, name)):
            return os.path.join(d, name)
    if compiler:
        try:
            path = subprocess.run([compiler, f'-print-file-name={name}'], capture_output = True, text = True).stdout.strip()
        except OSError:
            path = ''
        return path if os.path.isabs(path) and os.path.isfile(path) else None
    for pattern in SYSTEM_LIB_DIRS:
        for d in sorted(glob.glob(pattern)):
            if os.path.isfile(os.path.join(d, name)):
                return os.path.join(d, name)
    return None


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

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL openssl api_v1 detect_versions")

        found_paths_with_versions =  {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        uarch = ctx['tasks']['global']['host']['os']['uarch']
        if uarch == 'amd64':
            uarch = 'x64'

        for path in paths:
             r = self.cm.utils.files.read_file(path)
             if self.cm.catch_error(r): return r

             s = r['data']

             version = None
             try:
                 openssl_version_major = int(re.search(r"OPENSSL_VERSION_MAJOR\s+(\d+)", s).group(1))
                 openssl_version_minor = int(re.search(r"OPENSSL_VERSION_MINOR\s+(\d+)", s).group(1))
                 openssl_version_patch = int(re.search(r"OPENSSL_VERSION_PATCH\s+(\d+)", s).group(1))
                 version = str(openssl_version_major) + '.' + str(openssl_version_minor) + '.' + str(openssl_version_patch)
             except Exception as e:
                 pass

             if not version:
                 continue

             path_include = os.path.dirname(os.path.dirname(path))

             path_includes = [path_include]

             path_home = os.path.dirname(path_include)

             path_bin = os.path.join(path_home, 'bin')

             path_lib = os.path.join(path_home, 'lib')

             if uname == 'windows':
                 path_lib = os.path.join(path_lib, 'VC', uarch)
             else:
                 found_lib = False

                 for x in ['lib64', 'lib']:
                     path_lib = os.path.join(path_home, x)
                     if os.path.isdir(path_lib):
                         matches = list(Path(path_lib).rglob("libssl.a"))
                         if matches:
                             found_lib = True
                             break

                         matches = list(Path(path_lib).rglob("libssl.so"))
                         if matches:
                             found_lib = True
                             break

                 if not found_lib:
                     continue

                 path_lib = os.path.dirname(matches[0])

             _path_lib = path_lib

             _libs = {}

             if os.path.isdir(_path_lib):
                 if uname == 'windows':
                     path_lib_dynamic = os.path.join(_path_lib, 'MD')
                     if os.path.isdir(path_lib_dynamic):
                         path_lib = path_lib_dynamic # Default lib

                     path_lib_dynamic_debug = os.path.join(_path_lib, 'MDd')
                     if os.path.isdir(path_lib_dynamic_debug):
                         _libs['libs_debug'] = [path_lib_dynamic_debug]

                     path_lib_static = os.path.join(_path_lib, 'MT')
                     if os.path.isdir(path_lib_static):
                         _libs['libs_static'] = [path_lib_static]

                     path_lib_static_debug = os.path.join(_path_lib, 'MTd')
                     if os.path.isdir(path_lib_static_debug):
                         _libs['libs_static_debug'] = [path_lib_static_debug]

             # Default libs
             path_libs = [path_lib]
             qpath_libs = [self.cm.q(path_lib)]

             lib_names = [
               'ssl',
               'crypto'
             ]

             # Windows: the static libraries by name (the linker takes exactly the file named).
             # Linux and macOS: finish_dynamic_result names the archives by their paths.
             lib_names_static = []

             if uname == 'windows':
                 lib_names_static = [
                    'ssl_static',
                    'crypto_static',
                    '$ws2_32',
                    '$crypt32',
                    '$advapi32',
                    '$user32',
                 ]

             paths = {
                 'root': path_home,
                 'qroot': self.cm.q(path_home),
             }

             # FGG: bin is only needed on Windows for DLLs ...
             if uname == 'windows' and os.path.isdir(path_bin):
                 paths['dynamic_lib'] = path_bin
                 paths['qdynamic_lib'] = self.cm.q(path_bin)
                 paths['dynamic_libs'] = [path_bin]

             if os.path.isdir(path_include):
                 paths['include'] = path_include
                 paths['qinclude'] = self.cm.q(path_include)

             if path_includes:
                 paths['includes'] = path_includes

             if os.path.isdir(path_lib):
                 paths['lib'] = path_lib
                 paths['qlib'] = self.cm.q(path_lib)

             if path_libs:
                 paths['libs'] = path_libs

             if _libs:
                 paths.update(_libs)

             features = {
               'paths': paths,
               'lib_names': lib_names,
             }

             if lib_names_static:
                 features['lib_names_static'] = lib_names_static

             found_paths_with_versions[path] = {'output':version, 'features':features}

        return {'return':0, 'found_paths_with_versions':found_paths_with_versions}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        Runs for a fresh and for a reused result: the static libraries are checked and named from the
        installation as it is now. A request with with.static that cannot have them fails here; a
        request without it records why (features.static_unavailable), and setup-compile stops a
        static build on that.
        """

        if result['return'] != 0 or params.get('version_check', False):
            return {'return': 0}

        features = result['features']
        uname = ctx['tasks']['global']['host']['os']['uname']
        static = is_true((params.get('with') or {}).get('static'))

        if uname == 'windows':
            return self.windows_libraries(ctx, features, static)

        return self.static_libraries(ctx, features, params, static)

    ############################################################
    def windows_libraries(self,
                          ctx: dict,
                          features: dict,
                          static: bool = False,
    ):
        """
        Windows: the MT folder with libssl_static.lib and libcrypto_static.lib serves a static build
        (its libraries are named, so the linker takes exactly them); without it a static build stops.
        A dynamic build gets the DLL folder on its run-time path.
        """

        paths = features.setdefault('paths', {})
        folder, root = windows_static_folder(paths)
        if folder:
            paths['libs_static'] = [folder]
            features.pop('static_unavailable', None)
        else:
            paths.pop('libs_static', None)
            features['static_unavailable'] = no_static_archives('windows', where = root)
            if static:
                return self.cm.error('lib-openssl: ' + features['static_unavailable'])

        if not static:
            path_dyn_lib = paths.get('dynamic_lib')
            if path_dyn_lib and os.path.isdir(path_dyn_lib):
                paths['found_dynamic_lib_paths'] = [path_dyn_lib]

        return {'return': 0}

    ############################################################
    def static_libraries(self,
                         ctx: dict,
                         features: dict,
                         params: dict = {},
                         static: bool = False,
    ):
        """
        Linux and macOS: a static build links libssl.a and libcrypto.a by their paths (lib_names_static),
        never the shared library: named, a link without -static (nvcc's host link) would take
        libcrypto.so. Without the archives a request with with.static fails, with the package that
        gives them on this system; a request without it records the reason for setup-compile and
        names, for a static build that did not ask this tool for one, the archives and the system's
        static archives of what they may need (no tool is built for a dynamic request).
        """

        host = ctx['tasks']['global'].get('host', {})
        uname = host.get('os', {}).get('uname')
        paths = features.setdefault('paths', {})
        lib_dirs = paths.get('libs') or []

        archives = static_archives(lib_dirs)
        if not archives:
            os_extra = host.get('os_extra', {})
            features['static_unavailable'] = no_static_archives(uname, os_extra.get('id'), os_extra.get('id_like'), ', '.join(lib_dirs))
            features.pop('lib_names_static', None)
            if static:
                return self.cm.error('lib-openssl: ' + features['static_unavailable'])
            return {'return': 0}

        features.pop('static_unavailable', None)
        paths.pop('libs_static', None)       # entries made before: the archives' copies in a "static" folder

        if not static:
            deps = [dict(d, path = find_static_lib(d['lib'], lib_dirs)) for d in STATIC_DEPS]
            features['lib_names_static'] = static_lib_names(archives, [d for d in deps if d['path']], uname)
            return {'return': 0}

        return self.static_link_deps(ctx, features, params, archives, uname)

    ############################################################
    def static_link_deps(self,
                         ctx: dict,
                         features: dict,
                         params: dict,
                         archives: list,
                         uname: str,
    ):
        """
        A static link on Linux or macOS: a distribution's (or Homebrew's) libssl.a and libcrypto.a
        may refer to zlib, zstd and jitterentropy (Ubuntu 26.04: all three; Ubuntu 24.04, Debian:
        none; Homebrew: zlib). Only the libraries they need are linked, each by the path of its static
        archive: the system's when the compiler's linker finds one, else the one its tool builds
        (lib-zlib, lib-zstd, lib-jitterentropy). --with.static_deps=cmeta builds them even when the
        system has them. Without nm (binutils, Xcode's command line tools, llvm-nm next to the
        compiler) the needs cannot be read: the system's archives of the three are linked, if any.
        """

        c = params.get('control') or ctx.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        lib_dirs = features.get('paths', {}).get('libs') or []
        _global = ctx['tasks']['global']
        compiler = _global.get('compiler-c') or _global.get('compiler-cpp') or {}
        bin_dir = compiler.get('features', {}).get('paths', {}).get('bin')
        nm = shutil.which('nm')
        if not nm and bin_dir:
            nm = next((os.path.join(bin_dir, n) for n in ['nm', 'llvm-nm'] if os.path.isfile(os.path.join(bin_dir, n))), None)
        symbols = undefined_symbols(nm, archives, darwin = (uname == 'darwin')) if nm else None

        if symbols is None:
            if con:
                print(f'{space}WARNING: no nm to read what the static OpenSSL needs (binutils, or llvm-nm next to the '
                      f'compiler): the system\'s static archives of zlib, zstd and jitterentropy are linked, if any')
            deps = [dict(d, path = find_static_lib(d['lib'], lib_dirs, compiler.get('path'))) for d in STATIC_DEPS]
            features['lib_names_static'] = static_lib_names(archives, [d for d in deps if d['path']], uname)
            return {'return': 0}

        deps = [dict(d) for d in static_deps(symbols)]
        mode = str(params.get('with', {}).get('static_deps') or 'auto').lower()
        for d in deps:
            found = None if mode == 'cmeta' else find_static_lib(d['lib'], lib_dirs, compiler.get('path'))
            if found:
                d['path'] = found
                if verbose:
                    print(f'{space}INFO: the static OpenSSL needs lib{d["lib"]}.a: {found}')
                continue
            tool = d['tool'].split(',')[0]
            if con:
                print(f'{space}INFO: the static OpenSSL needs lib{d["lib"]}.a' +
                      ('' if mode == 'cmeta' else ', which this system has not') + f': tool {tool}')
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                                'ctx': ctx, 'name': d['tool'], 'install': params.get('install'),
                                'con': con, 'quiet': quiet, 'verbose': verbose})
            if self.cm.catch_error(r, fail16 = True):
                return r
            tool_features = r.get('features') or _global.get(tool, {}).get('features') or {}
            d['path'] = tool_features.get('static_lib')
            if not d['path']:
                return self.cm.error(f'lib-openssl: {tool} reported no static archive for lib{d["lib"]}.a')

        features['lib_names_static'] = static_lib_names(archives, deps, uname)

        return {'return': 0}
