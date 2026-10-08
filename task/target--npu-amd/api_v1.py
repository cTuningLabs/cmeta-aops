"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import os
import re

from task_c36be4b9314a45e0.api.ctask import InitCTask

# The NPUs of the Linux kernel's amdxdna driver (drivers/accel/amdxdna): PCI device ID and revision ->
# the driver's NPU generation, the platform, the XDNA architecture
AMD_NPUS = {
    ('1502', None): ('npu1', 'Phoenix / Hawk Point', 'xdna1'),
    ('17f0', '10'): ('npu4', 'Strix Point', 'xdna2'),
    ('17f0', '11'): ('npu5', 'Strix Halo', 'xdna2'),
    ('17f0', '20'): ('npu6', 'Krackan Point', 'xdna2'),
    ('17f2', None): ('npu3', 'data centre (PF)', 'xdna2'),
    ('17f3', None): ('npu3', 'data centre (VF)', 'xdna2'),
    ('1b0b', None): ('npu3', 'data centre (PF)', 'xdna2'),
    ('1b0c', None): ('npu3', 'data centre (VF)', 'xdna2'),
}
AMD_NPU_DEVICE_IDS = {d for d, _ in AMD_NPUS}


def describe(vendor, device, revision = None):
    """The device as a feature: its PCI ID with the generation, the platform and the architecture when known."""
    vendor, device = vendor.lower().replace('0x', ''), device.lower().replace('0x', '')
    rev = revision.lower().replace('0x', '').lstrip('0') if revision else None
    rev = rev.zfill(2) if rev is not None else None
    d = {'pci_id': f'{vendor}:{device}'}
    if rev is not None:
        d['revision'] = rev
    info = AMD_NPUS.get((device, rev)) or AMD_NPUS.get((device, None))
    if info:
        d['npu_generation'], d['platform'], d['architecture'] = info
    return d


def amd_npus_on_pci(sys_pci = '/sys/bus/pci/devices'):
    """The AMD NPUs on the PCI bus (vendor 0x1022, a device ID of AMD_NPUS), with or without a driver."""
    npus = []
    for d in sorted(glob.glob(os.path.join(sys_pci, '*'))):
        try:
            with open(os.path.join(d, 'vendor')) as f:
                vendor = f.read().strip().lower().replace('0x', '')
            with open(os.path.join(d, 'device')) as f:
                device = f.read().strip().lower().replace('0x', '')
            revision = None
            try:
                with open(os.path.join(d, 'revision')) as f:
                    revision = f.read().strip()
            except OSError:
                pass
        except OSError:
            continue
        if vendor == '1022' and device in AMD_NPU_DEVICE_IDS:
            npus.append(describe(vendor, device, revision))
    return npus


def parse_npus(data, uname):
    """
    The AMD NPUs in the probe's output: on Windows the Name/DeviceID/Status/DriverVersion blocks of the
    ComputeAccelerator devices, on Linux "accel0 amdxdna 0x1022 0x17f0 0x20 1.1.2.64 RyzenAI-npu6" lines.
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
                m = re.search(r'VEN_([0-9A-Fa-f]{4})&DEV_([0-9A-Fa-f]{4})(?:&SUBSYS_[0-9A-Fa-f]+)?(?:&REV_([0-9A-Fa-f]{2}))?', block.get('DeviceID', ''))
                if m and m.group(1).lower() == '1022':
                    d = describe(m.group(1), m.group(2), m.group(3))
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
            if driver == 'amdxdna' or (vendor == '1022' and device in AMD_NPU_DEVICE_IDS):
                d = describe(vendor, device, parts[4] if len(parts) > 4 else None)
                d.update({'node': f'/dev/accel/{node}', 'driver': driver})
                if len(parts) > 5 and parts[5] != '-':
                    d['firmware'] = parts[5]
                if len(parts) > 6 and parts[6] != '-':
                    d['name'] = parts[6]
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
                - **features** (dict): devices (pci_id, revision, npu_generation, platform, architecture;
                  on Linux node, driver, firmware, name; on Windows name, driver_version, status) and the
                  probe's output.
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
        A cached target keeps the NPU of the run that created the entry, possibly on another machine
        (a copied or shared CMETA_HOME). The probe ran again in this call ('uses'), so its output
        describes this machine now.
        """

        temp_file = ctx['tasks']['local'].get('generate-temp-file-target-npu-amd', {}).get('temp_file')

        if temp_file and os.path.isfile(temp_file):
            r = self._detect(ctx)
            if self.cm.catch_error(r): return r

            result['features'] = r['features']

        return {'return': 0, 'result': result}

    ############################################################
    def _detect(self, ctx):

        local = ctx['tasks']['local']
        temp_file = local['generate-temp-file-target-npu-amd']['temp_file']
        encoding = local.get('encoding')

        if not os.path.isfile(temp_file):
            return self.cm.error(f'temp file "{temp_file}" not found in "{__file__}" ({__name__})')

        r = self.cm.utils.files.read_file(temp_file, encoding = encoding, remove_after_read = True)
        if self.cm.catch_error(r): return r

        data = r['data'].strip()

        uname = ctx['tasks']['global']['host']['os']['uname']
        devices = parse_npus(data, uname)

        if not devices:
            if uname == 'windows':
                hint = 'no "ComputeAccelerator" device from AMD (VEN_1022) in the Device Manager (the Ryzen AI NPU driver installs it)'
            else:
                hint = 'no accel device of the amdxdna driver in /sys/class/accel'
                on_pci = amd_npus_on_pci()
                if on_pci:
                    d = on_pci[0]
                    hint += (f', although the {d.get("platform", "AMD")} NPU ({d["pci_id"]}) is on the PCI bus: the kernel lacks '
                             f'its amdxdna driver (Linux 6.14 and later; Ubuntu 26.04 has it) or its firmware '
                             f'(amdnpu/ in linux-firmware); the kernel log tells which: sudo dmesg | grep -i xdna')
            return self.cm.error(f'the AMD NPU is not detected: {hint}')

        return {'return': 0, 'features': {'output': data, 'devices': devices}}
