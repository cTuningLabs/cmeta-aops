"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import time
import copy
import fnmatch
import json
import platform
from datetime import datetime, timezone

from cmeta.category import InitCategory

# The cache attempts begun by the runs of one ctx (id(ctx) -> a stack): released by run() however a run ends
_CACHE_ATTEMPTS = {}

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
            't', 
            'ver', 
            'info', 
            'save', 
            'save_here', 
            'use', 
            'uses',
            'store_global', 
            'storage_key',
            'rem',
            'check_versions',
            'cv',
            'skip_clean_local',
        ]

        # Passed further to customization APIs ...
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
    def run(
            self,
            params,
    ):
        """
        """
        ctx = params.get('ctx')
        key = id(ctx) if ctx is not None else None
        stack = _CACHE_ATTEMPTS.setdefault(key, []) if key is not None else []
        depth = len(stack)

        try:
            return self._run(params)

        finally:
            # Whatever this call began in a cache entry and did not finish (an error return on the way,
            # an exception) is released here: the running file goes, the entry lock is dropped; the
            # entry stays tmp or failed and resumable - never locked by a process that is gone
            while len(stack) > depth:
                self._cache_release_attempt(stack.pop())
            if key is not None and not stack:
                _CACHE_ATTEMPTS.pop(key, None)

    ############################################################
    def _run(
            self,
            params,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING task api v1 run")

        ctx = params['ctx']

        inside_cli = 'cli' in ctx.get('origin',{})

        time_start = time.perf_counter()

        arg1 = params.get('arg1')
        if params.get('task_name'): 
            arg1 = params['task_name']
        tags = params.get('tags')
        if tags is None: 
            tags = params.get('t')
        ver = params.get('ver')
        info = params.get('info')
        use = params.get('use')
        uses = params.get('uses')

        save = params.get('save', False)
        save_here = params.get('save_here', False)
   
        store_global = params.get('store_global')
        storage_key = params.get('storage_key')

        skip_clean_local = params.get('skip_clean_local')

        saved_ctx_control = ctx['control'].copy()

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx.setdefault('tasks', {})
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        check_versions = params.get('check_versions')
        if check_versions is None:
            check_versions = params.get('check_versions')
        if check_versions is None:
            check_versions = ctx['tasks'].get('global', {}).get('init', {}).get('tool', {}).get('check_versions')
        if check_versions is None:
            check_versions = False

        cur_dir = os.getcwd()
        cache_path = None
        work_dir = cur_dir

        cache_sep = self.cmeta['cache_alias_separator']

        uses_categories = self.cmeta['uses_categories']

        if use is not None and type(use) != dict:
             return self.cm.error(f'type of "use" is "{type(use)}" in "{__file__}" ({__name__}) but it must be "dict"')

        if use is None:
            use = {}

        ctx_use = ctx_tasks.setdefault('use', {})
        if use:
            ctx_use = self.cm.utils.common.deep_merge(ctx_use, copy.deepcopy(use), append_lists=True)

        ###########################################################################################
        # SELECT TASK ARTIFACT

        self_category = ctx['category'].copy()

        p = {'category':uses_categories['utils'],
             'command':'select_artifact',
             'select_category':self_category,
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
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 1
            return r

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
            task_api_code.task_path = task_path
            task_api_code.cache_sep = cache_sep
            task_api_code.cdesc = cdesc
            task_api_code.artifact_alias = artifact_alias
            task_api_code.artifact_uid = artifact_uid
            task_api_code.artifact_au = artifact_au
            task_api_code.artifact_path = task_path
            task_api_code.category_alias = category_alias
            task_api_code.category_uid = category_uid

            load_api_ver_resolved = r.get('load_api_ver_resolved')
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
        # PREPARE GLOBAL CONTEXT, LOCAL VARS AND DUMMY RESULT
        # SAVE TEMPORAL PARAMS TO RESTORE AT THE END OF THE TASK !
        #   TASK MUST BE ATOMIC UNLESS LOCAL VAR IS SAVED VIA USE

        result = {'return':0}

        ctx_tasks.setdefault('global', {})

        saved_uparams = ctx_tasks.get('params')
        ctx_tasks['params'] = uparams
        saved_cparams = ctx_tasks.get('cparams')
        ctx_tasks['cparams'] = cparams

        # Local is only within a given task and sub functions but deps can't update it
        saved_local = ctx_tasks.get('local')
        if not skip_clean_local:
            ctx_tasks['local'] = {}

        # Useful to aggregate various info for the whole pipeline (such as env for complex run/compilation)
        _aggregated = ctx_tasks.setdefault('aggregated', {})

        ###########################################################################################
        # Save global if needed
        preserve_global = {}
        
        for k in cdesc.get('preserve_global_keys', []):
            if any(c in k for c in ('*', '?', '[')):
                for gk in list(ctx_tasks['global'].keys()):
                    if fnmatch.fnmatch(gk, k):
                        v = ctx_tasks['global'][gk]
                        if v is not None:
                            v = copy.deepcopy(v)
                            preserve_global[gk] = copy.deepcopy(v)
                        del (ctx_tasks['global'][gk])
            else:
                if k in ctx_tasks['global']:
                   v = ctx_tasks['global'][k]
                   if v is not None:
                       v = copy.deepcopy(v)
                       preserve_global[k] = v
                   del (ctx_tasks['global'][k])


        ###########################################################################################
        # CHECK DEPENDENCIES BEFORE INIT CALL TO TASK API (IF EXISTS)
        # Can update global/local deps

        uses_before_init = cdesc.get('uses_before_init', []).copy()
        if uses_before_init:
            r = self.use_(
                  ctx, 
                  desc = uses_before_init, 
#                  local = ctx_tasks['local'],
                  local = None,
                  task_artifact_alias = artifact_alias, 
                  task_artifact_uid = artifact_uid,
                  task_artifact_path = task_path,
                  task_api_code = task_api_code,
                  uparams = uparams,
                  self_desc = cdesc,
            )
            if self.cm.catch_error(r): return r

        ###########################################################################################
        # RUN INIT FROM TASK CODE IF EXISTS
        # Can check and update params 

        task_extra_uses = []
        if task_api_code is not None and hasattr(task_api_code, 'init') and callable(getattr(task_api_code, 'init')):
            r = task_api_code.init(ctx, ctx_tasks['params'])
            if self.cm.catch_error(r): return r

            if r.get('skip_run', False):
                # Early exit !!! local and params may have changed in init ...
#                ctx['tasks']['params'] = saved_uparams if saved_uparams else {}
#                ctx['tasks']['local'] = saved_local if saved_local else {}

                # Do not aggregate - already done!
                r = self._finish_run(
                        ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here, call_repro = None, 
                        aggregate = False, 
                        saved_uparams = saved_uparams, 
                        saved_cparams = saved_cparams, 
                        saved_local = saved_local,
                        saved_ctx_control = saved_ctx_control,
                        preserve_global = preserve_global,
                )
                if self.cm.catch_error(r): return r
    
                # !!! Exit from this function
                return r

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

            call_repro = {'params': ctx_tasks['params'].copy(), 'nested_call': nested_call}

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

        # Since we use dots to expand strings as dicts, we have to replace . with _
        storage_key = storage_key.replace('.', '-')



        ###########################################################################################
        # UPDATE PARAMS FROM USE BASED ON STORAGE KEY ...

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
        # May do some basic tasks and stop

        if task_api_code is not None and hasattr(task_api_code, 'check_params') and callable(getattr(task_api_code, 'check_params')):
            r = task_api_code.check_params(ctx, ctx_tasks['params'], cparams)
            if self.cm.catch_error(r): return r

            if r.get('stop', False):
                # It's usually done when code should not continue - for example to print versions, help, etc

                # Do not aggregate further - already done!
                rr = self._finish_run(
                        ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here, call_repro,
                        aggregate = False,
                        saved_uparams = saved_uparams,
                        saved_cparams = saved_cparams,
                        saved_local = saved_local,
                        saved_ctx_control = saved_ctx_control,
                        preserve_global = preserve_global,
                )
                if self.cm.catch_error(rr): return rr

                # Hand what check_params produced (versions, status, ...) to the caller
                r.pop('stop', None)

                # !!! Exit from this function
                return r

        ###########################################################################################
        # PRINT FINAL TASK PARAMS

        _params = copy.deepcopy(ctx_tasks['params'])
        if _params and con and verbose:
            print ('')
            print (f'{space}Parameters for task "{artifact_au}":')

            def print_recursive(obj, indent=0):
                space = '  ' * indent + '  '

                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, (dict, list, tuple, set)):
                            print(f"{space}* {k}:")
                            print_recursive(v, indent + 1)
                        else:
                            print(f"{space}* {k} = {v}")

                elif isinstance(obj, (list, tuple, set)):
                    for item in obj:
                        if isinstance(item, (dict, list, tuple, set)):
                            print(f"{space}-")
                            print_recursive(item, indent + 1)
                        else:
                            print(f"{space}- {item}")

                else:
                    print(f"{space}{obj}")

            print_recursive(_params, nested_call)

#            for k in _params:
#                v = _params[k]
#                if type(v) == list:
#                    print(f'{space}  * {k}:')
#                    for kk in v:
#                        print(f'{space}      - {kk}')
#                elif type(v) == dict:
#                    print(f'{space}  * {k}:')
#                    for kk in v:
#                        vv = v[kk]
#                        if type(vv) == list:
#                            print(f'{space}  * {kk}:')
#                            for kkk in vv:
#                                print(f'{space}      - {kkk}')
#                        else:
#                            print(f'{space}    * {kk} = {vv}')
#                else:
#                    print(f'{space}  * {k} = {v}')


        ###########################################################################################
        # If not local and result already exists in global, reuse result

        if store_global and storage_key and storage_key in ctx_tasks['global']:

            # REUSE DEPENDENCY RESULT FROM GLOBAL CONTEXT!!!
            if con and verbose:
                print ('')
                print (f'{space}REUSE: load task result from ctx["tasks"]["global"]["{storage_key}"]')

            result = copy.deepcopy(ctx_tasks['global'][storage_key])

            # Dynamic update to result (even if cached)
            if task_api_code is not None and hasattr(task_api_code, 'finish_dynamic_result') and callable(getattr(task_api_code, 'finish_dynamic_result')):
                ctx['control'] = saved_ctx_control.copy()
                r = task_api_code.finish_dynamic_result(ctx, result, _params)
                if self.cm.catch_error(r): return r
                if 'result' in r: result = r['result']

            # Do not aggregate - already done!
            r = self._finish_run(
                    ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here, call_repro, 
                    aggregate = False, 
                    saved_uparams = saved_uparams, 
                    saved_cparams = saved_cparams,
                    saved_local = saved_local,
                    saved_ctx_control = saved_ctx_control,
                    preserve_global = preserve_global,
            )
            if self.cm.catch_error(r): return r
            
            # !!! Exit from this function
            return result

        ###########################################################################################
        # EXPAND ALL CONTROL PARAMS

        path = cparams.get('path')
        skip = cparams.get('skip', False)

        cache = cparams.get('cache')

        cache_repo = cparams.get('cache_repo')
        # Check if was forced for the whole run: --use.init.default_cache_repo=<repo> or config::task (task init)
        x_cache_repo = ctx_tasks.get('global', {}).get('init', {}).get('default_cache_repo')
        if x_cache_repo:
            cache_repo = x_cache_repo

        cache_name = cparams.get('cache_name')
        if not cache_name:
            cache_name = cdesc.get('cache_name')
            if cache_name:
                r = self.cm.utils.common.expand_string(cache_name, ctx_tasks)
                if self.cm.catch_error(r): return r
                cache_name = r['string']

        cache_extra_alias = cparams.get('cache_extra_alias')
        if not cache_extra_alias:
            cache_extra_alias = cdesc.get('cache_extra_alias')
            if cache_extra_alias:
                r = self.cm.utils.common.expand_string(cache_extra_alias, ctx_tasks)
                if self.cm.catch_error(r): return r
                cache_extra_alias = r['string']


        cache_extra_params = copy.deepcopy(cdesc.get('cache_extra_params', {}))
        if cache_extra_params:
            r = self.cm.utils.common.expand_strings_in_dict(cache_extra_params, ctx_tasks)
            if self.cm.catch_error(r): return r
        _cache_extra_params = cparams.get('cache_extra_params')
        if _cache_extra_params:
            self.cm.utils.common.deep_merge(cache_extra_params, _cache_extra_params, append_lists=True)


        cache_extra_tags = copy.deepcopy(cdesc.get('cache_extra_tags', []))
        if cache_extra_tags:
            r = self.cm.utils.common.expand_strings_in_list(cache_extra_tags, ctx_tasks)
            if self.cm.catch_error(r): return r
        _cache_extra_tags = cparams.get('cache_extra_tags')
        if _cache_extra_tags:
            if type(_cache_extra_tags)==str:
                _cache_extra_tags = _cache_extra_tags.split(',')
            for x in _cache_extra_tags:
                if x not in cache_extra_tags:
                    cache_extra_tags.append(x)


        update = cparams.get('update', False)
        clean = cparams.get('clean', False)
        new = cparams.get('new', False)

        ###########################################################################################
        # CHECK DEPENDENCIES
        _uses = cdesc.get('uses', []).copy()

        if task_extra_uses:
            _uses += task_extra_uses

        if uses:
            _uses += uses

        # Set up local context
        if _uses:
            r = self.use_(
                    ctx, 
                    desc = _uses, 
#                    local = ctx_tasks['local'],
                    local = None,
                    task_artifact_alias = artifact_alias, 
                    task_artifact_uid = artifact_uid,
                    task_artifact_path = task_path,
                    task_api_code = task_api_code,
                    uparams = uparams,
                    self_desc = cdesc,
            )
            if self.cm.catch_error(r): return r

        ###########################################################################################
        # PROCESS CACHE

        task_result_file = None
        update_cache = False
        attempt = None          # this process's attempt in a cache entry (the lookup sets it)

        cache_params = {}

        cache_features = cdesc.get('cache_features', {})
        if cache_features:
            r = self.cm.utils.common.expand_strings_in_dict(cache_features, ctx_tasks)
            if self.cm.catch_error(r): return r

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
            cache_meta = {
              'cref':{
                'category_alias': 'task',
                'category_uid': category_uid,
                'artifact_alias': artifact_alias,
                'artifact_uid': artifact_uid,
              },
              'params':{},
            }

            cache_tags = [
              'task', 
              category_uid, 
              artifact_alias, 
              artifact_uid,
            ]

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
                # Check if need to expand
                v = None

                if k.startswith('{{') and k.endswith('}}'):
                    k = k[2:-2]

                    r = self.cm.utils.common.expand_string(k, ctx_tasks)
                    if self.cm.catch_error(r): return r
                    v = r['string']

                kk = k[1:] if k.startswith('@') else k

                if v is None:
                    v = uparams.get(kk)
    
                if v is not None:
                    cache_params[k] = v

            if task_api_code is not None:
                r = task_api_code.customize_cache_artifact(
                      ctx, 
                      cache_alias_template, 
                      cache_extra_alias, 
                      cache_meta, 
                      cache_tags, 
                      cache_params, 
                      uparams,
                      cache_features = cache_features,
                )
                if self.cm.catch_error(r): return r

                if cache_name is None and 'cache_name' in r: 
                    cache_name = r['cache_name']
                if 'cache_extra_alias' in r: 
                    cache_extra_alias = r['cache_extra_alias']
                if 'cache_alias_template' in r: 
                    cache_alias_template = r['cache_alias_template']

            # Check if exists
            ii = {'category': uses_categories['cache'],
                  'command': 'find',
                 }

            cache_meta['params'] = self.cm.utils.common.deep_merge(cache_meta['params'], cache_params, append_lists=False)

            if cache_name:
                cache_name = cache_name.lower() # Force lower to avoid various issues ...
            else:
                ii['tags'] = cache_tags
                ii['match'] = cache_meta
                ii['match_empty_version'] = True

            if cache_repo and not cache_name:
                ii['arg1'] = cache_repo + ':'

            # The query as the find makes it: with the fuzzy @ keys (versions with conditions)
            find_query = copy.deepcopy(ii)

            # Just for printing later if needed
            cache_meta_params_copy = cache_meta['params'].copy()

            # Clean params in cache_meta that that start from @ -
            # these are fuzzy versions with conditions
            # that should be resolved to the normal key

            for key in list(cache_meta['params'].keys()):
                if key.startswith('@'):
                    del(cache_meta['params'][key])

            for key in list(cache_params.keys()):
                if key.startswith('@'):
                    del(cache_params[key])

            # What this request asked for: recorded in a new entry, and the rule by which a resumable
            # entry is this request's attempt and no other's. Taken BEFORE the fuzzy keys were dropped, under
            # their plain names: a setup asks for its version as `@version`, and without it a failed
            # `--version=9.9.9` entry recorded {name} only and was resumed by the request WITHOUT a version
            # (the torchvision incident again - seen with jq on Windows, 2026-10-09 17:41).
            request_params = {}
            for key, value in copy.deepcopy(cache_meta_params_copy).items():
                request_params[key[1:] if key.startswith('@') else key] = value

            def create_entry():
                """A new entry for this request, tagged tmp, with the request recorded."""
                name = cache_name
                alias = None
                uid = None
                if not name:
                    uid = self.cm.utils.generate_cmeta_uid()
                    extra = '' if cache_extra_alias is None else cache_sep + cache_extra_alias
                    alias = cache_alias_template.replace('{cache_extra_alias}', extra) + cache_sep + uid
                    name = f'{alias},{uid}'.lower()
                    if cache_repo:
                        name = cache_repo + ':' + name

                meta = copy.deepcopy(cache_meta)
                meta['request_params'] = copy.deepcopy(request_params)

                r = self.cm.access({'category':uses_categories['cache'],
                                    'command':'create',
                                    'arg1':name,
                                    'tags':cache_tags + ['tmp'],
                                    'meta':meta
                    })
                if self.cm.catch_error(r, fail16=True):
                    r['return'] = 1
                    return r

                made_meta = r['meta']
                if uid is None:
                    uid = str(made_meta.get('artifact', '')).split(',')[-1].strip()
                if alias is None:
                    alias = os.path.basename(r['path'])

                return {'return':0, 'path': r['path'], 'meta': made_meta, 'name': name,
                        'ref_parts': {'artifact_alias': alias, 'artifact_uid': uid, 'artifact_alias_lowercase': alias.lower()}}

            # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            # Search in cache, classify, choose - under the creation lock of the cache repository
            r = self._cache_lookup(ctx, uses_categories, find_query, new, cache_repo, cache_name, request_params, path,
                                   task_api_code, uparams, artifact_alias, create_entry, con, verbose, space)
            if r['return']>0: return r

            cache_artifacts = r['ok']
            tmp_cache_artifacts = r['resumable']
            attempt = r['attempt']

            ###########################################################################################
            # Check if has cache_features
            if cache_features and len(cache_artifacts)>0:
                # First try to find if there are matching ones
                matched_cache_artifacts = []
                unmatched_cache_artifacts = []

                for cache_artifact in cache_artifacts:
                    x = cache_artifact['cmeta'].get('params', {})

                    if self.cm.utils.common.matches_query(x, 
                                                          cache_features, 
                                                          match_version_func = self.cm.repos.match_version_func, 
                                                          match_empty_version = True):
                        matched_cache_artifacts.append(cache_artifact)
                    else:
                        unmatched_cache_artifacts.append(cache_artifact)

                # If have matched artifacts, good - can keep going ...
                if matched_cache_artifacts:
                    cache_artifacts = matched_cache_artifacts

                elif unmatched_cache_artifacts:
                    text = ''

                    if verbose:
                        text += '\n'

                    text += f'{space}WARNING: cache entries found for task "{artifact_alias}"'

                    if cache_meta_params_copy:
                        text += ' with parameters:\n'
                        for p in sorted(cache_meta_params_copy):
                            v = str(cache_meta_params_copy[p])
                            text += f'{space}      * params.{p} = {v}\n'

                    text += f'{space}'

                    if cache_meta_params_copy:
                        text += 'and '

                    text += 'with features:\n'
                    for p in sorted(cache_features):
                        v = str(cache_features[p])
                        text += f'{space}      * params.{p} = {v}\n'

                    if con:
                        print (text)

                    x = f'{space}However, only one cache entry should exist with such parameters and different features.'
                    if quiet or update:
                        print (f'{x} Updating ...')
                    else:
                        r = self._ask(f'{space}{x} Update (Y/n)? ', '-q (--quiet) or --update to update it without asking')
                        if r['return']>0: return r
                        y = r['answer'].strip().lower()

                        if y in ['n', 'no']:
                            return self.cm.error(text + ' Cache update was cancelled by user')

                    update = True
                    cache_artifacts = unmatched_cache_artifacts

            ###########################################################################################
            # Merge back cache_features to cache_params

            if cache_features:
                for key in list(cache_features.keys()):
                    if key.startswith('@'):
                        del(cache_features[key])

                cache_meta['params'] = self.cm.utils.common.deep_merge(cache_meta['params'], cache_features, append_lists=False)
                cache_params = self.cm.utils.common.deep_merge(cache_params, cache_features, append_lists=False)

            ###########################################################################################
            if len(cache_artifacts)>1:

                text = ''

                if verbose:
                    text += '\n'

                text += f'{space}WARNING: More than 1 cache entry found for task "{artifact_alias}"'

                if cache_meta_params_copy:
                    text += ' with parameters:\n'
                    for p in sorted(cache_meta_params_copy):
                        v = str(cache_meta_params_copy[p])
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
                     'con': con,
                     'quiet': quiet,
                     'space': space,
                     'allow_skip': True,
                }

                if 'sort_keys' in cdesc:
                    p['sort_keys'] = cdesc['sort_keys']
                else:
                    p['sort_keys'] = [
                       '@cmeta.params.version-',
                       'cmeta.params.priority',
                       'cmeta.params.path',
                    ]

                r = self.cm.access(p)
                if self.cm.catch_error(r, fail16 = True): 
                    r['return'] = 1
                    return r

                if r.get('skipped', False):
                    cache_artifacts = []
                else:
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
                    ###########################################################################################
                    ###########################################################################################
                    # RETURN CACHED RESULT IF ENTRY IS VALID!!!!!!

                    cache_artifact_params = cache_artifact['cmeta'].get('params',{})
                    invalidate = False
                    delete = False
                    problem = False

                    x_cache_artifact_alias = cache_artifact['cmeta_ref_parts'].get('artifact_alias')
                    x_cache_artifact_uid = cache_artifact['cmeta_ref_parts']['artifact_uid']

                    # Check if check_cache_path (for example from git that may be deleted)
                    ca_check_path = cache_artifact_params.get('git_path')

                    if ca_check_path and not os.path.isdir(ca_check_path):
                        invalidate = True

                    if not invalidate:
                        # Check if tool path and version is correct
                        ca_check_path = cache_artifact_params.get('tool_path')

                        if check_versions and ca_check_path:
                            if (os.path.isfile(ca_check_path) or os.path.isdir(ca_check_path)):
                                x_version = cache_artifact['cmeta'].get('params', {}).get('version')
                                x_name = cache_artifact['cmeta'].get('params', {}).get('name')
                                skip_cache_version_check = cache_artifact['cmeta'].get('skip_cache_version_check', True)
                                if not skip_cache_version_check and x_version and x_name:
                                    x_cref = cache_artifact['cmeta'].get('cref')

                                    if x_cref.get('artifact_uid') in ['a2f9b61079ce4333'] and \
                                       x_cref.get('category_uid') in ['c36be4b9314a45e0']:

                                        if con and verbose:
                                            print ('')
                                            print (f'{space}CHECK: checking version for {x_name} ...')

                                        _con = con
                                        ii = {
                                              'category': self_category,      # task
                                              'command': 'run',
                                              'arg1': x_cref['artifact_uid'], # setup
                                              'name': x_name,
                                              'cache': False,
                                              'skip_detect': False, # Needed for libs and tools that force skip detect
                                              'skip_install': True,
                                              'skip_build': True,
                                              'version_check': True,
                                              'tool_path': ca_check_path,
                                              'timeout': 200,
                                              'quiet': quiet,
                                              'con': False,
                                              'verbose': False,
                                        }

                                        x_with = cache_artifact['cmeta'].get('params',{}).get('with',{})
                                        if x_with:
                                            ii['with'] = x_with

                                        x_use = cache_artifact['cmeta'].get('params',{}).get('use',{})
                                        if x_use:
                                            ii['use'] = x_use

                                        ii['ctx'] = ctx

                                        r = self.cm.access(ii)
                                        # FGG: Note that if something goes wrong with detection of the version,
                                        # the command will fail, but we should not fail and quit here but continue working ...
                                        # I also added error 32 if we didn't detect tool or there was some fail.
                                        # We may want to improve this functionality based on convenience...

                                        ctx['control']['con'] = _con

                                        ret = r['return']

    #                                    if self.cm.catch_error(r): return r

                                        if ret >0 :
                                            if con:
                                                print ('')
                                                print (f'{space}WARNING: There is a problem running the tool in cache entry {x_cache_artifact_alias} to check version:')
                                                print ('')
                                                err = r['error']
                                                print (f'{space}  {err}')
                                                print ('')
                                                if quiet:
                                                    # A quiet run asks nothing: the default (the entry is kept)
                                                    x = ''
                                                else:
                                                    r = self._ask(f'{space}Would you like to delete this potentially oudated cache entry (y/N): ',
                                                                  '-q (--quiet) to keep it without asking')
                                                    if r['return']>0: return r
                                                    x = r['answer']
                                                print ('')

                                                if x.strip().lower() in ['y', 'yes']:
                                                    delete = True

                                            # If console, we ask to delete, otherwise we keep running ...

                                        else:
                                            x_detected_version = r['version']

                                            if x_detected_version != x_version:
                                                problem = True

                                                if con:
                                                    print ('')
                                                    print (f'WARNING: The version in cache entry {x_cache_artifact_alias} has changed:')
                                                    print ('')
                                                    print (f'  Cache version: {x_version}')
                                                    print (f'  Detected real version: {x_detected_version}')
                                                    print ('')
                                                    if quiet:
                                                        # A quiet run asks nothing: the default, as for a missing path below
                                                        print ('Quietly deleting this potentially outdated cache entry ...')
                                                        x = 'Y'
                                                    else:
                                                        r = self._ask('Would you like to delete this potentially oudated cache entry (Y/n): ',
                                                                      '-q (--quiet) to delete it without asking')
                                                        if r['return']>0: return r
                                                        x = r['answer']
                                                    print ('')

                                                    if x.strip().lower() in ['', 'y', 'yes']:
                                                        delete = True

                            elif not (os.path.isfile(ca_check_path) or os.path.isdir(ca_check_path)):
                                invalidate = True

                    if invalidate:
                        if con:
                            print ('')
                            print (f'WARNING: Cache entry "{x_cache_artifact_alias}" exists but related path is missing:')
                            print ('')
                            print (f'  {ca_check_path}')
                            print ('')
                            if quiet:
                                print ('Quietly deleting this potentially outdated cache entry ...')
                                print ('')
                                x = 'Y'
                            else:
                                r = self._ask('Would you like to delete this potentially outdated cache entry (Y/n): ',
                                              '-q (--quiet) to delete it without asking')
                                if r['return']>0: return r
                                x = r['answer']
                                print ('')

                            if x.strip().lower() in ['', 'y', 'yes']:
                                delete = True

                    if delete:
                        ii = {'category': uses_categories['cache'],
                              'command': 'delete',
                              # default cache rm is only in local while we need to allow any repo here
                              'arg1': '*:' + x_cache_artifact_uid,
                              'force': True
                        }

                        if con: 
                            ii['con'] = True

                        r = self.cm.access(ii)
                        if self.cm.catch_error(r, fail16=True): 
                            r['return'] = 1
                            return r

                    if problem:
                        return self.cm.error('selected outdated cache entry was deleted - please restart the task')

                    if con and verbose:
                        print ('')
                        print (f'{space}REUSE: load task result from cache entry "{cache_path}"')

                    if not path:
                        path = cache_path

                    task_result_file = os.path.join(path, self.CACHE_FILE_WITH_RESULTS)
                    r = self.cm.utils.files.read_file(task_result_file)
                    if self.cm.catch_error(r): return r

                    # If not found but cache exists, often the path is outside cache and was deleted - need to recreate!
                    # similar to turning --update and or --clean option
                    if r['return'] == 0:
                        result = r['data']

                        # Dynamic update to result (even if cached)
                        if task_api_code is not None and hasattr(task_api_code, 'finish_dynamic_result') and callable(getattr(task_api_code, 'finish_dynamic_result')):
                            ctx['control'] = saved_ctx_control.copy()
                            r = task_api_code.finish_dynamic_result(ctx, result, _params)
                            if self.cm.catch_error(r): return r
                            if 'result' in r: result = r['result']

                        if storage_key:
                            if store_global:
                                ctx_tasks['global'][storage_key] = result
                            else:
                                ctx_tasks['local'][storage_key] = result

                        r = self._finish_run(
                                ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here,
                                call_repro, aggregate = True,
                                saved_uparams = saved_uparams, 
                                saved_cparams = saved_cparams,
                                saved_local = saved_local,
                                saved_ctx_control = saved_ctx_control,
                                preserve_global = preserve_global,
                        )
                        if self.cm.catch_error(r): return r

                        # !!! Exit from this function
                        return result



                ###########\####################################################################################
                cache_cmeta_ref_parts = cache_artifact['cmeta_ref_parts']
                cache_alias = cache_cmeta_ref_parts['artifact_alias']
                cache_uid = cache_cmeta_ref_parts['artifact_uid']
                cache_name = f'{cache_alias},{cache_uid}'.lower()
                if cache_repo:
                    cache_name = cache_repo + ':' + cache_name
                update_cache = True


            ###########################################################################################
            if len(cache_artifacts) == 0:
               # The lookup resumed or created the entry of this run and locked it for this process
               update_cache = True

               if attempt is None:
                   return self.cm.error('Inconsistency in task cache handling: no cache entry was chosen for this run')

               cache_path = attempt['path']
               cache_meta = attempt['meta']
               cache_cmeta_ref_parts = attempt['ref_parts']
               cache_alias = cache_cmeta_ref_parts['artifact_alias']
               cache_uid = cache_cmeta_ref_parts['artifact_uid']
               cache_name = f'{cache_alias},{cache_uid}'.lower()
               if cache_repo:
                   cache_name = cache_repo + ':' + cache_name

            if cache_name is None:
                return self.cm.error('Inconsistency in task cache handling since cache_name is None')
            if cache_path is None:
                return self.cm.error('Inconsistency in task cache handling since cache_path is None')

            if attempt is None and update_cache:
                # A usable entry rebuilt with --update or --clean (the user's explicit overwrite): this process's
                # attempt in it, like a resumed one - the entry lock and the running file
                r = self._cache_begin_attempt(ctx, {'path': cache_path, 'cmeta': cache_meta, 'cmeta_ref_parts': cache_cmeta_ref_parts},
                                              'ok', request_params, artifact_alias)
                if r['return']>0:
                    if r.get('busy'):
                        return self.cm.error(f'the cache entry "{cache_name}" is being rebuilt by another process - try again when it is done')
                    return r
                attempt = r['attempt']

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
            if os.path.isfile(work_dir):
                return self.cm.error(f'working dir "{work_dir}" is a file while it should be a directory')
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
        # CHECK DEPENDENCIES AFTER CACHE INIT AND BEFORE POSSIBLE PYTHON RUN

        uses2 = cdesc.get('uses2', []).copy()
        if uses2:
            r = self.use_(
                  ctx, 
                  desc = uses2, 
# Careful: reusing local - no complex sub-tasks ...
# Usually just for cmd ...
                  local = ctx_tasks['local'],
#                  local = None,
                  task_artifact_alias = artifact_alias, 
                  task_artifact_uid = artifact_uid,
                  task_artifact_path = task_path,
                  task_api_code = task_api_code,
                  uparams = uparams,
                  self_desc = cdesc,
            )
            if self.cm.catch_error(r): return r


        ###########################################################################################
        # RUN TASK CODE IF EXISTS

        time_start2 = time.perf_counter()
        if not skip and task_api_code is not None \
            and hasattr(task_api_code, 'run') and callable(getattr(task_api_code, 'run')):
            if con and verbose:
                print ('')
                print (f'{space}RUN TASK CODE: {task_api_path}')

            save_ctx_tasks_control = ctx['tasks'].get('run_control', {})

            ctx_tasks_control = ctx['tasks']['run_control'] = {}

            if update:
                ctx_tasks_control['update'] = True
            if clean:
                ctx_tasks_control['clean'] = True
            if new:
                ctx_tasks_control['new'] = True

            ctx_tasks_control['cache'] = cache
            ctx_tasks_control['cur_dir'] = cur_dir
            ctx_tasks_control['work_dir'] = work_dir
            ctx_tasks_control['task_path'] = task_path
            ctx_tasks_control['task_api_path'] = task_api_path
            ctx_tasks_control['task_desc'] = cdesc

            if cache_params:
                ctx_tasks_control['cache_params'] = cache_params

            if attempt is not None and attempt.get('state') != 'new':
                # A task that resumes an entry (crashed, failed, broken, or ok with --update / --clean) can check
                # what the entry holds (its content is the task's business); a new entry has nothing to check
                ctx_tasks_control['cache_resumed'] = {'state': attempt['state'], 'params': copy.deepcopy(attempt.get('meta', {}).get('params', {}))}

            #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            # Run custom code!
            result = task_api_code.run(ctx, **uparams)
            #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

            # Restore control
            ctx['tasks']['run_control'] = save_ctx_tasks_control
 
            # Check if success or fail
            if result['return']>0:
                if cache:
                    # The failed attempt ends: the result (the error) written, the entry tagged `failed`
                    # (resumable by the same request, never served as a result), the lock released
                    r = self._cache_finish_attempt(attempt, ctx, uses_categories, cache_name, cache_params, result,
                                                   failed = True, con = con, verbose = verbose, space = space)
                    if self.cm.catch_error(r): return r

                if save or save_here:
                    r = self._finish_run(
                            ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here,
                            call_repro, aggregate = True,
                            saved_uparams = saved_uparams,
                            saved_cparams = saved_cparams,
                            saved_local = saved_local,
                            saved_ctx_control = saved_ctx_control,
                            preserve_global = preserve_global,
                    )
                    if self.cm.catch_error(r): return r

                # Back to the directory of the caller (the success path does it in _finish_run): a process
                # left inside the entry would keep its folder from being removed on Windows
                if work_dir != cur_dir:
                    try:
                        os.chdir(cur_dir)
                    except OSError:
                        pass

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
        # UPDATE CACHE: this process's attempt ends with its result and ctx written first, then the entry
        # (its params replaced by this request's plus what the task added, the request recorded, the
        # tmp/failed tags removed), then the running file and the entry lock go

        if cache:
            if attempt is not None:
                r = self._cache_finish_attempt(attempt, ctx, uses_categories, cache_name, cache_params, result,
                                               failed = False, con = con, verbose = verbose, space = space)
                if self.cm.catch_error(r): return r

            else:
                # No attempt of this process (the task was skipped: a usable result in --path): the files as before
                r = self.cm.utils.files.safe_write_file(self.CACHE_FILE_WITH_RESULTS, result)
                if self.cm.catch_error(r): return r
                r = self.cm.utils.files.safe_write_file(self.CACHE_FILE_WITH_CTX, ctx, safe_dump = True)
                if self.cm.catch_error(r): return r

        # Dynamic update to result (even if cached)
        if task_api_code is not None and hasattr(task_api_code, 'finish_dynamic_result') and callable(getattr(task_api_code, 'finish_dynamic_result')):
            r = task_api_code.finish_dynamic_result(ctx, result, _params)
            if self.cm.catch_error(r): return r
            if 'result' in r: result = r['result']

        # Finish run
        if storage_key and store_global:
            if store_global:
                ctx_tasks['global'][storage_key] = result
            else:
                ctx_tasks['local'][storage_key] = result

        r = self._finish_run(
                ctx, con, verbose, work_dir, cur_dir, space, save, result, save_here,
                call_repro, aggregate = True,
                saved_uparams = saved_uparams, 
                saved_cparams = saved_cparams,
                saved_local = saved_local,
                saved_ctx_control = saved_ctx_control,
                preserve_global = preserve_global,
        )
        if self.cm.catch_error(r): return r

        # Need to duplicate if forced save to local otherwise local will be restored here
        if storage_key and not store_global:
            ctx_tasks['local'][storage_key] = result

            if result.get('add_to_local'):
                self.cm.utils.common.deep_merge(ctx_tasks['local'], result['add_to_local'], append_lists=False)

        # !!! Exit from this function
        return result


    ###########################################################################################
    # The cache entry of a run (docs/cmeta-aops/task-engine.md, "The cache entry of a run"): the lookup
    # under the creation lock of the cache repository, the states of the entries (the engine's cache
    # category classifies them: ok, running, crashed, failed, broken), the resume rule (an attempt is
    # resumed only by the request it was made for), the entry lock and the running file of an attempt,
    # and the end of an attempt - the result first, then the tags, so that an entry is never "finished"
    # without its result.

    @staticmethod
    def _ask(question, how):
        """A question of the task engine (ask of the task API): nobody to answer = an error that names `how`, no traceback."""
        from task_c36be4b9314a45e0.api.ctask import ask
        return ask(question, how)

    CACHE_WAIT_TIMEOUT_ENV = 'CMETA_CACHE_WAIT_TIMEOUT'   # how long a request waits for the attempt of another process
    CACHE_WAIT_TIMEOUT = 86400
    CACHE_FILE_RUNNING = 'cmeta-task-running.json'        # RUNNING_FILE of the engine's cache category: who runs the attempt

    def _cache_repo_folder(self, cache_repo):
        """The folder of the cache category in the repository where the entries of this run live."""
        ref = {'category_alias': 'repo', 'category_uid': self.cm.cfg['category_repo_uid']}
        if cache_repo:
            r = self.cm.utils.names.parse_cmeta_obj(cache_repo, key = 'artifact', fail_on_error = False)
            if r['return']>0: return r
            parts = r['obj_parts']
            if parts.get('artifact_uid'): ref['artifact_uid'] = parts['artifact_uid']
            if parts.get('artifact_alias'): ref['artifact_alias'] = parts['artifact_alias']
        else:
            ref['artifact_alias'] = 'local'

        r = self.cm.repos.find(ref)
        if r['return']>0: return r

        artifacts = r.get('artifacts', [])
        if len(artifacts) != 1:
            return self.cm.error(f'cannot find the repository "{cache_repo or "local"}" of the cache entries ({len(artifacts)} found)')

        return {'return':0, 'folder': os.path.join(artifacts[0]['full_path'], 'cache')}

    @staticmethod
    def _cache_normalized(x):
        """Parameters as comparable text: every leaf a string (the CLI gives strings, the API may give numbers)."""
        if isinstance(x, dict):
            return {str(k): Category._cache_normalized(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [Category._cache_normalized(v) for v in x]
        return str(x)

    def _cache_same_request(self, entry, request_params, request_path, cache_name):
        """
        True when `entry` (resumable) is the attempt of THIS request: the same path, and the parameters the
        request was made with (`request_params`, recorded in the entry at its creation) equal to this
        request's. An entry made before that record existed is matched as before: by the subset rule on
        its parameters. A forced cache name is the identity by itself.
        """
        if cache_name:
            return True

        cmeta = entry.get('cmeta', {})

        if (cmeta.get('path') or None) != (request_path or None):
            return False

        recorded = cmeta.get('request_params')
        if recorded is not None:
            return self._cache_normalized(recorded) == self._cache_normalized(request_params)

        return self.cm.utils.common.matches_query(cmeta.get('params', {}), request_params,
                                                  match_version_func = self.cm.repos.match_version_func,
                                                  match_empty_version = True)

    def _cache_begin_attempt(self, ctx, entry, state, request_params, artifact_alias):
        """
        Take the lock of the entry's folder for an attempt of this process (zero wait: a busy lock means
        another process works there and the caller waits for it instead), write the running file (who,
        since when, for which request), and register the attempt so that it is released however the run
        ends. Returns {'return': 0, 'attempt': ...}, or 'busy': True when the lock is held.
        """
        files = self.cm.utils.files

        path = entry['path']
        pid = os.getpid()
        host = platform.node() or 'unknown-host'
        started = datetime.now(timezone.utc).isoformat()
        note = f'task run {artifact_alias} by pid {pid} on {host} since {started}'

        lock = files.PathLock(files._get_lockfile_path(os.path.normpath(path)), logger = self.logger)
        try:
            lock.acquire(timeout = 0, note = note)
        except TimeoutError:
            return {'return':1, 'busy': True, 'error': f'the cache entry {path} is taken by another process'}
        except Exception as e:
            return self.cm.error(f'cannot lock the cache entry {path}: {e}')

        attempt = {
            'path': path,
            'meta': entry.get('cmeta', {}),
            'ref_parts': entry.get('cmeta_ref_parts', {}),
            'lock': lock,
            'state': state,
            'request_params': copy.deepcopy(request_params),
            'running_file': os.path.join(path, self.CACHE_FILE_RUNNING),
            'done': False,
        }

        if not os.path.isdir(path):
            os.makedirs(path, exist_ok = True)

        r = files.safe_write_file(attempt['running_file'], {'pid': pid, 'host': host, 'started': started,
                                                            'task': artifact_alias, 'params': request_params,
                                                            'resumes': state})
        if r['return']>0:
            lock.release()
            return r

        _CACHE_ATTEMPTS.setdefault(id(ctx), []).append(attempt)

        return {'return':0, 'attempt': attempt}

    def _cache_release_attempt(self, attempt):
        """The running file goes and the entry lock is dropped (idempotent; the entry's tags are not touched)."""
        if attempt is None or attempt.get('done'):
            return

        attempt['done'] = True

        try:
            if os.path.isfile(attempt['running_file']):
                os.remove(attempt['running_file'])
        except OSError:
            pass

        try:
            attempt['lock'].release()
        except Exception:
            pass

    def _cache_wait_for(self, entry, info, artifact_alias, con, space):
        """Wait for the attempt of another process in `entry` (up to CMETA_CACHE_WAIT_TIMEOUT seconds, 86400)."""
        files = self.cm.utils.files

        path = entry['path']
        alias = entry.get('cmeta_ref_parts', {}).get('artifact_alias', os.path.basename(path))
        holder = (info or {}).get('holder') or (info or {}).get('why') or 'another process'

        if con:
            print ('')
            print (f'{space}CACHE: the entry "{alias}" is being built by another process ({holder}) - waiting for it ...')

        timeout = files.lock_timeout(self.CACHE_WAIT_TIMEOUT, self.CACHE_WAIT_TIMEOUT_ENV, logger = self.logger)
        lock = files.PathLock(files._get_lockfile_path(os.path.normpath(path)), logger = self.logger)
        try:
            files.acquire_with_notice(lock, timeout, f'the cache entry "{alias}"', 'this request',
                                      self.CACHE_WAIT_TIMEOUT_ENV, logger = self.logger)
        except TimeoutError as e:
            return self.cm.error(str(e))
        except Exception as e:
            return self.cm.error(f'cannot wait for the cache entry "{alias}": {e}')

        lock.release()

        return {'return':0}

    def _cache_lookup(self, ctx, uses_categories, find_query, new, cache_repo, cache_name, request_params, request_path,
                      task_api_code, uparams, artifact_alias, create_entry, con, verbose, space):
        """
        The lookup of the cache entry of this run, under the creation lock of the cache repository (the
        sidecar lock of its cache category folder, held for milliseconds): find, classify (the engine's
        cache category), the task's filter hook; then

        - usable (ok) entries: returned for the selection and the cached result, as before;
        - otherwise the resumable entries of THIS request (the same recorded request): a running one is
          waited for (the creation lock released meanwhile) and the lookup starts again; otherwise the
          newest crashed, failed or broken one is resumed in place;
        - otherwise a new entry is created (`create_entry`) under the lock.

        The entry resumed or created is locked for this process's attempt before the creation lock is
        released, so two identical requests never build twice.

        Returns:
            {'return': 0, 'ok': [...], 'resumable': [...], 'states': {uid: info}, 'attempt': ... or None}
        """
        r = self._cache_repo_folder(cache_repo)
        if r['return']>0: return r
        category_folder = r['folder']

        files = self.cm.utils.files

        rounds = 0
        while True:
            rounds += 1
            if rounds > 50:
                return self.cm.error(f'no cache entry could be chosen for "{artifact_alias}" after {rounds} rounds of waiting')

            r = files.lock_path(category_folder, logger = self.logger)
            if r['return']>0:
                return self.cm.error(f'cannot lock the cache entries of {os.path.dirname(category_folder)}: {r.get("error")}')
            creation_lock = r['file_lock']

            wait_for = None
            wait_info = None
            try:
                if new:
                    found = []
                else:
                    r = self.cm.access(find_query)
                    if r['return']>0 and r['return']!=16: return r
                    found = r.get('artifacts', [])

                states = {}
                if found:
                    r = self.cm.access({'category': uses_categories['cache'], 'command': 'classify',
                                        'artifacts': found, 'con': False})
                    if self.cm.catch_error(r): return r
                    states = r['states']

                ok = []
                resumable = []
                for a in found:
                    if states.get(a['cmeta_ref_parts']['artifact_uid'], {}).get('state') == 'ok':
                        ok.append(a)
                    else:
                        resumable.append(a)

                # The task may drop entries that match the query but are not meant for this request
                # (task/setup asks the tool: a python request without a venv path of its own must not
                # reuse the venv of a program). Tasks without this hook keep every entry.
                if (ok or resumable) and task_api_code is not None and \
                   hasattr(task_api_code, 'filter_cache_artifacts') and callable(getattr(task_api_code, 'filter_cache_artifacts')):
                    r = task_api_code.filter_cache_artifacts(ctx, ok, resumable, uparams, path = request_path)
                    if self.cm.catch_error(r): return r

                    ok = r.get('artifacts', ok)
                    resumable = r.get('tmp_artifacts', resumable)

                if ok:
                    return {'return':0, 'ok': ok, 'resumable': resumable, 'states': states, 'attempt': None}

                mine = [a for a in resumable if self._cache_same_request(a, request_params, request_path, cache_name)]

                running = [a for a in mine if states.get(a['cmeta_ref_parts']['artifact_uid'], {}).get('state') == 'running']
                if running:
                    wait_for = running[0]
                    wait_info = states.get(wait_for['cmeta_ref_parts']['artifact_uid'], {})
                else:
                    candidates = [a for a in mine if states.get(a['cmeta_ref_parts']['artifact_uid'], {}).get('state') in ('crashed', 'failed', 'broken')]
                    candidates.sort(key = lambda a: str(a.get('cmeta', {}).get('creation_timestamp', '')), reverse = True)

                    for a in candidates:
                        state = states[a['cmeta_ref_parts']['artifact_uid']]['state']
                        r = self._cache_begin_attempt(ctx, a, state, request_params, artifact_alias)
                        if r['return'] == 0:
                            if con and verbose:
                                print ('')
                                print (f'{space}CACHE: resuming the {state} entry "{a["cmeta_ref_parts"].get("artifact_alias")}"')
                            return {'return':0, 'ok': [], 'resumable': resumable, 'states': states, 'attempt': r['attempt']}
                        if r.get('busy'):
                            wait_for = a
                            wait_info = states.get(a['cmeta_ref_parts']['artifact_uid'], {})
                            break
                        return r

                    if wait_for is None:
                        r = create_entry()
                        if r['return']>0: return r

                        entry = {'path': r['path'], 'cmeta': r['meta'], 'cmeta_ref_parts': r['ref_parts']}
                        r = self._cache_begin_attempt(ctx, entry, 'new', request_params, artifact_alias)
                        if r['return']>0:
                            if r.get('busy'):
                                return self.cm.error(f'the cache entry just created at {entry["path"]} is locked by another process')
                            return r

                        return {'return':0, 'ok': [], 'resumable': resumable, 'states': states, 'attempt': r['attempt']}

            finally:
                try:
                    creation_lock.release()
                except Exception:
                    pass

            r = self._cache_wait_for(wait_for, wait_info, artifact_alias, con, space)
            if r['return']>0: return r

    def _cache_finish_attempt(self, attempt, ctx, uses_categories, cache_name, cache_params, result, failed, con, verbose, space):
        """
        The end of this process's attempt in its entry: the result (and the ctx of a success) written
        first, atomically; then the entry updated - its `params` REPLACED by this request's cache params
        plus what the task added, the recorded request kept, the `tmp` tag removed, `failed` added or
        removed - then the running file removed and the entry lock released.
        """
        if attempt is None or attempt.get('done'):
            return {'return':0}

        files = self.cm.utils.files

        r = files.safe_write_file(self.CACHE_FILE_WITH_RESULTS, result)
        if self.cm.catch_error(r): return r

        if not failed:
            r = files.safe_write_file(self.CACHE_FILE_WITH_CTX, ctx, safe_dump = True)
            if self.cm.catch_error(r): return r

        if con and verbose:
            print ('')
            print (f'{space}UPDATE: cache in {cache_name}' + (' (the attempt failed)' if failed else ''))

        # The entry's params = THIS request's full cache meta params (the identity keys AND the constant
        # params a tool adds for the match, e.g. with.compute of llama-cpp - what the find of the next
        # request matches) plus what the task reported (`_update_params`, tool_path, version): nothing
        # of an earlier attempt survives. (Only cache_params here lost the constant params, and the next
        # request made a new entry instead of finding the built one - seen on WSL2, 2026-10-09 17:24.)
        meta = copy.deepcopy(attempt.get('meta') or {})
        request_params = copy.deepcopy(attempt.get('request_params') or {})
        meta['params'] = self.cm.utils.common.deep_merge(request_params, copy.deepcopy(cache_params) if cache_params else {}, append_lists=False)
        if attempt.get('request_params') is not None:
            meta['request_params'] = copy.deepcopy(attempt['request_params'])

        ii = {'category': uses_categories['cache'],
              'command': 'update',
              'arg1': cache_name,
              'replace': True,
              'meta': meta,
              'new_tags': ['tmp-', 'failed'] if failed else ['tmp-', 'failed-'],
              'con': False,
             }

        r = self.cm.access(ii)
        if self.cm.catch_error(r): return r

        self._cache_release_attempt(attempt)

        stack = _CACHE_ATTEMPTS.get(id(ctx))
        if stack and attempt in stack:
            stack.remove(attempt)

        return {'return':0}


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
                   saved_cparams = None,
                   saved_local = None,
                   skip_if_exist_in_list = True,
                   saved_ctx_control = None,
                   preserve_global = {},
    ):

        # Save output for reproducibility
        if self.cm.debug:
            call_repro['result'] = copy.deepcopy(result)

        # Check aggregated results
        if aggregate and '_aggregate' in result:
            _aggregate = result['_aggregate']
            ctx_tasks = ctx.setdefault('tasks', {})
            _aggregated = ctx_tasks.setdefault('aggregated', {})

            _aggregated = self.cm.utils.common.deep_merge(
              _aggregated, 
              _aggregate, 
              append_lists = True, 
              prepend_lists = True, 
              skip_if_exist_in_list = True,
            )

        # Save results in the work_dir directory (cache, path, etc)
        if save:
            if con:
                x = os.getcwd()
                print ('')
                print (f'SAVE: context and result in path "{x}"')

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

            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_RESULTS, result, safe_dump = True)
            if self.cm.catch_error(r): return r
            r = self.cm.utils.files.write_file(self.SAVE_FILE_WITH_CTX, ctx, safe_dump = True)
            if self.cm.catch_error(r): return r

        ctx['tasks']['params'] = saved_uparams if saved_uparams else {}
        ctx['tasks']['cparams'] = saved_cparams if saved_cparams else {}
        ctx['tasks']['local'] = saved_local if saved_local else {}
        ctx['control'] = saved_ctx_control if saved_ctx_control else {}

        # Restore global
        if preserve_global:
            for k in preserve_global:
                v = preserve_global[k]
                if v is None:
                    if k in ctx['tasks']['global']:
                        del(ctx['tasks']['global'][k])
                else:
                    ctx['tasks']['global'][k] = v

        return {'return':0}


    ############################################################
    def use_(
            self,
            ctx: dict,
            desc: dict = {},
            local = None,
            task_artifact_alias = None,
            task_artifact_uid = None,
            task_artifact_path = None,
            task_api_code = None,
            uparams = {},
            self_desc = {},
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

        # Local may come from some direct calls from sub-tasks or sub-functions
        # In such case, preserve current one and use the required one
        if local is not None:
            saved_local = ctx_tasks.get('local')
            ctx_tasks['local'] = local

        for sub_task_desc in copy.deepcopy(desc):
            if type(sub_task_desc) != dict:
                return self.cm.error(f'sub-task is not "dict" in task "{task_artifact_alias}" in "{__file__}" ({sub_task_desc})')

            ii = copy.deepcopy(sub_task_desc)

            # Check if _update
            _update = ii.pop('_update', None)
            if _update:
                r = self.cm.utils.common.expand_string(_update, ctx_tasks)
                if self.cm.catch_error(r): return r

                _update = r['value']

                self.cm.utils.common.deep_merge(ii, _update, append_lists=False)

            if ii.pop('skip_if_not_win', False) and os.name != 'nt':
                continue

            # Check OS
            target_os = ii.pop('if_os', None)
            target_os_id = ii.pop('if_os_id', None)
            fail_if_wrong_host_os = ii.pop('fail_if_not_os', False)

            if target_os:
                if type(target_os) == str:
                    target_os = target_os.split(',')

            if target_os_id:
                if type(target_os_id) == str:
                    target_os_id = target_os_id.split(',')

            if target_os or target_os_id:
                uname = ctx['tasks']['global']['host']['os']['uname']
                os_id = ctx['tasks']['global']['host']['os_extra']['id']

                if target_os and uname not in target_os:
                    if fail_if_wrong_host_os:
                        return self.cm.error(f'host OS "{uname}" is not supported for "{task_artifact_alias}" in "{__file__}"')
                    else:
                        continue

                if target_os_id and os_id not in target_os_id:
                    if fail_if_wrong_host_os:
                        return self.cm.error(f'host OS ID "{os_id}" is not supported for "{task_artifact_alias}" in "{__file__}"')
                    else:
                        continue

            # Check generic if
            _if = ii.pop('if', None)
            if _if:
                r = self.cm.utils.common.expand_string(_if, ctx_tasks)
                if self.cm.catch_error(r): return r

                _if = r['string']

                r = self.cm.utils.common.restricted_bool_eval(_if, {})
                if self.cm.catch_error(r): return r

                # If condition is not met, skip sub-task
                if not r['result']:
                    continue

            # Check local update
            _local = ii.pop('local', None)
            if _local:
                ctx_tasks['local'] = self.cm.utils.common.deep_merge(ctx_tasks['local'], _local, append_lists=True)

            # Add extra short-cut params
            ctx_tasks_with_extra_values = ctx_tasks.copy()
            ctx_tasks_with_extra_values['os_sep'] = os.sep
            if task_artifact_path:
                ctx_tasks_with_extra_values['task_artifact_path'] = task_artifact_path
            ctx_tasks_with_extra_values['task_artifact_alias'] = task_artifact_alias
            ctx_tasks_with_extra_values['task_artifact_uid'] = task_artifact_uid

            for k in ['file_ext_bat', 'cmd_new_line', 'os_sep', 'os_pathsep']:
                x = ctx['tasks']['global'].get('host',{}).get('vars',{}).get(k)
                if x: 
                    ctx_tasks_with_extra_values[k] = x 

            # Check if set env (in aggregated) used by further tasks
            set_env = ii.pop('set_env', {})
            if set_env:
                r = self.cm.utils.common.expand_strings_in_dict(set_env, ctx_tasks_with_extra_values)
                if self.cm.catch_error(r): return r

                _aggregated = ctx_tasks.setdefault('aggregated', {})
                _aggregated_env = _aggregated.setdefault('env', {})
                _aggregated_env = self.cm.utils.common.deep_merge(
                  _aggregated_env, 
                  set_env, 
                  append_lists = True, 
                  prepend_lists = True, 
                  skip_if_exist_in_list = True,
                )

            r = self.cm.utils.common.expand_strings_in_dict(ii, ctx_tasks_with_extra_values)
            if self.cm.catch_error(r): return r

            func = ii.pop('internal_func', None)
            task = ii.pop('task', None)

            if ii.pop('reuse_all_params', False) and uparams:
                self.cm.utils.common.deep_merge(ii, uparams, append_lists=True)

            if not task and not func:
                return self.cm.error(f'the requirement in task "{task_artifact_alias}" misses "task" or "internal_func" in "{__file__}" ({sub_task_desc})')

            if task:

                ii['ctx'] = ctx

                ii['arg1'] = task

                ii['category'] = 'task,' + self.cmeta['artifact'] if 'category' not in ii else ii['category']
                ii['command'] = 'run' if 'command' not in ii else ii['command']

                ii['con'] = con
                ii['quiet'] = quiet
                ii['verbose'] = verbose

                # Update context for tasks
                ctx_tasks['nested_call'] += 1

                sub_task_result = self.cm.access(ii)
                if self.cm.catch_error(sub_task_result): 
                    err = sub_task_result['error']

                    j = err.find('unexpected keyword argument')
                    if j>0:
                        j1 = err.find('.', j)
                        if j1>0:
                            sub_task_result['error'] = err[:j1+1] + f'\n(sub task desc = {sub_task_desc})' + err[j1+1:]

                    return sub_task_result

                ctx_tasks['nested_call'] -= 1
            else:
                if verbose:
                    print (f'{sub_space}' + '=' * (100-len(sub_space)))
                    print (f'{sub_space}INTERNAL FUNC: {func} from task "{task_artifact_alias}"')

                internal_func_from_local_key = ii.pop('internal_func_from_local_key', None)
                internal_func_from_global_key = ii.pop('internal_func_from_global_key', None)
                internal_func_safe = ii.pop('internal_func_safe', False)

                if internal_func_from_local_key or internal_func_from_global_key:
                    if internal_func_from_local_key:
                        api_code = ctx_tasks['local'][internal_func_from_local_key].get('api_code')
                        where = f'local context key "{internal_func_from_local_key}"'
                    else:
                        api_code = ctx_tasks['global'][internal_func_from_global_key].get('api_code')
                        where = f'global context key "{internal_func_from_global_key}"'
                else:
                    api_code = task_api_code
                    where = f'task "{task_artifact_alias}"'

                if api_code:
                    task_func = getattr(api_code, func, None)

                    if callable(task_func):
                        r = task_func(ctx, desc = self_desc, params = uparams, extra_desc_params = ii)
                        if self.cm.catch_error(r): return r
                    elif not internal_func_safe:
                        return self.cm.error(f'internal func "{func}" is missing in API code in {where}')

                elif not internal_func_safe:
                    return self.cm.error(f'internal func "{func}" misses api_code in {where}')


        # Restore local if direct call from external source and not from a given task
        if local is not None:
            ctx_tasks['local'] = saved_local

        return {'return':0, 'local': local}

