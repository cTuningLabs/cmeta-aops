"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

List the Vulkan devices of this machine through the Vulkan loader itself (ctypes), so neither
the Vulkan SDK nor vulkaninfo is needed - only a loader (vulkan-1.dll, libvulkan.so.1,
libvulkan.1.dylib or MoltenVK) and the GPU drivers' ICDs.

    python vulkan_probe.py [--loader <path to the loader library>]

Prints one JSON object: {"loader", "instance_version", "devices": [{"name", "type", "vendor",
"vendor_id", "device_id", "api_version", "driver_version", "device_local_memory_mib"}]}
or {"error": ...}. Run as a separate process: a broken driver can take the process down.
"""

import ctypes
import ctypes.util
import json
import os
import sys

VK_SUCCESS = 0
VK_INCOMPLETE = 5
VK_STRUCTURE_TYPE_APPLICATION_INFO = 0
VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1
VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR = 0x00000001
PORTABILITY_EXT = b'VK_KHR_portability_enumeration'

DEVICE_TYPES = {0: 'other', 1: 'integrated-gpu', 2: 'discrete-gpu', 3: 'virtual-gpu', 4: 'cpu'}
VENDORS = {0x10DE: 'nvidia', 0x8086: 'intel', 0x1002: 'amd', 0x1022: 'amd', 0x106B: 'apple',
           0x5143: 'qualcomm', 0x13B5: 'arm', 0x1010: 'imagination', 0x14E4: 'broadcom',
           0x10005: 'mesa', 0x19E5: 'huawei', 0x1AE0: 'google'}


class VkApplicationInfo(ctypes.Structure):
    _fields_ = [('sType', ctypes.c_int32), ('pNext', ctypes.c_void_p),
                ('pApplicationName', ctypes.c_char_p), ('applicationVersion', ctypes.c_uint32),
                ('pEngineName', ctypes.c_char_p), ('engineVersion', ctypes.c_uint32),
                ('apiVersion', ctypes.c_uint32)]


class VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [('sType', ctypes.c_int32), ('pNext', ctypes.c_void_p), ('flags', ctypes.c_uint32),
                ('pApplicationInfo', ctypes.POINTER(VkApplicationInfo)),
                ('enabledLayerCount', ctypes.c_uint32), ('ppEnabledLayerNames', ctypes.c_void_p),
                ('enabledExtensionCount', ctypes.c_uint32),
                ('ppEnabledExtensionNames', ctypes.POINTER(ctypes.c_char_p))]


class VkExtensionProperties(ctypes.Structure):
    _fields_ = [('extensionName', ctypes.c_char * 256), ('specVersion', ctypes.c_uint32)]


def api_version(v):
    return f'{(v >> 22) & 0x7F}.{(v >> 12) & 0x3FF}.{v & 0xFFF}'


def driver_version(v, vendor_id):
    # Vendors pack the driver version their own way (as vulkaninfo decodes it)
    if vendor_id == 0x10DE:
        return f'{(v >> 22) & 0x3FF}.{(v >> 14) & 0xFF}.{(v >> 6) & 0xFF}.{v & 0x3F}'
    if vendor_id == 0x8086 and os.name == 'nt':
        return f'{v >> 14}.{v & 0x3FFF}'
    return api_version(v)


def candidate_loaders():
    env = os.environ.get('VULKAN_SDK')
    if os.name == 'nt':
        names = [os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'vulkan-1.dll')]
        if env:
            names.append(os.path.join(env, 'Bin', 'vulkan-1.dll'))
        return names + ['vulkan-1.dll']
    if sys.platform == 'darwin':
        names = []
        if env:
            names += [os.path.join(env, 'lib', 'libvulkan.1.dylib'), os.path.join(env, 'lib', 'libMoltenVK.dylib')]
        names += ['/opt/homebrew/lib/libvulkan.1.dylib', '/usr/local/lib/libvulkan.1.dylib',
                  '/opt/homebrew/lib/libMoltenVK.dylib', '/usr/local/lib/libMoltenVK.dylib']
        return names + ['libvulkan.1.dylib']
    names = []
    if env:
        names.append(os.path.join(env, 'lib', 'libvulkan.so.1'))
    found = ctypes.util.find_library('vulkan')
    if found:
        names.append(found)
    return names + ['libvulkan.so.1']


def loaded_path(name):
    """The file a library loaded by its soname comes from (Linux: /proc/self/maps)."""
    if os.path.isabs(name) or not os.path.isfile('/proc/self/maps'):
        return name
    base = os.path.basename(name).split('.so')[0]
    with open('/proc/self/maps') as f:
        for line in f:
            part = line.split()[-1] if line.split() else ''
            if os.path.basename(part).startswith(base + '.so'):
                return part
    return name


def load_loader(path = None):
    tried = []
    for p in ([path] if path else candidate_loaders()):
        if not p:
            continue
        if os.path.isabs(p) and not os.path.isfile(p):
            continue
        try:
            lib = ctypes.CDLL(p)
            return lib, loaded_path(p)
        except OSError as e:
            tried.append(f'{p}: {e}')
    raise OSError('no Vulkan loader could be loaded' + (' (' + '; '.join(tried) + ')' if tried else ''))


def probe(loader_path = None):
    lib, loader = load_loader(loader_path)

    gipa = lib.vkGetInstanceProcAddr
    gipa.restype = ctypes.c_void_p
    gipa.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

    def fn(instance, name, restype, *argtypes):
        addr = gipa(instance, name)
        if not addr:
            return None
        return ctypes.CFUNCTYPE(restype, *argtypes)(addr)

    result = {'loader': os.path.abspath(loader) if os.path.isfile(loader) else loader}

    version = ctypes.c_uint32(0x00400000)  # 1.0 when vkEnumerateInstanceVersion is missing
    enum_version = fn(None, b'vkEnumerateInstanceVersion', ctypes.c_int32, ctypes.POINTER(ctypes.c_uint32))
    if enum_version:
        enum_version(ctypes.byref(version))
    result['instance_version'] = api_version(version.value)

    enum_ext = fn(None, b'vkEnumerateInstanceExtensionProperties', ctypes.c_int32,
                  ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(VkExtensionProperties))
    extensions = []
    if enum_ext:
        n = ctypes.c_uint32(0)
        enum_ext(None, ctypes.byref(n), None)
        props = (VkExtensionProperties * n.value)()
        enum_ext(None, ctypes.byref(n), props)
        extensions = [p.extensionName for p in props[:n.value]]

    app = VkApplicationInfo(VK_STRUCTURE_TYPE_APPLICATION_INFO, None, b'cmeta-vulkan-probe', 1, b'cmeta', 1,
                            min(version.value, (1 << 22) | (3 << 12)))
    ext_names = (ctypes.c_char_p * 1)(PORTABILITY_EXT)
    info = VkInstanceCreateInfo(VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, None, 0, ctypes.pointer(app), 0, None, 0, None)
    if PORTABILITY_EXT in extensions:
        # MoltenVK (macOS) devices are listed only with portability enumeration
        info.flags = VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR
        info.enabledExtensionCount = 1
        info.ppEnabledExtensionNames = ext_names

    create = fn(None, b'vkCreateInstance', ctypes.c_int32, ctypes.POINTER(VkInstanceCreateInfo), ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p))
    instance = ctypes.c_void_p()
    rc = create(ctypes.byref(info), None, ctypes.byref(instance))
    if rc != VK_SUCCESS:
        result['error'] = f'vkCreateInstance failed ({rc}): no Vulkan driver (ICD) available'
        result['devices'] = []
        return result

    devices = []
    try:
        enum_dev = fn(instance, b'vkEnumeratePhysicalDevices', ctypes.c_int32, ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p))
        get_props = fn(instance, b'vkGetPhysicalDeviceProperties', None, ctypes.c_void_p, ctypes.c_void_p)
        get_mem = fn(instance, b'vkGetPhysicalDeviceMemoryProperties', None, ctypes.c_void_p, ctypes.c_void_p)

        n = ctypes.c_uint32(0)
        enum_dev(instance, ctypes.byref(n), None)
        handles = (ctypes.c_void_p * max(n.value, 1))()
        enum_dev(instance, ctypes.byref(n), handles)

        for i in range(n.value):
            # VkPhysicalDeviceProperties: apiVersion, driverVersion, vendorID, deviceID, deviceType (5 x 4 bytes),
            # deviceName[256], ... (only the leading fields are read; the buffer covers the whole struct)
            buf = ctypes.create_string_buffer(4096)
            get_props(handles[i], buf)
            api, drv, vendor_id, device_id, dtype = (int.from_bytes(buf.raw[o:o + 4], 'little') for o in (0, 4, 8, 12, 16))
            name = buf.raw[20:276].split(b'\0', 1)[0].decode('utf-8', 'replace')

            # VkPhysicalDeviceMemoryProperties: memoryTypeCount, memoryTypes[32] (8 bytes each),
            # memoryHeapCount at 260, memoryHeaps[16] at 264 (size uint64 + flags uint32 + padding)
            mem = ctypes.create_string_buffer(1024)
            get_mem(handles[i], mem)
            heaps = int.from_bytes(mem.raw[260:264], 'little')
            local = 0
            for h in range(min(heaps, 16)):
                off = 264 + 16 * h
                size = int.from_bytes(mem.raw[off:off + 8], 'little')
                flags = int.from_bytes(mem.raw[off + 8:off + 12], 'little')
                if flags & 1:
                    local = max(local, size)

            entry = {'index': len(devices),
                            'name': name,
                            'type': DEVICE_TYPES.get(dtype, str(dtype)),
                            'vendor': VENDORS.get(vendor_id, hex(vendor_id)),
                            'vendor_id': hex(vendor_id),
                            'device_id': hex(device_id),
                            'api_version': api_version(api),
                            'driver_version': driver_version(drv, vendor_id),
                            'device_local_memory_mib': local // (1024 * 1024)}
            # A driver registered twice (two ICD manifests) lists its device twice
            same = [d for d in devices if {k: v for k, v in d.items() if k != 'index'} == {k: v for k, v in entry.items() if k != 'index'}]
            if not same:
                devices.append(entry)
    finally:
        destroy = fn(instance, b'vkDestroyInstance', None, ctypes.c_void_p, ctypes.c_void_p)
        if destroy:
            destroy(instance, None)

    result['devices'] = devices
    return result


if __name__ == '__main__':
    loader_path = None
    if '--loader' in sys.argv:
        loader_path = sys.argv[sys.argv.index('--loader') + 1]
    try:
        print(json.dumps(probe(loader_path), indent = 2))
    except Exception as e:
        print(json.dumps({'error': f'{type(e).__name__}: {e}', 'devices': []}, indent = 2))
