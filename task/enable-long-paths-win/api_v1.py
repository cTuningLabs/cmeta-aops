"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import copy
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            env: dict = {},
            delay: int = 3,
            timeout: int = 30,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        result = {'return':0}

        if os.name != 'nt':
            return {'return': 1, 'error': f"this task can run only on Windows: {misc['path']}"}

        # Check if long paths are enabled
        enabled = self._check_if_enabled()

        if not enabled:
            print ('')
            print (f'{space}WARNING: Windows long names are not enabled - trying to enable in admin mode via powershell!')

            time.sleep(int(delay))

            # path to this script
            module_path = self.module_path
            path_to_script = os.path.join(module_path, 'enable-long-paths-win.bat')

            cmd = f'powershell start {path_to_script} -v runas'

            r = self.cm.utils.sys.run(cmd, env = env, timeout = int(timeout), con = con, verbose = verbose, text_cmd = 'RUN:', space = space)
            if self.cm.catch_error(r): return r

            if r['returncode']!=0:
                if con:
                    print ('')
                return self.cm.error(f'Command timed out in "{__file__}" ({__name__})')

            if r['returncode']>0:
                x = r.get('stderr')
                x = '' if not x else ' '+x
                if con:
                    print ('')
                return self.cm.error(f'Command failed{x} in "{__file__}" ({__name__})')

            # Trying again
            enabled = self._check_if_enabled()

        if not enabled:
            return {'return':1, 'error': 'you may need to restart this task to check if long paths were enabled'}

        else:
            if con and verbose:
                print ('')
                print (f'{space}INFO: Windows long paths are enabled!')

        result['enabled'] = enabled

        return result

    ###################################################################
    def _check_if_enabled(self):
        from importlib import reload
        import ctypes
        reload(ctypes)

        ntdll = ctypes.WinDLL('ntdll')

        enabled = False

        if hasattr(ntdll, 'RtlAreLongPathsEnabled'):
            ntdll.RtlAreLongPathsEnabled.restype = ctypes.c_ubyte
            ntdll.RtlAreLongPathsEnabled.argtypes = ()

            enabled = bool(ntdll.RtlAreLongPathsEnabled())

        return enabled

