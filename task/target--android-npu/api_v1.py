"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import re

from task_c36be4b9314a45e0.api.ctask import InitCTask

# The vendor NPU stacks, by a service or library they bring, and how a program started from the
# adb shell can (or cannot) use them besides NNAPI
VENDOR_STACKS = [
    ('samsung-enn', 'vendor.samsung_slsi.hardware.enn', 'Samsung ENN: only from an app (the service refuses adb shell programs)'),
    ('mediatek-apu', 'vendor.mediatek.hardware.apuware', 'MediaTek APU (Neuron runtime): its libraries are vendor-only; NNAPI reaches the NPU'),
    ('google-edgetpu', 'edgetpu', 'Google Tensor TPU: NNAPI (google-edgetpu) and LiteRT (libedgetpu_litert.so)'),
    ('qualcomm-hexagon', 'libcdsprpc', 'Qualcomm Hexagon NPU: QNN, through the public libcdsprpc.so'),
]


def nnapi_devices(service_list, lshal = ''):
    """The NNAPI drivers: AIDL 'android.hardware.neuralnetworks.IDevice/<name>' services and HIDL
    'android.hardware.neuralnetworks@1.x::IDevice/<name>' (lshal)."""
    names = re.findall(r'android\.hardware\.neuralnetworks\.IDevice/([\w.\-]+)', service_list or '')
    names += re.findall(r'android\.hardware\.neuralnetworks@[\d.]+::IDevice/([\w.\-]+)', lshal or '')
    return sorted(set(names))


def vendor_stacks(text):
    """The vendor NPU stacks named in the service list, the vendor libraries or lshal."""
    t = (text or '').lower()
    return [{'name': name, 'note': note} for name, marker, note in VENDOR_STACKS if marker.lower() in t]


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
        The NPU of the Android device that target--android-cpu selected, as a program started
        from the adb shell reaches it: the NNAPI accelerators, and which vendor stack is there
        (Samsung ENN, MediaTek APU, Google EdgeTPU, Qualcomm Hexagon). Fails when NNAPI lists no
        accelerator, saying what the vendor stack needs instead.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **serial** (str): the device.
                - **features** (dict): nnapi.devices, vendor_stacks, soc.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        serial = ctx['tasks']['global']['target--android-cpu']['serial']

        r = self._adb_shell(ctx, serial, 'service list')
        if self.cm.catch_error(r): return r
        services = r['stdout']

        r = self._adb_shell(ctx, serial, 'lshal 2>/dev/null | grep -i neuralnetworks; echo ==; '
                                         "ls /vendor/lib64 2>/dev/null | grep -i -E 'edgetpu|cdsprpc|libenn|neuron'; echo ==; "
                                         'getprop ro.soc.manufacturer; getprop ro.soc.model')
        if self.cm.catch_error(r): return r
        parts = r['stdout'].split('==')
        lshal = parts[0] if parts else ''
        libs = parts[1] if len(parts) > 1 else ''
        soc = ' '.join(x.strip() for x in (parts[2] if len(parts) > 2 else '').splitlines() if x.strip())

        devices = nnapi_devices(services, lshal)
        stacks = vendor_stacks(services + '\n' + libs + '\n' + lshal)

        features = {'serial': serial, 'nnapi': {'devices': devices}, 'vendor_stacks': stacks, 'soc': soc}

        if not devices:
            x = '; '.join(s['note'] for s in stacks) or 'no vendor NPU stack found either'
            return self.cm.error(f'the Android device {serial} ({soc}) has no NNAPI accelerator that a program '
                                 f'started from the adb shell can reach ({x})')

        if con:
            print ('')
            print (f'{space}INFO: Android NPU of {serial} ({soc}): NNAPI {", ".join(devices)}'
                   + (f'; {", ".join(s["name"] for s in stacks)}' if stacks else ''))

        return {'return': 0, 'serial': serial, 'features': features}
