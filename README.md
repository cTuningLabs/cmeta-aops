# cMeta agentic ops repository (`cmeta-aops`)

[![Test cMeta core AOps](https://github.com/cTuningLabs/cmeta-aops/actions/workflows/test-core.yml/badge.svg)](https://github.com/cTuningLabs/cmeta-aops/actions/workflows/test-core.yml)
[![Test cMeta core AOps via cTuning](https://github.com/cTuningLabs/cmeta-aops/actions/workflows/test-core-via-ctuning.yml/badge.svg)](https://github.com/cTuningLabs/cmeta-aops/actions/workflows/test-core-via-ctuning.yml)

**`cmeta-aops`** is a collection of *artifacts* for AI Operations (AIOps) — recipes
that **install and run tools, build and benchmark programs, and fetch models and
datasets** in a portable, unified way across operating systems and hardware
(Linux, Windows, macOS, Android; CPU, CUDA, and more).

Instead of a pile of one-off scripts, every capability here is a small, composable
artifact you drive through **one command**:

```bash
cx <category> <command> [args] [--flags]
```

## Project status

**An experimental plugin repository and prototyping playground for reusable cMeta
automations and artifacts — supporting open science, collaborative research,
experimentation and portable AI-agent workflows.**

This repository is where I encode my own R&D as **executable, composable workflows**
rather than as prose, scripts and half-remembered command lines. Each artifact is a
small piece of accumulated practice — how to detect and install a toolchain, how to
build and benchmark a program on a given target, how to fetch a model — written once
in a portable form and then reused, composed and driven by humans or AI agents through
the same `cx` / `access()` interface.

The longer-term intent is personal and deliberately ambitious: to grow this into the
substrate for **my own AI-driven research assistant** — an "open scientist" in a
modest, literal sense. Not a system that invents science, but a growing body of
machine-readable, self-describing automations that an agent can discover, compose and
extend on its own, so that experiments, builds and benchmarks can be set up, varied
and repeated without re-deriving the same work each time. The artifacts are the
memory; the agent is the operator.

That direction is the continuation of a long line of work on making code, data, models
and knowledge reusable, portable and reproducible — the cTuning framework, Collective
Knowledge (CK), and MLCommons Collective Mind (CM/CMX). The vision behind it is set
out in the author's publications, listed in [`CITATION.cff`](CITATION.cff) and in the
framework's
[history and publications](https://github.com/cTuningLabs/cmeta/blob/main/docs/history.md);
see also [How to cite](#how-to-cite) below.

**What that means in practice — please read before relying on anything here:**

- **Maturity varies a lot.** A few paths have CI coverage across
  `{Linux, Windows, macOS} × Python {3.9, 3.14}` — the core, and a handful of
  clang/C++, NumPy and PyTorch task recipes. Note these workflows are
  **manually triggered** (`workflow_dispatch`), not run on every push, so a green
  badge reflects the last deliberate run rather than the current commit. Everything
  outside [`.github/workflows/`](.github/workflows/) is unverified by CI, and some
  artifacts are exploratory probes kept because they encode something worth not
  losing.
- **Expect to adapt things.** Recipes reach out to real toolchains, package managers,
  compilers and hardware. A recipe that works on one machine may need a version pin, a
  flag or a path adjusted on another. That is the normal case, not a defect.
- **Interfaces here are less stable than the engine's.** The cMeta framework aims for
  a small, stable core; this repository is deliberately freer to move.
- **Contributions and issue reports are welcome** — see [Contributing](#contributing) —
  but this is a research and prototyping project, not a supported product.

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


# Contributing

Contributions are welcome — new tools, tasks and programs, portability fixes, and
documentation. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow.

This project uses the **Developer Certificate of Origin (DCO)** rather than a CLA:
sign your commits with `git commit -s`. Please read the third-party section of
`CONTRIBUTING.md` before vendoring any source you did not write.

See also [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) and
[`MAINTAINERS.md`](MAINTAINERS.md).

# Copyright and license

Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the **Apache License, Version 2.0** — see [`LICENSE`](LICENSE),
[`COPYRIGHT`](COPYRIGHT) and [`NOTICE`](NOTICE). This is the same license as the
[cMeta framework](https://github.com/cTuningLabs/cmeta).

**Attribution when you reuse this.** Apache-2.0 §4 requires anyone redistributing
this work, or a derivative of it, to retain its attribution notices and reproduce
the contents of [`NOTICE`](NOTICE). That covers **metadata (`_cmeta.*`), automation
pipelines (`_desc.yaml`) and scripts as much as code**, and it applies whether the
copying was done by a person or generated, adapted or incorporated by an **AI agent
or LLM** — generation by a model does not waive the obligation. AI agents working in
this repository should also read [`llms.txt`](llms.txt) and
[`AGENTS.md` §8.1](AGENTS.md).

**Using the ideas rather than the code?** Concepts aren't covered by copyright, so
this is an invitation rather than a requirement: if this project's approach is
useful to yours, a citation is very welcome — and I would rather collaborate than
be copied quietly. Get in touch: [cTuning.ai/@gfursin](https://cTuning.ai/@gfursin).

> **Third-party components.** Parts of this repository are third-party works that
> are **not** covered by the Apache-2.0 license and are redistributed under their
> own terms — some of which are more restrictive (research-use-only, or GPL).
> See [`THIRD-PARTY.md`](THIRD-PARTY.md) for the full list of affected paths,
> their copyright holders and their licenses, and review it before redistributing
> this repository or building a product on it.

## How to cite

If you use cMeta AOps in your research, see [`CITATION.cff`](CITATION.cff) (GitHub
renders it as "Cite this repository"). Please also consider citing the
[cMeta framework](https://github.com/cTuningLabs/cmeta) and the author's earlier
work on Collective Knowledge and Collective Mind that this project builds upon.
