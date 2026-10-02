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
    The device nodes through which a Linux machine can use a GPU (as in tool/vulkan): DRM render
    nodes, WSL2's /dev/dxg, NVIDIA's and AMD's compute nodes. [] when there is none.
    """
    found = sorted(glob.glob(os.path.join(dev, 'dri', 'renderD*')))
    for name in ('dxg', 'nvidia0', 'kfd'):
        if os.path.exists(os.path.join(dev, name)):
            found.append(os.path.join(dev, name))
    return found


def summarize(data):
    """The tool's features from the probe's output: platforms, devices (each with its platform), gpus."""
    platforms = data.get('platforms', [])
    devices = []
    for p in platforms:
        for d in p.get('devices', []):
            devices.append(dict(d, platform = p.get('name', '')))
    versions = [p.get('version', '').split()[1] for p in platforms if len(p.get('version', '').split()) > 1]
    version = max(versions, key = lambda v: [int(x) for x in v.split('.') if x.isdigit()]) if versions else None
    return {'platforms': [{k: v for k, v in p.items() if k != 'devices'} for p in platforms],
            'devices': devices,
            'gpus': [d for d in devices if d.get('type') == 'gpu'],
            'vendors': sorted({d['vendor'] for d in devices if d.get('vendor')}),
            'version': version}


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
        Ask the OpenCL library for the platforms and devices (opencl_probe.py in a separate
        process: a broken driver must not take cMeta down). The tool is the library, its version
        the newest OpenCL version of its platforms; features.devices lists the devices,
        features.gpus the GPUs.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL opencl api_v1 detect")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        probe = os.path.join(os.path.dirname(__file__), 'opencl_probe.py')

        cmd = f'{self.cm.q(sys.executable)} {self.cm.q(probe)}'

        tool_path = params.get('tool_path')
        if tool_path:
            cmd += f' --library {self.cm.q(tool_path)}'

        rx = self.cm.access({'category': 'task,c36be4b9314a45e0',
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
                             'fail_if_nonzero_return_code': False})
        if self.cm.catch_error(rx): return rx

        try:
            data = json.loads(rx.get('stdout', ''))
        except ValueError:
            data = {'error': f'unexpected output of {probe}: {rx.get("stdout", "")[:500]} {rx.get("stderr", "")[:500]}'}

        library = data.get('library')
        if not library:
            if con and verbose:
                print (f'{space}INFO: no OpenCL library: {data.get("error")}')

            # Without a GPU, installing the ICD loader (with sudo) gives nothing to compute on
            uname = ctx['tasks']['global']['host']['os']['uname']
            if uname == 'linux' and not params.get('with', {}).get('allow_cpu') and not gpu_nodes():
                return self.cm.error('no OpenCL library, and no GPU to use here (no /dev/dri render node, no '
                                     '/dev/dxg, no /dev/nvidia0 or /dev/kfd): --with.allow_cpu installs the '
                                     'ICD loader anyway')

            return {'return': 0, 'parsed_paths_with_versions': []}

        features = summarize(data)
        features['paths'] = {'library': library}
        if data.get('error'):
            features['error'] = data['error']

        if con and verbose:
            print (f'{space}INFO: OpenCL library {library}, {len(features["platforms"])} platform(s)')
            for i, d in enumerate(features['devices']):
                print (f'{space}  {i}) {d["name"]} ({d["type"]}, {d["platform"]}, {d["version"]}, '
                       f'{d["compute_units"]} units, {d["global_memory_mib"]} MiB)')

        tool = {'path': library,
                'detected_version': features.get('version') or '0',
                'features': features}

        return {'return': 0, 'parsed_paths_with_versions': [tool]}
