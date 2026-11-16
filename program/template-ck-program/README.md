# template-ck-program

The hooks of programs converted from the Collective Knowledge (CK) format - cBench, PolyBench/C and
PolyBench/GPU in the repository cmeta-ck-legacy, converted by its task `import-ck`. They do what CK's
program pipeline did around a program's command line, on the host CPU, CUDA, OpenCL and Android over adb
(an iPhone app, run through devicectl, has no redirection: its standard output and error are left as they
are).

A program uses them by inheriting this template after `template-c-cpu`, with no `api_v1.py` of its own
(task `select-program` gives a program without hooks those of the first artifact it inherits that has
some):

```yaml
inherits:
  - template-c-cpu,649899ef3f004e4a
  - template-ck-program,f7fab3bed78041d1
```

and calls `customize_ck_run` after its dataset step:

```yaml
updates:
  run:
    uses:
      - match:
          internal_func: customize_run
        append:
          - task: dataset,30e20c7489f14f84
            dataset_tags: doc,txt
            name: '{{params.dataset|$None}}'
            filename: '{{params.dataset_file|$None}}'
          - internal_func: customize_ck_run
            internal_func_from_local_key: selected-program
            internal_func_safe: True
```

## What the program's `local_vars` ask for

| Key | Hook | What it does |
|---|---|---|
| - | `customize2` | `WINDOWS` defined for a build that runs on a Windows host (cpu, cuda, opencl) |
| `ck_legacy_c: True` | `customize2` | GNU C89 with GCC and clang (`-std=gnu89`, what GCC 14 and clang 16 made errors kept as warnings) for sources written before C99; MSVC needs nothing |
| `ck_size_vars: [NI, NJ ...]` | `customize2` | PolyBench: `--compile.size=mini\|small\|standard\|large\|extralarge` replaces these defines by the header's size; `--compile.dump=yes\|no` keeps or drops `POLYBENCH_DUMP_ARRAYS` (yes with CK's sizes, no with a size) |
| `ck_cpu_check: True` | `customize2` | PolyBench/GPU: `CK_CPU_CHECK` defined - the CPU reference the CK versions commented out (an `#ifdef CK_CPU_CHECK` block in the converted sources) is compiled, so "Non-Matching CPU-GPU Outputs" compares the GPU's result with the CPU's; `--compile.check=no` leaves it out, as CK did (a build of its own) |
| `ck_number_from_dataset: True` | `customize_ck_run` | the dataset is a number: `{{local.ck_number}}` (its `number`, else its file's content) |
| `ck_dataset_more_files: True` | `customize_ck_run` | the other files of the dataset, in its order, become the input files `data1`, `data2` ... (`{qinput_files.data1}`) |
| `ck_run_files: [file ...]` | `customize_ck_run` | files of the program's `src/` copied (host) or pushed (device) into the run's folder |
| `ck_dump_file: <file>` | `customize_ck_run` | an output that exists only when the arrays are dumped |
| `ck_redirect_stdio: True` | `customize_ck_run` | `{{local.ck_redirects}}` = `> tmp-output1.tmp 2> tmp-output2.tmp`, both added to the outputs (not on iOS) |
| `ck_opencl_device: True` | `customize_ck_run` | OpenCL: `CK_COMPUTE_PLATFORM_ID` and `CK_COMPUTE_DEVICE_ID` in the run's environment - `--opencl_platform` and `--opencl_device` (numbers, or `--opencl_device=<a word of the device's name>`), else the first GPU the `opencl` target found |

The dataset step gives, with its `path`, the dataset's `files` in its own order (`files` of the
dataset's `_desc.yaml`) and its `number` - see `task/dataset`.
