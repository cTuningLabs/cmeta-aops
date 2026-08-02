<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
-->

# cmeta-aops — architecture & internals

Developer/agent documentation for the **`cmeta-aops`** content repository: what the
artifacts are, how the `task` workflow engine executes them, how `tool` and `program`
delegate into it, and how the **`compute`** abstraction ties compilers, libraries and
targets together across OSes (Linux / Windows / macOS / Android; CPU / CUDA / …).

> This documents the *content repo*, **not** the engine. The engine (the `cmeta`
> Python package, CLI `cx`) is pip-installed and symlinked at `__symlinks/cmeta/`;
> read `__symlinks/cmeta/AGENTS.md` for engine internals. See the repo-root
> `AGENTS.md` for the short canonical brief.
>
> The engine is open source and its reference docs are public:
> [cTuningLabs/cmeta](https://github.com/cTuningLabs/cmeta) — in particular
> [`docs/using-cmeta.md`](https://github.com/cTuningLabs/cmeta/blob/main/docs/using-cmeta.md)
> and [`docs/error-handling.md`](https://github.com/cTuningLabs/cmeta/blob/main/docs/error-handling.md).

## Contents

| Doc | Topic |
|-----|-------|
| [python-api.md](python-api.md) | **The cMeta Python API in artifacts** — the single `access()` dispatch, what hook code is handed (`self.cm`, `ctx`), the `CTask` hook signatures, the dict **return contract**, and **error handling** (`catch_error`, soft error `16`, `fail16`). Start here before writing any `api_v1.py`. |
| [task-engine.md](task-engine.md) | The `task` category — the workflow engine: `run()` lifecycle, `uses` pipelines, `ctx`, `store_global`/cache, `CTask` hooks. |
| [tool-abstraction.md](tool-abstraction.md) | The `tool` category — detect / install / build / run an external CLI portably; version listing; `install_cmd_version`. |
| [program-and-compute.md](program-and-compute.md) | The `program` category — template inheritance, the **compute** abstraction, the compile/run task machinery, libraries, and 4 deep dives (repro-cache recompile, Android remote exec, `updates_cmd`, `build-*` vs template). |

## One-paragraph mental model

Everything funnels through a single dispatch surface — `cx <category> <command>`
(CLI) / `cm.access({'category','command',...})` (Python). Top-level folders are
**categories**; artifacts live at `category/<name>/<alias>/` as `_cmeta.yaml|json`
(identity) + `_desc.yaml` (declarative automation) + optional `api_v1.py` (hooks).
The **`task`** category is the workflow engine; **`tool`** and **`program`** are
thin delegators into it. Artifacts reference each other by `alias,UID` (UID is
authoritative → rename-safe). A shared **`ctx`** dict is threaded through every
nested call, carrying `global` (per-run memo), `local` (per-task), `aggregated`
(accumulated env), and `params`.

## The three layers

```
        cx tool run X            cx program run P cpu
             │                          │
   ┌─────────▼─────────┐      ┌─────────▼──────────────────┐
   │  tool  (delegator)│      │  program (delegator)       │
   │  setup + cmd      │      │  compile-and-run-program   │
   └─────────┬─────────┘      └─────────┬──────────────────┘
             │                          │
   ┌─────────▼──────────────────────────▼─────────────────┐
   │                    task  (engine)                     │
   │  select_artifact → uses_before_init → init → uses →   │
   │  cache → uses2 → run → cache write → finish_dynamic   │
   │  shared ctx['tasks']: global / local / aggregated     │
   └───────────────────────────────────────────────────────┘
             │  builds on / pulls in
   ┌─────────▼─────────┐   ┌──────────────┐   ┌────────────┐
   │  cache  category  │   │ config/utils │   │ dataset/…  │
   └───────────────────┘   └──────────────┘   └────────────┘
```

## Quick command reference

```bash
cx repo plug .                      # register this repo with the engine (once)
cx <cat> index <repo>:<alias>       # register ONE hand-authored artifact  (prefer)
cx <cat> update <repo>:<alias>      # refresh after editing an artifact's _cmeta.* meta
cx --reindex                        # rebuild EVERY category — slow; moves/renames, bulk pull

cx task run <alias> [--info]        # run a task (or show its run() help)
cx tool setup <name> [--version=X]  # detect/install a tool into the category cache
cx tool setup <name> --versions     # list available versions (from GitHub/npm)
cx tool run <name> -- <args>        # set up then run a tool (args after --)
cx program run <name> <compute>     # compile + run a program for a compute target
cx program compile <name> <compute> # compile only (skip_run)
cx program clean                    # remove all tmp*/ dirs across programs

# Global flags: -j/--verbose (full nested trace), --con, --quiet, --install,
#               --update / --clean / --new (cache control), --save.
```

## Conventions (load-bearing)

- **Apache-2.0 copyright headers** are copied from a sibling file into new files.
  The vendored third-party sources in [`THIRD-PARTY.md`](../../THIRD-PARTY.md) are the
  exception — keep their upstream notices verbatim and never relicense them.
- Reference artifacts/categories by **`alias,UID`**; cross-category code deps go through
  `self.cmeta['uses_categories']['<name>']`, never a hard-coded alias.
- After editing an artifact's `_cmeta.*` meta, refresh the index with the narrowest
  command — `cx <cat> index <ref>` for a hand-made folder, `cx <cat> update <ref>`
  after a meta edit. `cx --reindex` rebuilds every category and is slow; keep it for
  moves/renames and bulk `git pull`. A **`_desc.yaml`-only** edit needs no reindex.
  (One documented exception: editing `_cmeta.json` *after* `cx program add` already
  indexed it — see the [`add-program`](../../.claude/skills/add-program/SKILL.md)
  skill.)
- Leave author scratch/backup siblings alone: `*.yaml2`, `*.py2`, `*.arc1`, `tmp*/`,
  `cmeta-task-saved-*.json`.
