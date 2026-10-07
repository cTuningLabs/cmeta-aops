"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The stamp of a program's build folder: what the build in it was made for. compile-and-run-program
writes .cmeta-build-stamp.json after a successful compile (the targets, the host, the compiler, the
compile parameters that change the output, the program) and refuses to reuse or rebuild in a folder
whose stamp differs, unless --recompile was asked for or --clean wiped it: a folder configured for
one target or compiler was silently reused for another before (a CMake build keeps its cache, so a
host build was pushed to an Android device). A folder without a stamp, made before this, is used as
before and gets a stamp.
"""

import hashlib
import json
import os
import time

STAMP_FILE = '.cmeta-build-stamp.json'

# The files whose change makes a build stale (since 0.43.3 the stamp records their digests and
# compile-and-run-program recompiles when one differs): the declared sources, and every code or build
# file under the program's source folder - headers, CMake lists, Cargo/Go manifests, scripts. Data files
# and binaries are left out; so are hidden and tmp folders. A tree beyond the limits is not tracked.
SOURCE_SUFFIXES = ('.c', '.cc', '.cpp', '.cxx', '.cu', '.h', '.hh', '.hpp', '.hxx', '.cuh', '.inl', '.inc', '.def',
                   '.rs', '.go', '.py', '.pyx', '.f', '.f90', '.m', '.mm', '.swift', '.s', '.asm', '.cl', '.metal',
                   '.glsl', '.hlsl', '.java', '.kt', '.js', '.ts', '.sh', '.bat', '.cmake', '.toml', '.mod')
SOURCE_NAMES = ('CMakeLists.txt', 'Makefile', 'makefile', 'GNUmakefile', 'Cargo.lock', 'go.sum', 'build.gradle',
                'meson.build')
SKIPPED_DIRS = ('__pycache__', 'build', 'node_modules', 'target', '.git')
MAX_SOURCE_FILES = 2000
MAX_SOURCE_BYTES = 64 << 20


def source_digests(src_path, src_file_names = None):
    """
    {relative path: sha256} of a program's sources: the declared source files and the code/build files
    under src_path (recursive; hidden, tmp* and build folders left out). None when src_path is not a
    folder or the tree is beyond MAX_SOURCE_FILES - then nothing is compared.
    """
    if not src_path or not os.path.isdir(src_path):
        return None
    files = {}
    for name in src_file_names or []:
        p = os.path.join(src_path, str(name))
        if os.path.isfile(p):
            files[os.path.relpath(p, src_path).replace(os.sep, '/')] = p
    for root, dirs, names in os.walk(src_path):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not d.startswith('tmp') and d not in SKIPPED_DIRS)
        for n in sorted(names):
            if n in SOURCE_NAMES or os.path.splitext(n)[1].lower() in SOURCE_SUFFIXES:
                p = os.path.join(root, n)
                files[os.path.relpath(p, src_path).replace(os.sep, '/')] = p
                if len(files) > MAX_SOURCE_FILES:
                    return None
    out = {}
    for rel in sorted(files):
        p = files[rel]
        try:
            if os.path.getsize(p) > MAX_SOURCE_BYTES:
                continue
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
            out[rel] = h.hexdigest()
        except OSError:
            continue
    return out


def sources_changed(stamp, digests):
    """
    The sources that differ from the stamp's record - changed, added or removed files, as relative
    paths - or [] when they agree. None when there is nothing to compare: the stamp recorded no
    sources (a build made before 0.43.3) or the digests are None.
    """
    if not stamp or digests is None or not isinstance(stamp.get('sources'), dict):
        return None
    old = stamp['sources']
    return sorted(k for k in set(old) | set(digests) if old.get(k) != digests.get(k))

# The compile parameters recorded in the stamp (what a build is, not how it is reported) ...
COMPILE_KEYS = ('static', 'debug_info', 'fastest', 'openmp', 'profile', 'profile_cuda', 'profile_cuda_kernels', 'lib')
# ... and the ones a folder is refused for: the static/dynamic kind and library/program. Optimization,
# debug and profiling flags change the binary but are switched on one folder in everyday use
# (--compile.fastest, then a plain run), so they are recorded, not compared
COMPARED_COMPILE_KEYS = ('static', 'lib')


def normalize_compile(compile_params, keys = COMPILE_KEYS):
    """The compile parameters of `keys` that are set, as lowercase strings (None, False, "False", "0"
    and "" count as not set), so that a stamp and a request compare alike."""
    out = {}
    for k in keys:
        v = (compile_params or {}).get(k)
        if v in (None, '', False) or str(v).strip().lower() in ('false', 'none', '0', ''):
            continue
        out[k] = str(v).strip().lower()
    return out


def compiler_identity(compiler_result):
    """name, version and path of a resolved compiler (the result of task/compiler in the global context)."""
    if not compiler_result:
        return None
    identity = {'name': (compiler_result.get('tool') or {}).get('name') or compiler_result.get('name'),
                'version': compiler_result.get('version'),
                'path': compiler_result.get('path')}
    return identity if any(identity.values()) else None


def make_stamp(program, uid, compute, host, compiler = None, compile_params = None, android = None, sources = None):
    return {'version': 1,
            'program': program,
            'uid': uid,
            'compute': sorted(str(c) for c in (compute or [])),
            'host': host,
            'compiler': compiler,
            'compile': normalize_compile(compile_params),
            'android': {k: v for k, v in (android or {}).items() if v} or None,
            'sources': sources if isinstance(sources, dict) else None,
            'time': time.strftime('%Y-%m-%dT%H:%M:%S')}


def read_stamp(target_path):
    """The stamp of a build folder, or None (no file, or not readable)."""
    path = os.path.join(target_path, STAMP_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding = 'utf-8') as f:
            stamp = json.load(f)
        return stamp if isinstance(stamp, dict) else None
    except (OSError, ValueError):
        return None


def write_stamp(target_path, stamp):
    """Writes the stamp; returns None, or the error text when the folder is not writable."""
    try:
        os.makedirs(target_path, exist_ok = True)
        with open(os.path.join(target_path, STAMP_FILE), 'w', encoding = 'utf-8', newline = '\n') as f:
            json.dump(stamp, f, indent = 1, sort_keys = True)
        return None
    except (OSError, TypeError) as e:
        return str(e)


def differences(stamp, compute = None, host = None, compiler = None, compile_params = None, android = None):
    """
    What the request differs in from the stamp: a list of (what, built for, requested). Only the facts
    given (not None) are compared, so a request whose compiler is not resolved yet compares the rest.
    The compiler compares by name and version (a path alone changes with a reinstall of the same tool);
    the compile parameters by COMPARED_COMPILE_KEYS only, both sides normalized the same way.
    """
    diffs = []
    if compute is not None and sorted(str(c) for c in compute) != list(stamp.get('compute') or []):
        diffs.append(('targets', ','.join(stamp.get('compute') or []) or '-', ','.join(sorted(str(c) for c in compute)) or '-'))
    if host is not None and stamp.get('host') and host != stamp.get('host'):
        diffs.append(('host', stamp.get('host'), host))
    if compiler is not None and stamp.get('compiler'):
        old, new = stamp['compiler'], compiler
        for key in ('name', 'version'):
            if new.get(key) is not None and old.get(key) is not None and str(new[key]) != str(old[key]):
                diffs.append((f'compiler {key}', old.get(key), new.get(key)))
                break
    if compile_params is not None:
        old = normalize_compile(stamp.get('compile') or {}, COMPARED_COMPILE_KEYS)
        new = normalize_compile(compile_params, COMPARED_COMPILE_KEYS)
        if old != new:
            diffs.append(('compile parameters', _fmt(old), _fmt(new)))
    if android is not None and stamp.get('android'):
        new = {k: v for k, v in android.items() if v}
        for key in ('abi', 'serial'):
            if new.get(key) and stamp['android'].get(key) and new[key] != stamp['android'][key]:
                diffs.append((f'android {key}', stamp['android'][key], new[key]))
    return diffs


def _fmt(d):
    return ','.join(f'{k}={v}' for k, v in sorted((d or {}).items())) or 'defaults'


def built_for(stamp):
    """'cpu with clang 20.1.0 (static=true)'"""
    text = ','.join(stamp.get('compute') or []) or 'unknown targets'
    c = stamp.get('compiler') or {}
    if c.get('name'):
        text += f" with {c['name']}" + (f" {c['version']}" if c.get('version') else '')
    compared = normalize_compile(stamp.get('compile') or {}, COMPARED_COMPILE_KEYS)
    if compared:
        text += f" ({_fmt(compared)})"
    return text


def refusal_message(target_path, stamp, diffs):
    """
    "<folder>" was built for cpu with clang 20.1.0; this run asks for android-cpu (targets):
    use --target_tmp=<name> for another build folder, --recompile to rebuild in it, or --clean to start over
    """
    asks = '; '.join(f'{new} ({what})' for what, old, new in diffs)
    return (f'"{target_path}" was built for {built_for(stamp)}; this run asks for {asks}: '
            f'use --target_tmp=<name> for another build folder, --recompile to rebuild in it, or --clean to start over')
