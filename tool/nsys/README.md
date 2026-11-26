# tool/nsys: NVIDIA Nsight Systems' command line

`cx tool setup nsys` finds `nsys` where a CUDA toolkit or an Nsight Systems install put it (`extra_paths` of
`_desc.yaml`: a toolkit's `bin`, `nsight-systems*/bin`, `/opt/nvidia/nsight-systems/*/bin`, the Windows
installer's folder). When none is found, or not the version asked, it installs Nsight Systems without root from
NVIDIA's CUDA redistributable archives (https://developer.download.nvidia.com/compute/cuda/redist): the component
`nsight_systems` of a CUDA release, checked against the sha256 of NVIDIA's list and unpacked into the tool's cache
entry (`content/<CUDA release>/target-<platform>/nsys`). tool/nvcc's `redist.py` reads NVIDIA's lists.

```
cx tool setup nsys                          # found, else the Nsight Systems of the newest CUDA this driver runs
cx tool setup nsys --version=2026.1.3       # the newest CUDA release that carries it (a prefix or the full version)
cx tool setup nsys --version=latest         # the Nsight Systems of the newest CUDA this driver runs
cx tool setup nsys --status                 # what is found here against that newest one
```

Programs ask for it with `--profile_cuda` (task/setup-run): `nsys profile --trace=cuda,nvtx`, then the summary of
the CUDA kernels (`nsys stats --report cuda_gpu_kern_sum`). An older Nsight Systems may record no CUDA activity on a
newer GPU or driver - its report then "does not contain CUDA kernel data" (or "CUDA trace data"): ask for a newer
one for the run, `--use.nsys.version=latest`.

## Only the part of a run the program marks

`--profile_cuda_range` makes Nsight Systems wait for a mark of the program, so that the report holds the measured
part and not the start-up, the loading of a model or the warm-up:

```
cx program run <program> --profile_cuda --profile_cuda_range=cudaProfilerApi            # cudaProfilerStart ... cudaProfilerStop
cx program run <program> --profile_cuda --profile_cuda_range=nvtx:decode                # while the NVTX range "decode" is open
cx program run <program> --profile_cuda --profile_cuda_range=nvtx:decode@mydomain       # ... of that NVTX domain (@*: any)
cx program run <program> --profile_cuda --profile_cuda_range=cudaProfilerApi --profile_cuda_range_end=repeat   # every range
```

- `cudaProfilerApi`: from `cudaProfilerStart()` to `cudaProfilerStop()` (`cuda_profiler_api.h`; in PyTorch
  `torch.cuda.profiler.start()` / `stop()`). `program/test-nmm-nvcc-cuda` marks its measured part when built with
  `--compile.d.CUDA_PROFILER_RANGE`.
- `nvtx:<range>[@<domain>]`: while that NVTX range is open (`nvtxRangePush`, `torch.cuda.nvtx.range_push`).
  Nsight Systems compares the name with *registered* NVTX strings only unless the program is told otherwise, and a
  range pushed with a plain string then starts nothing: the task sets `NSYS_NVTX_PROFILER_REGISTER_ONLY=0` for the
  program (`--env-var` of nsys).
- `--profile_cuda_range_end` is what the end of the range does, in nsys's own words: `stop` (the default here: the
  recording ends, the program runs on), `repeat` or `repeat:<N>` (every range, or the first N - each gets a report
  of its own, `cuda_profile.<n>.nsys-rep`, and its own summary), `none`, `stop-shutdown`, `repeat-shutdown:<N>`.
  nsys's own default is `stop-shutdown`: the session ends with the first range, and nsys then ends the program too
  (`--kill`), before it writes its results - so the task always says the end.
- A program that never meets its range leaves no report ("No reports were generated"): the run fails and says
  "Nsight Systems recorded nothing - the program never met the range ...".
- The options are asked of the nsys that is used (its `profile --help`): one without them is said, with the way to a
  newer one (`--use.nsys.version=latest`).
- **One profiled run at a time in a build folder.** Two runs of one program under nsys at the same time, in the same
  folder, left nsys's agent and one program behind on Windows (the program had finished and could not exit; its
  console window stayed open). `nsys sessions list` names what is still open and `nsys shutdown --session=<its
  name>` ends it with its program.

Linux (x86_64, arm64) and Windows (x86_64) have archives; macOS has no Nsight Systems command line.
