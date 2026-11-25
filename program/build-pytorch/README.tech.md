# PyTorch from source in cMeta: program/build-pytorch and every option

`program/build-pytorch` clones PyTorch at a tag, builds it for the targets, installs it into a
venv of its own, and runs a device check. Release wheels come from `tool/pytorch` and
`tool/pip-torch` instead. Targets are chosen with `--compute` (or `--target`); see
[task/target/README.tech.md](../../task/target/README.tech.md).

```bash
cx program run build-pytorch --compute=cuda                   # v2.15.0 for the detected GPU (hours)
cx program run build-pytorch --compute=metal                  # MPS on macOS
cx program run build-pytorch --compute=cpu,cuda --target_tmp=auto
cx program run build-pytorch --compute=cuda --checkout=v2.14.0 --max_jobs=4 --compile.d.USE_FLASH_ATTENTION=OFF
cx program run build-pytorch --compute=cpu --compile.variation=lean          # the same build, cloned lean
cx program run build-pytorch --compute=cuda --compile.variation=minimal --compile.components.kineto
```

| Option | Default | Meaning |
|---|---|---|
| `--checkout` | `v2.15.0` | tag, branch or commit; a tag also sets `PYTORCH_BUILD_VERSION` |
| `--max_jobs` | sized to the RAM free now (4 GiB per CUDA job, 3 GiB per C++ job, 2 GiB kept for the system) | `MAX_JOBS` |
| `--compile.d.<VAR>=<value>` | `USE_DISTRIBUTED=OFF` | a build variable of `setup.py` (`ON`/`OFF` become `1`/`0`) |
| `--compile.variation=<name>` | none | a named set of the build's parts: `lean`, `minimal` (below) |
| `--compile.components.<part>`, `<part>-` | none | one part on, or off (below) |
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

## The host compiler on Windows

The build takes the machine's newest MSVC, as every request does - unless that compiler is one this
program is known not to configure with. Those are declared in its `_desc.yaml`, by system, each
with what happens and since when:

```yaml
compiler_limits:
  windows:
    msvc:
      - exclude: '>=19.51,<19.52'      # a version range, as a request writes it
        reason: ...
        since: '2026-11-24'
```

Before anything is set up, the program lists the machine's MSVC compilers (every Visual Studio
installation with the C++ tools). When the newest is excluded, the newest one outside the limits
is the compiler of this run, and the console says which and why; nothing of the machine changes
and every other request keeps the newest. A machine with no other compiler stops with the reason
and what to install. `--use.msvc.version=<version>` names a compiler yourself: it is taken as
asked. A limit is lifted by removing its entry, once a build of that compiler is seen to work.

Today's entry: `cl.exe` 19.51 (seen with 19.51.36260) ends with an internal compiler error on one
of SLEEF's configuration probes, which stops CMake; the compilers of Visual Studio 2022 and 2019
do not.

## The toolkit of a target

A target may need its vendor's toolkit in the release that goes with the PyTorch that is built.
For Intel GPUs (`xpu`), Intel names one release of oneAPI (its package Deep Learning Essentials)
per PyTorch release; the program declares them in its `_desc.yaml`:

```yaml
toolkits:
  xpu:
    oneapi:
      - program_version: '>=2.15,<2.16'   # the PyTorch versions the line is for
        version: '2026.1'                 # the release Intel names for them
        works_with: '>=2026.0'            # optional: what the build is seen to work with
        reason: ...
        source: <Intel's page>
```

After the targets are known and before the compiler is set up, the build asks the `oneapi` tool
for the named line, for this run only, and says so. The tool finds that release on the machine or
installs it: `--use.oneapi.with.accept_eula=yes` accepts Intel's licence (the tool's `_desc.yaml`
says what is installed where, per system). `--use.oneapi.version=<version>` names a release
yourself: it is taken as asked, with a warning when it is outside `works_with`. A PyTorch version
no line names (a branch, a release outside the table) asks nothing, and the build goes on with the
oneAPI of the machine.

The driver is declared the same way (`drivers: <target>: <system>`, a `min` per PyTorch
version): when the driver the target read on the machine is older than the one its vendor names,
the build says so and goes on - the driver matters when the result runs. Today: the Intel
graphics driver on Windows for PyTorch 2.15.

A SYCL extension is no package of its own: it is a part of the compiler and its runtime. PyTorch
2.15 uses `ipc_memory`, which the compiler of oneAPI 2025.3 does not have - with that release
`c10/xpu/XPUCachingAllocator.cpp` does not compile.

## The parts of the build

PyTorch's source brings some forty submodules, several with deep trees of their own, and a build
for one target reads only some of them. The program declares the optional parts in its
`_desc.yaml` (`components:`) with, for each, the build variables it sets, the submodules it alone
reads, the systems and targets it can be built for, the parts it needs, and its default; and
named sets of them (`variations:`). The general rule is in
[program-and-compute.md](../../docs/cmeta-aops/program-and-compute.md) (section D2).

| Part | Build variable | Submodule it alone reads | Built where |
|---|---|---|---|
| `distributed` | `USE_DISTRIBUTED` | | everywhere (off by default, as this program always built it) |
| `tensorpipe` | `USE_TENSORPIPE` | `third_party/tensorpipe` | Linux, macOS; needs `distributed` |
| `kineto` | `USE_KINETO` | `third_party/kineto` (up to 2.14; 2.15 carries it in its own tree) | everywhere (off on Windows by default) |
| `rocm-kernels` | `USE_ROCM_CK_SDPA`, `USE_ROCM_CK_GEMM` | `third_party/flash-attention`, `third_party/aiter` | Linux, target `rocm` |
| `mslk` | `USE_MSLK` | `third_party/mslk` | Linux, targets `cuda`, `rocm` |
| `mkldnn` | `USE_MKLDNN` | `third_party/ideep` | everywhere (off on Windows by default) |
| `fbgemm` | `USE_FBGEMM` | | everywhere |
| `xnnpack`, `nnpack`, `qnnpack` | `USE_XNNPACK`, `USE_NNPACK`, `USE_QNNPACK` | | everywhere |
| `flash-attention` | `USE_FLASH_ATTENTION` | | targets `cuda`, `rocm` |
| `tests` | `BUILD_TEST` | | everywhere (off by default) |

- **Without a variation and without a part asked, nothing changes**: every submodule with
  everything under it, the build variables of before.
- **`lean`** builds the same PyTorch and clones less: the submodules shallow (the commit each is
  pinned to, without its history), and the submodules of the parts that are off for this system
  and these targets without their own submodules. PyTorch's own check
  (`cmake/PreBuildSteps.cmake`) wants the folder of every submodule of `.gitmodules`, so the
  folders stay; what is under them is fetched only where the part is built.
- **The licence files the package lists are always there.** Since 2.15 PyTorch's
  `pyproject.toml` names every licence text of its wheel (`project.license-files`, PEP 639),
  some of them inside nested submodules, and the build stops when one is missing. The plan reads
  that list: a nested submodule that holds a listed file is fetched (shallow) also under a part
  that is off; the other nested submodules of that part are not.
- **`minimal`** also turns the optional CPU kernels, the profiler and the GPU attention kernels
  off - the smallest build for a target.
- **A part asked for** (`--compile.components.kineto`) wins over the variation; `<part>-` turns one
  off. A build variable the request sets itself (`--compile.d.USE_KINETO=ON`) is its word for the
  part and stays as given. Asking a part on where it cannot be built (TensorPipe on Windows, the
  ROCm kernels for the CPU), or without the part it needs, is an error; so is an unknown part or
  variation.
- **The run says what it decided**: a table of the parts (on, off or the build's own choice, and
  why), the build variables that follow, the submodules fetched without their own, and a
  submodule this version of the source no longer has.
- **Each variation is a build of its own**: `--compile.*` is part of a build's identity, so a
  `lean` build never replaces or reuses the plain one. From the tool:
  `cx tool setup pytorch --with.variation=lean` (and `--with.components.<part>`).
- **On Windows** Git refuses a git folder longer than 220 characters, whatever the long-path
  settings, and the deepest git folders of a PyTorch clone are those of the nested submodules of
  the ROCm kernels. A lean clone is shorter there only for a version whose licence list names no
  file in them; 2.15 lists some, so they are fetched and the clone needs as short a folder as a
  plain one (the file cache; `clone-git` says so when the limit is met).
