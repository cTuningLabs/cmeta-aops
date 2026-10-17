"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

# The run-wide settings of the versions of tools (task/setup/upgrade.py): the parameter of this task
# (--use.init.<key>=...), else the environment variable, else the key of config::task
VERSION_KEYS = {'version_policy': 'CMETA_VERSION_POLICY',           # known | latest | ask
                'versions_ttl_hours': 'CMETA_VERSIONS_TTL_HOURS'}    # how long a lookup of the newest version is trusted


class CTask(InitCTask):
    """
    """

    ############################################################
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        return {'return':0}

    ############################################################
    def run(self,
            ctx: dict,              # cMeta context
            default_cache_repo: str = None,
            cache_repos: dict = None,        # --use.init.cache_repos.<key>=<repo>: the repositories of the data tasks' entries for this run (else the key cache_repos of config::task)
            file_cache: str = None,          # the folder(s) of large downloads and clones for this run (else the key file_cache of config::task)
            version_policy: str = None,      # known | latest | ask for every tool of the run (else CMETA_VERSION_POLICY, else config::task)
            versions_ttl_hours: str = None,  # hours a cached lookup of a newest version is trusted (else CMETA_VERSIONS_TTL_HOURS, else config::task; 24)
    ):

        """
        It just stores init config

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        result = {'return':0}

        # Check in config::task
        r = self.cm.access({
          'category':'config,cc6bfe174be847ed', 
          'command':'get', 
          'arg1':'task',
        })
        if self.cm.catch_error(r): return r

        cfg = r['config_cmeta']
        if cfg:
            result.update(cfg)

        # Update from API/CLI (--use.init.default_cache_repo=<repo>): the key the task engine reads,
        # the same one config::task may set
        if default_cache_repo:
            result['default_cache_repo'] = default_cache_repo

        # --use.init.cache_repos.data=<repo>: where the data tasks (cache_repo_key: data) keep their entries this run
        if isinstance(cache_repos, dict) and cache_repos:
            result['cache_repos'] = dict(result.get('cache_repos') or {}, **{str(k): str(v) for k, v in cache_repos.items() if v})

        # --use.init.file_cache=<folder>: the file cache of this run (clone-git-to-cache, get-hf-model, ...)
        if file_cache:
            result['file_cache'] = file_cache

        # The versions of tools: the flag, else the environment, else the config (already in result)
        given = {'version_policy': version_policy, 'versions_ttl_hours': versions_ttl_hours}
        for key, env in VERSION_KEYS.items():
            value = given[key] or os.environ.get(env)
            if value not in (None, ''):
                result[key] = value

        return result

