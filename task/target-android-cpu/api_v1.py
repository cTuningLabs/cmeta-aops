"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import copy
import subprocess

from task_c36be4b9314a45e0.api.ctask import InitCTask

# TO BE UPDATED WITH "cmd" or running tool "adb" (with timeout, env, etc) !!!

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **devices** (list): List of dicts with keys `serial` and `state`
                  for each attached Android device.


                  os: ['Windows', 'Linux', 'macOS']
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        # qpath may be a quoted path string — strip surrounding quotes for subprocess
        adb_path = ctx_tasks['global']['adb']['qpath'].strip('"\'')

        try:
            proc = subprocess.run(
                [adb_path, 'devices'],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            return {'return': 1, 'error': f'adb not found at: {adb_path}'}
        except subprocess.TimeoutExpired:
            return {'return': 1, 'error': 'adb devices timed out'}

        if proc.returncode != 0:
            return {'return': 1, 'error': proc.stderr.strip() or 'adb devices failed'}

        devices = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            # Skip the header line and empty lines
            if not line or line.startswith('List of devices'):
                continue
            parts = line.split('\t', 1)
            if len(parts) == 2:
                devices.append({'serial': parts[0], 'state': parts[1]})

        if verbose:
            for dev in devices:
                print(f'{space}  {dev["serial"]}  ({dev["state"]})')

        features = {
            'devices': devices,
        }

        result = {
          'return': 0,
          'features': features,
        }

        return result
