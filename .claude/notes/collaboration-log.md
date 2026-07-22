<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.
Proprietary and confidential.

Working log for AI agents / collaborators on cmeta-aops. Append newest entries at the
top. This is a resume-point, not user-facing docs — the polished findings live in
docs/cmeta-aops/. Keep it factual and current.
-->

# cmeta-aops — collaboration log

## Orientation for a fresh session

1. Read `AGENTS.md` (repo brief) and `CLAUDE.md`, then `__symlinks/cmeta/AGENTS.md`
   (engine internals).
2. Read `docs/cmeta-aops/` — the distilled understanding of `task`, `tool`, `program`
   and the `compute` abstraction (built over the sessions logged below).
3. Skills available in `.claude/skills/`: **`add-tool`**, **`add-task`** (use these to
   author artifacts; they encode the scaffolding + gotchas).
4. Dispatch is `cx <category> <command>`; incremental index = `cx <cat> index
   ctuninglabs@cmeta-aops:<alias>`; full = `cx --reindex`. A `_desc.yaml`-only edit
   needs **no** reindex.

## Established facts / conventions (verified in-session)

- **Copyright header** for new files: `Copyright (C) 2025-2026 Grigori Fursin and
  cTuning Labs. All rights reserved.` + proprietary block. `cx <cat> add` scaffolds a
  *different* auto-copyright — fix it to match siblings.
- **`cx <cat> add`** on an existing folder says "already exists" and does NOT index;
  use **`cx <cat> index <ref>`** to register a hand-authored folder.
- **Reindex after editing a MATCHED `_cmeta.json` field** (verified with add-program):
  `cx <cat> add` indexes immediately with the initial meta; editing `_cmeta.json`
  afterwards (e.g. `constraints.supported_compute`) is NOT picked up by the incremental
  `cx <cat> index` ("already exists") — the stale meta stays in the index and match-based
  selection fails at run time. Run a full **`cx --reindex`**. (A `_desc.yaml`/`src` edit
  needs no reindex; and editing an unmatched field like `copyright` is harmless.)
- **`program` first-build prompts + is slow**: when several compilers match `lang-<lang>`,
  the `compiler` task calls `input()` to pick one → `EOFError` in non-interactive shells.
  Pass **`--quiet`** (auto-pick 0), `--con` (answer), or pin the compiler. The first CPU
  build sets up a toolchain and can take minutes; later runs reuse the cache.
- **`--info`** only shows help for tasks that have `api_v1.py`; a pure-`_desc.yaml` task
  *executes* instead. Verify pipeline-only artifacts with a safe real run (e.g.
  `-- --version`), not `--info`.
- **`cmd` interactivity**: `capture_output=False` + no timeout ⇒ `subprocess.run`
  inherits the terminal (`__symlinks/cmeta/cmeta/utils/sys.py`). CLI args to a wrapped
  tool must arrive as `unparsed` (`{{params.unparsed|$None}}`) since cMeta consumes
  parsed args.
- **`qpath_bin` is quoted** (e.g. `"C:\Program Files\nodejs"`); do NOT do
  `{{...qpath_bin}}/npm` (breaks on spaces). Prefer bare `npm` with the node-js dep set
  up via `add_tool_path_to_env: True`.
- **npm-shim tools on Windows** are `X.cmd`, not `X.exe` — list both in `names:`.
- **Version listing**: setup `--versions` parses `cmd_get_versions` output **per line,
  first regex match only** — so npm's 3-per-line columns drop versions; use
  `npm view <pkg> versions --json` (one per line). Anchor GitHub-tag regexes tightly to
  skip junk tag schemes.
- **`install_cmd_version`** fires only when `--version=X` is passed AND that version
  isn't already detected; `{{simple_version}}` is used for exact versions (fuzzy ranges
  fall back to `install_cmd`). Read the real installer to confirm it accepts a version.
- **YAML gotcha**: an unquoted scalar containing `word:` (colon-space) parses as a
  mapping — use a `|` block scalar for multi-line `install_help_text` etc.

## Session history

### Session 3 (2026-07-21) — `program` deep dive + documentation + README + add-program skill
- Rewrote the main **`README.md`** to be user-friendly: goals, link to the cMeta
  framework (https://github.com/cTuningLabs/cmeta, homepage https://cTuning.ai), basic
  ideas behind `tool`/`task`/`program`/`cache`, quick start, and a link to
  `docs/cmeta-aops/`. Kept badges + verbatim license. Reproducibility framed as
  "improved, not solved" (per project policy).
- Wrote skill **`.claude/skills/add-program/`** (authoring a program: inherit a template,
  set `constraints.supported_compute`, patch `updates`, `CProgram` hooks; worked example
  `test-hello-c-cpu`).
- **Dogfooded add-program end-to-end**: created **`program/test-hello-c-cpu/`** (kept as a
  clean minimal worked example — `_cmeta.json` + `_desc.yaml` inheriting `template-c-cpu`
  + `src/program.c`). Verified `cx program run test-hello-c-cpu cpu --quiet` →
  `Hello, world!` and `finish-run` collected `tmp-cmeta-program-stats.json`
  (`{"hello":"world"}`). Fixed two skill gaps found via dogfooding: the `--reindex`-after-
  `_cmeta`-edit gotcha and the `--quiet` compiler-selection requirement.

- Studied `category/program` (delegator: run→`compile-and-run-program`, compile, clean,
  `update_desc_` patcher), `template-c-cpu`, concrete programs (`test-nmm-c-cpu`,
  `test-nmm-nvcc-cuda`, `lib-xopenme`, `build-pytorch`, `build-llama-cpp`,
  `cbench-automotive-susan`), and the tasks `select-program`, `target` (+`target--cuda`,
  `target--android-cpu`), `compiler`, `setup-compile`, `setup-run`; compiler tool
  `features.flags` (e.g. `tool/gcc`).
- Deep dives written up in `docs/cmeta-aops/program-and-compute.md`: (A) repro-context
  recompile caching (`_repro_ctx_{all,compile,run}.json`), (B) Android-CPU remote exec,
  (C) `updates_cmd` multi-command programs, (D) `build-*` vs template.
- **Created `docs/cmeta-aops/`** doc set (README + task-engine + tool-abstraction +
  program-and-compute), linked from the main `README.md`. Fixed `docs/cmeta-aops/
  _cmeta.json` copyright to match siblings.

### Session 2 (2026-07-20) — `tool` work + `add-task` skill
- Created task **`run-claude`** (`task/run-claude/`, UID `e5d500ebc094460f`): setup
  `claude` tool + run interactively via `cmd` with `unparsed` passthrough.
- Wrote skill **`.claude/skills/add-task/`**; dogfooded end-to-end (built+ran+removed a
  throwaway `demo-python-version`).
- Added GitHub/npm **version listing** to tools `claude` (anthropics/claude-code),
  `codex` (openai/codex, `rust-v` regex), and completed **`openclaw`** (npm package:
  registry versions, npm-shim detection, cross-platform `npm install -g` install,
  `extra_paths` for npm global bin). openclaw is a real npm AI CLI (openclaw.ai).
- Added **`install_cmd_version`** (specific `--version` install) to `claude`, `codex`,
  `openclaw`. Verified the `--version` detect-match path without mutating installs.

### Session 1 — `tool` + `task` deep dives
- Mapped the `task` engine (`category/task/api/v2.py` orchestrator, `ctx`, `uses`
  pipelines, `store_global`/cache, `CTask` hooks) and the `tool` abstraction
  (`setup`/`cmd` delegation, detect/install/build). Captured in `docs/cmeta-aops/
  {task-engine,tool-abstraction}.md`.

## Open threads / TODO (not yet done)
- Optionally fold the YAML `key:`-colon and npm-shim gotchas into the `add-tool` skill's
  gotchas section.
- Optionally add an `openclaw` `test.bat` mirroring sibling tools.
- Nothing has been committed to git this collaboration — stage/commit on request.
- A real versioned install (to prove the `install_cmd_version` branch end-to-end) was
  deliberately NOT run (would overwrite a global CLI); do it only on explicit go-ahead.
