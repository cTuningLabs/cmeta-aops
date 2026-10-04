"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Shared by tool/torch-cpp (LibTorch built from source) and tool/torch-cpp-prebuilt (PyTorch's
prebuilt LibTorch archives): the version of a LibTorch folder, and the paths a C++ build needs.

A LibTorch folder ("home") has the main library in lib/ (libtorch.so, libtorch.dylib, torch.dll),
the headers in include/ and TorchConfig.cmake in share/cmake/Torch/ (or lib/cmake/Torch/).
"""

import os
import re


def _read(path):
    try:
        with open(path, encoding = 'utf-8', errors = 'replace') as f:
            return f.read()
    except OSError:
        return None


def libtorch_version(home):
    """The version of the LibTorch in `home` ("2.7.1"), or None."""
    text = _read(os.path.join(home, 'include', 'torch', 'csrc', 'api', 'include', 'torch', 'version.h'))
    if text:
        parts = [re.search(rf'#define\s+TORCH_VERSION_{k}\s+(\d+)', text) for k in ('MAJOR', 'MINOR', 'PATCH')]
        if all(parts):
            return '.'.join(p.group(1) for p in parts)
        m = re.search(r'#define\s+TORCH_VERSION\s*\\?\s*"(\d+\.\d+[.\d]*)', text)
        if m:
            return m.group(1)

    # The prebuilt archives: "2.7.1" or "2.7.1+cpu"
    text = _read(os.path.join(home, 'build-version'))
    if text:
        m = re.match(r'\s*(\d+\.\d+[.\d]*\d)', text)
        if m:
            return m.group(1)

    for sub in (('share', 'cmake', 'Torch'), ('lib', 'cmake', 'Torch')):
        text = _read(os.path.join(home, *sub, 'TorchConfigVersion.cmake'))
        if text:
            m = re.search(r'PACKAGE_VERSION\s+"(\d+\.\d+[.\d]*)"', text)
            if m:
                return m.group(1)
    return None


def libtorch_paths(path):
    """home, lib and include of the LibTorch whose main library is `path` (<home>/lib/<library>)."""
    lib = os.path.dirname(path)
    home = os.path.dirname(lib)
    return {'home': home, 'lib': lib, 'include': os.path.join(home, 'include')}


def found_paths_with_versions(paths, _with):
    """For task/setup's detection: {library: {'output': version, 'features': ...}} of the found libraries."""
    found = {}
    for path in paths:
        path = path[1:] if path.startswith('!') else path
        if not os.path.isfile(path):
            continue
        p = libtorch_paths(path)
        version = libtorch_version(p['home'])
        if version:
            found[path] = {'output': version, 'features': {'paths': p, 'with': _with}}
    return found


def add_path_features(tool, paths):
    """check_features of both tools: home, lib, include (and their quoted forms) of each found library."""
    for p in paths:
        x = libtorch_paths(p['path'])
        path_features = p.setdefault('features', {}).setdefault('paths', {})
        for k in ('home', 'lib', 'include'):
            path_features[k] = x[k]
            path_features['q' + k] = tool.cm.q(x[k])
    return paths
