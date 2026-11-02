"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask
from task_c36be4b9314a45e0.api import ios

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            **kwargs
    ):
        """
        The GPU of the iPhone or iPad that target--ios-cpu selected, as a Metal probe run on the device reports
        it: the device name and architecture, the highest Apple / Common / Metal GPU family, the threadgroup and
        buffer limits, the working set, raytracing and other features.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **features** (dict): the GPU (metal: the probe's answer)
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        r = ios.probe(self, ctx, os.path.join(self.artifact_path, 'src', 'probe.m'), ['Foundation', 'Metal'], 'cmeta-probe-gpu')
        if self.cm.catch_error(r): return r
        p = r['probe']

        cpu = (ctx['tasks']['global'].get('target--ios-cpu') or {}).get('features') or {}

        features = {
          'platform': 'ios',
          'device': {k: cpu.get(k) for k in ('udid', 'name', 'marketing_name', 'product_type', 'os_version')},
          'name': p.get('name'),
          'architecture': p.get('architecture'),
          'apple_family': p.get('apple_family'),
          'common_family': p.get('common_family'),
          'metal_version': p.get('metal_version'),
          'unified_memory': p.get('unified_memory'),
          'metal': p,
        }

        if con:
            print ('')
            print (f'{space}INFO: iOS GPU: {p.get("name")} ({p.get("architecture") or "?"}), Apple GPU family {p.get("apple_family")}, '
                   f'Metal {p.get("metal_version")}, threadgroup up to {p.get("max_threads_per_threadgroup")}, '
                   f'buffer up to {int(p.get("max_buffer_length") or 0) // (1024 * 1024)} MB, '
                   f'working set {int(p.get("recommended_max_working_set_size") or 0) // (1024 * 1024)} MB, '
                   f'raytracing {p.get("raytracing")}')

        return {'return': 0, 'features': features}
