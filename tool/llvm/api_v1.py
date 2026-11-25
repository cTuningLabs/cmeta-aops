"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256

LLVM_RELEASES = 'https://github.com/llvm/llvm-project/releases/download/llvmorg-{version}/{filename}'
LLVM_TAGS_REPO = 'https://github.com/llvm/llvm-project'
LLVM_RELEASE_API = 'https://api.github.com/repos/llvm/llvm-project/releases/tags/llvmorg-{version}'

OPENMP_MARKER = '.cmeta-openmp.json'     # in the content folder of an LLVM whose OpenMP runtime this tool built or tried


def has_openmp(home):
    """Whether an LLVM has the OpenMP runtime with its clang: omp.h in clang's resource folder (lib/clang/<N>/include)."""
    return bool(home) and bool(glob.glob(os.path.join(home, 'lib', 'clang', '*', 'include', 'omp.h')))


def is_inside(path, folder):
    """Whether a path is inside a folder (both real paths), the folder itself excluded."""
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(folder)]) == os.path.realpath(folder) and \
               os.path.realpath(path) != os.path.realpath(folder)
    except ValueError:                                            # another drive on Windows
        return False


def openmp_sources(spec, version, assets = None):
    """
    The sources of the OpenMP runtime of an LLVM release (openmp_runtime of _desc.yaml), checked before a download:
    the first layout of spec['sources'] that the release publishes, with a sha256 for each of its files - the one
    pinned in spec['sha256'][<version>], else the one GitHub publishes for the asset.

    assets: {<asset name>: <sha256 or None>} of the release, as GitHub lists it; None when it could not be listed
            (then only a layout whose digests are all pinned is taken).
    -> {'files': {<folder>: <file name>}, 'folders': [...], 'sha256': {<file name>: <sha256>}} or
       {'files': None, 'why': <text>}
    """
    pinned = ((spec or {}).get('sha256') or {}).get(str(version)) or {}
    whys = []
    for layout in (spec or {}).get('sources') or []:
        files = {key: str(name).format(version = version) for key, name in (layout.get('files') or {}).items()}
        if not files:
            continue
        if assets is not None and not all(name in assets for name in files.values()):
            whys.append(f'{", ".join(files.values())}: not published with the release')
            continue
        digests = {name: (pinned.get(name) or (assets or {}).get(name) or '').lower() for name in files.values()}
        unchecked = [name for name, sha in digests.items() if not re.fullmatch(r'[0-9a-f]{64}', sha)]
        if unchecked:
            whys.append(f'{", ".join(unchecked)}: no sha256 pinned' + ('' if assets is None else ' or published'))
            continue
        return {'files': files, 'folders': list(layout.get('folders') or []), 'sha256': digests}
    return {'files': None, 'why': '; '.join(whys) or 'no source layout declared'}


def release_assets(version, timeout = 30):
    """{<asset name>: <sha256 or None>} of an LLVM release, as GitHub lists it; None when it cannot be listed."""
    request = urllib.request.Request(LLVM_RELEASE_API.format(version = version),
                                     headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'cmeta-tool-llvm'})
    try:
        with urllib.request.urlopen(request, timeout = timeout) as f:
            release = json.load(f)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    assets = {}
    for a in release.get('assets') or []:
        digest = str(a.get('digest') or '')
        assets[a.get('name')] = digest.split(':', 1)[1] if digest.startswith('sha256:') else None
    return assets


def safe_members(t, folders = None):
    """
    The members of a source archive to unpack, its top folder dropped: files and folders only (no links, nothing
    absolute or with ".."), and with folders only those under <top>/<folder>/.
    """
    for m in t.getmembers():
        parts = Path(m.name).parts
        if m.name.startswith('/') or '..' in parts or m.issym() or m.islnk() or len(parts) < 2:
            continue
        if folders and parts[1] not in folders:
            continue
        m.name = '/'.join(parts[1:])
        yield m


def place_openmp(stage, resource_dir, lib_dir):
    """
    The OpenMP runtime installed into a staging folder, put where a release with OpenMP keeps it: the headers into
    clang's resource folder "include", the libraries into lib_dir. -> the paths placed.
    """
    placed = []
    include = os.path.join(stage, 'include')
    for name in sorted(os.listdir(include)) if os.path.isdir(include) else []:
        if name.endswith('.h') and os.path.isfile(os.path.join(include, name)):
            os.makedirs(os.path.join(resource_dir, 'include'), exist_ok = True)
            placed.append(shutil.copy2(os.path.join(include, name), os.path.join(resource_dir, 'include', name)))
    lib = os.path.join(stage, 'lib')
    for name in sorted(os.listdir(lib)) if os.path.isdir(lib) else []:
        if name.startswith('lib') and re.search(r'\.(so(\.[0-9.]+)?|a|dylib)$', name) and os.path.isfile(os.path.join(lib, name)):
            os.makedirs(lib_dir, exist_ok = True)
            placed.append(shutil.copy2(os.path.join(lib, name), os.path.join(lib_dir, name)))
    return placed


def is_swift_toolchain(path, output = ''):
    """
    Whether a clang belongs to a Swift toolchain (swift.org's fork of LLVM): its --version names
    swiftlang, or it lives in swiftly's folder (Linux, macOS), under Swift/Toolchains (Windows) or in a
    swift-*.xctoolchain (macOS). Such a clang carries no OpenMP headers or runtime.
    """
    if 'swiftlang' in (output or '').lower():
        return True
    p = path.replace('\\', '/').lower()
    return '/swiftly/' in p or '/swift/toolchains/' in p or ('.xctoolchain/' in p and '/swift-' in p)


def rank_swift_last(paths, sort_key):
    """
    The candidates of the detection with every other clang before the Swift toolchain's: the others
    get the detection's priority mark, in their own order (version, then path), so a newer Swift clang
    does not win over an LLVM, Apple or distribution clang. Returns (paths, only_swift): only_swift when
    no other clang was found, so the Swift one is taken (with a warning about OpenMP).
    """
    others = [p for p in paths if not p.get('features', {}).get('swift_toolchain')]
    swift = [p for p in paths if p.get('features', {}).get('swift_toolchain')]
    if not swift or not others:
        return paths, bool(swift) and not others
    others.sort(key = sort_key)
    for p in others:
        p['priority'] = True
    return others + swift, False


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        new_paths = []

        for p in paths:
            features = p.setdefault('features', {})
            paths = features.setdefault('paths', {})

            path = p['path']

            # The folders of the installation the binary belongs to: a distribution's /usr/bin/clang is
            # a link into /usr/lib/llvm-<N>/bin, whose parent holds its lib and include (not "/")
            path_real = os.path.realpath(path)
            path_bin = os.path.dirname(path_real)
            path_home = os.path.dirname(path_bin)

            paths['bin'] = path_bin
            paths['qbin'] = self.cm.q(path_bin)

            paths['home'] = path_home
            paths['qhome'] = self.cm.q(path_home)

            if is_swift_toolchain(path, p.get('output', '')):
                features['swift_toolchain'] = True

            new_paths.append(p)

        # A Swift toolchain's clang (swiftly, Swift/Toolchains) is often first on PATH; it has no OpenMP
        # headers or runtime, so every other clang ranks before it
        for p in new_paths:
            p['path_len'] = len(p['path'])
        new_paths, only_swift = rank_swift_last(
            new_paths, lambda a: self.cm.utils.common.build_sort_key(a, ['@detected_version-', 'path_len', 'path']))

        if only_swift and con:
            print ('')
            print (f"WARNING: the only clang found is a Swift toolchain's ({new_paths[0]['path']}): it has no OpenMP "
                   f"headers or runtime, so programs with OpenMP fail with it; \"cx tool setup llvm\" installs LLVM")

        return {'return':0, 'paths':new_paths}


    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        On every use of the LLVM (installed now or reused from the cache): features.openmp says whether its clang
        has the OpenMP runtime, and an LLVM this tool unpacked into its own cache entry without one gets it, built
        from the same release's sources (openmp_runtime of _desc.yaml). Whatever stops that build is said and the
        LLVM is used as it is - programs without OpenMP do not need it.
        """
        r = self.complete_openmp(ctx, result, params)
        if r['return'] > 0 and ctx['control'].get('con', False):
            print ('')
            print (f'WARNING: this LLVM has no OpenMP runtime (omp.h, libomp), so programs built with -fopenmp fail with '
                   f'its clang: {r.get("error")}')
        return {'return': 0, 'result': result}

    ############################################################
    def complete_openmp(self,
                        ctx: dict,
                        result: dict,
                        params: dict = {},
    ):
        """
        The OpenMP runtime of an LLVM this tool unpacked (see finish_dynamic_result). -> {'return': 0} when it has
        one, gets one or is not this tool's to complete; {'return': 1, 'error': ...} when it stays without.
        """
        _global = ctx['tasks']['global']
        uname = _global['host']['os']['uname']
        spec = self.cdesc.get('openmp_runtime') or {}

        features = result.setdefault('features', {})
        home = (features.get('paths') or {}).get('home') or ''
        features['openmp'] = has_openmp(home)
        if features['openmp'] or uname not in (spec.get('systems') or []):
            return {'return': 0}

        # Only an LLVM unpacked into this tool's own cache entry: never one of the system or of another installer
        clang = result.get('path') or ''
        entry = result.get('path_cmeta_cache') or ''
        content = os.path.join(entry, 'content')
        if not (entry and clang and home and is_inside(clang, content) and is_inside(home, entry)):
            return {'return': 0}

        version = str(result.get('version') or result.get('detected_version') or '')
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
            return {'return': 1, 'error': f'the release of this LLVM is not known ({version or "no version"})'}

        # A release whose sources could not be found or checked is tried again only when openmp_runtime changes
        marker = os.path.join(home, OPENMP_MARKER)
        spec_key = json.dumps({'sources': spec.get('sources'), 'sha256': (spec.get('sha256') or {}).get(version),
                               'cmake_args': spec.get('cmake_args')}, sort_keys = True)
        if os.path.isfile(marker):
            try:
                with open(marker, encoding = 'utf-8') as f:
                    tried = json.load(f)
            except (OSError, ValueError):
                tried = {}
            if tried.get('status') == 'unavailable' and tried.get('spec') == spec_key:
                return {'return': 1, 'error': tried.get('why', '')}

        # The sources: their sha256 pinned in _desc.yaml, else as GitHub publishes them
        pinned_only = openmp_sources(spec, version, None)
        sources = pinned_only if pinned_only['files'] else openmp_sources(spec, version, release_assets(version))
        if not sources['files']:
            why = (f'LLVM {version} publishes no OpenMP sources this tool can check ({sources["why"]}) - pin their sha256 '
                   f'in openmp_runtime of tool/llvm/_desc.yaml, or use a release that ships the runtime')
            with open(marker, 'w', encoding = 'utf-8') as f:
                json.dump({'version': version, 'status': 'unavailable', 'why': why, 'spec': spec_key}, f, indent = 2)
            return {'return': 1, 'error': why}

        r = self._build_openmp(ctx, params, entry, home, clang, version, sources, spec.get('cmake_args') or [])
        if r['return'] > 0:
            return r

        with open(marker, 'w', encoding = 'utf-8') as f:
            json.dump({'version': version, 'status': 'built', 'sources': sources, 'placed': r['placed'],
                       'compiler': clang, 'spec': spec_key}, f, indent = 2)
        features['openmp'] = has_openmp(home)
        if not features['openmp']:
            return {'return': 1, 'error': f'the OpenMP runtime of LLVM {version} was built, but {home} still has no omp.h'}
        return {'return': 0}

    ############################################################
    def _build_openmp(self,
                      ctx: dict,
                      params: dict,
                      entry: str,
                      home: str,
                      clang: str,
                      version: str,
                      sources: dict,
                      cmake_args: list,
    ):
        """
        Download, check, configure, build and install the OpenMP runtime of a release with its own clang, then put
        it where a release with OpenMP keeps it. -> {'return': 0, 'placed': [...]}
        """
        c = ctx.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        clang_cpp = os.path.join(os.path.dirname(clang), 'clang++' + os.path.splitext(clang)[1])
        if not os.path.isfile(clang_cpp):
            return {'return': 1, 'error': f'the release has no {clang_cpp}'}

        # Where clang looks for the runtime: asked of clang itself
        asked = {}
        for key, flag in (('resource_dir', '-print-resource-dir'), ('triple', '-print-target-triple')):
            p = subprocess.run([clang, flag], capture_output = True, text = True, stdin = subprocess.DEVNULL)
            asked[key] = p.stdout.strip()
            if p.returncode != 0 or not asked[key]:
                return {'return': 1, 'error': f'{clang} {flag} failed: {(p.stderr or p.stdout).strip()}'}
        lib_dir = os.path.join(home, 'lib', asked['triple'])
        if not os.path.isdir(lib_dir):
            lib_dir = os.path.join(home, 'lib')                     # a release without per-target runtime folders

        tools = {}
        for key, name in (('cmake', 'cmake,e26c11ebb3dd40ca'), ('ninja', 'ninja,a3df3c45e9b04830')):
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                                'name': name, 'ctx': ctx, 'con': con, 'quiet': quiet, 'verbose': verbose})
            if r['return'] > 0:
                return {'return': 1, 'error': f'{key} could not be set up: {r.get("error")}'}
            tools[key] = r['path']

        if con:
            print ('')
            print (f'{space}INFO: LLVM {version} has no OpenMP runtime: building it from the sources of the release '
                   f'({", ".join(sources["files"].values())}) with {clang} ...')

        work = os.path.join(entry, 'openmp-src')
        shutil.rmtree(work, ignore_errors = True)
        os.makedirs(work)
        cwd = os.getcwd()
        os.chdir(entry)
        try:
            for folder, name in sources['files'].items():
                url = LLVM_RELEASES.format(version = version, filename = name)
                r = _download(self, ctx, {'control': {'con': con, 'quiet': quiet, 'verbose': verbose}}, url, 'openmp-src', name)
                if r['return'] > 0:
                    return {'return': 1, 'error': f'could not download {url}: {r.get("error")}'}
                digest = _sha256(r['path'])
                if digest != sources['sha256'][name]:
                    return {'return': 1, 'error': f'{name}: sha256 {digest} is not the expected {sources["sha256"][name]}'}
                into = work if sources['folders'] else os.path.join(work, folder)
                with tarfile.open(r['path']) as t:
                    kwargs = {'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}
                    t.extractall(into, members = list(safe_members(t, sources['folders'])), **kwargs)
                os.remove(r['path'])

            build, stage = os.path.join(work, 'build'), os.path.join(work, 'stage')
            configure = [tools['cmake'], '-S', os.path.join(work, 'openmp'), '-B', build, '-G', 'Ninja',
                         f'-DCMAKE_MAKE_PROGRAM={tools["ninja"]}', '-DCMAKE_BUILD_TYPE=Release',
                         f'-DCMAKE_C_COMPILER={clang}', f'-DCMAKE_CXX_COMPILER={clang_cpp}',
                         f'-DCMAKE_INSTALL_PREFIX={stage}', f'-DPython3_EXECUTABLE={sys.executable}'] + list(cmake_args)
            for log, args in (('configure', configure), ('build', [tools['cmake'], '--build', build]),
                              ('install', [tools['cmake'], '--install', build])):
                if verbose:
                    print (f'{space}RUN: ' + ' '.join(args))
                p = subprocess.run(args, capture_output = True, text = True, stdin = subprocess.DEVNULL)
                log_file = os.path.join(entry, f'openmp-{log}.log')
                with open(log_file, 'w', encoding = 'utf-8') as f:
                    f.write(p.stdout + p.stderr)
                if p.returncode != 0:
                    return {'return': 1, 'error': f'its {log} step failed ({log_file}): {(p.stderr or p.stdout).strip()[-1500:]}'}

            placed = place_openmp(stage, asked['resource_dir'], lib_dir)
        finally:
            os.chdir(cwd)
            shutil.rmtree(work, ignore_errors = True)

        if con:
            print (f'{space}INFO: the OpenMP runtime of LLVM {version}: {", ".join(placed)}')
        return {'return': 0, 'placed': placed}

    ############################################################
    def _resolve_release(self,
                         ctx: dict,
                         prefix: str,
                         filename_template: str,
    ):
        """
        Newest published LLVM release whose version starts with `prefix` ("22" -> "22.1.8", "22.1" -> "22.1.8").

        The versions come from the upstream tags (git ls-remote, the same source as cmd_get_versions);
        release candidates (22.1.0-rc1) and "22-init" tags are skipped. Newest first, the release whose
        prebuilt asset for this platform answers on GitHub is taken - a release tagged minutes ago may have
        no assets yet, and then the previous one is the right answer.

        Args:
            ctx (dict): The cMeta context (the git tool set up earlier is reused when present).
            prefix (str): Partial version, "22" or "22.1".
            filename_template (str): Asset file name with "{version}" in place of the version.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **version** (str): The resolved release, e.g. "22.1.8".
                - **filename** (str): The asset file name for that release.
                - **prefix** (str): The prefix that was resolved.
                - **candidates** (list): All matching releases, newest first.
        """

        _global = ctx['tasks']['global']

        git = (_global.get('git') or {}).get('qpath')
        if not git:
            git_path = shutil.which('git')
            git = self.cm.q(git_path) if git_path else None
        if not git:
            return {'return': 1,
                    'error': f'git is needed to list the LLVM releases for the partial version "{prefix}"; '
                             f'install git or pass an exact version (cx tool setup llvm --versions lists them)'}

        r = self.cm.utils.sys.run(f'{git} ls-remote --tags {LLVM_TAGS_REPO}', capture_output=True)
        if r['return'] > 0: return r
        if r['returncode'] != 0:
            return {'return': 1, 'error': f'listing the LLVM releases failed: {r.get("stderr", "").strip()}'}

        releases = set()
        for line in r['stdout'].splitlines():
            match = re.search(r'refs/tags/llvmorg-(\d+\.\d+\.\d+)$', line.strip())
            if match:
                releases.add(match.group(1))

        candidates = sorted((v for v in releases if v.startswith(prefix + '.')),
                            key=lambda v: [int(x) for x in v.split('.')], reverse=True)
        if not candidates:
            return {'return': 1,
                    'error': f'no published LLVM release matches version "{prefix}" '
                             f'(cx tool setup llvm --versions lists the available ones)'}

        for v in candidates[:5]:
            filename = filename_template.format(version=v)
            if self._asset_exists(LLVM_RELEASES.format(version=v, filename=filename)):
                return {'return': 0, 'version': v, 'filename': filename, 'prefix': prefix, 'candidates': candidates}

        return {'return': 1,
                'error': f'the newest LLVM releases matching "{prefix}" ({", ".join(candidates[:5])}) publish no '
                         f'prebuilt "{filename_template}" asset; pass an exact version'}

    ############################################################
    def _asset_exists(self,
                      url: str,
    ):
        """
        True when GitHub answers the release asset URL with a redirect (the asset exists) or any 2xx/3xx;
        False on HTTP 404. A network problem counts as True so that an offline check never hides a release
        that does exist - the download step reports the real error then.
        """

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        request = urllib.request.Request(url, method='HEAD')
        try:
            with opener.open(request, timeout=20) as response:
                return 200 <= response.status < 400
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            return 200 <= e.code < 400 or e.code >= 500
        except Exception:
            return True

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL llvm api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version = params.get('version')
        version_simple = params.get('version_simple')
        version_major = params.get('version_major')

        if not version:
            version = self.cdesc['default_version']
            version_simple = version
            version_major = version_simple[:2]

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install for LLVM can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        url = None
        filename = None

        if uname == 'windows':
            if uarch == 'amd64':
                uarch2 = 'x86_64'
                filename = f'clang+llvm-{version_simple}-{uarch2}-pc-windows-msvc.tar.xz'
        elif uname == 'linux':
            if uarch == 'amd64':
                uarch2 = 'X64'
                filename = f'LLVM-{version_simple}-Linux-{uarch2}.tar.xz'
        elif uname == 'darwin':
            if uarch == 'arm64':
                uarch2 = 'ARM64'
                filename = f'LLVM-{version_simple}-macOS-{uarch2}.tar.xz'

        if not filename:
            return {
                'return': 16, 
                'error': f'custom install for LLVM could not create download URL',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        # A partial version ("22", "22.1") is not a release tag: llvmorg-22/LLVM-22-Linux-X64.tar.xz does
        # not exist (HTTP 404). Resolve it to the newest published release that starts with it and whose
        # prebuilt asset for this platform is there (a freshly tagged release may not have assets yet).
        if version_simple.count('.') < 2:
            r = self._resolve_release(ctx, version_simple, filename_template=filename.replace(version_simple, '{version}'))
            if self.cm.catch_error(r): return r
            if con:
                print ('')
                print (f'{space}INFO: LLVM version "{version_simple}" resolved to the newest published release {r["version"]}')
            version_simple = r['version']
            version = version_simple
            filename = r['filename']

        url = LLVM_RELEASES.format(version=version_simple, filename=filename)

        directory = 'content'
        path_to_clang = os.path.join(os.getcwd(), directory, 'bin', 'clang' + _global['host']['vars']['file_ext_exe'])

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: LLVM download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_clang}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'url': url,
              'directory': directory,
              'env': env,
              'timeout': timeout,
              'con': con, 
              'quiet': quiet, 
              'verbose': verbose, 
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 1,
              'check_file': path_to_clang,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {
          'return': 0, 
          'install_cmd': None, 
          'found_path': path_to_clang, 
          'version': version,
        }


