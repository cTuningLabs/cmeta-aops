# test-nmm-torch-cpp — matrix multiplication in C++ against LibTorch

A small C++ program built against LibTorch, the PyTorch C++ distribution, with CMake
(`find_package(Torch)`): it prints the LibTorch version and which devices it sees (CUDA, MPS),
multiplies two 4x4 matrices on the selected device and checks the result. It checks that a
LibTorch setup works for C++ programs on a machine, and for a compute target.

```bash
cx program run test-nmm-torch-cpp cpu
cx program run test-nmm-torch-cpp cuda
cx program run test-nmm-torch-cpp metal          # Apple GPUs (MPS)
```

The result is in `output.txt` (LibTorch version, device, matmul sum, PASSED or FAILED).

## Where LibTorch comes from

The program sets up [`tool/torch-cpp`](../../tool/torch-cpp/), which gives LibTorch in one of two
ways; `--setup_torch_cpp.<option>` passes options to it.

| | Source build (the default) | Prebuilt (`--setup_torch_cpp.build=prebuilt`) |
|---|---|---|
| What | PyTorch built from source by [`program/build-torch-cpp`](../build-torch-cpp/) (CMake, Ninja) | PyTorch's official LibTorch archive, through [`tool/torch-cpp-prebuilt`](../../tool/torch-cpp-prebuilt/README.md) |
| Time to set up | a long build (hours) | a download |
| Versions | any release tag | the releases with pinned archives (2.7.1) |
| Options | static builds, custom CMake options, compilers | the CPU build or a CUDA build; macOS: CPU and MPS |
| Cache entries | `task--setup--torch-cpp--*`: the build tree in `build/`, the installed LibTorch (`lib`, `include`, `share/cmake/Torch`) in `build/install/` | `task--setup--torch-cpp-prebuilt--*`, one per build |

```bash
# PyTorch's prebuilt LibTorch
cx program run test-nmm-torch-cpp cpu --setup_torch_cpp.build=prebuilt
cx program run test-nmm-torch-cpp cuda --setup_torch_cpp.build=prebuilt
cx program run test-nmm-torch-cpp cuda --setup_torch_cpp.build=prebuilt --setup_torch_cpp.variant=cu126
cx program run test-nmm-torch-cpp cpu --setup_torch_cpp.build=prebuilt --setup_torch_cpp_task.version=2.7.1
```

For `cuda`, the prebuilt CUDA build (cu118, cu126, cu128) is the newest one that has code for every
GPU of the machine and whose CUDA version the NVIDIA driver supports; `--setup_torch_cpp.variant`
picks one.

### The source build enables only the target's backends

A source build turns on exactly the backends of the target: for `cpu`, CUDA, cuDNN, ROCm, MPS and
XPU are off even when a CUDA toolkit or another SDK is installed. To let PyTorch's CMake enable
whatever it finds, as source builds did before:

```bash
cx program run test-nmm-torch-cpp cpu --setup_torch_cpp.strict_compute=False
```

`--setup_torch_cpp.strict_compute=True`, the same as the default now, keeps a cache entry of its own,
as before.

### Prebuilt LibTorch as the default later

The prebuilt archives could become the default of this program later: they take a download
instead of a long build and do not depend on the compilers, CUDA toolkit and Python packages of the
machine. The source build would stay for other versions, static builds and custom options. Until
then, `--setup_torch_cpp.build=prebuilt` chooses them.

## How the program is built

- **CMake config of LibTorch:** `Torch_DIR` points to the LibTorch of `tool/torch-cpp` (CMake would
  otherwise keep the one it found first in its cache).
- **CUDA:** a CUDA build of LibTorch enables CUDA in its CMake config, so the program sets up `nvcc`
  and passes it as `CMAKE_CUDA_COMPILER`, with `USE_SYSTEM_NVTX=ON` (NVTX3 from the CUDA toolkit;
  newer toolkits no longer have the nvToolsExt library that is looked for otherwise). The archive
  brings the CUDA run-time libraries it needs (cuDNN, cuBLAS, ...); only the NVIDIA driver must be
  installed to run it.
- **Windows:** PyTorch's archives are built with MSVC, and their CMake config adds MSVC options; when
  cMeta chose the GNU-style `clang++`, the program is compiled with `clang-cl` from the same LLVM
  (same ABI). On Windows the LibTorch DLLs are copied next to `program.exe`; on Linux and macOS the
  LibTorch `lib` folder is on the library path of the run.
- **MPS:** for `metal`, `USE_MPS` is defined for the program, which then selects the `mps` device
  when it is available.
- **C++ standard:** the one LibTorch's CMake config sets on its `torch` target (17 for the releases
  up to 2.8, 20 from 2.9 on, whose headers use `requires` clauses), else 17; `--cxx_standard=<n>`
  overrides it.
