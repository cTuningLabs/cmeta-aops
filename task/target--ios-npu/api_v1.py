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
        The Neural Engine of the iPhone or iPad that target--ios-cpu selected, as a Core ML probe run on the
        device reports it (iOS 17 and newer): the compute devices Core ML offers and the Neural Engine's cores.
        Fails when Core ML lists no Neural Engine.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **features** (dict): the Neural Engine (cores) and the compute devices of Core ML
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        r = ios.probe(self, ctx, os.path.join(self.artifact_path, 'src', 'probe.m'), ['Foundation', 'CoreML', 'Metal'],
                      'cmeta-probe-npu', min_os = '17.0')
        if self.cm.catch_error(r): return r
        p = r['probe']

        if not p.get('neural_engine'):
            return self.cm.error('Core ML lists no Neural Engine on this device (its compute devices: '
                                 f'{[d.get("type") for d in p.get("compute_devices") or []]})')

        cpu = (ctx['tasks']['global'].get('target--ios-cpu') or {}).get('features') or {}

        features = {
          'platform': 'ios',
          'device': {k: cpu.get(k) for k in ('udid', 'name', 'marketing_name', 'product_type', 'os_version')},
          'neural_engine': True,
          'neural_engine_cores': p.get('neural_engine_cores'),
          'compute_devices': p.get('compute_devices') or [],
          'stack': 'coreml',
          'coreml': p,
        }

        if con:
            print ('')
            print (f'{space}INFO: iOS NPU: a Neural Engine with {p.get("neural_engine_cores")} cores, reached through Core ML '
                   f'(compute devices: {", ".join(d.get("type") for d in p.get("compute_devices") or [])})')

        return {'return': 0, 'features': features}
