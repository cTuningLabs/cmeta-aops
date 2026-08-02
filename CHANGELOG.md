# Changelog

All notable changes to cMeta AOps are documented here, newest first.

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
