"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

List the OpenCL platforms and devices of this machine through the OpenCL library itself (ctypes),
so neither an OpenCL SDK nor clinfo is needed - only the ICD loader (OpenCL.dll, libOpenCL.so.1,
the macOS OpenCL framework) and the drivers' ICDs.

    python opencl_probe.py [--library <path to the OpenCL library>]

Prints one JSON object: {"library", "platforms": [{"name", "vendor", "version", "devices":
[{"name", "type", "vendor", "vendor_id", "version", "driver_version", "compute_units",
"max_clock_mhz", "global_memory_mib"}]}]} or {"error": ...}. Run as a separate process: a broken
driver can take the process down.
"""

import ctypes
import ctypes.util
import glob
import json
import os
import sys

CL_SUCCESS = 0
CL_PLATFORM_NOT_FOUND_KHR = -1001
CL_DEVICE_NOT_FOUND = -1
CL_DEVICE_TYPE_ALL = 0xFFFFFFFF

PLATFORM_VERSION, PLATFORM_NAME, PLATFORM_VENDOR = 0x0901, 0x0902, 0x0903
DEVICE_TYPE, DEVICE_VENDOR_ID, DEVICE_MAX_COMPUTE_UNITS = 0x1000, 0x1001, 0x1002
DEVICE_MAX_CLOCK_FREQUENCY, DEVICE_GLOBAL_MEM_SIZE = 0x100C, 0x101F
DEVICE_NAME, DEVICE_VENDOR, DRIVER_VERSION, DEVICE_VERSION = 0x102B, 0x102C, 0x102D, 0x102F

DEVICE_TYPES = [(4, 'gpu'), (2, 'cpu'), (8, 'accelerator'), (16, 'custom')]
VENDORS = {0x10DE: 'nvidia', 0x8086: 'intel', 0x1002: 'amd', 0x1022: 'amd', 0x106B: 'apple',
           0x1027F00: 'apple', 0x5143: 'qualcomm', 0x13B5: 'arm', 0x1010: 'imagination', 0x10006: 'pocl'}


def candidate_libraries():
    if os.name == 'nt':
        return [os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'OpenCL.dll'), 'OpenCL.dll']
    if sys.platform == 'darwin':
        return ['/System/Library/Frameworks/OpenCL.framework/OpenCL']
    names = ['libOpenCL.so.1', 'libOpenCL.so']
    found = ctypes.util.find_library('OpenCL')
    if found:
        names.append(found)
    for d in ('/usr/lib/x86_64-linux-gnu', '/usr/lib/aarch64-linux-gnu', '/usr/lib64', '/usr/lib',
              '/usr/local/cuda/lib64', '/opt/rocm/lib'):
        names += sorted(glob.glob(os.path.join(d, 'libOpenCL.so*')))
    return names


def loaded_path(name):
    """
    The file a library comes from, as a path that exists: by its soname on Linux, the file mapped
    in /proc/self/maps; on macOS the framework's folder (the library itself is in the system's
    shared cache, not on disk).
    """
    if sys.platform == 'darwin' and '.framework/' in name:
        return name.split('.framework/')[0] + '.framework'
    if os.path.isabs(name) or not os.path.isfile('/proc/self/maps'):
        return os.path.abspath(name) if os.path.isfile(name) else name
    base = os.path.basename(name).split('.so')[0]
    with open('/proc/self/maps') as f:
        for line in f:
            part = line.split()[-1] if line.split() else ''
            if os.path.basename(part).startswith(base + '.so'):
                return part
    return name


def load(path = None):
    """The OpenCL library (path, or the usual places) and the file it comes from."""
    errors = []
    for name in ([path] if path else candidate_libraries()):
        if os.path.isabs(name) and not os.path.isfile(name) and '.framework/' not in name:
            continue
        try:
            return ctypes.CDLL(name), loaded_path(name)
        except OSError as e:
            errors.append(f'{name}: {e}')
    raise OSError('no OpenCL library' + (': ' + '; '.join(errors[-3:]) if errors else ''))


def info_str(get, obj, param):
    size = ctypes.c_size_t(0)
    if get(obj, param, 0, None, ctypes.byref(size)) != CL_SUCCESS or not size.value:
        return ''
    buf = ctypes.create_string_buffer(size.value)
    if get(obj, param, size, buf, None) != CL_SUCCESS:
        return ''
    return buf.value.decode('utf-8', 'replace').strip()


def info_num(get, obj, param, ctype):
    v = ctype(0)
    return v.value if get(obj, param, ctypes.sizeof(v), ctypes.byref(v), None) == CL_SUCCESS else None


def probe(path = None):
    lib, name = load(path)
    vp = ctypes.c_void_p
    lib.clGetPlatformIDs.argtypes = [ctypes.c_uint32, ctypes.POINTER(vp), ctypes.POINTER(ctypes.c_uint32)]
    lib.clGetPlatformInfo.argtypes = [vp, ctypes.c_uint32, ctypes.c_size_t, vp, ctypes.POINTER(ctypes.c_size_t)]
    lib.clGetDeviceIDs.argtypes = [vp, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(vp), ctypes.POINTER(ctypes.c_uint32)]
    lib.clGetDeviceInfo.argtypes = [vp, ctypes.c_uint32, ctypes.c_size_t, vp, ctypes.POINTER(ctypes.c_size_t)]
    for f in (lib.clGetPlatformIDs, lib.clGetPlatformInfo, lib.clGetDeviceIDs, lib.clGetDeviceInfo):
        f.restype = ctypes.c_int32

    out = {'library': name, 'platforms': []}
    n = ctypes.c_uint32(0)
    rc = lib.clGetPlatformIDs(0, None, ctypes.byref(n))
    if rc == CL_PLATFORM_NOT_FOUND_KHR or (rc == CL_SUCCESS and not n.value):
        out['error'] = f'the OpenCL library lists no platform ({rc}): no driver ICD is registered'
        return out
    if rc != CL_SUCCESS:
        out['error'] = f'clGetPlatformIDs failed: {rc}'
        return out
    platforms = (vp * n.value)()
    lib.clGetPlatformIDs(n.value, platforms, None)

    for p in platforms:
        plat = {'name': info_str(lib.clGetPlatformInfo, p, PLATFORM_NAME),
                'vendor': info_str(lib.clGetPlatformInfo, p, PLATFORM_VENDOR),
                'version': info_str(lib.clGetPlatformInfo, p, PLATFORM_VERSION), 'devices': []}
        nd = ctypes.c_uint32(0)
        if lib.clGetDeviceIDs(p, CL_DEVICE_TYPE_ALL, 0, None, ctypes.byref(nd)) == CL_SUCCESS and nd.value:
            devices = (vp * nd.value)()
            lib.clGetDeviceIDs(p, CL_DEVICE_TYPE_ALL, nd.value, devices, None)
            for d in devices:
                t = info_num(lib.clGetDeviceInfo, d, DEVICE_TYPE, ctypes.c_uint64) or 0
                vendor_id = info_num(lib.clGetDeviceInfo, d, DEVICE_VENDOR_ID, ctypes.c_uint32)
                mem = info_num(lib.clGetDeviceInfo, d, DEVICE_GLOBAL_MEM_SIZE, ctypes.c_uint64)
                plat['devices'].append({
                    'name': info_str(lib.clGetDeviceInfo, d, DEVICE_NAME),
                    'type': next((name for bit, name in DEVICE_TYPES if t & bit), 'other'),
                    'vendor': VENDORS.get(vendor_id, info_str(lib.clGetDeviceInfo, d, DEVICE_VENDOR).lower()),
                    'vendor_id': vendor_id,
                    'version': info_str(lib.clGetDeviceInfo, d, DEVICE_VERSION),
                    'driver_version': info_str(lib.clGetDeviceInfo, d, DRIVER_VERSION),
                    'compute_units': info_num(lib.clGetDeviceInfo, d, DEVICE_MAX_COMPUTE_UNITS, ctypes.c_uint32),
                    'max_clock_mhz': info_num(lib.clGetDeviceInfo, d, DEVICE_MAX_CLOCK_FREQUENCY, ctypes.c_uint32),
                    'global_memory_mib': mem // 2**20 if mem else None,
                })
        out['platforms'].append(plat)
    return out


def main():
    path = None
    if '--library' in sys.argv:
        path = sys.argv[sys.argv.index('--library') + 1]
    try:
        out = probe(path)
    except (OSError, AttributeError) as e:
        out = {'error': str(e)}
    print(json.dumps(out))


if __name__ == '__main__':
    main()
