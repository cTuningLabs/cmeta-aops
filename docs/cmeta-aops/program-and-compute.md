<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.
Proprietary and confidential.
-->

# The `program` category & the `compute` abstraction

A **program** artifact (`program/<name>/`, category `program,22788f3c30d04e6d`,
API v1) is a compilable/runnable benchmark or app. Like `tool`, the category is a
**thin delegator**; the real work is in each program's `_desc.yaml` (patched onto a
shared template) executed by the `task` engine.

## 1. The `program` category (delegator)

`category/program/api/v1.py`:

| Command | Behaviour |
|---------|-----------|
| `run`     | → task `compile-and-run-program,05437a1aae224270`, mapping `arg1→name`, `arg2→compute` |
| `compile` | `run` + `skip_run: True` |
| `clean`   | find every program, `rmtree` each `tmp*` dir |
| `update_desc_` | the **inheritance patcher** (the engine behind `inherits`/`updates`) |

So `cx program run test-nmm-c-cpu cpu` = `cx task run compile-and-run-program
--name=test-nmm-c-cpu --compute=cpu`.

## 2. Program artifact anatomy

A program is a data description patched onto a template:

- **`inherits: [template-c-cpu,649899ef3f004e4a]`** — the base pipeline to clone.
- **`local_vars:`** — per-program facts threaded through `ctx['tasks']['local']`:
  `lang`, `src_dir`, `src_file_names`, `target_file_name`, `input_files`,
  `output_files` / `result_files` / `print_files`, `run_time_env`.
- **`params:`** — defaults (`compute: cuda`, `compile: {openmp: True, d: {XOPENME:}}`);
  `params_os:` for per-OS overrides.
- **`use:`** — `--use.<storage_key>` injections into downstream tasks.
- **`updates:`** — patches to the inherited `all`/`compile`/`run` pipelines.
- **`updates_cmd:`** — per-command-line variants (deep dive #3).
- **`api_v1.py`** — optional `CProgram(InitCProgram)` with `customize` / `customize1` /
  `customize2` / `customize_run` / `customize_pre` (and program-specific) hooks, invoked
  from the template via `internal_func … internal_func_from_local_key: selected-program`.
  Import: `from program_22788f3c30d04e6d.api.cprogram import InitCProgram`.

### The `updates` patcher (`update_desc_`)

Each entry matches a sub-task in a target `uses` list by key (`task:` or
`internal_func:`), then applies one of: `update:` (deep-merge into the match),
`append:` / `prepend:` (splice sub-tasks after/before), `substitute:` (replace).
A `+key` prepends `+` to append to a list value. This is how `test-nmm-nvcc-cuda` flips
the C template to CUDA (`update` compiler/setup-compile to `lang: cuda`, `append`
`lib-cuda`) and how `build-*` programs append their whole toolchain+build chain.

## 3. The template (`program/template-c-cpu/_desc.yaml`)

Defines three sub-pipelines the driver runs in order, plus `local_vars`:

- **`all.uses`** — always: `customize` hook → **`target` task** → `customize1` hook.
- **`compile.uses`** — `target-sdk` → **`compiler` task** (`lang`+`compute`) →
  `customize2` hook → **`setup-compile`** (builds the compile command) →
  `setup-dynamic-libs` → **`cmd`** (runs `local.compile_cmds`, `storage_key:
  compile-program`).
- **`run.uses`** — `customize_run` hook → conditional profiler setups (perf / nsys / ncu
  / simpleperf / WPR, gated by compute + `profile*`) → `setup-dynamic-libs` →
  **`setup-run`** (builds the run command) → **`cmd`** (runs `local.run_time_cmds`,
  `storage_key: run-program`) → **`finish-run`** (collects `result_files`).

## 4. The `compute` abstraction — the pivot

`compute` is a **list**: `["cpu"]`, `["cuda"]`, `["android-cpu"]`, `["metal"]`, or
hybrids. The **`target` task** (`task/target/api_v1.py`) resolves it:

1. Normalise (string→list; or interactively pick `target--*` artifacts if `ask`).
2. For each `c`, run sub-task **`target--<c>`** (e.g. `target--cuda` sets up the `cuda`
   tool, exposes `global.cuda.features`, emits env `CMETA_TARGET_CUDA=1`, and has an
   `sdk:` sub-pipeline that sets up `nvcc`; `target--cpu` just sets `CMETA_TARGET_CPU=1`;
   `target--android-cpu` detects the device — deep dive #2).
3. Aggregate each target's `env` / `cmake_vars` — using `env_if_not_used` /
   `cmake_vars_if_not_used` so *unused* targets still set `CMETA_TARGET_*=0`.
4. Store **`global.target = {compute, features, cmeta_targets, cmake_vars}`** and push
   `CMETA_TARGETS` / `CMETA_TARGET_*` into `aggregated.env`.

Every downstream `if:` reads `{{global.target.compute}}` — the single switch selecting
libraries, compilers, profilers and run wrapping. Two consumers filter on it:

- **`select-program`** sets `select_match: {constraints: {supported_compute: <compute>}}` —
  a program is selected only if its `_cmeta` `constraints.supported_compute` matches
  (AND-match; hybrids need all). It then resolves `inherits`, applies `updates` /
  `updates_cmd`, and stores the merged desc in `local['selected-program']`.
- **`compiler`** turns `lang`+`compute` into tool tags `lang-<lang>` + constraints
  `supports_compute`/`supports_os`, then selects + sets up the matching compiler tool
  → `global.compiler-<lang>`.

## 5. Compile machinery — tools → a compile command

1. **`compiler` task** selects a tool tagged `lang-<lang>` supporting the current
   OS+compute (gcc / clang / msvc / nvcc / icx / android-ndk clang), sets it up, stores
   it under `global.compiler-<lang>`. Its `finish_dynamic_result` derives `compiler_flags`
   from the tool's `features.flags`.
2. **The compiler tool** carries per-OS `features.flags` (see
   [tool-abstraction.md](tool-abstraction.md)) — the abstraction that makes one template
   work across toolchains.
3. **`setup-compile` task** (`task/setup-compile/api_v1.py`) is the assembler: reads
   `global['compiler-<lang>'].features.flags`, translates `params.compile`
   (`openmp`/`static`/`debug`/`d:{...}`/`fast`) into concrete flags, **scans every
   `global['lib-*']` entry** for include paths / lib paths / lib names / dynamic-lib
   paths, resolves `target_exe`/`target_path_exe`, and emits `local.compile_cmds`
   (compiler cmd + optional `ar` static-lib cmd). The template's `cmd` step runs it.

## 6. Run machinery

**`setup-run`** (`task/setup-run/api_v1.py`) assembles `local.run_time_cmds`: substitutes
the run-cmd template (`{target_xpath_exe}`, `{run_flags_after_exe}`, `{cmd_main}`,
`{input_files.*}` / `{qinput_files.*}`), folds dynamic-lib dirs into the right per-OS env
var, and wires profiling (perf/WPR/xctrace CPU, nsys/ncu CUDA, cProfile python) and the
Android remote path (deep dive #2). **`finish-run`** collects declared `result_files`
into the result and prints `print_files`.

## 7. Libraries are programs too (`lib-*`)

`lib-xopenme` inherits `template-c-cpu` with `params.compile.lib: True, install: True`
and `skip_run: True` — it compiles a static/shared lib (setup-compile's `lib_*` branch)
and copies headers. Its build result lands in `global['lib-xopenme']` with
`features.paths.{includes,libs,found_dynamic_lib*}` and `lib_names`. Programs pull it via
a `setup name: lib-xopenme` step (appended in `updates`), and `setup-compile`
auto-discovers it by scanning `global['lib-*']`. Same for `lib-polybench`, `lib-milepost`,
and OS/compute libs `lib-openssl`, `lib-openmp`, `lib-cuda`, `lib-cudnn`,
`lib-sysroot-android`, `lib-openmp-android`.

## 8. Program taxonomy (all ~31)

- **Template:** `template-c-cpu`.
- **`test-nmm-*` micro-benchmarks** (naive matmul, one per language/target):
  `c/cpp/go/java/mojo/python/rust/swift`-cpu, `objc-metal`, `nvcc-cuda`, `torch-cpp` —
  the canonical demonstration of the compute×language matrix over one template.
- **`lib-*`:** `lib-xopenme`, `lib-polybench`, `lib-milepost`.
- **Classic benchmarks:** `polybench-cpu-gemm`, `polybench-gemm-cpu-cuda`,
  `cbench-automotive-susan`, `milepost-codelet-…-susan-codelet-10-1`,
  `test-rnn-cudnn-blas-nvcc-cuda`.
- **`build-*`** (real source builds via compile-cmd override): `build-pytorch`,
  `build-pytorchvision`, `build-torch-cpp`, `build-llama-cpp`.
- **Inference / run apps:** `llama-cpp`, `image-classification-pytorch`,
  `image-classification-onnx`, `model-cnn-ylecun-mnist-pytorch`, `test-pytorch-with-audio`,
  `test-pytorch-with-vision`, `test-vllm`.

## 9. End-to-end flow (`cx program run test-nmm-c-cpu cpu`)

```
program.run  →  task compile-and-run-program (--name=test-nmm-c-cpu --compute=cpu)
  uses_before_init: select-program
      → pick test-nmm-c-cpu (constraints.supported_compute ⊇ [cpu])
      → resolve inherits(template-c-cpu) + apply updates/updates_cmd
      → local['selected-program'] = merged desc
  api.run() drives the merged desc:
   ALL:     customize → target(cpu)  [global.target.compute=["cpu"], CMETA_TARGET_CPU=1] → customize1
   COMPILE: target-sdk → compiler(lang=c,compute=cpu)  [global.compiler-c = gcc/clang + features.flags]
            → customize2 → setup(lib-openssl, lib-xopenme, lib-openmp…)  [global.lib-*]
            → setup-compile  [flags + lib-* includes/libs → local.compile_cmds]
            → cmd(compile-program)   [writes tmp-cmeta-compile-program.bat, runs it]
   RUN:     customize_run → setup-run  [local.run_time_cmds, dyn-lib env]
            → cmd(run-program) → finish-run  [collect tmp-cmeta-program-stats.json]
```

---

# Deep dives

## A. Repro-context recompile caching (`compile-and-run-program/api_v1.py`)

The driver persists three JSON snapshots in `target_path` and reuses them to skip work:
`_repro_ctx_all.json`, `_repro_ctx_compile.json`, `_repro_ctx_run.json` — each is
`{'ctx': <full ctx>, 'result': <r>}` (written `safe_dump`).

**target_path** is where compile+run happen and where these files live. Resolution:
- `config task` → `compile_and_run_program.skip_cache: True` ⇒ `target_path =
  <program_dir>/tmp`.
- else ⇒ a dedicated `cache` entry `task--program--<name>` (tags `[task,
  c36be4b9314a45e0, compile-and-run-program, 05437a1aae224270]`), `target_path =
  <cache_entry>/tmp`. A distinct `--path`/`work_path` gives a distinct build.
`work_path` (run cwd) defaults to `target_path`; `{pwd}` maps to `<cur_dir>/tmp`.

**Compile reuse decision** (`recompile` starts False unless `--recompile`):
1. Read `_repro_ctx_compile.json`. Missing ⇒ `recompile=True`. Present but
   `result.return != 0` ⇒ `recompile=True`.
2. Otherwise compare the cached compile context against the current run and force
   `recompile=True` if **any** differs:
   - a currently selected `compute` isn't in the cached `target.compute`;
   - `android-cpu` in compute **and** the cached `target--android-cpu.serial` differs
     from the current device serial;
   - the cached `host.os.uname` differs from the current one (Docker / WSL on a shared
     disk);
   - the cached `target_path_exe` no longer exists on disk.
3. If **no** recompile: `deep_merge` the cached `global` / `local` / `aggregated` and the
   cached `origin.params.compile` back into the live `ctx` (so later steps see the same
   toolchain/flags), **re-attach the non-serializable `selected-program.api_code`** from
   this run (it can't be JSON-round-tripped), and mark `_compiled=True` → the `compile`
   `uses` pipeline is skipped entirely.
4. If recompile: delete `_repro_ctx_compile.json`, run the `compile.uses` pipeline, then
   write a fresh snapshot. `_impact` records `self_time_compile[_with_cmeta]`.

The `run` step is analogous but simpler (writes `_repro_ctx_run.json` each run;
compilation invalidation removes the stale run snapshot first). The `all` step writes
`_repro_ctx_all.json`. Net effect: re-running a program re-uses the compiled binary and
its resolved context unless the target/host/serial/binary changed — while still
re-running the program each invocation.

## B. Android-CPU remote execution

Two tasks cooperate:

**`target--android-cpu`** (`store_global`, key `target--android-cpu`, `cache: True`,
`uses_before_init: setup adb`):
- `init` runs `adb devices`, filters by optional `--serial` (`arg2`), and — if several —
  prompts (or quietly picks 0). Stores the chosen serial/state in `local` and cache-keys
  the entry on `serial` (`cache_extra_params.serial`).
- `run` collects a rich device fingerprint over `adb -s <serial> shell` (`getprop`
  `ro.product.*`/`ro.soc.*`/`ro.board.*`, `uname -m`, `/proc/cpuinfo`,
  `/sys/devices/system/cpu/{online,possible}`), normalizes arch (arm64/arm/x86_64/x86),
  derives CPU feature flags (neon/asimd/sve/aes/… or sse/avx/…), core counts and
  perf-levels, and returns it as `features` (stored in `global['target--android-cpu']`).

**`setup-run`** builds the remote command sequence when `android-cpu` is in compute:
`adb -s <serial>` is the prefix for everything. Preparation `cmds` (run first, via a
`cmd` sub-call): wipe+`mkdir /data/local/tmp/lib`, `push` the exe to
`/data/local/tmp/<exe>`, `chmod 755`, `push` each `input_file` and each dynamic lib
(from `setup-compile.found_dynamic_libs`) into the tmp lib dir. The run command becomes
`adb -s <serial> shell "cd /data/local/tmp && export LD_LIBRARY_PATH=... && <exe> <args>"`
(with `simpleperf record -g --` inserted when `profile`). Output files are `pull`ed back
to the host (`adb ... pull`), and profile reports are generated (`simpleperf report`).
The compiler for the exe itself comes from the android-ndk clang tool + `lib-sysroot-android`
/ `lib-openmp-android` libs (appended by programs' `updates` under an `android-cpu` `if:`).

## C. `updates_cmd` — multi-command-line programs

A program can expose several *named command lines* via `updates_cmd:`; each is a patch
block (same match/update/append grammar as `updates`) applied **on top of** `updates`.
`cbench-automotive-susan` defines three (`corners` `-c`, `edges` `-e`, `smoothing` `-s`),
each overriding `setup-run`'s `cmd_main` and adding `tmp-output.pgm` to `output_files`
(`+output_files`):

```yaml
updates_cmd:
  corners:
    run: {uses: [{match: {task: setup-run,148f6c1fdb4247df},
                  update: {cmd_main: '{qinput_files.data} tmp-output.pgm -c'}}]}
    local_vars: {+output_files: ['tmp-output.pgm']}
  edges:    { ... -e ... }
  smoothing:{ ... -s ... }
```

Selection (in `select-program`): the command line comes from `arg4`/`--cmd`. If omitted
and multiple exist, it prompts (`updates_cmd_keys` sets/overrides the ordering; otherwise
sorted keys, default index 0). The chosen block is applied via the program category's
`update_desc`. So `cx program run cbench-automotive-susan cpu edges` runs the `-e` variant.
(`model-cnn-ylecun-mnist-pytorch` also uses `updates_cmd`, e.g. train vs infer.)

## D. `build-*` programs vs the compile template

`build-*` programs (`build-pytorch`, `build-pytorchvision`, `build-torch-cpp`,
`build-llama-cpp`) reuse the **same** template skeleton (target → compiler → cache →
repro), but their `updates.compile.uses` **append** a full real-build chain after
`customize2` and **replace the compile `cmd`** with an actual build:

- Set up the build toolchain by tag/name: extra `compiler lang: c`, `cmake`, `ninja`,
  host `msvc` (Windows), `python`, plus build-time `pip` packages, and compute libs
  (`lib-cuda`/`lib-cudnn`/`lib-openmp`) under `if:` compute gates.
- **Clone source into its own cache entry** via `clone-git-to-cache,86919b3cfdd443d2`
  (keyed by `url`/`checkout`; result at `global.clone-git-to-cache-<name>.path_to_git_repo`)
  — the source cache is **separate** from the program's `task--program--<name>` build
  cache. Submodules are initialised with a `cmd` sub-task.
- A program-specific `internal_func` (`customize_pytorch` / `customize_llama_cpp`)
  computes build env / cmake vars / check-file paths.
- The build itself is a `cmd` with `storage_key: compile-program` (so the repro-cache in
  deep dive #A still governs it) running e.g.
  `python -m pip install --no-build-isolation -v .` (pytorch) or
  `cmake … -G Ninja … && cmake --build .` (llama.cpp) in the cloned source / target dir.
- `run` swaps `setup-run`'s cmd to run the built artifact — `python program.py` for the
  Python builds, `llama-cli -m {model} -f {input}` for llama.cpp — pulling models/datasets
  via the `model,86f0effd07ad454d` and `dataset,30e20c7489f14f84` category tasks.

So the difference from a `test-nmm-*` program is **only in the compile step's content**
(a real multi-tool build vs a single compiler invocation) and the **extra source-clone
cache**; the driver, compute abstraction, repro-caching and run/finish machinery are
identical.

---

## The through-line

`_desc.yaml` **data + template inheritance** describe *what*; the **`task` engine**
(select-program, target, compiler, setup-compile, setup-run, cmd, finish-run) executes
*how*; the **`compute` list in `global.target`** is the switch that selects tools,
libraries, compilers and profilers; and **`tool` artifacts** supply both the toolchains
(via `compiler`'s `lang-*` tags + `features.flags`) and the libraries/runtimes/datasets
(via `setup name:` and the `dataset`/`model` categories).
