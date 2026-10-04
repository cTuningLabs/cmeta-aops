# lib-cudnn — NVIDIA cuDNN for the CUDA toolkit of `tool/nvcc`

`cx tool setup lib-cudnn` gives programs the cuDNN headers and libraries that match the CUDA toolkit
`tool/nvcc` set up. A program lists it with the other libraries of a CUDA build:

```yaml
- task: setup,a2f9b61079ce4333
  name: lib-cudnn,440a30eb25b64853
```

and `task/setup-compile` adds its include folder, its library folder and `cudnn` to the compile and
link commands; at run time the folder of `cudnn64_9.dll` / `libcudnn.so.9` is on the library path.

## Detection

A cuDNN already on the machine is used when its CUDA version matches the toolkit:

| System | Where it is looked for |
|---|---|
| Windows | NVIDIA's installer folders `C:\Program Files\NVIDIA\CUDNN\v9.x\include\<cuda version>\cudnn.h` (also `D:` and `Program Files (x86)`) |
| Linux | `/usr/local/cuda*/include`, `/usr/include`, `/opt/cuda*/include` |

The CUDA version a cuDNN was built for must have the same major version as nvcc's and a minor
version that is not newer. The version is read from `cudnn_version.h`.

## Install: NVIDIA's public redistributable

When no matching cuDNN is found, the tool downloads the archive of cuDNN **9.27.0.42** for this OS,
CPU and the CUDA major version of the toolkit from NVIDIA's public redistributable site
(`https://developer.download.nvidia.com/compute/cudnn/redist/`, no account needed), checks its SHA-256
against the digest published in NVIDIA's `redistrib_9.27.0.json`, and unpacks it into the tool's cache
entry (`content/cudnn-<platform>-9.27.0.42_cuda<N>-archive/` with `include/`, `lib/`, `bin/` on
Windows). Nothing is installed in the system.

| OS, CPU | CUDA 12 | CUDA 13 |
|---|---|---|
| Linux x86_64 | yes (about 1 GB) | yes (about 0.9 GB) |
| Linux arm64 (sbsa) | yes | yes |
| Windows x64 | yes (about 1.8 GB) | yes (about 1.3 GB) |
| Windows arm64 | no | yes |
| macOS | no | no |

`--version=9.x.y.z` (an exact version) takes another 9.x release: its archive and digest are read from
NVIDIA's `redistrib_<version>.json`. Where NVIDIA publishes no archive (macOS; CUDA 11 and older) the
tool asks for a cuDNN installed by hand. Several toolkits on one machine get one cuDNN entry each:
the entry records the CUDA toolkit it belongs to, and an archive built for another CUDA major version
is never taken.

## The GPU

The early cuDNN 9 releases run on GPUs of compute capability 5.0 (Maxwell) and newer; from 9.11 on,
NVIDIA's support matrix says 7.5 (Turing) and newer, and the tool found the same by trying the
releases on a Maxwell GPU: 9.0.0, 9.5.1 and 9.10.2 run; 9.11.1, 9.12.0 and 9.27.0 fail. On a GPU that
is too old `cudnnCreate` still succeeds and the first kernel fails with `CUDNN_STATUS_EXECUTION_FAILED`,
deep inside a program; the tool therefore refuses the setup of such a cuDNN on such a GPU (the one
`task/target--cuda` found) with a message that names the cause and the releases that still run
there (`--version=9.10.2`). `--with.any_gpu` sets cuDNN up anyway, for a build that runs on another
machine. The minimum of the version set up is recorded as `features.gpu_arch_min` (50 or 75).

**License:** cuDNN is NVIDIA's software under the NVIDIA cuDNN license (`LICENSE.txt` in the archive,
the same terms as NVIDIA's installers); downloading it this way is the redistribution NVIDIA offers
for package managers. The disk space it needs is in `_desc_sizes.yaml`.

## Static builds

NVIDIA ships static cuDNN and cuBLAS archives on Linux only (`libcudnn_*_static.a`,
`libcublas_static.a`), none on Windows. A `--compile.static` CUDA build in cMeta links the CUDA runtime
statically (`-cudart=static`) and, where the program's libraries provide them, static third-party
libraries; cuDNN and cuBLAS stay shared libraries, loaded from the folders recorded by this tool and
`tool/lib-cuda`. A fully static host binary is not possible for CUDA programs: the driver library is
always shared.
