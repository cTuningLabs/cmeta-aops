"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

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
            self.logger.debug("RUNNING TOOL cuda api_v1 check_features")

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
                    versions[oo[0].strip().lower()] = oo[1].strip().lower()

            if versions:
                features_versions = features.setdefault('versions', {})
                features_versions.update(versions)

            # Checking devices
            nvidia_smi_path = self.cm.q(p['path']) # path to nvidia-smi

            nvidia_smi_cmd = nvidia_smi_path + ' --query-gpu=index,name,uuid,pci.bus_id,driver_version,memory.total,compute_cap --format=csv'

            ii = {'category': 'task,c36be4b9314a45e0',
                  'command': 'run',
                  'ctx': ctx,
                  'arg1': 'cmd,c9ba0a88df394d7f',
                  'cmd': nvidia_smi_cmd,
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
                return self.cm.error(f'failed to detect CUDA capabilties using CMD "{nvidia_smi_cmd}" in "{__file__}"')

            if returncode == 0:
                import csv
                from io import StringIO

                reader = csv.DictReader(StringIO(rx['stdout']))

                devices = list(reader)

                updated_devices = clean_devices(devices)

                # Check capacity
                compute_cap_int_min = None
                compute_cap_int_max = None
                for device in updated_devices:
                    compute_cap = device.get('compute_cap')
                    compute_cap_int = int(compute_cap.replace('.',''))
                    device['compute_cap_int'] = compute_cap_int

                    if not compute_cap_int_min or compute_cap_int_min > compute_cap_int:
                        compute_cap_int_min = compute_cap_int
                    if not compute_cap_int_max or compute_cap_int_max < compute_cap_int:
                        compute_cap_int_max = compute_cap_int

                features['compute_cap_int_min'] = compute_cap_int_min
                features['compute_cap_int_max'] = compute_cap_int_max

                features['devices'] = updated_devices

                # process versions to simplify further analysis
                cuda_version = features.get('versions',{}).get('cuda version')
                if cuda_version:
                    features['versions']['cuda_version_int'] = int(cuda_version.replace('.',''))

        return {'return':0, 'paths':paths}

def clean_devices(devices):
    import re

    cleaned_devices = []

    for device in devices:
        cleaned = {}

        for raw_key, raw_value in device.items():
            key = raw_key.strip()
            value = raw_value.strip()

            # Keep cleaned original key/value
            if key == 'index':
                value = int(value)

            cleaned[key] = value

            # Detect keys with [MiB]
            match = re.search(r"\[MiB\]", key)
            if match:
                # Remove [MiB] from key and normalize spacing
                new_key = re.sub(r"\s*\[MiB\]", "", key).strip()

                # Parse leading numeric part from value like "4096 MiB"
                num_match = re.match(r"^\s*(\d+)", value)
                if num_match:
                    mib_value = int(num_match.group(1))
                    cleaned[new_key] = mib_value * 1024 * 1024

        cleaned_devices.append(cleaned)

    return cleaned_devices

