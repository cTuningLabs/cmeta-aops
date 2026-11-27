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
| `ios-cpu` | an iPhone or iPad on a Mac's USB (`--device=<name or UDID>`, `xcrun devicectl`): programs are built with Xcode's clang and the iOS SDK (`tool/apple.xcode`, `tool/apple.xcode.clang`), put into an app bundle, signed with the developer's identity and the development profile the target finds or makes, installed and launched with the console attached; their output files come back from the app's Documents folder ([task/target--ios-cpu](../target--ios-cpu/README.md)) |
| `ios-gpu` | the GPU of that device, as a Metal probe run on it reports it: the device and architecture, the highest Apple / Common / Metal GPU family, limits and features |
| `ios-npu` | the Neural Engine of that device, as a Core ML probe run on it reports it (iOS 17 and newer): its cores and the compute devices of Core ML - an app reaches it only through a Core ML model. Fails when Core ML lists none |
| `tpu`, `opu-lumai` | placeholders: fail until supported |

## Where each target works

Each `task/target--<name>/_desc.yaml` declares it in a `support` block, which `cx program targets` prints
under each target and the page `cserver.cmeta.targets` draws as a matrix (`/cmeta.targets` on the engine's
cserver; `cx cserver.cmeta.targets matrix` in a terminal):

```yaml
support:
  kind: gpu                      # cpu, gpu, npu, stack, app
  hardware: 'NVIDIA GPUs (CUDA)'
  host_os: [linux, windows]      # the OS of the machine cMeta runs on (linux, windows, darwin)
  device_os: android             # only when the program runs on another device, driven from the host (android, ios)
  status: supported              # supported, placeholder
```

These are declared facts, read from what the target's code does on each OS - not test results. A new target
declares its block too (`tests/cmeta_aops_basic_tests/test_target_support.py` checks it).

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

## Which targets a machine has

```bash
cx task run detect-targets                      # every target with a probe: there or not, its devices
cx task run detect-targets --only=gpu,npu       # some kinds or targets (a view: all are still probed)
cx task run detect-targets --full               # also the target task of each one found: tools, devices, versions
cx task run detect-targets --redetect           # whatever the fingerprint says
cx program targets <program> --detect           # where a program can run here, with the command lines
cx program run <program> --compute=auto         # take what this machine has
```

- Each target task declares a cheap probe (`probe:` in its `_desc.yaml`). Nothing is installed or started.
- The findings are kept in `state::local:detect-targets` with a fingerprint of the OS, the kernel, the devices and
  the driver versions. A changed fingerprint means the targets are detected again and what changed is said.
- `--compute=auto` takes, among the targets found that the program supports:
  1. an accelerator of the machine itself (`cuda`, `rocm`, `xpu`, `metal`, an NPU): one kind is taken, several are
     listed with their command lines - never a guess;
  2. else a portable interface over its devices (`auto: portable` in the target: `opencl`, `vulkan`, `openvino`),
     the same way;
  3. else the CPU.
  A target that is another device driven from the machine (`support.device_os`: an Android tablet) is never taken
  by itself: it is listed with its command line.
- A run without `--compute` is unchanged: the CPU, nothing probed.

## Adding a target, in any repository

A target is an artifact, `task/target--<name>`. Nothing else names it: `--compute=<name>`, `cx program targets`,
`detect-targets` and `--compute=auto` find the targets by their alias among the repositories plugged in. A backend
that must not be public is a target in a repository of its own:

```bash
cx task add <repository>:target--acme-npu --yaml
```

Its `_desc.yaml` holds what the public targets hold:

```yaml
store_global: True
storage_key: target--acme-npu
cache: True

uses:                              # how it is set up: its driver, runtime or SDK as cMeta tools (they may be private too)
  - task: setup,a2f9b61079ce4333
    name: acme-runtime

env_if_not_used:
  CMETA_TARGET_ACME_NPU: 0
env:
  CMETA_TARGET_ACME_NPU: 1

support:                           # what "cx program targets" shows
  kind: npu                        # cpu, gpu, npu, stack, app
  hardware: 'the Acme NPU'
  host_os: [linux, windows]
  status: supported

probe:                             # how detect-targets finds it: per OS (linux, windows, darwin) or all
  linux:
    any:
      - {pci: {vendor: ['0xfff0']}}                    # its PCI vendor id (0xfff0 stands for it here)
  windows:
    any:
      - {pnp: {class: [System], vendor: ['FFF0']}}
```

The checks of a probe (one that holds is enough; `all:` / `any:` combine them):

| Check | Holds when |
|---|---|
| `{always: true}` | always (the CPU) |
| `{machine: [arm64]}` | the machine's architecture is one of these |
| `{glob: <pattern>}` (+ `version: <regex>`, `names: true`) | a file is there; its version is read from it; the files are the devices |
| `{pci: {vendor: [...], device: [...], drivers: [...]}}` | Linux: a PCI device with these ids (and this driver) |
| `{drm_vendor: '0x10de', drivers: [...]}` | Linux: a GPU of this vendor with one of these kernel drivers |
| `{accel_driver: [...]}` | Linux: an accelerator of `/sys/class/accel` with one of these drivers |
| `{kfd_gfx: true}` | Linux: an AMD GPU in the kernel's ROCm interface |
| `{pnp: {class: [...], vendor: [...]}}` | Windows: a present device of these classes and vendors |
| `{pnp_driver_value: {class: [...], value: <name>}}` | Windows: a present device whose driver key has this value |
| `{registry_values: <key>}` | Windows: the key (under HKEY_LOCAL_MACHINE) has values |
| `{cpu_vendor: [GenuineIntel]}` | the CPU says one of these vendors |
| `{adb_devices: true}` | the adb server of the machine lists an Android device as ready |
| `{script: probe.py}` | the target's own code says so: `probe(host)` of that file of the artifact returns `{'present': bool, 'devices': [...], 'versions': {...}}` - for a device none of the checks above describes |

- A probe is expected to be cheap: it runs at every `--compute=auto`. What takes time (asking a runtime for its
  devices) belongs to the target task itself, which `--full` runs and caches.
- What else a target says about itself, read by shared code through one query (`targets(cm)` of
  `category/task/api/ctask.py`) - no list of target names stands in shared code:

  | Key | Says | Read by |
  |---|---|---|
  | `auto: portable` | an interface over the devices of other targets: `--compute=auto` takes it second | `detect-targets` |
  | `support.device_os: android` | another device, driven from the machine: pushed to and run on it; never the choice of `--compute=auto` by itself | `detect-targets`, `setup-run`, `compile-and-run-program` |
  | `instance_overlay: [docker, podman, wsl]` | in such an instance (`--on=docker` ...) the device must be given to it: the instance is made with the template's compute overlay of this target's name, and a template without one stops the run. Any other target runs in a CPU instance | the task category (`--on`) |
  | `backends: {<tool's storage key>: <backend>}` | the backend of a tool that this target selects, for a tool that does not list the target in its own `target_backends:` | the tool (`self.target_backends(compute)`) |
- **A target of a repository that a call must not see** (`--hide_repos`, a clearance of a site) is neither probed nor
  named by that call, and the findings are kept per set of targets probed - such a call never reads what a call
  that sees more has found.
- A program names the targets it supports in `constraints.supported_compute`; a program for a private backend
  lives in the private repository beside its target.

See also: [docs/cmeta-aops/program-and-compute.md](../../docs/cmeta-aops/program-and-compute.md),
[docs/cmeta-aops/llm-stacks.md](../../docs/cmeta-aops/llm-stacks.md).
