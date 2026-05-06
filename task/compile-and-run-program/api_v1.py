"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import shutil
import copy

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            name: str = None,
            program_tags: str = None,
            program_api_ver: str = None,
            compute: str = None,
            skip_compile: bool = False,
            recompile: bool = False,
            skip_run: bool = False,
            target_path: str = None,
            compile: dict = None,
            run: dict = None,
            unparsed: str = None,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK compile-and-run-program run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        ctx_tasks_control = ctx['tasks']['run_control']
        clean = ctx_tasks_control.get('clean', False)

        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        host = _global['host']
        uname = host['os']['uname']

        selected_program = ctx['tasks']['local']['selected-program']

        artifact = selected_program['artifact']
        path = artifact['path']

        desc = copy.deepcopy(selected_program['loaded_files']['_desc'].get('data', {})) # May change during context merge

        ###########################################################################################
        if not target_path:
            target_path = os.path.join(path, 'tmp')

        ctx['tasks']['local']['target_path'] = target_path

        path_repro_compile = os.path.join(target_path, '_repro_ctx_compile.json')
        path_repro_run = os.path.join(target_path, '_repro_ctx_run.json')

        ###########################################################################################
        # Init vars
        result = {'return':0}

        local_vars = desc.get('local_vars')
        if local_vars:
            r = self.cm.utils.common.expand_strings_in_dict(local_vars, ctx_tasks)
            if self.cm.catch_error(r): return r

            self.cm.utils.common.deep_merge(ctx['tasks']['local'], local_vars, append_lists=False)

        ###########################################################################################
        # Clean (restart) (clean flag is used by "task" category)

        if clean and os.path.isdir(target_path):
            if con and verbose:
                print ('')
                print (f'{space}CLEANING ...')

            shutil.rmtree(target_path)

        if not os.path.isdir(target_path):
            os.makedirs(target_path)

        ###########################################################################################
        # Compile

        compile_desc = desc.get('compile', {})

        if not compile_desc.get('skip', False) and not skip_compile:
            if con and verbose:
                print ('')
                print (f'{space}COMPILING ...')

            if os.path.isfile(path_repro_run):
                os.remove(path_repro_run)

            _compiled = False
            _compiled_state = {}
            _compile_params = None

            if not recompile and os.path.isfile(path_repro_compile):
                r = self.cm.utils.files.read_file(path_repro_compile)
                if r['return'] >0:
                    recompile = True
                else:
                    _compiled_state = r['data']

                    if _compiled_state.get('result', {}).get('return') != 0:
                        recompile = True

                    # Check if compute didn't change:
                    _compiled_state_global = _compiled_state.get('ctx', {}).get('tasks', {}).get('global')
                    if _compiled_state_global:
                        compile_target_compute = _compiled_state_global.get('target',{}).get('compute', [])
                        if compile_target_compute:
                            if compute:
                                if compute not in compile_target_compute:
                                    recompile = True
                            elif 'cpu' not in compile_target_compute:
                                recompile = True

                        if not recompile and 'android-cpu' in compile_target_compute:
                            compile_target_adb_serial = _compiled_state_global.get('target--android-cpu',{}).get('serial')
                            target_adb_serial = ctx_tasks['global'].get('target--android-cpu',{}).get('serial')
                            if compile_target_adb_serial != target_adb_serial:
                                recompile = True

                    if not recompile:
                        if _compiled_state_global:
                            if con and verbose:
                                print ('')
                                print (f'{space}REUSING EXISTING GLOBAL COMPILE CONTEXT ...')

                            self.cm.utils.common.deep_merge(ctx['tasks']['global'], _compiled_state_global, append_lists=False)

                        _compiled_state_local = _compiled_state.get('ctx', {}).get('tasks', {}).get('local')
                        if _compiled_state_local:
                            if con and verbose:
                                print (f'{space}REUSING EXISTING LOCAL COMPILE CONTEXT ...')

                            self.cm.utils.common.deep_merge(ctx['tasks']['local'], _compiled_state_local, append_lists=False)

                        _compiled_state_aggregated = _compiled_state.get('ctx', {}).get('tasks', {}).get('aggregated')
                        if _compiled_state_aggregated:
                            if con and verbose:
                                print (f'{space}REUSING EXISTING AGGREGATED COMPILE CONTEXT ...')

                            self.cm.utils.common.deep_merge(ctx['tasks']['aggregated'], _compiled_state_aggregated, append_lists=False)

                        _compile_params = _compiled_state.get('ctx', {}).get('origin', {}).get('params', {}).get('compile', {})
                        if _compile_params:
                            if con and verbose:
                                print (f'{space}REUSING EXISTING COMPILE PARAMS ...')

                            self.cm.utils.common.deep_merge(ctx['origin']['params'], {'compile':_compile_params}, append_lists=True)
                            self.cm.utils.common.deep_merge(ctx['tasks']['params'], {'compile':_compile_params}, append_lists=False)


                        if _compiled_state.get('result', {}).get('return') == 0:
                            _compiled = True

            if recompile or not _compiled:
                if os.path.isfile(path_repro_compile):
                    os.remove(path_repro_compile)

                compile_uses = compile_desc.get('uses')
                if compile_uses:
                    p = {'category': self.category_alias + ',' + self.category_uid,
                         'command': 'use',
                         'con': con,
                         'quiet': quiet,
                         'verbose': verbose,
                         'ctx': ctx,
                         'desc': compile_uses,
                         'local': ctx['tasks']['local'], # Reuse local from this task (selected-program)
                         'task_artifact_alias': self.artifact_alias,
                         'task_artifact_uid': self.artifact_uid,
                         'task_artifact_path': self.artifact_path,
                        }

#                    if _compile_params:
#                        p['uparams'] = {'compile':_compile_params}

                    r = self.cm.access(p)

                    rx = self.cm.utils.files.write_file(path_repro_compile, {'ctx':ctx, 'result':r}, safe_dump = True)
                    if self.cm.catch_error(rx): return rx

                    if self.cm.catch_error(r): return r


        ###########################################################################################
        # Run
        run_desc = desc.get('run', {})

        if not run_desc.get('skip', False) and not skip_run:
            if con and verbose:
                print ('')
                print (f'{space}RUNNING ...')

            if os.path.isfile(path_repro_run):
                os.remove(path_repro_run)

            if unparsed:
                x = ''
                for u in unparsed:
                    x += ' ' + self.cm.q(u)
                ctx['tasks']['local']['unparsed'] = x.strip()

            run_uses = run_desc.get('uses')
            if run_uses:
                p = {'category': self.category_alias + ',' + self.category_uid,
                     'command': 'use',
                     'con': con,
                     'quiet': quiet,
                     'verbose': verbose,
                     'ctx': ctx,
                     'desc': run_uses,
                     'local': ctx['tasks']['local'], # Reuse local from this task (selected-program)
                     'task_artifact_alias': self.artifact_alias,
                     'task_artifact_uid': self.artifact_uid,
                     'task_artifact_path': self.artifact_path,
                    }

                r = self.cm.access(p)

                rx = self.cm.utils.files.write_file(path_repro_run, {'ctx':ctx, 'result':r}, safe_dump = True)
                if self.cm.catch_error(rx): return rx

                if self.cm.catch_error(r): return r

        return result

