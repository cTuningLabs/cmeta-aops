# LLM inference stacks: llama.cpp, vLLM, Ollama and PyTorch

cMeta installs, builds and runs four LLM stacks with the same commands on Windows, Linux
(WSL2 included) and macOS, on the CPU, CUDA, Vulkan and Metal. Every run records the
stack's own timings, so results from different machines, kernels and models compare.

| Stack | Install (prebuilt) | Build from source | Run and measure |
|---|---|---|---|
| llama.cpp | `tool/llama-cpp` (release assets) | `program/build-llama-cpp` | `program/llama-cpp`, `program/build-llama-cpp` |
| vLLM | `tool/pip-vllm` (wheels) | `program/build-vllm` | `program/test-vllm`, `program/build-vllm` |
| Ollama | `tool/ollama` (portable release) | – | `program/test-ollama` |
| PyTorch | `tool/pip-torch` | `program/build-pytorch` | `program/build-pytorch` (a device check) |

## Compute targets

`--compute` selects the device: `cpu`, `cuda`, `vulkan`, `metal`, and `rocm` / `xpu`
where a stack supports them (see [program-and-compute.md](program-and-compute.md#4-the-compute-abstraction--the-pivot)).

- `vulkan` runs on any Vulkan GPU: NVIDIA, AMD and Intel drivers, Apple GPUs through
  MoltenVK, or Mesa's CPU device (llvmpipe). `tool/vulkan` detects the runtime and lists
  the devices, and `tool/vulkan-sdk` provides the headers and `glslc` that builds need.
- A cached target describes the machine it runs on. The CUDA, ROCm and Vulkan targets take
  their devices from the tool detected in this call. The Metal and XPU targets parse the
  probe that ran in this call. The CPU target probes again when the host name, architecture
  or CPU count changed. A `CMETA_HOME` copied or shared between machines therefore never
  builds for another machine's GPU.

## llama.cpp

The prebuilt release for the OS, CPU and backend, then one generation:

```bash
cx program run llama-cpp --compute=cuda --n=64 --seed=12345     # cpu, cuda, vulkan, metal
cx program run llama-cpp --compute=cuda --setup_llama_cpp.version=11324
cx tool setup llama-cpp --versions                              # the release builds
```

- The asset comes from the release's own list. CUDA builds are matched to the driver
  (CUDA minor-version compatibility), and the `cudart` bundle is installed next to the
  binaries. The Linux CUDA builds need glibc 2.38 or newer (Ubuntu 24.04+).
- `--compute=cpu` keeps the model on the CPU (`-ngl 0 --device none`) even when a GPU
  is present.
- The model is a GGUF from the `model` category, and the prompt comes from the `dataset`
  category.
- The result has `response` (the generated text) and `perf` (`perf.json`): prompt and
  generation tokens per second, load and total time, the devices used and the CUDA
  architectures of the build.

From source, with the same run afterwards:

```bash
cx program run build-llama-cpp --compute=cuda --checkout=b11324 --n=64 --seed=12345
```

CMake and Ninja are cMeta tools. The compiler is selected for the target, and the CUDA
architecture is that of the detected GPU. Vulkan builds take headers, `glslc` and the loader
library from `tool/vulkan-sdk`, Metal is the default on macOS, and OpenSSL is optional:
the system library if found, else `LLAMA_OPENSSL=OFF`, or BoringSSL built along with
`--compile.boringssl` (as the release binaries do).
Trees that have `tools/completion` run `llama-completion`, older ones `llama-cli`.

## vLLM

The wheel for the target and the driver, then one generation:

```bash
cx program run test-vllm --compute=cuda      # Linux and WSL2
cx program run test-vllm --compute=cpu       # Linux x86_64/arm64, macOS arm64
```

- `tool/pip-vllm` chooses the package index. PyPI has the CUDA 13.0 build (driver R580 or
  newer). Older drivers get the CUDA 12.9 build (`wheels.vllm.ai/<version>/cu129`), and
  the CPU, ROCm and XPU builds come from their own indexes.
- vLLM supports Python 3.10–3.14 (3.12 on macOS). The program sets up a Python in that
  range, or `--python_version` picks one.
- vLLM does not run on native Windows. Use the same command in WSL2.
- On a Linux CPU, vLLM needs `libnuma` (`tool/lib-numa`). `--cpu_kv_cache_gib` sets
  `VLLM_CPU_KVCACHE_SPACE`, and a Docker container needs `--shm-size=2g` or more.
- Parameters: `--model`, `--n`, `--gpu_mem`, `--max_len`, `--vllm_version`.

From source, with the same run afterwards:

```bash
cx program run build-vllm --compute=cuda --checkout=v0.30.0
cx program run build-vllm --compute=cpu --checkout=v0.30.0
```

The build installs `requirements/build/<device>.txt`, with a torch whose CUDA major version
matches the local toolkit, then runs `pip install --no-build-isolation -v .`. The variables
it sets are `VLLM_TARGET_DEVICE`, `CUDA_HOME` (the toolkit of `nvcc`), `TORCH_CUDA_ARCH_LIST`
(the detected GPU; a single architecture shortens the build a lot), `NVCC_THREADS`, and
`MAX_JOBS` sized to the RAM (4 GiB per CUDA job). Override them with `--cuda_arch_list`,
`--max_jobs`, `--nvcc_threads` or `--compile.env.<VAR>=<value>`. A CUDA build takes one to
several hours.

## Ollama

```bash
cx tool setup ollama                              # the pinned portable release
cx program run test-ollama --compute=cuda         # cpu, cuda, metal, rocm, vulkan
cx program run test-ollama --model=qwen2.5:0.5b --n=64 --port=11435
```

The release is unpacked into the cMeta cache (no installer, no service, no administrator
rights). The Linux `.tar.zst` archive is unpacked by a Python 3.14 when no `zstd` is at
hand; uv downloads that Python if needed. The program starts a private server on its own
port, pulls the model and generates once after a warm-up. It records Ollama's timings and
how much of the model sits in VRAM (`size_vram_mib`). `--compute=cpu` keeps the model on the
CPU, and `--compute=vulkan` sets `OLLAMA_VULKAN=1`.

## PyTorch from source

```bash
cx program run build-pytorch --compute=cuda --checkout=v2.14.1    # cpu, cuda, metal
```

The build runs `pip install --no-build-isolation -v .` (scikit-build-core) after
`requirements-build.txt`. It sets `TORCH_CUDA_ARCH_LIST` from the detected GPUs,
`MAX_JOBS` from the RAM, `BUILD_TEST=0`, and `PYTORCH_BUILD_VERSION` from the tag. On
Windows it also sets the MSVC environment and `DISTUTILS_USE_SDK=1`. The run checks the
device: a matmul on `cuda`, `mps` or the CPU.

On macOS the MPS build works with the Command Line Tools alone. PyTorch then compiles its
Metal shaders at runtime, because only the Metal toolchain of Xcode precompiles them, and it
builds without OpenMP unless Homebrew's `libomp` is installed.

## Build tools

- **Windows:** Visual Studio, or the Build Tools, with the C++ workload. `cx tool setup
  microsoft.visual-studio` finds every installation through `vswhere`, and `--version=19.44`
  picks one by its `cl.exe` version. `--install` installs the newest Build Tools through
  winget (`--with.year=2022` for an older release line); the installer asks for
  administrator rights.
- **Linux:** the distribution's `gcc`/`g++`; CMake and Ninja come as cMeta tools. CUDA
  builds need the CUDA toolkit (`nvcc`).
- **macOS:** the Xcode Command Line Tools (`clang`), plus Homebrew for `libomp` and the
  Vulkan packages.

A tool that can only come from a `sudo` package manager never waits at a password prompt in
a quiet run (`-q`). The command fails at once, and cMeta prints it so you can run it yourself.
