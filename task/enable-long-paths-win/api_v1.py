"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import sys
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

# The one switch behind Windows long paths. The Settings toggle, the "Enable
# Win32 long paths" group policy and enable-long-paths-win.bat (kept next to
# this file for running by hand) all write this value.
REG_KEY = r'SYSTEM\CurrentControlSet\Control\FileSystem'
REG_VALUE = 'LongPathsEnabled'

# Start reg.exe elevated and wait for it to finish.
#
# reg.exe is started directly rather than the .bat next to this file, for two
# reasons. The .bat used to begin with a UTF-8 BOM, which cmd.exe reads as part
# of the first command under every code page except 65001: the elevated window
# failed on "'<BOM>reg' is not recognized", closed, and the value was never
# written, so every run asked for administrator rights again. And no path of
# ours has to survive three layers of quoting (cmd -> powershell ->
# Start-Process) - a user name with a space in it broke the unquoted .bat path.
#
# -Wait matters too: without it the check below ran before the elevated
# command had even started. Exit code 1223 (ERROR_CANCELLED) is what the catch
# reports, because Start-Process throws when the UAC prompt is declined.
ELEVATED_CMD = (
    'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "'
    'try { $p = Start-Process -FilePath reg.exe -ArgumentList '
    "'add','HKLM\\" + REG_KEY + "','/v','" + REG_VALUE + "','/t','REG_DWORD','/d','1','/f' "
    '-Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode } '
    'catch { Write-Host $_.Exception.Message; exit 1223 }"'
)

# What to do by hand when the automatic attempt does not work. Printed before
# the attempt, so it is already on screen if the prompt is declined, and again
# in the error. The reg command works in both cmd and PowerShell.
MANUAL_STEPS = [
    'Windows 11: open Settings > System > Advanced and turn on "Enable long paths".',
    'Windows 10, or a build without that switch: open a terminal as administrator and run',
    '  reg add "HKLM\\' + REG_KEY + '" /v ' + REG_VALUE + ' /t REG_DWORD /d 1 /f',
    'Then run this command again.',
]

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
            timeout: int = 300,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **enabled** (bool): True if Windows long paths are enabled.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if os.name != 'nt':
            return {'return': 1, 'error': 'this task can run only on Windows'}

        # Enabled for this process: the usual case, and the only free one.
        if self._check_if_enabled():
            if con and verbose:
                print ('')
                print (f'{space}INFO: Windows long paths are enabled!')

            return {'return': 0, 'enabled': True}

        # Enabled in Windows but not for this process. Windows reads the value
        # once, when a program starts, so a process that was already running
        # when it was switched on (a cserver, say) never sees it. There is
        # nothing to fix, and asking for administrator rights again would only
        # repeat the prompt forever.
        if self._check_registry():
            if con and verbose:
                print ('')
                print (f'{space}INFO: Windows long paths are enabled for programs started after they were switched on.')

            return {'return': 0, 'enabled': True}

        print ('')
        print (f'{space}WARNING: Windows long paths are not enabled, so file paths are limited to 260 characters')
        print (f'{space}         and deep artifact trees can break tools.')
        print ('')
        print (f'{space}         cMeta will now try to enable them automatically: a command runs in administrator')
        print (f'{space}         mode, so please accept the Windows prompt (UAC).')
        print ('')
        print (f'{space}         If that does not work, enable them by hand:')
        for line in MANUAL_STEPS:
            print (f'{space}           {line}')

        # The elevated command writes straight to the console, so anything
        # still buffered here would otherwise appear after it.
        sys.stdout.flush()

        time.sleep(int(delay))

        r = self.cm.utils.sys.run(ELEVATED_CMD, env = env, timeout = int(timeout), con = con, verbose = verbose, text_cmd = 'RUN:', space = space)
        if self.cm.catch_error(r): return r

        returncode = r.get('returncode', 0)

        # The registry is the source of truth: it is what the elevated command
        # changes, and unlike RtlAreLongPathsEnabled it is not frozen at the
        # moment this process started.
        if self._check_registry():
            print ('')
            print (f'{space}INFO: Windows long paths are now enabled. Windows applies this to programs started from')
            print (f'{space}      now on, so if this run still fails because a path is too long, run the command again.')

            return {'return': 0, 'enabled': True}

        if returncode == 1223:
            reason = 'the administrator prompt was declined'
        elif returncode == -1:
            reason = f'no answer to the administrator prompt within {timeout} seconds'
        elif returncode != 0:
            reason = f'the elevated command exited with code {returncode}'
        else:
            reason = 'the setting did not change'

        steps = '\n'.join('  ' + line for line in MANUAL_STEPS)

        return self.cm.error(f'could not enable Windows long paths automatically ({reason}).\n'
                             f'Please enable them by hand:\n{steps}')

    ###################################################################
    def _check_if_enabled(self):
        """
        Whether long paths are active for THIS process.

        Windows decides that once, when the process starts (the result is
        cached in its PEB), so this cannot turn true within a run no matter
        what changes in the registry - see _check_registry for that.
        """
        import ctypes

        ntdll = ctypes.WinDLL('ntdll')

        enabled = False

        if hasattr(ntdll, 'RtlAreLongPathsEnabled'):
            ntdll.RtlAreLongPathsEnabled.restype = ctypes.c_ubyte
            ntdll.RtlAreLongPathsEnabled.argtypes = ()

            enabled = bool(ntdll.RtlAreLongPathsEnabled())

        return enabled

    ###################################################################
    def _check_registry(self):
        """
        Whether long paths are switched on in Windows, i.e. for every program
        started from now on.
        """
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY) as key:
                value, _ = winreg.QueryValueEx(key, REG_VALUE)
            return int(value) == 1
        except (OSError, TypeError, ValueError):
            return False
