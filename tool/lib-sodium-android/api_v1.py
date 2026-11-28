"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup lib-sodium-android" (in a run for an Android target, --compute=android-cpu): libsodium
(https://libsodium.org) for the ABI of the attached device, built from upstream's pinned source
release with the NDK's clang into the tool's own cache entry, the static and the shared library side
by side:

    <entry>/install/include/sodium.h, sodium/*.h
    <entry>/install/lib/libsodium.a, libsodium.so
    <entry>/install/_source.json        what was built, from where, how, and the tests' verdict

The same on a Windows, Linux or macOS host: the sources are compiled directly (upstream's configure
needs a POSIX shell), with what that configure decides for Android written as data in _desc.yaml
(build: the sources, the flags, the definitions). The library is built for the lowest Android API
level of that block, as upstream's own Android builds, so one entry serves every device of the ABI.
Then upstream's test suite runs on the attached device, unless --with.check- . --with.abi=<ABI> builds
for a named ABI on a machine with no device attached (no tests then).

What a program gets (features, read by task setup-compile for every "lib-*" key): the include folder,
the shared library for a dynamic build (found_dynamic_libs: the run puts it on the device), the static
library by its path for a static build.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import fetch_pinned
from tool_c393ba5c6fa14f66.api.common_static_lib import object_name, safe_members

TARGET = 'target--android-cpu'
NDK_CLANG = 'android-ndk-clang'

# adb push takes several files to one folder; a few at a time keeps the command short
PUSH_BATCH = 24


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


def run(args, cwd = None, timeout = None):
    """One program with its output captured: (exit code, stdout and stderr)."""

    try:
        p = subprocess.run([str(a) for a in args], cwd = cwd, capture_output = True, text = True, errors = 'replace',
                           stdin = subprocess.DEVNULL, timeout = timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)

    return p.returncode, (p.stdout or '') + (p.stderr or '')


def clang_target(build, abi, levels):
    """
    The clang target the library is built for: the ABI's target of the build block with its API level
    (build: api_level), or the NDK's lowest level above it: (target, API level, None), or
    (None, None, why not). `levels` are the API levels the NDK has for that target.
    """

    base = (build.get('targets') or {}).get(abi)
    if not base:
        return None, None, (f'libsodium is not described for the Android ABI "{abi}" '
                            f'(build: targets of _desc.yaml has: {", ".join(sorted(build.get("targets") or {}))})')

    wanted = int(build['api_level'])
    usable = sorted(int(x) for x in levels if str(x).isdigit() and int(x) >= wanted)

    if not usable:
        return None, None, f'this NDK has no Android API level {wanted} or later for {base}'

    return base + str(usable[0]), usable[0], None


def library_sources(src_root, build):
    """The C files of the library (build: sources, without the folders of build: skip), sorted."""

    files = []
    for pattern in build['sources']:
        files += [f for f in glob.glob(os.path.join(src_root, pattern), recursive = True) if os.path.isfile(f)]

    skip = tuple(build.get('skip') or [])
    relative = sorted(set(os.path.relpath(f, src_root).replace(os.sep, '/') for f in files))

    return [os.path.join(src_root, *r.split('/')) for r in relative if not r.startswith(skip)]


def describe(tool, path):
    """The features of the libsodium whose sodium.h is `path`: (features, None) or (None, why not)."""

    include = os.path.dirname(path)
    home = os.path.dirname(include)
    lib_dir = os.path.join(home, 'lib')
    archive = os.path.join(lib_dir, 'libsodium.a')
    shared = os.path.join(lib_dir, 'libsodium.so')

    if not os.path.isfile(archive) or not os.path.isfile(shared):
        return None, f'no libsodium.a and libsodium.so in {lib_dir}'

    q = tool.cm.q
    features = {
        'paths': {'root': home, 'qroot': q(home), 'include': include, 'qinclude': q(include), 'includes': [include],
                  'lib': lib_dir, 'qlib': q(lib_dir), 'libs': [lib_dir], 'libs_static': [lib_dir]},
        'lib_names': ['sodium'],

        # the archive by its path: named with -l, a link without -static would take the shared library
        'lib_names_static': [archive],
        'static_lib': archive,
        'dynamic_lib': shared,
    }

    return features, None


def build_library(tool, ctx, params, version, abi):
    """The static and the shared library and the headers into <entry>/install: {'return': 0, ...}."""

    _global = ctx['tasks']['global']
    build = tool.cdesc.get('build') or {}
    release = tool.cdesc.get('release') or {}
    c = params.get('control', {})
    con, verbose = c.get('con', False), c.get('verbose', False)
    space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

    ndk = _global.get(NDK_CLANG) or {}
    cc = ndk.get('path')
    ar = (ndk.get('features') or {}).get('paths', {}).get('tool_lib')

    if not cc or not ar:
        return tool.cm.error('lib-sodium-android: the NDK\'s clang and llvm-ar were not set up (google.android-ndk.clang)')

    base = (build.get('targets') or {}).get(abi, '')
    levels = ((ndk.get('features') or {}).get('abi-android-versions') or {}).get(base.split('-')[0]) or []

    target, api_level, error = clang_target(build, abi, levels)
    if error:
        return tool.cm.error('lib-sodium-android: ' + error)

    r = fetch_pinned(tool, ctx, params, release, 'source', version)
    if r['return'] > 0:
        return r
    package = r

    # The sources of a checked release, unpacked afresh
    root = os.getcwd()
    install = os.path.join(root, 'install')
    src_parent = os.path.join(root, 'src')
    obj_dir = os.path.join(root, 'obj')

    for folder in (install, src_parent, obj_dir):
        shutil.rmtree(folder, ignore_errors = True)

    with tarfile.open(package['path']) as t:
        t.extractall(src_parent, members = list(safe_members(t)), **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))

    top = os.path.join(src_parent, release['source_dir'].format(version = version))
    src_root = os.path.join(top, *build['src'].split('/'))
    version_header = os.path.join(top, *build['version_header'].split('/'))

    srcs = library_sources(src_root, build)
    if not srcs or not os.path.isfile(version_header):
        return tool.cm.error(f'lib-sodium-android: libsodium {version} does not look as _desc.yaml (build:) describes it: '
                             f'{len(srcs)} sources in {src_root}, version header {version_header}')

    # The version header where the sources include it from, as configure leaves it
    shutil.copy2(version_header, os.path.join(src_root, 'include', 'sodium', 'version.h'))

    defines = list(build.get('defines') or []) + list((build.get('defines_abi') or {}).get(abi) or [])
    common = ['--target=' + target] + list(build.get('cflags') or []) + ['-D' + d for d in defines]
    includes = ['-I' + os.path.join(src_root, *d.split('/')) for d in build.get('include_dirs') or ['.']]

    os.makedirs(obj_dir)
    jobs = [(src, object_name(src_root, src, '.o')) for src in srcs]

    if con:
        print(f'{space}INFO: building libsodium {version} for Android {abi} ({target}, {len(jobs)} sources) with {cc} ...')

    def compile_one(job):
        args = [cc, '-c'] + common + includes + [job[0], '-o', job[1]]
        return job[0], args, run(args, cwd = obj_dir)

    with ThreadPoolExecutor(max_workers = min(16, os.cpu_count() or 2)) as pool:
        for src, args, (code, out) in pool.map(compile_one, jobs):
            if code != 0:
                return tool.cm.error(f'compiling {os.path.relpath(src, src_root)} failed:\n{" ".join(args)}\n{out.strip()[-2000:]}')

    lib_dir = os.path.join(install, 'lib')
    os.makedirs(lib_dir)
    archive = os.path.join(lib_dir, 'libsodium.a')
    shared = os.path.join(lib_dir, 'libsodium.so')
    objs = [o for _, o in jobs]

    for what, args, made in (('archiving libsodium.a', [ar, 'rcs', archive] + objs, archive),
                             ('linking libsodium.so', [cc, '--target=' + target] + list(build.get('ldflags_shared') or ['-shared']) +
                              ['-o', shared] + objs, shared)):
        code, out = run(args, cwd = obj_dir)
        if code != 0 or not os.path.isfile(made):
            return tool.cm.error(f'{what} failed:\n{" ".join(args[:6])} ...\n{out.strip()[-2000:]}')

    # The public headers, in the tree they have in the sources
    copied = 0
    for pattern in build.get('headers') or []:
        for header in sorted(glob.glob(os.path.join(src_root, *pattern.split('/')))):
            dest = os.path.join(install, os.path.relpath(header, src_root))
            os.makedirs(os.path.dirname(dest), exist_ok = True)
            shutil.copy2(header, dest)
            copied += 1

    found = os.path.join(install, 'include', 'sodium.h')
    if not os.path.isfile(found) or read_version(os.path.dirname(found)) != version:
        return tool.cm.error(f'lib-sodium-android: the headers of libsodium {version} were not installed as expected '
                             f'({copied} copied into {os.path.join(install, "include")})')

    return {'return': 0, 'found_path': found, 'top': top, 'target': target, 'api_level': api_level, 'cc': cc,
            'common': common, 'lib_dir': lib_dir, 'shared': shared, 'package': package, 'sources': len(jobs)}


def check_on_device(tool, ctx, params, built):
    """
    Upstream's test programs, compiled against the shared library, run on the attached device in a
    folder of their own (build: tests: device_dir), which is removed after: {'return': 0, 'tests': n}.
    """

    _global = ctx['tasks']['global']
    tests = (tool.cdesc.get('build') or {}).get('tests') or {}
    c = params.get('control', {})
    con, verbose = c.get('con', False), c.get('verbose', False)
    space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

    adb = (_global.get('adb') or {}).get('path')
    serial = (_global.get(TARGET) or {}).get('serial')

    if not adb or not serial:
        return tool.cm.error('lib-sodium-android: no adb or no selected device to run the tests on (--with.check- skips them)')

    top = built['top']
    sources = sorted(glob.glob(os.path.join(top, *tests['sources'].split('/'))))
    expected = sorted(glob.glob(os.path.join(top, *tests['expected'].split('/'))))
    names = [os.path.splitext(os.path.basename(s))[0] for s in sources]

    if not names or set(names) != set(os.path.splitext(os.path.basename(e))[0] for e in expected):
        return tool.cm.error(f'lib-sodium-android: the test programs of this libsodium are not as _desc.yaml (build: tests) '
                             f'describes them: {len(sources)} sources, {len(expected)} expected outputs')

    bin_dir = os.path.join(os.getcwd(), 'tests')
    shutil.rmtree(bin_dir, ignore_errors = True)
    os.makedirs(bin_dir)

    includes = ['-I' + os.path.join(top, *d.split('/')) for d in tests.get('include_dirs') or []]

    if con:
        print(f'{space}INFO: building the {len(names)} test programs of libsodium ...')

    def compile_one(job):
        args = [built['cc']] + built['common'] + ['-DTEST_SRCDIR="."'] + includes + \
               [job[0], '-o', os.path.join(bin_dir, job[1]), '-L' + built['lib_dir'], '-lsodium']
        return job[1], args, run(args, cwd = bin_dir)

    with ThreadPoolExecutor(max_workers = min(16, os.cpu_count() or 2)) as pool:
        for name, args, (code, out) in pool.map(compile_one, list(zip(sources, names))):
            if code != 0:
                return tool.cm.error(f'compiling the test {name} failed:\n{" ".join(args)}\n{out.strip()[-2000:]}')

    device_dir = tests['device_dir']
    files = [os.path.join(bin_dir, n) for n in names] + expected + [built['shared']]

    if con:
        print(f'{space}INFO: running them on the device {serial} in {device_dir} ...')

    def on_device(*args, timeout = 1800):
        return run([adb, '-s', serial] + list(args), timeout = timeout)

    code, out = on_device('shell', f'rm -rf {device_dir} && mkdir -p {device_dir}')
    if code != 0:
        return tool.cm.error(f'lib-sodium-android: could not make {device_dir} on the device: {out.strip()}')

    try:
        for i in range(0, len(files), PUSH_BATCH):
            code, out = on_device('push', *files[i:i + PUSH_BATCH], device_dir + '/')
            if code != 0:
                return tool.cm.error(f'lib-sodium-android: adb push failed: {out.strip()[-500:]}')

        # pushed from Windows, files are not executable; a test passes when it exits 0 (its output
        # compared with its .exp by the program itself)
        loop = (f'cd {device_dir} && chmod 755 * && for e in *.exp; do t=${{e%.exp}}; '
                f'LD_LIBRARY_PATH=. ./$t > /dev/null 2>&1; echo "RESULT $t $?"; done')
        code, out = on_device('shell', loop)

    finally:
        on_device('shell', f'rm -rf {device_dir}', timeout = 120)
        shutil.rmtree(bin_dir, ignore_errors = True)

    results = dict(re.findall(r'^RESULT (\S+) (\d+)\s*$', out, re.MULTILINE))
    failed = sorted(n for n in names if results.get(n) != '0')

    if code != 0 or failed:
        shown = ', '.join(f'{n} ({results.get(n, "not run")})' for n in failed[:20])
        return tool.cm.error(f'lib-sodium-android: {len(failed)} of the {len(names)} tests of libsodium failed on the device '
                             f'{serial}: {shown or out.strip()[-500:]}')

    if con:
        print(f'{space}INFO: the {len(names)} tests of libsodium passed on the device')

    return {'return': 0, 'tests': len(names)}


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        The ABI of the attached device (target android-cpu) names the cache entry. A setup of its own
        (cx tool setup lib-sodium-android) runs the target first; in a program's run for android-cpu
        it is there already. --with.abi=<ABI> names the ABI instead: a build on a machine with no
        device attached (the tests are then not run).
        """

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        abi = (params.get('with') or {}).get('abi')
        if abi:
            ctx_tasks['local']['target_abi'] = str(abi)
            return {'return': 0}

        if TARGET not in _global:
            c = ctx['control']
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run',
                                'arg1': 'target--android-cpu,eb4790d97cf74df9', 'ctx': ctx, 'con': c.get('con', False),
                                'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False)})
            if r.get('return', 1) > 0:
                return r

        if TARGET not in _global:
            return self.cm.error('lib-sodium-android: the target compute "android-cpu" must be selected (an Android device '
                                 'attached), or the ABI named: --with.abi=arm64-v8a')

        ctx_tasks['local']['target_abi'] = _global[TARGET]['features']['ro.product.cpu.abi']

        return {'return': 0}

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        The pinned source release compiled with the NDK's clang into the tool's cache entry, then
        upstream's tests on the attached device unless --with.check- .
        """

        version = params.get('version_simple') or str(self.cdesc.get('default_version') or '')

        if not version:
            return self.cm.error('lib-sodium-android needs an exact version (--version=1.0.22): its _desc.yaml pins the '
                                 'default one (default_version) and the SHA-256 of each release it can build')

        abi = ctx['tasks']['local'].get('target_abi')
        # the tests run on the device the ABI was read from; with a named ABI and no device they are
        # not run, unless asked (--with.check), which then needs the device
        check = (params.get('with') or {}).get('check')
        check = (TARGET in ctx['tasks']['global']) if check is None else is_true(check)

        r = build_library(self, ctx, params, version, abi)
        if r['return'] > 0:
            return r
        built = r

        tests = 'not run'
        if check:
            r = check_on_device(self, ctx, params, built)
            if r['return'] > 0:
                return r
            tests = f'{r["tests"]} passed on the device'

        package = built['package']
        root = os.getcwd()

        with open(os.path.join(root, 'install', '_source.json'), 'w', encoding = 'utf-8') as f:
            json.dump({'name': 'libsodium', 'version': version, 'kind': 'source', 'url': package['url'],
                       'sha256': package['sha256'], 'abi': abi, 'target': built['target'], 'api_level': built['api_level'],
                       'compiler': built['cc'], 'compiler_version': (ctx['tasks']['global'].get(NDK_CLANG) or {}).get('version'),
                       'sources': built['sources'], 'tests': tests}, f, indent = 2)

        shutil.rmtree(os.path.join(root, 'src'), ignore_errors = True)
        shutil.rmtree(os.path.join(root, 'obj'), ignore_errors = True)
        os.remove(package['path'])

        return {'return': 0, 'install_cmd': None, 'found_path': built['found_path']}

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        Each sodium.h -> its version (sodium/version.h) and what a build links (describe).
        """

        found = {}
        errors = []

        for path in paths:
            version = read_version(os.path.dirname(path))
            if not version:
                continue

            features, error = describe(self, path)
            if error:
                errors.append(error)
                continue

            found[path] = {'output': version, 'features': features}

        if not found and errors:
            return self.cm.error('lib-sodium-android: ' + '; '.join(errors))

        return {'return': 0, 'found_paths_with_versions': found}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        Runs for a fresh and for a reused result: what a build links is read from the installation
        as it is now. A dynamic build (no with.static) names the shared library for the device.
        """

        path = result.get('path')

        if result.get('return', 0) != 0 or params.get('version_check', False) or not path or not os.path.isfile(path):
            return {'return': 0}

        features, error = describe(self, path)
        if error:
            return self.cm.error('lib-sodium-android: ' + error)

        if not is_true((params.get('with') or {}).get('static')):
            features['paths']['found_dynamic_libs'] = [features['dynamic_lib']]

        kept = result.setdefault('features', {})
        for key in ('lib_names', 'lib_names_static', 'static_lib', 'dynamic_lib', 'paths'):
            kept.pop(key, None)
        kept.update(features)

        return {'return': 0, 'result': result}
