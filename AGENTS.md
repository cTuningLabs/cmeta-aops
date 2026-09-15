# AGENTS.md — Working context for AI agents on `cmeta-aops`

> Canonical brief for AI coding agents. Keep it short, factual and current.
> This is a **cMeta content/plugin repository**, not the engine.

## 1. What this repository is

**`cmeta-aops`** is a **cMeta content/plugin repository** for AI Operations
(AIOps): a collection of *artifacts* that install and run tools, datasets,
models and multi-step workflows in a portable, unified way across OSes and
platforms (Linux, Windows, macOS, Android; CPU/CUDA/etc.).

It is an **experimental plugin repository and prototyping playground** — the
author's accumulated R&D encoded as executable, agent-drivable workflows.
**Artifact maturity varies:** a few paths have CI coverage (`.github/workflows/`,
all `workflow_dispatch` — manually triggered, never on push), the rest are
unverified and some are exploratory probes that may not run out of the box. When
something fails, first establish which kind you are looking at before assuming a
regression.

It is **not** the engine. The engine is the **cMeta framework** (`cmeta` Python
package, CLI `cx` / `cmeta` / `cxt` / `cserver`), already pip-installed. Its
source, agent docs and skills are symlinked at **`__symlinks/cmeta/`** →
the `cmeta` package of your local cMeta checkout (created by
`_create_symlinks_for_ai_context_min.bat`). **Read `__symlinks/cmeta/AGENTS.md`
first** for engine internals (`access()` dispatch, `ctx`, resolution, reindex,
repos, command naming, return contract).

- **License:** **Apache-2.0** (`LICENSE`, `COPYRIGHT`) — the same license as the
  cMeta engine. New files get the standard Apache header; copy it from a sibling
  artifact (see §8).
  **Exception:** the vendored third-party sources listed in
  [`THIRD-PARTY.md`](THIRD-PARTY.md) are **not** Apache-2.0 and keep their own
  upstream notices verbatim — never rewrite those headers.
- **Repo identity:** `_cmr.yaml` → `ctuninglabs@cmeta-aops,3cb4ee4f444048f6`
  (category `repo`); registered with the engine via `cx repo plug .`.

## 2. How everything runs

One dispatch surface: `cx <category> <command> [args] [--flags]` (CLI) or
`cm.access({'category','command',...})` (Python). `cxt` = CLI with tracing.

```bash
cx repo plug .                 # register this repo with the engine (once)
cx <cat> index <repo>:<alias>  # register ONE hand-made artifact  \ prefer these
cx <cat> update <repo>:<alias> # refresh after a _cmeta.* meta edit/ over --reindex
cx --reindex                   # rebuild EVERY category (slow) — moves/renames, bulk pull
cx task list                   # list task artifacts (also tool/program/...)
cx tool setup git              # detect/install a tool into category cache
cx tool run git -- status      # run a set-up tool (args after --)
cx program run test-nmm-c-cpu  # compile+run a program
cx task run <alias> --info     # a task's help/params (does not execute it)
```

Flags: `-j`/`--verbose`, `--con`, `--quiet`; `--repro`/`--dump` capture
input/output/`ctx`. Skills (loaded when editing under `__symlinks/cmeta/`):
`use-cmeta-cli`, `use-cmeta-python`, `add-plugin`, `add-repo`.

## 3. Repository layout — categories and artifacts

Top-level folders are **categories**. The important ones here:

| Category | Role |
|----------|------|
| `task/`    | The workflow-engine artifacts — reusable, composable, cacheable steps. The heart of the repo (~114). |
| `tool/`    | External tools (git, cmake, clang, cuda, conda, docker, android-ndk, hf, …) — detect/install/build/run (~103). |
| `program/` | Compilable/runnable benchmark programs (matmul variants, pytorch/llama builds, polybench, …) (~31). |
| `model/`, `dataset/`, `docker/`, `skill/` | Auxiliary. **Currently stubs** — only inherit base CRUD (`api/v1.py` has just `test_`/`test2`); real behavior comes via tasks. `skill` moved here from the cMeta engine in 0.32.0 and has no artifacts yet. |

Under `category/<name>/` there are two kinds of thing:

1. **Category definition** — `category/<name>/`:
   - `_cmeta.yaml` — UID, `last_api_version`, `base_category_default_api_versions`,
     `min_cmeta_version`, and `uses_categories:` / `uses_artifacts:` (rename-safe
     `alias,UID` refs to categories/artifacts this category dispatches into).
   - `api/v1.py` (`v2.py`, …) — a `Category(InitCategory)` subclass adding/overriding
     commands; `last_api_version` selects which loads.
   - `api/c<name>.py` — an `InitC<Name>` base mixed into per-artifact API code.

2. **Artifacts** — `category/<name>/<alias>/`:
   - `_cmeta.yaml` **or** `_cmeta.json` — `artifact:` (UID), `category:` ref
     (`task,c36be4b9314a45e0`), `tags`, `constraints`, `note`.
   - `_desc.yaml` — the **automation/pipeline** (cache config, `uses`, `params_map`,
     `inherits`, `updates`, templated commands). Most behavior lives here.
   - `api_v1.py` — optional per-artifact hooks (`CTask`/`CTool`/`CProgram` class).
   - `tests/`, `*.bat`, `src/` — CLI test recipes and program sources.

**References use `alias,UID`** — when both are given the **UID is authoritative**,
so refs are rename-safe (that is why `_desc.yaml` writes `task: setup,a2f9b61079ce4333`).
New artifacts get a fresh 16-hex UID
(`python -c "import uuid; print(uuid.uuid4().hex[:16])"`); clone the nearest existing
artifact rather than authoring from scratch. Cross-category refs in code go through
`self.cmeta['uses_categories']['<name>']`, never a bare hard-coded alias.

## 4. The `task` category — the workflow engine (`category/task/api/v2.py`)

`task` is API v2. `run()` is a ~1700-line orchestrator; in order it:

1. **Selects** the task artifact by `arg1`/`--tags`, loads its `_desc.yaml` (`cdesc`)
   and `api_v1.py` (`CTask` class).
2. Applies **`params_map`** (positional `arg2/arg3/...` and short flags → named
   params, incl. dotted paths into `use`/`ctx`/nested dicts).
3. Runs **`uses_before_init` → `api.init()` → `uses` → cache resolution → `uses2` →
   `api.run()` → cache write → `api.finish_dynamic_result()`**.
4. Threads a shared **`ctx`** through nested calls; `ctx['tasks']` holds `global`,
   `local`, `params`, `aggregated`, `nested_call`, `use`.

Key `_desc.yaml` keys for tasks:
- `uses:` / `uses_before_init:` / `uses2:` — **sub-task pipelines**. Each entry is a
  dict with `task: <alias>,<UID>` (dispatch `task run`) or `internal_func: <name>`
  (call a hook on this task's api code), plus params. Conditions/modifiers: `if:`
  (safe expr over `ctx['tasks']`), `if_os:`/`if_os_id:`/`skip_if_not_win`/
  `fail_if_not_os`, `_update`, `local`, `set_env` (accumulates into `aggregated.env`
  for later steps), `reuse_all_params`.
- `store_global` + `storage_key` — memoize a task's result in `ctx` for the run so a
  dependency (e.g. setting up a tool) resolves once.
- `params_map`, `preserve_global_keys`, plus the **cache** keys (§6).

### Per-artifact hooks (`api_v1.py`, `CTask` class)

The engine calls these if present: `init(ctx, params)` (may `skip_run`, add `uses`,
set `storage_key`), `check_params(ctx, params, cparams)` (may `stop`),
`run(ctx, **params)` (main body → result dict), `finish_dynamic_result(...)`
(post-process even cached results), `customize_cache_artifact(...)`. Return contract
everywhere: `{'return':0, ...}` on success, `{'return':>0, 'error':...}` on failure;
check with `self.cm.catch_error(r)`. Note `16` is a **soft "not found"** that
`catch_error` deliberately lets through — pass `fail16=True` when absence should be
fatal. Command-function naming (engine convention):
`foo_` → typed kwargs + `ctx`; `foo`/`foo__` → single `params` dict (trailing `__`
stripped from the CLI name).

**Before writing any `api_v1.py`, read [`docs/cmeta-aops/python-api.md`](docs/cmeta-aops/python-api.md)** —
the `access()` dispatch, `self.cm`/`ctx`, hook signatures, the return contract and
error handling, with the repo's real idioms.

## 5. `tool` and `program` — thin delegators

- **`tool` (`category/tool/api/v1.py`)**: `setup`/`run` re-dispatch into `task`.
  `tool setup X` → task `setup,a2f9b61079ce4333 --name=X`; `tool run X -- <args>`
  sets X up then runs task `cmd,c9ba0a88df394d7f` (dynamic-lib paths folded into
  `env['+PATH'/'+LD_LIBRARY_PATH'/...]`). A **tool artifact's `_desc.yaml`** describes
  detection/install: `names:`, `match_version:`/`cmd_get_version:`,
  `install_cmd:`/`install_cmd_version:` (per OS, templated with `{{global....}}`),
  `extra_paths:`, `requires_sudo:`.
- **Install strategy — always work down this ladder** (details and worked
  examples in the `add-tool` skill, §1):
  1. **Download a prebuilt binary** (`curl`-style, via task
     `download-file,03fed13e2e0447cf` from an `install()` hook). Preferred: pins
     an exact version, checksum-verifiable, **no privileges**, works in a bare
     container, identical on every host.
  2. **Non-sudo system package manager** — `winget` (Windows, present by
     default) or `brew` (macOS/Linux), via declarative `install_cmd:`.
  3. **Sudo/system package manager** — apt/dnf/apk/pacman/zypper/… via
     `{{global.host.os_extra.install_cmd_sudo}}` + `requires_sudo:`. Last
     resort: needs root and gives whatever version the distro ships.

  Combine them: Tier 1 primary, returning `{'return':16, 'install_cmd': cmd}`
  when it can't apply so `setup` falls through to the declarative command.
  **Never depend on a package manager that is not itself a cMeta `tool`** — only
  `tool/winget` and `tool/brew` exist, so anything else (chocolatey, scoop, …)
  would be an undetectable host dependency. Fetch such a mirror's artifact over
  plain HTTPS as a Tier-1 download instead of depending on its client.
- **`program` (`category/program/api/v1.py`)**: `run` → task
  `compile-and-run-program,05437a1aae224270`; `compile` = run with `skip_run`;
  `clean` removes all `tmp*` dirs across programs. A **program artifact's `_desc.yaml`**
  uses `inherits: [template-...]` + `updates:` to patch the inherited `uses` pipeline
  (match a sub-task by `task:`/`internal_func:`, then `update`/`append`/`prepend`/
  `substitute`). Programs pull compilers/libs **by tag** via `setup` sub-tasks gated
  with `if:`/`if_os:`.

## 6. Category cache — how installs/downloads are reused

Tasks with `cache: True` store their result and downloaded/built files in **`cache`
category entries** (`cx cache show|clean|delete`), found **semantically** by tags +
match-params, so multiple versions coexist and are reused across runs. `_desc.yaml`
keys: `cache_params:` (identity params; `@key` = fuzzy/conditional version match),
`cache_extra_params:`/`cache_extra_tags:`/`cache_extra_alias:` (templated extra
identity), `cache_features:` (softer match to pick among entries),
`cache_name`/`cache_repo`. CLI: `--update` (rebuild entry), `--clean`, `--new`
(force fresh entry), `--cache_repo=<repo>`, `--path=<dir>` (a distinct path = a
distinct entry). Unfinished entries are tagged `tmp` and reused/cleaned. Result/ctx
files inside an entry: `cmeta-task-cached-result.json`, `cmeta-task-cached-ctx.json`
(and `cmeta-task-saved-*.json` with `--save`).

## 7. Testing

Two layers:

- **Basic pytest smoke tests** (`tests/basic_tests/`) — hermetic checks of engine
  wiring, category/artifact resolution, `_desc.yaml`/`_cmeta.*` integrity, `--info`,
  and a couple of offline task runs. They create their own temporary `CMETA_HOME`
  and plug this repo, so they never touch your global cMeta state or the network.
  Run with:

  ```bash
  uv run python -m pytest tests          # or: uv run python -m pytest tests -q
  ```

  `uv` reads the root `pyproject.toml` (deps: `pytest` + `cmeta` from the
  `__symlinks/cmeta` path source), so the symlink must exist first (run
  `_create_symlinks_for_ai_context_min.bat` on Windows). Without uv:
  `python -m pytest tests` works when `cmeta` and `pytest` are already importable.

- **CLI recipes** — per-artifact `test*.bat` / `test*.py` and `tests/` folders of
  real `cx`/`cxt` invocations that hit the network/cache/toolchain. Many use Windows
  paths / drive letters — adapt before running. CI (`.github/workflows/*.yml`,
  `workflow_dispatch`) clones the framework, `pip install .[all]`,
  `cx repo plug .`, then runs `cx task ...` recipes on
  `{ubuntu,windows,macos} × py{3.9,3.14}`. To verify a real change, run the relevant
  recipe locally.

## 8. Conventions

- **Copyright headers are load-bearing** — copy the Apache header from a sibling
  file into any new `.py`. Never rewrite the upstream notices on the vendored
  third-party sources listed in [`THIRD-PARTY.md`](THIRD-PARTY.md); if you vendor
  new third-party code, keep its header verbatim and add it to that file.
  **See §8.1 for the full attribution rule.**
- **Don't touch author scratch/backup files.** Common untracked siblings:
  `*.yaml2`/`*.yaml3`, `*.py2`, `*.arc1`/`*.arc2`, `tmp*/` dirs,
  `cmeta-task-saved-*.json`. These are manual backups / work outputs — don't edit,
  rename, commit, or treat as authoritative.
- Reference artifacts/categories by `alias,UID`; cross-category code deps via
  `uses_categories:`.
- After hand-editing an artifact's `_cmeta.*` **meta**, refresh the index with the
  narrowest command: `cx <cat> index <repo>:<artifact>` to register a hand-made
  folder, `cx <cat> update <repo>:<artifact>` after a meta edit. `cx --reindex`
  rebuilds every category and is slow — keep it for moves/renames, bulk `git
  pull`, or a wiped `CMETA_HOME`. Payload-only edits (`api/`, `src/`,
  `_desc.yaml`) need no reindex at all.
- Python 3.9–3.14; keep engine runtime deps out of artifact code.

### 8.0 Git workflow — sign-off, branch naming, PR titles

These rules hold for **every** commit, branch and pull request here, including
those an AI agent creates on the author's behalf:

- **Sign off every commit: `git commit -s -m "…"`.** The `-s`/`--signoff` flag
  appends the DCO `Signed-off-by:` line certifying the Developer Certificate of
  Origin 1.1 (see [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [`DCO`](DCO)
  file). A DCO check runs on every pull request and an unsigned commit blocks the
  merge. If one slipped through, repair it *before* pushing:
  `git commit --amend -s --no-edit` for the last commit, or
  `git rebase --signoff <base>` for a range.
- **Name PR branches `YYYYMMDD-<short-branch-name>`.** Creation date first, then
  a short kebab-case topic — e.g. `20260808-add-ripgrep-tool`,
  `20260808-fix-task-cache-key`. The date prefix keeps branches chronologically
  sortable and makes a pile of open PRs analyzable. Always branch before
  committing; don't push work directly to the default branch.
- **Prefix the PR title the same way: `YYYYMMDD - <Title of PR>`.** The date, a
  spaced hyphen, then the normal human-readable title — e.g.
  `20260808 - Add a tool artifact for ripgrep`. This is the subject line visible
  on GitHub, so the same date ordering that helps on branches also helps when
  scanning or scripting over the PR list (`gh pr create --title "20260808 - …"`,
  `gh pr list`). Use the same date as the branch prefix — the day the work was
  branched, not the day it merges.

### 8.1 Attribution, provenance and citation

`cmeta-aops` is Apache-2.0, created and developed by **Grigori Fursin** and
**cTuning Labs**. This applies to work done by AI agents and LLM-based tools
exactly as it does to work done by people. See [`NOTICE`](NOTICE),
[`COPYRIGHT`](COPYRIGHT), [`LICENSE`](LICENSE), [`CITATION.cff`](CITATION.cff)
and — for the parts that are *not* Apache-2.0 —
[`THIRD-PARTY.md`](THIRD-PARTY.md).

When you generate, modify or move code, metadata or scripts in this project:

- **Never remove or rewrite an existing copyright header or attribution.** If you
  split a module, carry its header into the new file. If you move an artifact,
  keep its `authors` / `copyright` fields intact.
- **New source files** get the standard header:

  ```python
  """
  Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

  Licensed under the Apache License, Version 2.0.
  See the COPYRIGHT and LICENSE files in the project root for details.
  """
  ```

- **New artifacts and categories** record provenance in their `_cmeta.*`:

  ```yaml
  authors: '[Grigori Fursin](https://cTuning.ai/@gfursin)'
  copyright: 2025-2026 Grigori Fursin and cTuning Labs. See the COPYRIGHT and
    LICENSE files in the project root for details.
  ```

  In a **downstream** repo, set `authors` / `copyright` to that repo's own owner
  instead — but keep any cmeta-aops-derived material's original notices.

- **Reusing this content elsewhere.** Apache-2.0 §4 requires retaining the
  copyright, patent, trademark and attribution notices and reproducing the
  `NOTICE` file contents in the distribution. That obligation covers metadata
  (`_cmeta.*`), automation pipelines (`_desc.yaml`) and scripts as well as code,
  and **is not waived because the copying was done by an agent rather than a
  person**.

- **Citing.** If the work is research, or reuses the *concepts* (portable
  artifact recipes behind one uniform interface, the tool/task/program
  abstraction, the compute-target model, content-addressed caching), please cite
  the project — [`CITATION.cff`](CITATION.cff) carries the machine-readable
  citation. This is a **request, not a licence condition**. Citation and
  collaboration are actively welcomed: https://cTuning.ai/@gfursin

## 9. Pointers

- **Python API in artifacts** (dispatch, hooks, return contract, error handling):
  [`docs/cmeta-aops/python-api.md`](docs/cmeta-aops/python-api.md)
- Engine brief + concepts: `__symlinks/cmeta/AGENTS.md`, `.../CLAUDE.md`
- Engine reference docs (public): <https://github.com/cTuningLabs/cmeta> —
  [`using-cmeta.md`](https://github.com/cTuningLabs/cmeta/blob/main/docs/using-cmeta.md),
  [`error-handling.md`](https://github.com/cTuningLabs/cmeta/blob/main/docs/error-handling.md)
- Worked task (cache + uses): `task/clone-git-to-cache/_desc.yaml`
- Central tool-setup task: `task/setup/` · run/compile driver: `task/compile-and-run-program/`
- Program template pattern: `program/test-nmm-c-cpu/_desc.yaml`
- Tool detection pattern: `tool/git/_desc.yaml`
- Basic tests: `tests/basic_tests/`
