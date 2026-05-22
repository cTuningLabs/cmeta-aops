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

        self.target_artifact_alias_prefix = 'target--'


    ############################################################
    def run(self,
            ctx: dict,            # cMeta context
            compute: list = None, # string or list of compute (task::target-{name})
            ask: bool = False,    # ask for compute if not specified
            add_env: bool = True, # add global ENV
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        if '#target' in ctx_tasks['global']:
            # runner is already running and called from somewhere again
            return {'return':0}

        # Set lock
        ctx_tasks['global']['#target'] = {}

        # Check target compute
        # Simplify CLI
        if compute is True:
            compute = None
            ask = True

        if not compute:
            if ask:
                p = {
                  'category': self.cmeta['uses_categories']['utils'],
                  'command': 'select_artifact',
                  'select_category': self.category_alias + ',' + self.category_uid,
                  'select_artifact': self.target_artifact_alias_prefix + '*',
                  'select_text': 'Select compute targets (one or separated by comma)',
                  'allow_multiple': True,
                  'con': con,
                  'quiet': quiet,
                  'verbose': verbose,
                  'space': space,
                  'print_extra_line': True,
                }

                r = self.cm.access(p)
                if self.cm.catch_error(r, fail16=True): 
                    r['return'] = 99
                    return r

                artifacts = r['artifacts']
                indexes = r['indexes']
                compute = []

                for index in indexes:
                    artifact = artifacts[index]
                    artifact_alias = artifact['cmeta_ref_parts']['artifact_alias']
                    compute.append(artifact_alias[len(self.target_artifact_alias_prefix):].lower())

                if con:
                    print ('')
                    x = ', '.join(compute)
                    print (f'{space}INFO: selected compute: {x}')

            else:
               compute = ['cpu']
        elif type(compute) == str:
            xcompute = []
            for x in compute.split(','):
                x = x.strip().lower()
                if x != '': 
                    xcompute.append(x)
            compute = xcompute

        # Prepare dependencies
        uses = []
        _local = {}
        features = {}

        for c in compute:
            task = self.target_artifact_alias_prefix + c

            # Try to load desc
            r = self.cm.access({
              'category': self.category_alias + ',' + self.category_uid,
              'command': 'read',
              'arg1': task,
              'base': True,
              'load_files':['_desc'],
            })
            if self.cm.catch_error(r, fail16=True): 
                r['return'] = 99
                return r
 
            cdesc = r['loaded_files']['_desc'].get('data', {})

            features[c] = {'desc': cdesc}

            compute_use = {
              'task': task,
            }

            uses.append(compute_use)


        # Resolve as standard dependency
        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'use',
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'ctx': ctx,
              'desc': uses,
              'local': _local,
              'task_artifact_alias': self.artifact_alias,
              'task_artifact_uid': self.artifact_uid,
              'task_artifact_path': self.artifact_path,
             }

        r = self.cm.access(ii)
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 99
            return r

        # Prepare result
        result = {
          'return': 0,
          'compute': compute,
        }

        for c in compute:
            key = self.target_artifact_alias_prefix + c

            ft = ctx['tasks']['global'][key].get('features', {})

            features[c].update(ft)

        result['features'] = features

        # Check environment vars
        p = {
          'category': self.category_alias + ',' + self.category_uid,
          'command': 'find',
          'arg1': self.target_artifact_alias_prefix + '*',
          'load_files':['_desc'],
        }

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 99
            return r
        
        env = {'CMETA_TARGETS': ','.join(compute)}

        cmake_vars = {}
        env_vars = {}

        for c in r.get('artifacts',[]):
            desc = c['loaded_files']['_desc'].get('data',{})
            compute_alias = c['cmeta_ref_parts']['artifact_alias'][len(self.target_artifact_alias_prefix):].lower()

            env_set = desc.get('env', {})
            env_unset = desc.get('env_if_not_used', {})

            if env_set and env_unset:
                if compute_alias in compute:
                    env_vars.update(env_set)

            cmake_vars_set = desc.get('cmake_vars', {})
            cmake_vars_unset = desc.get('cmake_vars_if_not_used', {})

            if cmake_vars_set and cmake_vars_unset:
                if compute_alias in compute:
                    cmake_vars.update(cmake_vars_set)


        for c in r.get('artifacts',[]):
            desc = c['loaded_files']['_desc'].get('data',{})
            compute_alias = c['cmeta_ref_parts']['artifact_alias'][len(self.target_artifact_alias_prefix):].lower()

            env_set = desc.get('env', {})
            env_unset = desc.get('env_if_not_used', {})

            if env_set and env_unset:
                for k in env_unset:
                    if k not in env_vars:
                        env_vars[k] = env_unset[k]

            cmake_vars_set = desc.get('cmake_vars', {})
            cmake_vars_unset = desc.get('cmake_vars_if_not_used', {})

            if cmake_vars_set and cmake_vars_unset:
                for k in cmake_vars_unset:
                    if k not in cmake_vars:
                        cmake_vars[k] = cmake_vars_unset[k]


        result['cmake_vars'] = cmake_vars

        env.update(env_vars)

        if add_env:
            _aggregate = result.setdefault('_aggregate', {})
            _aggregate_env = _aggregate.setdefault('env', {})

            _aggregate_env.update(env)

        # Remove lock
        del (ctx_tasks['global']['#target'])

        return result
