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
            state: dict,                   # cMeta state
            arg1: str = None,              # Task artifact alias or UID
            tags: str = None,              # Optional tag filter
            ver: int = None,               # version

            info: bool = False,            # If True, show help about params passed to a given task module (Python API and flags)

            path: str = None,              # Working directory (change path there)
            save: bool = False,            # Force save results even if not cached
            skip: bool = False,            # If True, skip task run but keep all the rest

            cache: bool = False,           # If True, use cache to process this task
            cache_repo: str = None,        # Force to use non "local" repo
            cache_name: str = None,        # Use custom cache alias instead of automatically generated one
            cache_alias_extra: str = None, 
            cache_extra_params: dict = None,
            cache_extra_tags: str = None,

            update: bool = False,          # Rerun task and update cache entry even if exists
            clean: bool = False,           # Clean cache entry or path 

            use: dict = None,

            **params: dict,                # Parameters passed to a given task module
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

        category_uid = r['category_uid']

        task_api_path = r['api_path']
        task_api_code = r['api_code']
        
        if task_api_code is not None and info:
            r = self.cm.utils.names.restore_cmeta_obj(cmeta_ref_parts, key='artifact', fail_on_error = self.fail_on_error)
            if r['return']>0: return r
            category_str = r['obj']

            r = self.cm.utils.sys.get_api_info(task_api_code, 'run', f'task run {artifact_au}')
            if r['return'] > 0: return r

            help_text = r['api_info']

            if con:
                print (help_text)

            return {'return':0, 'help': help_text}

        ###########################################################################################
        # PRINT SELECTED TASK

        if con and verbose:
            if nested_call>0: print ('')
            print (f'{space}' + '=' * (100-len(space)))
            print (f'{space}TASK: {artifact_alias} ({artifact_path})')

        ###########################################################################################
        # PREPARE GLOBAL SCRATCHPAD

        _global = state_tasks.setdefault('global', {})

        ###########################################################################################
        # UNIFY PARAMS - most commonly convert args to keys

        uparams = params.copy()

        redirect_params = cdesc.get('redirect_params', {})
        if redirect_params:
            for k in redirect_params:
                key = redirect_params[k]

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

        if update:
            uparams['update'] = True
        if clean:
            uparams['clean'] = True

        result = {'return':0}




        ###########################################################################################
        # SAVE CALL IF SELF.DEBUG (maybe should use some other flag?)

        if self.cm.debug:
            calls = state_tasks.setdefault('calls', [])

            call_repro = {'params': state['params'].copy(), 'nested_call': nested_call}

            calls.append(call_repro)









        ###########################################################################################
        # CHECK DEPENDENCIES
        uses = cdesc.get('uses', [])

        _local = {}

        if uses:

           for sub_task_desc in uses:

               # *********************************************************************************
               # Process individual sub-task

               sub_space = '  ' * (nested_call + 1)

               name = sub_task_desc.get('name', '')
               if name and con and verbose:
                   print ('')
                   print (f'{sub_space}==> {name}')

               # *********************************************************************************
               # Check if this is another task or CMD

               task = sub_task_desc.get('task', None)
               store_in_global = sub_task_desc.get('global', False)

               r = self.cm.utils.names.parse_cmeta_name(task)
               if r['return']>0: return self.cm._error2(dep_result, self.cm)

               task_alias = r['name'].get('alias')
               task_uid = r['name'].get('uid')

               if not task_alias and not task_uid:
                   err = f'the requirement in task "{artifact_alias}" misses task name or uid'
                   return self.cm._error(err, 1, None, self.cm.fail_on_error)

               # *********************************************************************************
               # Check if self call and forbid it to avoid infinite loop

               self_run = False

               if not self_run and task_uid is not None and artifact_uid is not None and artifact_uid.strip().lower() == task_uid.strip().lower():
                   self_run = True

               if not self_run and task_alias is not None and artifact_alias is not None and artifact_alias.strip().lower() == task_alias.strip().lower():
                   self_run = True

               if self_run:
                   err = f'task {artifact_au} can\'t call itself'
                   return self.cm._error(err, 1, None, self.cm.fail_on_error)

               # *********************************************************************************
               # Check storage key and location

               key = sub_task_desc.get('key', None)
               sub_task_storage_key = None
               if key:
                   sub_task_storage_key = key
               elif task and task_alias:
                   sub_task_storage_key = task_alias 

               # If not local  result already exists in global, skip sub-task
               if store_in_global and sub_task_storage_key and sub_task_storage_key in _global:
                   if con and verbose:
                       print ('')
                       print (f'{space}REUSE: load task result from _global["{sub_task_storage_key}"]')

                   continue

               values_to_expand = {'global':state_tasks['global'], 'local':_local, 'params':uparams}

               # *********************************************************************************
               # Check conditions

               _if = sub_task_desc.get('if', '')
               if _if:
                   r = self.cm.utils.common.expand_string(_if, values_to_expand)
                   if r['return']>0: return self.cm._error2(r, self)

                   _if = r['string']

                   r = self.cm.utils.common.restricted_bool_eval(_if, {})
                   if r['return']>0: return self.cm._error2(r, self)

                   # If condition is not met, skip sub-task
                   if not r['result']:
                       continue

               # *********************************************************************************
               # Run task
               _with = sub_task_desc.get('with', {})

               if type(_with) is not dict:
                   err = f'"with" key must be "dict" in {sub_task_desc} in "{__name__}"'
                   return self.cm._error(err, 1, None, self.cm.fail_on_error)
                  
               ii = copy.deepcopy(_with)

               r = self.cm.utils.common.expand_strings_in_dict(ii, values_to_expand)
               if r['return']>0: return self.cm._error2(r, self)

               ii['arg1'] = task

               if 'category' not in ii: ii['category'] = cmeta['category']
               if 'command' not in ii: ii['command'] = 'run'

               ii['con'] = con
               ii['quiet'] = quiet
               ii['verbose'] = verbose

               # Update state for tasks
               state_tasks['nested_call'] += 1

               ii['state'] = state

               # Check if must update from sub-tasks vars
               if state_use:
                   for use_key in state_use:
                       if sub_task_storage_key and use_key == sub_task_storage_key:
                           use_params = state_use[use_key]

                           ii = self.cm.utils.common.deep_merge(ii, use_params, append_lists=True)

               sub_task_result = self.cm.access(ii)

               if sub_task_result['return']>0: 
                   return self.cm._error2(sub_task_result, self.cm)

               state_tasks['nested_call'] -= 1

               # *********************************************************************************
               # Check where to store the result

               if sub_task_storage_key:
                   if store_in_global:
                       _global[sub_task_storage_key] = sub_task_result
                   else:
                       _local[sub_task_storage_key] = sub_task_result



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







        if cache:
            # Check if compatible with cache
            if cdesc.get('no_cache', False):
                err = f'the task "{artifact_au}" does not support cache'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)

            # Need to prepare alias and tags
            cache_alias_template = f'task--{artifact_alias}{{cache_alias_extra}}'

            cache_meta = {'cref':{'category_alias': 'task',
                                  'category_uid': category_uid,
                                  'artifact_alias': artifact_alias,
                                  'artifact_uid': artifact_uid,
                                 },
                          'params':{},
                         }

            if path:
                cache_meta['path'] = path

            cache_tags = ['task', category_uid, artifact_alias, artifact_uid]

            if cache_extra_tags:
                if type(cache_extra_tags) == list:
                    cache_tags += cache_extra_tags
                else:
                    cache_tags += cache_extra_tags.split(',')

            # Check if params keys are defined in cdesc to be added to cache_tags
            cache_params_keys = cdesc.get('cache_params', [])
            if len(cache_params_keys)>0:
                for k in cache_params_keys:
                    v = uparams.get(k)
                    if v is not None:
                        cache_params[k] = v

            if task_api_code is not None:
                r = task_api_code.customize_cache_artifact(state, cache_alias_template, cache_alias_extra, cache_meta, cache_tags, cache_params, uparams)
                if r['return']>0: return r

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

            if cache_repo and not cache_name:
                ii['arg1'] = cache_repo + ':'

            r = self.cm.access(ii)
            if r['return']>0 and r['return']!=16: return r

            cache_artifacts = r.get('artifacts', [])

            if len(cache_artifacts)>1:
                # If multiple ones, remove unfinished ones
                finished_cache_artifacts = []

                for cache_artifact in cache_artifacts:
                    if 'tmp' not in cache_artifact['cmeta'].get('tags',[]):
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

                text += 'Please select'

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
                     'space':space}

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

                if 'tmp' not in cache_artifact['cmeta'].get('tags',[]) and not update and not clean:

                    ###########################################################################################
                    # RETURN CACHED RESULT

                    if con and verbose:
                        print ('')
                        print (f'{space}REUSE: load task result from {cache_path}')

                    if not path:
                        path = cache_path

                    task_result_file = os.path.join(path, self.CACHE_FILE_WITH_RESULTS)
                    r = self.cm.utils.files.read_file(task_result_file)
                    if r['return']>0: return self.cm._error2(r, self.cm)

                    result = r['data']

                    # To avoid changing working copies
                    if self.cm.debug:
                        call_repro['result'] = copy.deepcopy(result)

                    return result

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

               if cache_name is None or cache_name == '':
                   cache_uid = self.cm.utils.generate_cmeta_uid()
                   cache_alias_extra = '' if cache_alias_extra is None else '--' + cache_alias_extra
                   cache_alias = cache_alias_template.replace('{cache_alias_extra}', cache_alias_extra)
                   cache_name = f'{cache_alias}--{cache_uid},{cache_uid}'
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
                            print (f'{space}REUSE: result: {task_result_file}')

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
            print (f'{space}RUN cd {workdir}')

        os.chdir(workdir)

        if task_result_file and os.path.isfile(task_result_file) and (clean or update):
            if con and verbose:
                print ('')
                print (f'{space}RUN rm {task_result_file}')

            os.remove(task_result_file)



        ###########################################################################################
        # RUN TASK CODE IF EXISTS

        time_start2 = time.perf_counter()
        if task_api_code is not None and not skip:
            if con and verbose:
                print ('')
                print (f'{space}RUN TASK CODE: {task_api_path}')

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

        if self.cm.debug:
            call_repro['result'] = copy.deepcopy(result)

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

        if save:
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_RESULTS, result)
            if r['return']>0: return self.cm._error2(r, self.cm)
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_STATE, state)
            if r['return']>0: return self.cm._error2(r, self.cm)


        ###########################################################################################
        # RESTORE ORIGINAL DIRECTORY

        if con and verbose and workdir != cur_dir:
            print ('')
            print (f'{space}RUN: cd {cur_dir}')

        os.chdir(cur_dir)

        return result
