"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask, intel_gpu_on_pci

INTEL_GPU_RUNTIME = 'intel-gpu-runtime,1fce5a1fbba34a81'

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
        We need this function to resolve name if not provided,
        to be able to customize storage_key and cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        r = self.cm.check_params(params, [
                'flags', 
            ], __name__)
        if self.cm.catch_error(r): return r

        flags = params.get('flags')

        flags = flags if flags else ''

#        if os.name == 'nt':
#            if '/EHsc' not in flags:
#                flags += ' /EHsc'

        ctx['tasks']['local']['flags'] = flags

        return {'return':0}

    ############################################################
    def intel_gpu_runtime(self, ctx, desc = None, params = {}, extra_desc_params = None):
        """
        On Linux x86_64 with an Intel GPU, set up Intel's GPU compute runtime (Level Zero and OpenCL: detected,
        else installed without root). It exports its libraries and its ICD to the steps that follow; without
        it SYCL sees the CPU only, and the test runs there.

        Every other machine runs the test as before, on the device SYCL picks: Windows has the runtime in the
        graphics driver, and a machine without an Intel GPU has no use for it.
        """

        host = ctx['tasks']['global']['host']['os']
        if host['uname'] != 'linux' or host.get('uarch') != 'amd64' or not intel_gpu_on_pci():
            return {'return': 0}

        c = ctx['control']
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'ctx': ctx,
                            'arg1': 'setup,a2f9b61079ce4333', 'name': INTEL_GPU_RUNTIME,
                            'con': c.get('con', False), 'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False)})
        if self.cm.catch_error(r): return r

        return {'return': 0}

