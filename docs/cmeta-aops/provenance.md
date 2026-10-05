# Provenance of a program run

*Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).*

A program run resolves tools (compilers, a CUDA toolkit, libraries, a Python), builds a binary and
runs it. Three questions come up as soon as several versions of anything are around: what did the
run **request**, what did cMeta **resolve**, and what did the process **really load**? The
provenance record answers them for every run, and a few checks compare the three.

The rule behind the checks is the one the whole repository follows:

| | the default was taken | the configuration was requested explicitly |
|---|---|---|
| available | use it, record it | use it, record it |
| unavailable, or not what ran | report it and go on (a **warning**) | **fail** (an **error**) — never a silent fallback |

A result produced under a configuration other than the requested one is worse than no result: it
goes into a table under the wrong label.

## The record

Every `cx program run` writes `provenance.json` into the program's build folder — the same
`target_tmp` folder (default `tmp`) that holds the binary, the run script and `.cmeta-build-stamp.json`
— next to the existing `_repro_ctx_*.json` files. Writing it never fails a run: an error inside the
recorder is a warning.

| Key | What it holds |
|---|---|
| `format` | `1` |
| `created` | ISO 8601 UTC |
| `program` | `alias`, `uid`, `target_tmp`, `target_path` |
| `compute` | the compute targets of the run (`["cuda"]`) |
| `host` | `uname`, `uarch`, `os_id` |
| `requested` | the explicit choices of the request: `use` (`--use.<tool>.version` / `.name` …), `compile` (`--compile.static`, …), `with`, `compute`, `params` |
| `resolved` | every tool of the run: `name`, `version`, `path`, `entry` (its cache entry), a subset of `features` |
| `build` | the build stamp, and the inspector's view of the binary: `format` (`elf`, `pe`, `macho`), `arch`, `static`, `deps` (each dependency with the `path` the loader would take, its `source` — rpath, environment, program folder, system — and whether it is a `system` library), `missing` |
| `runtime` | the driver and GPU, the Python and its venv |
| `loaded` | `method` (`resolved` or `loader-log`), `libraries` (each with `path`, `system`, and the `tool` whose entry it comes from, or `null`; a compiler's own runtime library carries the compiler's key and `role: runtime`), `processes` |
| `checks` | `rule`, `level` (`error`, `warning`, `info`), `ok`, `detail` (and `tool` when it concerns one) |
| `ok` | `false` when an error-level check failed |

A shortened example:

```json
{
  "format": 1, "created": "2026-10-04T20:11:03Z",
  "program": {"alias": "test-nmm-nvcc-cuda", "target_tmp": "tmp-static"},
  "compute": ["cuda"], "host": {"uname": "linux", "uarch": "x86_64"},
  "requested": {"use": {"nvcc": {"version": "13.3"}}, "compile": {"static": true}},
  "resolved": {"nvcc": {"version": "13.3.1", "path": "/usr/local/cuda-13.3/bin/nvcc"},
               "compiler-cpp": {"name": "gcc-cpp", "version": "14.2.0"},
               "lib-cudnn": {"version": "9.27.0", "path": ".../cache/task--setup--lib-cudnn--.../content/lib"}},
  "build": {"binary": {"format": "elf", "arch": "x86_64", "static": false,
                       "deps": [{"name": "libcudnn.so.9", "path": ".../lib-cudnn--.../lib/libcudnn.so.9", "source": "env", "system": false}]}},
  "loaded": {"method": "loader-log",
             "libraries": [{"name": "libcudnn.so.9", "path": ".../lib-cudnn--.../lib/libcudnn.so.9", "system": false, "tool": "lib-cudnn"},
                           {"name": "libc.so.6", "path": "/lib/x86_64-linux-gnu/libc.so.6", "system": true, "tool": null}]},
  "checks": [{"rule": "static: no shared library beyond the system set", "level": "error", "ok": true},
             {"rule": "loaded libcudnn.so.9 comes from the resolved lib-cudnn", "level": "error", "ok": true, "tool": "lib-cudnn"}],
  "ok": true
}
```

## The modes: `--provenance=on|off|loaded|strict`

| Mode | What changes |
|---|---|
| `on` (default) | Passive: after the run, the recorder reads the binary's headers and the context the driver already has, and writes the record. No compile or run command changes, no environment variable is added, measurements are untouched. The dependencies are *resolved* — the files the loader would take — not observed. |
| `off` | No record at all. |
| `loaded` | The run is also observed: on Linux `LD_DEBUG=libs` (to a file per process), on macOS `DYLD_PRINT_LIBRARIES` (to a file); the record's `loaded` section then holds what every process really loaded — a Python program shows a wheel's bundled CUDA libraries, a plugin loaded with `dlopen` appears. Program start is slightly slower. On Windows and Android there is no loader log: `loaded` stays the resolution. |
| `strict` | As `on` (or `loaded`), and a failed **error**-level check fails the run with return code 99 and the `PROVENANCE:` message. |

In `on` and `loaded`, a failed check is printed as `PROVENANCE: ...` and recorded (`ok: false`), and the
run's own result is returned as usual.

When a run names no mode, the environment variable **`CMETA_PROVENANCE`** sets it: a test session or a
CI job exports `CMETA_PROVENANCE=strict` and every `cx program run` in it fails on a failed error-level
check, while an interactive shell keeps the passive default. `--provenance=<mode>` on the command line
always wins; an unset or empty variable means `on`.

### Which tool a loaded library belongs to

A library is attributed to the tool that names it and holds it in its folders (`libcudart` to the
CUDA toolkit, `libcrypto` to `lib-openssl`), else to the tool whose cache entry contains it (a wheel's
file inside a tool's venv). A compiler's own runtime is the exception that needs a third rule: GCC's
`libgomp`, `libstdc++` and `libgcc_s`, LLVM's `libomp` and `libc++`, Intel's `libiomp5`, MSVC's
`vcomp140` are installed where every other library is (`/usr/lib/<triplet>`, `C:\Windows\System32`),
so no tool names them and no folder reaches them. The record asks the compiler itself:
`<compiler> -print-file-name=<file>` prints the file the compiler links against, and when it is the
same file as the one the process loaded (links resolved), the library is that compiler's runtime, shown
under the compiler's row with `(runtime)`. MSVC has no such question: its runtime DLLs are known by
name and must lie in the Visual Studio installation or in `System32` (the redistributable copies). A
compiler installed in a folder of its own (LLVM on Windows, MinGW, a Homebrew GCC, an Android NDK)
also owns a runtime-named library found under that folder. The names are kept to each family's own
runtime, because a compiler's `-print-file-name` also finds the other family's libraries in the shared
system folders; a `libgomp` loaded from somewhere else than the compiler's answer stays unattributed,
which is the point. Only libraries that no other rule claimed are asked about, so a run asks a handful of
questions at most, and never for MSVC.

## The checks and the policy per target

| Check | Level | Meaning |
|---|---|---|
| static: no shared library beyond the system set | error when `--compile.static` was requested | A **CPU** static build is fully static (no dynamic loader). A **CUDA** static build links the static CUDA runtime and the static third-party libraries, and may load: the C library family, `libstdc++`/`libgcc_s`, the CUDA driver (`libcuda`) and NVIDIA's shared libraries (cuBLAS, cuDNN, …) — the policy [`program-and-compute.md`](program-and-compute.md) documents. On Windows the OpenMP runtime stays a DLL (no static one exists), as documented. |
| a tool's library comes from that tool's entry | error | `libcudart` from the resolved CUDA toolkit, `libcudnn` from the resolved `lib-cudnn`, `libcrypto` from the resolved `lib-openssl` (or absent in a static build): a library loaded from elsewhere (the system's, another entry's) is flagged with both paths. |
| requested version resolved | error | `--use.<tool>.version=<v>` → the resolved version matches (setup already enforces it; the record keeps the proof). |
| requested accelerator used | error when explicit, warning when a default | For programs that report `available` / `required` accelerators (LiteRT on Android): an accelerator named explicitly must have been used; an optional one (`npu?`) that was not available is a warning. |

## The view: `cx program provenance`

The command reads the program's build folders through the `cache` category, which the program category
declares as a dependency in its meta: after pulling the version that introduced it, refresh the index once
(`cx category update <repo>:program`, or `cx --reindex`), or the command stops with a message saying so.

```bash
cx program provenance test-nmm-nvcc-cuda                        # the newest record (tmp of a single entry first)
cx program provenance test-nmm-nvcc-cuda --target_tmp=tmp-static
cx program provenance test-nmm-nvcc-cuda --all                  # every build entry (one per request) and folder with a record
cx program provenance test-nmm-nvcc-cuda --entry=3f9a2c1e8b7d6a54            # one entry: its alias, UID or request digest
cx program provenance test-nmm-nvcc-cuda --target_tmp=tmp-static --diff=tmp-dynamic
cx program provenance test-nmm-nvcc-cuda --entry=3f9a2c1e8b7d6a54 --diff=task--program--test-nmm-nvcc-cuda:tmp
cx program provenance test-nmm-nvcc-cuda --target_tmp=tmp-static --diff=/path/from/another/machine/provenance.json
cx program provenance test-nmm-nvcc-cuda --target_tmp=tmp-static --as_flags
cx program provenance test-nmm-nvcc-cuda --as_json
```

A program's builds live in **one cache entry per request** (`task--program--<program>` for the plain
request, `task--program--<program>--<uid>` for the others; see `program-and-compute.md`): the entry of
`--use.nvcc.version=12.9` and the entry of `--use.nvcc.version=13.3` coexist, each with its build
folders. `--all` groups the records by entry and names each entry's request; `--entry` picks one by its
alias, UID or request digest; `--diff=<entry>:<folder>` compares across entries.

The view prints the header (program, folder, date, compute, host, the binary's format and whether it is
static, the result), then one row per tool — what was requested (or `(auto)`), what was resolved and
where, the libraries the process loaded from that tool's entry, and the check result of the row —
then the checks and the libraries loaded from outside any tool (the system ones folded into one
line):

```
Provenance of program test-nmm-nvcc-cuda (tmp-old)   created 2026-10-03T09:00:00Z
compute: cuda   host: linux x86_64   binary: ELF x86_64, dynamic   result: FAILED (1 ok, 1 failed, 1 warnings)
loaded: 5 libraries by the loader log, 1 processes

  tool          requested  resolved        loaded
  compiler-cpp  (auto)     gcc-cpp 14.2.0  libstdc++.so.6 (runtime)
                           /usr/bin/g++
  lib-cudnn     (auto)     9.27.0          libcudnn.so.9  [ok]
                           /home/u...k--setup--lib-cudnn--bb22/content/lib
  lib-openssl   (auto)     3.0.13          libcrypto.so.3  [FAIL]
                           /usr
  nvcc          13.3       12.9.86         -
                           /usr/local/cuda-12.9/bin/nvcc

checks:
  FAIL  static: no shared library beyond the system set: libcrypto.so.3 loaded from /lib/x86_64-linux-gnu  (error)
  ok    loaded libcudnn.so.9 comes from the resolved lib-cudnn
  warn  accelerator used: npu not available, cpu used  (warning)

other libraries: 2 system (libc.so.6, libm.so.6)
```

`--diff` lists what differs between two records by section — the request, the resolved versions and
paths, the libraries added and removed, the checks that changed, and the context (compute, host,
static or not):

```
Differences: test-nmm-nvcc-cuda (tmp-old) -> test-nmm-nvcc-cuda (tmp-static)
resolved:
  nvcc path: /usr/local/cuda-12.9/bin/nvcc -> /usr/local/cuda-13.3/bin/nvcc
  nvcc version: 12.9.86 -> 13.3.1
loaded libraries:
  - /lib/x86_64-linux-gnu/libcrypto.so.3
checks:
  accelerator used: warn -> (none)
  static: no shared library beyond the system set: FAIL -> ok
```

`--as_flags` prints, on one line, the options that reproduce the resolved configuration — the chosen
compiler tools, the version of every resolved tool, the explicit compile and `with` parameters, the
compute targets and the build folder:

```
--use.compiler-cpp.name=gcc-cpp --use.lib-cudnn.version=9.27.0 --use.lib-openssl.version=3.0.13 --use.nvcc.version=13.3.1 --compile.static --compute=cuda --target_tmp=tmp-static
```

A folder without a record gets a message naming the folder and the run that creates one; when the
default folder has none but others do, they are listed.

## In a test session

A record belongs with the test it came from. `cx task run test-session --start` prints the line that
makes the session the shell's current one (`export CMETA_TEST_SESSION=<YYYYMMDD/HHMM.type>`; `set` on
cmd, `$env:` on PowerShell; `--print=export` prints only that line). With the variable set, every
`cx program run`:

- attaches its record to the session, as `attachments/provenance--<program>--<build folder>--<HHMMSS>.json`,
  with a note `provenance: <program> (<folder>) ok, 0 failed, 1 warnings; compute cpu` in `session.md`;
- runs with `--provenance=strict` unless the run names a mode or `CMETA_PROVENANCE` is set, so a run
  whose explicit configuration was not honoured fails the test instead of producing a mislabelled result.

The attachments stay with the session's log (`log::cmeta-aops-test-sessions`), so a result in a summary
can always be taken back to the toolchain and the libraries that produced it. A record can still be
attached by hand: `cx task run test-session --id=<id> --attach=<build folder>/provenance.json --attach_as=<name>`.

## Limits

- **Windows and Android:** no loader log; `loaded` is the resolution of the binary's imports under the
  run's environment, which misses libraries a program loads itself at run time.
- **Plugins and `dlopen`:** visible only with `--provenance=loaded`.
- **Python programs:** the binary is the interpreter; the interesting libraries (a wheel's CUDA runtime)
  appear with `--provenance=loaded`, or in `runtime` when the framework reports its own versions.
- The record describes **one run** in one build folder. The folder's entry is named by the request, so a
  changed `--use.<tool>.version` builds in its own entry; a changed resolution of the *same* request (a
  toolkit upgraded underneath an auto choice) is refused by the build-folder stamp and rebuilt with
  `--recompile` or `--clean`.
