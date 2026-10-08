"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import copy
import glob
import os

from task_c36be4b9314a45e0.api.ctask import InitCTask


def gfx_name(target_version):
    """
    The GPU family name of the kernel's gfx_target_version (kfd topology): 110502 -> gfx1152,
    90400 -> gfx904, 90a00 is spelt 90a (minor and stepping are one hex digit each).
    """
    v = int(target_version)
    major, minor, step = v // 10000, (v // 100) % 100, v % 100
    return f'gfx{major}{minor:x}{step:x}'


def gfx_from_kfd(topology = '/sys/class/kfd/kfd/topology/nodes'):
    """
    The GPU families the kernel's ROCm interface (kfd) exposes, in node order: the nodes with compute
    units (the CPU node has none), from their properties file. Empty where there is no kfd (not Linux,
    no amdgpu, no access).
    """
    names = []
    for node in sorted(glob.glob(os.path.join(topology, '*')), key = lambda p: int(os.path.basename(p)) if os.path.basename(p).isdigit() else 0):
        try:
            with open(os.path.join(node, 'properties')) as f:
                props = dict(line.split(None, 1) for line in f if ' ' in line)
        except OSError:
            continue
        if int(props.get('simd_count', 0)) > 0 and props.get('gfx_target_version', '0').strip() != '0':
            names.append(gfx_name(props['gfx_target_version'].strip()))
    return names


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
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


                  os: ['Windows', 'Linux', 'macOS']
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if 'rocm' not in ctx['tasks']['global']:
            return self.cm.error(f'ROCm target not found in "{__file__}" ({__name__})')

        result = {
          'return':0,
          'features': ctx['tasks']['global']['rocm']['features'],
        }

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        _result = {'return':0}

        # A cached target keeps the features of the run that created the entry, possibly on another
        # machine (a copied or shared CMETA_HOME) or before a GPU or driver change. The rocm tool
        # was set up again in this call ('uses'), so its features describe this machine now.
        tool_features = ctx['tasks']['global'].get('rocm', {}).get('features')
        if tool_features:
            result['features'] = copy.deepcopy(tool_features)

        _with = params.get('with', {})

        ver = _with.get('ver')

        if ver:
            result['features']['ver'] = ver

        # The GPU families from the kernel (kfd topology), so that what builds for or installs on this
        # GPU knows its name (gfx942, gfx1152) without any ROCm tool: the devices get it in order
        features = result.setdefault('features', {})
        gfx = gfx_from_kfd()
        if gfx:
            features['gfx'] = gfx
            for device, name in zip(features.get('devices', []), gfx):
                device.setdefault('gfx', name)

        # --use.target--rocm.gfx_override=<major.minor.step>: the GPU presented to the ROCm runtime as
        # another family (HSA_OVERRIDE_GFX_VERSION), for prebuilt kernels that do not carry its own.
        # Only on request: a framework built for the GPU breaks under an override.
        override = params.get('gfx_override') or _with.get('gfx_override')
        if override and str(override).lower() not in ('none', 'false', '0', ''):
            features['gfx_override'] = str(override)
            result['_aggregate'] = {'env': {'HSA_OVERRIDE_GFX_VERSION': str(override)}}
            if ctx['control'].get('con', False):
                print(f'INFO: the ROCm runtime will see the GPU as gfx version {override} (HSA_OVERRIDE_GFX_VERSION, --use.target--rocm.gfx_override)')

        _result['result'] = result

        return _result
