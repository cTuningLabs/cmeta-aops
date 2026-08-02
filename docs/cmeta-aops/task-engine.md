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
  - Files in an entry: `cmeta-task-cached-result.json`, `cmeta-task-cached-ctx.json`
    (and `cmeta-task-saved-*.json` with `--save`).

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
