"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.
License: Proprietary - contact the author for licensing information.
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
        self.CACHE_FILE_WITH_STATE = 'cmeta-task-cached-state.json'
        self.SAVE_FILE_WITH_RESULTS = 'cmeta-task-saved-result.json'
        self.SAVE_FILE_WITH_STATE = 'cmeta-task-saved-state.json'

        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def test_(self, state, arg1=None, flag1=False):
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
    def run_(
            self,
            state: dict,                      # cMeta state
            arg1: str = None,                 # Task artifact alias or UID
            tags: str = None,                 # Optional tag filter
            ver: int = None,                  # version

            info: bool = False,               # If True, show help about params passed to a given task module (Python API and flags)

            path: str = None,                 # Working directory (change path there)
            save: bool = False,               # Force save results even if not cached
            save_here: bool = False,          #
            skip: bool = False,               # If True, skip task run but keep all the rest

            cache: bool = None,               # If True, use cache to process this task
            cache_repo: str = None,           # Force to use non "local" repo
            cache_name: str = None,           # Use custom cache alias instead of automatically generated one
            cache_alias_extra: str = None, 
            cache_extra_params: dict = None,
            cache_extra_tags: str = None,

            update: bool = False,             # Rerun task and update cache entry even if exists
            clean: bool = False,              # Clean cache entry or path 
            new: bool = False,                # Create new entry (for new versions)

            use: dict = None,

            store_global: bool = None,              # Force store in global memory
            storage_key: str = None,          # Force storage key

            **params: dict,                   # Parameters passed to a given task module
    ):

        """
        Run a task.

        Args:
            state (dict): cMeta state.
            arg1 (str | None): Artifact alias or UID.
            tags (str | list | None): Optional tag filter.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        time_start = time.perf_counter()

        con = state['control'].get('con', False)
        quiet = state['control'].get('quiet', False)
        verbose = state['control'].get('verbose', False)
        api = state['control'].get('api', 1)
        inside_cli = 'cli' in state.get('origin',{})

        state_tasks = state.setdefault('tasks', {})
        nested_call = state_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call

        cur_dir = os.getcwd()
        cache_path = None
        workdir = cur_dir

        uses_categories = self.cmeta['uses_categories']

        if use is not None and type(use) != dict:
             err = f'type of "use" is "{type(use)}" in "{__name__}" but it must be "dict"'
             return self.cm._error(err, 1, None, self.cm.fail_on_error)

        if use is None:
            use = {}

        state_use = state_tasks.setdefault('use', {})
        if use:
            state_use = self.cm.utils.common.deep_merge(state_use, copy.deepcopy(use), append_lists=True)

        ###########################################################################################
        # SELECT TASK ARTIFACT

        # Call base find function to find an artifact with a website
        p = {'category':uses_categories['utils'],
             'command':'select_artifact',
             'select_category':state['category'],
             'select_artifact':arg1,
             'select_tags':tags,
             'con':con,
             'quiet':quiet,
             'load_files':['desc'],
             'space':space,
             'load_api': True,
             'load_api_ver': ver,
             'load_api_class': 'CTask',
        }

        r = self.cm.access(p)
        if r['return']>0: 
            ret = r['return']
            if ret == 16: ret = 1
            return self.cm._error(r['error'], ret, None, self.cm.fail_on_error)

        artifact = r['artifact']
        cdesc = r['loaded_files']['desc'].get('data', {})

        artifact_path = artifact['path']
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
            task_api_code.cdesc = cdesc
            task_api_code.artifact_alias = artifact_alias
            task_api_code.artifact_uid = artifact_uid
            task_api_code.artifact_au = artifact_au
            task_api_code.category_alias = category_alias
            task_api_code.category_uid = category_uid

        if task_api_code is not None and info:
            r = self.cm.utils.names.restore_cmeta_obj(cmeta_ref_parts, key='artifact', fail_on_error = self.fail_on_error)
            if r['return']>0: return self.cm._error2(r, self.cm)
            category_str = r['obj']

            r = self.cm.utils.sys.get_api_info(task_api_code, 'run', f'task run {artifact_au}')
            if r['return']>0: return self.cm._error2(r, self.cm)

            help_text = r['api_info']

            if con:
                print (help_text)

            return {'return':0, 'help': help_text}


        if cdesc.get('fail_if_not_win', False) and os.name != 'nt':
            err = f'the task "{artifact_au}" can run only on Windows'
            return self.cm._error(err, 1, None, self.cm.fail_on_error)

        ###########################################################################################
        # PRINT SELECTED TASK

        if con and verbose:
            if nested_call>0: print ('')
            print (f'{space}' + '=' * (100-len(space)))
            print (f'{space}TASK: {artifact_alias} ({artifact_path})')


        ###########################################################################################
        # PREPARE GLOBAL CONTEXT AND DUMMY RESULT

        _global = state_tasks.setdefault('global', {})
        _aggregated = state_tasks.setdefault('aggregated', {})
        _local = {}

        result = {'return':0}


        ###########################################################################################
        # UNIFY PARAMS - most commonly convert args to keys

        uparams = params.copy()

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
                            raise TypeError(f"{current_dict} must be a dict, not {type(current_dict).__name__}")

                        current_dict[key_parts[-1]] = v

                        if first_key == 'use':
                            _use = self.cm.utils.common.deep_merge(_use, current_dict_root['use'], append_lists=True)

                        elif first_key == 'state':
                            state = self.cm.utils.common.deep_merge(state, current_dict_root['state'], append_lists=True)

                        else:
                            uparams = self.cm.utils.common.deep_merge(uparams, current_dict_root, append_lists=True)

                    else:
                        uparams[key] = v


        ###########################################################################################
        # RUN EXTRA CHECK FROM CODE IF EXISTS
        task_extra_uses = []
        if task_api_code is not None and hasattr(task_api_code, 'check_params') and callable(getattr(task_api_code, 'check_params')):
            r = task_api_code.check_params(state, uparams)
            if r['return']>0: return self.cm._error2(r, self.cm)

            if 'uses' in r:
                task_extra_uses = r['uses']

        ###########################################################################################
        # SAVE CALL IF SELF.DEBUG (maybe should use some other flag?)

        call_repro = None
        if self.cm.debug:
            calls = state_tasks.setdefault('calls', [])

            call_repro = {'params': state['params'].copy(), 'nested_call': nested_call}

            calls.append(call_repro)

        ###########################################################################################
        # CHECK GLOBAL OR LOCAL STORAGE FOR THIS TASK

        context = {
           'global':_global, 
           'local':_local, 
           'params':uparams,
        }

        # Resolve storage_key and where to store
        store_in_global = False
        if store_global is not None:
            store_in_global = store_global
        elif 'store_global' in cdesc:
            store_in_global = cdesc['store_global']

        if storage_key is None:
            if 'storage_key' in cdesc:
                storage_key = cdesc['storage_key']

        if storage_key is None:
            storage_key = str(artifact_alias)

        r = self.cm.utils.common.expand_string(storage_key, context)
        if r['return']>0: return self.cm._error2(r, self.cm)
        storage_key = r['string']

        # If not local  result already exists in global, skip sub-task
        if store_in_global and storage_key and storage_key in _global:
            # REUSE DEPENDENCY RESULT FROM GLOBAL CONTEXT!!!
            if con and verbose:
                print ('')
                print (f'{space}REUSE: load task result from _global["{storage_key}"]')

            result = copy.deepcopy(_global[storage_key])

            # Do not aggregate - already done!
            r = self._finish_run(state, con, verbose, workdir, cur_dir, space, save, result, save_here,
                                 call_repro, aggregate = False)
            if r['return']>0: return self.cm._error2(r, self.cm)
            
            return result


        ###########################################################################################
        # CHECK DEPENDENCIES
        uses = cdesc.get('uses', []).copy()

        if task_extra_uses:
            uses += task_extra_uses

        # Set up local context
        if uses:
            r = self.use_(state, 
                          desc = uses, 
                          nested_call = nested_call, 
                          local = _local,
                          task_artifact_alias = artifact_alias, 
                          task_artifact_uid = artifact_uid,
            )
            if r['return']>0: return self.cm._error2(r, self.cm)



        ###########################################################################################
        # SAVE LOCAL TO STATE TO BE USED WITH TASK CODE IF NEEDED ...
        # IT SHOULD NOT BE USED OUTSIDE A RUNNING TASK

        state_tasks['local'] = _local

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
                err = f'the task "{artifact_au}" does not support cache'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)

            # Need to prepare alias and tags
            cache_alias_template = f'task,{artifact_alias}{{cache_alias_extra}}'

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
                r = task_api_code.customize_cache_artifact(state, cache_alias_template, cache_alias_extra, cache_meta, cache_tags, cache_params, uparams)
                if r['return']>0: return self.cm._error2(r, self.cm)

                if cache_name is None and 'cache_name' in r: cache_name = r['cache_name']
                if cache_alias_extra is None and 'cache_alias_extra' in r: cache_alias_extra = r['cache_alias_extra']
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

            if len(cache_artifacts)>0:
                # If multiple ones, remove unfinished ones
                finished_cache_artifacts = []

                for cache_artifact in cache_artifacts:
                    if 'tmp' in cache_artifact['cmeta'].get('tags',[]):
                        tmp_cache_artifacts.append(cache_artifact)
                    else:
                        finished_cache_artifacts.append(cache_artifact)

                if len(finished_cache_artifacts)>0:
                    cache_artifacts = finished_cache_artifacts

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
                if r['return']>0: 
                    ret = r['return']
                    if ret == 16: ret = 1
                    return self.cm._error(r['error'], ret, None, self.cm.fail_on_error)

                cache_artifacts = [r['artifact']]


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
                    if r['return']>0 and r['return']!=16: 
                        return self.cm._error2(r, self.cm)

                    # If not found but cache exists, often the path is outside cache and was deleted - need to recreate!
                    # similar to turning --update and or --clean option
                    if r['return'] == 0:
                        result = r['data']

                        if storage_key:
                            if store_in_global:
                                _global[storage_key] = result
                            else:
                                _local[storage_key] = result

                        r = self._finish_run(state, con, verbose, workdir, cur_dir, space, save, result, save_here,
                                             call_repro, aggregate = True)
                        if r['return']>0: return self.cm._error2(r, self.cm)

                        return result



                ###############################################################################################
                cache_cmeta_ref_parts = cache_artifact['cmeta_ref_parts']
                cache_alias = cache_cmeta_ref_parts['artifact_alias']
                cache_uid = cache_cmeta_ref_parts['artifact_uid']
                cache_name = f'{cache_alias},{cache_uid}'
                if cache_repo:
                    cache_name = cache_repo + ':' + cache_name
                update_cache = True


            if len(cache_artifacts) == 0:
               # Create with tmp tag
               update_cache = True

               if len(tmp_cache_artifacts)>0:
                   # Reuse the first from tmp cache artifacts to avoid creating many tmp ones
                   cache_path = tmp_cache_artifacts[0]['path']
                   cache_meta = tmp_cache_artifacts[0]['meta']

               else:
                   if cache_name is None or cache_name == '':
                       cache_uid = self.cm.utils.generate_cmeta_uid()
                       cache_alias_extra = '' if cache_alias_extra is None else ',' + cache_alias_extra
                       cache_alias = cache_alias_template.replace('{cache_alias_extra}', cache_alias_extra)
                       cache_name = f'{cache_alias},{cache_uid},{cache_uid}'
                       if cache_repo:
                           cache_name = cache_repo + ':' + cache_name

                   r = self.cm.access({'category':uses_categories['cache'],
                                       'command':'create',
                                       'arg1':cache_name,
                                       'tags':cache_tags + ['tmp'],
                                       'meta':cache_meta
                       })
                   if r['return']>0: return self.cm._error2(r, self.cm)

                   cache_path = r['path']
                   cache_meta = r['meta']

            if con and verbose:
                print ('')
                print (f'{space}CACHE: use {cache_path}')

            # Check if result already exists in the path and without error - it means rebuilding existing cache entry ...
            if path and os.path.isdir(path):
                task_result_file = os.path.join(path, self.CACHE_FILE_WITH_RESULTS)
                if os.path.isfile(task_result_file) and not update and not clean:
                    r = self.cm.utils.files.read_file(task_result_file)
                    if r['return']>0: return self.cm._error2(r, self.cm)

                    result = r['data']
                    
                    if result['return'] == 0:
                        if con and verbose:
                            print ('')
                            print (f'{space}REUSE: result file {task_result_file}')

                        skip = True


        ###########################################################################################
        # PREPARE WORKING DIRECTORY
        if path:
            workdir = path
        elif cache_path:
            workdir = cache_path
            
        if not os.path.isdir(workdir):
            os.makedirs(workdir, exist_ok=True)

        if con and verbose and workdir != cur_dir:
            print ('')
            print (f'{space}RUN: cd {workdir}')

        os.chdir(workdir)

        if task_result_file and os.path.isfile(task_result_file) and (clean or update):
            if con and verbose:
                print ('')
                print (f'{space}RUN: rm {task_result_file}')

            os.remove(task_result_file)



        ###########################################################################################
        # RUN TASK CODE IF EXISTS

        # Restore basic state control that may be changed by deps
        state['control']['con'] = con
        state['control']['quiet'] = quiet
        state['control']['verbose'] = verbose

        time_start2 = time.perf_counter()
        if not skip and task_api_code is not None \
            and hasattr(task_api_code, 'run') and callable(getattr(task_api_code, 'run')):
            if con and verbose:
                print ('')
                print (f'{space}RUN TASK CODE: {task_api_path}')

            state_tasks_control = state['tasks']['control'] = {}
            if update:
                state_tasks_control['update'] = True
            if clean:
                state_tasks_control['clean'] = True
            if new:
                state_tasks_control['new'] = True

            result = task_api_code.run(state, **uparams)

            # Check if success or fail
            if result['return']>0:
                if cache:
                    r = self.cm.utils.files.write_file(self.CACHE_FILE_WITH_RESULTS, result)
                    if r['return']>0: return self.cm._error2(r, self.cm)

                return self.cm._error(result['error'], result['return'], None, self.cm.fail_on_error)
 




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
            if r['return']>0: return self.cm._error2(r, self.cm)

        # Save result to cache for reuse
        if cache:
            r = self.cm.utils.files.write_file(self.CACHE_FILE_WITH_RESULTS, result)
            if r['return']>0: return self.cm._error2(r, self.cm)
            r = self.cm.utils.files.write_file(self.CACHE_FILE_WITH_STATE, state)
            if r['return']>0: return self.cm._error2(r, self.cm)

        # Finish run
        if storage_key:
            if store_in_global:
                _global[storage_key] = result
            else:
                _local[storage_key] = result

        r = self._finish_run(state, con, verbose, workdir, cur_dir, space, save, result, save_here,
                             call_repro, aggregate = True)
        if r['return']>0: return self.cm._error2(r, self.cm)

        return result


    ###########################################################################################
    # Finalize run

    def _finish_run(
                   self,
                   state = {},
                   con = False,
                   verbose = False,
                   workdir = None,
                   cur_dir = None,
                   space = '',
                   save = False,
                   result = {},
                   save_here = False,
                   call_repro = None,
                   aggregate = True,
    ):

        # Save output for reproducibility
        if self.cm.debug:
            call_repro['result'] = copy.deepcopy(result)

        # Check aggregated results
        if aggregate and '_aggregate' in result:
            _aggregate = result['_aggregate']
            state_tasks = state.setdefault('tasks', {})
            _aggregated = state_tasks.setdefault('aggregated', {})
            _aggregated = self.cm.utils.common.deep_merge(_aggregated, _aggregate, append_lists = True, prepend_lists=True)

        # Save results in the workdir directory (cache, path, etc)
        if save:
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_RESULTS, result)
            if r['return']>0: return self.cm._error2(r, self.cm)
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_STATE, state)
            if r['return']>0: return self.cm._error2(r, self.cm)

        if con and verbose and workdir != cur_dir:
            print ('')
            print (f'{space}RUN: cd {cur_dir}')

        os.chdir(cur_dir)

        # Save results in the current directory where this task was called from
        if save_here:
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_RESULTS, result)
            if r['return']>0: return self.cm._error2(r, self.cm)
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_STATE, state)
            if r['return']>0: return self.cm._error2(r, self.cm)

        return {'return':0}


    ############################################################
    def use_(
            self,
            state: dict,
            desc: dict = {},
            nested_call: int = 0,
            local = {},
            task_artifact_alias = None,
            task_artifact_uid = None,
    ):

        """
        Resolve sub_tasks

        Args:
            state (dict): cMeta state.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = state['control'].get('con', False)
        quiet = state['control'].get('quiet', False)
        verbose = state['control'].get('verbose', False)

        state_tasks = state.setdefault('tasks', {})

        _global = state_tasks.setdefault('global', {})
        _local = local

        state_use = state_tasks.setdefault('use', {})

        for sub_task_desc in desc:

            # *********************************************************************************
            # Process individual sub-task

            sub_space = '  ' * (nested_call + 1)

            task = sub_task_desc.get('task', None)
            if not task:
                err = f'the requirement in task "{task_artifact_alias}" misses "task" name or uid'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)

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
                err = f'unknown key(s) "{','.join(unknown_keys)}" in sub-task description in "{__name__}"'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)


            # Load task to check some extra params
            sub_task_category = 'task,' + self.cmeta['artifact'] if 'category' not in sub_task_desc else sub_task_desc['category']
            sub_task_command = 'run' if 'command' not in sub_task_desc else sub_task_desc['command']

            r = self.cm.access({'category': sub_task_category,
                                'command': 'load',
                                'arg1': task,
                                'load_files':['desc'],
            })
            if r['return']>0: return self.cm._error2(r, self.cm)

            sub_task_cmeta_desc = r['loaded_files']['desc'].get('data',{})
            sub_task_cmeta_ref_parts = r['artifact']['cmeta_ref_parts']

            task_alias = sub_task_cmeta_ref_parts.get('artifact_alias')
            task_uid = sub_task_cmeta_ref_parts.get('artifact_uid')

            if not task_alias and not task_uid:
                err = f'the requirement in task "{task_artifact_alias}" misses task name or uid'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)


            # Prepare input
            _with = sub_task_desc.get('with', {})

            if type(_with) is not dict:
                err = f'"with" key must be "dict" in {sub_task_desc} in "{__name__}"'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)
               
            context = {
               'global':_global, 
               'local':_local, 
               'params':_with, 
            }

            force_store_global = sub_task_desc.get('store_global')
            force_storage_key = sub_task_desc.get('storage_key')
            force_cache = sub_task_desc.get('cache')

            if not force_storage_key:
                # Check from sub task meta description to be able to update input via "use"
                if sub_task_cmeta_desc.get('storage_key'):
                    force_storage_key = sub_task_cmeta_desc['storage_key']
                elif task and task_alias:
                    force_storage_key = task_alias 

            if force_storage_key:
                r = self.cm.utils.common.expand_string(force_storage_key, context)
                if r['return']>0: return self.cm._error2(r, self.cm)
                force_storage_key = r['string']

            # Quick check (though should be checked by running task but we can skip)
            if force_store_global and force_storage_key and force_storage_key in _global:
                # REUSE DEPENDENCY RESULT FROM GLOBAL CONTEXT!!!
                if con and verbose:
                    print ('')
                    print (f'{sub_space}REUSE: load task result from _global["{force_storage_key}"]')

                continue

            # *********************************************************************************
            # Check conditions

            _if = sub_task_desc.get('if', '')
            if _if:
                r = self.cm.utils.common.expand_string(_if, context)
                if r['return']>0: return self.cm._error2(r, self.cm)

                _if = r['string']

                r = self.cm.utils.common.restricted_bool_eval(_if, {})
                if r['return']>0: return self.cm._error2(r, self.cm)

                # If condition is not met, skip sub-task
                if not r['result']:
                    continue

            # *********************************************************************************
            # Run task
            ii = copy.deepcopy(_with)

            if force_cache: ii['cache'] = force_cache
            if force_store_global: ii['store_global'] = force_store_global
            if force_storage_key: ii['storage_key'] = force_storage_key

            r = self.cm.utils.common.expand_strings_in_dict(ii, context)
            if r['return']>0: return self.cm._error2(r, self.cm)

            ii['arg1'] = task

            ii['category'] = sub_task_category
            ii['command'] = sub_task_command

            ii['con'] = con
            ii['quiet'] = quiet
            ii['verbose'] = verbose

            # Update state for tasks
            state_tasks['nested_call'] += 1

            ii['state'] = state

            # Check if must update via use dict
            if state_use:
                for use_key in state_use:
                    if force_storage_key and use_key == force_storage_key:
                        use_params = state_use[use_key]

                        ii = self.cm.utils.common.deep_merge(ii, use_params, append_lists=True)

            sub_task_result = self.cm.access(ii)

            if sub_task_result['return']>0: 
                return self.cm._error2(sub_task_result, self.cm)

            state_tasks['nested_call'] -= 1

        return {'return':0}
