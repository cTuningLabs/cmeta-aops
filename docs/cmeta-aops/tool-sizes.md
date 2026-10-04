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
  disk_gb: 11.2          # the size of the cache entry afterwards (what is kept)
  disk_method: install   # install or build
  disk_os: linux
  disk_arch: amd64
  download_gb: 1.4       # the archives download-file fetched into the entry
  peak_gb: 12.9          # the largest of: archive + unpacked tree at the end of each unpacking (before
                         # download-file removes the archive), what install() reported, the entry's size
```

`task/download-file` measures every download it unpacks: the archive (`download_bytes`), the files
it added (`unpacked_bytes`) and their sum (`peak_bytes`), returns them as `download_sizes` and
appends them to `.cmeta-download-sizes.json` in the folder it works in; during an install that is
the tool's cache entry, so every tool that downloads a release archive (through `download-file`
directly, `common_release.py`, `common_jdk.py`, …) gets a real peak without any code of its own.

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

## Programs

A program whose build is large may have the same file, `program/<name>/_desc_sizes.yaml`, with the
same rules; `compile-and-run-program` checks the free space of the **build folder's** volume
(`target_path`: the program's cache entry, `--target_tmp=<name>` or `--target_path=<folder>`) before
the compile phase, when a compile is going to run (a reused build is not checked). The facts a rule
matches are `os`, `arch`, `method: build`, `compute` (the targets, a list: `{compute: cuda}` matches
a run whose targets include cuda), `version` (the program's `--version`, when it has one) and `with`
= the compile parameters (`{static: true}`). The configured minimum (`min_free_gb`) applies as for
tools, `--skip_size_check` skips the check, and the message says what to do:

```
build-pytorch (build, linux, cuda) needs about 40 GB during the build; 23.1 GB are free in
/home/x/CMETA/repos/local/cache/task--program--build-pytorch/tmp. Free space, give
--target_tmp=<name> or --target_path=<folder on another disk>, or --skip_size_check.
```

After a successful compile the size of the build folder is recorded in the compile state of the
folder and in the run's result (`_impact.disk_gb`, with `disk_os`, `disk_arch`, `disk_compute`), so
the rules of the build programs (`build-pytorch`, `build-vllm`, `build-llama-cpp`,
`build-executorch-android`, `build-torch-cpp`, `build-pytorchvision` have them) can be checked
against what builds really take. A program without the file and no minimum: no check, no output.

## For tool authors

- Add `_desc_sizes.yaml` to a tool whose install or build takes more than a few gigabytes; small
  tools need none.
- A tool that fetches its files with `task/download-file` gets the peak of its downloads recorded for
  free. A custom `install()` that unpacks or builds in its own way may return `peak_gb`; the largest
  of all these figures is recorded.
- The check does not change the cache identity of a tool: `_impact` is not matched by the cache.

See also [tool-abstraction.md](tool-abstraction.md) and the `add-tool` skill.
