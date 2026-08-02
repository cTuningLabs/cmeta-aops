# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

**See `AGENTS.md` for the canonical brief** — what this repo is (an Apache-2.0
**cMeta content/plugin repository** for AIOps, not the engine), the
category/artifact layout, the `task` workflow engine, `tool`/`program` delegation,
the category cache, testing, and conventions. This file adds Claude-specific notes
only.

## Orient yourself first

- This repo runs on the **cMeta framework** (engine), which is pip-installed and
  symlinked at `__symlinks/cmeta/`. Read `__symlinks/cmeta/AGENTS.md` for engine
  internals (`access()` dispatch, `ctx`, `alias,UID` resolution, `--reindex`, repos,
  command-function naming, `{'return':0}` contract) before changing behavior.
- Everything funnels through one surface: `cx <category> <command>` (CLI) /
  `cm.access({'category','command',...})` (Python). Extend via
  categories / tasks / `api_v1.py` hooks — not side entry points.
- **This is an experimental prototyping repository** — artifact maturity varies and
  many components are exploratory (see [Project status](README.md#project-status)).
  When something does not run, first work out whether it is a regression or an
  artifact that never worked on this platform.

## Where to read next

| Need | Read |
|------|------|
| Writing any `api_v1.py` | [`docs/cmeta-aops/python-api.md`](docs/cmeta-aops/python-api.md) — `access()`, `self.cm`/`ctx`, hook signatures, return contract, error handling (`catch_error`, soft `16`, `fail16`) |
| Adding a tool / task / program | the skills in [`.claude/skills/`](.claude/skills/) — `add-tool`, `add-task`, `add-program` |
| How the workflow engine executes | [`docs/cmeta-aops/task-engine.md`](docs/cmeta-aops/task-engine.md) |
| Compute targets, compilers, builds | [`docs/cmeta-aops/program-and-compute.md`](docs/cmeta-aops/program-and-compute.md) |
| Licensing before touching vendored source | [`THIRD-PARTY.md`](THIRD-PARTY.md) |
| Attribution / provenance / citation rules | [`NOTICE`](NOTICE), [`AGENTS.md` §8.1](AGENTS.md), [`llms.txt`](llms.txt) |

## The shape to internalize

- Top-level folders are **categories**; artifacts live at `category/<name>/<alias>/`
  as `_cmeta.yaml|json` (+ `_desc.yaml` automation, optional `api_v1.py` hooks).
- `task/` is the workflow engine (API v2, `category/task/api/v2.py`): `uses`
  pipelines, `store_global`/`storage_key`, `params_map`, and the
  `init`/`check_params`/`run`/`finish_dynamic_result`/`customize_cache_artifact`
  hook surface. `tool/` and `program/` are thin delegators into `task`.
- Reference artifacts by `alias,UID` (UID is authoritative → rename-safe). Cross-category
  code deps go through `self.cmeta['uses_categories']['<name>']`.

## Working here

- Run the tests with `uv run python -m pytest tests` (see `AGENTS.md` §7). They are
  hermetic — own temporary `CMETA_HOME`, no network.
- After hand-editing an artifact's `_cmeta.*` meta, use the narrowest reindex:
  `cx <cat> index <ref>` for a hand-made folder, `cx <cat> update <ref>` after a
  meta edit. `cx --reindex` is slow — reserve it for moves/renames and bulk
  `git pull`. Payload-only edits need no reindex.
- This repo is **Apache-2.0**, like the cMeta engine. Copy the Apache copyright
  header from a sibling file into new files, and **never strip or rewrite an
  existing attribution** — carry it into split/moved files. Work you do as an agent
  carries the same obligations as work done by a person; see `AGENTS.md` §8.1.
- **Never rewrite the upstream headers** on the vendored third-party sources
  listed in `THIRD-PARTY.md` — some carry terms more restrictive than Apache-2.0
  (SUSAN is research-only and must not be sold; `lib-milepost` is GPL).
- Leave the author's scratch/backup siblings alone (`*.yaml2`, `*.py2`, `*.arc1`,
  `tmp*/`, `cmeta-task-saved-*.json`) — don't edit, rename, or commit them.
