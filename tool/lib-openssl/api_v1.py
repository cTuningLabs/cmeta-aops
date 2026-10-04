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


def undefined_symbols(nm, archives):
    """The symbols that the objects of the archives refer to and do not define (nm -u), or None."""
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
                symbols.add(parts[-1])
    return symbols


def static_deps(symbols):
    """The entries of STATIC_DEPS that the undefined symbols need."""
    return [d for d in STATIC_DEPS
            if symbols & d.get('symbols', set()) or any(s.startswith(d.get('prefixes', ())) for s in symbols)]


def static_lib_names(deps):
    """The libraries of a static link of OpenSSL: libssl, libcrypto, what they need, libm."""
    names = ['ssl', 'crypto']
    for d in deps:
        names += [d['lib']] + d.get('needs', [])
    return names + ['m']


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
             elif uname == 'linux':
                 lib_names_static = [
                    'ssl', 
                    'crypto',
                    'z',
                    'm',
                    'zstd',
#                    'jitterentropy',
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
        """

        if result['return'] == 0 and not params.get('version_check', False):
            _with = params.get('with', {})

            if not _with.get('static', False):

                uname = ctx['tasks']['global']['host']['os']['uname']

                features = result['features']

                found_dynamic_libs = []

                if uname == 'windows':
                    path_dyn_lib = features['paths']['dynamic_lib']

                    if os.path.isdir(path_dyn_lib):
                        features['paths']['found_dynamic_lib_paths'] = [path_dyn_lib]

            elif ctx['tasks']['global']['host']['os']['uname'] == 'linux':
                r = self.static_link_deps(ctx, result['features'], params)
                if r['return'] > 0: return r

        return {'return':0}

    ############################################################
    def static_link_deps(self,
                         ctx: dict,
                         features: dict,
                         params: dict = {},
    ):
        """
        A static link on Linux: a distribution's libssl.a and libcrypto.a may refer to zlib, zstd and
        jitterentropy (Ubuntu 26.04: all three; Ubuntu 24.04: none). Only the libraries they need are
        linked (lib_names_static); a needed one that the system has no static archive of is built by
        its tool (lib-zlib, lib-zstd, lib-jitterentropy), whose lib folder setup-compile then adds.
        --with.static_deps=cmeta builds them even when the system has them. Without nm (binutils), or
        for an OpenSSL without static archives, the libraries stay as they were.
        """

        c = params.get('control') or ctx.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        paths = features.get('paths', {})
        lib_dirs = paths.get('libs_static') or paths.get('libs') or []
        archives = [os.path.join(d, a) for d in lib_dirs for a in ['libssl.a', 'libcrypto.a']
                    if os.path.isfile(os.path.join(d, a))]
        if not archives:
            return {'return': 0}

        _global = ctx['tasks']['global']
        compiler = _global.get('compiler-c') or _global.get('compiler-cpp') or {}
        bin_dir = compiler.get('features', {}).get('paths', {}).get('bin')
        nm = shutil.which('nm')
        if not nm and bin_dir:
            nm = next((os.path.join(bin_dir, n) for n in ['nm', 'llvm-nm'] if os.path.isfile(os.path.join(bin_dir, n))), None)
        symbols = undefined_symbols(nm, archives) if nm else None
        if symbols is None:
            return {'return': 0}

        deps = static_deps(symbols)
        features['lib_names_static'] = static_lib_names(deps)

        mode = str(params.get('with', {}).get('static_deps') or 'auto').lower()
        for d in deps:
            found = None if mode == 'cmeta' else find_static_lib(d['lib'], lib_dirs, compiler.get('path'))
            if found:
                if verbose:
                    print(f'{space}INFO: the static OpenSSL needs lib{d["lib"]}.a: {found}')
                continue
            if con:
                print(f'{space}INFO: the static OpenSSL needs lib{d["lib"]}.a' +
                      ('' if mode == 'cmeta' else ', which this system has not') + f': tool {d["tool"].split(",")[0]}')
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                                'ctx': ctx, 'name': d['tool'], 'install': params.get('install'),
                                'con': con, 'quiet': quiet, 'verbose': verbose})
            if self.cm.catch_error(r, fail16 = True):
                return r

        return {'return': 0}

