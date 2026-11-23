Global config for tasks!

  * default_cache_repo -> the repo that takes the cache entries of the whole run instead of local
    (to keep some persistent entries in other repos): `--use.init.default_cache_repo=<repo>` for one run,
    or the key `default_cache_repo` of config::task for every run. It wins over `--cache_repo=<repo>`,
    which does the same for a single task.

  * reuse_conflict -> what the task engine does when a storage key that is already chosen in a run is asked again
    with another version (the first choice is used): `warn` (said and kept in the context), `all` (any other
    parameter asked differently too), `error` (the run stops), `ignore`. `--use.init.reuse_conflict=<word>` for
    one run, else `CMETA_REUSE_CONFLICT`, else the key `reuse_conflict` of config::task.
