"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A static C library built from a pinned upstream source release, shared by tool/lib-zlib,
tool/lib-zstd and tool/lib-jitterentropy (the libraries that a distribution's static OpenSSL may
need, see tool/lib-openssl):

    from tool_c393ba5c6fa14f66.api.common_static_lib import install_static_lib, detect_static_lib

    SPEC = {'name': 'zlib', 'lib': 'z', 'default_version': '1.3.2',
            'url': 'https://github.com/madler/zlib/releases/download/v{version}/zlib-{version}.tar.gz',
            'sha256': {'1.3.2': 'bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16'},
            'src_dir': 'zlib-{version}', 'sources': ['*.c'], 'headers': ['zlib.h', 'zconf.h'],
            'version': ('zlib.h', ['ZLIB_VERSION'])}

    def install(self, ctx, params, cmd=None, *misc):
        return install_static_lib(self, ctx, params, cmd, SPEC)

    def detect_versions(self, ctx, paths, params={}):
        return detect_static_lib(self, ctx, paths, params, SPEC)

What install_static_lib does, with no root and no build system:
  1. downloads the release with the download-file task and checks it against the SHA-256 pinned in
     the spec (--with.sha256=<digest> for a version the spec does not pin);
  2. unpacks it with Python's tarfile;
  3. compiles the sources with the C compiler of cMeta's compiler task - the one the program that
     asks for the library uses (its C counterpart for a C++ program), else the one the task selects -
     and archives the objects with that compiler's archiver (ar, llvm-ar);
  4. installs the archive and the public headers into the tool's cache entry
     (install/lib/lib<lib>.a, install/include/), with the source, its digest and the compiler in
     install/_source.json; the unpacked sources and the objects are removed.
detect_static_lib reads the version from an installed header and reports the include and lib folders
and the library name the way the other lib-* tools do, so setup-compile adds -I, -L and -l<lib>; a
static build gets the archive by its path (lib_names_static), which every linker takes as it is.

Linux and macOS (gcc or clang); on Windows install_static_lib returns a clear error.

SPEC keys:
  name             the upstream project
  lib              the library: lib<lib>.a, -l<lib>
  default_version  the version built when no exact version is asked for
  url              the source release URL template ({version}), or a list of them (mirrors)
  file             the name of the downloaded file (template; default: the URL's last part)
  sha256           {version: SHA-256 of the release file}
  src_dir          the source folder inside the archive (template)
  sources          source files or glob patterns, relative to src_dir
  include_dirs     include folders relative to src_dir (default: src_dir itself)
  defines          preprocessor definitions, NAME or NAME=VALUE
  cflags           compiler flags (default: -O2); -fPIC is added
  headers          the public headers, relative to src_dir, installed into include/
  version          (header, [macro, ...]): the version from these #defines of an installed header,
                   joined with "." (a quoted string value is taken as it is)
  windows          the message for Windows
"""

import glob
import json
import os
import re
import shutil
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor

from tool_c393ba5c6fa14f66.api.common_release import _sha256

# The C compiler tool of a C++ compiler tool (a C++ program that needs a static C library)
C_COMPILER_OF = {'gcc-cpp': 'gcc', 'clang-cpp': 'clang'}


def download(tool, ctx, params, url, directory, filename):
    """
    The file of the URL, with the download-file task. Without its progress bar: the engine's download
    fails on a response without a length (GitHub's archives of a tag) when it shows one.
    """
    c = params.get('control', {})
    path = os.path.join(os.getcwd(), directory, filename)
    r = tool.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'download-file,03fed13e2e0447cf',
                        'ctx': ctx, 'url': url, 'directory': directory, 'filename': filename,
                        'env': params.get('env'), 'timeout': params.get('timeout'), 'con': False,
                        'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False), 'unzip': False,
                        'check_file': path})
    if r['return'] > 0:
        return r
    return {'return': 0, 'path': path}


def release(spec, version):
    """The URLs (mirrors in order) and the file name of a version's source release."""
    urls = spec['url'] if isinstance(spec['url'], list) else [spec['url']]
    urls = [u.format(version = version) for u in urls]
    name = spec['file'].format(version = version) if spec.get('file') else urls[0].rsplit('/', 1)[-1]
    return urls, name


def header_version(text, macros):
    """The version from the #defines of a header: one quoted string, or numbers joined with "."."""
    parts = []
    for macro in macros:
        m = re.search(r'^\s*#\s*define\s+' + re.escape(macro) + r'\s+("([^"]*)"|\S+)', text, re.MULTILINE)
        if not m:
            return None
        parts.append(m.group(2) if m.group(2) is not None else m.group(1))
    return '.'.join(parts) if parts else None


def source_files(src_root, patterns):
    """The source files of the patterns (sorted per pattern): (files, error)."""
    files = []
    for pattern in patterns:
        found = sorted(f for f in glob.glob(os.path.join(src_root, pattern)) if os.path.isfile(f))
        if not found:
            return None, f'no source file matches "{pattern}" in {src_root}'
        files += [f for f in found if f not in files]
    return files, None


def object_name(src_root, src, ext):
    """A unique object file name for a source file: its path below src_root with "_" for the separators."""
    rel = os.path.relpath(src, src_root)
    return os.path.splitext(rel)[0].replace(os.sep, '_').replace('/', '_') + ext


def flag_args(flag, value):
    """A compiler flag of the compiler meta with its value as arguments: "-o " -> ["-o", v], "-I" -> ["-Iv"]."""
    if flag.endswith(' '):
        return [flag.strip(), value]
    return [flag + value]


def compile_args(cc, flags, src, obj, include_dirs, defines, cflags):
    """The arguments that compile one source file into an object file."""
    args = [cc, (flags.get('compile_to_obj') or '-c').strip()] + list(cflags)
    args += [(flags.get('d') or '-D') + d for d in defines]
    for d in include_dirs:
        args += flag_args(flags.get('include_path') or '-I', d)
    return args + [src] + flag_args(flags.get('obj_file') or '-o ', obj)


def archive_args(ar, flags, target, objs):
    """The arguments that archive the objects into a static library (ar rcs <target> <objects>)."""
    lib1 = flags.get('static_lib1')
    args = [ar] + ('rcs' if lib1 is None else lib1).split()
    return args + [(flags.get('static_lib2') or '') + target] + list(objs)


def safe_members(t):
    """The files and folders of a tar archive that stay inside the folder it is unpacked into."""
    for m in t.getmembers():
        parts = m.name.replace('\\', '/').split('/')
        if (m.isfile() or m.isdir()) and not m.name.startswith(('/', '\\')) and '..' not in parts and ':' not in parts[0]:
            yield m


def c_compiler(tool, ctx, params):
    """The C compiler of the pipeline (global "compiler-c"), set up with cMeta's compiler task if needed."""
    _global = ctx['tasks']['global']
    if 'compiler-c' not in _global:
        c = params.get('control', {})
        p = {'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'compiler,f3925b201c704bde',
             'ctx': ctx, 'lang': 'c', 'con': c.get('con', False), 'quiet': c.get('quiet', False),
             'verbose': c.get('verbose', False)}
        # A C++ program: the C compiler of the same family and version
        cpp = _global.get('compiler-cpp') or {}
        name = C_COMPILER_OF.get((cpp.get('tool') or {}).get('name'))
        if name:
            p['name'] = name
            if cpp.get('version'):
                p['version'] = cpp['version']
        r = tool.cm.access(p)
        if tool.cm.catch_error(r, fail16 = True):
            return r
    compiler = _global.get('compiler-c') or {}
    if not compiler.get('path'):
        return tool.cm.error('no C compiler was set up to build the static library')
    return {'return': 0, 'compiler': compiler}


def install_static_lib(tool, ctx, params, cmd, spec):
    """Builds the static library of the spec into the tool's cache entry (see the module docstring)."""
    _global = ctx['tasks']['global']
    c = params.get('control', {})
    con, verbose = c.get('con', False), c.get('verbose', False)
    space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''
    name, lib = spec['name'], spec['lib']

    if _global['host']['os']['uname'] == 'windows':
        return tool.cm.error(spec.get('windows') or f'lib{lib}: the static library is built on Linux and macOS')

    version = params.get('version_simple') or spec['default_version']
    sha256 = (params.get('with', {}).get('sha256') or spec['sha256'].get(version) or '').lower()
    if not sha256:
        return tool.cm.error(f'no SHA-256 is pinned for {name} {version}: give --with.sha256=<SHA-256 of its '
                             f'source release> (pinned: {", ".join(sorted(spec["sha256"]))})')

    r = c_compiler(tool, ctx, params)
    if r['return'] > 0:
        return r
    compiler = r['compiler']
    features = compiler.get('features', {})
    flags = features.get('flags', {})
    cc = compiler['path']
    ar = features.get('paths', {}).get('tool_lib') or shutil.which('ar')
    if not ar:
        return tool.cm.error(f'no archiver (ar) next to the C compiler {cc}')

    # The source release, checked against its SHA-256
    root = os.getcwd()
    urls, filename = release(spec, version)
    errors = []
    for url in urls:
        if con:
            print(f'{space}INFO: downloading {url} ...')
        r = download(tool, ctx, params, url, 'download', filename)
        if r['return'] == 0:
            break
        errors.append(f'{url}: {r.get("error")}')
    else:
        return tool.cm.error(f'could not download {name} {version}: ' + '; '.join(errors))
    archive = r['path']
    digest = _sha256(archive)
    if digest != sha256:
        os.remove(archive)
        return tool.cm.error(f'SHA-256 mismatch for {filename}: expected {sha256}, got {digest}')

    src_parent = os.path.join(root, 'src')
    shutil.rmtree(src_parent, ignore_errors = True)
    with tarfile.open(archive) as t:
        kwargs = {'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}
        t.extractall(src_parent, members = list(safe_members(t)), **kwargs)
    src_root = os.path.join(src_parent, spec['src_dir'].format(version = version))
    srcs, error = source_files(src_root, spec['sources'])
    if error:
        return tool.cm.error(error)

    # Compile in parallel, then archive
    obj_dir = os.path.join(root, 'obj')
    shutil.rmtree(obj_dir, ignore_errors = True)
    os.makedirs(obj_dir)
    ext = features.get('vars', {}).get('file_ext_obj') or '.o'
    include_dirs = [os.path.join(src_root, d) for d in spec.get('include_dirs', ['.'])]
    cflags = list(spec.get('cflags', ['-O2'])) + ['-fPIC']
    jobs = [(src, os.path.join(obj_dir, object_name(src_root, src, ext))) for src in srcs]
    if con:
        print(f'{space}INFO: building lib{lib}.a from {name} {version} ({len(jobs)} sources) with {cc} ...')

    def build(job):
        args = compile_args(cc, flags, job[0], job[1], include_dirs, spec.get('defines', []), cflags)
        return job[0], args, subprocess.run(args, capture_output = True, text = True, cwd = obj_dir)

    with ThreadPoolExecutor(max_workers = min(16, os.cpu_count() or 2)) as pool:
        for src, args, p in pool.map(build, jobs):
            if verbose:
                print(f'{space}RUN: ' + ' '.join(args))
            if p.returncode != 0:
                return tool.cm.error(f'compiling {os.path.relpath(src, src_root)} failed:\n{" ".join(args)}\n'
                                     f'{(p.stderr or p.stdout).strip()[-2000:]}')

    lib_dir = os.path.join(root, 'install', 'lib')
    include_dir = os.path.join(root, 'install', 'include')
    shutil.rmtree(os.path.join(root, 'install'), ignore_errors = True)
    os.makedirs(lib_dir)
    os.makedirs(include_dir)
    target = os.path.join(lib_dir, f'lib{lib}.a')
    args = archive_args(ar, flags, target, [os.path.basename(o) for _, o in jobs])
    p = subprocess.run(args, capture_output = True, text = True, cwd = obj_dir)
    if p.returncode != 0 or not os.path.isfile(target):
        return tool.cm.error(f'archiving lib{lib}.a failed:\n{" ".join(args)}\n{(p.stderr or p.stdout).strip()[-2000:]}')

    for h in spec['headers']:
        shutil.copy2(os.path.join(src_root, h), os.path.join(include_dir, os.path.basename(h)))
    with open(os.path.join(root, 'install', '_source.json'), 'w', encoding = 'utf-8') as f:
        json.dump({'name': name, 'version': version, 'url': url, 'sha256': sha256, 'compiler': cc,
                   'compiler_version': compiler.get('version'), 'defines': spec.get('defines', []),
                   'cflags': cflags}, f, indent = 2)

    shutil.rmtree(src_parent, ignore_errors = True)
    shutil.rmtree(obj_dir, ignore_errors = True)
    os.remove(archive)

    return {'return': 0, 'install_cmd': None, 'found_path': os.path.join(include_dir, spec['version'][0])}


def detect_static_lib(tool, ctx, paths, params, spec):
    """The version, include and lib folders and library name of an installed static library."""
    found = {}
    for path in paths:
        try:
            with open(path, encoding = 'utf-8', errors = 'replace') as f:
                version = header_version(f.read(), spec['version'][1])
        except OSError:
            continue
        include = os.path.dirname(path)
        home = os.path.dirname(include)
        lib_dir = os.path.join(home, 'lib')
        archive = os.path.join(lib_dir, f'lib{spec["lib"]}.a')
        if not version or not os.path.isfile(archive):
            continue
        features = {
            'paths': {'root': home, 'qroot': tool.cm.q(home),
                      'include': include, 'qinclude': tool.cm.q(include), 'includes': [include],
                      'lib': lib_dir, 'qlib': tool.cm.q(lib_dir), 'libs': [lib_dir], 'libs_static': [lib_dir]},
            'lib_names': [spec['lib']],
            # a static build gets the archive by its path: named, a link without -static would take a
            # shared library of that name found first (setup-compile, tool/lib-openssl)
            'lib_names_static': [archive],
            'static_lib': archive,
        }
        found[path] = {'output': version, 'features': features}
    return {'return': 0, 'found_paths_with_versions': found}
