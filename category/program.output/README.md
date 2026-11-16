# program.output

The reference outputs of a program: what a run is expected to produce, kept so that a later run - on another
machine, compiler or target - can be checked against it. An artifact per program, named after it, in any
repository; a **case** per command, input and parameters inside it, a folder named by a UID:

```
program.output/cbench-consumer-jpeg-c/
  _cmeta.yaml                        program: cbench-consumer-jpeg-c,<uid>; tags
  a47e54b790cc4d9a/case.json         the key of the case, the facts of the recording, every output file with its digests
  a47e54b790cc4d9a/tmp-output.tmp    the output itself, kept when small (up to 10 MB)
  bc1ccc2b8366492d/...               another input
```

`case.json`:

```json
{"key": {"program": "polybench-cpu-2mm", "cmd": "default", "dataset": null, "sub_dataset": null, "dataset_file": null,
         "params": {"compile.size": null, "compile.dump": null, "compile.d.DATA_TYPE": "double", "compile.d.NI": "16",
                    "compile.d.NJ": "16", "compile.d.NK": "16", "compile.d.NL": "16", "compile.d.POLYBENCH_DUMP_ARRAYS": "YES",
                    "compile.d.POLYBENCH_PADDING_FACTOR": "0", "repeat": 1}},
 "recorded": {"date": "...", "host": {...}, "cpu": "...", "gpu": [], "compute": ["cpu"], "tools": "...", "command": "...",
              "params": {"name": "polybench-cpu-2mm", "compute": "cpu", "repeat": 1}, "calibration": null, "times": {...}},
 "files": {"tmp-ck-output-dump.txt": {"size": 7871, "sha256": "...", "sha256_lf": "...", "sha256_nan": "...", "kept": true},
           "tmp-output2.tmp": {"size": 0, "sha256": "...", "sha256_lf": "...", "sha256_nan": "...", "kept": true}}}
```

The key tells the cases apart - never the folder's name: the command, the dataset, its sub-dataset and file,
and the parameters the program says matter (`key_params`, dotted names read from the request; `key_values`,
values given as they are - what a hook computes: for a CK program the defines the build was made with, with
`--compile.size`, `n`, `precision` and `dump` applied, and the kernel's `repeat`). The target is not part of it
(a reference is meant to hold across targets; the one it was recorded on is a fact of `recorded`); a program
that wants it lists `compute` among its key parameters. `recorded` keeps the facts: the host, the targets, the
tools, the command, the parameters of the request (`params`), the calibration of the repeat when there was one
(`--calibrate`: the rounds, the repeat it settled on, the time) and the times of the run.

## Recording and checking

`compile-and-run-program` does both after a run (`cx program run <program> <target> ...`):

```bash
cx program run cbench-consumer-jpeg-c cpu --check_output                       # compared with the reference, or recorded when there is none
cx program run cbench-consumer-jpeg-c cpu --check_output --output_repo=cmeta-repo-ck-legacy-program-output   # recorded into that repository
cx program run cbench-consumer-jpeg-c cpu --check_output=validate              # an error without a reference
cx program run cbench-consumer-jpeg-c cpu --check_output=record --overwrite_output   # the reference made again
cx task run test-ck-programs --programs=cbench-* --all_datasets --extra="--check_output --output_repo=..."  # every input
```

A recording goes into `--output_repo` (`local` by default: a shared repository only when asked); the artifact is
made there when it is not. A check finds the case in the artifacts of the program's name in every plugged
repository (the first found). A file is the same by its SHA-256, or but for the line ends (`sha256_lf`) or the
spelling of NaN (`sha256_nan`), or - when the program gives a `tolerance` - when every number of a text file is
within it (relative, with an absolute floor of the same value) and the text around the numbers is the same; the
lines `ignore_lines` names are left out of all of it; a file the reference lacks is added to it, a file neither the
reference nor the run made is the same; a difference fails the run. A GPU program of PolyBench compares its
standard output without the lines that name the device: its reference says that the GPU's result matched the
CPU's, and so holds on any device - recorded on an NVIDIA GPU, validated on an Intel, Apple or PowerVR one. The verdict is a `check:` line of the run
summary and `output_check` of the result (`--json_file`).

## What a program says: `output_check` of its `_desc.yaml`

```yaml
output_check:
  files: [tmp-output.tmp, tmp-output2.tmp]   # the outputs compared; default: output_files minus what the run printed and its times
                                    # (tmp-output1.tmp, tmp-output2.tmp, tmp-ck-timer.json) - listed, they are compared: CK compared
                                    # the standard error of every program, and the standard output where the result is
  key_params: [compile.size]        # parameters of the key (dotted names read from the request)
  key_values: {variant: a}          # values of the key given as they are (a hook adds the defines and the repeat for CK programs)
  invariant_of_repeat: True         # the output does not depend on the kernel's repeat: no repeat in the key (CK's output_invariant_of_repeat)
  ignore_lines: ['^GPU Device ']    # regular expressions: a line of a text output that matches one is left out of every comparison
                                    # (the device a GPU program names) - the digests are of the rest, the file is kept whole
  tolerance: 0.001                  # of the numbers in a text file
  skip: [tmp-output.tmp]            # never compared: something of the machine or the moment in it
  artifact: shared-codelet-filter   # the program whose references these are (shared)
updates_cmd:
  encode:
    output_check:                   # for one command
      skip: [tmp-output.tmp]
```

A program's hooks may add to the rules: `customize_output_check(ctx, rules)` - `template-ck-program` adds the
defines of the build (`key_values`: `compile.d.NI` ...), PolyBench's size and dump (`key_params`) and the
kernel's `repeat` (`key_values`). The parameters of a CK program a case is keyed by are the ones of its command
line: `--repeat=<n>` (`--calibrate` settles it), `--compile.size=<name>`, `--compile.n=<N>`,
`--compile.precision=float|double`, `--compile.d.<NAME>=<value>`, `--compile.dump=yes|no`.

## On the Hugging Face Hub

A repository of references is a cMeta repository like any other: pulled with `cx repo pull hf://<owner>/<name>`
(cMeta 0.43+, no git needed; a private repository with `--identity=<token secret>`), recorded into with
`--output_repo=<its alias>`, pushed back with `cx task run upload-to-hf <its folder> <owner>/<name>` - for
instance `ctuning/cmeta-repo-ck-legacy-program-output`, the references of the CK legacy benchmarks of
cmeta-ck-legacy.
