"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The host compilers a CUDA toolkit supports, as its include/crt/host_config.h checks them (nvcc
stops with "unsupported ... version" otherwise), and the version ranges they give for the cMeta
tools of those compilers.
"""

import os
import re


def limits(text):
    """
    The limits in the text of host_config.h:
      msvc:  (low, high) - _MSC_VER from low to high, high excluded (1910, 1950: VS 2017 to 2022);
      gcc:   the newest GCC major version (14);
      clang: the first clang major version that is too new (20).
    What the file does not check is left out.
    """
    out = {}
    m = re.search(r'#if\s+_MSC_VER\s*<\s*(\d+)\s*\|\|\s*_MSC_VER\s*>=\s*(\d+)', text)
    if m:
        out['msvc'] = (int(m.group(1)), int(m.group(2)))
    m = re.search(r'#if\s+__GNUC__\s*>\s*(\d+)', text)
    if m:
        out['gcc'] = int(m.group(1))
    m = re.search(r'#if\s+\(__clang_major__\s*>=\s*(\d+)\)\s*\|\|\s*\(__clang_major__\s*<\s*3\)', text)
    if m:
        out['clang'] = int(m.group(1))
    return out


def read_limits(cuda_home):
    """The limits of the toolkit in cuda_home, {} when it has no host_config.h."""
    path = os.path.join(cuda_home or '', 'include', 'crt', 'host_config.h')
    if not cuda_home or not os.path.isfile(path):
        return {}
    with open(path, encoding = 'utf-8', errors = 'replace') as f:
        return limits(f.read())


def cl_version(msc_ver):
    """cl.exe's version for _MSC_VER: 1950 -> 19.50."""
    return f'{msc_ver // 100}.{msc_ver % 100:02d}'


def version_ranges(lim):
    """
    The versions (--use.<storage key>.version) that keep each host compiler tool within the
    limits: the Visual Studio installation and its MSVC (both have cl.exe's version), g++ and
    clang++.
    """
    out = {}
    if 'msvc' in lim:
        low, high = lim['msvc']
        spec = f'>={cl_version(low)},<{cl_version(high)}'
        out['microsoft-visual-studio'] = spec
        out['msvc'] = spec
    if 'gcc' in lim:
        out['gcc-cpp'] = f'<{lim["gcc"] + 1}'
    if 'clang' in lim:
        out['clang-cpp'] = f'<{lim["clang"]}'
    return out


def numbers(version):
    return [int(x) for x in re.findall(r'\d+', str(version or ''))]


def unsupported(name, version, lim):
    """Why the toolkit rejects this host compiler (its cMeta tool and version), or None."""
    n = numbers(version)
    if not n:
        return None
    if name == 'msvc' and 'msvc' in lim and len(n) >= 2:
        low, high = lim['msvc']
        msc = n[0] * 100 + n[1]
        if not low <= msc < high:
            return f'MSVC {version} (_MSC_VER {msc}) is outside the MSVC {cl_version(low)} to {cl_version(high - 1)} it supports'
    if name == 'gcc-cpp' and 'gcc' in lim and n[0] > lim['gcc']:
        return f'g++ {version} is newer than the GCC {lim["gcc"]} it supports'
    if name == 'clang-cpp' and 'clang' in lim and n[0] >= lim['clang']:
        return f'clang++ {version} is newer than the clang {lim["clang"] - 1} it supports'
    return None
