# cMeta agentic ops repository (`cmeta-aops`)

[![Test cMeta core AOps](https://github.com/cTuningLabs/cmeta-aops/actions/workflows/test-core.yml/badge.svg)](https://github.com/cTuningLabs/cmeta-aops/actions/workflows/test-core.yml)
[![Test cMeta core AOps via cTuning](https://github.com/cTuningLabs/cmeta-aops/actions/workflows/test-core-via-ctuning.yml/badge.svg)](https://github.com/cTuningLabs/cmeta-aops/actions/workflows/test-core-via-ctuning.yml)

**`cmeta-aops`** is a curated collection of ready-to-use *artifacts* for AI Operations
(AIOps) — recipes that **install and run tools, build and benchmark programs, and fetch
models and datasets** in a portable, unified way across operating systems and hardware
(Linux, Windows, macOS, Android; CPU, CUDA, and more).

Instead of a pile of one-off scripts, every capability here is a small, composable
artifact you drive through **one command**:

```bash
cx <category> <command> [args] [--flags]
```

## Goals

- **One interface for everything** — set up a compiler, build PyTorch, run a matmul on
  CPU or CUDA, or fetch a model — all through the same `cx` surface.
- **Portable by construction** — the same artifact adapts to the host OS, package
  manager and compute target, so a recipe written once runs in many places.
- **Reusable and composable** — tools, libraries, builds and downloads are cached and
  shared across runs and across artifacts, so work isn't repeated.
- **Automation- and agent-friendly** — artifacts are plain metadata + small hooks that
  humans and AI agents can read, extend and compose (see the [skills](.claude/skills/)).

> This repository is **content**, not the engine. It runs on **cMeta**, a small portable
> framework for unifying and reusing code, data, models, agents and knowledge through a
> single uniform interface. cMeta targets collaborative, **reproducible-by-design**
> research and experimentation (an ongoing effort — reproducibility is *improved*, not
> "solved").
>
> - cMeta framework (Apache-2.0, open source): **https://github.com/cTuningLabs/cmeta**
> - Homepage / author: **https://cTuning.ai** · [Grigori Fursin](https://cTuning.ai/@gfursin)

## Quick start

cMeta is a Python package (`pip install cmeta`, Python 3.9–3.14). Once it's installed and
this repository is on disk:

```bash
cx repo plug .                      # register this repository with cMeta (once)
cx --reindex                        # build the fast index

cx tool setup git                   # detect or install git into the cache
cx tool run git -- status           # run a set-up tool (args go after --)

cx task list                        # browse the reusable workflow steps
cx program run test-nmm-c-cpu cpu   # compile & run a matmul benchmark on CPU
cx program run test-nmm-nvcc-cuda cuda   # ...or on CUDA (if available)
```

Handy flags: `-j`/`--verbose` (full step-by-step trace), `--con`, `--quiet`,
`--version=X` (pin a tool version), `--update`/`--clean`/`--new` (cache control).

## Core concepts

Four ideas cover almost everything here. Top-level folders are **categories**; each
subfolder is an **artifact** described by `_cmeta.*` (identity) + `_desc.yaml`
(automation) + optional `api_v1.py` (hooks).

- **`task` — the workflow engine.** A task is one reusable, composable, cacheable step.
  Tasks call other tasks in `uses:` pipelines and share a context, so complex workflows
  are just small steps wired together. Everything else is built on tasks.
  → `cx task run <name>`

- **`tool` — external programs, made portable.** A tool artifact knows how to **detect,
  install, build and run** one CLI (git, cmake, clang, cuda, python, node-js, …) across
  OSes, and how to list its available versions. Set one up once and reuse it everywhere.
  → `cx tool setup <name>` · `cx tool run <name> -- <args>` · `cx tool setup <name> --versions`

- **`program` — build & run benchmarks and apps.** A program is a compilable/runnable
  artifact (matmul micro-benchmarks, PyTorch/llama.cpp builds, image classification, …).
  You pick a **compute** target (`cpu`, `cuda`, `android-cpu`, …) and the program
  automatically selects the right compiler, libraries and run wrapping for that target.
  → `cx program run <name> <compute>` · `cx program compile <name> <compute>`

- **`cache` — reuse across runs.** Installs, downloads and builds are stored as cache
  entries matched *semantically* by tags and parameters, so multiple versions coexist and
  are reused across runs and artifacts instead of being rebuilt. Control it with
  `--update` (rebuild), `--clean` (wipe), `--new` (force a fresh entry).
  → `cx cache show | clean | delete`

Putting it together: `cx program run` uses **tasks** to set up the **tools** and
libraries a program needs for the chosen compute target, and stores everything in the
**cache** so the next run is fast.

## Documentation

In-depth developer/agent documentation lives in
[`docs/cmeta-aops/`](docs/cmeta-aops/README.md):

- [Architecture & internals overview](docs/cmeta-aops/README.md)
- [The `task` workflow engine](docs/cmeta-aops/task-engine.md)
- [The `tool` abstraction (detect/install/build/run, version listing)](docs/cmeta-aops/tool-abstraction.md)
- [The `program` category & the `compute` abstraction](docs/cmeta-aops/program-and-compute.md)

See also `AGENTS.md` (canonical brief for AI agents), `CLAUDE.md`, and the authoring
[skills](.claude/skills/) (`add-tool`, `add-task`, `add-program`).


# Useful configurations

```
cx config set task --meta.file_cache=x:\cmeta-file-cache-windows
cx config set task --meta.check_versions
cx config set default --meta.default_git=git@github.com:
```


# Copyright and license

Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.

No part of this Software, including but not limited to source code, object code,
scripts, configuration files, JSON/YAML metadata and descriptions, datasets,
documentation, examples, specifications, outputs, and related materials
(collectively, the "Materials"), may be copied, reproduced, modified, distributed,
reverse engineered, analyzed, processed, or otherwise used for the purpose of
training, pre-training, fine-tuning, adapting, evaluating, benchmarking, improving,
or developing any artificial intelligence, machine learning, large language model,
foundation model, automated code generation system, or similar technology,
without the prior written permission of the copyright holders.

The use of the Materials, directly or indirectly, by any person, organization,
contractor, agent, affiliate, customer, end user, or automated system for the
creation of derivative, competing, or functionally similar products or services,
including through the assistance of artificial intelligence systems, is prohibited
unless expressly authorized in writing by the copyright holders.
