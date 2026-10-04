"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

LLVM's OpenMP runtime (libomp) for clang: detected next to the LLVM or Homebrew libomp (Linux, macOS,
Windows), its folder put on the run-time library path of the program, and, for a static build
(--with.static) on Linux and macOS, its static archive in the "static" folder of the same cache entry: a libomp.a shipped next to the detected library (Homebrew's libomp), else one built from
the pinned OpenMP source release with cmake and ninja. The identity of the cache entry does not change:
one entry serves dynamic and static builds, as the entries of the libraries cMeta builds itself do.
"""

import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256

# The OpenMP runtime source: the last LLVM release line with a standalone tarball (22.x publishes the
# whole llvm-project only); the runtime's ABI is stable, so this libomp.a serves any recent clang. The
# cmake tarball holds the modules that a standalone runtime build needs next to the sources ("../cmake").
OPENMP_SRC = {
    'version': '21.1.8',
    'url': 'https://github.com/llvm/llvm-project/releases/download/llvmorg-{version}/{file}',
    'files': {
        'openmp-{version}.src.tar.xz': '856b023748b41ac7b2c83fd8e9f765ff48a4df2fe6777d2811ef7c7ed8f2f977',
        'cmake-{version}.src.tar.xz': '85735f20fd8c81ecb0a09abb0c267018475420e93b65050cc5b7634eab744de9',
    },
}
CMAKE_TOOL = 'cmake,e26c11ebb3dd40ca'
NINJA_TOOL = 'ninja,a3df3c45e9b04830'


def is_true(value):
    """A boolean from a with.* value: None, '' and False are False; strings are read."""
    if value in (None, '', False):
        return False
    if isinstance(value, str):
        return value.strip().lower() in ('true', 'yes', '1', 'on')
    return bool(value)


def cmake_args(cmake, ninja, src, build, cc, cxx):
    """The configure command of a static libomp (no shared library, no offloading, no tools)."""
    return [cmake, '-S', src, '-B', build, '-G', 'Ninja', f'-DCMAKE_MAKE_PROGRAM={ninja}',
            '-DCMAKE_BUILD_TYPE=Release', f'-DCMAKE_C_COMPILER={cc}', f'-DCMAKE_CXX_COMPILER={cxx}',
            '-DLIBOMP_ENABLE_SHARED=OFF', '-DOPENMP_ENABLE_LIBOMPTARGET=OFF', '-DOPENMP_ENABLE_OMPT_TOOLS=OFF',
            '-DLIBOMP_OMPD_SUPPORT=OFF', '-DLIBOMP_INSTALL_ALIASES=OFF', '-DLIBOMP_FORTRAN_MODULES=OFF',
            '-DCMAKE_POSITION_INDEPENDENT_CODE=ON']


def safe_members(t):
    for m in t.getmembers():
        if m.name.startswith('/') or '..' in Path(m.name).parts or m.issym() or m.islnk():
            continue
        yield m


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

        found_paths_with_versions =  {}

        uname = ctx['tasks']['global']['host']['os']['uname']

        for path in paths:
             path_lib = os.path.dirname(path)
             path_home = os.path.dirname(path_lib)

             paths = {}

             paths['dynamic_lib'] = path_lib
             paths['qdynamic_lib'] = self.cm.q(path_lib)
             paths['dynamic_libs'] = [path_lib]

             paths['lib'] = path_lib
             paths['qlib'] = self.cm.q(path_lib)
             paths['libs'] = [path_lib]

             paths['home'] = path_home
             paths['qhome'] = self.cm.q(path_home)

             lib_names = []

             if uname == 'darwin':
                 path_include = os.path.join(path_home, 'include')

                 if os.path.isdir(path_include):
                     paths['include'] = path_include
                     paths['qinclude'] = self.cm.q(path_include)

                     paths['includes'] = [path_include]

                 lib_names = [
                   'omp',
                 ]

             features = {
               'paths': paths,
             }

             if lib_names:
                 features['lib_names'] = lib_names

             version = 'default'

             found_paths_with_versions[path] = {'output':version, 'features':features}

        return {'return':0, 'found_paths_with_versions':found_paths_with_versions}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        A dynamic build gets the folder of the detected libomp as a run-time library path; a static
        build gets libomp.a (static_library) as the only library folder and name, so the linker takes
        the archive (clang's -fopenmp adds -lomp; Apple's ld takes a dylib over an archive in the same
        folder, which is why the archive gets a folder of its own).
        """

        if result['return'] == 0 and not params.get('version_check', False):
            _with = params.get('with', {})
            features = result['features']

            # Windows has no static OpenMP runtime (see the README): a static build keeps libomp.dll,
            # whose folder the program needs on its run-time path like a dynamic build
            if not is_true(_with.get('static')) or ctx['tasks']['global']['host']['os']['uname'] == 'windows':
                path_dyn_lib = features['paths']['dynamic_lib']

                if os.path.isdir(path_dyn_lib):
                    features['paths']['found_dynamic_lib_paths'] = [path_dyn_lib]

            else:
                r = self.static_library(ctx, result, params)
                if r['return'] > 0: return r

                features['paths']['libs_static'] = [r['path']]
                features['lib_names_static'] = ['omp']
                features['paths'].pop('found_dynamic_lib_paths', None)

        return {'return':0}

    ############################################################
    def static_library(self,
                       ctx: dict,
                       result: dict,
                       params: dict,
    ):
        """
        The folder "static" of this cache entry with libomp.a in it: an archive shipped next to the
        detected library (Homebrew's libomp), else one built from the pinned OpenMP source release
        (OPENMP_SRC) with cmake and ninja and the C and C++ compilers of the current build. Returns
        {'return': 0, 'path': <folder>}, or a clear error when neither is possible.
        """

        c = params.get('control') or ctx.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''
        _global = ctx['tasks']['global']

        root = result.get('path_cmeta_cache')
        if not root or not os.path.isdir(root):
            return self.cm.error('lib-openmp: a static build needs libomp.a in the cache entry of the library, '
                                 'and this result has no cache entry')
        static_dir = os.path.join(root, 'static')
        target = os.path.join(static_dir, 'libomp.a')
        if os.path.isfile(target):
            return {'return': 0, 'path': static_dir}

        # 1. An archive next to the detected library
        lib_dir = result.get('features', {}).get('paths', {}).get('dynamic_lib') or ''
        shipped = os.path.join(lib_dir, 'libomp.a')
        if os.path.isfile(shipped):
            os.makedirs(static_dir, exist_ok = True)
            shutil.copy2(shipped, target)
            if con:
                print(f'{space}INFO: lib-openmp: static archive {shipped} -> {target}')
            return {'return': 0, 'path': static_dir}

        # 2. Built from the pinned source release
        cc = (_global.get('compiler-c') or {}).get('path')
        cxx = (_global.get('compiler-cpp') or {}).get('path')
        if cc and not cxx:
            cxx = os.path.join(os.path.dirname(cc), os.path.basename(cc).replace('clang', 'clang++').replace('gcc', 'g++'))
        if cxx and not cc:
            cc = os.path.join(os.path.dirname(cxx), os.path.basename(cxx).replace('clang++', 'clang').replace('g++', 'gcc'))
        if not (cc and cxx and os.path.isfile(cc) and os.path.isfile(cxx)):
            return self.cm.error('lib-openmp: a static build with clang needs a static OpenMP runtime (libomp.a), '
                                 f'which the LLVM release does not ship ({lib_dir}); building it needs the C and C++ '
                                 'compilers of the build, which are not set up. Use gcc (--use.compiler-c.name=gcc '
                                 '--use.compiler-cpp.name=gcc-cpp) or a dynamic build')

        tools = {}
        for key, name in (('cmake', CMAKE_TOOL), ('ninja', NINJA_TOOL)):
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                                'name': name, 'ctx': ctx, 'con': con, 'quiet': quiet, 'verbose': verbose})
            if self.cm.catch_error(r, fail16 = True):
                r['return'] = 1
                return r
            tools[key] = r['path']

        version = OPENMP_SRC['version']
        if con:
            print(f'{space}INFO: lib-openmp: building libomp.a from OpenMP {version} with {cc} (a static build needs it) ...')
        work = os.path.join(root, 'static-src')
        shutil.rmtree(work, ignore_errors = True)
        os.makedirs(work)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            for file_template, sha256 in OPENMP_SRC['files'].items():
                filename = file_template.format(version = version)
                url = OPENMP_SRC['url'].format(version = version, file = filename)
                r = _download(self, ctx, params, url, 'static-src', filename)
                if r['return'] > 0:
                    return self.cm.error(f'lib-openmp: could not download {url}: {r.get("error")}')
                digest = _sha256(r['path'])
                if digest != sha256:
                    return self.cm.error(f'lib-openmp: SHA-256 mismatch for {filename}: expected {sha256}, got {digest}')
                with tarfile.open(r['path']) as t:
                    kwargs = {'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}
                    t.extractall(work, members = list(safe_members(t)), **kwargs)
                os.remove(r['path'])
            # The standalone runtime build looks for the LLVM cmake modules in "../cmake"
            os.rename(os.path.join(work, f'cmake-{version}.src'), os.path.join(work, 'cmake'))
            src = os.path.join(work, f'openmp-{version}.src')
            build = os.path.join(work, 'build')
            os.makedirs(static_dir, exist_ok = True)
            for log, args in (('cmake.log', cmake_args(tools['cmake'], tools['ninja'], src, build, cc, cxx)),
                              ('build.log', [tools['cmake'], '--build', build, '--target', 'omp'])):
                if verbose:
                    print(f'{space}RUN: ' + ' '.join(args))
                p = subprocess.run(args, capture_output = True, text = True)
                with open(os.path.join(static_dir, log), 'w', encoding = 'utf-8') as f:
                    f.write(p.stdout + p.stderr)
                if p.returncode != 0:
                    return self.cm.error(f'lib-openmp: building libomp.a from OpenMP {version} failed ({log} in {static_dir}):\n'
                                         f'{(p.stderr or p.stdout).strip()[-1500:]}\n'
                                         'Use gcc (--use.compiler-c.name=gcc --use.compiler-cpp.name=gcc-cpp) or a dynamic build')
            built = os.path.join(build, 'runtime', 'src', 'libomp.a')
            if not os.path.isfile(built):
                return self.cm.error(f'lib-openmp: the build made no {built}')
            shutil.copy2(built, target)
            with open(os.path.join(static_dir, '_source.json'), 'w', encoding = 'utf-8') as f:
                json.dump({'name': 'openmp', 'version': version, 'files': OPENMP_SRC['files'], 'url': OPENMP_SRC['url'],
                           'compiler': cc, 'compiler_cxx': cxx}, f, indent = 2)
        finally:
            os.chdir(cwd)
            shutil.rmtree(work, ignore_errors = True)

        if con:
            print(f'{space}INFO: lib-openmp: {target}')
        return {'return': 0, 'path': static_dir}
