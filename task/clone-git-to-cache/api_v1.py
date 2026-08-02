"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self, ctx, **params):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK clone-git-to-cache run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''
        clean = ctx_tasks['run_control'].get('clean', False)
        update = ctx_tasks['run_control'].get('update', False)

        cparams = ctx_tasks['cparams']
        path = cparams.get('path') # If defined should be the same as work_dir

        path_file_cache_list = ctx['tasks'].get('global', {}).get('init', {}).get('file_cache')
        if path_file_cache_list:
            path_file_cache = None

            for x in path_file_cache_list.split(os.pathsep):
                if os.path.isdir(x):
                    path_file_cache = x
                    break
                else:
                    try:
                       os.makedirs(x, exist_ok=True)
                       path_file_cache = x
                       break
                    except:
                       pass

            if path_file_cache:
                path = os.path.join(path_file_cache, 'git-' + params['name'])
                version_to_dir = params.get('version_to_dir', False)
                skip_checkout_dir = params.get('skip_checkout_dir', False)

                root_dir = ''

                if params.get('root_dir'):
                    root_dir = params['root_dir']
                else:
                    if version_to_dir:
                        if not params.get('version'):
                            return self.cm.error(f'version_to_dir is True but version is not defined in "{__file__}" ')

                        root_dir += params['version']

                    if not skip_checkout_dir:
                        checkout = params.get('checkout')
                        if not checkout:
                            checkout = 'current'

                        if root_dir != '':
                            root_dir += '-'

                        root_dir += checkout

                path = os.path.join(path, root_dir)
                os.makedirs(path, exist_ok=True)

        run_control = ctx_tasks['run_control']

        cur_dir = run_control['cur_dir'] # from where this task is executed
        work_dir = run_control['work_dir'] # either cache or forced path !

        p = {
          'ctx': ctx,
          'category': self.category_alias + ',' + self.category_uid,
          'command': 'run',
          'arg1': 'clone-git,af9422df6ea241ec',
          'con': con,
          'quiet': quiet,
          'verbose': verbose,
          'path': path,
          'update': cparams.get('update')
        }

        for k in ['url', 'directory', 'tag', 'checkout']:
            if k in params:
                p[k] = params[k]

        result = self.cm.access(p)
        if self.cm.catch_error(result): return result

        path_to_git_repo = result['path_to_git_repo']

        # Update cache parameter to let task check if path disappeared and invalidate cache entry
        _update_params = result.setdefault('_update_params', {})
        _update_params['git_path'] = path_to_git_repo

        return result

