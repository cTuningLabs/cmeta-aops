"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import importlib.util
import os
import shutil
import copy
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask
from task_c36be4b9314a45e0.api import deadlines
from task_c36be4b9314a45e0.api import build_stamp

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)



    ############################################################
    def common_sizes(self):
        """
        The size rules and the disk measures of the tool category (category/tool/api/common_sizes.py),
        shared with task/setup. Its package, tool_<uid>.api, exists once the engine has loaded the tool
        category in this process (any tool setup does that); before that, the module is loaded from
        the category's folder, found through uses_categories. None when the category is not plugged.
        """
        try:
            from tool_c393ba5c6fa14f66.api import common_sizes
            return common_sizes
        except ImportError:
            pass
        category = self.cmeta.get('uses_categories', {}).get('tool', 'tool,c393ba5c6fa14f66')
        r = self.cm.access({'category': 'category', 'command': 'find', 'arg1': category})
        artifacts = r.get('artifacts') if r.get('return', 1) == 0 else None
        if not artifacts:
            return None
        path = os.path.join(artifacts[0]['path'], 'api', 'common_sizes.py')
        if not os.path.isfile(path):
            return None
        spec = importlib.util.spec_from_file_location('cmeta_aops_common_sizes', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    ############################################################
    def build_facts(self,
                    ctx: dict,
                    params: dict,
                    compute: list,
                    compiler_key: str = None,
                    compiler_from: dict = None,
    ):
        """
        What a build is made for, as the stamp of the build folder records it: the targets, the host,
        the compiler (from the global context under compiler_key, when resolved), the compile
        parameters that change the output, the Android device.
        """
        _global = ctx['tasks']['global']
        compiler = None
        if compiler_key:
            compiler = build_stamp.compiler_identity((compiler_from or _global).get(compiler_key))
        android_target = _global.get('target--android-cpu') or {}
        android = {'serial': android_target.get('serial'),
                   'abi': (android_target.get('features') or {}).get('ro.product.cpu.abi')} if android_target else None
        return {'compute': list(compute or []), 'host': _global['host']['os']['uname'], 'compiler': compiler,
                'compile_params': params.get('compile') or {}, 'android': android}

    ############################################################
    def requested_compiler(self,
                           ctx: dict,
                           compiler_key: str,
    ):
        """The compiler a run asks for through --use (--use.compiler-c.name=gcc), as the stamp records
        one, or None: on a reused build the compiler is not resolved, only what the user asked."""
        use = ctx['tasks'].get('use') or {}
        asked = use.get(compiler_key) or use.get('compiler') or {}
        identity = {'name': asked.get('name'), 'version': asked.get('version')}
        return identity if any(identity.values()) else None

    ############################################################
    def refuse_stale_build(self,
                           ctx: dict,
                           target_path: str,
                           facts: dict,
    ):
        """
        The guard of the build folder: when its stamp differs from this run (targets, host, compiler,
        compile parameters, Android device), the folder is neither reused nor rebuilt in place. A
        folder configured for one target or compiler was silently reused for another before: on
        macOS a host build of llama.cpp was pushed to an Android device, since CMake kept its cache.
        --recompile (explicit) and --clean (the folder is wiped first) go on. Returns the error, or
        {'return': 0, 'stamp': <the stamp or None>}.
        """
        stamp = build_stamp.read_stamp(target_path)
        if not stamp:
            return {'return': 0, 'stamp': None}
        diffs = build_stamp.differences(stamp, **facts)
        if diffs:
            return self.cm.error(build_stamp.refusal_message(target_path, stamp, diffs))
        return {'return': 0, 'stamp': stamp}

    ############################################################
    def write_build_stamp(self,
                          ctx: dict,
                          target_path: str,
                          artifact_alias: str,
                          artifact_uid: str,
                          facts: dict,
    ):
        """Records what the build in the folder is made for (after a compile, or for a folder made
        before the stamps existed); a folder that cannot be written is left alone."""
        stamp = build_stamp.make_stamp(artifact_alias, artifact_uid, facts['compute'], facts['host'],
                                       compiler = facts.get('compiler'), compile_params = facts.get('compile_params'),
                                       android = facts.get('android'))
        error = build_stamp.write_stamp(target_path, stamp)
        if error and ctx['control'].get('con', False) and ctx['control'].get('verbose', False):
            print (f'WARNING: the build stamp of "{target_path}" was not written: {error}')
        return stamp

    ############################################################
    def check_program_disk_space(self,
                                 ctx: dict,
                                 params: dict,
                                 program_path: str,
                                 program_name: str,
                                 target_path: str,
                                 compute: list,
    ):
        """
        Before the compile phase: the rule of the program's _desc_sizes.yaml for this run (OS, CPU,
        method build, the targets, the compile parameters as "with", --version) gives the space the
        build needs (peak); the configured minimum of free space (cx config set task
        --meta.min_free_gb=<GB>) applies to every program. The folder checked is the build folder's
        volume (target_path). Below that: a quiet run stops before compiling, else a warning and the
        question whether to go on. --skip_size_check skips it. No file and no minimum: no check.
        """
        if params.get('skip_size_check', False):
            return {'return': 0}

        sizes = self.common_sizes()
        if sizes is None:
            return {'return': 0}

        ctx_tasks = ctx['tasks']
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx_tasks.get('nested_call', 0) if verbose else ''

        rules = sizes.load_sizes(program_path)

        floor = ctx_tasks.get('global', {}).get('init', {}).get('min_free_gb')
        try:
            floor = float(floor) if floor not in (None, '', False) else None
        except (TypeError, ValueError):
            return self.cm.error(f'the configured minimum of free space "min_free_gb" is not a number: {floor}')

        if not rules and floor is None:
            return {'return': 0}

        host = ctx_tasks['global']['host']['os']
        compile_params = build_stamp.normalize_compile(params.get('compile'))
        facts = sizes.request_facts(version = params.get('version') or None, os_name = host['uname'],
                                    arch = host.get('uarch'), method = 'build', compute = list(compute or []),
                                    with_ = compile_params or None)
        rule = sizes.select_rule(rules, facts, self.cm.utils.common.matches_query,
                                 match_version_func = self.cm.repos.match_version_func)
        needed = rule.get('peak') if rule else None

        ok, free, required = sizes.check_space(needed, target_path, floor_gb = floor)
        if ok:
            if verbose and con and required is not None:
                print (f'{space}INFO: disk space for the build: {free:.1f} GB free in {target_path}, about {required:g} GB needed')
            return {'return': 0}

        rule_based = needed is not None and needed >= (floor or 0)
        what = f'{program_name} (build, {host["uname"]}' + (f', {",".join(compute)}' if compute else '') + ')'
        need = (f'needs about {required:g} GB during the build' if rule_based
                else f'needs at least {required:g} GB free (the configured minimum)')
        message = (f'{what} {need}; {free:.1f} GB are free in {target_path}. Free space, give '
                   f'--target_tmp=<name> or --target_path=<folder on another disk>, or --skip_size_check.')

        if quiet or not con:
            return self.cm.error(message)

        print ('')
        print (f'{space}WARNING: {message}')
        x = input(f'{space}Continue anyway (y/N)? ').strip().lower()
        if x not in ['y', 'yes']:
            return self.cm.error(f'build of "{program_name}" cancelled: not enough disk space')

        return {'return': 0}

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
        selected_program_api_code = selected_program.get('api_code')

        artifact = selected_program['artifact']
        path = artifact['path']

        cmeta_ref_parts = artifact['cmeta_ref_parts']

        artifact_alias = cmeta_ref_parts.get('artifact_alias')
        artifact_uid = cmeta_ref_parts['artifact_uid']

        desc = copy.deepcopy(selected_program['loaded_files']['_desc'].get('data', {})) # May change during context merge

        program_api_code = selected_program.get('api_code')

        ctx_tasks = ctx['tasks']
        _global = ctx_tasks['global']

        host = _global['host']
        uname = host['os']['uname']

        ###########################################################################################
        params = copy.deepcopy(params)

        if 'params' in desc:
            params_desc = copy.deepcopy(desc['params'])
            self.cm.utils.common.deep_merge(params_desc, params, append_lists=False)
            params = params_desc

        params_os = desc.get('params_os')
        if params_os:
            v = None
            if 'all' in params_os:
                v = params_os['all']
            elif uname in params_os:
                v = params_os[uname]
            elif uname != 'windows' and 'linux' in params_os:
                v = params_os['linux']
            if v:
                params_os_desc = copy.deepcopy(v)
                self.cm.utils.common.deep_merge(params_os_desc, params, append_lists=False)
                params = params_os_desc

        r = self.cm.utils.common.expand_strings_in_dict(params, ctx_tasks)
        if self.cm.catch_error(r): return r

        _use = desc.get('use')
        if _use:
            ctx_use = ctx['tasks'].setdefault('use', {})
            self.cm.utils.common.deep_merge(ctx_use, copy.deepcopy(_use), append_lists=True)

        ###########################################################################################
        # Check if customization
        if hasattr(program_api_code, 'customize_pre') and callable(getattr(program_api_code, 'customize_pre')):
            r = program_api_code.customize_pre(ctx, params)
            if self.cm.catch_error(r): return r

        ###########################################################################################
        name = params.get('name')
        program_tags = params.get('program_tags')
        program_api_ver = params.get('program_api_ver')
        skip_compile = params.get('skip_compile')
        recompile = params.get('recompile')
        skip_run = params.get('skip_run')
        target_path = params.get('target_path')
        work_path = params.get('work_path')
        here = params.get('here')
        run = params.get('run')
        env = params.get('env', {})
        unparsed = params.get('unparsed')

        ###########################################################################################
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks_control = ctx['tasks']['run_control']
        clean = ctx_tasks_control.get('clean', False)

        cur_dir = ctx_tasks_control['cur_dir']
        work_dir = ctx_tasks_control['work_dir']
        task_path = ctx_tasks_control['task_path']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        result = {'return':0}

        ###########################################################################################
        # Init vars
        local_vars = desc.get('local_vars')
        if local_vars:
#            r = self.cm.utils.common.expand_strings_in_dict(local_vars, ctx_tasks)
#            if self.cm.catch_error(r): return r

            self.cm.utils.common.deep_merge(ctx['tasks']['local'], local_vars, append_lists=False)

        selected_compute = _global.get('target',{}).get('compute', [])

        ###########################################################################################
        # The folder of the build and the run under the program's cache entry (or the current
        # directory for programs that run in '{pwd}'): --target_tmp, else the configured default,
        # else tmp. "auto" gives every set of targets its own folder (tmp-cuda, tmp-cpu-cuda),
        # so builds for different targets stay side by side for comparisons on one machine.
        r = self.cm.access({
          'category':self.cmeta['uses_categories']['config'],
          'command':'get',
          'arg1':'task',
        })
        if self.cm.catch_error(r): return r

        cfg = r['config_cmeta']

        target_tmp = params.get('target_tmp') or cfg.get('compile_and_run_program', {}).get('target_tmp') or 'tmp'
        if target_tmp == 'auto':
            # The target task has not run yet: the targets as given (the template's default is cpu)
            requested = params.get('compute') or 'cpu'
            if isinstance(requested, str):
                requested = requested.split(',')
            requested = [str(c).strip().lower() for c in requested if str(c).strip()] if isinstance(requested, list) else []
            target_tmp = 'tmp-' + '-'.join(requested) if requested else 'tmp'

        if not target_path:
            target_path = ctx_tasks['local'].get('target_path')
            if not target_path:
                x = target_tmp

                skip_cache = cfg.get('compile_and_run_program',{}).get('skip_cache', False)

                if skip_cache:
                    target_path = os.path.join(path, x)
                else:
                    # Check if in current path or cache
                    artifact_au = artifact_alias if artifact_alias else artifact_uid
                    r = self.cm.access({
                      'category':self.cmeta['uses_categories']['cache'],
                      'command':'get', 
                      'arg1':f'task--program--{artifact_au}',
                      'tags': [
                         "task",
                         "c36be4b9314a45e0",
                         "compile-and-run-program",
                         "05437a1aae224270",
                      ]
                    })
                    if self.cm.catch_error(r): return r

                    target_path = os.path.join(r['artifact']['path'], x)

        target_path = target_path.replace('//', os.sep)

        ctx_tasks['local']['target_path'] = target_path

        if here:
            work_path = os.getcwd()

        if not work_path:
            work_path = ctx_tasks['local'].get('work_path')
            if not work_path:
                work_path = target_path

        if work_path.strip().lower() == '{pwd}':
            work_path = cur_dir

            work_path = os.path.join(work_path, target_tmp)

            work_path = work_path.replace('//', os.sep)

        ctx_tasks['local']['work_path'] = work_path

        os.makedirs(work_path, exist_ok=True)

        ###########################################################################################
        if 'run_time_env' not in ctx_tasks['local']:
            ctx_tasks['local']['run_time_env'] = env 
        else:
            self.cm.utils.common.deep_merge(ctx['tasks']['local']['run_time_env'], env, append_lists=True)

        if 'params' not in ctx_tasks['local']:
            ctx_tasks['local']['params'] = params
        else:
            self.cm.utils.common.deep_merge(ctx['tasks']['local']['params'], params, append_lists=True)

        ###########################################################################################
        # Extra possible update dependig on run cmd
        


#        ###########################################################################################
#        # Check if customization
#        if hasattr(program_api_code, 'customize') and callable(getattr(program_api_code, 'customize')):
#            r = program_api_code.customize(ctx, params)
#            if self.cm.catch_error(r): return r

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
                 'self_desc': desc,
                 'uparams': params,
                }

            r = self.cm.access(p)

            rx = self.cm.utils.files.write_file(path_repro_all, {'ctx':ctx, 'result':r}, safe_dump = True)
            if self.cm.catch_error(rx): return rx

            if self.cm.catch_error(r): return r


#        ###########################################################################################
#        # Prepare src path
#        # Check if customization2 after uses_pre (compute, etc)
#        if hasattr(program_api_code, 'customize1') and callable(getattr(program_api_code, 'customize1')):
#            r = program_api_code.customize1(ctx, params=params, desc=desc)
#            if self.cm.catch_error(r): return r

        src_path = params.get('src_path')
        if not src_path:
            src_dir = ctx['tasks']['local'].get('src_dir')
            if src_dir:
                src_path = os.path.join(path, src_dir)
            else:
                src_path = path

        ctx['tasks']['local']['src_path'] = src_path

        # Duplicated in setup-run if we need to update names without compilation
        # (such as python)
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
        # The target task of the 'all' pipeline has resolved the targets only now: read before
        # (above), selected_compute was empty, so a change of --compute never triggered a
        # recompile, and the cached context of the other target (its build, its run flags) was
        # reused - a --compute=metal run after a --compute=cpu build ran on the CPU
        selected_compute = ctx_tasks['global'].get('target', {}).get('compute', []) or selected_compute

        ###########################################################################################
        # Compile

        compile_desc = desc.get('compile', {})

        _compiled_state = {}
        _compile_params = None

        compile_target_compute = None

        ctx_setup_compile = None

        build_disk_gb = None

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
                # Check if compute didn't change (in either direction: cpu,cuda -> cuda changes the
                # build as much as cuda -> cpu,cuda):
                if _compiled_state_global:
                    compile_target_compute = _compiled_state_global.get('target',{}).get('compute', [])
                    if compile_target_compute and set(selected_compute) != set(compile_target_compute):
                        recompile = True

                    if not recompile and any(c in ('android-cpu', 'android-gpu', 'android-npu') for c in compile_target_compute):
                        compile_target_adb_serial = _compiled_state_global.get('target--android-cpu',{}).get('serial')
                        target_adb_serial = ctx_tasks['global'].get('target--android-cpu',{}).get('serial')
                        if compile_target_adb_serial != target_adb_serial:
                            recompile = True

                    if not recompile:
                        compile_uname = _compiled_state_global['host']['os']['uname']
                        # Can happen in Docker or WSL with shared host disk
                        if compile_uname != uname:
                            recompile = True

                    if not recompile:
                        target_path_exe = _compiled_state_local.get('target_path_exe')
                        if target_path_exe and not os.path.isfile(target_path_exe):
                            recompile = True

                    # The stamp of the build folder: a build for other targets, another compiler
                    # (asked for with --use) or other compile parameters is not reused
                    if not recompile:
                        _compiler_key = (_compiled_state_local or {}).get('global_compiler_key')
                        _facts = self.build_facts(ctx, params, selected_compute)
                        _facts['compiler'] = self.requested_compiler(ctx, _compiler_key) if _compiler_key else None
                        r = self.refuse_stale_build(ctx, target_path, _facts)
                        if self.cm.catch_error(r): return r
                        if r['stamp'] is None and _compiled_state_global:
                            # A folder made before the stamps, which this run reuses: stamped with this
                            # run's targets and compile parameters (the saved origin parameters lack the
                            # program's defaults) and the compiler the saved state resolved
                            _facts['compiler'] = build_stamp.compiler_identity(_compiled_state_global.get(_compiler_key)) if _compiler_key else None
                            self.write_build_stamp(ctx, target_path, artifact_alias, artifact_uid, _facts)

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

                        # However, take original selected-program from the beginning of this task
                        # since it has initialized code that is not serializable!
                        ctx['tasks']['local']['selected-program']['api_code'] = selected_program_api_code

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
                        build_disk_gb = _compiled_state.get('result', {}).get('_impact', {}).get('disk_gb')

            if recompile or not _compiled:
                if os.path.isfile(path_repro_compile):
                    os.remove(path_repro_compile)

                ###########################################################################################
                compile_uses = compile_desc.get('uses')
                if compile_uses:
                    self_time_compile_with_cmeta = time.time()

                    # The stamp of the build folder: a rebuild that this run implies (the targets
                    # changed, the binary is gone) does not go into a folder built for other targets,
                    # another compiler or other compile parameters; an explicit --recompile does
                    if not params.get('recompile'):
                        r = self.refuse_stale_build(ctx, target_path, self.build_facts(ctx, params, selected_compute))
                        if self.cm.catch_error(r): return r

                    # The free space of the build folder's volume against the program's _desc_sizes.yaml
                    r = self.check_program_disk_space(ctx, params, path, artifact_alias or artifact_uid, target_path, selected_compute)
                    if self.cm.catch_error(r): return r

                    # For setup-compile, which resolves the compiler inside the pipeline: the folder to
                    # compare the compiler with, and whether a rebuild was asked for (--recompile).
                    # A stack, as a lib built on the way runs its own compile-and-run-program
                    ctx['tasks'].setdefault('build_stamps', []).append({'target_path': target_path, 'rebuild': bool(params.get('recompile'))})

                    # --compile_timeout: a deadline for the whole compile phase, the builds that tools
                    # run inside it included (task/cmd caps every command by the time left); closed
                    # before the state is saved, so it never reaches the repro file or the run phase
                    compile_deadline = deadlines.open_deadline(ctx, 'compile', params.get('compile_timeout'), '--compile_timeout')

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
                         'self_desc': desc,
                         'uparams': params,
                        }

#                    if _compile_params:
#                        p['uparams'] = {'compile':_compile_params}

                    try:
                        r = self.cm.access(p)
                    finally:
                        deadlines.close_deadline(ctx, compile_deadline)
                        if ctx['tasks'].get('build_stamps'):
                            ctx['tasks']['build_stamps'].pop()
                            if not ctx['tasks']['build_stamps']:
                                del ctx['tasks']['build_stamps']

                    _impact = r.setdefault('_impact', {})
                    _impact['self_time_compile'] = ctx['tasks']['local'].get('compile-program', {}).get('_impact',{}).get('self_time')
                    _impact['self_time_compile_with_cmeta'] = time.time() - self_time_compile_with_cmeta

                    sizes = self.common_sizes() if r.get('return') == 0 else None
                    if sizes is not None:
                        # What the build took on disk, for the rules of _desc_sizes.yaml
                        _impact['disk_gb'] = round(sizes.folder_gb(target_path), 6)
                        _impact['disk_os'] = uname
                        _impact['disk_arch'] = host['os'].get('uarch')
                        _impact['disk_compute'] = list(selected_compute or [])
                        build_disk_gb = _impact['disk_gb']

                    rx = self.cm.utils.files.write_file(path_repro_compile, {'ctx':ctx, 'result':r}, safe_dump = True)
                    if self.cm.catch_error(rx): return rx

                    if self.cm.catch_error(r): return r

                    # The stamp: what this folder's build is made for (the compiler is resolved now)
                    _compiler_key = ctx['tasks']['local'].get('global_compiler_key')
                    self.write_build_stamp(ctx, target_path, artifact_alias, artifact_uid,
                                           self.build_facts(ctx, params, selected_compute, compiler_key = _compiler_key))

#                ###########################################################################################
#                # Check if customization2 after uses_pre (compute, etc)
#                if hasattr(program_api_code, 'customize2') and callable(getattr(program_api_code, 'customize2')):
#                    r = program_api_code.customize2(ctx, params)
#                    if self.cm.catch_error(r): return r

                ctx_setup_compile = ctx['tasks']['local'].get('setup-compile')

                # Check target program
                target_path_exe = ctx['tasks']['local'].get('target_path_exe')
                if target_path_exe and not os.path.isfile(target_path_exe):
                    return self.cm.error(f'Target file "{target_path_exe}" was not created in "{__file__}"')

        ###########################################################################################
        # Run

        run_desc = desc.get('run', {})

#        if ctx_setup_compile:
#            ctx['tasks']['local']['setup-compile'] = ctx_setup_compile
#
#            for k in ['target_path_exe', 'target_exe']:
#                if k in ctx_setup_compile and k not in ctx_tasks['local']:
#                    ctx['tasks']['local'][k] = ctx_setup_compile[k]
#
#        if 'setup-dynamic-libs' in ctx['tasks']['local']:
#            dynamic_lib_paths = ctx['tasks']['local']['setup-dynamic-libs'].get('found_dynamic_lib_paths')
#            if dynamic_lib_paths:
#                ctx['tasks']['local']['run_time_env']['+PATH'] = dynamic_lib_paths


        self_time_run_with_cmeta = time.time()
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
                     'self_desc': desc,
                     'uparams': params,
                    }

                r = self.cm.access(p)

                rx = self.cm.utils.files.write_file(path_repro_run, {'ctx':ctx, 'result':r}, safe_dump = True)
                if self.cm.catch_error(rx): return rx

                if self.cm.catch_error(r): return r

            # Check result files
            result_files_data = ctx['tasks']['local'].get('result_files_data')

            if result_files_data:
                result.update(result_files_data)

        self_time_compile = ctx_tasks['local'].get('compile-program', {}).get('_impact', {}).get('self_time')

        result['_impact'] = {'self_time_compile_with_cmeta': self_time_compile,
                             'self_time_run_with_cmeta': time.time() - self_time_run_with_cmeta}
        if build_disk_gb is not None:
            result['_impact']['disk_gb'] = build_disk_gb

        return result


