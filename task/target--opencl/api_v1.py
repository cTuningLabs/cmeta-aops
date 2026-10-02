"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import copy
import glob
import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

INTEL_GPU_RUNTIME = 'intel-gpu-runtime,1fce5a1fbba34a81'


def intel_gpu_on_pci(sys_pci = '/sys/bus/pci/devices'):
    """Whether an Intel display controller (vendor 0x8086, class 0x03xxxx) is on the PCI bus."""
    for d in glob.glob(os.path.join(sys_pci, '*')):
        try:
            with open(os.path.join(d, 'vendor')) as f:
                vendor = f.read().strip().lower()
            with open(os.path.join(d, 'class')) as f:
                cls = f.read().strip().lower()
        except OSError:
            continue
        if vendor == '0x8086' and cls.startswith('0x03'):
            return True
    return False


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def intel_gpu_runtime(self, ctx, desc = None, params = {}, extra_desc_params = None):
        """
        On Linux x86_64 with an Intel GPU, set up Intel's GPU compute runtime (detected, else
        installed without root): it exports its ICD (OCL_ICD_FILENAMES), so OpenCL lists the
        Intel GPU next to the others. --use.target--opencl.skip_intel_runtime skips it.
        """

        host = ctx['tasks']['global']['host']['os']
        if host['uname'] != 'linux' or host.get('uarch') != 'amd64' or params.get('skip_intel_runtime'):
            return {'return': 0}
        if not intel_gpu_on_pci():
            return {'return': 0}

        c = ctx['control']
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                            'arg1': 'setup,a2f9b61079ce4333', 'name': INTEL_GPU_RUNTIME,
                            'con': c.get('con', False), 'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False)})
        if self.cm.catch_error(r): return r

        return {'return': 0}

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs
    ):
        """
        The OpenCL platforms and devices of this machine as the target's features (from
        tool/opencl). Fails without any device, and when only CPU devices (Intel's CPU runtime,
        PoCL) exist: an opencl run there would compute on the CPU. --use.target--opencl.allow_cpu
        accepts them.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **features** (dict): platforms, devices, gpus, vendors, version, paths.library.
        """

        features = ctx['tasks']['global']['opencl']['features']

        r = self._check(ctx, features, kwargs)
        if self.cm.catch_error(r): return r

        return {'return': 0, 'features': features}

    ############################################################
    def _check(self, ctx, features, params):
        """A GPU among the OpenCL devices, or CPU devices with allow_cpu."""

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        devices = features.get('devices', [])
        if not devices:
            x = features.get('error') or 'the OpenCL library lists no device'
            return self.cm.error(f'no OpenCL device found ({x}): install or update the GPU driver '
                                 f'(on Linux also the ICD loader: "cx tool setup opencl --install")')

        if not features.get('gpus'):
            names = ', '.join(f'{d["name"]} ({d["platform"]})' for d in devices)
            if not params.get('allow_cpu'):
                return self.cm.error(f'OpenCL sees no GPU, only {names}: an opencl run would compute on the CPU. '
                                     f'Install the GPU\'s driver, or accept them with --use.target--opencl.allow_cpu')
            if con:
                print ('')
                print (f'{space}WARNING: OpenCL sees no GPU, only {names}: allowed (allow_cpu)')

        return {'return': 0}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        A cached target keeps the devices of the run that created the entry; tool/opencl was set
        up again in this call ('uses'), so its features describe this machine now, and are checked
        again.
        """

        features = ctx['tasks']['global'].get('opencl', {}).get('features')
        if features:
            result['features'] = copy.deepcopy(features)

            r = self._check(ctx, features, params)
            if self.cm.catch_error(r): return r

        return {'return': 0, 'result': result}
