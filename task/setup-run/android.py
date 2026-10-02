"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Files that programs running on an Android device over adb keep on the device between runs: a
folder of binaries and libraries (a llama.cpp release or build) and large inputs (models). They
are pushed under /data/local/tmp once, and again only when they change, so a 400 MB model is not
copied over USB for every run.
"""

import hashlib
import os
import subprocess

# adb push takes several sources to one directory; a few at a time keeps the command short
PUSH_BATCH = 16


def adb(adb_path, serial, *args, timeout = 1800):
    """Run adb for one device: (exit code, stdout and stderr)."""
    try:
        r = subprocess.run([adb_path, '-s', serial] + [str(a) for a in args],
                           capture_output = True, text = True, timeout = timeout)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def stamp_of(files):
    """A stamp of the files' names, sizes and modification times."""
    h = hashlib.sha1()
    for path in sorted(files, key = os.path.basename):
        st = os.stat(path)
        h.update(f'{os.path.basename(path)}:{st.st_size}:{int(st.st_mtime)}\n'.encode('utf-8'))
    return h.hexdigest()[:16]


def push_folder(adb_path, serial, files, device_dir):
    """
    The files into device_dir, unless its .cmeta-stamp says they are there already.
    Returns (pushed, error).
    """
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        return False, f'no such file to push: {missing[0]}'
    stamp = stamp_of(files)
    rc, out = adb(adb_path, serial, 'shell', f'cat {device_dir}/.cmeta-stamp 2>/dev/null')
    if rc == 0 and out.strip() == stamp:
        return False, None
    rc, out = adb(adb_path, serial, 'shell', f'rm -rf {device_dir} && mkdir -p {device_dir}')
    if rc != 0:
        return False, out.strip()
    for i in range(0, len(files), PUSH_BATCH):
        rc, out = adb(adb_path, serial, 'push', *files[i:i + PUSH_BATCH], device_dir + '/')
        if rc != 0:
            return False, out.strip()
    # Pushed from Windows, files are not executable
    rc, out = adb(adb_path, serial, 'shell', f'chmod 755 {device_dir}/* && echo {stamp} > {device_dir}/.cmeta-stamp')
    if rc != 0:
        return False, out.strip()
    return True, None


def push_file(adb_path, serial, host_file, device_path):
    """A (large) file, unless the device has one of the same size there. Returns (pushed, error)."""
    if not os.path.isfile(host_file):
        return False, f'no such file to push: {host_file}'
    size = os.path.getsize(host_file)
    rc, out = adb(adb_path, serial, 'shell', f'stat -c %s {device_path} 2>/dev/null')
    if rc == 0 and out.strip() == str(size):
        return False, None
    parent = device_path.rsplit('/', 1)[0]
    rc, out = adb(adb_path, serial, 'shell', f'mkdir -p {parent}')
    if rc != 0:
        return False, out.strip()
    rc, out = adb(adb_path, serial, 'push', host_file, device_path)
    if rc != 0:
        return False, out.strip()
    return True, None


def device_path(base, path):
    """A device path: absolute as given, else under base (/data/local/tmp)."""
    return path if path.startswith('/') else f'{base}/{path}'
