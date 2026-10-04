# PyTorch from source in cMeta: program/build-pytorch and every option

`program/build-pytorch` clones PyTorch at a tag, builds it for the targets, installs it into a
venv of its own, and runs a device check. Release wheels come from `tool/pytorch` and
`tool/pip-torch` instead. Targets are chosen with `--compute` (or `--target`); see
[task/target/README.tech.md](../../task/target/README.tech.md).

```bash
cx program run build-pytorch --compute=cuda                   # v2.14.1 for the detected GPU (hours)
cx program run build-pytorch --compute=metal                  # MPS on macOS
cx program run build-pytorch --compute=cpu,cuda --target_tmp=auto
cx program run build-pytorch --compute=cuda --checkout=v2.14.0 --max_jobs=4 --compile.d.USE_FLASH_ATTENTION=OFF
```

| Option | Default | Meaning |
|---|---|---|
| `--checkout` | `v2.14.1` | tag, branch or commit; a tag also sets `PYTORCH_BUILD_VERSION` |
| `--max_jobs` | sized to the RAM (4 GiB per CUDA job, 2 GiB per C++ job) | `MAX_JOBS` |
| `--compile.d.<VAR>=<value>` | `USE_DISTRIBUTED=OFF` | a build variable of `setup.py` (`ON`/`OFF` become `1`/`0`) |
| `--use_cudnn` | off | `USE_CUDNN=1` with `lib-cudnn` |
| `--use_mkl` | off | MKL for CPU and XPU builds |
| `--compile.debug_info` | off | a debug build |
| `--recompile`, `--clean` | | build again, or from an empty build folder |
| `--target_tmp=auto` | `tmp` | one build folder per set of targets |

- The targets turn on `USE_CUDA`, `USE_ROCM`, `USE_MPS` (`metal`) and `USE_XPU`. CPU is in
  every build.
- `TORCH_CUDA_ARCH_LIST` comes from the detected GPUs. Without a GPU, CUDA 13 rejects
  PyTorch's default list.
- Other build settings:
  - `BUILD_TEST=0`;
  - the build uses `CMAKE_GENERATOR=Ninja` with cMeta's CMake and Ninja;
  - `CMAKE_POLICY_VERSION_MINIMUM=3.5`, because CMake 4 refuses NNPACK's helper projects;
  - `DISTUTILS_USE_SDK=1` with the MSVC environment on Windows (Visual Studio through
    `vswhere`).
- The build runs `pip install -r requirements-build.txt`, then
  `pip install --no-build-isolation -v .` (scikit-build-core).
- **One venv per set of targets** (`<build folder>/venv-<targets>`). A shared venv once mixed
  vLLM's pip cuBLAS 13.1 with a torch built for the CUDA 13.3 toolkit (cuBLAS 13.6), and the
  import failed with "undefined symbol: cublasLtGroupedMatrixLayoutCreate".
- On macOS, MPS builds work with the Command Line Tools alone. The Metal shaders are then
  compiled at run time, because only Xcode's Metal toolchain precompiles them. The build has
  no OpenMP unless Homebrew's `libomp` is installed.

**The run** prints the Python and PyTorch versions, whether CUDA, MPS and XPU are available,
and checks a small matmul on the device. It is a check, not a benchmark.
