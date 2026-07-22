---
name: add-task
description: Add a new cMeta `task` artifact (the workflow-engine unit) under `task/<name>/` — a composable, cacheable step built from a declarative `_desc.yaml` pipeline (`uses` sub-tasks, `params_map`, `store_global`/`storage_key`, cache keys) plus an optional `api_v1.py` (`CTask` hooks: `init`/`check_params`/`run`/`finish_dynamic_result`/`customize_cache_artifact`). Use when the user asks to "add a task", "create a workflow/pipeline", "make a task that sets up tool X and runs it", or "wrap steps so `cx task run <name>` works". Worked example: run-claude (setup the `claude` tool + run it interactively).
---

# add-task — author a cMeta `task` workflow artifact

A **task** artifact lives at `task/<name>/` and is one reusable, composable,
**cacheable** step of the cMeta workflow engine (category `task,c36be4b9314a45e0`,
API v2, orchestrator `category/task/api/v2.py`). Everything higher-level delegates
into tasks: `cx tool setup/run` → task `setup`/`cmd`; `cx program run` → task
`compile-and-run-program`. You compose tasks by having one task's `_desc.yaml`
list others under `uses:`.

Authoring a task = writing up to two files under `task/<name>/`:

| File | Role | Required? |
|------|------|-----------|
| `_desc.yaml` | The **declarative pipeline** — `uses` sub-tasks, `params_map`, cache + `store_global` config, templated commands. Most tasks are *only* this. | **Yes** |
| `api_v1.py`  | Optional `CTask` hooks for imperative logic (`run`, `init`, …) that YAML can't express. | Only when you need real Python |

(`_cmeta.yaml` — identity/UID — is scaffolded for you; see §2.)

> **Read first:** `AGENTS.md` (§4 task engine), and these worked artifacts:
> `task/test-python/_desc.yaml` (trivial `uses` chain), `task/setup/`
> (central detect/install/build), `task/cmd/` (command runner),
> `task/clone-git-to-cache/_desc.yaml` (cache keys), `task/host/api_v1.py`
> (a pure-Python task). `cx task run <x> --info` shows a task's `run` help.

---

## 1. Decide the shape first — do you need `api_v1.py`?

This choice determines whether you write Python at all.

- **A. Pure pipeline (`_desc.yaml` only)** — the task is a sequence of existing
  sub-tasks (set up a tool, run a command, clone a repo, …) wired with
  templating and conditions. **Most tasks are this.** Examples:
  `task/test-python`, `task/test-claude`, `task/run-claude`, `task/cmd`,
  `task/setup-run`.
- **B. Pipeline + `api_v1.py`** — you need imperative work: inspect/transform
  results, compute params, loop, parse output, decide control flow. Add a
  `CTask` class with a `run()` (and optionally `init`/`check_params`/…).
  Examples: `task/host` (detects OS), `task/setup` (orchestrates install),
  `task/compile-and-run-program` (the program driver).

Both still live under `task/<name>/`; B just adds one file.

---

## 2. Scaffold the artifact

**Qualify the target repo.** A bare `cx task add <name>` lands in the default
`local` repo, **not** this content repo. Prefix with the repo alias (from
`_cmr.yaml` → `ctuninglabs@cmeta-aops`):

```bash
cx task add ctuninglabs@cmeta-aops:run-claude --yaml   # writes task/run-claude/_cmeta.yaml (fresh UID, category: task,c36be4b9314a45e0)
```

`--yaml` matches the siblings (which use `_cmeta.yaml`); omit for `_cmeta.json`.
The generated `copyright:` may differ from siblings — fix it to
`Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.`

Fastest correct route: **clone the nearest existing task** and edit. Copy a
`_desc.yaml` whose shape matches your intent (e.g. `task/test-claude/` for
"setup a tool then run it").

If you hand-author the folder yourself (copying files rather than using
`cx task add`), the new artifact is on disk but **not yet in the index**. Two
ways to register it:

- **Incremental (preferred for one artifact):** `cx task index ctuninglabs@cmeta-aops:<name>`
  — picks up the existing `_cmeta.*`/tags already on disk and adds just that
  entry to the index (base `create_` with `index=True`).
- **Full:** `cx --reindex` — rebuilds the whole fast index.

> Note: `cx task add <ref>` on an **existing** folder reports "artifact already
> exists" and does **not** index it — use `cx task index <ref>` for that.
> A `_desc.yaml`-**only** edit needs **no** reindex (the index tracks
> `_cmeta.*` identity/tags, not `_desc` content). Reindex only after changing
> `_cmeta.*`, moving/creating folders, or adding tags.

**Copyright headers are load-bearing.** Keep the `authors:`/`copyright:` lines
atop `_desc.yaml`; copy the verbatim proprietary block into any `.py`. Don't relicense.

---

## 3. `_desc.yaml` — the pipeline

Minimal shape (a task that sets up `python` then reports it — like `test-python`):

```yaml
authors: Grigori Fursin
copyright: Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.

uses:
  - task: runner,1e48cc0c5f6041a5      # bootstrap host (OS/env/vars) — usually already in global
  - task: setup,a2f9b61079ce4333       # detect/install a tool
    name: python
```

### 3a. Sub-task pipelines — `uses` / `uses_before_init` / `uses2`

Each is a list of dicts resolved by the engine's `use_()`. An entry dispatches
**either** a sub-task **or** an internal function:

- `task: <alias>,<UID>` — recurse into `task run` (reference by `alias,UID`,
  UID authoritative → rename-safe). Extra keys become that sub-task's params.
- `internal_func: <name>` — call a method on **this** task's `api_v1.py`
  (or, with `internal_func_from_local_key`/`_from_global_key`, on api code
  stored in ctx). `internal_func_safe: True` = don't error if missing.

Which list to use:
- `uses_before_init:` — runs **before** `api.init()` (set up prerequisites that
  `init` needs; e.g. `setup` pulls in `runner` here).
- `uses:` — the main dependency pipeline (after `init`, before cache + `run`).
- `uses2:` — runs **after** the cache dir is chosen, right before `api.run()`;
  reuses `local` context (used for lightweight finalizers like a `cmd`).

Per-entry modifiers (all optional):
- Conditions: `if: '"{{global.host.os.uname}}"=="windows"'` (safe expr over
  `ctx['tasks']`), `if_os: linux,darwin`, `if_os_id: ubuntu`, `fail_if_not_os: True`,
  `skip_if_not_win: True`.
- `set_env: {KEY: val, +PATH: [dir]}` — accumulate into `ctx.tasks.aggregated.env`
  for later steps (a downstream `cmd` consumes it).
- `_update: '{{...}}'` — deep-merge a computed dict into this entry at runtime.
- `local: {...}` — merge into the task-local context.
- `reuse_all_params: True` — fold the parent task's params into this sub-task.
- Per-entry `store_global` / `storage_key` / `cache` overrides.
- All values are templated against `ctx['tasks']` (see 3d).

### 3b. Params — `params_map`

Map CLI positionals/short flags to named params the task/sub-tasks read:

```yaml
params_map:
  arg2: name        # first positional after the task name -> params.name
  arg3: compute
```

Dotted targets write into nested dicts / `use.*` / `ctx.*`
(e.g. `arg2: use.setup.version`). To pass raw CLI args **through to a wrapped
CLI**, don't map them — use the `unparsed` passthrough (see §6): cMeta consumes
parsed args, so a wrapped tool needs everything after `--`.

### 3c. Reuse — `store_global` / `storage_key` and the cache

Two independent reuse layers:

- **In-memory memo (per run):** `store_global: True` + `storage_key: <key>` makes
  the result reusable within the run — a later task asking for the same key gets
  the stored result instantly. `setup` forces `storage_key: "{{$params.name}}"`
  so `python` is set up once; `init`/`runner`/`host` pin fixed keys.
- **On-disk cache (across runs):** `cache: True` stores the result + built/
  downloaded files in a `cache` entry, matched semantically by tags + params:
  - `cache_params:` — identity params. `@key` = fuzzy/conditional version match;
    `{{...}}` entries are templated. (e.g. `setup` uses `name`, `@version`, `tool_path`.)
  - `cache_extra_params:` / `cache_extra_tags:` / `cache_extra_alias:` — templated
    extra identity/labels.
  - `cache_features:` — softer match to disambiguate multiple entries.
  - `cache_name:` — force an explicit entry name.
  - CLI: `--update` (rebuild), `--clean` (wipe), `--new` (force fresh entry),
    `--cache_repo=<repo>`, `--path=<dir>` (distinct path = distinct entry).

  Set `cache: False` for tasks with side effects you never want memoized on disk
  (most `run`/launch tasks). `preserve_global_keys: [compiler, lib-*]` snapshots
  and restores matching global keys around the task (glob-aware) to keep it atomic.

### 3d. Templating

Values are expanded against `ctx['tasks']`:
- `{{global.<key>...}}` — global context (e.g. `{{global.host.os.uname}}`,
  `{{global.claude.qpath}}` = quoted path to a tool set up earlier).
- `{{params.<x>}}` — this task's params. Default after `|`:
  `{{params.version|}}` (empty), `{{params.compute|$None}}` (Python `None`),
  `{{params.p|How computer works?}}` (literal). `$$` = UID form.
- Shortcuts inside sub-task entries: `{{os_sep}}`, `{{os_pathsep}}`,
  `{{file_ext_bat}}`, `{{cmd_new_line}}`, `{{task_artifact_path}}`.

---

## 4. `api_v1.py` — `CTask` hooks (Strategy B)

Subclass `CTask` and implement only the hooks you need. The orchestrator calls
each if present, in this order: `uses_before_init` → **`init`** → `uses` →
cache → `uses2` → **`run`** → cache write → **`finish_dynamic_result`**.

```python
"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask   # category UID, same in every task's api_v1.py

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,          # cMeta context (docstring/signature shows in `--info`)
            my_param: str = "",
    ):
        con     = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        _global     = ctx['tasks']['global']       # host, runner, set-up tools, ...
        _local      = ctx['tasks']['local']        # scoped to this invocation
        _aggregated = ctx['tasks']['aggregated']   # e.g. aggregated['env'] for cmd

        # ... do work ...

        return {'return': 0, 'my_result': 42}
```

Hook surface (all optional):
- `init(ctx, params)` → may `{'skip_run': True}` (early exit), inject `{'uses': [...]}`,
  or override `{'storage_key': ...}`.
- `check_params(ctx, params, cparams)` → validate; may `{'stop': True}` to finish
  early (e.g. print versions and stop).
- `run(ctx, **params)` → the work → result dict. Special result keys the engine
  acts on: `_aggregate` (merged into `ctx.tasks.aggregated`, e.g.
  `{'env':{'+PATH':[...]}}`), `_update_params` (added to cache identity),
  `add_to_local`; `_impact` timings are added for you.
- `finish_dynamic_result(ctx, result, params)` → post-process **even cached/memoized**
  results (runs on reuse too — do PATH injection etc. here so it survives caching).
- `customize_cache_artifact(...)` → shape cache alias/tags/params before lookup.

**Return contract (everywhere):** `{'return':0, ...}` ok; `{'return':>0, 'error':...}`
fail; `{'return':16}` = soft "not found/not handled". Check peer calls with
`self.cm.catch_error(r)` (`fail16=True` to also treat 16 as error). Cross-category
calls go through `self.cmeta['uses_categories']['<name>']`, never a hard-coded alias.

**Command-function naming** (engine convention): `run(self, ctx, foo="")` → typed
kwargs + `ctx`; a single-`params`-dict form (`foo`/`foo__`, trailing `__` stripped
from the CLI name) is used where the signature is dynamic.

---

## 5. Common building-block sub-tasks (reference by `alias,UID`)

| Task | UID | Use for |
|------|-----|---------|
| `runner`  | `1e48cc0c5f6041a5` | bootstrap host/env (add first in most pipelines) |
| `host`    | `96ac7118439c4490` | OS/arch/vars detection (pulled in by `runner`) |
| `setup`   | `a2f9b61079ce4333` | detect/install/build a tool: `name: <tool>` |
| `cmd`     | `c9ba0a88df394d7f` | run a shell command (see §6) |
| `download-file` | `03fed13e2e0447cf` | fetch a file/archive into the cache |
| `clone-git` / `clone-git-to-cache` | `…` | git clone |
| `target`  | `94decb2ddd28441f` | select compute target (cpu/cuda/…) |
| `print-text` | `…` | print / pause |

Look up a UID with `cx task find <alias>` or read the sibling's `_cmeta.*`.

---

## 6. Worked example — `run-claude` (set up a tool + run it interactively)

Goal: set up the `claude` CLI tool, then launch it **interactively**, passing any
extra CLI flags straight through.

Key facts this relies on:
- The `cmd` task runs `utils.sys.run` with `capture_output=False` and no timeout,
  so `subprocess.run` **inherits the terminal** → fully interactive. Just run the
  binary with no `-p`/`--print`.
- cMeta consumes parsed args, so user CLI flags must arrive as `unparsed`
  (everything after `--`); the `cmd` task quotes and appends them.

### `task/run-claude/_cmeta.yaml`
```yaml
artifact: e5d500ebc094460f      # fresh 16-hex UID (python -c "import uuid;print(uuid.uuid4().hex[:16])")
authors: Grigori Fursin
category: task,c36be4b9314a45e0
copyright: Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.
tags:
  - run
  - claude
  - ai
  - cli
  - interactive
note: Set up the "claude" tool and run it interactively via CLI.
```

### `task/run-claude/_desc.yaml`
```yaml
authors: Grigori Fursin
copyright: Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.

uses:
  # Bootstrap host (OS detection, env, vars) - normally already resolved from global
  - task: runner,1e48cc0c5f6041a5

  # Detect / install the "claude" tool and expose {{global.claude.qpath}}
  - task: setup,a2f9b61079ce4333
    name: claude,383841b240c74e88

  # Launch claude interactively (no -p / --print => interactive TUI).
  # Anything after "--" on the cx command line arrives as "unparsed" and is
  # quoted and appended straight to the claude CLI.
  - task: cmd,c9ba0a88df394d7f
    cmd: '{{global.claude.qpath}}'
    unparsed: '{{params.unparsed|$None}}'
```

No `api_v1.py` needed. To later expose named flags (`--resume`, `--model`) as
first-class params, add a `CTask` with a `run` signature (§4).

---

## 7. Index, test, verify

```bash
cx task index ctuninglabs@cmeta-aops:run-claude   # register the hand-authored folder (or `cx --reindex`)
cx task find run-claude                            # confirm it resolves to task/run-claude in THIS repo

cx task run run-claude -- --version                # passthrough check: RUN ... claude.exe --version
cx task run run-claude                             # real interactive launch (needs a TTY)
```

Verifying without side effects:
- `cx task run <name> --info` prints the `run` docstring/signature **only if the
  task has `api_v1.py`** (the info branch needs api code to introspect). For a
  pure-`_desc.yaml` task, `--info` does **not** short-circuit — it **executes**
  the pipeline. So for pipeline-only tasks, verify with a safe passthrough
  (like `-- --version`) rather than `--info`.
- `-j`/`--verbose` prints the full nested trace (which sub-tasks reused global,
  which hit cache, the resolved `RUN:` command).
- `--con` for real interactive prompts; `--quiet`/`--install` to auto-proceed in
  non-interactive shells (CI, agents) where `input()` would raise `EOFError`.

Add a `test.bat` mirroring siblings if the task warrants a CLI recipe.

---

## 8. Checklist / gotchas

- [ ] Created/registered with the **repo-qualified** name
      (`cx task add|index ctuninglabs@cmeta-aops:<name>`), not a bare form (which lands in `local`).
- [ ] Fixed the auto-generated `copyright:` in `_cmeta.*` to match siblings.
- [ ] Sub-tasks referenced by `alias,UID` (UID authoritative); looked up real UIDs with `cx task find`.
- [ ] Chose the right list: `uses_before_init` (before `init`) vs `uses` (main) vs `uses2` (post-cache, pre-run).
- [ ] Set `cache: False` for launch/side-effecting tasks; used `store_global`/`storage_key` only for true "resolve-once" deps.
- [ ] Templating defaults correct: `{{x|}}` empty vs `{{x|$None}}` Python-None.
- [ ] Passing args to a wrapped CLI → used `unparsed: '{{params.unparsed|$None}}'` (args after `--`), not `params_map`.
- [ ] Strategy B: `api_v1.py` imports `from task_c36be4b9314a45e0.api.ctask import InitCTask` (the **category** UID — identical in every task's api code).
- [ ] Strategy B: honored the return contract (`{'return':0}` / `>0` / `16`); did PATH/env reuse in `finish_dynamic_result` so it survives caching.
- [ ] Ran `cx task index <ref>` (or `cx --reindex`) after adding the folder / changing `_cmeta.*`; a `_desc.yaml`-only edit needs neither.
- [ ] Verified with a real run (safe passthrough, not `--info` for pipeline-only tasks); used `-j` to read the trace.
- [ ] Verbatim proprietary copyright headers preserved; didn't touch author scratch siblings (`*.yaml2`, `*.py2`, `*.arc1`, `tmp*/`, `cmeta-task-saved-*.json`).
