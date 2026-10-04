# nvcc — the CUDA compiler, a CUDA toolkit that suits the machine, and its host compiler

`tool/nvcc` finds nvcc in a CUDA toolkit, or installs a toolkit without root, so that the programs
it builds run on this machine's GPU and driver. It also sets up the host compiler (GCC, clang or
MSVC) that the toolkit supports.

```bash
cx tool setup nvcc                              # the newest toolkit that suits the GPU and the driver
cx tool setup nvcc --version=12.9               # CUDA 12.9 (the nvcc version, 12.9.86, also works)
cx tool setup nvcc --version=">=12.4,<12.7"     # a range
cx program run test-nmm-nvcc-cuda --use.nvcc.version=12.8   # a program built with CUDA 12.8
cx tool setup lib-cuda --with.lib_names=cublas  # cuBLAS, added to an installed toolkit if missing
```

`--version` is what `nvcc --version` reports: `12.9.86`, or a prefix (`12.9`, `12`), or a range.
A CUDA release label such as `12.9.1` is not an nvcc version, and the error says which one to ask
for.

## What suits the machine

The `cuda` tool (a dependency) reports the GPUs (`compute_cap_int_min`: the oldest GPU's compute
capability, times 10) and the CUDA version of the driver (`nvidia-smi`). A toolkit is skipped
when the programs it builds could not run here:

- **the GPU is older than the toolkit's oldest architecture.** CUDA 12 dropped Kepler (sm_35,
  sm_37), and CUDA 13 dropped Maxwell, Pascal and Volta (sm_50 to sm_70). The check uses
  `nvcc --list-gpu-arch`;
- **the driver is for an older major CUDA version** (a CUDA 13 toolkit with a driver for CUDA 12).

`--with.any_arch` and `--with.any_driver` keep such toolkits, to build for other machines.

The cache keeps one nvcc entry per GPU architecture (`gpu_arch_min` in its parameters). A toolkit
found for one GPU is not reused for another. Without `--version`, a run takes the newest toolkit
already in the cache for this GPU. `cx tool setup nvcc --version=<v>` adds another.

## Install: NVIDIA's redistributable archives, without root

When no toolkit on the system suits the machine, or none has the version asked for, `install()`
builds one from NVIDIA's archives at
`https://developer.download.nvidia.com/compute/cuda/redist`. Every component of every release
since 11.0.3 is listed in `redistrib_<release>.json`, with its sha256, for `linux-x86_64`,
`linux-sbsa` (Linux arm64) and `windows-x86_64`. The steps (`redist.py`):

1. **The release.** It is the newest one that matches `--version` and suits the machine:
   - its major version is at most the driver's;
   - its oldest architecture is at most the GPU's.

   Without `--version`, the release's major.minor must also be at most the driver's. A request
   may get a newer minor version than the driver's, with a warning: its programs then run through
   CUDA's minor version compatibility, without PTX JIT.
2. **The components.** nvcc, the runtime (cudart), the headers (cccl) and the profiler API are
   always included. Since CUDA 13, cccl, crt and nvvm are components of their own.
3. **Download and unpack.** Each archive is checked against its sha256 and unpacked into the
   cache entry, `content/<release>/` (`bin`, `include`, `lib`, `nvvm`). On Linux,
   `targets/<arch>-linux/{include,lib}` link to them, since `nvcc.profile` looks there.
4. **The record.** `version.json` lists the release and the components, as NVIDIA's installer
   writes it. `cmeta-cuda-redist.json` records the release, the platform and every component with
   its sha256.

**Libraries on demand.** `--with.cuda_libs=cublas,cufft` installs libraries with the toolkit.
`lib-cuda` passes on its `lib_names` (`$cublas`, ...), so a program that links cuBLAS gets it.
A toolkit made from the archives gets each missing library once. Without `-q`, it first asks,
with the download size, since libraries such as cuBLAS are large. A toolkit from NVIDIA's
installer or a distribution is left as it is. The names: cublas (with cublasLt), cufft, curand,
cusparse, cusolver (with cublas and cusparse), npp, nvjpeg, cufile, nvrtc, nvjitlink, nvml,
cupti, nvtx, opencl, cuobjdump, nvdisasm, cuxxfilt, nvprune.

## The host compiler

nvcc compiles host code with GCC, clang or MSVC, and each toolkit accepts only the versions that
its `include/crt/host_config.h` lists. For example, CUDA 12.8 takes MSVC up to Visual Studio 2022
(`_MSC_VER` below 1950) and GCC up to 14; CUDA 13.3 takes Visual Studio 2019 to 2026 and GCC up
to 15. Once the toolkit is found, `finish_dynamic_result` sets up the host compiler as follows
(`host.py`):

1. It reads those limits from the toolkit.
2. It turns them into versions of the compiler tools, as `--use` would: `msvc` by `cl.exe`'s
   version (`>=19.10,<19.50` for CUDA 12.8; the Visual Studio installation follows the version
   asked of `msvc`), `gcc-cpp`, and `clang-cpp`. A version you give with `--use.<tool>.version`
   stays, and a C++ compiler version you ask for with `--use.compiler-cpp.version` is taken as it
   is: when the toolkit rejects it, the run stops with the message below instead of quietly using
   another version. Once the compiler is decided, `task compiler` narrows the range of its tool to
   that version, so the later setups of the same run (and the Visual Studio of `msvc`) follow it
   without a question. When no version decides the installation (clang's dependency `msvc` asks
   for none), `tool/microsoft.visual-studio` takes the newest one itself, with an INFO line
   (`--use.microsoft-visual-studio.version=<version>` picks another).
3. It sets up `task compiler --lang=cpp`, which picks the newest compiler in those ranges: for
   CUDA 12.8 on a machine with Visual Studio 2026 and 2022, it picks 2022. Cached compilers
   outside the ranges, or without the tags and constraints of the request, are not offered; when
   several cached compilers remain, the preferred compiler of the OS is taken (MSVC on Windows,
   GCC on Linux, clang on macOS: `preferred_compilers` in `task/compiler/_desc.yaml`), then the
   one whose tool the repository ranks first, then the newest version, without a prompt (an INFO
   line names the others) - the rule of every compiler choice in `task compiler`, for CPU builds
   too. `--use.compiler-cpp.name=<tool>` picks another. The same task selects the cached entry of
   nvcc itself (`--lang=cuda`): it follows the toolkit set up for the `cuda` target in this run,
   so the toolkit is chosen once.
4. It passes the compiler to nvcc as `-ccbin <path>` (the `host_compiler` flag that
   `setup-compile` adds), so every build records which compiler it used.

A C++ compiler set up earlier in the same run that the toolkit rejects stops the run. The error
names the `--use` option that picks a supported one. `--with.any_host_compiler` takes any
compiler and adds nvcc's `-allow-unsupported-compiler`. `--with.compiler_extra_tags` and
`--with.compiler_extra_match` narrow the choice of compiler tool.

## Architecture flags

With `--with.arch_flags` (as `program/test-nmm-nvcc-cuda` uses), the result carries
`-gencode arch=compute_<N>,code=sm_<N>` for the GPU. For a GPU newer than the toolkit, or one
whose architecture the toolkit does not list, it carries the PTX of the newest architecture
before it (`code=compute_<M>`), which the driver compiles for the GPU. For a GPU older than the
toolkit, the result is an error that names the older toolkit to use.

## Options

| Option | Effect |
|---|---|
| `--version` | nvcc version, prefix or range |
| `--with.arch_flags` | `-gencode` flags for this GPU |
| `--with.add_env` | `CUDA_HOME`, `CUDA_PATH` and nvcc's `bin` on `PATH` for the steps that follow |
| `--with.cuda_libs` | libraries to install with a toolkit, or add to one made from the archives |
| `--with.any_arch`, `--with.any_driver` | keep toolkits that do not suit this GPU or driver |
| `--with.any_host_compiler` | any host compiler, with `-allow-unsupported-compiler` |
| `--with.compiler_extra_tags`, `--with.compiler_extra_match` | narrow the choice of host compiler tool |

nvcc does not run on macOS.
