"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import sys

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

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
