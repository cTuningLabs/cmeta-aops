"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import shlex

from program_22788f3c30d04e6d.api.cprogram import InitCProgram
from program_22788f3c30d04e6d.api import common_llama_cpp

class CProgram(InitCProgram):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize1(self,
                   ctx: dict,
                   **misc
    ):
        """
        """

        desc = misc.get('desc', {})
        params = misc.get('params', {})

        model = params.get('model')
        prompt = params.get('prompt')

        if model or prompt:
            _use = ctx['tasks'].setdefault('use', {})
            if model:
                _use.setdefault('model',{})['filename'] = os.path.abspath(model)
            if prompt:
                _use.setdefault('dataset',{})['filename'] = os.path.abspath(prompt)

        return {'return':0}

    ############################################################
    def customize_run(self,
                      ctx: dict,
                      **misc
    ):
        """
        The llama.cpp flags of this run from the targets and the offload parameters (--ngl,
        --devices, --split_mode, --tensor_split, --main_gpu, --threads): see common_llama_cpp.
        """

        params = misc.get('params') or ctx['tasks']['local'].get('params', {})
        compute = ctx['tasks']['global']['target']['compute']

        flags, settings = common_llama_cpp.run_flags(compute, params)

        # The OpenVINO build runs where GGML_OPENVINO_DEVICE says: the NPU for npu-intel
        device = common_llama_cpp.openvino_device(compute)
        if device:
            ctx['tasks']['local'].setdefault('run_time_env', {})['GGML_OPENVINO_DEVICE'] = device
            settings['openvino_device'] = device

        ctx['tasks']['local']['llama_cpp_compute_flags'] = flags
        ctx['tasks']['local']['llama_cpp_settings'] = settings

        return {'return':0}

    ############################################################
    def prepare_target_run(self,
                           ctx: dict,
                           **misc
    ):
        """
        The binary and the model of the run: here, or on the Android device (--compute=android-cpu),
        where the release and the model are kept under /data/local/tmp between runs.
        """

        tool = ctx['tasks']['global']['llama-cpp']
        backend = tool.get('features', {}).get('with', {}).get('backend', 'cpu')
        common_llama_cpp.target_run(self.cm, ctx, tool['completion_path'],
                                    f"release-b{tool.get('version')}-{backend}")

        return {'return':0}

    ############################################################
    def finish_llama_run(self,
                         ctx: dict,
                         desc: dict = {},
                         **misc,
    ):
        """
        After the run: clean output.txt, record llama.cpp's timings in perf.json (result['perf']).
        """

        return common_llama_cpp.finish_llama_run(self, ctx, desc, **misc)
