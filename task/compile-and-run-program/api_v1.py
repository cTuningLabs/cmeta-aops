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
            **params,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK compile-and-run-program run")

        ###########################################################################################
        # Get program and desc (uses compute as constraints)
        selected_program = ctx['tasks']['local']['selected-program']

        artifact = selected_program['artifact']
        path = artifact['path']

        desc = copy.deepcopy(selected_program['loaded_files']['_desc'].get('data', {})) # May change during context merge

        program_api_code = selected_program.get('api_code')

        ###########################################################################################
        if 'params' in desc:
            params = copy.deepcopy(params)
            self.cm.utils.common.deep_merge(params, desc['params'], append_lists=False)

        _use = desc.get('use')
        if _use:
            ctx_use = ctx['tasks'].setdefault('use', {})
            self.cm.utils.common.deep_merge(ctx_use, copy.deepcopy(_use), append_lists=True)

        ###########################################################################################
        name = params.get('name')
        program_tags = params.get('program_tags')
        program_api_ver = params.get('program_api_ver')
        skip_compile = params.get('skip_compile')
        recompile = params.get('recompile')
        skip_run = params.get('skip_run')
        target_path = params.get('target_path')
        run = params.get('run')
        env = params.get('env', {})
        unparsed = params.get('unparsed')

        ###########################################################################################
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

        ###########################################################################################
        # Init vars
        result = {'return':0}

        local_vars = desc.get('local_vars')
        if local_vars:
            r = self.cm.utils.common.expand_strings_in_dict(local_vars, ctx_tasks)
            if self.cm.catch_error(r): return r

            self.cm.utils.common.deep_merge(ctx['tasks']['local'], local_vars, append_lists=False)

        selected_compute = _global.get('target',{}).get('compute', [])

        src_path = params.get('src_path')
        if not src_path:
            src_dir = local_vars.get('src_dir')
            if src_dir:
                src_path = os.path.join(path, src_dir)
            else:
                src_path = path

            ctx['tasks']['local']['src_path'] = src_path

        src_file_names = local_vars.get('src_file_names')
        if src_file_names:
            src_file_names_str = ''
            src_file_names_str_with_path = ''
            for sfn in src_file_names:
                sfn = sfn.replace('//', os.sep)

                if src_file_names_str != '':
                    src_file_names_str += ' '
                src_file_names_str += sfn

                sfnp = os.path.join(src_path, sfn)
                if src_file_names_str_with_path != '':
                    src_file_names_str_with_path += ' '
                src_file_names_str_with_path += sfnp

            ctx['tasks']['local']['src_file_names_str'] = src_file_names_str
            ctx['tasks']['local']['src_file_names_str_with_path'] = src_file_names_str_with_path


        ###########################################################################################
        if not target_path:
            target_path = ctx_tasks['local'].get('target_path')
            if not target_path:
                x = 'tmp' if not params.get('target_tmp') else params['target_tmp']
                target_path = os.path.join(path, x)

        ctx_tasks['local']['target_path'] = target_path.replace('//', os.sep)

        if 'run_time_env' not in ctx_tasks['local']:
            ctx_tasks['local']['run_time_env'] = env 
        else:
            self.cm.utils.common.deep_merge(ctx['tasks']['local']['run_time_env'], env, append_lists=True)

        if 'params' not in ctx_tasks['local']:
            ctx_tasks['local']['params'] = params
        else:
            self.cm.utils.common.deep_merge(ctx['tasks']['local']['params'], params, append_lists=True)

        ###########################################################################################
        # Check if customization
        if hasattr(program_api_code, 'customize') and callable(getattr(program_api_code, 'customize')):
            r = program_api_code.customize(ctx, params)
            if self.cm.catch_error(r): return r

        ###########################################################################################
        # Prepare some paths

        path_repro_all = os.path.join(target_path, '_repro_ctx_all.json')
        path_repro_compile = os.path.join(target_path, '_repro_ctx_compile.json')
        path_repro_run = os.path.join(target_path, '_repro_ctx_run.json')

        ###########################################################################################
        # Check if target is supported - it's already checked via cmeta.constraints.supported_compute
        # when selecting program
#        supported_compute = artifact['cmeta'].get('constraints', {}).get('supported_compute')

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
        # All
        all_desc = desc.get('all', {})
        all_uses = all_desc.get('uses', {})

        if all_uses:
            if con and verbose:
                print ('')
                print (f'{space}PREPARING ...')

            p = {'category': self.category_alias + ',' + self.category_uid,
                 'command': 'use',
                 'con': con,
                 'quiet': quiet,
                 'verbose': verbose,
                 'ctx': ctx,
                 'desc': all_uses,
                 'local': ctx['tasks']['local'], # Reuse local from this task (selected-program)
                 'task_artifact_alias': self.artifact_alias,
                 'task_artifact_uid': self.artifact_uid,
                 'task_artifact_path': self.artifact_path,
                }

            r = self.cm.access(p)

            rx = self.cm.utils.files.write_file(path_repro_all, {'ctx':ctx, 'result':r}, safe_dump = True)
            if self.cm.catch_error(rx): return rx

            if self.cm.catch_error(r): return r


        ###########################################################################################
        # Compile

        compile_desc = desc.get('compile', {})

        _compiled_state = {}
        _compile_params = None

        compile_target_compute = None

        ctx_setup_compile = None

        if not recompile:
            r = self.cm.utils.files.read_file(path_repro_compile)
            if r['return']>0:
                recompile = True
            else:
                _compiled_state = r['data']

                if _compiled_state.get('result', {}).get('return') != 0:
                    recompile = True

                _compiled_state_global = _compiled_state.get('ctx', {}).get('tasks', {}).get('global')
                _compiled_state_local = _compiled_state.get('ctx', {}).get('tasks', {}).get('local')

                if _compiled_state_global:
                    compile_target_compute = _compiled_state_global.get('target',{}).get('compute', [])

                if _compiled_state_local:
                    ctx_setup_compile = _compiled_state_local.get('setup-compile')

        if not compile_desc.get('skip', False) and not skip_compile:
            if con and verbose:
                print ('')
                print (f'{space}COMPILING ...')

            if os.path.isfile(path_repro_run):
                os.remove(path_repro_run)

            _compiled = False

            if not recompile:
                # Check if compute didn't change:
                if _compiled_state_global:
                    compile_target_compute = _compiled_state_global.get('target',{}).get('compute', [])
                    if compile_target_compute:
                        for sc in selected_compute:
                            if sc not in compile_target_compute:
                                recompile = True
                                break

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

                ###########################################################################################
                # First do uses_pre
                compile_uses_pre = compile_desc.get('uses_pre')

                if compile_uses_pre:
                    p = {'category': self.category_alias + ',' + self.category_uid,
                         'command': 'use',
                         'con': con,
                         'quiet': quiet,
                         'verbose': verbose,
                         'ctx': ctx,
                         'desc': compile_uses_pre,
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
                # Check if customization2 after uses_pre (compute, etc)
                if hasattr(program_api_code, 'customize2') and callable(getattr(program_api_code, 'customize2')):
                    r = program_api_code.customize2(ctx, params)
                    if self.cm.catch_error(r): return r

                ###########################################################################################
                # Assemble other uses
                compile_uses = []

                for k in ['uses_libs', 'uses_prep', 'uses']:
                    x = compile_desc.get(k)
                    if x:
                        compile_uses += x

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

                ctx_setup_compile = ctx['tasks']['local'].get('setup-compile')

        ###########################################################################################
        # Run
        run_desc = desc.get('run', {})

        if ctx_setup_compile:
            ctx['tasks']['local']['setup-compile'] = ctx_setup_compile

            for k in ['target_path_exe', 'target_exe']:
                if k in ctx_setup_compile and k not in ctx_tasks['local']:
                    ctx['tasks']['local'][k] = ctx_setup_compile[k]

            dynamic_lib_paths = ctx_setup_compile.get('dynamic_lib_paths')
            if dynamic_lib_paths:
                ctx['tasks']['local']['run_time_env']['+PATH'] = dynamic_lib_paths

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

            run_uses = []

            for k in ['uses_pre', 'uses_prep', 'uses', 'uses_post']:
                x = run_desc.get(k)
                if x:
                    run_uses += x

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

            # Check result files
            result_files_data = ctx['tasks']['local'].get('result_files_data')

            if result_files_data:
                result.update(result_files_data)

        return result

