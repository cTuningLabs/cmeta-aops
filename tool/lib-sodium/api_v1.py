"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup lib-sodium": libsodium (https://libsodium.org) in the tool's own cache entry, the same
way on every system - upstream's release of the pinned version, checked against the SHA-256 pinned in
_desc.yaml (release:), with the static and the shared library side by side:

  Linux, macOS   the source release built with its own configure and make and the C compiler of
                 cMeta into <entry>/install (lib/libsodium.a and libsodium.so or libsodium.dylib),
                 then upstream's test suite (make check) unless --with.check- ;

  Windows        upstream's build for MSVC, which clang links too: the include folder and the Release
                 libraries of this machine's architecture, unpacked into <entry>/install (static:
                 libsodium.lib; dynamic: the import library and libsodium.dll).

Nothing is installed into the system and no package manager is asked. A libsodium that is already
there is used only when its sodium.h is named: --tool_path=<prefix>/include/sodium.h (a prefix with
lib/, or an unpacked MSVC package).

What a program gets (features, read by task setup-compile for every "lib-*" key): the include folder,
the shared library for a dynamic build (and its folder for the run-time path), the static library by
its path for a static build, with the libraries the static one needs. A static link on Windows needs
-DSODIUM_STATIC in the program (libsodium's own rule; harmless elsewhere).
"""

import glob
import json
import os
import re
import shutil
import tarfile
import zipfile

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import fetch_pinned
from tool_c393ba5c6fa14f66.api.common_static_lib import c_compiler

MAKE = 'make,d539463695b8480c'

# The shared library of a prefix, by system
SHARED_NAMES = {'linux': 'libsodium.so', 'darwin': 'libsodium.dylib'}


def is_true(value):
    """A boolean from a with.* value: None, '' and False are False; strings are read."""

    if value in (None, '', False):
        return False

    if isinstance(value, str):
        return value.strip().lower() in ('true', 'yes', '1', 'on')

    return bool(value)


def read_version(include_root):
    """The SODIUM_VERSION_STRING of <include_root>/sodium/version.h, or None."""

    try:
        with open(os.path.join(include_root, 'sodium', 'version.h'), encoding = 'utf-8', errors = 'replace') as f:
            text = f.read()
    except OSError:
        return None

    m = re.search(r'SODIUM_VERSION_STRING\s+"([^"]+)"', text)

    return m.group(1) if m else None


def private_libs(lib_dir):
    """The libraries a static link needs besides libsodium.a: the -l names of "Libs.private" in the
    pkg-config file the build installed (pthread, where the system keeps it apart)."""

    try:
        with open(os.path.join(lib_dir, 'pkgconfig', 'libsodium.pc'), encoding = 'utf-8') as f:
            text = f.read()
    except OSError:
        return []

    m = re.search(r'^Libs\.private:(.*)$', text, re.MULTILINE)

    return [x[2:] for x in (m.group(1).split() if m else []) if x.startswith('-l') and len(x) > 2]


def toolset_number(name):
    """The number of an MSVC toolset folder (v143 -> 143), or None for another folder."""

    m = re.fullmatch(r'v(\d+)', name)

    return int(m.group(1)) if m else None


def describe_msvc(home, arch, wanted = None):
    """
    An unpacked MSVC package (<home>/<arch>/Release/<toolset>/static|dynamic): its features, or an
    error text. Without --with.toolset the oldest toolset of the package is taken: Microsoft's
    linkers take libraries of the same and of older toolsets, so it links with the most compilers.
    """

    base = os.path.join(home, arch, 'Release')
    toolsets = sorted((d for d in (os.listdir(base) if os.path.isdir(base) else []) if toolset_number(d) is not None),
                      key = toolset_number)

    if not toolsets:
        return None, f'no MSVC libraries for this architecture in {base}'

    toolset = str(wanted) if wanted else toolsets[0]

    if toolset not in toolsets:
        return None, f'the MSVC toolset "{toolset}" (--with.toolset) is not in this libsodium (it has: {", ".join(toolsets)})'

    static = os.path.join(base, toolset, 'static', 'libsodium.lib')
    dynamic = os.path.join(base, toolset, 'dynamic', 'libsodium.lib')
    dll = os.path.join(base, toolset, 'dynamic', 'libsodium.dll')

    features = {'toolset': toolset, 'toolsets': toolsets}
    paths = {}

    if os.path.isfile(dynamic) and os.path.isfile(dll):
        folder = os.path.dirname(dynamic)
        paths.update({'lib': folder, 'libs': [folder], 'dynamic_lib': folder, 'found_dynamic_lib_paths': [folder]})

        # the import library by its path: the linker takes it as it is; libsodium.dll is loaded at run time
        features['lib_names'] = [dynamic]
        features['dynamic_lib'] = dll

    if os.path.isfile(static):
        paths['libs_static'] = [os.path.dirname(static)]

        # the static library names the system libraries it needs itself (/DEFAULTLIB: advapi32)
        features['lib_names_static'] = [static]
        features['static_lib'] = static

        if 'lib_names' not in features:
            features['lib_names'] = [static]

    if 'lib_names' not in features:
        return None, f'no libsodium.lib in {os.path.join(base, toolset)}'

    features['paths'] = paths

    return features, None


def describe_prefix(home, uname):
    """A prefix with lib/ (what configure and make install leave, a system's own layout): its
    features, or an error text."""

    shared_name = SHARED_NAMES.get(uname, 'libsodium.so')

    # lib/ first, then the multiarch and lib64 folders of a system's prefix, each in a fixed order
    folders = [os.path.join(home, 'lib')] + sorted(glob.glob(os.path.join(home, 'lib', '*-linux-gnu*'))) + \
              [os.path.join(home, 'lib64')]

    lib_dir = next((d for d in folders if os.path.isfile(os.path.join(d, 'libsodium.a')) or
                    os.path.isfile(os.path.join(d, shared_name))), None)

    if not lib_dir:
        return None, f'no libsodium.a or {shared_name} under {os.path.join(home, "lib")}'

    archive = os.path.join(lib_dir, 'libsodium.a')
    shared = os.path.join(lib_dir, shared_name)

    features = {'lib_names': ['sodium']}
    paths = {'lib': lib_dir, 'libs': [lib_dir]}

    if os.path.isfile(shared):
        paths.update({'dynamic_lib': lib_dir, 'found_dynamic_lib_paths': [lib_dir]})
        features['dynamic_lib'] = shared

    if os.path.isfile(archive):
        paths['libs_static'] = [lib_dir]

        # the archive by its path: named with -l, a link without -static would take the shared library
        features['lib_names_static'] = [archive] + private_libs(lib_dir)
        features['static_lib'] = archive

    features['paths'] = paths

    return features, None


def describe(tool, path, uname, uarch, params):
    """
    The features of the libsodium whose sodium.h is `path`, as the installation is now: (features,
    None), or (None, why it cannot be used). A missing static library is not an error here: the
    features say why (static_unavailable) and a static build stops on it.
    """

    include = os.path.dirname(path)
    home = os.path.dirname(include)
    release = tool.cdesc.get('release') or {}
    msvc_arch = (release.get('msvc_arch') or {}).get(uarch)

    if uname == 'windows' and msvc_arch and os.path.isdir(os.path.join(home, msvc_arch, 'Release')):
        features, error = describe_msvc(home, msvc_arch, (params.get('with') or {}).get('toolset'))
    else:
        features, error = describe_prefix(home, uname)

    if error:
        return None, error

    q = tool.cm.q
    paths = features['paths']
    paths.update({'root': home, 'qroot': q(home), 'include': include, 'qinclude': q(include), 'includes': [include]})

    if paths.get('lib'):
        paths['qlib'] = q(paths['lib'])

    if 'lib_names_static' not in features:
        features['static_unavailable'] = (f'this libsodium ({home}) has no static library: set up the one of cMeta '
                                          f'("cx tool setup lib-sodium" without --tool_path), or build the program '
                                          f'without --compile.static')

    return features, None


def write_source_record(install, record):
    """What was installed, from where and how: <entry>/install/_source.json."""

    with open(os.path.join(install, '_source.json'), 'w', encoding = 'utf-8') as f:
        json.dump(record, f, indent = 2)


def install_msvc(tool, ctx, params, version):
    """Windows: upstream's MSVC package - the headers and the Release libraries of this machine's
    architecture - unpacked into <entry>/install."""

    _global = ctx['tasks']['global']
    uarch = _global['host']['os']['uarch']
    release = tool.cdesc.get('release') or {}
    arch = (release.get('msvc_arch') or {}).get(uarch)

    if not arch:
        return tool.cm.error(f'upstream\'s MSVC package of libsodium has no libraries for "{uarch}" '
                             f'(it has: {", ".join(sorted(release.get("msvc_arch") or {}))})')

    r = fetch_pinned(tool, ctx, params, release, 'msvc', version)
    if r['return'] > 0:
        return r
    package = r

    root = os.getcwd()
    install = os.path.join(root, 'install')
    shutil.rmtree(install, ignore_errors = True)

    # the package holds one folder, "libsodium": its include/ and <arch>/Release/ are what a build needs
    wanted = ('libsodium/include/', f'libsodium/{arch}/Release/')

    with zipfile.ZipFile(package['path']) as z:
        for info in z.infolist():
            name = info.filename.replace('\\', '/')

            if info.is_dir() or not name.startswith(wanted) or '..' in name.split('/'):
                continue

            target = os.path.join(install, *name.split('/')[1:])
            os.makedirs(os.path.dirname(target), exist_ok = True)

            with z.open(info) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)

    found = os.path.join(install, 'include', 'sodium.h')
    if not os.path.isfile(found):
        return tool.cm.error(f'{os.path.basename(package["path"])} was unpacked but {found} is missing')

    write_source_record(install, {'name': 'libsodium', 'version': version, 'kind': 'msvc', 'url': package['url'],
                                  'sha256': package['sha256'], 'arch': arch})
    os.remove(package['path'])

    return {'return': 0, 'install_cmd': None, 'found_path': found}


def install_source(tool, ctx, params, version):
    """Linux, macOS: the source release built with its configure and make and the C compiler of
    cMeta into <entry>/install, its test suite run unless --with.check- ."""

    _global = ctx['tasks']['global']
    uname = _global['host']['os']['uname']
    release = tool.cdesc.get('release') or {}
    c = params.get('control', {})
    con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
    space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''
    check = (params.get('with') or {}).get('check')
    check = True if check is None else is_true(check)

    root = os.getcwd()
    install = os.path.join(root, 'install')

    def run(command, what, log, work_dir, env = None):
        if con:
            print(f'{space}INFO: {what} ... (log: {log})')

        rr = tool.cm.utils.sys.run(command, work_dir = work_dir, capture_output = True, env = env or {},
                                   con = con, verbose = verbose, text_cmd = 'RUN', space = space)
        if rr['return'] > 0:
            return rr

        with open(log, 'w', encoding = 'utf-8') as f:
            f.write((rr.get('stdout') or '') + (rr.get('stderr') or ''))

        if rr.get('returncode', 0) != 0:
            with open(log, encoding = 'utf-8') as f:
                tail = ''.join(f.readlines()[-25:])
            return tool.cm.error(f'{what} failed (return code {rr.get("returncode")}):\n{tail}')

        return {'return': 0}

    # The C compiler of the run (the program's, else the one cMeta selects) and make
    r = c_compiler(tool, ctx, params)
    if r['return'] > 0:
        return r
    compiler = r['compiler']

    r = tool.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                        'ctx': ctx, 'name': MAKE, 'con': con, 'quiet': quiet, 'verbose': verbose})
    if r['return'] > 0:
        hint = ' (on macOS: xcode-select --install)' if uname == 'darwin' else ''
        return tool.cm.error(f'building libsodium needs make{hint}: {r.get("error")}')
    make = _global.get('make', {}).get('qpath') or tool.cm.q(r.get('tool_path'))

    r = fetch_pinned(tool, ctx, params, release, 'source', version)
    if r['return'] > 0:
        return r
    package = r

    # The sources of a checked release, unpacked afresh
    src_parent = os.path.join(root, 'src')
    shutil.rmtree(src_parent, ignore_errors = True)
    shutil.rmtree(install, ignore_errors = True)

    with tarfile.open(package['path']) as t:
        t.extractall(src_parent, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))

    src = os.path.join(src_parent, release['source_dir'].format(version = version))
    if not os.path.isfile(os.path.join(src, 'configure')):
        return tool.cm.error(f'{os.path.basename(package["path"])} was unpacked but {src} has no configure')

    configure = ' '.join(release.get('configure') or [])
    jobs = max(1, min(os.cpu_count() or 1, 16))
    env = {'CC': compiler['path']}

    steps = [(f'./configure --prefix={tool.cm.q(install)} {configure}', f'configuring libsodium {version}', 'build-configure.log'),
             (f'{make} -j{jobs}', f'building libsodium {version} with {jobs} jobs', 'build-make.log')]
    if check:
        steps.append((f'{make} -j{jobs} check', 'running the test suite of libsodium', 'build-check.log'))
    steps.append((f'{make} install', f'installing it into {install}', 'build-install.log'))

    for command, what, log in steps:
        r = run(command, what, os.path.join(root, log), src, env)
        if r['return'] > 0:
            return r

    found = os.path.join(install, 'include', 'sodium.h')
    if not os.path.isfile(found):
        return tool.cm.error(f'libsodium {version} was built but {found} is missing')

    write_source_record(install, {'name': 'libsodium', 'version': version, 'kind': 'source', 'url': package['url'],
                                  'sha256': package['sha256'], 'configure': release.get('configure') or [],
                                  'compiler': compiler['path'], 'compiler_version': compiler.get('version'),
                                  'tests': 'passed' if check else 'not run'})

    shutil.rmtree(src_parent, ignore_errors = True)
    os.remove(package['path'])

    return {'return': 0, 'install_cmd': None, 'found_path': found}


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        The pinned release in the cache (skip_detect of _desc.yaml) unless a sodium.h is named
        (--tool_path): that installation is then described, never changed.
        """

        if params.get('tool_path'):
            params['skip_detect'] = False

        return {'return': 0}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Upstream's release into the tool's cache entry: the MSVC package on Windows, the source
        release built with configure and make elsewhere.
        """

        version = params.get('version_simple') or str(self.cdesc.get('default_version') or '')

        if not version:
            return self.cm.error('lib-sodium needs an exact version (--version=1.0.22): its _desc.yaml pins the '
                                 'default one (default_version) and the SHA-256 of each release it can install')

        if ctx['tasks']['global']['host']['os']['uname'] == 'windows':
            return install_msvc(self, ctx, params, version)

        return install_source(self, ctx, params, version)

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        Each sodium.h -> its version (sodium/version.h) and what a build links (describe).
        """

        host = ctx['tasks']['global']['host']['os']
        found = {}
        errors = []

        for path in paths:
            version = read_version(os.path.dirname(path))
            if not version:
                continue

            features, error = describe(self, path, host['uname'], host['uarch'], params)
            if error:
                errors.append(error)
                continue

            found[path] = {'output': version, 'features': features}

        # a named sodium.h that cannot be used says why
        if not found and errors:
            return self.cm.error('lib-sodium: ' + '; '.join(errors))

        return {'return': 0, 'found_paths_with_versions': found}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        Runs for a fresh and for a reused result: what a build links is read from the installation
        as it is now and for this request (--with.toolset), so an entry made before a change of
        this tool serves it too. A request with with.static stops when there is no static library.
        """

        path = result.get('path')

        if result.get('return', 0) != 0 or params.get('version_check', False) or not path or not os.path.isfile(path):
            return {'return': 0}

        host = ctx['tasks']['global']['host']['os']

        features, error = describe(self, path, host['uname'], host['uarch'], params)
        if error:
            return self.cm.error('lib-sodium: ' + error)

        if is_true((params.get('with') or {}).get('static')) and features.get('static_unavailable'):
            return self.cm.error('lib-sodium: ' + features['static_unavailable'])

        # what the detection recorded besides (the flags of the meta) stays; these keys are current
        kept = result.setdefault('features', {})
        for key in ('lib_names', 'lib_names_static', 'static_lib', 'dynamic_lib', 'static_unavailable', 'toolset',
                    'toolsets', 'paths'):
            kept.pop(key, None)
        kept.update(features)

        return {'return': 0, 'result': result}
