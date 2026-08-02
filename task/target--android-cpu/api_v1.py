"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import copy
import re
import subprocess

from task_c36be4b9314a45e0.api.ctask import InitCTask

# TO BE UPDATED WITH "cmd" or running tool "adb" (with timeout, env, etc) !!!

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TASK target--android-cpu customize_cache_artifact")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        adb_path = ctx_tasks['global']['adb']['qpath']

        env = params.get('env')
        serial = params.get('serial')

        ###########################################################################################
        # Get connected devices
        cmd = f'{adb_path} devices'

        ii = {
            'category': self.category_alias + ',' + self.category_uid,
            'command': 'run',
            'ctx': ctx,
            'arg1': 'cmd,c9ba0a88df394d7f',
            'cmd': cmd,
            'env': env,
            'con': con,
            'quiet': quiet,
            'verbose': verbose,
            'text_cmd': 'RUN:',
            'print_extra_line': False,
            'fail_if_nonzero_return_code': False,
            'capture_output': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx):
            return rx

        returncode = rx['returncode']
        if returncode > 0:
            err = f'CMD "{cmd}" failed with return code {returncode} in "{__file__}"'
            return self.cm.error(err, 99)

        stdout = rx['stdout']

        devices = []
        for line in stdout.splitlines():
            line = line.strip()
            # Skip the header line and empty lines
            if not line or line.startswith('List of devices'):
                continue
            parts = line.split('\t', 1)
            if len(parts) == 2:
                _serial = parts[0]

                if not serial or serial.strip().lower() == _serial.strip().lower():
                    devices.append({'serial': _serial, 'state': parts[1]})

        if not devices:
            x = f' with s/n "{serial}"' if serial else ''
            return self.cm.error(f'no attached adb devices found{x} in "{__file__}"')

        device = 0
        if len(devices)>1:
            print ('')
            print (f'{space}More than 1 adb device found:')
            print ('')

            for idev in range(0, len(devices)):
                dev = devices[idev]
                print(f'{space}{idev}) {dev["serial"]}  ({dev["state"]})')

            print ('')

            if quiet:
                print (f'{space}Quiely selected 0')     
            else:
                x = input(f'{space}Please select your device or press Enter for 0: ').strip().lower()
                if x != '':
                    device = int(x)
                    if device <0 or device>=len(devices):
                        return self.cm.error(f'wrong device number selected in "{__file__}"')
                    
        # Check selected device
        _device = devices[device]

        # You need to get and update local here because it may be changed by above task
        ctx['tasks']['local']['adb_serial'] = _device['serial']
        ctx['tasks']['local']['adb_state'] = _device['state']

        return {'return':0}

    ############################################################
    def customize_cache_artifact(self,
                                 ctx,
                                 cache_alias_template,
                                 cache_extra_alias,
                                 cache_meta,
                                 cache_tags,
                                 cache_params,
                                 params,
                                 **extra,
        ):

        if self.cm.debug:
            self.logger.debug("RUNNING TASK target--android-cpu customize_cache_artifact")

        serial = ctx['tasks']['local']['adb_serial']

        result = {'return':0}

#        if cache_extra_alias is None: 
#            cache_extra_alias = ''
#
#        if cache_extra_alias !='':
#            cache_extra_alias += self.cache_sep
#
#        cache_extra_alias += f'{serial}'
#
#        result['cache_extra_alias'] = cache_extra_alias
# 
#        result['cache_extra_params'] = {'serial':serial}


        return result

    ############################################################
    def run(self,
            ctx: dict,
            **kwargs
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **devices** (list): List of dicts with keys `serial` and `state`
                  for each attached Android device.


                  os: ['Windows', 'Linux', 'macOS']
        """

        env = kwargs.get('env')

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        adb_path = ctx_tasks['global']['adb']['qpath']

        serial = ctx['tasks']['local']['adb_serial']
        state = ctx['tasks']['local']['adb_state']

        def _run_cmd(cmd: str):
            ii = {
                'category': self.category_alias + ',' + self.category_uid,
                'command': 'run',
                'ctx': ctx,
                'arg1': 'cmd,c9ba0a88df394d7f',
                'cmd': cmd,
                'env': env,
                'con': con,
                'quiet': quiet,
                'verbose': verbose,
                'text_cmd': 'RUN:',
                'print_extra_line': False,
                'fail_if_nonzero_return_code': False,
                'capture_output': True,
            }

            rx = self.cm.access(ii)
            if self.cm.catch_error(rx):
                return rx

            returncode = rx['returncode']
            if returncode > 0:
                err = f'CMD "{cmd}" failed with return code {returncode} in "{__file__}"'
                return self.cm.error(err, 99)

            return {
                'return': 0,
                'stdout': rx.get('stdout', ''),
                'stderr': rx.get('stderr', ''),
            }

        def _run_adb_shell(serial: str, shell_cmd: str):
            cmd = f'{adb_path} -s {serial} shell {shell_cmd}'
            return _run_cmd(cmd)

        def _adb_getprop(serial: str, key: str):
            rx = _run_adb_shell(serial, f'getprop {key}')
            if self.cm.catch_error(rx):
                return rx
            return {'return': 0, 'value': rx['stdout'].strip()}

        def _parse_cpu_range(text: str):
            cpus = set()
            t = (text or '').strip()
            for part in t.split(','):
                part = part.strip()
                if not part:
                    continue
                if '-' in part:
                    xs = part.split('-', 1)
                    try:
                        a = int(xs[0])
                        b = int(xs[1])
                        if b >= a:
                            cpus.update(range(a, b + 1))
                    except ValueError:
                        continue
                else:
                    try:
                        cpus.add(int(part))
                    except ValueError:
                        continue
            return sorted(cpus)

        def _parse_cpuinfo(raw: str):
            info = {}
            feature_tokens = []
            hardware = ''
            model_name = ''
            cpu_architecture = ''
            implementers = set()
            part_ids = set()
            processor_ids = []

            for line in (raw or '').splitlines():
                if ':' not in line:
                    continue
                k, v = line.split(':', 1)
                key = k.strip().lower()
                val = v.strip()

                if key == 'features':
                    feature_tokens.extend([x.strip().lower() for x in val.split() if x.strip()])
                elif key == 'hardware':
                    hardware = val
                elif key == 'model name':
                    model_name = val
                elif key == 'processor':
                    if val.isdigit():
                        processor_ids.append(int(val))
                elif key == 'cpu architecture':
                    cpu_architecture = val
                elif key == 'cpu implementer':
                    implementers.add(val)
                elif key == 'cpu part':
                    part_ids.add(val)

            if processor_ids:
                info['logical_cpu_count'] = len(set(processor_ids))

            info['features_raw_tokens'] = sorted(set(feature_tokens))
            info['hardware'] = hardware
            info['model_name'] = model_name
            info['cpu_architecture'] = cpu_architecture
            info['cpu_signature_hint'] = ','.join(sorted(implementers | part_ids))
            return info

        def _normalize_arch(abi: str, uname_m: str):
            x = (abi or '').lower()
            y = (uname_m or '').lower()
            src = x if x else y

            if 'arm64' in src or 'aarch64' in src or 'v8a' in src:
                return {
                    'arch_raw': src or 'arm64',
                    'arch_normalized': 'arm64',
                    'arch_family': 'arm',
                    'arch_bits': 64,
                }
            if 'armeabi' in src or 'armv7' in src or re.search(r'\barm\b', src):
                return {
                    'arch_raw': src or 'arm',
                    'arch_normalized': 'arm',
                    'arch_family': 'arm',
                    'arch_bits': 32,
                }
            if 'x86_64' in src or 'amd64' in src:
                return {
                    'arch_raw': src or 'x86_64',
                    'arch_normalized': 'x86_64',
                    'arch_family': 'x86',
                    'arch_bits': 64,
                }
            if 'x86' in src:
                return {
                    'arch_raw': src or 'x86',
                    'arch_normalized': 'x86',
                    'arch_family': 'x86',
                    'arch_bits': 32,
                }

            return {
                'arch_raw': src or 'unknown',
                'arch_normalized': src or 'unknown',
                'arch_family': 'unknown',
                'arch_bits': 0,
            }

        ###########################################################################################

        props = {}
        prop_keys = [
            'ro.product.model',
            'ro.build.version.sdk',
            'ro.product.cpu.abi',
            'ro.product.cpu.abilist',
            'ro.product.cpu.abilist32',
            'ro.product.cpu.abilist64',
            'ro.board.platform',
            'ro.soc.model',
            'ro.soc.manufacturer',
            'ro.hardware',
            'ro.build.fingerprint',
        ]

        for key in prop_keys:
            rx = _adb_getprop(serial, key)
            if self.cm.catch_error(rx):
                return rx
            props[key] = rx['value']

        rx = _run_adb_shell(serial, 'uname -m')
        if self.cm.catch_error(rx):
            return rx
        uname_m = rx['stdout'].strip()

        rx = _run_adb_shell(serial, 'cat /proc/cpuinfo')
        if self.cm.catch_error(rx):
            return rx
        cpuinfo_raw = rx['stdout']
        cpuinfo = _parse_cpuinfo(cpuinfo_raw)

        rx = _run_adb_shell(serial, 'cat /sys/devices/system/cpu/online')
        if self.cm.catch_error(rx):
            return rx
        online_cpu_range = rx['stdout'].strip()

        rx = _run_adb_shell(serial, 'cat /sys/devices/system/cpu/possible')
        if self.cm.catch_error(rx):
            return rx
        possible_cpu_range = rx['stdout'].strip()

        abi = props.get('ro.product.cpu.abi', '')
        arch = _normalize_arch(abi, uname_m)

        online_cpus = _parse_cpu_range(online_cpu_range)
        possible_cpus = _parse_cpu_range(possible_cpu_range)

        logical_cpu_count = 0
        if online_cpus:
            logical_cpu_count = len(online_cpus)
        elif possible_cpus:
            logical_cpu_count = len(possible_cpus)
        else:
            logical_cpu_count = int(cpuinfo.get('logical_cpu_count', 0))

        usable_logical_cpu_count = logical_cpu_count
        physical_core_count = len(possible_cpus) if possible_cpus else logical_cpu_count

        raw_tokens = set(cpuinfo.get('features_raw_tokens', []))
        arch_str = str(cpuinfo.get('cpu_architecture', '')).strip()
        is_arm = arch.get('arch_family') == 'arm'

        feature_flags = {
            'aes': ('aes' in raw_tokens),
            'arm_v8': ('v8' in abi.lower() or arch.get('arch_bits') == 64 or arch_str.startswith('8')),
            'asimd': ('asimd' in raw_tokens),
            'avx': ('avx' in raw_tokens),
            'avx2': ('avx2' in raw_tokens),
            'avx512f': ('avx512f' in raw_tokens),
            'crc32': ('crc32' in raw_tokens),
            'neon': ('neon' in raw_tokens or 'asimd' in raw_tokens),
            'sha1': ('sha1' in raw_tokens),
            'sha2': ('sha2' in raw_tokens or 'sha256' in raw_tokens),
            'sse': ('sse' in raw_tokens),
            'sse2': ('sse2' in raw_tokens),
            'sse4_1': ('sse4_1' in raw_tokens),
            'sse4_2': ('sse4_2' in raw_tokens),
            'ssse3': ('ssse3' in raw_tokens),
            'sve': ('sve' in raw_tokens),
            'sve2': ('sve2' in raw_tokens),
            'vmx_or_svm': ('vmx' in raw_tokens or 'svm' in raw_tokens),
        }

        if is_arm and feature_flags['arm_v8']:
            feature_flags['neon'] = feature_flags['neon'] or feature_flags['asimd']

        brand = (
            props.get('ro.soc.model')
            or props.get('ro.product.model')
            or cpuinfo.get('hardware')
            or cpuinfo.get('model_name')
            or uname_m
        )

        extended_identifier = (
            props.get('ro.soc.model')
            or props.get('ro.board.platform')
            or props.get('ro.hardware')
            or brand
        )

        perflevel0 = {
            'logicalcpu': logical_cpu_count,
            'physicalcpu': physical_core_count,
            'perflevel': 0,
        }

        features = {
            'adb_device_serial_number': serial,
            'adb_device_state': state,
            'platform': 'android',
            'arch_bits': arch.get('arch_bits', 0),
            'arch_family': arch.get('arch_family', 'unknown'),
            'arch_normalized': arch.get('arch_normalized', 'unknown'),
            'arch_raw': arch.get('arch_raw', 'unknown'),
            'interpreter_bits': arch.get('arch_bits', 0),
            'logical_cpu_count': logical_cpu_count,
            'logical_cpu_count_sysctl': logical_cpu_count,
            'usable_logical_cpu_count': usable_logical_cpu_count,
            'physical_core_count': physical_core_count,
            'nperflevels': 1,
            'performance_levels': [perflevel0],
            'core_classes': {
                'kind': 'perflevel',
                'groups': {
                    'perflevel0': perflevel0,
                },
            },
            'cpu_signature': {
                'brand': brand,
            },
            'extended_identifier': extended_identifier,
            'features_normalized': feature_flags,
            'features_raw': sorted(raw_tokens),
            'ro.product.model': props.get('ro.product.model', ''),
            'ro.build.version.sdk': props.get('ro.build.version.sdk', ''),
            'ro.product.cpu.abi': props.get('ro.product.cpu.abi', ''),
            'ro.product.cpu.abilist': props.get('ro.product.cpu.abilist', ''),
            'ro.product.cpu.abilist32': props.get('ro.product.cpu.abilist32', ''),
            'ro.product.cpu.abilist64': props.get('ro.product.cpu.abilist64', ''),
            'ro.board.platform': props.get('ro.board.platform', ''),
            'ro.soc.model': props.get('ro.soc.model', ''),
            'ro.soc.manufacturer': props.get('ro.soc.manufacturer', ''),
            'ro.hardware': props.get('ro.hardware', ''),
            'ro.build.fingerprint': props.get('ro.build.fingerprint', ''),
            'uname.machine': uname_m,
            'cpuinfo.cpu_architecture': cpuinfo.get('cpu_architecture', ''),
            'cpuinfo.cpu_signature_hint': cpuinfo.get('cpu_signature_hint', ''),
        }

        ###########################################################################################

#        if con:
#            print ('')
#            for key in sorted(features):
#                ft = features[key]
#                print (f'* {key} = {ft}')

        result = {
          'return': 0,
          'serial': serial,
          'state': state,
          'features': features,
        }

        return result

