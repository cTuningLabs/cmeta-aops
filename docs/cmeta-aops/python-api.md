<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
-->

# The cMeta Python API inside cmeta-aops artifacts

How the artifacts in this repository call cMeta from Python: the single
`access()` dispatch surface, what an artifact's hook code is handed, the
dictionary return contract, and how errors — including the "not found" soft
error — are handled here in practice.

> **Engine vs. content.** The API itself is defined by the **cMeta framework**
> (the Apache-2.0 `cmeta` package). This page documents how *this* repository
> uses it and the conventions that hold across its artifacts. For the framework
> reference, see the engine docs linked in [§8](#8-engine-reference-docs).

At the time of writing this repository contains **142 `api_v1.py` hook files**
making **124 `access()` calls** and **287 error checks** — so the patterns below
are the ones you will actually meet when reading the code.

---

## 1. One function for everything

There is a single entry point. Everything — running a task, setting up a tool,
finding an artifact, reading a config, touching the cache — goes through it:

```python
r = cm.access({'category': 'task', 'command': 'run', 'arg1': 'clone-git-to-cache'})
```

The dict is the whole call: `category` and `command` select what runs, and every
other key is an argument. The CLI is the same surface with different syntax —
`cx task run clone-git-to-cache` builds the same dict. Anything you can do from
the shell you can do from Python, and vice versa.

Inside artifact code you never construct a `CMeta` instance; the engine hands you
one as **`self.cm`**:

```python
result = self.cm.access(p)
if self.cm.catch_error(result): return result
```

From a standalone script outside an artifact, create one:

```python
from cmeta import CMeta

cm = CMeta()
r = cm.access({'category': 'repo', 'command': 'list'})
if cm.catch_error(r): return r
```

### Referencing other categories — never hard-code an alias

Artifacts and categories are addressed by **`alias,UID`**, where the UID is
authoritative. That makes references survive renames. Category code declares its
cross-category dependencies in `_cmeta.*` under `uses_categories:` and
dereferences them at run time:

```python
uses_categories = self.cmeta['uses_categories']

p = {'category': uses_categories['cache'],       # not the literal string 'cache'
     'command': 'find',
     ...}
r = self.cm.access(p)
```

Writing `'category': 'cache'` happens to work today and breaks the moment
anything is renamed or a second category shares the alias. Use the dereference.

---

## 2. Where Python lives in this repository

Two places, and they are not the same thing:

| File | Role |
|---|---|
| `category/<name>/api/v1.py` (and `v2.py`) | **Category** implementation — the commands a whole category exposes. `category/task/api/v2.py` is the workflow engine itself. |
| `<category>/<alias>/api_v1.py` | **Artifact** hooks — optional per-artifact Python that customises one task, tool or program. |

Most artifacts have **no Python at all**: a declarative `_desc.yaml` pipeline is
enough. Add `api_v1.py` only when the declarative form cannot express what you
need. See [task-engine.md](task-engine.md) for where hooks fit in the lifecycle.

### The base class import is UID-based

An artifact's hook class inherits from a base shipped by its category, imported
through a **UID-qualified module name** that the engine registers at run time:

```python
from task_c36be4b9314a45e0.api.ctask import InitCTask       # task category
from tool_c393ba5c6fa14f66.api.ctool import InitCTool       # tool category
from program_22788f3c30d04e6d.api.cprogram import InitCProgram
```

That `task_c36be4b9314a45e0` is `task` + its category UID. It looks odd but it is
the rename-safe form — copy it verbatim from a sibling artifact rather than
inventing it.

### The skeleton

```python
"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx, **params):
        ...
        return {'return': 0}
```

Passing `module_file_path = __file__` is required — the base class derives the
artifact's paths and its logger name from it.

---

## 3. What `self` gives you

From `InitCTask.__init__` (`category/task/api/ctask.py`):

| Attribute | What it is |
|---|---|
| `self.cm` | The `CMeta` instance — `access()`, `catch_error()`, `utils`, `debug`, `logger`. |
| `self.cmeta` | The artifact's own metadata, including `uses_categories`. |
| `self.logger` | A child logger named after the artifact; use instead of `print()` for diagnostics. |
| `self.module_file_path` | Absolute path to this `api_v1.py`. |
| `self.module_path` | Directory holding it (i.e. `api/` for category code). |
| `self.path` | The artifact directory. |
| `self.module_name` / `self.task_module_name` | Module identifiers used for logging and dynamic import. |

Guard verbose logging on the engine's debug flag:

```python
if self.cm.debug:
    self.logger.debug("RUNNING TASK clone-git-to-cache run")
```

---

## 4. The `ctx` dictionary

Every hook receives **`ctx`**, the context threaded through all nested
`access()` calls. Two branches carry almost everything:

**`ctx['control']`** — how the run should behave:

```python
con     = ctx['control'].get('con', False)      # console output allowed
quiet   = ctx['control'].get('quiet', False)    # suppress prompts, auto-pick
verbose = ctx['control'].get('verbose', False)  # full nested trace (-j)
```

**`ctx['tasks']`** — the workflow state:

| Key | Contents |
|---|---|
| `global` | Per-run memo shared across the whole pipeline (this is where `store_global` results land). |
| `local` | Per-task scratch. |
| `aggregated` | Accumulated environment/paths from sub-tasks. |
| `params` | Resolved parameters for the current task. |
| `cparams` | Cache-relevant parameters. |
| `run_control` | `clean`, `update`, `new`, `cache`, `work_dir`, `cur_dir`, `task_path`, … |
| `nested_call` | Current nesting depth — used for indenting trace output. |

`ctx` is also the documented place to thread your own state through nested calls
(agent session ids, budgets, traces). Framework keys are reserved; namespace
anything you add, e.g. `ctx['agent']`.

---

## 5. The `CTask` hook surface

The engine calls these if present, in this order (`category/task/api/v2.py`).
The exact signatures matter:

| Hook | Signature | Purpose |
|---|---|---|
| `init` | `init(ctx, params)` | Early setup. Return `{'skip_run': True}` to exit before the pipeline runs. |
| `check_params` | `check_params(ctx, params, cparams)` | Validate/normalise. Return `{'stop': True}` to finish early — used for `--version`/help paths. |
| `run` | `run(ctx, **params)` | The body. Its returned dict **is** the task result. |
| `finish_dynamic_result` | `finish_dynamic_result(ctx, result, params)` | Post-process; return `{'result': ...}` to replace the result. |
| `customize_cache_artifact` | `customize_cache_artifact(*args, **params)` | Shape the cache entry this task produces. |

Note `run` is invoked as `task_api_code.run(ctx, **uparams)` — parameters arrive
as **keyword arguments**, not as a dict.

Every hook must return a dict with `return`. The engine checks each one with
`catch_error` and aborts the pipeline on failure.

A `run` result may also carry keys the engine acts on — `_aggregate` (merged into
`ctx['tasks']['aggregated']`, e.g. `{'env': {'+PATH': [...]}}`), `_update_params`
(folded into the cache identity), `add_to_local`, and `_impact` timings added for
you. [task-engine.md](task-engine.md#ctask-hooks-api_v1py) documents these and the
surrounding lifecycle in full; this page covers the calling convention and the
error contract.

### A real `run` ending

From `task/clone-git-to-cache/api_v1.py` — call out, check, enrich, return:

```python
result = self.cm.access(p)
if self.cm.catch_error(result): return result

path_to_git_repo = result['path_to_git_repo']

# Tell the cache layer what to record, so a vanished path invalidates the entry
_update_params = result.setdefault('_update_params', {})
_update_params['git_path'] = path_to_git_repo

return result
```

Returning the callee's dict directly (after enriching it) is the normal idiom —
it preserves `return`, `error` and any command-specific keys.

---

## 6. The return contract

**cMeta does not raise on failure by default.** Every call returns a dict:

| Key | Meaning |
|---|---|
| `return` | `0` on success, `> 0` on failure. Always present. |
| `error` | Human-readable message. Present when `return > 0`. |
| … | Command-specific keys on success (`artifact`, `path`, `meta`, …). |

Codes you will meet:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Generic error |
| `8` | Conflict — e.g. artifact already exists, category not found |
| **`16`** | **Soft error — "not found"**. Often a normal outcome, see §7 |
| `32` | The command does not exist in that category API |
| `99` | Internal error — an API returned a non-dict, or a dict without `return` |

On the CLI the **process exit code equals `return`**, so shell scripts and CI
branch on the same numbers Python sees.

---

## 7. Error handling in practice

### Always prefer `catch_error`

```python
r = self.cm.access(p)
if self.cm.catch_error(r): return r
```

This is the house style — **287 of the error checks in this repository use it**.
It does three things a bare `if r['return'] > 0` cannot:

1. **Raises at the point of failure when debugging is enabled**, so the traceback
   points at the call that actually failed rather than somewhere far downstream.
2. **Skips soft errors** — a `16` does *not* return here; execution continues.
3. Normalises `r['error']` so messages propagate consistently.

The bare form still appears in about 17 places and is acceptable in short,
self-contained code — but it has no debug hook and treats `16` as fatal.

### Soft errors: code 16 means "not found", which is often fine

Probing for something that may not exist is routine, so `16` is exempt from both
raising and propagation unless you opt in. That is what lets this work:

```python
r = self.cm.access({'category': 'note', 'command': 'find', 'arg1': 'my-note'})
if self.cm.catch_error(r): return r     # a 16 does NOT return — fall through
if r['return'] == 16:
    ...                                  # handle "does not exist yet"
```

### Escalating a soft error — `fail16=True`

When "not found" *is* fatal, opt in. From `task/compiler/api_v1.py`, where a
missing compiler must stop the build — and the message is improved on the way
out:

```python
r = self.cm.access(p)
if self.cm.catch_error(r, fail16=True):
    if r['return'] == 16:
        if tool_constraints:
            r['error'] += f' and constraints "{tool_constraints}"'
        r['return'] = 99
    return r
```

This is the pattern to copy when a lookup failure should abort: escalate with
`fail16=True`, then add context to `error` before returning.

### Returning a soft error — "I can't handle this, fall back"

The other half of the mechanism: your code can *produce* a `16` to decline a case
without failing the run. Tool install hooks use this to hand control back to the
declarative `install_cmd`. From `tool/bazel/api_v1.py`:

```python
if not version_simple:
    # Only exact/simple versions map to a release asset.
    # Return 16 + the original cmd so setup can fall back to install_cmd.
    return {
        'return': 16,
        'error': f'custom install for "bazel" needs an exact version in "{__file__}"',
        'install_cmd': cmd,
    }
```

The caller (`task/setup/`) checks with plain `catch_error`, so the `16` passes
through and the declarative path runs instead. `task/setup/install.py` and
`build.py` return `16` the same way when a tool has no install or build procedure.

Use `16` when *"this does not apply"* is a legitimate outcome; use `1` (or a more
specific code) when something genuinely went wrong. Always set `error` even on a
`16` — it becomes the message if a caller escalates with `fail16=True`.

### Halting at the top level

Inside a hook you *return* the error dict so the engine can unwind. Only at the
top level of a standalone script do you halt:

```python
cm.catch_error_and_halt(r)   # prints to stderr and sys.exit(r['return'])
```

Do **not** call this inside artifact hooks — it exits the process and robs the
engine of the chance to clean up and report.

### Making cMeta raise, for debugging

Set `CMETA_FAIL_ON_ERROR=yes` to turn failures into exceptions so a debugger
breaks at the origin. Related: `CMETA_DEBUG=1`, `CMETA_LOG=DEBUG`,
`CMETA_LOG_FILE=<path>`, `CMETA_VERBOSE=yes`.

---

## 8. Reusable helpers — `self.cm.utils`

Prefer the engine's helpers over hand-rolled equivalents: they are portable
across the OSes this repository targets, respect the same return contract, and
keep artifact code short. Examples in use here:

```python
self.cm.utils.common.deep_merge(a, b, append_lists=True)   # merge meta/ctx trees
self.cm.utils.common.expand_string(template, ctx_tasks)    # {{...}} substitution
self.cm.utils.names.restore_cmeta_obj(parts, key='artifact')
self.cm.utils.sys.get_api_info(api_code, 'run', label)
```

There are also `utils.files` and `utils.cli`. Reach for `self.cm.utils.*` before
`os`/`shutil`/`subprocess` — it is what makes artifact code reusable and
debuggable rather than machine-specific.

---

## 9. Engine reference docs

The framework's own documentation, in the public
[cTuningLabs/cmeta](https://github.com/cTuningLabs/cmeta) repository:

| Doc | Covers |
|---|---|
| [`docs/error-handling.md`](https://github.com/cTuningLabs/cmeta/blob/main/docs/error-handling.md) | The full error contract: return codes, `catch_error`, soft errors, CLI/CI handling in bash/batch/PowerShell, debugging in VS Code / Visual Studio / PyCharm. |
| [`docs/using-cmeta.md`](https://github.com/cTuningLabs/cmeta/blob/main/docs/using-cmeta.md) | End-to-end walkthrough: mental model, artifacts from Python and CLI, `alias`/UID resolution, the repo model, `_cmr.yaml`, configuration, adding categories and artifacts, the fast index. |
| [`docs/configuration.md`](https://github.com/cTuningLabs/cmeta/blob/main/docs/configuration.md) | Working with `config` artifacts. |
| [`docs/cplatform.md`](https://github.com/cTuningLabs/cmeta/blob/main/docs/cplatform.md) | Connecting to the cTuning.ai platform and testing its API. |
| [`AGENTS.md`](https://github.com/cTuningLabs/cmeta/blob/main/AGENTS.md) | Framework brief for AI agents: `access()` dispatch, `ctx`, resolution, reindexing, command naming, the `{'return':0}` contract. |

The engine also ships Claude Code skills under `.claude/skills/` —
`use-cmeta-python`, `use-cmeta-cli`, `add-plugin`, `add-repo` — which encode the
same conventions in a form agents pick up automatically.

Locally, the engine source and its docs are symlinked at `__symlinks/cmeta/`.

---

## 10. Checklist for artifact hook code

- [ ] Inherit the category base class via its **UID-qualified import**, copied from a sibling.
- [ ] Pass `module_file_path = __file__` to `super().__init__`.
- [ ] Every hook returns a dict containing `return`.
- [ ] Every `access()` result is checked — `if self.cm.catch_error(r): return r`.
- [ ] Deliberate decision on soft errors: fall through for "may not exist", `fail16=True` where absence is fatal.
- [ ] No `catch_error_and_halt` inside hooks.
- [ ] Other categories reached through `self.cmeta['uses_categories'][...]`, never a literal alias.
- [ ] `self.cm.utils.*` used in preference to raw `os`/`subprocess` where an equivalent exists.
- [ ] Diagnostics through `self.logger`, guarded by `self.cm.debug` when verbose.
- [ ] Apache-2.0 copyright header copied from a sibling file.
