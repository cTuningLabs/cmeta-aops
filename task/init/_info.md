Global config for tasks!

  * default_cache_repo -> the repo that takes the cache entries of the whole run instead of local
    (to keep some persistent entries in other repos): `--use.init.default_cache_repo=<repo>` for one run,
    or the key `default_cache_repo` of config::task for every run. It wins over `--cache_repo=<repo>`,
    which does the same for a single task.
