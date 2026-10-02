# llama.cpp in cMeta: release builds, source builds, runs and every option

Three artifacts work together:

| Artifact | Does |
|---|---|
| `tool/llama-cpp` | detects or installs a release build of llama.cpp (the binaries GitHub publishes) |
| `program/llama-cpp` | runs a release build once and records llama.cpp's timings |
| `program/build-llama-cpp` | builds llama.cpp from source for the targets, then runs it the same way |

Targets are chosen with `--compute` (or `--target`); see [task/target/README.tech.md](../../task/target/README.tech.md).

## Release builds: tool/llama-cpp

```bash
cx tool setup llama-cpp                          # the release for the host: cpu (metal on macOS)
cx tool setup llama-cpp --with.compute=cuda      # the CUDA build
cx tool setup llama-cpp --version=11324          # a given build (default: 11324)
cx tool setup llama-cpp --versions               # the published builds
cx tool setup llama-cpp --status | --upgrade     # newest build available / install it
```

- The asset comes from the release's own list, for the OS, the CPU and the backend.
- The backend follows the targets: `cuda`, `vulkan`, `rocm`, `xpu` (SYCL), `openvino` or
  `metal`; `cpu` otherwise.
- CUDA builds are matched to the driver: the newest CUDA build the driver can run, through
  CUDA's minor-version compatibility. The `cudart` bundle is installed next to the binaries.
- The Linux CUDA builds need glibc 2.38 or newer (Ubuntu 24.04+); older systems get an error
  that says so.
- `--with.ver=12.4` picks another CUDA build than the newest, for example for an old driver.
- `--with.backend=<backend>` forces a backend.
- One release build has one GPU backend. Two GPU targets (`--compute=cuda,vulkan`) are refused:
  build from source with both.
- Each target list is its own cache entry: the CPU, CUDA and Vulkan builds stay installed side
  by side.

## Running a release build: program/llama-cpp

```bash
cx program run llama-cpp --compute=cuda --n=64 --seed=12345
cx program run llama-cpp --compute=cpu,cuda --ngl=12          # 12 layers on the GPU, the rest on the CPU
cx program run llama-cpp --compute=vulkan --model=my.gguf --prompt=prompt.txt
cx program run llama-cpp --compute=cuda --setup_llama_cpp.version=11300 --setup_llama_cpp.with.ver=12.4
```

| Option | Default | llama.cpp flag |
|---|---|---|
| `--n` | 500 | `-n`: tokens to generate |
| `--temp` | 0.7 | `--temp` |
| `--c` | 4096 | `-c`: context size |
| `--seed` | 12345 | `--seed` |
| `--model=<file.gguf>` | model category (tag `gguf`: Qwen2.5-0.5B-Instruct Q4_K_M) | `-m` |
| `--prompt=<file>` | dataset category (tags `prompt,txt,llm`) | `-f` |
| `--ngl=N` | all layers (none with `--compute=cpu`) | `-ngl`: layers offloaded to the GPU |
| `--devices=CUDA0,Vulkan0` | all GPUs (none with `--compute=cpu`) | `--device` |
| `--split_mode=layer\|row\|none` | layer | `-sm` |
| `--tensor_split=3,1` | even | `-ts` |
| `--main_gpu=N` | 0 | `-mg` |
| `--threads=N` | llama.cpp's choice | `-t` |
| `--log_flags=` | `-v` | logging; `-v` is what makes newer builds log the device used |
| `--run_flags="..."` | | any other llama.cpp flags |
| `--setup_llama_cpp.<param>=` | | passes a setup parameter to tool/llama-cpp (`version`, `with.ver`, `with.backend`) |

The run uses `llama-completion` (`llama-cli` became an interactive chat UI) with the model's
chat template and a single turn.

### Results

- `response` is the generated text (`output.txt`).
- `perf` comes from `perf.json`, parsed from `llama.log`:
  - `prompt_tokens_per_second`, `generation_tokens_per_second`, `timings` (load, prompt eval,
    eval, sampling, total);
  - `devices` (what llama.cpp used, e.g. `CUDA0 (NVIDIA RTX A500 Laptop GPU)`) and
    `gpu_layers` (`{"offloaded": 25, "total": 25}`);
  - `targets` and `settings` (the options above);
  - `build` and `commit`, `threads`, `cuda_archs` (the CUDA architectures of the build) and
    `system_info` (the CPU features).

## Building from source: program/build-llama-cpp

```bash
cx program run build-llama-cpp --compute=cuda                     # b11324 (as the release), for the detected GPU
cx program run build-llama-cpp --compute=cuda,vulkan --target_tmp=auto
cx program run build-llama-cpp --compute=cuda,vulkan --target_tmp=auto --devices=Vulkan0
cx program run build-llama-cpp --compute=metal --checkout=b11400 --compile.d.GGML_METAL_EMBED_LIBRARY=OFF
```

- `--checkout=<tag|branch|commit>`: the default is `b11324`, the same build as the release
  tool's, so a release and a source build compare out of the box.
- One `GGML_<BACKEND>=ON` for each target. On macOS Metal is turned off for builds without
  `metal`, so a CPU build opens no GPU.
- CUDA builds compile for the detected GPU.
- Vulkan builds take the headers, `glslc` and the loader library from `tool/vulkan-sdk`.
- CMake and Ninja are cMeta tools, and the compiler is chosen for the targets.
- `--compile.d.<VAR>=<value>` passes a CMake variable (`-D<VAR>=<value>`).
- `--compile.boringssl` builds BoringSSL along, as the releases do. Without it the system
  OpenSSL is used if found, else `LLAMA_OPENSSL=OFF`.
- `--compile.static`, `--compile.debug_info` and `--compile.strict_compute` (turns the backends
  not listed off) are also accepted.
- `--recompile` builds again; `--clean` starts from an empty build folder. A build is also
  redone when the targets change in the same folder. `--target_tmp=auto` keeps one folder per
  set of targets.
- The run takes the same options and gives the same results as `program/llama-cpp`.

## Recipes

- **Release against source build:** run both, alternating, on an idle machine.
  `cx program run llama-cpp --compute=cuda` and
  `cx program run build-llama-cpp --compute=cuda --target_tmp=tmp-build-cuda`, three rounds
  each. On 2026-10-02 they agreed within 1% on four machines.
- **Partial offload:** `--compute=cpu,cuda --ngl=N` for N from 0 to the layer count (25 for
  the 0.5B model). `perf.gpu_layers` confirms the split.
- **Two GPUs, or CUDA against Vulkan on one GPU:** build with `--compute=cuda,vulkan`, then run
  with `--devices=CUDA0`, `--devices=Vulkan0`, or both.
- **First runs:** the first Vulkan run on a machine also compiles the shaders. Discard it or
  repeat it.

Results of the test fleet: [docs/cmeta-aops/llm-stacks.md](../../docs/cmeta-aops/llm-stacks.md).
