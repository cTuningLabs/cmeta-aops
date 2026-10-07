"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The provenance record of a program run: what was requested, what cMeta resolved, what the build is
made of, what the process loaded, and whether they agree. compile-and-run-program writes
provenance.json into the build folder after every run (next to .cmeta-build-stamp.json). The record
is passive by default: it reads the binary's headers (binary_deps.py) and the context the driver
already holds, changes no command and no environment, and a failure to write it is a warning, never
a failed run.

Modes (`cx program run <program> --provenance=<mode>`):
  on      (default) the record with the inspector's resolution of the binary's dependencies
  off     no record
  loaded  also what the process really loaded - Linux: LD_DEBUG=libs into a file per process,
          macOS: DYLD_PRINT_LIBRARIES into a file; Windows and Android: the resolution only
  strict  as `on`, and a failed error-level check fails the run
  When the run names no mode, the environment sets it: CMETA_PROVENANCE when set (a CI job exports
  CMETA_PROVENANCE=strict), else `strict` inside a test session (CMETA_TEST_SESSION, which
  "cx task run test-session --start" prints for the shell), else `on`. Inside a test session the
  record also joins the session's attachments, with a note (session_attachment_name, session_note).

A loaded library that no tool claims but that is a compiler's own runtime (libgomp, libstdc++,
libgcc_s; libomp, libc++; libiomp5; vcomp140, msvcp140) is attributed to the compiler of the run
that owns it, with `role: runtime` (attribute_runtime: GCC, Clang and Intel are asked with
-print-file-name, MSVC's DLLs are known by name and must lie in the Visual Studio installation or
in System32, a compiler installed in a folder of its own owns what lies under it).

A library inside a Python package (a wheel's own CUDA runtime, ONNX Runtime's providers, numpy's
OpenBLAS) is attributed to the pip-<package> tool of the run that installed its distribution,
directly or as a dependency (attribute_wheel: the distribution from its RECORD, the dependency path
from the METADATA of the venv's distributions), and the record names the distribution (`dist`).

Checks (the `checks` list of the record; `ok` = no failed error):
  static       with compile.static: CPU - the binary is fully static (Windows: only the OS runtime
               and the documented OpenMP DLL); CUDA - no shared library beyond the OS runtime, the C++
               runtime, the driver and NVIDIA's shared libraries (libcudart, libgomp, libcrypto, ...
               present are violations). Error when static was requested, warning when it is a default.
  origin       a library that belongs to a resolved tool (its lib names) comes from that tool's
               folders - libcudart from the resolved toolkit, libcrypto from the resolved OpenSSL.
               Error when the tool was requested with --use, warning otherwise.
  version      every --use.<tool>.version matches the resolved version (error).
  wheel        a --use.nvcc|cuda.version (or lib-cudnn) cannot apply to a CUDA runtime (cuDNN) that a
               wheel brought along (libcudart from nvidia-cuda-runtime, loaded by a Python program): error.
  toolchain    a Go or Rust binary says which toolchain built it (Go buildinfo; rustc's version string or
               /rustc/<commit>/ paths): another one than the resolved compiler is a warning, an error
               when that compiler's version was requested with --use.
  accelerator  when the program reports accelerators (available/required), a required one that was
               not available is an error; an optional one missing is info.
  info         the toolchain, the frameworks of a Python run (runtime.frameworks: the distributions behind
               the loaded wheel libraries and the pip tools' packages, with the CUDA a wheel was built for),
               the driver and GPU, Python.
"""

import glob
import json
import os
import posixpath
import re
import subprocess
import sys
import time

try:
    from . import binary_deps
except ImportError:
    import importlib.util
    _spec = importlib.util.spec_from_file_location('cmeta_aops_binary_deps', os.path.join(os.path.dirname(__file__), 'binary_deps.py'))
    binary_deps = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(binary_deps)

FORMAT = 1
RECORD_FILE = 'provenance.json'
STAMP_FILE = '.cmeta-build-stamp.json'
LD_DEBUG_FILE = 'tmp-cmeta-ld-debug'        # glibc appends .<pid>
DYLD_LOG_FILE = 'tmp-cmeta-dyld.log'
MODES = ('on', 'off', 'loaded', 'strict')
MODE_ENV = 'CMETA_PROVENANCE'                # the default mode when a run names none
SESSION_ENV = 'CMETA_TEST_SESSION'           # the test session of this shell (cx task run test-session --start prints it):
                                             # the record joins its attachments, and the default mode is strict

# The policy of a static build, by the normalized library name (library_key): what may stay shared
CXX_RUNTIME = ('stdc++', 'gcc_s', 'c++', 'c++abi', 'unwind')
NVIDIA_DRIVER = ('cuda', 'nvcuda')                # libcuda.so / nvcuda.dll (exact names); libnvidia-* by prefix
NVIDIA_SHARED = ('cublas', 'cublaslt', 'cudnn', 'nvrtc', 'cufft', 'curand', 'cusparse', 'cusolver', 'nvjitlink',
                 'cutensor', 'nccl', 'nvjpeg', 'npp', 'nvtx', 'nvperf', 'cupti')
WINDOWS_OPENMP = ('omp', 'vcomp')                 # no static OpenMP runtime exists on Windows (documented)
# Libraries that a static build must not load: a static runtime or archive exists for each of them
STATIC_MUST_BE_IN = ('cudart', 'gomp', 'crypto', 'ssl', 'z', 'zstd', 'jitterentropy', 'xopenme', 'polybench')

# The global context keys that are not tools
NOT_TOOLS = ('host', 'init', 'runner', 'target', 'enable-long-paths-win')


###################################################################################################
def mode_of(value, env = None):
    """
    'on' (the default; also None, True, yes), 'off' (False, no, none), 'loaded' or 'strict'.
    When the run names no mode (None), the environment sets it: CMETA_PROVENANCE when it is set
    (a CI job exports CMETA_PROVENANCE=strict), else 'strict' inside a test session
    (CMETA_TEST_SESSION, exported by "cx task run test-session --start"), else 'on'.
    Anything else raises ValueError with the accepted values (`env` replaces os.environ in tests).
    """
    source = f'--provenance={value}'
    if value is None:
        environment = os.environ if env is None else env
        value = environment.get(MODE_ENV)
        if value is None or str(value).strip() == '':
            return 'strict' if str(environment.get(SESSION_ENV) or '').strip() else 'on'
        source = f'{MODE_ENV}={value}'
    if value is True:
        return 'on'
    if value is False:
        return 'off'
    text = str(value).strip().lower()
    if text in ('', 'true', 'yes', 'on', '1'):
        return 'on'
    if text in ('false', 'no', 'off', '0', 'none'):
        return 'off'
    if text in MODES:
        return text
    raise ValueError(f'{source}: expected on, off, loaded or strict')


def loader_env(uname, target_path):
    """The environment that makes the dynamic loader log what it loads (mode `loaded`)."""
    if uname == 'linux':
        return {'LD_DEBUG': 'libs', 'LD_DEBUG_OUTPUT': os.path.join(target_path, LD_DEBUG_FILE)}
    if uname == 'darwin':
        return {'DYLD_PRINT_LIBRARIES': '1', 'DYLD_PRINT_TO_FILE': os.path.join(target_path, DYLD_LOG_FILE)}
    return {}


def loader_prefix(uname, target_path):
    """
    The same as loader_env(), as shell assignments in front of the command. macOS strips DYLD_*
    from the environment of the system shell that runs a command (System Integrity Protection),
    so the variables must be set by the shell itself, in the command line.
    """
    env = loader_env(uname, target_path)
    return ''.join(f'{k}="{v}" ' if ' ' in v else f'{k}={v} ' for k, v in env.items())


def loader_log_files(target_path):
    return sorted(glob.glob(os.path.join(glob.escape(target_path), LD_DEBUG_FILE + '.*')) +
                  glob.glob(os.path.join(glob.escape(target_path), DYLD_LOG_FILE)))


def clear_loader_logs(target_path):
    for f in loader_log_files(target_path):
        try:
            os.remove(f)
        except OSError:
            pass


def parse_ld_debug(text):
    """
    The libraries a process loaded, from glibc's LD_DEBUG=libs output: one "calling init: <path>"
    line per library (the executable itself included). Order kept, duplicates dropped.
    """
    out = []
    for line in text.splitlines():
        m = re.search(r'calling init:\s*(\S.*?)\s*$', line)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def parse_dyld_log(text):
    """
    The libraries dyld logged: "dyld[<pid>]: <UUID> <path>" (dyld 4), "dyld[<pid>]: <path>" or bare
    paths on older systems. Order kept, duplicates dropped.
    """
    out = []
    for line in text.splitlines():
        line = re.sub(r'^\s*dyld\[\d+\]:\s*', '', line.strip())
        line = re.sub(r'^<[0-9A-Fa-f-]+>\s*', '', line)
        if line.startswith('/') and line not in out:
            out.append(line)
    return out


def loader_log_libraries(target_path, uname):
    """(paths, processes) from the loader logs of the last run, or (None, 0) when there are none."""
    files = loader_log_files(target_path)
    if not files:
        return None, 0
    paths = []
    for f in files:
        try:
            with open(f, encoding = 'utf-8', errors = 'replace') as h:
                text = h.read()
        except OSError:
            continue
        for p in (parse_dyld_log(text) if f.endswith(DYLD_LOG_FILE) else parse_ld_debug(text)):
            if p not in paths:
                paths.append(p)
    processes = len([f for f in files if not f.endswith(DYLD_LOG_FILE)]) or (1 if paths else 0)
    return paths, processes


###################################################################################################
def library_key(name_or_path):
    """
    The library behind a file name: libcublasLt.so.13 -> cublaslt, cudart64_13.dll -> cudart,
    libcrypto-3-x64.dll -> crypto, libstdc++.so.6 -> stdc++, ssl_static -> ssl, $ws2_32 -> ws2_32.
    """
    base = str(name_or_path).replace('\\', '/').rsplit('/', 1)[-1].strip().lower().lstrip('$')   # a record of either OS, read on either
    for ext in ('.so', '.dylib', '.dll'):
        i = base.find(ext)
        if i > 0:
            base = base[:i]
            break
    base = re.sub(r'(\.\d+)+$', '', base)                            # libcrypto.3 (Mach-O), libfoo.1.2
    if base.startswith('lib') and len(base) > 3:
        base = base[3:]
    base = re.sub(r'_static$', '', base)
    base = re.sub(r'64_\d+(_\d+)*$', '', base)                       # cudart64_13, nvrtc64_120_0
    base = re.sub(r'-\d+([.-]\d+)*(-x64|-x86|-arm64)?$', '', base)   # libcrypto-3-x64
    return base


def is_system(name_or_path, uname):
    """
    binary_deps.is_system_library when it works (plus: on macOS everything under /usr/lib is Apple's,
    System Integrity Protection lets nobody else write there), else a small heuristic of the same meaning.
    """
    if uname == 'darwin' and str(name_or_path).startswith(('/usr/lib/', '/System/')):
        return True
    try:
        return bool(binary_deps.is_system_library(name_or_path, uname))
    except Exception:
        key = library_key(name_or_path)
        base = str(name_or_path).replace('\\', '/').rsplit('/', 1)[-1].lower()
        if uname == 'windows':
            return key in ('kernel32', 'kernelbase', 'user32', 'gdi32', 'advapi32', 'shell32', 'ole32', 'oleaut32',
                           'ws2_32', 'ntdll', 'bcrypt', 'crypt32', 'msvcrt', 'ucrtbase', 'secur32', 'rpcrt4') \
                or base.startswith(('api-ms-win-', 'ext-ms-', 'vcruntime', 'msvcp', 'ucrtbase'))
        if uname == 'darwin':
            return str(name_or_path).startswith(('/usr/lib/libSystem', '/usr/lib/libc++', '/usr/lib/libobjc',
                                                 '/usr/lib/system/', '/System/Library/')) or base.startswith(('libsystem', 'libc++', 'libobjc'))
        return base.startswith(('ld-linux', 'ld-musl', 'linux-vdso', 'linux-gate', 'libc.so', 'libc-2.', 'libm.so',
                                'libdl.so', 'libpthread.so', 'librt.so', 'libresolv.so', 'libutil.so', 'libnsl.so'))


def static_allowed(name_or_path, uname, compute, system):
    """Whether a shared library may stay in a static build for these targets (the documented policy)."""
    key = library_key(name_or_path)
    if system:
        return True
    if uname == 'windows' and key.startswith(WINDOWS_OPENMP):
        return True
    if 'cuda' in (compute or []):
        if key in CXX_RUNTIME or key in ('cuda', 'nvcuda') or key.startswith(('nvidia-', 'nvidia_')) or key.startswith(NVIDIA_SHARED):
            return True
    return False


###################################################################################################
def entry_uid(tool):
    """The cache entry of a resolved tool (the UID at the end of its folder name), or None."""
    folder = tool.get('path_cmeta_cache') or ''
    base = os.path.basename(os.path.normpath(folder)) if folder else ''
    uid = base.rsplit('--', 1)[-1] if '--' in base else ''
    return uid if re.fullmatch(r'[0-9a-f]{16}', uid) else None


def _dirs(value):
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str) and v]
    return []


def tool_roots(tool):
    """The folders a tool's files live in: its cache entry, its binary's folder, its lib/bin paths."""
    roots = []
    for d in [tool.get('path_cmeta_cache'), tool.get('path_bin')] + \
             ([os.path.dirname(tool['path'])] if isinstance(tool.get('path'), str) and tool['path'] else []):
        if d:
            roots.append(d)
    paths = (tool.get('features') or {}).get('paths') or {}
    if isinstance(paths, dict):
        for k, v in paths.items():
            if k.startswith('q'):
                continue
            for d in _dirs(v):
                if os.path.splitext(d)[1].lower() in ('.exe', '.dll', '.so', '.dylib', '.a', '.lib', '.h'):
                    d = os.path.dirname(d)
                roots.append(d)
    out = []
    for r in roots:
        n = os.path.normcase(os.path.normpath(r))
        if n not in out:
            out.append(n)
    return out


def _real(path):
    """A path with its symbolic links resolved, normalized for comparison (/lib -> /usr/lib on merged-usr systems)."""
    try:
        path = os.path.realpath(path)
    except (OSError, ValueError):
        pass
    return os.path.normcase(os.path.normpath(path))


def under(path, roots):
    """Whether `path` lies in one of `roots`; both sides are compared with their links resolved too."""
    if not path:
        return False
    candidates = {os.path.normcase(os.path.normpath(path)), _real(path)}
    for r in roots:
        for root in {r, _real(r)}:
            root = root.rstrip('\\/')
            for p in candidates:
                if p == root or p.startswith(root + os.sep) or p.startswith(root + '/'):
                    return True
    return False


def _is_library_file(path):
    """Whether a path names a library file: libomp.so, libomp.so.5, libomp.dylib, omp.dll, libomp.a, omp.lib."""
    base = str(path or '').replace('\\', '/').rsplit('/', 1)[-1].lower()     # a record of either OS, read on either
    return bool(re.search(r'[^./].*\.(so(\.\d+)*|dylib|dll|a|lib)$', base))


def tool_library_keys(tool, key = None, broad = False):
    """
    The libraries a resolved tool provides, as library_key values: its lib names, the library file
    it was resolved to (lib-openmp: libomp.so), plus the CUDA runtime for nvcc and lib-cuda. With
    `broad` (attribution, not checking) the toolkit also claims NVIDIA's shared libraries that live
    in its folders (cublas, cufft, nvrtc, ...).
    """
    f = tool.get('features') or {}
    keys = []
    for k in ('lib_names', 'lib_names_static'):
        for name in _dirs(f.get(k)):
            if name.startswith('$'):
                continue
            lk = library_key(name)
            if lk and lk not in keys:
                keys.append(lk)
    # a tool resolved to a library file names that library (lib-openmp: .../libomp.so)
    path = tool.get('path')
    if isinstance(path, str) and _is_library_file(path):
        lk = library_key(path)
        if lk and lk not in keys:
            keys.append(lk)
    if key in ('nvcc', 'lib-cuda'):
        keys += [k for k in ('cudart',) + (NVIDIA_SHARED if broad and key == 'nvcc' else ()) if k not in keys]
    return keys


def collect_resolved(global_ctx):
    """Every tool of the run (the global context entries with a path or a version), trimmed."""
    out = {}
    for key, v in (global_ctx or {}).items():
        if not isinstance(v, dict) or key in NOT_TOOLS or key.startswith('target'):
            continue
        if not (v.get('path') or v.get('version')):
            continue
        f = v.get('features') or {}
        tool = (v.get('tool') or {}).get('name') if isinstance(v.get('tool'), dict) else None
        entry = {'name': tool or key, 'version': v.get('version'), 'path': v.get('path'), 'path_bin': v.get('path_bin'),
                 'entry': entry_uid(v)}
        with_ = (v.get('_params') or {}).get('with') if isinstance(v.get('_params'), dict) else None
        features = {}
        for k in ('lib_names', 'lib_names_static', 'static_unavailable'):
            if k in f:
                features[k] = f[k]
        paths = f.get('paths') if isinstance(f.get('paths'), dict) else {}
        for k in ('dynamic_lib', 'dynamic_libs', 'found_dynamic_lib_paths', 'lib', 'bin'):
            if k in paths:
                features['paths.' + k] = paths[k]
        if isinstance(with_, dict) and 'static' in with_:
            features['static'] = with_['static']
        if features:
            entry['features'] = features
        if v.get('requested_version'):
            entry['requested_version'] = v['requested_version']
        out[key] = entry
    return out


###################################################################################################
# A library of a Python package: the pip tool that installed the distribution the file belongs to.
# A wheel brings its own libraries (ONNX Runtime's CUDA provider, the nvidia-* runtime wheels,
# numpy's OpenBLAS) into the venv of the program, which lies in the program's build folder - no tool
# names them and no tool's cache entry holds them. The venv itself knows: every distribution's
# RECORD lists its files and its METADATA the distributions it requires, and the pip-<package> tool
# of the run records the package it installed. So a file is attributed to the pip tool whose package
# is the file's distribution, or requires it, directly or through other distributions
# (nvidia-cudnn-cu13 <- onnxruntime-gpu[cuda] -> pip-onnxruntime). The nearest tool wins; a file of
# a distribution that no tool of the run pulled stays unattributed.
_DIST_INDEX = {}


def norm_dist(name):
    """A distribution name as pip compares them (PEP 503): lower case, runs of -_. as one dash."""
    return re.sub(r'[-_.]+', '-', str(name or '').strip().lower())


def site_packages_of(path):
    """The site-packages folder a file lies in (as written in the path), or None."""
    s = str(path or '')
    low = s.replace('\\', '/').lower()
    i = low.rfind('/site-packages/')
    if i < 0:
        return None
    return s[:i + len('/site-packages')]


def dist_index(site_packages):
    """
    The distributions of a site-packages folder, from their .dist-info: {'files': {relative path
    (normalized): dist}, 'requires': {dist: [dist]}, 'versions': {dist: version}}; read once per folder.
    """
    key = os.path.normcase(os.path.normpath(site_packages))
    if key in _DIST_INDEX:
        return _DIST_INDEX[key]
    files, requires, versions = {}, {}, {}
    try:
        names = os.listdir(site_packages)
    except OSError:
        names = []
    for n in names:
        if not n.lower().endswith('.dist-info'):
            continue
        folder = os.path.join(site_packages, n)
        name, version, reqs = None, None, []
        try:
            with open(os.path.join(folder, 'METADATA'), encoding = 'utf-8', errors = 'replace') as f:
                for line in f:
                    if not line.strip():                 # the headers end at the first empty line
                        break
                    if line.startswith('Name:'):
                        name = line[5:].strip()
                    elif line.startswith('Version:'):
                        version = line[8:].strip()
                    elif line.startswith('Requires-Dist:'):
                        m = re.match(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)', line[14:])
                        if m:
                            reqs.append(norm_dist(m.group(1)))
        except OSError:
            pass
        dist = norm_dist(name or n[:-len('.dist-info')].split('-')[0])
        versions[dist] = version
        requires[dist] = reqs
        try:
            with open(os.path.join(folder, 'RECORD'), encoding = 'utf-8', errors = 'replace') as f:
                for line in f:
                    rel = line.split(',')[0].strip()
                    if rel:
                        files[os.path.normcase(os.path.normpath(rel))] = dist
        except OSError:
            pass
    _DIST_INDEX[key] = {'files': files, 'requires': requires, 'versions': versions}
    return _DIST_INDEX[key]


def wheel_dist(path):
    """The distribution a file under a site-packages folder belongs to (its RECORD), with the folder; (None, None) outside one."""
    sp = site_packages_of(path)
    if not sp:
        return None, None
    idx = dist_index(sp)
    candidates = []
    for p in (str(path), _real(path)):
        try:
            candidates.append(os.path.normcase(os.path.normpath(os.path.relpath(p, sp))))
        except ValueError:
            pass
    for rel in candidates:
        if rel in idx['files']:
            return idx['files'][rel], sp
    return None, sp


def _dist_distance(requires, start, goal, limit = 16):
    """How many Requires-Dist steps lead from one distribution to another (0 = the same), or None."""
    if start == goal:
        return 0
    seen, frontier, depth = {start}, [start], 0
    while frontier and depth < limit:
        depth += 1
        nxt = []
        for d in frontier:
            for r in requires.get(d, []):
                if r == goal:
                    return depth
                if r not in seen:
                    seen.add(r)
                    nxt.append(r)
        frontier = nxt
    return None


def pip_tools(global_ctx):
    """[(key, the distribution the tool installed, the venv's python)] for the pip-<package> tools of the run, in order."""
    out = []
    for key, v in (global_ctx or {}).items():
        if not isinstance(v, dict) or not key.startswith('pip-'):
            continue
        params = v.get('_params') if isinstance(v.get('_params'), dict) else {}
        with_ = params.get('with') if isinstance(params.get('with'), dict) else {}
        out.append((key, norm_dist(with_.get('package') or key[4:]), v.get('path')))
    return out


def attribute_wheel(path, global_ctx):
    """
    The pip tool a wheel's library belongs to, with the distribution: the file's distribution (RECORD),
    then the pip-<package> tool of the run whose package is that distribution or requires it, in the
    venv the file lies in; the nearest tool wins. (None, dist) when no tool of the run pulled it.
    """
    dist, sp = wheel_dist(path)
    if not dist:
        return None, None
    idx = dist_index(sp)
    best, best_depth = None, None
    for key, pkg, python in pip_tools(global_ctx):
        if python:
            # the venv the tool installed into: .venv/bin/python or .venv/Scripts/python.exe
            venv = os.path.dirname(os.path.dirname(str(python)))
            if not under(sp, [venv]):
                continue
        depth = _dist_distance(idx['requires'], pkg, dist)
        if depth is None and pkg != norm_dist(key[4:]):
            depth = _dist_distance(idx['requires'], norm_dist(key[4:]), dist)
        if depth is not None and (best_depth is None or depth < best_depth):
            best, best_depth = key, depth
    return best, dist


def attribute(path, global_ctx):
    """
    The key of the resolved tool a library belongs to: a wheel's library to the pip tool that
    installed its distribution (attribute_wheel); else the tool that names the library (its lib
    names) and holds it in its folders; else the tool whose cache entry holds it (the longest match).
    A library in a system folder that no tool names stays unattributed (a distribution's OpenSSL
    shares /usr/lib with everything else).
    """
    if site_packages_of(path):
        key, _ = attribute_wheel(path, global_ctx)
        if key:
            return key
    key_of_lib = library_key(path)
    # the NVIDIA driver's own libraries (libcuda, libnvidia-*; nvcuda.dll) belong to the driver the run
    # resolved - the `cuda` entry of the target, which recorded its version and the GPU
    if nvidia_driver_library(path) and isinstance((global_ctx or {}).get('cuda'), dict):
        return 'cuda'
    tools = [(key, v) for key, v in (global_ctx or {}).items()
             if isinstance(v, dict) and key not in NOT_TOOLS and not key.startswith('target')]
    for key, v in tools:
        keys = tool_library_keys(v, key, broad = True)
        if any(key_of_lib == k or key_of_lib.startswith(k + '_') for k in keys) and under(path, tool_roots(v)):
            return key
    best, best_len = None, -1
    for key, v in tools:
        entry = v.get('path_cmeta_cache')
        if entry and under(path, [os.path.normcase(os.path.normpath(entry))]) and len(entry) > best_len:
            best, best_len = key, len(entry)
    return best


def nvidia_driver_library(path):
    """Whether a library is the NVIDIA driver's own: libcuda.so / nvcuda.dll, or libnvidia-* (the driver's helpers)."""
    key = library_key(path)
    base = str(path or '').replace('\\', '/').rsplit('/', 1)[-1].lower()     # a record of either OS, read on either
    return key in NVIDIA_DRIVER or base.startswith('libnvidia-')


def library_entries(paths, global_ctx, uname):
    out = []
    for p in paths or []:
        if not p:
            continue
        entry = {'name': os.path.basename(p), 'path': p, 'system': is_system(p, uname),
                 'tool': attribute(p, global_ctx)}
        if site_packages_of(p):
            dist, _ = wheel_dist(p)
            if dist:
                entry['dist'] = dist             # the Python distribution the file belongs to
        if entry['tool'] == 'cuda' and nvidia_driver_library(p):
            entry['role'] = 'driver'             # shown as "(driver)" under the cuda row
        out.append(entry)
    return out


###################################################################################################
# A compiler's own runtime libraries. GCC's libgomp, libstdc++ and libgcc_s, LLVM's libomp and
# libc++, Intel's libiomp5 and libimf, MSVC's vcomp140 and msvcp140 are installed where every other
# library is (/usr/lib/<triplet>, C:\Windows\System32), so no tool names them and no folder rule
# reaches them. The compiler itself is asked: "<compiler> -print-file-name=<file>" prints the file
# the compiler links against, and the same file (links resolved) as the one the process loaded
# makes the library that compiler's runtime. MSVC takes no such question: its runtime DLLs are
# known by name and live in the Visual Studio installation or as the redistributable copies in
# System32. A compiler installed in a folder of its own (LLVM on Windows, MinGW, a Homebrew GCC,
# the clang of a Swift toolchain, an Android NDK) also owns a runtime-named library under that
# folder. The names are kept to each family's own runtime, since a compiler's -print-file-name also
# finds the libraries of the other family in the shared system folders.
RUNTIME_LIBRARIES = {
    'gnu': re.compile(r'^(gomp|stdc\+\+|gcc_s(_\w+)?|atomic|quadmath|itm|ssp|gfortran|objc|winpthread|asan|ubsan|tsan|lsan|hwasan)$'),
    'llvm': re.compile(r'^(omp\w*|archer|c\+\+|c\+\+abi|c\+\+_shared|c\+\+experimental|clang_rt\..*)$'),
    'intel': re.compile(r'^(iomp5(md)?|imf|svml|irng|intlc|ifcore(md)?|ifport|sycl\d*|ur_\w+|pi_\w+)$'),
    'msvc': re.compile(r'^(vcomp|msvcp|vcruntime|concrt|vccorlib|vcamp|msvcr|mfc)\w*$'),
}
COMPILER_FAMILIES = {
    'gcc': 'gnu', 'gcc-cpp': 'gnu', 'g++': 'gnu', 'gfortran': 'gnu', 'mingw': 'gnu',
    'clang': 'llvm', 'clang-cpp': 'llvm', 'clang++': 'llvm', 'clang-cl': 'llvm', 'llvm': 'llvm', 'android-ndk': 'llvm',
    'icx': 'intel', 'icpx': 'intel', 'icc': 'intel', 'icpc': 'intel', 'ifx': 'intel', 'ifort': 'intel', 'dpcpp': 'intel',
    'intel-oneapi': 'intel',
    'msvc': 'msvc', 'cl': 'msvc', 'microsoft-visual-studio': 'msvc', 'microsoft.visual-studio': 'msvc',
}
# Tools that hold a compiler without being the compiler the run used (the role keys compiler-* and
# the compilers themselves come first when a library is attributed)
HOLDER_TOOLS = ('microsoft-visual-studio', 'microsoft.visual-studio', 'llvm', 'android-ndk', 'intel-oneapi')
# Folders every package shares: a compiler found there owns only what -print-file-name confirms
POSIX_SHARED_PREFIXES = ('', '/', '/bin', '/sbin', '/lib', '/lib64', '/usr', '/usr/local', '/opt', '/opt/local',
                         '/opt/homebrew', '/home', '/users', '/snap', '/var', '/tmp')


def compiler_family(tool, key = None):
    """gnu, llvm, intel or msvc for a resolved compiler (its tool name, then its key, then its binary); None otherwise."""
    names = []
    t = tool.get('tool') if isinstance(tool, dict) else None
    if isinstance(t, dict) and t.get('name'):
        names.append(str(t['name']))
    if key:
        names.append(str(key))
    if isinstance(tool, dict) and isinstance(tool.get('path'), str) and tool['path']:
        names.append(os.path.basename(tool['path']))
    for name in names:
        n = re.sub(r'\.(exe|bat|cmd)$', '', name.strip().lower())
        if n in COMPILER_FAMILIES:
            return COMPILER_FAMILIES[n]
        if 'clang' in n:                                                     # clang-21, aarch64-linux-android35-clang++
            return 'llvm'
        if re.search(r'(^|[-_.])(gcc|g\+\+|gfortran)(-\d+(\.\d+)*)?$', n) or n.startswith('mingw'):   # x86_64-linux-gnu-gcc-15
            return 'gnu'
        if n.startswith(('icx', 'icpx', 'ifx', 'intel')):
            return 'intel'
    return None


def _native_path(text):
    """Whether a path is one of the host OS (a drive or UNC path on Windows, a POSIX path elsewhere): only those get realpath."""
    return (os.name == 'nt') == bool(re.match(r'^([A-Za-z]:[\\/]|\\\\)', text))


def _basename_any(path):
    """The last component of a path with either separator (a Windows record read on Linux, and the tests)."""
    return re.split(r'[\\/]', str(path or ''))[-1]


def _norm_any(path):
    """A path as lower-case forward-slash text, links resolved when it is a path of this host: comparable across separators."""
    text = str(path)
    if _native_path(text):
        text = _real(text)
    text = text.replace('\\', '/')
    text = posixpath.normpath(text) if text else text
    return text.rstrip('/').lower()


def _under_any(path, roots):
    """Whether `path` lies in one of `roots`, whatever the separators and the case."""
    if not path:
        return False
    p = _norm_any(path)
    for r in roots or []:
        if not r:
            continue
        r = _norm_any(r)
        if r and (p == r or p.startswith(r + '/')):
            return True
    return False


def compiler_root(tool, family):
    """
    The installation folder of a compiler: the folder above its bin folder (links resolved) - /usr for
    /usr/bin/gcc, /usr/lib/llvm-21 for Ubuntu's clang, C:\\Program Files\\LLVM; for MSVC the Visual Studio
    installation, the folder above "VC" (cl.exe and vcvars64.bat both live under it).
    """
    path = tool.get('path') if isinstance(tool, dict) else None
    if not isinstance(path, str) or not path:
        return None
    text = _real(path) if _native_path(path) else path
    parts = re.split(r'[\\/]', text)
    sep = '\\' if '\\' in text else '/'
    if family == 'msvc':
        for i in range(len(parts) - 1, 0, -1):
            if parts[i].lower() == 'vc':
                return sep.join(parts[:i]) or None
        return None
    folder = parts[:-1]
    if folder and folder[-1].lower() == 'bin':
        folder = folder[:-1]
    root = sep.join(folder)
    return root if root else None


def dedicated_root(root, uname = None):
    """A compiler's installation folder of its own, as against a system folder every package shares."""
    if not root:
        return False
    r = _norm_any(root)
    if uname == 'windows' or re.match(r'^[a-z]:', r):
        win = _norm_any(os.environ.get('SystemRoot') or os.environ.get('WINDIR') or 'C:\\Windows')
        if r == win or r.startswith(win + '/'):
            return False
        return not re.fullmatch(r'[a-z]:(/program files( \(x86\))?|/users(/[^/]+)?|/windows)?', r)
    return r not in POSIX_SHARED_PREFIXES


def windows_runtime_folders():
    """System32, SysWOW64 and WinSxS: where Windows keeps the redistributable copies of the MSVC runtime."""
    root = os.environ.get('SystemRoot') or os.environ.get('WINDIR') or 'C:\\Windows'
    return [os.path.join(root, d) for d in ('System32', 'SysWOW64', 'WinSxS')]


def compiler_tools(global_ctx):
    """
    The compilers of the run as (key, tool, family, root): the compiler tools themselves first (gcc,
    msvc), then the role keys (compiler-c), then the holders (microsoft-visual-studio); one per binary.
    """
    found = []
    for key, v in (global_ctx or {}).items():
        if not isinstance(v, dict) or key in NOT_TOOLS or key.startswith('target'):
            continue
        if not isinstance(v.get('path'), str) or not v['path']:
            continue
        family = compiler_family(v, key)
        if not family:
            continue
        rank = 2 if key in HOLDER_TOOLS else (1 if key.startswith('compiler-') else 0)
        found.append((rank, key, v, family))
    found.sort(key = lambda x: (x[0], x[1]))
    out, seen = [], set()
    for rank, key, v, family in found:
        binary = _norm_any(v['path'])
        if binary in seen:
            continue
        seen.add(binary)
        out.append((key, v, family, compiler_root(v, family)))
    return out


def print_file_name(compiler, filename, timeout = 15):
    """
    What "<compiler> -print-file-name=<filename>" answers (GCC, Clang, Intel): the path of the file
    when the compiler finds it in its library folders, else None (the compiler echoes the name back).
    """
    try:
        r = subprocess.run([compiler, f'-print-file-name={filename}'], capture_output = True, text = True, timeout = timeout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    lines = [l.strip() for l in (r.stdout or '').splitlines() if l.strip()]
    answer = lines[-1] if lines else ''
    if not answer or answer == filename or not os.path.isfile(answer):
        return None
    return answer


def attribute_runtime(libraries, global_ctx, uname, probe = None):
    """
    Gives the loaded libraries that no tool claimed and that are a compiler's runtime (RUNTIME_LIBRARIES)
    to the compiler of the run that owns them: `tool` = its key, `role` = 'runtime'. GCC, Clang and
    Intel are asked with -print-file-name (`probe`; tests replace it); MSVC's DLLs are known by name
    and must lie in the Visual Studio installation or in System32; a compiler installed in a folder of
    its own also owns the runtime-named libraries under that folder. Returns how many were attributed.
    """
    probe = probe or print_file_name
    compilers = compiler_tools(global_ctx)
    if not compilers:
        return 0
    # a library that a resolved tool names is that tool's business (the origin check says whether the
    # loaded one came from it): lib-openmp's libomp is never the compiler's runtime here
    claimed = set()
    for key, v in (global_ctx or {}).items():
        if isinstance(v, dict) and key not in NOT_TOOLS and not key.startswith('target'):
            claimed.update(tool_library_keys(v, key))
    answers = {}
    count = 0
    for lib in libraries or []:
        if not isinstance(lib, dict) or lib.get('tool') or lib.get('system'):
            continue
        path = lib.get('path')
        name = _basename_any(path or lib.get('name') or '').strip()
        if not path or not name:
            continue
        stem = library_key(name)
        if stem in claimed:
            continue
        for key, tool, family, root in compilers:
            if not RUNTIME_LIBRARIES[family].match(stem):
                continue
            if family == 'msvc':
                owner = _under_any(path, ([root] if root else []) + windows_runtime_folders())
            else:
                ask = (tool['path'], name)
                if ask not in answers:
                    answers[ask] = probe(tool['path'], name)
                owner = answers[ask] is not None and _norm_any(answers[ask]) == _norm_any(path)
                if not owner and root and dedicated_root(root, uname):
                    owner = _under_any(path, [root])
            if owner:
                lib['tool'] = key
                lib['role'] = 'runtime'
                count += 1
                break
    return count


###################################################################################################
def run_environment(run_time_env, base = None):
    """The environment of the run: the process environment plus the run's env (+KEY lists prepended)."""
    env = dict(os.environ if base is None else base)
    for k, v in (run_time_env or {}).items():
        if not isinstance(k, str):
            continue
        if k.startswith('+'):
            name = k[1:]
            items = [str(x) for x in (v if isinstance(v, (list, tuple)) else [v]) if x]
            env[name] = os.pathsep.join(items + ([env[name]] if env.get(name) else []))
        elif v is not None:
            env[k] = str(v)
    return env


def requested_from(request_params, request_use):
    """
    What the request made explicit: the --use tree as given (before the program's `use` defaults),
    the compile/with/compute parameters and program parameters as given (before the program's
    `params` defaults). Control and routing keys are dropped.
    """
    skip = {'name', 'program_tags', 'program_api_ver', 'ask', 'cmd', 'unparsed', 'target_tmp', 'target_path',
            'work_path', 'here', 'skip_compile', 'skip_run', 'recompile', 'env', 'provenance', 'timeout',
            'compile_timeout', 'dynamic_lib_paths', 'target', 'skip_size_check', 'min_free_gb'}
    params = {k: v for k, v in (request_params or {}).items() if k not in skip and v is not None}
    out = {'use': request_use or {}}
    for k in ('compile', 'with', 'run'):
        if isinstance(params.get(k), dict) and params[k]:
            out[k] = params.pop(k)
        else:
            params.pop(k, None)
    if params.get('compute'):
        c = params.pop('compute')
        out['compute'] = c.split(',') if isinstance(c, str) else list(c)
    if params:
        out['params'] = params
    return out


def is_true(value):
    return value is True or str(value).strip().lower() in ('true', 'yes', '1', 'on')


###################################################################################################
def find_accelerators(data, out = None):
    """The accelerator entries ({accelerator, available, required, ...}) anywhere in a result."""
    if out is None:
        out = []
    if isinstance(data, dict):
        if 'accelerator' in data and ('available' in data or 'required' in data):
            out.append(data)
        else:
            for v in data.values():
                find_accelerators(v, out)
    elif isinstance(data, list):
        for v in data:
            find_accelerators(v, out)
    return out


###################################################################################################
# The frameworks of a Python run, from the venv: the distributions the loaded wheel libraries belong
# to, with their versions (nvidia-cuda-runtime 13.4.92 is the CUDA runtime a wheel brought along; a
# torch version ending in +cu130 names the CUDA it was built for), plus the packages the pip tools of
# the run installed even when nothing of theirs was loaded (Windows and Android have no loader log).
def site_packages_folders(venv):
    """The site-packages folders of a venv: Lib/site-packages (Windows), lib/python3.x/site-packages (POSIX)."""
    out = []
    w = os.path.join(str(venv), 'Lib', 'site-packages')
    if os.path.isdir(w):
        out.append(w)
    out += sorted(glob.glob(os.path.join(str(venv), 'lib', 'python3*', 'site-packages')))
    return out


def cuda_build_of(version):
    """'2.14.1+cu130' -> '13.0', '2.9.0+cu128' -> '12.8'; None when the version carries no CUDA tag."""
    m = re.search(r'\+cu(\d{2,3})$', str(version or ''))
    if not m:
        return None
    digits = m.group(1)
    return digits[:-1] + '.' + digits[-1]


def framework_versions(libraries, global_ctx):
    """
    {distribution: {'version', 'loaded', 'tool', 'cuda_build'?}} - every distribution a loaded wheel
    library belongs to, and the package of every pip tool of the run (installed in its venv, loaded or not).
    """
    out = {}

    def put(dist, version, loaded, tool):
        e = out.setdefault(dist, {'version': version, 'loaded': False})
        if version and not e.get('version'):
            e['version'] = version
        e['loaded'] = bool(e['loaded'] or loaded)
        if tool and not e.get('tool'):
            e['tool'] = tool

    for lib in libraries or []:
        dist, path = lib.get('dist'), lib.get('path')
        if not dist or not path:
            continue
        sp = site_packages_of(path)
        versions = dist_index(sp)['versions'] if sp else {}
        put(dist, versions.get(dist), True, lib.get('tool'))
    for key, pkg, python in pip_tools(global_ctx):
        if not python:
            continue
        venv = os.path.dirname(os.path.dirname(str(python)))
        for sp in site_packages_folders(venv):
            versions = dist_index(sp)['versions']
            if pkg in versions:
                put(pkg, versions[pkg], False, key)
                break
    for e in out.values():
        cb = cuda_build_of(e.get('version'))
        if cb:
            e['cuda_build'] = cb
    return out


###################################################################################################
# What kind of Python ran: a venv (pyvenv.cfg; its base from the "home =" line, "uv =" when uv made
# it), a conda environment or a conda base (conda-meta/), a uv-managed interpreter (uv's python
# folder) or the system's. The record says so because "python" alone names any of them, and where a
# run's packages came from (conda channels, pip or uv into a venv, the distribution) follows from it.
def _python_prefix(path):
    p = os.path.normpath(str(path or ''))
    parent = os.path.dirname(p)
    if os.path.basename(parent).lower() in ('bin', 'scripts'):
        return os.path.dirname(parent)
    return parent


def _classify_prefix(prefix):
    """('conda' | 'conda-env' | 'uv-managed' | 'system', the environment's name or None) for an interpreter prefix."""
    low = str(prefix).replace('\\', '/').rstrip('/').lower()
    if os.path.isdir(os.path.join(prefix, 'conda-meta')):
        # a base carries the conda itself (condabin/), its package cache (pkgs/) and its environments (envs/);
        # an environment has none of them - under envs/ of a base, or anywhere with "conda create -p"
        # (cMeta's .conda-env inside a python entry)
        if any(os.path.isdir(os.path.join(prefix, d)) for d in ('condabin', 'pkgs', 'envs')):
            return 'conda', None
        return 'conda-env', os.path.basename(str(prefix).rstrip('\\/'))
    if re.search(r'/uv/python/[^/]*cpython-', low) or re.search(r'/uv/python/[^/]*pypy', low):
        return 'uv-managed', None
    return 'system', None


def python_environment(path):
    """
    {'kind': 'venv' | 'conda' | 'conda-env' | 'uv-managed' | 'system', 'prefix', 'made_by'? ('uv 0.12.21'),
     'name'? (a conda environment), 'base'? ({'kind', 'prefix', 'name'?} of a venv's base interpreter)}
    for an interpreter path; {} without one.
    """
    if not path:
        return {}
    prefix = _python_prefix(path)
    out = {'prefix': prefix}
    cfg = os.path.join(prefix, 'pyvenv.cfg')
    if os.path.isfile(cfg):
        out['kind'] = 'venv'
        home, uv = None, None
        try:
            with open(cfg, encoding = 'utf-8', errors = 'replace') as f:
                for line in f:
                    k, _, v = line.partition('=')
                    k, v = k.strip().lower(), v.strip()
                    if k == 'home':
                        home = v
                    elif k == 'uv':
                        uv = v
        except OSError:
            pass
        if uv:
            out['made_by'] = 'uv ' + uv
        if home:
            base_prefix = os.path.dirname(home) if os.path.basename(home).lower() in ('bin', 'scripts') else home
            kind, name = _classify_prefix(base_prefix)
            out['base'] = {'kind': kind, 'prefix': base_prefix}
            if name:
                out['base']['name'] = name
        return out
    kind, name = _classify_prefix(prefix)
    out['kind'] = kind
    if name:
        out['name'] = name
    if kind in ('conda-env', 'conda'):
        # an environment cMeta made (task venv --conda) carries who made it
        marker = os.path.join(prefix, '.cmeta-conda-env.json')
        if os.path.isfile(marker):
            try:
                with open(marker, encoding = 'utf-8') as f:
                    made = json.load(f)
                if isinstance(made, dict) and made.get('made_by'):
                    out['made_by'] = str(made['made_by'])
                    if made.get('conda'):
                        out['conda'] = str(made['conda'])
            except (OSError, ValueError):
                pass
    return out


def conda_packages(prefix):
    """{name: version} of the packages conda installed into an environment or base (conda-meta/*.json), {} when none."""
    folder = os.path.join(str(prefix or ''), 'conda-meta')
    out = {}
    if not os.path.isdir(folder):
        return out
    for n in sorted(os.listdir(folder)):
        if not n.endswith('.json'):
            continue
        try:
            with open(os.path.join(folder, n), encoding = 'utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get('name'):
            out[str(d['name'])] = str(d.get('version') or '?')
    return out


def python_environment_text(env):
    """One line for the checks: 'venv made by uv 0.12.21 on a uv-managed Python', 'conda environment myenv', ..."""
    if not env or not env.get('kind'):
        return ''
    kind = env['kind']
    if kind == 'venv':
        base = env.get('base') or {}
        words = {'conda': 'a conda base', 'conda-env': f"the conda environment {base.get('name') or '?'}",
                 'uv-managed': 'a uv-managed Python', 'system': "the system's Python"}
        text = 'venv' + (f" made by {env['made_by']}" if env.get('made_by') else '')
        if base.get('kind'):
            text += ' on ' + words.get(base['kind'], base['kind'])
        return text
    made = f" made by {env['made_by']}" if env.get('made_by') else ''
    return {'conda': 'a conda base environment' + made, 'conda-env': f"the conda environment {env.get('name') or '?'}" + made,
            'uv-managed': 'a uv-managed Python (no venv)', 'system': "the system's Python (no venv)"}.get(kind, kind)


###################################################################################################
# The toolchain a Go or Rust binary was built with, read from the binary itself. A Go binary carries
# its buildinfo (the magic "\xff Go buildinf:" and, since Go 1.18, the version string inline), so a
# GOTOOLCHAIN that fetched another Go than the one cMeta set up shows; a Rust binary carries
# "rustc version X.Y.Z (commit date)" (the .comment of an ELF) or at least the toolchain's commit in its
# "/rustc/<hash>/" source paths, which the resolved rustc's `-vV` answer is compared with.
GO_BUILDINFO_MAGIC = b'\xff Go buildinf:'
BINARY_READ_LIMIT = 256 * 1024 * 1024


def go_version_in_binary(path):
    """The Go version a binary was built with ('1.26.2'), from its buildinfo; None when it has none."""
    try:
        with open(path, 'rb') as f:
            data = f.read(BINARY_READ_LIMIT)
    except OSError:
        return None
    i = data.find(GO_BUILDINFO_MAGIC)
    if i < 0 or i + 32 > len(data):
        return None
    flags = data[i + 15]
    if flags & 2:                                   # the version string inline: a varint length, then the bytes
        p, n, shift = i + 32, 0, 0
        while p < len(data):
            b = data[p]
            p += 1
            n |= (b & 0x7f) << shift
            shift += 7
            if b < 0x80:
                break
        s = data[p:p + n].decode('utf-8', 'replace').strip()
    else:                                           # Go 1.13-1.17: the version string lies nearby
        m = re.search(rb'go1\.\d+(?:\.\d+)?(?:rc\d+|beta\d+)?', data[i:i + 65536])
        s = m.group(0).decode() if m else ''
    if not s:
        return None
    return s[2:] if s.startswith('go') else s


def rust_version_in_binary(path):
    """(version, commit) as far as a binary tells: 'rustc version X.Y.Z (commit date)', else the /rustc/<hash>/ paths."""
    try:
        with open(path, 'rb') as f:
            data = f.read(BINARY_READ_LIMIT)
    except OSError:
        return None, None
    m = re.search(rb'rustc version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)(?: \(([0-9a-f]{7,40})[^)]*\))?', data)
    if m:
        return m.group(1).decode(), (m.group(2).decode() if m.group(2) else None)
    m = re.search(rb'/rustc/([0-9a-f]{40})/', data)
    return None, (m.group(1).decode() if m else None)


def rustc_commit(rustc_path, env = None, timeout = 20):
    """The commit-hash of `rustc -vV`, or None. `env` is the run's environment: a rustup proxy needs RUSTUP_HOME/CARGO_HOME."""
    full = dict(os.environ)
    for k, v in (env or {}).items():
        if isinstance(v, str):
            full[str(k)] = v
    try:
        out = subprocess.run([str(rustc_path), '-vV'], capture_output = True, text = True, timeout = timeout, env = full).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    m = re.search(r'^commit-hash:\s*([0-9a-f]+)', out or '', re.M)
    return m.group(1) if m else None


def tools_env(global_ctx):
    """The environment the tools of the run added (every entry's _aggregate.env: RUSTUP_HOME, CARGO_HOME, ...)."""
    env = {}
    for v in (global_ctx or {}).values():
        agg = v.get('_aggregate') if isinstance(v, dict) else None
        e = agg.get('env') if isinstance(agg, dict) else None
        if isinstance(e, dict):
            env.update({str(k): val for k, val in e.items() if isinstance(val, str)})
    return env


def toolchain_in_binary(exe, global_ctx, rustc_probe = None, env = None):
    """{'go': {...}} / {'rust': {...}}: for each compiler of the run that leaves its version in the binary, what the binary says."""
    out = {}
    if not exe or not os.path.isfile(str(exe)):
        return out
    if rustc_probe is None:
        # the rustup proxy answers only with its homes: the tools' own environment, then the run's
        probe_env = dict(tools_env(global_ctx))
        probe_env.update({str(k): v for k, v in (env or {}).items() if isinstance(v, str)})
        rustc_probe = lambda path: rustc_commit(path, probe_env)
    for key, v in (global_ctx or {}).items():
        if not key.startswith('compiler-') or not isinstance(v, dict):
            continue
        tool = v.get('tool') if isinstance(v.get('tool'), dict) else {}
        name = str(tool.get('name') or key[len('compiler-'):]).lower()
        # the tool's name decides: go, go-android (not google.android-ndk.clang); rustc, rustc-android, rustup
        if key == 'compiler-go' or re.match(r'^go(-|$)', name):
            found = go_version_in_binary(exe)
            out['go'] = {'tool': key, 'resolved': v.get('version'), 'binary': found,
                         'source': 'go buildinfo' if found else None}
        elif key == 'compiler-rust' or re.match(r'^rust(c|up)?(-|$)', name):
            version, commit = rust_version_in_binary(exe)
            entry = {'tool': key, 'resolved': v.get('version'), 'binary': version, 'binary_commit': commit,
                     'source': 'rustc version string' if version else ('/rustc/<commit>/ source paths' if commit else None)}
            if commit and not version and v.get('path'):
                entry['resolved_commit'] = rustc_probe(v['path'])
            out['rust'] = entry
    return out


def same_version(a, b):
    """'1.26.2' vs '1.26.2' or '1.26' - the same release as far as both say."""
    a, b = str(a or '').strip(), str(b or '').strip()
    return bool(a and b) and (a == b or a.startswith(b + '.') or b.startswith(a + '.'))


def run_checks(record, global_ctx, static_effective, match_version = None):
    """The checks of a record (see the module docstring). Returns the list; sets record['ok']."""
    checks = []
    requested = record.get('requested') or {}
    compute = record.get('compute') or []
    uname = (record.get('host') or {}).get('uname')
    loaded = record.get('loaded') or {}
    libraries = loaded.get('libraries') or []
    build = (record.get('build') or {}).get('binary') or {}
    inspector_ok = build.get('format') is not None or loaded.get('method') == 'loader-log'

    def add(rule, level, ok, detail, tool = None):
        check = {'rule': rule, 'level': level, 'ok': ok, 'detail': detail}
        if tool:
            check['tool'] = tool
        checks.append(check)

    # static
    static_requested = is_true((requested.get('compile') or {}).get('static'))
    if static_effective or static_requested:
        level = 'error' if static_requested else 'warning'
        if not inspector_ok and loaded.get('method') != 'loader-log':
            add('static', 'info', None, 'static build: the binary inspector is unavailable, nothing checked')
        else:
            shared = [l for l in libraries if not static_allowed(l.get('path') or l.get('name'), uname, compute, l.get('system'))]
            if 'cuda' not in compute and uname == 'linux' and loaded.get('method') == 'resolved' and build.get('format') == 'elf' and not build.get('static'):
                not_static = [l.get('name') for l in libraries]
                add('static', level, False, 'static build: the binary is not fully static' +
                    (': ' + ', '.join(not_static) if not_static else ''))
            elif shared:
                add('static', level, False, 'static build: shared libraries loaded that have a static form: ' +
                    ', '.join(f"{l['name']} ({l.get('path') or 'not found'})" for l in shared))
            else:
                add('static', level, True, 'static build: no shared library beyond the allowed set' +
                    (' (' + ', '.join(l['name'] for l in libraries) + ')' if libraries else ''))

    # origin: a tool's library comes from its folders
    use = requested.get('use') or {}
    for key, tool in (global_ctx or {}).items():
        if not isinstance(tool, dict) or key in NOT_TOOLS or key.startswith('target'):
            continue
        keys = tool_library_keys(tool, key)
        if not keys:
            continue
        roots = tool_roots(tool)
        level = 'error' if key in use else 'warning'
        for lib in libraries:
            lkey = library_key(lib.get('name'))
            if not any(lkey == k or (len(k) > 3 and lkey.startswith(k + '_')) for k in keys):
                continue
            if lib.get('system'):
                continue
            if lib.get('path') and not under(lib['path'], roots):
                add('origin', level, False, f"{lib['name']} comes from {lib['path']}, not from the resolved {key}"
                    + (f" {tool.get('version')}" if tool.get('version') else '') + f" ({tool.get('path_bin') or tool.get('path')})", tool = key)
            elif lib.get('path'):
                add('origin', 'info', True, f"{lib['name']} comes from the resolved {key}", tool = key)

    # version: every explicit --use.<tool>.version matches
    for key, spec in use.items():
        if not isinstance(spec, dict) or not spec.get('version'):
            continue
        tool = (global_ctx or {}).get(key)
        if not isinstance(tool, dict) or not tool.get('version'):
            add('version', 'info', None, f'--use.{key}.version={spec["version"]}: {key} is not part of this run', tool = key)
            continue
        want, have = str(spec['version']), str(tool['version'])
        ok = None
        if match_version is not None:
            try:
                ok = bool(match_version(want, have))
            except Exception:
                ok = None
        if ok is None:
            ok = have == want or have.startswith(want.lstrip('=~^') + '.') or have == want.lstrip('=~^')
        add('version', 'error', ok, f'--use.{key}.version={want}: resolved {have}' + ('' if ok else ' (mismatch)'), tool = key)

    # accelerator: what the program reports
    for acc in find_accelerators(record.get('result') or {}):
        name = acc.get('accelerator')
        required, available = is_true(acc.get('required')), is_true(acc.get('available'))
        if required and not available:
            add('accelerator', 'error', False, f'accelerator {name} was required but is not available')
        elif not available:
            add('accelerator', 'info', True, f'accelerator {name} is not available (optional)')
        else:
            add('accelerator', 'info', True, f'accelerator {name} used')

    # python: an interpreter requested with --use.python.tool_path is the one that ran, or the base of the venv that ran
    rt = record.get('runtime') or {}
    want_py = (use.get('python') or {}).get('tool_path') if isinstance(use.get('python'), dict) else None
    if want_py and want_py != '{{sys.executable}}':
        py = rt.get('python') if isinstance(rt.get('python'), dict) else {}
        got = str(py.get('path') or '')
        env_ = py.get('environment') or {}
        want_prefix = _python_prefix(want_py)
        ok = bool(got) and (_real(got) == _real(want_py) or _real(_python_prefix(got)) == _real(want_prefix))
        if not ok and env_.get('kind') == 'venv' and (env_.get('base') or {}).get('prefix'):
            ok = _real(env_['base']['prefix']) == _real(want_prefix)         # a venv made on the requested interpreter
        add('python', 'error', ok,
            f"--use.python.tool_path={want_py}: " + (f"the run used it" + (' (through a venv made on it)' if env_.get('kind') == 'venv' else '')
                                                      if ok else f"the run used {got or 'no Python'} instead" +
                                                      (f" ({python_environment_text(env_)})" if env_ else '')), tool = 'python')

    # python: a conda environment was asked for (--use.python.with.conda): the run's python is one cMeta made
    want_conda = isinstance(use.get('python'), dict) and isinstance(use['python'].get('with'), dict) \
        and str(use['python']['with'].get('conda', '')).strip().lower() in ('true', 'yes', '1', 'on')
    if want_conda:
        py = rt.get('python') if isinstance(rt.get('python'), dict) else {}
        env_ = py.get('environment') or {}
        ok = env_.get('kind') == 'conda-env'
        add('python', 'error', ok, '--use.python.with.conda: ' +
            (f"the run used the conda environment {env_.get('name') or '?'}" + (f" made by {env_['made_by']}" if env_.get('made_by') else '')
             if ok else f"the run used {python_environment_text(env_) or py.get('path') or 'no Python'} instead"), tool = 'python')

    # wheel: a requested CUDA or cuDNN version cannot apply to the runtime a wheel brought along
    frameworks = rt.get('frameworks') or {}
    cuda_key = next((k for k in ('nvcc', 'cuda', 'lib-cuda') if isinstance(use.get(k), dict) and use[k].get('version')), None)
    cudnn_key = 'lib-cudnn' if isinstance(use.get('lib-cudnn'), dict) and use['lib-cudnn'].get('version') else None
    for lib in libraries:
        dist = str(lib.get('dist') or '')
        if not dist:
            continue
        lkey = library_key(lib.get('name'))
        hit = None
        if cuda_key and (lkey == 'cudart' or dist.startswith('nvidia-cuda-runtime')):
            hit, cuda_key = cuda_key, None
        elif cudnn_key and (lkey.startswith('cudnn') or dist.startswith('nvidia-cudnn')):
            hit, cudnn_key = cudnn_key, None
        if hit:
            version = (frameworks.get(dist) or {}).get('version') or ''
            add('wheel', 'error', False,
                f"--use.{hit}.version={use[hit]['version']} cannot apply to {lib['name']}, which came with the wheel "
                f"{dist} {version} ({lib.get('tool') or 'no tool of the run'}): pin the package instead", tool = lib.get('tool'))

    # toolchain: the binary was built by the compiler cMeta resolved (GOTOOLCHAIN or rustup's default may differ)
    for lang, tc in ((record.get('build') or {}).get('toolchain') or {}).items():
        key = tc.get('tool') or f'compiler-{lang}'
        explicit = any(isinstance(use.get(k), dict) and use[k].get('version') for k in (key, lang, 'go', 'rustc', 'rustup', 'rustc-android', 'go-android'))
        level = 'error' if explicit else 'warning'
        resolved = str(tc.get('resolved') or '')
        if tc.get('binary'):
            ok = same_version(tc['binary'], resolved)
            add('toolchain', 'info' if ok else level, ok,
                f"{lang}: the binary was built by {lang} {tc['binary']}; the resolved {key} is {resolved or '?'}"
                + ('' if ok else ' (another toolchain built it)'), tool = key)
        elif tc.get('binary_commit'):
            rc = tc.get('resolved_commit')
            if rc:
                ok = tc['binary_commit'].startswith(rc) or rc.startswith(tc['binary_commit'])
                add('toolchain', 'info' if ok else level, ok,
                    f"{lang}: the binary carries the toolchain commit {tc['binary_commit'][:12]}; the resolved {key} {resolved} "
                    f"is {rc[:12]}" + ('' if ok else ' (another toolchain built it)'), tool = key)
            else:
                add('toolchain', 'info', None, f"{lang}: the binary carries the toolchain commit {tc['binary_commit'][:12]}; "
                                               f"the resolved {key} {resolved} did not report its commit", tool = key)
        else:
            add('toolchain', 'info', None, f"{lang}: the binary does not say which {lang} toolchain built it", tool = key)

    # info
    resolved = record.get('resolved') or {}
    tools = [f"{k} {v.get('version')}" for k, v in resolved.items()
             if k.startswith('compiler-') or k in ('nvcc', 'python', 'msvc', 'gcc', 'gcc-cpp', 'clang', 'clang-cpp') or k.startswith('lib-')]
    if tools:
        add('info', 'info', True, 'toolchain: ' + ', '.join(tools))
    py_env = ((rt.get('python') or {}).get('environment') or {}) if isinstance(rt.get('python'), dict) else {}
    py_text = python_environment_text(py_env)
    if py_text:
        add('info', 'info', True, f"python {(rt.get('python') or {}).get('version') or '?'}: {py_text}", tool = 'python')
    if frameworks:
        add('info', 'info', True, 'frameworks: ' + ', '.join(
            f"{d} {e.get('version') or '?'}" + (f" (built for CUDA {e['cuda_build']})" if e.get('cuda_build') else '')
            + ('' if e.get('loaded') else ' (installed, nothing of it loaded)') for d, e in frameworks.items()))
    if rt.get('driver') or rt.get('gpu'):
        add('info', 'info', True, f"driver {rt.get('driver')}, GPU {rt.get('gpu')}")

    record['checks'] = checks
    record['ok'] = not any(c['level'] == 'error' and c['ok'] is False for c in checks)
    return checks


###################################################################################################
def read_json(path):
    try:
        with open(path, encoding = 'utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, (dict, list)) else None
    except (OSError, ValueError):
        return None


def binary_of_run(local, global_ctx, run_cmds = None):
    """The file to inspect: the built executable, else the interpreter of the run (a Python program)."""
    exe = (local or {}).get('target_path_exe')
    if exe:
        return exe, 'program'
    python = (global_ctx or {}).get('python') or {}
    if python.get('path') and os.path.isfile(python['path']):
        return python['path'], 'interpreter'
    for cmd in run_cmds or []:
        if isinstance(cmd, str):
            first = cmd.strip().split('"')[1] if cmd.strip().startswith('"') else cmd.strip().split(' ')[0]
            if first and os.path.isfile(first):
                return first, 'command'
    return None, None


def inspect_binary(path, env, cwd, uname):
    """binary_deps.resolve() with every failure turned into a note."""
    if not path:
        return {'path': None, 'format': None, 'error': 'no executable to inspect'}
    try:
        info = binary_deps.resolve(path, env = env, cwd = cwd, uname = uname)
    except NotImplementedError as e:
        return {'path': path, 'format': None, 'error': f'binary inspector unavailable: {e}'}
    except Exception as e:
        return {'path': path, 'format': None, 'error': f'binary inspector failed: {type(e).__name__}: {e}'}
    out = {k: info.get(k) for k in ('path', 'format', 'arch', 'bits', 'static', 'interpreter', 'needed', 'delay_needed',
                                    'rpath', 'runpath', 'kind', 'deps', 'missing', 'error') if k in info}
    out.setdefault('path', path)
    return out


def build_record(mode, program, target_tmp, target_path, compute, global_ctx, local, request_params, request_use,
                 static_effective, result_data = None, match_version = None, note = None, run_skipped = False, entry = None):
    """
    The record of a run. `global_ctx`/`local` are ctx['tasks']['global'] and ['local'] after the run,
    `request_params`/`request_use` the request before the program's defaults were merged, `entry` the
    build entry of the request (alias, uid, request, request_digest; build_identity.py).
    """
    host = (global_ctx or {}).get('host') or {}
    os_info = host.get('os') or {}
    uname = os_info.get('uname')
    hostname = host.get('hostname')
    if isinstance(hostname, dict):          # task/host records the name with the addresses
        hostname = hostname.get('hostname')
    record = {
        'format': FORMAT,
        'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'mode': mode,
        'program': {'alias': program.get('alias'), 'uid': program.get('uid'), 'target_tmp': target_tmp, 'target_path': target_path},
        'compute': list(compute or []),
        'host': {'uname': uname, 'uarch': os_info.get('uarch'), 'os_id': (host.get('os_extra') or {}).get('id'),
                 'hostname': hostname},
        'requested': requested_from(request_params, request_use),
        'effective': {'static': bool(static_effective)},
        'resolved': collect_resolved(global_ctx),
    }
    if isinstance(entry, dict) and (entry.get('uid') or entry.get('alias')):
        record['program']['entry'] = {k: entry.get(k) for k in ('alias', 'uid', 'request', 'request_digest') if entry.get(k) is not None}
    if note:
        record['note'] = note

    # build: the stamp and the binary
    run_env = run_environment((local or {}).get('run_time_env'))
    exe, kind = binary_of_run(local, global_ctx, (local or {}).get('run_time_cmds'))
    binary = inspect_binary(exe, run_env, target_path, uname)
    if kind:
        binary['kind_of_file'] = kind
    record['build'] = {'stamp': read_json(os.path.join(target_path, STAMP_FILE)) if target_path else None, 'binary': binary}
    try:
        toolchain = toolchain_in_binary(exe, global_ctx, env = run_env)
    except Exception as e:                           # a reading problem never spoils the record
        toolchain = {'error': f'{type(e).__name__}: {e}'}
    if toolchain:
        record['build']['toolchain'] = toolchain

    # runtime
    cuda = ((global_ctx or {}).get('cuda') or {}).get('features') or {}
    versions = cuda.get('versions') or {}
    python = (global_ctx or {}).get('python') or {}
    record['runtime'] = {
        'driver': versions.get('driver version'),
        'driver_cuda': versions.get('cuda version'),
        'gpu': cuda.get('devices') if cuda.get('devices') else None,
        'compute_capability': cuda.get('compute_cap_int_min'),
        'python': {'version': python.get('version'), 'path': python.get('path'), 'entry': entry_uid(python)} if python else None,
        'engine_python': sys.version.split()[0],
    }
    if python and python.get('path'):
        try:
            record['runtime']['python']['environment'] = python_environment(python['path'])
        except Exception as e:                       # never spoils the record
            record['runtime']['python']['environment'] = {'error': f'{type(e).__name__}: {e}'}
        env_ = record['runtime']['python'].get('environment') or {}
        if env_.get('kind') in ('conda-env', 'conda') and env_.get('prefix'):
            # what conda installed there (pip's distributions are in runtime.frameworks)
            record['runtime']['python']['conda_packages'] = conda_packages(env_['prefix'])

    # loaded
    paths, processes = (None, 0)
    android = any(str(c).startswith('android') for c in (compute or []))
    if mode == 'loaded' and not android and not run_skipped:
        paths, processes = loader_log_libraries(target_path, uname)
    if paths is not None:
        record['loaded'] = {'method': 'loader-log', 'processes': processes,
                            'libraries': library_entries([p for p in paths if p != exe], global_ctx, uname)}
    else:
        deps = binary.get('deps') or []
        record['loaded'] = {'method': 'resolved',
                            'libraries': [{'name': os.path.basename(d.get('name') or '') or d.get('name'), 'path': d.get('path'),
                                           'system': bool(d.get('system')) or is_system(d.get('path') or d.get('name') or '', uname),
                                           'tool': attribute(d.get('path'), global_ctx) if d.get('path') else None,
                                           'source': d.get('source')} for d in deps]}
        if mode == 'loaded':
            record['loaded']['note'] = ('the loader logs nothing on this platform; the resolution stands in'
                                        if not android else 'an Android run: the resolution stands in')
        if binary.get('error'):
            record['loaded']['note'] = '; '.join(x for x in [record['loaded'].get('note'), binary['error']] if x)
    # a compiler's runtime library (libgomp, vcomp140, ...) belongs to the compiler of the run
    try:
        attribute_runtime(record['loaded'].get('libraries') or [], global_ctx, uname)
    except Exception as e:          # an attribution problem never spoils the record
        record['loaded']['note'] = '; '.join(x for x in [record['loaded'].get('note'),
                                                         f'runtime attribution failed: {type(e).__name__}: {e}'] if x)
    if run_skipped:
        record['loaded']['note'] = '; '.join(x for x in [record['loaded'].get('note'), 'the run phase was skipped: build-side record'] if x)
    # the frameworks of a Python run: the distributions behind the loaded wheel libraries, the pip tools' packages
    try:
        frameworks = framework_versions(record['loaded'].get('libraries') or [], global_ctx)
    except Exception as e:
        frameworks = {}
        record['loaded']['note'] = '; '.join(x for x in [record['loaded'].get('note'), f'framework versions failed: {type(e).__name__}: {e}'] if x)
    if frameworks:
        record['runtime']['frameworks'] = frameworks

    if result_data is not None:
        record['result'] = result_data

    run_checks(record, global_ctx, static_effective, match_version)
    return record


def write_record(target_path, record):
    """Writes provenance.json; returns None, or the error text."""
    try:
        os.makedirs(target_path, exist_ok = True)
        path = os.path.join(target_path, RECORD_FILE)
        with open(path, 'w', encoding = 'utf-8', newline = '\n') as f:
            json.dump(record, f, indent = 1, ensure_ascii = False, default = str)
        return None
    except (OSError, TypeError, ValueError) as e:
        return str(e)


def summary(record):
    """{'ok', 'errors', 'warnings'} of a record."""
    checks = record.get('checks') or []
    return {'ok': record.get('ok', True),
            'errors': sum(1 for c in checks if c['level'] == 'error' and c['ok'] is False),
            'warnings': sum(1 for c in checks if c['level'] == 'warning' and c['ok'] is False)}


def failed_lines(record):
    """The lines to print for failed checks: ('error' | 'warning', text)."""
    return [(c['level'], c['detail']) for c in record.get('checks') or [] if c['ok'] is False and c['level'] in ('error', 'warning')]


def session_attachment_name(record):
    """
    The record's name among a test session's attachments: provenance--<program>--<build folder>--<HHMMSS>.json
    (the time from the record, UTC), so the records of several programs, folders and runs stay apart.
    """
    prog = record.get('program') or {}
    created = str(record.get('created') or '')
    digits = re.sub(r'\D', '', created.split('T', 1)[1]) if 'T' in created else ''
    hhmmss = digits[:6] if len(digits) >= 6 else time.strftime('%H%M%S', time.gmtime())
    alias = re.sub(r'[^\w.-]+', '-', str(prog.get('alias') or prog.get('uid') or 'program'))
    folder = re.sub(r'[^\w.-]+', '-', str(prog.get('target_tmp') or 'tmp'))
    return f'provenance--{alias}--{folder}--{hhmmss}.json'


def session_note(record):
    """One line for a test session's notes: the program, its build folder, the checks, the compute targets."""
    s = summary(record)
    prog = record.get('program') or {}
    compute = ','.join(str(c) for c in record.get('compute') or []) or '?'
    return (f"provenance: {prog.get('alias') or prog.get('uid') or '?'} ({prog.get('target_tmp') or 'tmp'}) "
            f"{'ok' if s['ok'] else 'FAILED'}, {s['errors']} failed, {s['warnings']} warnings; compute {compute}")
