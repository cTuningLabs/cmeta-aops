<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
-->

# Disk sizes of tools — `_desc_sizes.yaml` and the free-space check

A large install or build that fills the disk part-way fails late, with an unclear error: a prebuilt
LLVM release unpacks to more than ten gigabytes, and PyTorch, vLLM, CUDA or LibTorch are in the same
class. A tool can declare how much space its setup needs, and `task/setup` checks the free space of
the folder that will receive the data **before** downloading or building anything. Without a
declaration there is no check and nothing changes.

## `_desc_sizes.yaml` — the rules of a tool

The sizes live in their own file next to `_desc.yaml`, `tool/<name>/_desc_sizes.yaml`, which only
the size check and the sizes report read (`_desc.yaml` is read for many purposes and stays small).
It is a list of rules; **the first matching rule wins**; sizes are GB (floats):

```yaml
sizes:
  - if: {method: install, os: linux, version: '>=22'}   # the prebuilt LLVM 22 on Linux
    peak: 15          # during the setup: download + unpacked (+ build tree)
    kept: 12          # what stays in the cache afterwards
  - if: {method: install}
    peak: 4
  - if: {method: build}                                 # from source
    peak: 60
    kept: 10
  - peak: 4                                             # anything else
```

The keys of `if` are optional; a missing key matches anything:

| Key | Values | Note |
|---|---|---|
| `version` | `'>=22'`, `'3.12'`, `'==1.2.3'` | cMeta's own version matching, as `--version` uses it; a request without a version matches only rules without this key |
| `os` | `windows`, `linux`, `darwin` | the host |
| `arch` | `amd64`, `arm64` | the host's CPU |
| `method` | `install`, `build` | a download or package install, or a build from source |
| `compute` | `cpu`, `cuda`, … | one value matches a request whose `with.compute` list contains it |
| `with` | `{build: prebuilt}`, `{static: true}`, … | any keys of the request's `with` |

Matching is the engine's `matches_query`, so there is no syntax of its own. The values are
deliberately rough: they only need to be safe upper bounds.

## The check

Before an install and before a build, `task/setup`:

1. picks the rule for the request (version, OS, CPU, method, `with`);
2. reads the free space of the folder that receives the data: the cache entry, or `--path`;
3. compares it with the rule's `peak` and with the configured minimum (below).

When the space is short:

- a quiet run (`-q`) **stops before downloading anything**:
  `LLVM 22.1.7 (install, linux) needs about 15 GB during the setup; 6.5 GB are free in /home/x/CMETA/repos/local/cache/task--setup--llvm--…. Free space, give --path=<folder on another disk>, or --skip_size_check.`
- an interactive run prints the same as a warning and asks `Continue anyway (y/N)?`.

`--skip_size_check` skips the check (inside a pipeline: `--use.<tool>.skip_size_check`).

**A minimum for every tool:** `cx config set task --meta.min_free_gb=5` makes every install and build
check for that much free space, with or without a `_desc_sizes.yaml`. It is off by default
(`cx config set task --meta.min_free_gb= --unset` or an empty value turns it off again).

Only the target folder's volume is checked: downloads that `download-file` keeps elsewhere, the pip
and uv caches and Docker images are not counted.

## Learning the sizes

Every install or build that `task/setup` finishes in the cache records what it took in the cache
entry's result, next to the timings:

```
_impact:
  disk_gb: 11.2          # the size of the cache entry (and of --path) afterwards
  disk_method: install   # install or build
  disk_os: linux
  disk_arch: amd64
  peak_gb: 12.9          # only when the tool's install() reports its peak (archive + unpacked tree)
```

`cx tool setup <tool> --sizes` lists the records of the tool's cache entries, the rules of its
`_desc_sizes.yaml`, and the rules it suggests from the records (about 20 % above the largest sizes
seen, one rule per method, OS, CPU and major version, plus a default rule) as text to paste:

```
$ cx tool setup llvm --sizes

Disk sizes recorded for "llvm" (1 of 3 cache entries):

  22.1.7       install  linux    amd64  kept 11.32 GB  task--setup--llvm--92cba9b802b84070

Rules in _desc_sizes.yaml: 5

Suggested _desc_sizes.yaml (about 20% above the largest sizes seen; adjust and paste):

sizes:
  - if: {method: install, os: linux, arch: amd64, version: '>=22,<23'}
    peak: 14
    kept: 14
  - peak: 14
```

Detected tools (found on the system) record no size. Run it on several machines, or inside test
sessions, and the rules of the big tools fill in over time.

## For tool authors

- Add `_desc_sizes.yaml` to a tool whose install or build takes more than a few gigabytes; small
  tools need none.
- A custom `install()` may return `peak_gb` (the size of the archive plus the unpacked tree, before
  the archive is removed) so that the record carries the peak and not only what is kept.
- The check does not change the cache identity of a tool: `_impact` is not matched by the cache.

See also [tool-abstraction.md](tool-abstraction.md) and the `add-tool` skill.
