# Compute targets: selecting, combining and comparing them

A **target** is the hardware a program builds for and runs on. Each one is a task
`task/target--<name>`: it detects the device (GPUs, drivers, versions), records them as the
target's features, sets `CMETA_TARGET_<NAME>=1` (and `=0` for the others), and has an `sdk`
step that sets up what builds need (the CUDA toolkit, the Vulkan SDK, ...). The `target` task
in this folder resolves the list a program asks for.

## Selecting targets

```bash
cx program targets                                  # the targets this cMeta knows
cx program run <program> --compute=cuda             # or --target=cuda, or: cx program run <program> cuda
cx program run <program> --compute=cpu,cuda         # several targets
cx program run <program> --compute                  # asks which ones (several can be picked)
```

- The default is `cpu`.
- `--target` is `--compute` by another name.
- A program runs only on targets it declares in `constraints.supported_compute` (its
  `_cmeta.json`); with several targets it must declare all of them.
- The selected targets reach every step of the pipeline:
  - `{{global.target.compute}}` is the list;
  - `{{global.target.cmeta_targets}}` is the same as text (`cpu,cuda`);
  - `{{global.target.cmeta_targets_tag}}` is the same for folder names (`cpu-cuda`): a comma
    splits an unquoted path in `cmd.exe` and breaks `-Wl,...` linker flags;
  - `{{global.target.features.<target>}}` holds what was detected, for example
    `features.cuda.devices[].compute_cap`;
  - the environment has `CMETA_TARGETS` and `CMETA_TARGET_<NAME>`.

| Target | What it is |
|---|---|
| `cpu` | the host CPU (the CPU inventory, with a host fingerprint) |
| `cuda` | NVIDIA GPUs (`tool/cuda`: nvidia-smi; the SDK step sets up `nvcc`) |
| `vulkan` | any Vulkan GPU (`tool/vulkan`; the SDK step sets up `tool/vulkan-sdk`) |
| `opencl` | any OpenCL GPU (`tool/opencl`: the platforms and devices from the ICD loader, without an SDK; on Linux an Intel GPU gets `tool/intel-gpu-runtime` first, so its ICD joins the others). CPU-only OpenCL fails unless `--use.target--opencl.allow_cpu` |
| `metal` | the Apple GPU (system_profiler) |
| `rocm` | AMD GPUs (ROCm) |
| `xpu` | Intel GPUs (oneAPI) |
| `npu-intel` | the Intel NPU, Meteor Lake and newer (its PCI ID, generation and driver, found without any SDK; its stack is OpenVINO). On Linux x86_64 it then gets `tool/intel-npu-runtime`, the user-space driver the kernel's `intel_vpu` does not bring (`--use.target--npu-intel.skip_runtime` skips it) |
| `openvino` | the OpenVINO stack: with a device target it runs there (`npu-intel` -> NPU, `xpu` -> GPU, `cpu` -> CPU); alone, on every device OpenVINO finds |
| `android-cpu` | an Android device over adb (`--serial`) |
| `android-gpu` | the GPU of that device: its Vulkan devices (`cmd gpu vkjson`), GLES driver and OpenCL library (public or not). Programs are built with the NDK and run over adb, as for `android-cpu`. From the adb shell, a vendor `libOpenCL.so` may find its platform only when loaded in the vendor namespace (`android_load_sphal_library`) |
| `android-npu` | the NPU of that device, as an adb shell program reaches it: the NNAPI accelerators (`google-edgetpu`, `mtk-mdla`, ...) and the vendor stack (Samsung ENN: app only; MediaTek APU: NNAPI; Google TPU: NNAPI and LiteRT; Qualcomm: QNN). Fails without an NNAPI accelerator, saying what the vendor stack needs |
| `tpu`, `opu-lumai` | placeholders: fail until supported |

## Several targets at once

What a program does with `--compute=a,b` is up to the program:

| Program | With several targets |
|---|---|
| `llama-cpp` (release build) | CPU plus one GPU: the GPU build, which has the CPU backend too. `--ngl=N` keeps N layers on the GPU and the rest on the CPU. Two GPU targets: an error (a release has one GPU backend). |
| `build-llama-cpp` | builds every backend listed (`cuda,vulkan` gives one binary with both); the run uses all GPUs unless `--devices=CUDA0` picks some; `--ngl`, `--split_mode`, `--tensor_split` split the model |
| `test-ollama` | `--ngl=N` sets Ollama's `num_gpu` (layers on the GPU) |
| `test-vllm`, `build-vllm` | one device type (cuda, rocm, xpu or cpu); `--cpu_offload_gb` keeps part of the weights in CPU memory |
| `build-pytorch` | `USE_CUDA`, `USE_MPS`, `USE_ROCM`, `USE_XPU` for each target listed |
| `test-openvino` | runs on each device listed (`cpu,npu-intel`: the CPU and the NPU side by side), each named in `compile_model`, never AUTO; with `openvino` alone, every device OpenVINO finds |

## Comparing targets on one machine

- Each program run happens in a build folder under the program's cache entry,
  `task--program--<program>/<folder>`. The folder is `tmp` unless `--target_tmp=<name>` names it.
- A build is reused while the targets stay the same. With other targets in the same folder,
  the program is built again.
- `--target_tmp=auto` gives every set of targets its own folder: `tmp-cuda`, `tmp-vulkan`,
  `tmp-cpu-cuda`. The builds stay side by side, and switching targets costs nothing after the
  first build.
- To make `auto` the default:

  ```bash
  cx config set task --meta.compile_and_run_program.target_tmp=auto
  cx config show task
  cx config unset task --meta.compile_and_run_program.target_tmp=auto    # back to tmp
  ```

- `test-vllm`, `build-vllm` and `build-pytorch` install Python packages. Each set of targets
  gets its own venv (`<folder>/venv-<targets>`, for example `venv-cpu-cuda`), so the CPU and the
  CUDA builds of torch never replace each other.
- Tools are cached per target too. The llama.cpp CUDA and Vulkan release builds, for example,
  are two cache entries.

## Recording what ran

- `--save_here` writes `cmeta-task-saved-result.json` and `cmeta-task-saved-ctx.json` in the
  current directory.
- The context holds `tasks.global.target` with the targets and everything detected: devices,
  drivers, compute capabilities, the CPU inventory.
- The llama.cpp programs add `perf.targets`, `perf.settings` (the offload options),
  `perf.devices` (the devices llama.cpp used) and `perf.gpu_layers`. Ollama and vLLM put their
  settings in `stats.settings`.

## Cached targets on another machine

A target's result is cached, but it is refreshed on every run:
- `cuda`, `rocm` and `vulkan` take the devices of the tool set up in the same call;
- `metal` and `xpu` parse their probe, which runs every time;
- `cpu` probes again when its host fingerprint (name, architecture, CPU count) changes.

A `CMETA_HOME` copied or shared between machines therefore never builds for another
machine's GPU.

See also: [docs/cmeta-aops/program-and-compute.md](../../docs/cmeta-aops/program-and-compute.md),
[docs/cmeta-aops/llm-stacks.md](../../docs/cmeta-aops/llm-stacks.md).
