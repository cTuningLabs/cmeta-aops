"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
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
            cmd: str = "",
            cmds: list = None,
            chdir: str = None,
            chdir_and_stay: str = None,
            mkdir: str = None,
            env: dict = {},
            genv: dict = {},
            timeout: int = None,
            capture_output: bool = False,
            capture_env: bool = False,
            fail_if_nonzero_return_code: bool = True,
            text_cmd: str = 'RUN:',
            print_env_keys: list = None,
            print_extra_line: bool = True,
            print_line_in_verbose: bool = False,
            print_cur_dir: bool = False,
            hide_in_cmd: list = None,
            hide_in_env: list = None,
            unparsed: list = [],
            save_script: str = None,
            open_shell: bool = None,
            open_shell_after: bool = None,
            clean_files: list = None,
            skip_print_env: bool = True,
    ):

        """
        Args:
            timeout (int): Seconds after which the command and all its subprocesses are stopped
                (a process group on Linux and macOS, a Job Object on Windows); each command of
                `cmds` gets the full time. None, 0 or "" (the default): no limit.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **timed_out** (bool): True if the timeout stopped the command (with
                  `fail_if_nonzero_return_code=False`; otherwise the task fails).


        """
        self.logger.debug("RUNNING TASK run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''

        _global = ctx['tasks']['global']
        _aggregated = ctx['tasks']['aggregated']

        os_env = _global['host']['os_env']
        envs = _aggregated.get('env', {})

#        print ('===')
#        print ('os_env_PATH=', os_env.get('PATH'))
#        print ('===')
#        print ('os_env_+PATH=', os_env.get('+PATH'))

#        print ('===')
#        print ('envs_PATH=', envs.get('PATH'))
#        print ('===')
#        print ('envs_+PATH=', envs.get('+PATH'))
#
#        print ('===')
#        print ('env_PATH=', env.get('PATH'))
#        print ('===')
#        print ('env_+PATH=', env.get('+PATH'))

        cur_dir = os.getcwd()

        if mkdir:
            if con and verbose:
                print ('')
                print (f'{space}INFO: mkdir -p "{chdir}"')
            os.makedirs(mkdir, exist_ok=True)

        if chdir:
            if con and verbose:
                print ('')
                print (f'{space}INFO: cd "{chdir}"')
            os.chdir(chdir)
        elif chdir_and_stay:
            if con and verbose:
                print ('')
                print (f'{space}INFO: cd "{chdir_and_stay}"')
            os.chdir(chdir_and_stay)

        if unparsed:
            for u in unparsed:
                if cmd != '':
                    cmd += ' '

                cmd += self.cm.utils.files.quote_path(u)

        if clean_files:
            for cf in clean_files:
               if os.path.isfile(cf):
                   os.remove(cf)

        if save_script and con and verbose:
            save_script = save_script.replace('//', os.sep)
            print ('')
            print (f'{space}INFO: saving script to "{save_script}"')

        if con and verbose and print_line_in_verbose:
            print ('='*80)

        # No limit for None, 0 or "" (from the command line the value comes as a string)
        if timeout in (None, '', 0, '0', False):
            timeout = None
        else:
            timeout = max(1, int(float(timeout)))

        started = time.time()

        result = self.cm.utils.sys.run(
            cmd, 
            cmds = cmds,
            env = env, 
            envs = envs, 
            genv = genv, 
            os_env = os_env,
            hide_in_cmd = hide_in_cmd,
            hide_in_env = hide_in_env,
            timeout = timeout, 
            capture_output = capture_output,
            capture_env = capture_env,
            con = con, 
            verbose = verbose, 
            text_cmd = text_cmd, 
            space = space,
            print_env_keys = print_env_keys,
            print_extra_line = print_extra_line,
            print_cur_dir = print_cur_dir,
            save_script = save_script,
            open_shell = open_shell,
            open_shell_after = open_shell_after,
            skip_print_env = skip_print_env,
        )

        elapsed = time.time() - started

        if chdir:
            os.chdir(cur_dir)

        if self.cm.catch_error(result, fail16=True): return result

        returncode = result.get('returncode', 0)

        # utils.sys.run stops a command that runs past the timeout, with its subprocesses, and
        # returns -1, the code it also returns at once when a command cannot be started
        timed_out = timeout is not None and returncode == -1 and elapsed >= timeout
        if timed_out:
            result['timed_out'] = True

        # Any code but 0 fails: a negative one is a signal on Linux and macOS
        if fail_if_nonzero_return_code and returncode != 0:
            failed_cmd = result.get('cmd', cmd)
            if timed_out:
                return self.cm.error(f'CMD "{failed_cmd}" timed out after {timeout} s (stopped with its subprocesses)', 99)
            stderr = result.get('stderr')
            reason = f': {stderr.strip()[-500:]}' if returncode == -1 and isinstance(stderr, str) and stderr.strip() else ''
            return self.cm.error(f'CMD "{failed_cmd}" failed with return code {returncode}{reason}', 99)

        result['env'] = env
        result['cmd'] = cmd

        return result

