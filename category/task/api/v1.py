"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
import time
import copy

from cmeta.category import InitCategory

class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):

        self.CACHE_FILE_WITH_RESULTS = 'cmeta-task-cached-result.json'
        self.CACHE_FILE_WITH_CTX = 'cmeta-task-cached-ctx.json'
        self.SAVE_FILE_WITH_RESULTS = 'cmeta-task-saved-result.json'
        self.SAVE_FILE_WITH_CTX = 'cmeta-task-saved-ctx.json'

        self.control1 = [
            'arg1', 
            'task_name', 
            'tags', 
            'ver', 
            'info', 
            'save', 
            'save_here', 
            'use', 
            'store_global', 
            'storage_key',
        ]

        self.control2 = [
            'path', 
            'skip', 
            'cache', 
            'cache_repo', 
            'cache_name',
            'cache_extra_alias', 
            'cache_extra_params', 
            'cache_extra_tags',
            'update', 
            'clean', 
            'new',
        ]

        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def test_(self, ctx, arg1=None, flag1=False):
        """
        """

        self.logger.debug("RUNNING API v1 test_")

        print (f'arg1={arg1}')
        print (f'flag1={flag1}')

        return {'return':0}

    ############################################################
    def test2(self, params):
        """
        """

        self.logger.debug("RUNNING API v1 test2")

        import json
        print (json.dumps(params, indent=2))

        return {'return':0}


    ############################################################
    def run(
            self,
            params,
    ):
        """
        """

        self.cm.outdated(__file__, self.cmeta)

        ctx = params['ctx']

        inside_cli = 'cli' in ctx.get('origin',{})

        time_start = time.perf_counter()

        arg1 = params.get('arg1')
        if params.get('task_name'): arg1 = params['task_name']
        tags = params.get('tags')
        ver = params.get('ver')
        info = params.get('info')
        use = params.get('use')

        save = params.get('save', False)
        save_here = params.get('save_here', False)
   
        store_global = params.get('store_global')
        storage_key = params.get('storage_key')

        con = ctx['control'].get('con', False)

        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx.setdefault('tasks', {})
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        cur_dir = os.getcwd()
        cache_path = None
        work_dir = cur_dir

        cache_sep = self.cmeta['cache_alias_separator']

        uses_categories = self.cmeta['uses_categories']

        if use is not None and type(use) != dict:
             return self.cm.error(f'type of "use" is "{type(use)}" in "{__name__}" but it must be "dict"')

        if use is None:
            use = {}

        ctx_use = ctx_tasks.setdefault('use', {})
        if use:
            ctx_use = self.cm.utils.common.deep_merge(ctx_use, copy.deepcopy(use), append_lists=True)

        ###########################################################################################
        # SELECT TASK ARTIFACT

        p = {'category':uses_categories['utils'],
             'command':'select_artifact',
             'select_category':ctx['category'],
             'select_artifact':arg1,
             'select_tags':tags,
             'con':con,
             'quiet':quiet,
             'load_files':['_desc'],
             'space':space,
             'load_api': True,
             'load_api_ver': ver,
             'load_api_class': 'CTask',
             'inside_cli': inside_cli,
        }

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): return r

        artifact = r['artifact']
        cdesc = r['loaded_files']['_desc'].get('data', {})

        task_path = artifact['path']
        cmeta = artifact['cmeta']
        cmeta_ref_parts = artifact['cmeta_ref_parts']

        artifact_alias = r['artifact_alias']
        artifact_uid = r['artifact_uid']
        artifact_au = r['artifact_au']

        category_alias = r['category_alias']
        category_uid = r['category_uid']

        task_api_path = r['api_path']
        task_api_code = r['api_code']
        
        if task_api_code is not None:
            task_api_code.cmeta = cmeta
            task_api_code.task_cmeta = self.cmeta
            task_api_code.cache_sep = cache_sep
            task_api_code.cdesc = cdesc
            task_api_code.artifact_alias = artifact_alias
            task_api_code.artifact_uid = artifact_uid
            task_api_code.artifact_au = artifact_au
            task_api_code.category_alias = category_alias
            task_api_code.category_uid = category_uid

            load_api_ver_resolved = r['load_api_ver_resolved']
            task_api_code.api_ver = load_api_ver_resolved

            if ctx['control'].get('repro', False):
                ctx['repro']['ver'] = load_api_ver_resolved

        ###########################################################################################
        # CHECK INFO (HELP)

        if task_api_code is not None and info:
            r = self.cm.utils.names.restore_cmeta_obj(cmeta_ref_parts, key='artifact', fail_on_error = self.fail_on_error)
            if self.cm.catch_error(r): return r
            category_str = r['obj']

            r = self.cm.utils.sys.get_api_info(task_api_code, 'run', f'task run {artifact_au}')
            if self.cm.catch_error(r): return r

            help_text = r['api_info']

            if con:
                print (help_text)

            return {'return':0, 'help': help_text}

        ###########################################################################################
        # CHECK WINDOWS

        if cdesc.get('fail_if_not_win', False) and os.name != 'nt':
            return self.cm.error(f'the task "{artifact_au}" can run only on Windows')

        ###########################################################################################
        # PRINT SELECTED TASK

        if con and verbose:
            if nested_call>0: print ('')
            print (f'{space}' + '=' * (100-len(space)))
            print (f'{space}TASK: {artifact_alias} ({task_path})')


        ###########################################################################################
        # Unify params to customize task, map for convenience and leave control params
        cparams = {}
        uparams = {}

        for key in params:
            if key in self.control1 + self.control2:
                cparams[key] = params[key]
            elif key != 'ctx':
                uparams[key] = params[key]

        params_map = cdesc.get('params_map', {})
        if params_map:
            for k in params_map:
                key = params_map[k]

                if k in uparams:
                    if k not in uparams:
                        continue

                    v = uparams.pop(k)

                    if '.' in key:
                        fix_keys = True

                        key_parts = key.split('.')

                        current_dict = {}
                        current_dict_root = current_dict

                        first_key = key_parts[0]
                        
                        # Navigate/create nested structure
                        root_key = True
                        for nested_key in key_parts[:-1]:
                            if root_key and fix_keys:
                                nested_key = nested_key.replace('-', '_')
                            if nested_key not in current_dict:
                                current_dict[nested_key] = {}
                            current_dict = current_dict[nested_key]
                            root_key = False
                        
                        # Set the final value
                        if not isinstance(current_dict, dict):
                            x = type(current_dict).__name__
                            raise TypeError(f"{current_dict} must be a dict, not {x}")

                        current_dict[key_parts[-1]] = v

                        if first_key == 'use':
                            _use = self.cm.utils.common.deep_merge(_use, current_dict_root['use'], append_lists=True)

                        elif first_key == 'ctx':
                            ctx = self.cm.utils.common.deep_merge(ctx, current_dict_root['ctx'], append_lists=True)

                        else:
                            uparams = self.cm.utils.common.deep_merge(uparams, current_dict_root, append_lists=True)

                    else:
                        uparams[key] = v


        ###########################################################################################
        # PREPARE GLOBAL CONTEXT AND DUMMY RESULT

        result = {'return':0}

        ctx_tasks.setdefault('global', {})

        saved_local = ctx_tasks.get('local')
        ctx_tasks['local'] = {}

        saved_uparams = ctx_tasks.get('params')
        ctx_tasks['params'] = uparams

        # Useful to aggregate various info for the whole pipeline (such as env for complex run/compilation)
        _aggregated = ctx_tasks.setdefault('aggregated', {})

        ###########################################################################################
        # CHECK DEPENDENCIES BEFORE INIT CALL TO TASK API (IF EXISTS)
        # Can update global/local deps

        uses_before_init = cdesc.get('uses_before_init', []).copy()
        if uses_before_init:
            r = self.use_(ctx, 
                          desc = uses_before_init, 
                          local = ctx_tasks['local'],
                          task_artifact_alias = artifact_alias, 
                          task_artifact_uid = artifact_uid,
            )
            if self.cm.catch_error(r): return r

        ###########################################################################################
        # RUN INIT FROM TASK CODE IF EXISTS
        # Can check and update params 

        task_extra_uses = []
        if task_api_code is not None and hasattr(task_api_code, 'init') and callable(getattr(task_api_code, 'init')):
            r = task_api_code.init(ctx, ctx_tasks['params'])
            if self.cm.catch_error(r): return r

            if 'uses' in r:
                task_extra_uses = r['uses']

            # Customized storage_key!
            if r.get('storage_key'):
                storage_key = r['storage_key']

        ###########################################################################################
        # SAVE CALL IF SELF.DEBUG (maybe should use some other flag?)

        call_repro = None
        if self.cm.debug:
            calls = ctx_tasks.setdefault('calls', [])

            call_repro = {'params': ctx['params'].copy(), 'nested_call': nested_call}

            calls.append(call_repro)

        ###########################################################################################
        # FINISH RESOLVING STORAGE KEY AND WHERE TO STORE RESULT

        if store_global is None:
            store_global = cdesc.get('store_global')

        if not storage_key:
            storage_key = cdesc.get('storage_key')

        if storage_key:
            r = self.cm.utils.common.expand_string(storage_key, ctx_tasks)
            if self.cm.catch_error(r): return r
            storage_key = r['string']

        if not storage_key:
            storage_key = str(artifact_alias)



        ###########################################################################################
        # If not local and result already exists in global, reuse result

        if store_global and storage_key and storage_key in ctx_tasks['global']:

            # REUSE DEPENDENCY RESULT FROM GLOBAL CONTEXT!!!
            if con and verbose:
                print ('')
                print (f'{space}REUSE: load task result from ctx["tasks"]["global"]["{storage_key}"]')

            result = copy.deepcopy(ctx_tasks['global'][storage_key])

            # Do not aggregate - already done!
            r = self._finish_run(ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here,
                                 call_repro, aggregate = False, 
                                 saved_uparams = saved_uparams, saved_local = saved_local,
            )
            if self.cm.catch_error(r): return r
            
            return result


        ###########################################################################################
        # UPDATE PARAMS FROM USE ...

        if ctx_use:
            for use_key in ctx_use:
                if use_key == storage_key:
                    use_params = ctx_use[use_key].copy()

                    use_control_params = {}

                    for k in list(use_params.keys()):
                        if k in self.control2:
                            use_control_params[k] = use_params.pop(k)

                    if use_params:
                        ctx_tasks['params'] = self.cm.utils.common.deep_merge(ctx_tasks['params'], use_params, append_lists=True)
                    if use_control_params:
                        cparams = self.cm.utils.common.deep_merge(cparams, use_control_params, append_lists=True)

        ###########################################################################################
        # CHECK PARAMS INCLUDING FROM --use. ...

        if task_api_code is not None and hasattr(task_api_code, 'check_params') and callable(getattr(task_api_code, 'check_params')):
            r = task_api_code.check_params(ctx, ctx_tasks['params'], cparams)
            if self.cm.catch_error(r): return r


        ###########################################################################################
        # EXPAND ALL CONTROL PARAMS

        path = cparams.get('path')
        skip = cparams.get('skip', False)

        cache = cparams.get('cache')
        cache_repo = cparams.get('cache_repo')
        cache_name = cparams.get('cache_name')
        cache_extra_alias = cparams.get('cache_extra_alias')
        cache_extra_params = cparams.get('cache_extra_params')
        cache_extra_tags = cparams.get('cache_extra_tags')

        update = cparams.get('udpate', False)
        clean = cparams.get('clean', False)
        new = cparams.get('new', False)


        ###########################################################################################
        # CHECK DEPENDENCIES
        uses = cdesc.get('uses', []).copy()

        if task_extra_uses:
            uses += task_extra_uses

        # Set up local context
        if uses:
            r = self.use_(ctx, 
                          desc = uses, 
                          local = ctx_tasks['local'],
                          task_artifact_alias = artifact_alias, 
                          task_artifact_uid = artifact_uid,
            )
            if self.cm.catch_error(r): return r

        ###########################################################################################
        # PROCESS CACHE

        task_result_file = None
        update_cache = False

        cache_params = {}
        if cache_extra_params:
            cache_params = copy.deepcopy(cache_extra_params)

        if cache is None:
            cache = cdesc.get('cache')

        if cache:
            # Check if compatible with cache
            if cdesc.get('no_cache', False):
                return self.cm.error(f'the task "{artifact_au}" does not support cache')

            # May have been updated by various customizations and uses from above ...
            uparams = ctx_tasks['params']

            # Need to prepare alias and tags
            cache_alias_template = f'task{cache_sep}{artifact_alias}{{cache_extra_alias}}'

            # Note that cache_meta will be used first to match existing cache entries 
            # and later updated with extra things that shouldn't be matched, such as path
            cache_meta = {'cref':{'category_alias': 'task',
                                  'category_uid': category_uid,
                                  'artifact_alias': artifact_alias,
                                  'artifact_uid': artifact_uid,
                                 },
                          'params':{},
                         }

            cache_tags = ['task', category_uid, artifact_alias, artifact_uid]

            # Notice that path should also separate entries, i.e.
            # if we want to download a file to a different place, it should have 
            # different cache entry ... If one wants to reuse existing one,
            # they sould use --update
            if path:
                cache_meta['path'] = path

            if cache_extra_tags:
                if type(cache_extra_tags) == list:
                    cache_tags += cache_extra_tags
                else:
                    cache_tags += cache_extra_tags.split(',')

            # Check if params keys are defined in cdesc to be added to cache_tags
            for k in cdesc.get('cache_params', []):
                kk = k[1:] if k.startswith('@') else k
                v = uparams.get(kk)
                if v is not None:
                    cache_params[k] = v

            if task_api_code is not None:
                r = task_api_code.customize_cache_artifact(ctx, cache_alias_template, cache_extra_alias, cache_meta, cache_tags, cache_params, uparams)
                if self.cm.catch_error(r): return r

                if cache_name is None and 'cache_name' in r: cache_name = r['cache_name']
                if 'cache_extra_alias' in r: cache_extra_alias = r['cache_extra_alias']
                if 'cache_alias_template' in r: cache_alias_template = r['cache_alias_template']

            # Check if exists
            ii = {'category':uses_categories['cache'],
                  'command':'find',
                 }

            cache_meta['params'] = self.cm.utils.common.deep_merge(cache_meta['params'], cache_params, append_lists=False)

            if cache_name:
                ii['arg1'] = cache_name
            else:
                ii['tags'] = cache_tags
                ii['match'] = cache_meta
                ii['match_empty_version'] = True

            if cache_repo and not cache_name:
                ii['arg1'] = cache_repo + ':'

            if new:
                cache_artifacts = []
            else:
                # Search in cache !
                r = self.cm.access(ii)
                if r['return']>0 and r['return']!=16: return r

                cache_artifacts = r.get('artifacts', [])

            # Clean params in cache_meta that that start from @ - 
            # these are fuzzy versions with conditions 
            # that should be resolved to the normal key
            for key in list(cache_meta['params'].keys()):
                if key.startswith('@'):
                    del(cache_meta['params'][key])

            for key in list(cache_params.keys()):
                if key.startswith('@'):
                    del(cache_params[key])

            # Add any extra info to cache_meta if needed:

            tmp_cache_artifacts = []

            ###########################################################################################
            if len(cache_artifacts)>0:
                # If multiple ones, remove unfinished ones
                finished_cache_artifacts = []

                for cache_artifact in cache_artifacts:
                    ca_tool_path = cache_artifact['cmeta'].get('params',{}).get('tool_path')
                    if 'tmp' in cache_artifact['cmeta'].get('tags',[]) or \
                       (ca_tool_path and not (os.path.isfile(ca_tool_path) or os.path.isdir(ca_tool_path))):
                        if 'tmp' not in cache_artifact['cmeta'].get('tags',[]):
                            cache_artifact['cmeta'].setdefault('tags',[])
                            cache_artifact['cmeta']['tags'].append('tmp')
                        tmp_cache_artifacts.append(cache_artifact)
                    else:
                        finished_cache_artifacts.append(cache_artifact)

                cache_artifacts = finished_cache_artifacts

            ###########################################################################################
            if len(cache_artifacts)>1:

                text = ''

                if verbose:
                    text += '\n'

                text += f'{space}WARNING: More than 1 cache entry found for task "{artifact_alias}"'

                if len(cache_params)>0:
                    text += ' with parameters:\n'
                    for p in sorted(cache_params):
                        v = str(cache_params[p])
                        text += f'{space}      * params.{p} = {v}\n'
                    text += '\n'
                else:
                    text += '. '

                text += f'{space}Please select'

                # Call base find function to find an artifact with a website
                p = {'category': uses_categories['utils'],
                     'command': 'select_artifact',
                     'select_category': 'cache',
                     'select_text': text,
                     'artifacts': cache_artifacts,
                     'cmeta_params_keys': ['params', 'path'],
                     'skip_uids': True,
                     'con':con,
                     'quiet':quiet,
                     'space':space,
                }

                if 'sort_keys' in cdesc:
                    p['sort_keys'] = cdesc['sort_keys']

                r = self.cm.access(p)
                if self.cm.catch_error(r, fail16 = True): return r

                cache_artifacts = [r['artifact']]


            ###########################################################################################
            if len(cache_artifacts) == 1:
                cache_artifact = cache_artifacts[0]

                cache_path = cache_artifact['path']
                cache_meta = cache_artifact['cmeta']

                if not path:
                    path = cache_meta.get('path')


                ###############################################################################################
                if 'tmp' not in cache_artifact['cmeta'].get('tags',[]) and not update and not clean:

                    ###########################################################################################
                    # RETURN CACHED RESULT !!!!!!

                    if con and verbose:
                        print ('')
                        print (f'{space}REUSE: load task result from {cache_path}')

                    if not path:
                        path = cache_path

                    task_result_file = os.path.join(path, self.CACHE_FILE_WITH_RESULTS)
                    r = self.cm.utils.files.read_file(task_result_file)
                    if self.cm.catch_error(r): return r

                    # If not found but cache exists, often the path is outside cache and was deleted - need to recreate!
                    # similar to turning --update and or --clean option
                    if r['return'] == 0:
                        result = r['data']

                        if storage_key:
                            if store_global:
                                ctx_tasks['global'][storage_key] = result
                            else:
                                ctx_tasks['local'][storage_key] = result

                        r = self._finish_run(ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here,
                                             call_repro, aggregate = True,
                                             saved_uparams = saved_uparams, saved_local = saved_local,
                        )
                        if self.cm.catch_error(r): return r

                        return result



                ###########\####################################################################################
                cache_cmeta_ref_parts = cache_artifact['cmeta_ref_parts']
                cache_alias = cache_cmeta_ref_parts['artifact_alias']
                cache_uid = cache_cmeta_ref_parts['artifact_uid']
                cache_name = f'{cache_alias},{cache_uid}'
                if cache_repo:
                    cache_name = cache_repo + ':' + cache_name
                update_cache = True


            ###########################################################################################
            if len(cache_artifacts) == 0:
               # Create with tmp tag
               update_cache = True

               if len(tmp_cache_artifacts)>0:
                   # Reuse the first from tmp cache artifacts to avoid creating many tmp ones
                   cache_path = tmp_cache_artifacts[0]['path']
                   cache_meta = tmp_cache_artifacts[0]['cmeta']
                   cache_cmeta_ref_parts = tmp_cache_artifacts[0]['cmeta_ref_parts']
                   cache_alias = cache_cmeta_ref_parts['artifact_alias']
                   cache_uid = cache_cmeta_ref_parts['artifact_uid']
                   cache_name = f'{cache_alias},{cache_uid}'

               else:
                   if cache_name is None or cache_name == '':
                       cache_uid = self.cm.utils.generate_cmeta_uid()
                       cache_extra_alias = '' if cache_extra_alias is None else cache_sep + cache_extra_alias
                       cache_alias = cache_alias_template.replace('{cache_extra_alias}', cache_extra_alias)
                       cache_name = f'{cache_alias}{cache_sep}{cache_uid},{cache_uid}'
                       if cache_repo:
                           cache_name = cache_repo + ':' + cache_name

                   r = self.cm.access({'category':uses_categories['cache'],
                                       'command':'create',
                                       'arg1':cache_name,
                                       'tags':cache_tags + ['tmp'],
                                       'meta':cache_meta
                       })
                   if self.cm.catch_error(r): return r

                   cache_path = r['path']
                   cache_meta = r['meta']

            if cache_name is None:
                return self.cm.error('Inconsistency in task cache handling since cache_name is None')
            if cache_path is None:
                return self.cm.error('Inconsistency in task cache handling since cache_path is None')

            if con and verbose:
                print ('')
                print (f'{space}CACHE: use "{cache_path}"')

            # Check if result already exists in the path and without error - it means rebuilding existing cache entry ...
            if path and os.path.isdir(path):
                task_result_file = os.path.join(path, self.CACHE_FILE_WITH_RESULTS)
                if os.path.isfile(task_result_file) and not update and not clean:
                    r = self.cm.utils.files.read_file(task_result_file)
                    if self.cm.catch_error(r): return r

                    result = r['data']
                    
                    if result['return'] == 0:
                        if con and verbose:
                            print ('')
                            print (f'{space}REUSE: result file {task_result_file}')

                        skip = True


        ###########################################################################################
        # PREPARE WORKING DIRECTORY
        if path:
            work_dir = path
        elif cache_path:
            work_dir = cache_path
            
        if not os.path.isdir(work_dir):
            os.makedirs(work_dir, exist_ok=True)

        if con and verbose and work_dir != cur_dir:
            print ('')
            print (f'{space}RUN: cd {work_dir}')

        os.chdir(work_dir)

        if task_result_file and os.path.isfile(task_result_file) and (clean or update):
            if con and verbose:
                print ('')
                print (f'{space}RUN: rm {task_result_file}')

            os.remove(task_result_file)



        ###########################################################################################
        # RUN TASK CODE IF EXISTS

        time_start2 = time.perf_counter()
        if not skip and task_api_code is not None \
            and hasattr(task_api_code, 'run') and callable(getattr(task_api_code, 'run')):
            if con and verbose:
                print ('')
                print (f'{space}RUN TASK CODE: {task_api_path}')

            ctx_tasks_control = ctx['tasks']['run_control'] = {}
            if update:
                ctx_tasks_control['update'] = True
            if clean:
                ctx_tasks_control['clean'] = True
            if new:
                ctx_tasks_control['new'] = True

            ctx_tasks_control['cur_dir'] = cur_dir
            ctx_tasks_control['work_dir'] = work_dir
            ctx_tasks_control['task_path'] = task_path
            ctx_tasks_control['task_api_path'] = task_api_path
            ctx_tasks_control['task_desc'] = cdesc

            if cache_params:
                ctx_tasks_control['cache_params'] = cache_params

            result = task_api_code.run(ctx, **uparams)

            # Check if success or fail
            if result['return']>0:
                if cache:
                    r = self.cm.utils.files.write_file(self.CACHE_FILE_WITH_RESULTS, result)
                    if self.cm.catch_error(r): return r

                return self.cm.error(result['error'], result['return'])




        # Check if extra params were produced by the task that should be added to cache entry
        _update_params = result.pop('_update_params', {})
        if len(_update_params)>0 and cache:
            update_cache = True

        if len(_update_params)>0:
            cache_params = self.cm.utils.common.deep_merge(cache_params, _update_params, append_lists=False)

        if len(cache_params)>0:
            result['_params'] = cache_params

        _impact = result.setdefault('_impact', {})
        _impact['self_time'] = time.perf_counter() - time_start2
        _impact['self_time_with_cmeta'] = time.perf_counter() - time_start

        ###########################################################################################
        # UPDATE CACHE

        if update_cache:
            if con and verbose:
                print ('')
                print (f'{space}UPDATE: cache in {cache_name}')
           
            # TBD -> maybe move result error there for debugging?
            ii = {'category':uses_categories['cache'],
                  'command':'update',
                  'arg1':cache_name,
                  'new_tags':['tmp-'],
                 }

            # Check if extra params were produced by the task that should be added to cache entry
            if len(cache_params)>0:
                ii['meta'] = {'params':cache_params}

            r = self.cm.access(ii)
            if self.cm.catch_error(r): return r

        # Save result to cache for reuse
        if cache:
            r = self.cm.utils.files.write_file(self.CACHE_FILE_WITH_RESULTS, result)
            if self.cm.catch_error(r): return r
            r = self.cm.utils.files.write_file(self.CACHE_FILE_WITH_CTX, ctx)
            if self.cm.catch_error(r): return r

        # Finish run
        if storage_key:
            if store_global:
                ctx_tasks['global'][storage_key] = result
            else:
                ctx_tasks['local'][storage_key] = result

        r = self._finish_run(ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here,
                             call_repro, aggregate = True,
                             saved_uparams = saved_uparams, saved_local = saved_local,
        )
        if self.cm.catch_error(r): return r

        return result


    ###########################################################################################
    # Finalize run

    def _finish_run(
                   self,
                   ctx = {},
                   con = False,
                   verbose = False,
                   work_dir = None,
                   cur_dir = None,
                   space = '',
                   save = False,
                   result = {},
                   save_here = False,
                   call_repro = None,
                   aggregate = True,
                   saved_uparams = None,
                   saved_local = None,
    ):

        # Save output for reproducibility
        if self.cm.debug:
            call_repro['result'] = copy.deepcopy(result)

        # Check aggregated results
        if aggregate and '_aggregate' in result:
            _aggregate = result['_aggregate']
            ctx_tasks = ctx.setdefault('tasks', {})
            _aggregated = ctx_tasks.setdefault('aggregated', {})
            _aggregated = self.cm.utils.common.deep_merge(_aggregated, _aggregate, append_lists = True, prepend_lists=True)

        # Save results in the work_dir directory (cache, path, etc)
        if save:
            if con:
                x = os.getcwd()
                print ('')
                print (f'SAVE: in path "{x}"')

            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_RESULTS, result)
            if self.cm.catch_error(r): return r
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_CTX, ctx)
            if self.cm.catch_error(r): return r

        if con and verbose and work_dir != cur_dir:
            print ('')
            print (f'{space}RUN: cd {cur_dir}')

        os.chdir(cur_dir)

        # Save results in the current directory where this task was called from
        if save_here:
            if con:
                print ('')
                print (f'SAVE: in path "{cur_dir}"')

            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_RESULTS, result)
            if self.cm.catch_error(r): return r
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_CTX, ctx)
            if self.cm.catch_error(r): return r

        
        ctx['tasks']['params'] = saved_uparams if saved_uparams else {}
        ctx['tasks']['local'] = saved_local if saved_local else {}

        return {'return':0}


    ############################################################
    def use_(
            self,
            ctx: dict,
            desc: dict = {},
            local = None,
            task_artifact_alias = None,
            task_artifact_uid = None,
    ):

        """
        Resolve sub_tasks

        Args:
            ctx (dict): cMeta context.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx.setdefault('tasks', {})
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        sub_space = '  ' * (nested_call + 1) if verbose else ''

        if local:
            saved_local = ctx_tasks.get('local', {})
            ctx_tasks['local'] = local

        for sub_task_desc in desc:

            # *********************************************************************************
            # Process individual sub-task

            task = sub_task_desc.get('task', None)
            if not task:
                return self.cm.error(f'the requirement in task "{task_artifact_alias}" misses "task" name or uid')

            name = sub_task_desc.get('name', '')
            if name and con and verbose:
                print ('')
                print (f'{sub_space}==> {name}')

            if sub_task_desc.get('skip_if_not_win', False) and os.name != 'nt':
                if con and verbose:
                    print ('')
                    print (f'TASK: {task} - SKIPPED on non-win host')

                continue

            # Check if some unknown keys in sub_task_desc
            unknown_keys = [k for k in sub_task_desc.keys() if k not in ['task', 'with', 'storage_key', 'store_global', 'cache', 
                                                                         'if', 'skip_if_not_win', 'category', 'command']]
            if unknown_keys:
                x = ','.join(unknown_keys)
                return self.cm.error(f'unknown key(s) "{x}" in sub-task description in "{__name__}"')

            # Prepare input
            sub_task_category = 'task,' + self.cmeta['artifact'] if 'category' not in sub_task_desc else sub_task_desc['category']
            sub_task_command = 'run' if 'command' not in sub_task_desc else sub_task_desc['command']

            _with = sub_task_desc.get('with', {})

            if type(_with) is not dict:
                return self.cm.error(f'"with" key must be "dict" in {sub_task_desc} in "{__name__}"')
               
            force_store_global = sub_task_desc.get('store_global')
            force_storage_key = sub_task_desc.get('storage_key')
            force_cache = sub_task_desc.get('cache')

            # *********************************************************************************
            # Check conditions

            _if = sub_task_desc.get('if', '')
            if _if:
                r = self.cm.utils.common.expand_string(_if, ctx_tasks)
                if self.cm.catch_error(r): return r

                _if = r['string']

                r = self.cm.utils.common.restricted_bool_eval(_if, {})
                if self.cm.catch_error(r): return r

                # If condition is not met, skip sub-task
                if not r['result']:
                    continue

            # *********************************************************************************
            # Run task
            ii = copy.deepcopy(_with)

            if force_cache: ii['cache'] = force_cache
            if force_store_global: ii['store_global'] = force_store_global
            if force_storage_key: ii['storage_key'] = force_storage_key

            r = self.cm.utils.common.expand_strings_in_dict(ii, ctx_tasks)
            if self.cm.catch_error(r): return r

            ii['ctx'] = ctx
            ii['arg1'] = task

            ii['category'] = sub_task_category
            ii['command'] = sub_task_command

            ii['con'] = con
            ii['quiet'] = quiet
            ii['verbose'] = verbose

            # Update context for tasks
            ctx_tasks['nested_call'] += 1

            sub_task_result = self.cm.access(ii)
            if self.cm.catch_error(sub_task_result): return sub_task_result

            ctx_tasks['nested_call'] -= 1

        if local:
            ctx_tasks['local'] = saved_local

        return {'return':0, 'local': local}
