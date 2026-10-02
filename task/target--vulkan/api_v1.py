"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import copy

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs
    ):
        """
        The Vulkan devices of this machine as the target's features (from tool/vulkan).
        Fails without any device, and when only CPU devices (Mesa's llvmpipe) exist: a vulkan run
        there would compute on the CPU. --use.target--vulkan.allow_cpu accepts them (to test
        Vulkan code without a GPU).

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **features** (dict): devices, gpus, vendors, paths.loader.
        """

        features = ctx['tasks']['global']['vulkan']['features']

        r = self._check(ctx, features, kwargs)
        if self.cm.catch_error(r): return r

        return {'return': 0, 'features': features}

    ############################################################
    def _check(self, ctx, features, params):
        """A GPU among the Vulkan devices, or CPU devices with allow_cpu."""

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        devices = features.get('devices', [])
        if not devices:
            x = features.get('error') or 'the Vulkan loader lists no device'
            return self.cm.error(f'no Vulkan device found ({x}): install or update the GPU driver '
                                 f'(Mesa on Linux, MoltenVK on macOS: "cx tool setup vulkan --install")')

        if not features.get('gpus'):
            names = ', '.join(d['name'] for d in devices)
            if not params.get('allow_cpu'):
                return self.cm.error(f'Vulkan sees no GPU, only CPU devices ({names}): a vulkan run would compute on '
                                     f'the CPU. Install the GPU\'s driver, or accept them with '
                                     f'--use.target--vulkan.allow_cpu')
            if con:
                print ('')
                print (f'{space}WARNING: Vulkan sees no GPU, only CPU devices ({names}): allowed (allow_cpu)')

        return {'return': 0}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        A cached target keeps the devices of the run that created the entry, possibly on another
        machine (a copied or shared CMETA_HOME) or before a driver change. tool/vulkan was set up
        again in this call ('uses'), so its features describe this machine now.
        """

        features = ctx['tasks']['global'].get('vulkan', {}).get('features')
        if features:
            result['features'] = copy.deepcopy(features)

            # The same check as for a fresh target: the machine may have lost its GPU driver
            r = self._check(ctx, features, params)
            if self.cm.catch_error(r): return r

        return {'return': 0, 'result': result}
