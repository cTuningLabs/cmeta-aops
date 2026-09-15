# Changelog

All notable changes to cMeta AOps are documented here, newest first.

## 0.32.1
- **Six generic artifacts moved in from a downstream repository** (same UIDs, so any
  existing `alias,UID` reference keeps resolving): `tool/az` + `task/run-az` (Azure CLI:
  the official prebuilt download on Windows and macOS, the package manager on Linux,
  `az login` with the terminal attached), `tool/opencode` (OpenCode.AI, the third sibling
  of `claude` and `codex`) and the prompt runners `task/run-claude2`, `task/run-codex2`,
  `task/run-opencode2` (headless or interactive; transcript and token statistics recorded
  next to the prompt file). `run-claude2` adds cMeta repositories to the agent's context
  as `--add-dir`: by default its own repository plus the aliases in the new
  `agent_add_repos` key of the local cMeta config
  (`cx config set default --meta.agent_add_repos=alias,alias`, once per machine);
  `--add_repos=<alias,alias>` adds more, `none` adds nothing. These six carry no per-file
  copyright line - the repository licence (Apache-2.0) applies. New guide:
  [`docs/cmeta-aops/agent-tasks.md`](docs/cmeta-aops/agent-tasks.md) (usage, the flags
  the three runners share, which model and reasoning effort to pass to each agent).
- **`tool/obsidian` is a real recipe.** The previous file was a copy of `tool/openclaw`
  with the name changed; Obsidian is now detected on Windows, macOS and Linux with its
  version read from the installed files, and installed with `winget`, `brew --cask` or
  the pinned AppImage (tier 1 of the install ladder on Linux).
- **Every tool, task and program carries a one-line `desc` in its `_cmeta.*`**, shown by
  the cTuning.ai catalogues (tools, tasks, programs) and available to `cx <category> list`
  without scraping `_desc.*` keys.
- **Repository version 0.32.1** (`_cmr.yaml`), released together with cMeta 0.32.1, the
  engine release it was tested with.
- **Fix: `cx tool run <tool> --versions` no longer crashes.** `setup` may stop early
  without producing a command (it only prints the available versions); `tool run` now
  returns that result instead of reading a missing `cmd`.
- **Fix: `download-file` with several URLs (mirrors).** Filenames and MD5 sums are
  matched to URLs by position; with fewer names than URLs every later mirror derives
  its own filename and skips the checksum instead of failing on an out-of-range index.
- **`tool/rclone`: default version pinned in `_desc.yaml`** (`default_version`, bump it
  there), **two download mirrors** (downloads.rclone.org and GitHub releases, walked in
  order by `download-file`), and **package-manager fallbacks** (`apt`/`dnf`/... via
  `install_cmd_sudo`, `winget` on Windows) when the binary download fails.
- **New task `rclone-to-ssh`**: sync / copy / bisync / resync a local directory to a
  plain SSH host with rclone's connection-string remote - no `rclone.conf` entry, no
  stored credentials.
- **`tool/claude`: the Windows installer is run as `.\install.cmd`**, so the command
  works when the current directory is not on PATH.
- **`add-tool` skill rewritten around the install ladder** (prebuilt binary via
  `download-file` -> non-sudo package manager -> sudo package manager), with the
  mirror pattern and `download-file`'s two positional behaviours documented;
  `AGENTS.md` and `CLAUDE.md` carry the same rule plus the git workflow (sign-off,
  dated branches and PR titles).
- **Housekeeping:** `.gitignore` now covers AI-session provenance files
  (`claude-resume-*`, `claude-summary-*`, `codex-*`), the runtime state of a
  `CMETA_HOME` created inside the repo (`index/`, `repos/`, `repos.json`), partial
  downloads (`*.partial`) and the bytecode caches under `task/target` and `task/venv`;
  the docs no longer carry a machine-local path or a LAN address.
- **Documentation: the abstraction the content rests on is now named.** Goals
  gained "Abstractions you can operate" — every tool, library, program, model,
  dataset and workflow here is one artifact that is simple, reusable, live and
  interconnected by `alias,UID`, inspectable down to its inputs and provenance,
  so results can be taken back to first principles and the content is
  [FAIR](https://www.go-fair.org/fair-principles/) by construction rather than by
  extra effort. `llms.txt` carries the same line.
- **Documentation: the purpose is stated consistently with the cMeta framework.**
  The Goals section now names all six aims — the previously missing *scalable* and
  *sustainable* were added — and the agent goal makes the point explicitly: an
  agent is only as useful as the context it can assemble, and here that context is
  already recorded and machine-readable.

## 0.32.0

**First public release, under the Apache License 2.0.**

- **Relicensed the repository from proprietary ("All rights reserved") to
  Apache-2.0**, matching the [cMeta framework](https://github.com/cTuningLabs/cmeta):
  - New `LICENSE` (Apache-2.0) and rewritten `COPYRIGHT`.
  - Copyright headers updated across the artifact collection — `_cmeta.*` metadata
    fields, Python/C/C++/Objective-C++ source headers, workflow and script comments.
    Original copyright years and holders were preserved.
- **New `THIRD-PARTY.md`** — the authoritative record of vendored third-party
  components, replacing the previous three-line `LICENSES` file. It lists each
  component's path, copyright holder and licence, and flags those whose terms are
  **more restrictive than Apache-2.0**:
  - `program/cbench-automotive-susan/` — SUSAN, Crown Copyright (UK DERA):
    research use only, must not be sold; UK Patent 2272285.
  - `program/milepost-codelet-…-susan-codelet-10-1/` — SUSAN-derived MILEPOST codelet.
  - `program/lib-milepost/` — GPL (EU FP6 MILEPOST, released by CAPS Entreprise).
  - `program/lib-polybench/` — Ohio State University Software Distribution License.
  - `program/lib-xopenme/` — BSD and LGPL.
  - `task/test-mojo-life/` — Modular Inc., Apache-2.0 with LLVM Exceptions
    (compatible; listed for attribution).
- **Removed the vendored NVIDIA cuDNN RNN sample**, whose licence prohibits
  redistribution. The affected artifacts (`program/test-rnn-cudnn-blas-nvcc-cuda`,
  `task/test-nvcc-cudnn-rnn`) were moved to a separate private repository.
- **Added community health files** for the public release: `CONTRIBUTING.md` (with
  guidance on vendoring third-party code), the verbatim `DCO` (Developer
  Certificate of Origin 1.1), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1),
  `MAINTAINERS.md`, `CITATION.cff`, and a self-contained
  `.github/workflows/dco.yml` that checks every pull-request commit is signed off.
- **Hardened `.gitignore`** against cMeta run artifacts (`tmp*/`, `tmp-cmeta-*`,
  `cmeta-task-saved-*`, `_repro_ctx_*`) and author scratch/backup siblings. These
  capture the full environment of the machine that produced them and must not be
  published; a few that had been committed were removed from tracking.
- Moved the `skill` category into this repository from the cMeta engine.
- Documentation and authoring skills (`AGENTS.md`, `CLAUDE.md`,
  `docs/cmeta-aops/`, `.claude/skills/`) updated for the Apache-2.0 licence, the
  third-party carve-outs, and the narrow-reindex guidance.

## Earlier

Development prior to 0.32.0 was not public and is not itemised here. It covered
the `task` workflow engine (API v2), the `tool` and `program` delegators, the
category cache, the compute abstraction (CPU / CUDA / Android / Metal / …), and
the growth of the artifact collection to roughly 115 tasks, 100 tools and 30
programs, plus models and datasets.
