---
name: add-program
description: Add a new cMeta `program` artifact under `program/<name>/` — a compilable/runnable benchmark or app that inherits a template (e.g. `template-c-cpu`), declares its `local_vars`/`params`/`updates`, sets `constraints.supported_compute`, and runs via `cx program run <name> <compute>`. Handles the compute abstraction (cpu/cuda/android-cpu/…), compiler+library selection, and optional `CProgram` hooks (`customize`/`customize1`/`customize2`/`customize_run`). Use when the user asks to "add a program/benchmark", "make X compile and run via cMeta", "port a program to a new compute target", or "wrap a build (cmake/pip) as a program". Worked example: test-hello-c-cpu.
---

# add-program — author a cMeta `program` (build + run) artifact

A **program** artifact (`program/<name>/`, category `program,22788f3c30d04e6d`,
API v1) is a compilable/runnable benchmark or app. The category is a **thin delegator**:
`cx program run <name> <compute>` = `cx task run compile-and-run-program
--name=<name> --compute=<compute>`. All real behaviour is your program's `_desc.yaml`
(patched onto a **template**) executed by the `task` engine.

> **Read first:** `docs/cmeta-aops/program-and-compute.md` (the full model + deep dives),
> and these worked artifacts: `program/template-c-cpu/` (the base template),
> `program/test-nmm-c-cpu/` (simplest concrete, CPU+Android), `program/test-nmm-nvcc-cuda/`
> (CUDA), `program/cbench-automotive-susan/` (`updates_cmd` + input dataset),
> `program/build-llama-cpp/` (a real cmake build). The `add-task` / `add-tool` skills
> cover the tasks/tools a program pulls in.

Authoring = a few files under `program/<name>/`:

| File | Role | Required |
|------|------|----------|
| `_cmeta.json` | identity + **`constraints.supported_compute`** (the compute filter) | **Yes** |
| `_desc.yaml`  | `inherits` a template + `local_vars` / `params` / `updates` / `updates_cmd` | **Yes** |
| `src/…`       | the program's source files (referenced by `local_vars.src_file_names`) | usually |
| `api_v1.py`   | optional `CProgram` hooks for imperative customization | only if needed |
| `tests/*.bat`, `_test_*.bat` | CLI test recipes mirroring siblings | recommended |

Sibling programs use **`_cmeta.json`** (not `.yaml`) — match that.

---

## 1. Decide two things first

1. **Which template to inherit.** Today the base is
   **`template-c-cpu,649899ef3f004e4a`** — a compile-then-run skeleton that works for
   C/C++/CUDA/… by setting `local_vars.lang` and patching the compiler step. Even
   "build" programs (cmake/pip) inherit it and replace the compile *command*. Clone the
   nearest existing program whose shape matches your intent.
2. **Which compute targets** it supports: any subset of `cpu`, `cuda`, `android-cpu`,
   `metal`, `rocm`, `xpu`, `tpu`, … (hybrids allowed). This becomes
   `constraints.supported_compute` and gates every OS/compute-specific dependency.

---

## 2. Scaffold the artifact

**Repo-qualify** the name (a bare `cx program add <name>` lands in the `local` repo):

```bash
cx program add ctuninglabs@cmeta-aops:test-hello-c-cpu   # writes program/test-hello-c-cpu/_cmeta.json (fresh UID, category: program,22788f3c30d04e6d)
```

(Programs use `_cmeta.json`, the default — do **not** pass `--yaml`.) `cx program add`
maps to the base `create_`; it writes only `_cmeta.json` and **indexes it immediately**
with that initial meta. Fix its auto-generated `copyright:` to `Copyright (C) 2025-2026
Grigori Fursin and cTuning Labs. All rights reserved.`, then add your `constraints`.

> **Reindex gotcha (verified):** because `cx program add` already indexed the artifact,
> editing `_cmeta.json` afterwards (e.g. adding `constraints.supported_compute`) is **not**
> picked up by the incremental `cx program index <ref>` — it refuses with "artifact
> already exists" and leaves the **stale** meta in the index, so the compute filter fails
> at run time (`couldn't find "program" artifact(s) … with constraints …`). After any
> `_cmeta.json` change to an already-indexed artifact, run a full **`cx --reindex`**.
> A `_desc.yaml`- or `src/`-only edit needs no reindex at all.

If you instead hand-author the folder from scratch (it isn't indexed yet), register it
with `cx program index ctuninglabs@cmeta-aops:<name>` (or `cx --reindex`).

Fastest correct route: copy `program/test-nmm-c-cpu/` and edit.

---

## 3. `_cmeta.json` — identity + compute filter

```json
{
  "artifact": "<fresh 16-hex uid>",
  "authors": "Grigori Fursin",
  "category": "program,22788f3c30d04e6d",
  "constraints": { "supported_compute": ["cpu"] },
  "copyright": "Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.",
  "note": "one-line description"
}
```

`select-program` (run inside `compile-and-run-program`) only picks your program if
`constraints.supported_compute` matches the requested `compute` (AND-match; a hybrid like
`cpu,cuda` needs both listed). Omit/leave it and the program is selectable for any target
— usually wrong.

---

## 4. `_desc.yaml` — inherit a template and patch it

```yaml
authors: Grigori Fursin
copyright: Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.

inherits:
  - template-c-cpu,649899ef3f004e4a

# Per-program facts threaded through ctx['tasks']['local'].
local_vars:
  lang: c                         # c | cpp | cuda | objc | ...  (selects the compiler tool via lang-<lang> tag)
  src_dir: src                    # where sources live (relative to the program dir)
  src_file_names:                 # compiled in order
    - program.c
  target_file_name: program       # base name of the produced executable
  output_files:                   # files the run produces (cleaned before, collected after)
    - tmp-cmeta-program-stats.json
  result_files:                   # {label: file} surfaced in the result
    stats: tmp-cmeta-program-stats.json
# input_files: { data: '{{local.dataset.path}}' }   # for programs that take an input
# run_time_env: { MY_VAR: '1' }

# Compile/run defaults (params_os: for per-OS overrides; params.compute: for a default target).
params:
  compile:
    openmp: True
    d:                            # -D defines
      XOPENME:

# Patch the inherited compile/run pipelines (match a step, then update/append/prepend/substitute).
updates:
  compile:
    uses:
      - match: { task: compiler,f3925b201c704bde }
        update: { lang: c }

      - match: { internal_func: customize2 }
        append:
          # Libraries this program links — gate by compute with if:
          - task: setup,a2f9b61079ce4333
            if: '{{global.target.compute|$[]}} == ["cpu"]'
            name: lib-xopenme,c7b96678a7734510

  run:
    uses:
      - match: { task: setup-run,148f6c1fdb4247df }
        update:
          # The program's command-line arguments (templated; params.* are user-overridable).
          cmd_main: '{{params.dim|1500}} {{params.repeat|3}}'
```

Key ideas:
- **The template provides `all`/`compile`/`run` sub-pipelines**; you only *patch* them.
  `all` runs the `target` task (→ `global.target.compute`); `compile` runs `compiler` +
  `setup-compile` + `cmd`; `run` runs `setup-run` + `cmd` + `finish-run`. See the doc.
- **Pull libraries/tools by appending `setup` steps** after `customize2` (compile) or
  `customize_run` (run), each gated with `if:`/`if_os:` on `{{global.target.compute}}` or
  the host OS. The compiler and its flags come automatically from the `compiler` task +
  the compiler tool's `features.flags`; `setup-compile` auto-discovers every
  `global['lib-*']` you set up and adds their includes/libs.
- **`updates_cmd:`** defines several *named* command lines (same grammar), selected via
  `arg4`/`--cmd` (e.g. susan's `corners`/`edges`/`smoothing`). Use `+output_files` in a
  variant's `local_vars` to add per-command outputs.
- Templating reads `ctx['tasks']`: `{{global.target.compute}}`, `{{global.<tool>.qpath}}`,
  `{{params.<x>|default}}` (`|$None` → Python None, `|$[]` → empty list, `|` → empty
  string), `{{local.<x>}}`, `{{os_sep}}`.

---

## 5. `src/` — the source

Put sources under `local_vars.src_dir` (conventionally `src/`); list them in
`src_file_names`. The compiled executable and all `tmp*` build/run artifacts land in the
program's **cache** build dir (`target_path`), not in `src/`. The program is expected to
write its declared `output_files`/`result_files` (e.g. a small `tmp-cmeta-program-stats.json`)
into the run cwd so `finish-run` can collect them.

---

## 6. `api_v1.py` — `CProgram` hooks (only if needed)

Subclass `CProgram` for imperative customization the YAML can't express. Hooks are called
from the template pipeline via `internal_func … internal_func_from_local_key:
selected-program` (declared safe, so a missing hook is skipped):

```python
"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os

from program_22788f3c30d04e6d.api.cprogram import InitCProgram   # category UID, same in every program's api

class CProgram(InitCProgram):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize2(self, ctx, **misc):
        # Runs in the COMPILE pipeline (after target+compiler are resolved).
        # misc: desc=<merged _desc>, params=<program params>, extra_desc_params=<the entry>
        compute = ctx['tasks']['global']['target']['compute']
        uname   = ctx['tasks']['global']['host']['os']['uname']

        if uname == 'windows' and any(c in compute for c in ('cpu', 'cuda')):
            ctx['tasks']['local']['params']['compile'].setdefault('d', {})['WINDOWS'] = None

        return {'return': 0}
```

Hook points (all optional): `customize_pre` (very early, adjust params), `customize` /
`customize1` (in `all`, around the `target` step), `customize2` (in `compile`, after
compiler resolved — the usual place to inject defines/deps), `customize_run` (start of
`run`), plus program-specific funcs you append yourself (e.g. `customize_llama_cpp`).
Return `{'return':0,...}`; touch `ctx['tasks']['local']`/`['global']` to influence later
steps.

---

## 7. Index, run, verify

```bash
cx --reindex                                                # if you edited _cmeta.json after `cx program add` (see gotcha above)
cx program find test-hello-c-cpu                            # confirm it resolves in THIS repo

cx program compile test-hello-c-cpu cpu -j --quiet         # compile only (skip_run); -j trace; --quiet auto-picks selections
cx program run     test-hello-c-cpu cpu -j --quiet         # compile + run
cx program run     test-hello-c-cpu cpu --recompile --quiet # force a rebuild (ignore repro cache)
cx program run     test-hello-c-cpu cpu --quiet -- --extra-arg  # args after -- reach the program (unparsed)
cx program clean                                           # remove all tmp*/ build dirs across programs
```

- **Use `--quiet` (or `--con`) for the first build in a non-interactive shell.** When the
  host has several compilers for `lang-<lang>` (e.g. gcc + clang + msvc for C), the
  `compiler` task **prompts to pick one** — which raises `EOFError` under CI/agents.
  `--quiet` auto-selects `0`; `--con` lets you answer; or pin it (e.g.
  `--use.compiler-c.name=gcc,...`). The first CPU build also **sets up a compiler
  toolchain and can take minutes** (subsequent runs reuse it from the cache).
- `-j`/`--verbose` prints which tasks reused global/cache and the resolved compile/run
  commands (also saved as `tmp-cmeta-compile-program{ext}` / `tmp-cmeta-run-program{ext}`
  scripts in the build dir).
- The build lives in a `cache` entry `task--program--<name>` (unless
  `config task --meta.compile_and_run_program.skip_cache`). Re-running reuses the compiled
  binary via the **repro cache** (`_repro_ctx_compile.json`) unless compute/host/serial/
  binary changed — use `--recompile` or `--clean` to force.
- Test each declared compute target you claimed in `constraints.supported_compute`
  (only those the host can actually build — e.g. `cuda` needs a CUDA toolchain).

Add `tests/*.bat` (or `_test_cpu.bat`) mirroring siblings, e.g. `cx program run
test-hello-c-cpu cpu`.

---

## 8. Worked example — `test-hello-c-cpu` (single-file C, CPU)

`program/test-hello-c-cpu/_cmeta.json`
```json
{
  "artifact": "<fresh 16-hex uid>",
  "authors": "Grigori Fursin",
  "category": "program,22788f3c30d04e6d",
  "constraints": { "supported_compute": ["cpu"] },
  "copyright": "Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.",
  "note": "minimal hello-world C program with a stats output file"
}
```

`program/test-hello-c-cpu/_desc.yaml`
```yaml
authors: Grigori Fursin
copyright: Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.

inherits:
  - template-c-cpu,649899ef3f004e4a

local_vars:
  lang: c
  src_dir: src
  src_file_names:
    - program.c
  target_file_name: hello
  output_files:
    - tmp-cmeta-program-stats.json
  result_files:
    stats: tmp-cmeta-program-stats.json

params:
  compile:
    fast: True          # -O3

updates:
  run:
    uses:
      - match: { task: setup-run,148f6c1fdb4247df }
        update:
          cmd_main: '{{params.name|world}}'
```

`program/test-hello-c-cpu/src/program.c`
```c
#include <stdio.h>
int main(int argc, char** argv) {
    const char* who = argc > 1 ? argv[1] : "world";
    printf("Hello, %s!\n", who);
    FILE* f = fopen("tmp-cmeta-program-stats.json", "w");
    if (f) { fprintf(f, "{\"hello\": \"%s\"}\n", who); fclose(f); }
    return 0;
}
```

Then:
```bash
cx --reindex                                   # _cmeta.json changed after `cx program add`
cx program run test-hello-c-cpu cpu --quiet    # sets up a C compiler, builds hello, runs it → "Hello, world!" + {"hello":"world"}
```

(Verified end-to-end on Windows: prints `Hello, world!` and `finish-run` collects
`tmp-cmeta-program-stats.json` = `{"hello": "world"}`.)

---

## 9. Checklist / gotchas

- [ ] Created/registered with the **repo-qualified** name (`cx program add|index
      ctuninglabs@cmeta-aops:<name>`), not a bare form (which lands in `local`).
- [ ] `_cmeta.json` (json, matching siblings); fixed the auto-generated `copyright:`.
- [ ] **`constraints.supported_compute`** set to exactly the targets you support — and ran
      **`cx --reindex`** after editing `_cmeta.json` (incremental `cx program index` won't
      refresh an already-indexed entry, so the compute filter would use stale meta).
- [ ] `_desc.yaml` `inherits` a real template `alias,UID`; referenced tasks/tools/libs by
      `alias,UID` (look up UIDs with `cx task find` / `cx tool find`).
- [ ] `local_vars.lang` matches a compiler tag (`lang-c`/`lang-cpp`/`lang-cuda`); flipped
      it in the `compiler` (and `setup-compile`) steps via `updates` if not C.
- [ ] Compute/OS-specific deps gated with `if: '{{global.target.compute|$[]}} == [...]'`
      / `if_os:`; libraries appended after `customize2` (compile) so `setup-compile`
      discovers them.
- [ ] Sources in `src/` and listed in `src_file_names`; program writes its declared
      `output_files`/`result_files`.
- [ ] `api_v1.py` (if any) imports `from program_22788f3c30d04e6d.api.cprogram import
      InitCProgram` (the **category** UID — identical in every program's api).
- [ ] Verified with a real `cx program run <name> <compute> -j --quiet` for each supported
      target the host can build (`--quiet` avoids the interactive compiler-pick `EOFError`);
      used `--recompile`/`--clean` to bust the repro cache when testing.
- [ ] Verbatim proprietary copyright headers preserved; didn't touch author scratch
      siblings (`*.yaml2`, `*.py2`, `*.arc1`, `tmp*/`, `cmeta-task-saved-*.json`).
```
