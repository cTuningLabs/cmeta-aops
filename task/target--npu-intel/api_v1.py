"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re

from task_c36be4b9314a45e0.api.ctask import InitCTask

# The NPUs of the Linux kernel's intel_vpu driver (drivers/accel/ivpu): PCI device ID ->
# platform and NPU generation (the driver's IVPU_HW_IP_<gen>)
INTEL_NPUS = {
    '7d1d': ('Meteor Lake', '37xx'),
    'ad1d': ('Arrow Lake', '37xx'),
    '643e': ('Lunar Lake', '40xx'),
    'b03e': ('Panther Lake', '50xx'),
    'fd3e': ('Wildcat Lake', '50xx'),
    'd71d': ('Nova Lake', '60xx'),
}


def describe(vendor, device):
    """The device as a feature: its PCI ID with the platform and the NPU generation when known."""
    vendor, device = vendor.lower(), device.lower()
    platform, generation = INTEL_NPUS.get(device, (None, None))
    d = {'pci_id': f'{vendor}:{device}'}
    if platform:
        d['platform'] = platform
        d['npu_generation'] = generation
    return d


def parse_npus(data, uname):
    """
    The Intel NPUs in the probe's output: on Windows the Name/DeviceID/Status/DriverVersion
    blocks of the ComputeAccelerator devices, on Linux "accel0 intel_vpu 0x8086 0xb03e" lines.
    """
    npus = []
    if uname == 'windows':
        block = {}
        for line in data.splitlines() + ['']:
            key, sep, value = line.partition(':')
            if sep and key.strip():
                block[key.strip()] = value.strip()
                continue
            if block:
                # PCI\VEN_8086&DEV_B03E&SUBSYS_...&REV_04\3&11583659&0&58
                m = re.search(r'VEN_([0-9A-Fa-f]{4})&DEV_([0-9A-Fa-f]{4})', block.get('DeviceID', ''))
                if m and m.group(1).lower() == '8086':
                    d = describe(m.group(1), m.group(2))
                    d['name'] = block.get('Name', '')
                    for k, f in (('DriverVersion', 'driver_version'), ('Status', 'status'), ('DeviceID', 'instance_id')):
                        if block.get(k):
                            d[f] = block[k]
                    npus.append(d)
                block = {}
    else:
        for line in data.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            node, driver, vendor, device = parts[:4]
            vendor, device = vendor.lower().replace('0x', ''), device.lower().replace('0x', '')
            if driver == 'intel_vpu' or (vendor == '8086' and device in INTEL_NPUS):
                d = describe(vendor, device)
                d.update({'node': node, 'driver': driver})
                npus.append(d)
    return npus


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **features** (dict): devices (pci_id, platform, npu_generation, name,
                  driver_version on Windows, node and driver on Linux) and the probe's output.
        """

        r = self._detect(ctx)
        if self.cm.catch_error(r): return r

        return {'return': 0, 'features': r['features']}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        A cached target keeps the NPU of the run that created the entry, possibly on another
        machine (a copied or shared CMETA_HOME). The probe ran again in this call ('uses'),
        so its output describes this machine now.
        """

        temp_file = ctx['tasks']['local'].get('generate-temp-file-target-npu-intel', {}).get('temp_file')

        if temp_file and os.path.isfile(temp_file):
            r = self._detect(ctx)
            if self.cm.catch_error(r): return r

            result['features'] = r['features']

        return {'return': 0, 'result': result}

    ############################################################
    def _detect(self, ctx):

        local = ctx['tasks']['local']
        temp_file = local['generate-temp-file-target-npu-intel']['temp_file']
        encoding = local.get('encoding')

        if not os.path.isfile(temp_file):
            return self.cm.error(f'temp file "{temp_file}" not found in "{__file__}" ({__name__})')

        r = self.cm.utils.files.read_file(temp_file, encoding = encoding, remove_after_read = True)
        if self.cm.catch_error(r): return r

        data = r['data'].strip()

        uname = ctx['tasks']['global']['host']['os']['uname']
        devices = parse_npus(data, uname)

        if not devices:
            hint = ('a "ComputeAccelerator" device from Intel (VEN_8086) in the Device Manager' if uname == 'windows'
                    else 'an accel device of the intel_vpu driver in /sys/class/accel')
            return self.cm.error(f'the Intel NPU is not detected: no {hint}')

        return {'return': 0, 'features': {'output': data, 'devices': devices}}
