<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
-->

# The `task` category — the workflow engine

`task` (category UID `c36be4b9314a45e0`, **API v2**, orchestrator
`category/task/api/v2.py`) is cMeta's workflow engine. A *task artifact* is one
reusable, composable, cacheable step. Everything higher-level delegates into tasks
(`tool setup/run` → `setup`/`cmd`; `program run` → `compile-and-run-program`). There
are ~114 task artifacts. The category declares only two cross-category deps
(`category/task/_cmeta.yaml`): `cache` and `utils`.

## Task artifact anatomy

`task/<name>/`:

| File | Role | Required |
|------|------|----------|
| `_cmeta.yaml/json` | identity (`artifact:` UID, `category: task,c36be4b9314a45e0`, `tags`, `constraints`, `note`) | yes |
| `_desc.yaml` | the **declarative pipeline** — `uses`, `params_map`, cache + `store_global` config, templated commands. Most tasks are only this. | yes |
| `api_v1.py` | optional `CTask(InitCTask)` hooks for imperative logic | ~66 of 114 |

## The `run()` lifecycle (`v2.py`, ~1400 lines)

Every `cx task run X` and every nested sub-task re-enters this one function. Ordered
phases:

1. **Select artifact** — `utils.select_artifact` resolves `arg1`/`--tags`, loads
   `_desc.yaml` → `cdesc` and the `CTask` class → `task_api_code`.
2. **`--info`** — prints `run()`'s signature/docstring and returns **only if the task
   has `api_v1.py`** (the info branch needs api code). For a pure-`_desc.yaml` task,
   `--info` does *not* short-circuit — it executes the pipeline.
3. **`params_map`** — maps positional `arg2/arg3/...` and short flags to named params,
   including dotted paths into nested dicts / `use.*` / `ctx.*`.
4. **Save/blank state** — `params`, `cparams`, `local` are saved and reset;
   `preserve_global_keys` (glob-aware) snapshots+removes matching global keys so a task
   is atomic w.r.t. shared context (restored in `_finish_run`).
5. **`uses_before_init`** pipeline → **`api.init()`** (may `skip_run`, inject `uses`,
   override `storage_key`).
6. **Resolve `storage_key`** (templated, `.`→`-`) and default `store_global`.
7. **Global-memo short-circuit** — if `store_global` and `storage_key` already in
   `ctx['tasks']['global']`, reuse the stored result (running `finish_dynamic_result`
   even on the cached copy) and return.
8. **Apply `--use.<key>`** overrides → **`api.check_params()`** (may `stop`).
9. **`uses`** pipeline (main deps).
10. **Cache resolution** — may return an on-disk cached result.
11. **`uses2`** pipeline (after cache dir chosen, before python; reuses `local` — used
    for `cmd`-type finalizers).
12. **`api.run(ctx, **uparams)`** → result dict.
13. **Cache write + `finish_dynamic_result`** — persist result/ctx JSON, apply dynamic
    post-processing (runs even on cache/memo reuse).
14. **`_finish_run`** — aggregate `_aggregate` into `aggregated`, optional `--save`,
    `chdir` back, restore saved params/local/global.

Return contract everywhere: `{'return':0, ...}` ok; `{'return':>0,'error':...}` fail;
`{'return':16}` soft "not found". Check with `self.cm.catch_error(r)` (`fail16=True` to
treat 16 as error).

## The shared `ctx['tasks']` context

The single thread of state through all nested calls:

- **`global`** — survives the whole run; keyed by `storage_key` (`host`, `runner`,
  `init`, `compiler-<lang>`, `<tool-name>`, `target`, `target--<c>`, `lib-*`). The
  in-memory memoization store.
- **`local`** — scoped to one invocation; blanked on entry, restored on exit.
- **`params` / `cparams`** — the current task's user params vs. control params.
- **`aggregated`** — accumulator across the pipeline, chiefly **`aggregated.env`** (the
  `+PATH`/`+LD_LIBRARY_PATH` lists a later `cmd` task consumes).
- **`use`** — `--use.<storage_key>.<param>` overrides injected into a specific task.
- **`nested_call`** — depth counter (verbose indentation).
- **`run_control`** — per-run scratch (`cur_dir`, `work_dir`, `task_path`,
  `clean`/`update`/`new`, `cache_params`, `cache`) handed to `api.run()`.

## Sub-task pipelines — `uses` / `uses_before_init` / `uses2`

Lists of dicts resolved by `use_()`. Each entry dispatches **either**:

- `task: <alias>,<UID>` — recurse into `task run`. Extra keys become that sub-task's params.
- `internal_func: <name>` — call a method on this task's api code (or, with
  `internal_func_from_local_key`/`_from_global_key`, on api code stored in ctx);
  `internal_func_safe: True` = don't error if missing.

Which list:
- **`uses_before_init`** — before `api.init()` (prerequisites `init` needs).
- **`uses`** — the main pipeline (after `init`, before cache + `run`).
- **`uses2`** — after cache dir chosen, right before `api.run()`; reuses `local`.

Per-entry modifiers (all optional, all values templated against `ctx['tasks']`):
`if:` (safe expr), `if_os:` / `if_os_id:` / `fail_if_not_os` / `skip_if_not_win`,
`set_env:` (accumulate into `aggregated.env`), `_update:` (deep-merge a computed dict),
`local:` (merge into local ctx), `reuse_all_params: True`, and per-entry
`store_global`/`storage_key`/`cache` overrides.

## Changing a dependency anywhere in a pipeline

`--use.<storage_key>.<param>=<value>` changes a parameter of **any** sub-task of a run, however deep
it sits, without editing a `_desc.yaml`:

```bash
cxt test-mojo-life --use.python.version=3.12.13            # the python that some sub-task sets up
cxt <task> --use.uv.version=0.12.16                         # the uv that setup,name=uv installs or detects
cxt <task> --use.clang.version=22.1.7 --use.clang-cpp.version=22.1.7
cxt <task> --use.get-hf-model.repo=<org>/<model> --use.get-hf-model.update   # a param and a control switch of one sub-task
```

How it works (`v2.py`: `use` is parsed with the other dotted keys, kept in `ctx['tasks']['use']`, and
applied in "UPDATE PARAMS FROM USE BASED ON STORAGE KEY"):
- **One dict for the whole run.** `--use.uv.version=0.12.16` becomes `use: {uv: {version: 0.12.16}}`,
  deep-merged into `ctx['tasks']['use']`, so it reaches every nesting level.
- **Matched by storage key.** When a task starts, its params are deep-merged with `use[<its storage
  key>]`, **overriding** what its parent passed in the `uses:` entry.
- **The words are read by what `run()` expects (cMeta 0.37+).** On a run started from the command line,
  a word given to a task - `--x=no` on its own command line or `--use.<key>.x=no` for a sub-task - becomes
  a boolean when `run()` annotates the parameter `bool` (`x: bool = False`): yes/no, true/false, on/off,
  1/0, any case; any other word stops the run with a message naming the parameter and the task. A task
  can describe its sensitive parameters in its `_desc.yaml` and the task category converts and checks
  exactly those: `cli_params: {count: int, mode: {values: [fast, full]}, ratio: {type: float, min: 0,
  max: 1}}`. A parameter without annotation or description gets the text as it is; the Python API and the
  values a task's code passes to a sub-task are never read (the task category reads only the words the
  command line literally holds for the task: `--x=no`, `-x=no`, `x=no`, `--use.<key>.x=no`). A task whose
  `run()` reads `**kwargs` has no annotations to read against: it names its switches in `cli_params`
  (`task/setup` does, for `detect`, `install`, `skip_install`, `versions`, ...). `cli_types: false` in a
  task's `_desc.yaml` and `CMETA_CLI_TYPES=off` keep the words text.
- **Control switches travel too.** `path`, `skip`, `cache`, `cache_repo`, `cache_name`,
  `cache_extra_alias`, `cache_extra_params`, `cache_extra_tags`, `update`, `clean`, `new` go to that
  task's control params: `--use.get-hf-model.update` redoes only that step.
- **The cache repo of a whole run.** `--use.init.default_cache_repo=<repo>` (or the key
  `default_cache_repo` of `config::task`, for every run) makes every task of the run, dependencies
  included, find and create its cache entries in that repo instead of `local`; an unknown repo is an
  error. `--cache_repo=<repo>` on a task (`--use.<key>.cache_repo=<repo>` on a sub-task) does it for
  that task alone, and the run-wide repo wins over it.

The storage key of a sub-task:

| Sub-task | Storage key | Example |
|---|---|---|
| `setup` (a tool) | the tool's alias (`{{$params.name}}`): `python`, `uv`, `git`, `clang`, ... | `--use.python.version=3.12.13` |
| `clone-git-to-cache` | `clone-git-to-cache-<name>` | `--use.clone-git-to-cache-src-<x>.depth=1` |
| `runner`, `host`, `init` | fixed: `runner`, `host`, `init` | |
| a compiler | `compiler-<lang>` | `--use.compiler-c.name=gcc,...` |
| any other task | its `storage_key` in `_desc.yaml`, else its alias | `--use.get-hf-model.repo=<org>/<model>` |

Dots inside a key become `-`. To see the keys of a run, read the names under `tasks.global` in a
task's `cmeta-task-cached-ctx.json`, or run with `-v`.

**Aim at the key the pipeline actually sets up.** `program/llama-cpp` sets up `clang` and `clang-cpp`,
so `--use.llvm.version=...` changes nothing there. A version given through `--use` also enters the
cache identity of that sub-task, so it gets its own cache entry and the default one stays.

## Running the same words elsewhere: `--on`

Docker/Podman instances have their own cMeta engine, home, index and local tool cache. Selected
recipe repositories are live bind mounts of the caller's filesystem, not duplicate clones: ordinary
edits are visible on both sides without a sync operation. `--on_repos=a,b` selects those repositories;
the default is the public AOps repository. The caller's whole `local` repository and repositories
flagged `secrets` are not mounted. Configured data repositories can also be shared (`--on_data=none`
disables them); individual state/result artifacts can be shared with `--on_artifacts`.
There is no automatic whole-CMETA copy or bisync. Windows Python environments/tool binaries are not
reused as Linux tools; the image's engine resolves its own tools and cache.

Protected state subpaths can use `--on_artifacts.state.storage=volume` together with
`--on_artifacts.state.cref=state::local:my-app/volumes/app`; the host retains an ownership registration,
and the files physically live in a Linux engine volume. See the resolver guide for backup/lifecycle.
With no `--on`, execution stays local unless an artifact's `on:` block supplies a route.
`--on=here` forces local execution. A template requires its engine prefix, such as `docker:ubuntu`,
`podman:debian` or `wsl:ubuntu`; a bare name denotes an existing host artifact.

`--on=<host>` on any `cx task run` / `cx program run` / `cx tool setup` / `cx app run` hands the whole
command line, as typed, to a host and returns its result:

```bash
cx program run test-nmm-c-cpu cpu -q --on=docker            # an instance of the container template ubuntu on this machine's docker, made on first use
cx program run test-nmm-c-cpu cpu -q --on=docker:debian     # another template; --on=podman[:<template>] the same with podman
cx program run test-nmm-nvcc-cuda cuda -q --on=docker --on_template.cuda_flavour=devel   # the template's CUDA overlay (the GPU through the engine)
cx task run test-python -q --on=wsl                          # a WSL distribution made from the same template (Windows)
cx tool setup gcc --install -q --on=lab-thinkpad-ubuntu      # a fleet host (cx host ls); a Windows host needs "access: shell: powershell"
cx task run test-python --on=docker --on_template.os_version=24.04 --on_repos=ctuninglabs@cmeta-aops,my-repo
```

How it works (`v2.py`, `_run_on`): the outermost task of a command line started from the CLI sees the word,
resolves the host - a host artifact, `get-host--docker` for `docker` / `podman`, `get-host--wsl` for `wsl`
(`--on_instance`, `--on_repos`, `--on_data`, `--on_arch`, `--on_new_host`, `--on_refresh_cmeta` (the image's uv and
cMeta built again, a newer release) and `--on_template.<key>` go to them; the compute word of the run picks the
template's overlay when it has one: `cuda`, `rocm`) - and runs
`CMETA_ON=here cx <the words minus --on and --on_*>` there through `cx host run`, quoted for the host's
shell (POSIX, or PowerShell). The inner run never delegates again. `-q` and `-v` travel as typed; a terminal
here is a terminal there (`ssh -t`, `docker exec -it`), so the inner run asks its questions as a local run
would, and a run without one (a script) stays without one. The result is the inner exit code plus `run_on`
(host, words, engine, image, whether the instance was made now, the terminal, the data repositories), also
in `ctx['on']`; the inner run's provenance and repro records carry `run_on` too (host, from, engine, image;
`cx program provenance --as_flags` adds `--on=<host>`); one closing line says where it ran and how to open
a shell there. An instance's cMeta home and cache are its own, never the machine's; the repositories mounted
into it are the machine's, live. `--on_pull` makes the run work in `~/work/<run id>` there (its repro records,
what `--save_here` writes) and brings that folder back into `on-runs/<run id>` here; `--on_rm` makes a
throwaway instance for the run and destroys it after. `--on_detach` keeps the run going there after the command
returns - a server: it runs in a session of its own, its output in `~/cmeta-detached/<run id>.log`, its process group
in the `.pid` file next to it, and the closing line says how to read the output and how to stop it; `--on_ports=8080`
(or `8080:80`, comma-separated) publishes ports of a new instance on 127.0.0.1 (a container cannot publish a port later:
an instance made without it says so):

```text
cx tool run python --on=docker --on_instance=web --on_ports=8765 --on_detach -- -m http.server 8765
cx host run web "tail -n 50 ~/cmeta-detached/<run id>.log"            # what it prints
cx host run web "kill -- -$(cat ~/cmeta-detached/<run id>.pid)"      # stop it
```

POSIX hosts and instances only for now (a Windows host refuses `--on_detach`). Started from a terminal on a
Windows machine, a detached run asks for no terminal: its words reach the host on stdin, from a temporary script,
where cmd.exe cannot strip their quotes (a run that keeps its terminal gets a quoted command base64-encoded). A coding
agent on another machine is the same: `cxt run-ai --project=<cRef> --new -q "<request>" --on=<host> --on_detach` - the
project named by its cRef resolves there, and its records come back with the project's sync.

For an interactive terminal that can be reattached after a disconnect, use GNU Screen:

```console
cxt run-ai --project="work::my-project" --on=my-host --on_screen
cxt run-ai --project="work::another-project" --on=my-host --on_screen=another-task
```

The bare flag uses the command's artifact alias as the screen name (`run-ai` here). Repeating the same name
reattaches to the existing command without submitting its prompt again; its original window title shows the
project. Use different names for independent tasks. Closing SSH leaves the remote task running; quitting the
harness normally lets run-ai finish and closes the screen. A later launch follows run-ai's usual conversation
rules. `--on_screen` requires a client terminal and a POSIX target with GNU Screen, detected or installed through
the cMeta tool. It cannot be combined with `--on_detach`, `--on_pull`, `--on_rm` or `--on_isolated`.

Docker templates can declare `instance_artifacts` to bind individual host cache/result roots, or a run
can select them with `--on_artifacts.state=result::local:my-application-state`. A writable result is
created when absent; the container sees it at `<home>/artifacts/state` and receives its reference,
inside/host paths, mode and source OS in `CMETA_ARTIFACT_MOUNTS`. The host's entire local repository
remains private. This supports durable application data shared between native and container execution
without keeping that data in the container's writable layer. Mounts persist in recreation arguments;
an existing instance refuses changed mount selections. Existing instances without artifact mounts keep
their previous mounts. See [get-host--docker](../../task/get-host--docker/README.md) for declarations
and filesystem requirements.

An ssh host runs the words on its own clones and home. `--on_isolated` runs them on THIS machine's repositories
instead (`ctuninglabs@cmeta-aops`, or `--on_isolated=<repo>,<repo>`): they are copied to `~/cmeta-tests/on-<run id>`,
a throwaway cMeta home there plugs them, the run uses it (the host's own engine, its own home untouched) and the
folder goes afterwards (`--on_keep` keeps it). A repository flagged `secrets: true` never leaves this machine.

An artifact can carry its own route, so that no word is needed - a task's `_desc.yaml`, or a program's (the
program category hands it to the task):

```yaml
'on':                           # quoted: YAML 1.1 reads a bare on as the boolean true
  requires_os: [linux]          # the pipeline needs a Linux userland (test-sglang, OpenShell, TGI)
  windows: docker:sglang        # the route on a Windows machine (an instance of the stack template sglang)
  darwin: docker:sglang         # and on a Mac
  default: docker:vllm-cuda     # the route everywhere when the command line names none (a stable stack image)
```

The real ones: test-sglang (Linux only: Windows and macOS go into the SGLang stack, whose compute variant follows
the run's `--compute`) and test-vllm (Linux and macOS natively, Windows into the ubuntu template's instance).

The OS's own route wins, else `default`; nothing happens when this OS satisfies `requires_os` and no route is
forced for it; an OS that is not allowed and has no route stops the run with the options. `--on=here` on the
command line keeps a run local whatever the block says; `--on=<ref>` wins over it.

Instances are kept and managed by the host category: `cx host ls --made`, `cx host snapshot <instance>
[--name=..]` (docker: a committed image; WSL: an exported tar) and `cx host restore <instance> [--name=..]`,
`cx host push / pull <instance> ...` (docker cp, or cp through wsl.exe), `cx host destroy <instance>`. A
test-on-hosts round takes instance refs in `--hosts` (`docker:ubuntu,docker:debian,wsl`): the matrix of OS
images runs on the carriers that have an engine, with the tree where the instance mounts it.

## Data repositories: models and datasets apart from the tools

A data task says where its entries belong with `cache_repo_key` in its `_desc.yaml` (`get-hf-model` and
`get-hf-dataset`: `data`); a caller can say it for a generic step in the `uses` entry (`cache_repo_key: data`
on a `download-file` or `clone-git-to-cache` step). The key is resolved through `cache_repos` of
`config::task` - `cx config set task --meta.cache_repos.data=my-models` after `cx repo init my-models
--path=D:\models` - or for one run with `--use.init.cache_repos.data=my-models`; an explicit `--cache_repo`
or the run-wide `default_cache_repo` still wins. Nothing set: the entries stay in `local`, as before. A lookup
spans every plugged repository, so an entry is found wherever it lives.

With `--on`, every repository of `cache_repos` is mounted into the instance under `$HOME/data/<alias>` and
plugged there, the config inside gets the same keys (`--on_data=data,models` restricts the set,
`--on_data=data=my-models` names one without the config key, `--on_data=none` mounts nothing), and after the
run each data repository is indexed here again: a model fetched inside lands where one fetched here does,
and the entry made on one OS is reused on another (the cached result's paths are rewritten to the entry's
current place at reuse). The tools of a run never go there: each environment keeps its own.

## Two reuse layers

- **In-memory memo (per run):** `store_global: True` + `storage_key: <key>`. A later
  task asking for the same key gets the stored result instantly. `setup` forces
  `storage_key: "{{$params.name}}"` so `python` is set up once; `init`/`runner`/`host`
  pin fixed keys.
- **On-disk cache (across runs):** `cache: True` stores result + built/downloaded files
  in a `cache`-category entry, matched semantically by tags + params:
  - `cache_params:` — identity params; `@key` = fuzzy/conditional version match;
    `{{...}}` entries are templated.
  - `cache_extra_params:` / `cache_extra_tags:` / `cache_extra_alias:` — templated extras.
  - `cache_features:` — softer match to disambiguate multiple entries.
  - `cache_name:` — force an explicit entry name.
  - CLI: `--update` (rebuild), `--clean` (wipe), `--new` (fresh entry), `--path=<dir>`
    (distinct path = distinct entry). Unfinished entries carry a `tmp` tag; the
    `check_versions` config re-detects a cached tool's version and invalidates stale ones.
    `--update` rebuilds an entry from what is installed; upgrading the *tool* itself is
    `cx tool setup <tool> --upgrade` (see [tool-abstraction.md](tool-abstraction.md)),
    which switches `update` on for its run so the entry records the new version.
  - A reused tool entry is completed from the tool's *current* `_desc.yaml`: `task/setup`
    lays the declarative `features` block of the meta (the `all` / host-OS / `linux` block the
    detection also starts from) under the cached features in `finish_dynamic_result`, so a key
    the meta gained after the entry was cached (a compiler flag, for example) is there on every
    use without `--update`; what was detected keeps its value, and the entry's files are not
    rewritten — they stay the record of what was detected.
  - Files in an entry: `cmeta-task-cached-result.json`, `cmeta-task-cached-ctx.json`
    (and `cmeta-task-saved-*.json` with `--save`), and `cmeta-task-running.json` while an
    attempt runs (who, since when, for which request).

## The cache entry of a run (since cmeta-aops 0.45.0, cMeta 0.34.2)

An entry is in one of five **states**, derived from its tags, its files and the lock of its
folder - nothing to configure (`cx cache show` prints them, `cx cache classify` is the API):

| state | what it means | served as a result? | a matching request |
|---|---|---|---|
| `ok` | result with `return 0`, recorded paths present | yes | uses it |
| `running` | the folder's lock is held: another process builds it | no | waits for it, then uses its result |
| `crashed` | the `tmp` tag of an attempt whose process is gone | no | resumes it in place |
| `failed` | the last attempt ended with an error (`failed` tag, the error in the result file) | no | resumes it in place |
| `broken` | the result file cannot be read, or is missing from an entry the task engine made (its request record or ctx file is there), or the recorded `tool_path` / `git_path` is gone | no | resumes it in place |

(A cache artifact that never carries a result - a program's build workspace, a folder used as storage - is
`ok`: nothing of the states applies to it and `clean` leaves it alone.)

The rules, in the order the engine applies them:

- **A retry of the same configuration resumes the same entry.** A heavy task (a 1 GB
  download and a 10 GB build) that fails is restarted *in its entry*: the download is
  there, the attempt counts up. "The same configuration" = the parameters the request was
  made with (`request_params`, recorded in the entry at its creation) and the same `--path`.
  A request with another configuration - a different version, or none where the failed
  attempt had one - gets its **own, new entry**; the failed one stays, resumable by its own
  configuration, until `cx cache clean --failed`. Nothing of a failed attempt leaks into
  another request. (Entries made before the record existed are matched by the parameter
  subset rule of before.)
- **The request drives a resumed run.** The task gets the request's parameters; at the end
  the entry's `params` are **replaced** by them (plus what the task reports in
  `_update_params`), never merged with the old ones. A task that wants to check what it
  resumes reads `ctx['tasks']['run_control']['cache_resumed']` (`state`, the entry's old
  `params`); whether the content of the entry is still right for the request (is the source
  tree complete, is it the right version) is the task's business.
- **`failed` is an attempt, not a result.** A cached failure is never returned to a later
  request; the request resumes the entry and the task runs again.
- **Identical requests at once make one entry.** The find-then-create of the lookup runs
  under the lock of the cache repository's category folder (`<repo>/cache.lock`, held for
  milliseconds); the attempt holds the lock of its entry's folder (`<entry>.lock`, the same
  lock a `delete` of the folder takes) from the choice of the entry until its result and
  tags are written. A second identical request finds the entry `running`, waits for it (a
  notice after 3 s naming the process; up to `CMETA_CACHE_WAIT_TIMEOUT` seconds, 86400) and
  then uses its result. A different configuration does not wait: it makes its own entry.
- **The result before the tags.** A successful attempt writes its result and ctx files
  (atomically) *first*, then clears the `tmp` / `failed` tags: no entry is ever "finished"
  without its result. A failed attempt writes its result (the error) and sets `failed`. A
  killed process leaves `tmp` and the running file: the entry is `crashed` and resumable; its
  lock died with the process.
- **Nothing is deleted on its own.** `cx cache clean` removes the crashed entries by default
  and takes `--failed`, `--broken`, `--unfinished` (all three) and `--all --force`; a running
  entry is never removed: `clean` skips it, and `cx cache delete` of it waits for the attempt
  (`CMETA_LOCK_TIMEOUT`, 30 s) and fails as a whole while it goes on - record and folder stay.
- `--update` and `--clean` rebuild the selected usable entry in place, as before, as an
  attempt under its lock (the explicit overwrite); `--new` makes a fresh entry.

### Several usable entries: which one a request takes

A request often matches more than one usable entry: three versions of a tool, the same version
built for two targets. They are offered in this order, and a quiet run (`-q`) takes the first:

1. the task's own `sort_keys` (`_desc.yaml`), or by default the highest version
   (`@cmeta.params.version-`), then the lowest `priority`, then the `path`;
2. the entry's `sort` value, when it has one;
3. **the time of creation, the newest first** (`creation_timestamp` of the entry's meta);
4. the alias, then the UID.

Step 3 is what makes the choice the same on every machine. Two entries that are equal on steps 1
and 2 - a second entry made with `--new`, the two entries that identical requests at once made
before 0.45 - used to fall to their aliases, which end in a random UID: one machine took the older
entry, the next one the newer. Now the entry made last is taken everywhere; an entry without a
time of creation comes after the ones that have one.

When the time of creation decided, a quiet run says so in one line:

```text
NOTE: 2 cache entries have the same version, priority, path: the newest is used - task--setup--jq--5f0c..., made 2026-10-12T10:07:10+00:00
```

and a run that asks adds "(entries with the same version, priority, path are listed newest first)"
to its question. Without the console (`--con-`, the API) nothing is printed. `cx cache show
--duplicates` lists the usable entries that no request can tell apart, group by group, and `cx
cache clean --duplicates` keeps the newest of each group (cMeta 0.35.1 and later).

What a resumed attempt finds in its entry, for the three things most entries hold:

- **A download** (`task/download-file`). A file gets its name only when it is complete: the
  engine compares what arrived with the size the server announced, so a transfer that the
  network cuts is an error, and a checksum (`md5sum`), when the tool gives one, is compared
  before the name is given. Until then the bytes are in `<name>.download` in the working
  directory, with a small record next to it (`<name>.download.resume`: the URL, the file's
  ETag or date on the server, its size). The next attempt asks only for the rest, with an HTTP
  range request that the server answers only if the file is still the same one; it starts
  over when that cannot be guaranteed (no record, another URL or mirror, a server without
  ranges or validators, a file that changed). The partial file lives outside `directory`
  because the tools ask for a clean `directory` on every attempt. An archive is downloaded
  again when the run was stopped while unpacking it (the unpacked tree and the archive are
  in that folder). `--resume-` starts every download at its first byte.
- **A folder named by the request** (`--path`, the venv path of a python). cMeta records a
  folder under the name the request gave it and resolves no link: a venv made at
  `<link>/venv` is found again at `<link>/venv`, whatever disk the link points to today.
  The same folder named by another path (its physical path, a second link) is another name
  and gets its own entry. Tasks that report a path from the current directory use
  `folder_as_named()` of the task API for it (`os.getcwd()` is the physical path on Linux
  and macOS).
- **A question.** A run without a terminal (a detached job, `nohup`, CI) cannot be asked
  anything: a question is then an error that names the flag which answers it in advance
  (`-q`, `--install`, `--build`, `--update`, `--skip_size_check`, `-f`), the attempt ends
  `failed`, and the same request with the flag resumes it. No answer is ever made up. Tasks
  ask through `ask()` of the task API, never through `input()`.

## `CTask` hooks (`api_v1.py`)

> For the calling convention, the dict **return contract** and **error handling**
> (`self.cm.catch_error`, soft error `16`, `fail16=True`), see
> [python-api.md](python-api.md).

`InitCTask` (`category/task/api/ctask.py`) is the tiny base. Concrete tasks override,
all optional; the engine calls each if present, in order:
`uses_before_init → init → uses → cache → uses2 → run → cache write → finish_dynamic_result`.

- `init(ctx, params)` → may `{'skip_run':True}`, inject `{'uses':[...]}`, override
  `{'storage_key':...}`.
- `check_params(ctx, params, cparams)` → validate; may `{'stop':True}`.
- `run(ctx, **params)` → the work. Special result keys: `_aggregate` (merged into
  `aggregated`, e.g. `{'env':{'+PATH':[...]}}`), `_update_params` (added to cache
  identity), `add_to_local`; `_impact` timings added for you.
- `finish_dynamic_result(ctx, result, params)` → post-process **even cached/memoized**
  results (do PATH/env injection here so it survives caching).
- `customize_cache_artifact(...)` → shape cache alias/tags/params before lookup.

Import: `from task_c36be4b9314a45e0.api.ctask import InitCTask` (the **category** UID —
identical in every task's api code). Command-function naming: `run(self, ctx, foo="")`
→ typed kwargs + `ctx`; a single-`params`-dict form (`foo`/`foo__`, trailing `__`
stripped from the CLI name) is used where the signature is dynamic.

The same module holds the two helpers every task uses instead of the Python built-ins:
`ask(question, how, optional=False)` for a question to the person who runs the command
(`{'return': 0, 'answer': ...}`, or an error that names `how` - the flag that makes the
question unnecessary - when there is no terminal; `optional=True` for a pause, which is
then skipped), and `folder_as_named(named, base)` for the current directory under the
name the request gave it (see "The cache entry of a run").

It also holds `MAX_PROMPT_ARG_CHARS`, `prompt_via_file()` and
`prompt_via_file_done()`: a task that must hand a program a long text as a command
line argument (the agent tasks' interactive sessions, `opencode run`, `openclaw agent`)
writes it to a file above that length and passes a one-line request to read it
first — see [agent-tasks.md](agent-tasks.md#flags-shared-by-run-claude--run-codex--run-opencode--run-agy--run-gemini--run-hermes).

## Bootstrap chain & key building-block tasks

| Task | UID | Role |
|------|-----|------|
| `init`   | `ee7466d402654266` | loads `config,task`; fixed global key `init`; no cache |
| `runner` | `1e48cc0c5f6041a5` | `uses: host`; fixed key `runner` |
| `host`   | `96ac7118439c4490` | detects OS/arch/bits, package manager, per-OS var table (`file_ext_*`, `cmd_sep`, `os_sep`), seeds `aggregated.env`; fixed key `host` |
| `setup`  | `a2f9b61079ce4333` | detect/install/build any tool (delegates to `tool` artifacts) — see [tool-abstraction.md](tool-abstraction.md) |
| `cmd`    | `c9ba0a88df394d7f` | the command runner (`utils.sys.run` with merged env; `capture_output=False`+no-timeout ⇒ interactive) |
| `target` | `94decb2ddd28441f` | the **compute** selector — see [program-and-compute.md](program-and-compute.md) |
| `download-file` | `03fed13e2e0447cf` | fetch a file/archive into the cache |

`cx task run test-python` = `uses: [runner, setup name=python]` → `runner` pulls `host`
→ `host` pulls `init`. The second time anything asks for `python`, the global memo
short-circuits before cache is even touched — yet `finish_dynamic_result` still
re-injects PATH so downstream `cmd` tasks stay correct.

## Authoring a task

Use the **`add-task`** skill (`.claude/skills/add-task/`). In short: scaffold with
`cx task add ctuninglabs@cmeta-aops:<name> --yaml`, fix the copyright, write `_desc.yaml`
(clone the nearest sibling), add `api_v1.py` only if you need imperative logic, then
`cx task index <ref>` (or `cx --reindex`). Verify pipeline-only tasks with a real run
(a safe passthrough), not `--info`.
