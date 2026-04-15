"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import json
import os
import re

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL rocm api_v1 check_features")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        _with = params.get('with', {})
        env = _with.get('env', {})
        timeout = _with.get('timeout')

        for p in paths:
            # Parsing standard output
            output = p['output'].split('\n')

            versions = {}

            features = p.setdefault('features', {})

            for o in output:
                oo = o.split(':')

                if len(oo) == 2:
                    versions[oo[0].strip().lower()] = oo[1].strip()

            if versions:
                features_versions = features.setdefault('versions', {})
                features_versions.update(versions)

            # Checking devices
            rocm_smi_path = p['path'] # path to rocm-smi

            rocm_smi_cmd = rocm_smi_path + ' --showbus --showuniqueid --showproductname --showdriverversion --showmeminfo vram --json'

            ii = {'category': 'task,c36be4b9314a45e0',
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': rocm_smi_cmd,
                  'env': env,
                  'timeout': timeout,
                  'con': con, 
                  'quiet': quiet,
                  'verbose': verbose, 
                  'text_cmd': 'RUN:', 
                  'capture_output': True,
                  # Important to be able to continue processing detect/install/build
                  'fail_if_nonzero_return_code': False, 
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx): return rx

            returncode = rx['returncode']                                            

            if returncode != 0:
                # Fallback for older rocm-smi versions that may not support one of the explicit flags.
                rocm_smi_cmd = rocm_smi_path + ' --json'

                ii['cmd'] = rocm_smi_cmd
                rx = self.cm.access(ii)
                if self.cm.catch_error(rx): return rx

                returncode = rx['returncode']

            if returncode != 0:
                return self.cm.error(f'failed to detect ROCm capabilities using CMD "{rocm_smi_cmd}" in "{__file__}"')

            if returncode == 0:
                rocm_smi_json = parse_json(rx.get('stdout', ''))
                devices = parse_rocm_smi_devices(rocm_smi_json)

                if devices:
                    # Propagate a single known driver version if present on all devices.
                    driver_versions = {d.get('driver_version') for d in devices if d.get('driver_version')}
                    if len(driver_versions) == 1:
                        features_versions = features.setdefault('versions', {})
                        features_versions.setdefault('driver version', next(iter(driver_versions)))

                features['devices'] = devices

        return {'return':0, 'paths':paths}

def parse_json(s):
    s = (s or '').strip()
    if not s:
        return {}

    try:
        return json.loads(s)
    except Exception:
        return {}


def _get_alias(d, aliases):
    if not isinstance(d, dict):
        return None

    folded = {str(k).strip().lower(): v for k, v in d.items()}

    for alias in aliases:
        if alias.lower() in folded:
            return folded[alias.lower()]

    return None


def _parse_int(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    text = str(value)
    # Keep digits only, so values like "4,096 MiB" or "17163091968 B" can be parsed.
    digits = ''.join(ch for ch in text if ch.isdigit())
    if not digits:
        return None

    try:
        return int(digits)
    except Exception:
        return None


def _parse_memory_total(gpu_data):
    memory_total = _get_alias(gpu_data, [
        'vram total memory (b)',
        'vram total memory (bytes)',
        'memory total (b)',
        'memory total (bytes)',
    ])
    memory_total_mib = _get_alias(gpu_data, [
        'vram total memory (mib)',
        'memory total (mib)',
    ])

    total_bytes = _parse_int(memory_total)
    total_mib = _parse_int(memory_total_mib)

    if total_bytes is None and total_mib is not None:
        total_bytes = total_mib * 1024 * 1024

    return total_bytes, total_mib


def parse_rocm_smi_devices(rocm_json):
    if not isinstance(rocm_json, dict):
        return []

    cleaned_devices = []

    for top_key, top_value in rocm_json.items():
        if not isinstance(top_value, dict):
            continue

        # Typical rocm-smi JSON format uses keys like "card0", "card1", etc.
        if not re.match(r'^(card|gpu)\d+$', str(top_key).strip().lower()):
            continue

        index = _parse_int(re.sub(r'\D+', '', str(top_key)))
        name = _get_alias(top_value, [
            'card series',
            'card model',
            'device name',
            'product name',
            'gpu name',
        ])
        uuid = _get_alias(top_value, [
            'unique id',
            'gpu uuid',
            'serial number',
        ])
        bus_id = _get_alias(top_value, [
            'pci bus',
            'pci bus id',
            'pci bus address',
            'pcie bus',
        ])
        driver_version = _get_alias(top_value, [
            'driver version',
            'amdgpu driver version',
        ])
        compute_cap = _get_alias(top_value, [
            'gpu gfx',
            'gfx version',
            'asic',
            'target gfx version',
        ])

        memory_total, memory_total_mib = _parse_memory_total(top_value)

        cleaned = {}

        if index is not None:
            cleaned['index'] = index
        if name is not None:
            cleaned['name'] = str(name).strip()
        if uuid is not None:
            cleaned['uuid'] = str(uuid).strip()
        if bus_id is not None:
            cleaned['pci.bus_id'] = str(bus_id).strip()
        if driver_version is not None:
            cleaned['driver_version'] = str(driver_version).strip()
        if compute_cap is not None:
            cleaned['compute_cap'] = str(compute_cap).strip()
        if memory_total is not None:
            cleaned['memory.total'] = memory_total
        if memory_total_mib is not None:
            cleaned['memory.total [MiB]'] = f'{memory_total_mib} MiB'

        cleaned_devices.append(cleaned)

    return cleaned_devices
