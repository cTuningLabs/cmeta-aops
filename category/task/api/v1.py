"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.
License: Proprietary - contact the author for licensing information.
"""

import os
import time
import copy

from cmeta.category import InitCategory
from .ctask import InitCTask


# TBD: change cmeta -> params to cmeta -> input -> params that can be reused 
#   see how to deal with directory and update <- must be picked up from the input ...
#

# TBD: move task to the common ...
# TBD:  how to deal with multiple 
# TBD:  how to save externally and pick up externally in some directory?

# TBD: expose git detect, etc - what if inside installation
# TBD: pipelines 


class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):

        self.CACHE_FILE_WITH_RESULTS = 'cmeta-task-result.json'

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

        cur_dir = os.getcwd()
        cache_path = None
        workdir = cur_dir

        ###########################################################################################
        # SELECT ARTIFACT

        # Call base find function to find an artifact with a website
        p = {'category':'utils,234ce5e3262e4d52',
             'command':'select_artifact',
             'select_category':state['category'],
             'select_artifact':arg1,
             'select_tags':tags,
             'con':con,
             'quiet':quiet}

        r = self.cm.access(p)
        if r['return']>0: 
            ret = r['return']
            if ret == 16: ret = 1
            return self.cm._error(r['error'], ret, None, self.cm.fail_on_error)

        artifact = r['artifact']

        artifact_path = artifact['path']
        cmeta = artifact['cmeta']
        cmeta_ref_parts = artifact['cmeta_ref_parts']

        artifact_alias = cmeta_ref_parts.get('artifact_alias', '')
        artifact_uid = cmeta_ref_parts['artifact_uid']
        artifact_au = artifact_alias if artifact_alias is not None and artifact_alias != '' else artifact_uid
        category_uid = cmeta_ref_parts['category_uid']

        # Check version
        xver = '1'
        if ver is not None and str(ver) != '0':
            xver = ver
        elif inside_cli or str(ver) == '0':
            if cmeta.get('last_api_version') is not None:
                xver = str(cmeta['last_api_version'])

        # Check min cMeta versions
        min_cmeta_version = cmeta.get('min_cmeta_version_api')
        if min_cmeta_version is None:
            min_cmeta_version = cmeta.get('min_cmeta_version',{}).get(xver)

        if min_cmeta_version is not None:
            cm_version = self.cm.__version__
            r = self.cm.utils.common.compare_versions(min_cmeta_version, cm_version)
            if r['return']>0: return r
            if r['comparison'] == '>':
                err = f'the task "{artifact_au}" requires min cMeta version "{min_cmeta_version}" but "{cm_version}" is installed'
                return self.cm._error(err, 1, None, self.cm.fail_on_error)

        task_api_path = os.path.join(artifact_path, f'api_v{xver}.py')

        if ver is not None and not os.path.isfile(task_api_path):
            err = f'task module not found: {task_api_path}'
            return self.cm._error(err, 1, None, self.cm.fail_on_error)

        result = {'return':0}

        task_api_code = None
        if os.path.isfile(task_api_path):
            r = self.cm.utils.sys.load_module(task_api_path, self.cm.module_cache, fail_on_error = self.fail_on_error, 
                                              init_class="CTask", cmeta=self.cm, suffix=category_uid, self_meta=cmeta)
            if r['return'] >0: return r

            task_api_code = r['cache']['initialized_class']

        if task_api_code is not None and info:
            r = self.cm.utils.names.restore_cmeta_obj(cmeta_ref_parts, key='artifact', fail_on_error = self.fail_on_error)
            if r['return']>0: return r
            category_str = r['obj']

            r = self.cm.utils.sys.get_api_info(task_api_code, 'run', f'task run {artifact_au}')
            if r['return'] > 0: return r

            help_text = r['api_info']

            if con:
                print (help_text)

            result['help'] = help_text

            return result



        ###########################################################################################
        # UNIFY PARAMS - most commonly convert args to keys

        uparams = params.copy()

        params_aliases = cmeta.get('params_aliases', {})
        if len(params_aliases):
            for k in params_aliases:
                kk = params_aliases[k]

                if k in uparams:
                    uparams[kk] = uparams.pop(k)

        if update:
            uparams['update'] = True
        if clean:
            uparams['clean'] = True
 

        ###########################################################################################
        # PROCESS CACHE
        task_result_file = None
        update_cache = False

        cache_params = {}
        if cache_extra_params:
            cache_params = copy.deepcopy(cache_extra_params)

        if cache:
            # Check if compatible with cache
            if cmeta.get('no_cache', False):
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

            # Check if params keys are defined in cmeta to be added to cache_tags
            cache_params_keys = cmeta.get('cache_params', [])
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
            ii = {'category':'cache,1ebdcc1cc30c4022',
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

                text = f'More than 1 cache entry found for task "{artifact_alias}"'
                if len(cache_params)>0:
                    text += ' with parameters:\n'
                    for p in sorted(cache_params):
                        v = str(cache_params[p])
                        text += f'      * params.{p} = {v}\n'
                    text += '\n'
                else:
                    text += '. '

                text += 'Please select'

                # Call base find function to find an artifact with a website
                p = {'category': 'utils,234ce5e3262e4d52',
                     'command': 'select_artifact',
                     'select_category': 'cache',
                     'select_text': text,
                     'artifacts': cache_artifacts,
                     'cmeta_params_keys': ['params', 'path'],
                     'skip_uids': True,
                     'con':con,
                     'quiet':quiet}

                if 'sort_keys' in cmeta:
                    p['sort_keys'] = cmeta['sort_keys']

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

                    if con and verbose:
                        print (f'INFO Reusing task result from {cache_path}')

                    if not path:
                        path = cache_path

                    task_result_file = os.path.join(path, self.CACHE_FILE_WITH_RESULTS)
                    r = self.cm.utils.files.read_file(task_result_file)
                    if r['return']>0: return self.cm._error2(r, self.cm)

                    return r['data']

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

               r = self.cm.access({'category':'cache,1ebdcc1cc30c4022',
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
                print (f'USE cMeta cache: {cache_path}')

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
                            print (f'REUSE result: {task_result_file}')

                        skip = True


        ###########################################################################################
        # PREPARE WORKING DIRECTORY
        if path:
            workdir = path
        elif cache_path:
            workdir = cache_path
            
        if not os.path.isdir(workdir):
            os.makedirs(workdir, exist_ok=True)

        if con and verbose:
            print ('')
            print (f'RUN cd {workdir}')

        os.chdir(workdir)

        if task_result_file and os.path.isfile(task_result_file) and (clean or update):
            if con and verbose:
                print ('')
                print (f'RUN rm {task_result_file}')

            os.remove(task_result_file)

        ###########################################################################################
        # RUN TASK

        time_start2 = time.perf_counter()
        if task_api_code is not None and not skip:
            if con and verbose:
                print ('')
                print (f'RUN TASK {artifact_alias}')

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
            ii = {'category':'cache,1ebdcc1cc30c4022',
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
        if cache or save:
            r = self.cm.utils.files.write_file(self.CACHE_FILE_WITH_RESULTS, result)
            if r['return']>0: return self.cm._error2(r, self.cm)


        ###########################################################################################
        # RESTORE ORIGINAL DIRECTORY

        os.chdir(cur_dir)

        return result
