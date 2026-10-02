"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Unpacking Debian packages without root, for tools that install a vendor's release packages into
the cMeta cache (tool/intel-gpu-runtime, tool/intel-npu-runtime): dpkg-deb -x when there is one,
else the ar archive and its data.tar (zstd through Python 3.14, the zstandard module or the zstd
tool); nothing is installed in the system.

    from tool_c393ba5c6fa14f66.api.common_deb import sha256_of, ar_members, zstd_decompress, extract_deb
"""

import hashlib
import io
import os
import shutil
import subprocess
import tarfile


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def ar_members(path):
    """The members of an ar archive (a .deb): {name: bytes}."""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:8] != b'!<arch>\n':
        raise ValueError(f'{path} is not an ar archive (.deb)')
    members, pos = {}, 8
    while pos + 60 <= len(data):
        name = data[pos:pos + 16].decode('ascii', 'replace').strip().rstrip('/')
        size = int(data[pos + 48:pos + 58].decode('ascii').strip())
        members[name] = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size % 2)
    return members


def zstd_decompress(blob):
    """zstd without root: Python 3.14's compression.zstd, the zstandard module, or the zstd tool."""
    try:
        from compression import zstd
        return zstd.decompress(blob)
    except ImportError:
        pass
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompressobj().decompress(blob)
    except ImportError:
        pass
    if shutil.which('zstd'):
        r = subprocess.run(['zstd', '-dc'], input = blob, capture_output = True)
        if r.returncode == 0:
            return r.stdout
    raise RuntimeError('unpacking the packages needs dpkg-deb, Python 3.14, the zstandard module or zstd')


def extract_deb(deb, root, use_dpkg = True):
    """Unpack the files of a .deb into root (dpkg-deb -x when there is one: no root needed)."""
    if use_dpkg and shutil.which('dpkg-deb'):
        r = subprocess.run(['dpkg-deb', '-x', deb, root], capture_output = True, text = True)
        if r.returncode == 0:
            return
    members = ar_members(deb)
    name = next((n for n in members if n.startswith('data.tar')), None)
    if not name:
        raise ValueError(f'{deb} has no data.tar')
    blob = members[name]
    if name.endswith('.zst'):
        blob, mode = zstd_decompress(blob), 'r:'
    else:
        mode = {'.xz': 'r:xz', '.gz': 'r:gz', '.bz2': 'r:bz2'}.get(os.path.splitext(name)[1], 'r:')
    os.makedirs(root, exist_ok = True)
    with tarfile.open(fileobj = io.BytesIO(blob), mode = mode) as t:
        try:
            t.extractall(root, filter = 'data')
        except TypeError:   # Python < 3.12 (and without the backported filter)
            t.extractall(root)
