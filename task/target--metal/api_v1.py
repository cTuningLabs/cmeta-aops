"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

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

        return {'return':0}

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
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        ctx_tasks_control = ctx_tasks['run_control']

        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        result = {'return':0}

        r = self._detect(ctx)
        if self.cm.catch_error(r): return r

        result['features'] = r['features']

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        A cached target keeps the devices of the run that created the entry, possibly on another
        Mac (a copied or shared CMETA_HOME). system_profiler ran again in this call ('uses'),
        so its output describes this machine now.
        """

        output_file = ctx['tasks']['local'].get('generate-temp-file-target-metal', {}).get('temp_file')

        if output_file and os.path.isfile(output_file):
            r = self._detect(ctx)
            if self.cm.catch_error(r): return r

            result['features'] = r['features']

        return {'return': 0, 'result': result}

    ############################################################
    def _detect(self, ctx):
        """
        The Metal devices in the output of system_profiler SPDisplaysDataType (the temp file).
        """

        output_file = ctx['tasks']['local']['generate-temp-file-target-metal']['temp_file']

        r = self.cm.utils.files.read_file(output_file, remove_after_read = True)
        if self.cm.catch_error(r): return r

        metal_present = False

        devices = []
        for d in r['data'].get('SPDisplaysDataType', []):
            metal = d.get('spdisplays_mtlgpufamilysupport')
            if metal:
                j = metal.find('_metal')
                if j>0:
                    metal_present = True
                    metal_version = metal[j+6:]
                    d['metal_version'] = metal_version
                    devices.append(d)

        if not metal_present:
            return self.cm.error(f'Apple Metal accelerator is not detected in "{__file__}"')

        return {'return': 0, 'features': {'devices': devices}}

