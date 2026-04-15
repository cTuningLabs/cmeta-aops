"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import platform

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
            task_id: str = None,
            save_script_for_id: str = None,
            save_script_template: str = None,
            open_shell: bool = None,
            open_shell_for_id: str = None,
            clean_files: list = None,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


        """
        self.logger.debug("RUNNING TASK run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''

        _global = ctx['tasks']['global']
        _aggregated = ctx['tasks']['aggregated']

        os_env = _global['host']['os_env']

        envs = _aggregated.get('env', {})

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

        if not save_script and task_id and save_script_for_id:
            if type(task_id) == str:
                task_id = task_id.split(',')

            if type(save_script_for_id) == str:
                save_script_for_id = save_script_for_id.split(',')

            for tid in task_id:
                if tid in save_script_for_id:
                    tid0 = task_id[0]
                    if save_script_template:
                        save_script = save_script_template.replace('{{task_id}}', tid0)
                    else:
                        save_script = f'cmd-script--{tid0}' + '{{file_ext_bat}}'
                    break

        if not open_shell and task_id and open_shell_for_id:
            if type(task_id) == str:
                task_id = task_id.split(',')

            if type(open_shell_for_id) == str:
                open_shell_for_id = open_shell_for_id.split(',')

            for tid in task_id:
                if tid in open_shell_for_id:
                    open_shell = True
                    break

        if save_script and con and verbose:
            print ('')
            print (f'{space}INFO: saving script to "{save_script}"')

        if con and verbose and print_line_in_verbose:
            print ('='*80)

        result = self.cm.utils.sys.run(
            cmd, 
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
        )

        if chdir:
            if con and verbose:
                print ('')
                print (f'{space}INFO: cd "{cur_dir}"')
            os.chdir(cur_dir)

        if self.cm.catch_error(result, fail16=True): return result

        returncode = result['returncode']

        result['env'] = env
        result['cmd'] = cmd

        if fail_if_nonzero_return_code and returncode>0:
            return self.cm.error(f'CMD "{cmd}" failed with return code {returncode}', 99)

        return result
