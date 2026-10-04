"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json

from task_c36be4b9314a45e0.api.ctask import InitCTask

VK_DEVICE_TYPES = {0: 'other', 1: 'integrated-gpu', 2: 'discrete-gpu', 3: 'virtual-gpu', 4: 'cpu'}
VENDORS = {0x13B5: 'arm', 0x5143: 'qualcomm', 0x1010: 'imagination', 0x144D: 'samsung',
           0x1002: 'amd', 0x10DE: 'nvidia', 0x8086: 'intel', 0x1AE0: 'google', 0x10005: 'mesa'}

OPENCL_PATHS = ('/vendor/lib64/libOpenCL.so', '/system/vendor/lib64/libOpenCL.so', '/system/lib64/libOpenCL.so',
                '/vendor/lib64/libOpenCL-pixel.so')


def vk_version(v):
    v = int(v)
    return f'{(v >> 22) & 0x7F}.{(v >> 12) & 0x3FF}.{v & 0xFFF}'


def parse_vkjson(text):
    """The Vulkan devices of 'cmd gpu vkjson': name, type, vendor, API version, driver version."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    devices = []
    for d in data.get('devices', []):
        p = d.get('properties', {})
        vendor_id = int(p.get('vendorID', 0))
        devices.append({'name': p.get('deviceName', ''),
                        'type': VK_DEVICE_TYPES.get(int(p.get('deviceType', 0)), 'other'),
                        'vendor': VENDORS.get(vendor_id, hex(vendor_id)),
                        'vendor_id': vendor_id,
                        'api_version': vk_version(p.get('apiVersion', 0)),
                        'driver_version': int(p.get('driverVersion', 0)),
                        'device_id': int(p.get('deviceID', 0))})
    return devices


def parse_gles(line):
    """'GLES: ARM, Mali-G720-Immortalis MC12, OpenGL ES 3.2 v1.r44p1-...' as vendor, renderer, version."""
    line = (line or '').strip()
    if not line.startswith('GLES:'):
        return {}
    parts = [x.strip() for x in line[len('GLES:'):].split(',', 2)]
    keys = ('vendor', 'renderer', 'version')
    return {k: v for k, v in zip(keys, parts)}


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _adb_shell(self, ctx, serial, shell_cmd):
        adb = ctx['tasks']['global']['adb']['qpath']
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                            'arg1': 'cmd,c9ba0a88df394d7f', 'cmd': f'{adb} -s {serial} shell "{shell_cmd}"',
                            'con': False, 'verbose': False, 'capture_output': True,
                            'fail_if_nonzero_return_code': False})
        if self.cm.catch_error(r): return r
        return {'return': 0, 'stdout': (r.get('stdout') or '').replace('\r', '')}

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs
    ):
        """
        The GPU of the Android device that target--android-cpu selected: its Vulkan devices, GLES
        driver and OpenCL library (whether apps may load it: the vendor's public libraries).
        Fails when the device has neither a Vulkan GPU nor an OpenCL library.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **serial** (str): the device.
                - **features** (dict): vulkan.devices, gles, opencl, gpus, hardware.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        serial = ctx['tasks']['global']['target--android-cpu']['serial']

        r = self._adb_shell(ctx, serial, 'cmd gpu vkjson')
        if self.cm.catch_error(r): return r
        vulkan = parse_vkjson(r['stdout'])

        r = self._adb_shell(ctx, serial, "dumpsys SurfaceFlinger | grep -m1 'GLES:'")
        if self.cm.catch_error(r): return r
        gles = parse_gles(r['stdout'])

        r = self._adb_shell(ctx, serial, 'ls ' + ' '.join(OPENCL_PATHS) + ' 2>/dev/null; echo ==; '
                                         'cat /vendor/etc/public.libraries.txt 2>/dev/null; echo ==; '
                                         'getprop ro.hardware.vulkan; getprop ro.hardware.egl; getprop ro.soc.model')
        if self.cm.catch_error(r): return r
        parts = r['stdout'].split('==')
        libs = [x.strip() for x in parts[0].split() if x.strip()]
        public = [x.strip() for x in (parts[1] if len(parts) > 1 else '').splitlines() if x.strip()]
        props = [x.strip() for x in (parts[2] if len(parts) > 2 else '').splitlines()]
        props += [''] * (3 - len(props))

        opencl = {'library': libs[0] if libs else None,
                  'public': any(x.startswith('libOpenCL') for x in public),
                  # from the adb shell, a vendor libOpenCL.so may need the vendor (sphal) namespace
                  # to find its driver: load it with android_load_sphal_library (libvndksupport)
                  'shell_note': 'load it through android_load_sphal_library() when it finds no platform'}

        gpus = [d for d in vulkan if d['type'] != 'cpu']
        if not gpus and not opencl['library']:
            return self.cm.error(f'the Android device {serial} has no Vulkan GPU and no OpenCL library')

        features = {'serial': serial,
                    'vulkan': {'devices': vulkan},
                    'gles': gles,
                    'opencl': opencl,
                    'gpus': [d['name'] for d in gpus] or ([gles['renderer']] if gles.get('renderer') else []),
                    'hardware': {'vulkan': props[0], 'egl': props[1], 'soc': props[2]}}

        if con:
            print ('')
            print (f'{space}INFO: Android GPU of {serial}: {", ".join(features["gpus"]) or "?"} '
                   f'(Vulkan {", ".join(d["api_version"] for d in gpus) or "none"}; '
                   f'OpenCL {opencl["library"] or "none"}{", public" if opencl["public"] else ""})')

        return {'return': 0, 'serial': serial, 'features': features}
