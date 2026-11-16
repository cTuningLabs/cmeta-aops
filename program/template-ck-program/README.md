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
| `ck_size_vars: [NI, NJ ...]` | `customize2` | PolyBench: `--compile.size=mini\|small\|standard\|large\|extralarge` replaces these defines by the header's size; `--compile.n=<N>` makes every one of them N (square arrays; not with a size); `--compile.dump=yes\|no` keeps or drops `POLYBENCH_DUMP_ARRAYS` (yes with CK's sizes, no with a size or an N). Each choice is a build of its own |
| `DATA_TYPE` among the defines | `customize2` | `--compile.precision=float\|double` sets it (PolyBench: double on the CPU, float on CUDA and OpenCL by default) |
| `CT_REPEAT_MAIN` in `run_time_env` | - | `--repeat=<n>` repeats the kernel (CK's variable); `--calibrate[=<seconds>]` of compile-and-run-program raises it until the run lasts about the target (4 s as CK; `--calibrate_max`, 10 rounds) |
| `ck_cpu_check: True` | `customize2` | PolyBench/GPU: `CK_CPU_CHECK` defined - the CPU reference the CK versions commented out (an `#ifdef CK_CPU_CHECK` block in the converted sources) is compiled, so "Non-Matching CPU-GPU Outputs" compares the GPU's result with the CPU's; `--compile.check=no` leaves it out, as CK did (a build of its own) |
| `ck_number_from_dataset: True` | `customize_ck_run` | the dataset is a number: `{{local.ck_number}}` (its `number`, else its file's content) |
| `ck_dataset_more_files: True` | `customize_ck_run` | the other files of the dataset, in its order, become the input files `data1`, `data2` ... (`{qinput_files.data1}`) |
| `ck_run_files: [file ...]` | `customize_ck_run` | files of the program's `src/` copied (host) or pushed (device) into the run's folder |
| - | `customize_summary` | what the summary that compile-and-run-program prints after the run says of a CK program: the defines it was built with (`defines:`), the GPU result against the CPU's (PolyBench/GPU, the count the program prints), the OpenCL device of the run, PolyBench's size, and what the program printed - CK's `tmp-output1.tmp` and `tmp-output2.tmp` as the block's standard output and error sections |
| - | `customize_output_check` | the reference outputs (`--check_output`): the cases of a program are told apart by the defines it was built with (`compile.d.<NAME>` with size / n / precision / dump applied - every define it declares but `XOPENME` and `WINDOWS`), PolyBench's `compile.size` and `compile.dump` (`key_params`), and the kernel's `repeat` (after a `--calibrate`, the one it settled on) unless the program's `output_check: invariant_of_repeat: True`, and the other parameters of the run its environment takes (`{{local.params.<name>|<default>}}` in its `run_time_env`: the codelet's `--time=day\|night`, CK's `CT_TIME`), with their default when not given. A PolyBench program (with `ck_size_vars`) also gets a relative `tolerance` of `1e-6` for its floating-point dump, so a reference holds across compilers and architectures (x86 and arm64 round differently); the program's own `output_check.tolerance` overrides it. Its dump file (`ck_dump_file`) is compared only when the arrays are dumped |
| `ck_dump_file: <file>` | `customize_ck_run` | an output that exists only when the arrays are dumped |
| `ck_redirect_stdio: True` | `customize_ck_run` | `{{local.ck_redirects}}` = `> tmp-output1.tmp 2> tmp-output2.tmp`, both added to the outputs (not on iOS) |
| `ck_opencl_device: True` | `customize_ck_run` | OpenCL: `CK_COMPUTE_PLATFORM_ID` and `CK_COMPUTE_DEVICE_ID` in the run's environment - `--opencl_platform` and `--opencl_device` (numbers, or `--opencl_device=<a word of the device's name>`), else the first GPU the `opencl` target found |

The dataset step gives, with its `path`, the dataset's `files` in its own order (`files` of the
dataset's `_desc.yaml`) and its `number` - see `task/dataset`.
