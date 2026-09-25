# Changelog

All notable changes to cMeta AOps are documented here, newest first.

## DEV VERSION (0.32.1.1)
- **`task/run-claude2` records how the artifacts of a claude session were made.** It sets
  `CMETA_GENERATOR` for the claude process - `{"method": "agent", "agent": "Claude Code <version>",
  "model": ..., "effort": ...}`, the model and effort as passed after `--`, else the thinking budget
  of `MAX_THINKING_TOKENS` - unless a task that runs claude set it already, so an import task keeps
  its own record. With the engine's `artifact_defaults` / `CMETA_GENERATOR` support, every artifact
  claude creates through `cx` carries it as `generator`, and every one it updates as
  `last_generator`. Documented in `docs/cmeta-aops/agent-tasks.md`.
- **Fix: `task/enable-long-paths-win` never enabled anything on a stock Windows.** Its
  `enable-long-paths-win.bat` began with a UTF-8 BOM, which `cmd.exe` reads as part of the first command
  under every code page except 65001 (UTF-8) - so on an ordinary English or French install the elevated
  window failed on `'<BOM>reg' is not recognized`, closed at once, and the registry value was never
  written. Every run then asked for administrator rights again and still reported long paths as off; it
  only ever worked on machines with the system-wide UTF-8 code page. The task now starts `reg.exe`
  elevated itself (no batch file, no user path to quote - an unquoted path with a space in the user name
  broke it too), waits for it, and checks the registry rather than `RtlAreLongPathsEnabled`, which
  Windows freezes when a process starts and so could never turn true within the same run. When the
  value is already set in the registry it no longer prompts at all. The warning says up front that an
  administrator prompt is coming and what to do if it does not work (Settings > System > Advanced >
  "Enable long paths" on Windows 11, or the `reg add` command), and the error repeats it with the reason
  (prompt declined, timed out, command failed). The `.bat` is kept, BOM-free, for running by hand.
- **Batch files no longer start with a UTF-8 BOM.** 336 `.bat` test scripts and helpers under `program/`,
  `task/` and `tool/` began with one, which `cmd.exe` reads as part of the first command under every code
  page except 65001 - on an ordinary English or French Windows their first line failed with
  `'<BOM>...' is not recognized`. Nothing else in them was non-ASCII, so they are plain ASCII now and run
  the same under any code page.
- **Tool detection lists each file once on merged-/usr Linux.** On Ubuntu, Debian, Fedora, Arch and
  others `/bin` and `/sbin` (and on some `/usr/sbin`) are symlinks into `/usr`, and all of them are on
  `PATH`, so every candidate was offered two to four times: a fresh Ubuntu listed `/bin/gcc`, `/bin/gcc-13`,
  `/usr/bin/gcc`, `/usr/bin/gcc-13`, ... and the first `cx tool setup git` asked to choose between `/bin/git`
  and `/usr/bin/git`, the same file. `find_path` now skips those three system aliases when the directory
  they point to is searched anyway. Nothing else is resolved: paths that may lead to different versions
  after an update - `/usr/local/cuda` and `/usr/local/cuda-13.0`, `gcc` and `gcc-13` - are still offered
  side by side, and `-q` still takes the default where there is no terminal to ask.
- **winget installs name `--source winget`.** Without it winget also queries the Microsoft Store source,
  and where that fails - `0x8a15005e: The server certificate did not match any of the expected values`,
  typically certificate pinning broken by an HTTPS-inspecting antivirus or proxy - it refuses to install
  a package it has already found in the winget source and asks for `--source`. Every `tool/*` winget
  command and the Windows `install_cmd*` of `task/host` (used by `install-sys-tool`) now pass it, as
  `tool/swiftlang` already did. Two lines that could never have worked are fixed on the way: the
  versioned `tool/tailscale` command said `--Tailscale.Tailscale` instead of `--id=Tailscale.Tailscale`,
  and `tool/microsoft.windows.adk` used `-id`, which winget rejects.
- **The ssh client is now a declared dependency, not a word on the caller's PATH.** `task/rclone-to-ssh`
  built its sftp command as a bare `ssh`, so which binary ran depended on the shell. A Windows host can
  carry several OpenSSH clients - the system one in `System32\OpenSSH`, the MSYS build inside Git, and
  copies bundled with other products - and they disagree on one thing that matters: the Windows build
  refuses a private key whose permissions let other users read it (`UNPROTECTED PRIVATE KEY FILE`, after
  which the key is ignored and authentication fails), while the MSYS build uses it anyway. The result was
  a sync that worked in one shell and failed in another with nothing but rclone's
  `couldn't initialise SFTP: ... unexpected EOF` to go on, which reads like a network or server fault.
  The task now resolves `tool/open-ssh` through `setup`, uses the absolute path, and prints it with its
  version, so the binary in use is visible in the trace instead of being a property of the environment.
  A resolved path containing a space keeps the bare name, because rclone parses `--sftp-ssh` as a
  space-separated list and the value is already quoted; the path is still reported.
- **`tool/open-ssh` detects properly and can install itself.** It gained `extra_paths` (the Windows
  system directory, winget packages, Homebrew), a second version regex, a per-distribution package name
  (`openssh-client` on Debian and Alpine, `openssh-clients` on Fedora, RHEL and SUSE, `openssh` on Arch),
  install commands for the three platforms and help text naming the Windows optional feature. Detection
  is what runs in practice, since the client ships with Windows 10 1809 and later, macOS and nearly
  every Linux.
- **MLPerf Inference v6.1 results and the MLPerf Inference Endpoints benchmark.** `task/get-mlperf-inference-results`
  defaults to the v6.1 round (published 2026-09-15; `--version=6.0` etc. still work) with a test script, plus the
  `clone-git` example scripts for inference v6.1 and training v6.0. Two new tasks read the Endpoints benchmark:
  `task/get-mlperf-endpoints-src` (mlcommons/endpoints, optional tag or branch) and `task/get-mlperf-endpoints-results`
  (`endpoints_results_v<round>`, default 0.7), both thin wrappers over `clone-git-to-cache` like their inference siblings.
- **README rewritten for first-time readers.** A plain opening (what the repository is, the one command,
  where to start: the course, the installer, the catalogues), a "Try it" block that pulls the repository
  from GitHub and runs the first tool, task and program, and one sentence on the Collective Knowledge
  lineage with a link to the framework's history page instead of the lineage paragraph. The status
  warnings, goals and core concepts are unchanged.
- **Fix: `tool/llvm` with a partial version (`--use.llvm.version=22`, `--version=22.1`).** The
  install hook pasted the partial version into the release URL (`llvmorg-22/LLVM-22-Linux-X64.tar.xz`,
  HTTP 404), which failed the *clang++ 22* workflow on every OS. It now resolves a partial version to
  the newest published release that starts with it (from the upstream tags, like `cmd_get_versions`),
  skipping release candidates and a release whose prebuilt asset is not there yet.

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
