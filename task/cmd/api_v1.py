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
            open_shell: bool = None,
            clean_files: list = None,
            skip_print_env: bool = True,
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

#        print ('===')
#        print ('os_env_PATH=', os_env.get('PATH'))
#        print ('===')
#        print ('os_env_+PATH=', os_env.get('+PATH'))
#        input('xyz1')

#        print ('===')
#        print ('envs_PATH=', envs.get('PATH'))
#        print ('===')
#        print ('envs_+PATH=', envs.get('+PATH'))
#        input('xyz2')
#
#        print ('===')
#        print ('env_PATH=', env.get('PATH'))
#        print ('===')
#        print ('env_+PATH=', env.get('+PATH'))
#        input('xyz3')

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
            skip_print_env = skip_print_env,
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
