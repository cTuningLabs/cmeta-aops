"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import glob
import json
import os
import sys

from tool_c393ba5c6fa14f66.api.ctool import InitCTool


def gpu_nodes(dev = '/dev'):
    """
    The device nodes through which a Linux machine can use a GPU: DRM render nodes (the kernel
    driver of an AMD, Intel or NVIDIA GPU, also of the GPUs of Arm SoCs, which are not on PCI),
    WSL2's /dev/dxg (Mesa's dzn runs Vulkan on the Windows GPU), NVIDIA's and AMD's compute nodes.
    [] when there is none: Mesa would then give Vulkan on the CPU only (llvmpipe).
    """
    found = sorted(glob.glob(os.path.join(dev, 'dri', 'renderD*')))
    for name in ('dxg', 'nvidia0', 'kfd'):
        if os.path.exists(os.path.join(dev, name)):
            found.append(os.path.join(dev, name))
    return found


def pci_display_devices(sys_pci = '/sys/bus/pci/devices'):
    """
    PCI display controllers (class 0x03xxxx) as '<address> <vendor>:<device>'. One without a
    device node has no driver here, or was not passed into the container (WSL2 shows its virtual
    GPUs as 3D controllers even then), so Mesa could not use it.
    """
    found = []
    for d in sorted(glob.glob(os.path.join(sys_pci, '*'))):
        try:
            with open(os.path.join(d, 'class')) as f:
                cls = f.read().strip()
            if not cls.lower().startswith('0x03'):
                continue
            ids = []
            for name in ('vendor', 'device'):
                with open(os.path.join(d, name)) as f:
                    ids.append(f.read().strip().lower().replace('0x', ''))
            found.append(f'{os.path.basename(d)} {ids[0]}:{ids[1]}')
        except OSError:
            continue
    return found

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect(self,
               ctx: dict,
               params: dict = {},
    ):
        """
        Ask the Vulkan loader for the devices (vulkan_probe.py in a separate process: a broken
        driver must not take cMeta down). The tool is the loader library, its version the
        loader's Vulkan version; features.devices lists the devices, features.gpus the GPUs.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL vulkan api_v1 detect")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        probe = os.path.join(os.path.dirname(__file__), 'vulkan_probe.py')

        cmd = f'{self.cm.q(sys.executable)} {self.cm.q(probe)}'

        tool_path = params.get('tool_path')
        if tool_path:
            cmd += f' --loader {self.cm.q(tool_path)}'

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'ctx': ctx,
              'arg1': 'cmd,c9ba0a88df394d7f',
              'cmd': cmd,
              'env': params.get('env', {}),
              'timeout': params.get('timeout') or 120,
              'con': False,
              'verbose': False,
              'text_cmd': 'RUN:',
              'capture_output': True,
              'fail_if_nonzero_return_code': False,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        try:
            data = json.loads(rx.get('stdout', ''))
        except ValueError:
            data = {'error': f'unexpected output of {probe}: {rx.get("stdout", "")[:500]} {rx.get("stderr", "")[:500]}'}

        loader = data.get('loader')
        if not loader or not os.path.isfile(loader):
            if con and verbose:
                print (f'{space}INFO: no Vulkan loader: {data.get("error")}')

            # Without a GPU, installing Mesa (with sudo) would only give Vulkan on the CPU: say so
            # before any install, unless --with.allow_cpu asks for that
            uname = ctx['tasks']['global']['host']['os']['uname']
            if uname == 'linux' and not params.get('with', {}).get('allow_cpu') and not gpu_nodes():
                pci = pci_display_devices()
                x = (f'PCI display devices {", ".join(pci)} have no device node here (no driver, or not passed '
                     f'into the container)') if pci else 'no GPU'
                return self.cm.error(f'no Vulkan loader, and no GPU to use: {x}; no /dev/dri render node, no '
                                     f'/dev/dxg. Mesa would only run Vulkan on the CPU (llvmpipe): '
                                     f'--with.allow_cpu installs it anyway')

            return {'return': 0, 'parsed_paths_with_versions': []}

        devices = data.get('devices', [])

        if con and verbose:
            print (f'{space}INFO: Vulkan loader {loader} ({data.get("instance_version")}), {len(devices)} device(s)')
            for d in devices:
                print (f'{space}  {d["index"]}) {d["name"]} ({d["type"]}, Vulkan {d["api_version"]}, '
                       f'driver {d["driver_version"]}, {d["device_local_memory_mib"]} MiB)')

        features = {
          'devices': devices,
          'gpus': [d for d in devices if d.get('type') != 'cpu'],
          'vendors': sorted({d['vendor'] for d in devices}),
          'paths': {'loader': loader},
        }
        if data.get('error'):
            features['error'] = data['error']

        tool = {'path': loader,
                'detected_version': data.get('instance_version'),
                'features': features}

        return {'return': 0, 'parsed_paths_with_versions': [tool]}
