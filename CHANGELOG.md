# Changelog

All notable changes to cMeta AOps are documented here, newest first.

## 0.42.0
- **Static and dynamic library variants keep their own cache entries** (`tool/lib-xopenme`,
  `lib-polybench`, `lib-milepost`): a request's `with.static` and `with.debug_info` always carry a
  value, so a dynamic build no longer matches the static entry as well (a program's
  `'{{params.compile.static|$None}}'` left the key out of the query, and quiet mode could reuse the
  static entry). Existing entries keep matching.
- **Static builds with clang get a static OpenMP runtime** (`tool/lib-openmp`): `libomp.a` in the
  library's cache entry, the archive shipped with Homebrew's libomp on macOS, else built from the
  pinned OpenMP 21.1.8 source release (SHA-256 checked) with cMeta's cmake and ninja on Linux; before,
  `-static -fopenmp` failed on `-lomp`. `test-nmm-c-cpu`, `test-nmm-cpp-cpu`, `polybench-cpu-gemm`
  and `polybench-gemm-cpu-cuda` pass `compile.static` to it.
- **`test-nmm-nvcc-cuda`:** a static build uses the static xopenme and, on Linux, lib-openssl's
  static libraries, like the C programs (static for CUDA is `-cudart=static` with static third-party
  libraries: a fully static host binary cannot load the CUDA driver).
- **`test-nmm-c-cpu`:** links the math library on Linux; before, the dynamic build linked only with
  `--compile.fastest`.
- **`--compile_timeout` is a deadline for the whole compile phase** (`task/compile-and-run-program`,
  `task/cmd`, `category/task/api/deadlines.py`): every command that runs before it ends gets at most
  the time left, the builds that tools run inside the phase included (a LibTorch or llama.cpp built
  from source by a dependency); a command stopped by it fails with "stopped after N s: the compile
  deadline of M s (--compile_timeout) passed", one that would start after it is not started. Before,
  only the program's own compile command was limited. The deadline ends with the compile phase, so
  `--timeout` alone governs the run phase; without the option nothing is limited.
- **LibTorch source build:** `cmake --install` installs into `<entry>/build/install`, apart from the
  build tree (`program/build-torch-cpp`); before, the prefix was the build tree itself and CMake
  deleted `protoc` while installing it onto itself (its RPATH check), so the install never finished
  on Linux. `tool/torch-cpp` hands the installed library to the detection. The test programs of
  `build-torch-cpp` and `test-nmm-torch-cpp` take the C++ standard LibTorch's CMake config asks for
  (17 up to 2.8, 20 from 2.9, whose headers use `requires`); `--cxx_standard` overrides it.
- **A program's Python venv stays its own** (`category/task/api/v2.py`, `task/setup`, `tool/python`):
  - **A request without a venv of its own** (no `with.venv_path`, `with.venv_here`, `tool_path`,
    `with.here` or `--path`) no longer reuses the venv that a program or a tool made inside its own
    cache entry (`venv_path` under `task--program--<name>/`). Before, such a venv matched too, and in
    quiet mode its higher version often won, so it received the packages of unrelated tasks. The
    rest is as before: detected Pythons (the venv cMeta runs from, an activated venv), venvs made in
    their own cache entry (plain requests, `--version`) and venvs at places the user chose (`--path`,
    `--use.venv.path`, `venv_here`) are shared by version. README with the rules.
  - **A request with its own venv path** looks for a python only in that venv: an existing venv
    there is reused, else it is made. Before, a venv found on `PATH` (an activated one, or the one
    cMeta runs from) could be recorded as that request's venv, and in quiet mode an existing venv
    at that path without a cache entry was wiped and made again.
  - **Task engine:** a task can drop cache entries that match the cache query but are not meant
    for the request (`filter_cache_artifacts`); `task/setup` passes it on to the tool
    (`filter_tool_cache_artifacts`). Tasks and tools without it behave as before.
  - **`task/venv`:** an error message used an undefined name; `qpath_to_python` held the activate
    script.
- **Static Linux links of OpenSSL** (`tool/lib-zlib`, `tool/lib-zstd`, `tool/lib-jitterentropy`,
  new; `category/tool/api/common_static_lib.py`; `tool/lib-openssl`):
  - **New tools:** zlib, Zstandard and the Jitter RNG as static libraries built from their pinned
    source releases (SHA-256 checked) with the C compiler of cMeta, into the cache: no root, no
    system package. Linux and macOS.
  - **`tool/lib-openssl`:** a static link on Linux links only the libraries that the
    distribution's `libssl.a`/`libcrypto.a` need (`nm -u`), each from the system's static archive,
    else from its tool; `--with.static_deps=cmeta` always uses the tools. Before, `-lz -lzstd` were
    always added and the link failed where those archives were missing. Dynamic links and
    macOS/Windows are unchanged.
  - **`test-nmm-c-cpu`, `test-nmm-cpp-cpu`:** pass `with.static` to `lib-openssl` for static builds
    on Linux.
- **Go and Rust programs on Android** (`tool/go-android`, `tool/rustc-android`, new):
  - **`cx program run test-nmm-go-cpu android-cpu`** builds with the host's Go for the device's ABI
    (`GOOS=android`, `GOARCH`, `CGO_ENABLED=0`, `-buildmode=pie`; no NDK needed) and runs it over adb.
  - **`cx program run test-nmm-rust-cpu android-cpu`** builds with the host's rustc for the device's
    Rust target, whose standard library rustup adds the first time, linked by the Android NDK's clang
    for the device's API level.
  - Host builds keep `tool/go` and `tool/rustc`: the new tools support only `android-cpu`.
  - **`task/setup-compile`:** the compile command also gets the compiler tool's `features.env` (the
    program's own env wins); no other tool sets one.
- **`test-nmm-rust-cpu`:** writes `tmp-cmeta-program-stats.json` like the C and Go versions; before,
  the file its description declares was missing.
- **`test-nmm-swift-cpu`:** no longer declares `android-cpu`, which no Swift compiler tool supports,
  so a run for it stops at once.
- **`tool/openjdk`:** on musl Linux (Alpine) the default JDK is Temurin's `alpine-linux` build;
  before, the glibc build was downloaded and did not run there.
- **LibTorch for C++ programs** (`tool/torch-cpp`, `program/build-torch-cpp`, `program/test-nmm-torch-cpp`;
  `tool/torch-cpp-prebuilt`, new; `category/tool/api/common_libtorch.py`, new):
  - **Prebuilt LibTorch:** `--with.build=prebuilt` (`--setup_torch_cpp.build=prebuilt` for
    `test-nmm-torch-cpp`) uses PyTorch's official archive instead of a source build: 2.7.1 for Linux
    x86_64 and Windows x64 (cpu, cu118, cu126, cu128), Windows ARM64 (cpu) and macOS arm64 (cpu, with
    MPS), SHA-256 pinned. For CUDA the newest build with code for every GPU that the driver supports is
    chosen; `--with.variant` picks one. `tool/torch-cpp-prebuilt` caches the archive; the setup of
    `tool/torch-cpp` with it is not cached, so its source-build entries keep their cache identity.
  - **Source builds enable only the target's backends by default:** CUDA, cuDNN, ROCm, MPS and XPU are
    off unless the target asks for them; before, PyTorch's CMake enabled what it found (a CPU build on
    a machine with CUDA tried to build CUDA). `--with.strict_compute=False` restores that. Existing
    cache entries keep matching. On Linux, programs linked with LibTorch find LLVM's libomp.
  - **`tool/torch-cpp`:** detects the LibTorch a build installed (its library, its version from the
    headers).
  - **`test-nmm-torch-cpp`:** compiles (`customize_compile` failed) and runs its program (the run step
    had no command); the compile and run steps get the same `--setup_torch_cpp.*` options; `Torch_DIR`
    is set; CUDA builds of LibTorch get `nvcc` and `USE_SYSTEM_NVTX`; on Windows the MSVC-built archive
    is compiled with `clang-cl` when cMeta chose `clang++`. README with the options.
- **An OpenSSH server run as the user** (`tool/openssh-server`, `task/run-openssh`, new):
  - **`cx task run run-openssh --keys=<public key file>`** starts sshd on a port of its own (2222)
    with key-only logins, as the user: no service, no administrator. `status` shows it, and `stop`
    ends it together with its logins.
  - **Address:** the machine's Tailscale address (`tailscale ip -4`) by default, else 127.0.0.1;
    `--listen` picks another.
  - **Keys:** `--keys` takes public key files, `authorized_keys` files or keys; without it, the
    user's `~/.ssh/authorized_keys`.
  - **The server:** Windows gets the portable Win32-OpenSSH release (x64, ARM64, SHA-256 pinned) in
    the cache, and logins get cmd.exe; Linux and macOS use the system sshd. Its host key,
    configuration and log stay in a cache entry, one per `--name` and port.
- **JDKs of five vendors** (`tool/jdk-temurin`, `jdk-microsoft`, `jdk-corretto`, `jdk-zulu`,
  `jdk-oracle`, new; `category/tool/api/common_jdk.py`):
  - **Install:** the latest release of `--with.feature` (the major version, default 25) for this OS
    and CPU (x64, aarch64), from the vendor's API or download site, checked against the vendor's
    SHA-256. Temurin also has a musl (Alpine) build. `--version` pins a release (Temurin, Microsoft,
    Zulu). Oracle's license applies to the Oracle JDK.
  - **Separate tools, so nothing changes for `tool/openjdk`:** its detection of an installed JDK,
    its Temurin download and its cache entries stay as they were. The vendor tools store their
    result as `openjdk` too.
  - **`tool/javac`, `tool/java`:** `--with.vendor=<vendor>` (and `--with.feature`) uses that vendor's
    JDK; without it, `tool/openjdk` as before.
  - **`test-nmm-java-cpu --jdk=<vendor>`** (and `--jdk_feature`) compiles and runs with it.
  - **`task/compiler`:** `tool_with` passes `with` to the setup of the compiler tool (the javac of a
    vendor); without it nothing changes.
- **`tool/java`:** the version is read from `openjdk version "…"` and `java version "…"` (Oracle
  JDK); before, the word "version" was taken as the version, and Oracle's output was not read.
- **`task/setup-compile`:** the program's target name is also used with an explicit target extension
  (Java's `Program.class`); before, `program.class` was expected, which only file systems that ignore
  case found.
- **`tool/rustup`:** runs `rustup-init` by its full path; it failed where cmd.exe does not search the
  current directory (`NoDefaultCurrentDirectoryInExePath`).
- **`polybench-gemm-cpu-cuda`:** sets up `lib-cuda` for CUDA targets, so a CUDA runtime from the
  cMeta cache (CUDA 12 for an older GPU) is on the run-time library path.
- **`tool/mpi`:** `--with.build=source|pip`. The source build compiles Open MPI from its release
  tarball (SHA-256 pinned) into the tool's environment, with mpi4py built against it, so that macOS
  and Linux nodes can run one job; it is the default on macOS (it needs the Xcode Command Line
  Tools). The build is part of the cache identity, so the first setup after this change installs the
  wheel again into a new entry.
- **Timeouts for program runs:** `cx program run <program> --timeout=<seconds>` limits each run
  command, `--compile_timeout=<seconds>` each compile command (the template passes them to its
  `cmd` steps). The default stays without a limit.
- **`task/cmd`:**
  - **Timeouts:** a command that runs past `--timeout` is stopped with all its subprocesses (a
    process group on Linux and macOS, a Job Object on Windows), and the task fails with "timed
    out". Before, the stopped command's return code (-1) counted as a success. With
    `fail_if_nonzero_return_code=False` the result has `timed_out: True`.
  - **Any return code but 0 fails:** a negative code (a command ended by a signal on Linux and
    macOS) passed as a success before.
  - The working directory is restored when the command fails, too.
- **LiteRT for Android from its official releases** (`tool/lib-litert-android`, new):
  - **Contents:** the AAR from Google Maven (`libLiteRt.so` with its C API and the GPU
    accelerator, per ABI; Maven's SHA-256), the C/C++ SDK headers (with the `build_config.h` that
    CMake would generate), the NPU dispatch libraries (Google Tensor; Qualcomm HTP v69-v81) and
    the release's MobileNet v2 test model. GitHub's SHA-256 digests come from the release API,
    pinned for the default release (2.2.0).
  - **As a `lib-*` tool:** an NDK build links `-lLiteRt` with its headers, and setup-run pushes
    the arm64-v8a runtime, GPU accelerator and Google Tensor NPU libraries to the device.
- **ExecuTorch for Android from source** (`program/build-executorch-android`, new): builds
  `executor_runner` with the XNNPACK (CPU) and Vulkan (GPU) backends, which the prebuilt runtime
  lacks. It cross-compiles with the NDK and uses the LunarG `glslc` for the shaders (NDK r29's
  lacks `GL_KHR_cooperative_matrix`). A CPU torch, in a venv next to the build folder, does the
  code generation.
  - **Options:** `--checkout=<tag|branch|commit>` (default v1.5.1, cloned with its submodules),
    `--vulkan=OFF`, `--android_abi`, `--android_api` and `--cmake_flags`.
  - **The binary** is stripped (15 MB).
  - **Build environment:** ninja goes on PATH, because XNNPACK's nested CMake builds look for it
    there.
- **`tool/pip-mlx`:** refuses CUDA for GPUs older than Volta (7.0) before the install, because
  MLX's CUDA kernels need `__grid_constant__`.
- **Apple MLX for every target** (`tool/pip-mlx`, new): `cx tool setup pip mlx` picks the
  backend from the targets.
  - **Backends:** Metal on Apple silicon, `mlx[cuda13]` or `mlx[cuda12]` on Linux with NVIDIA
    GPUs (from the driver and the oldest GPU), and `mlx[cpu]` on Linux and Windows.
  - **Windows:** MLX 0.32 declares its `cpu` extra for Linux only, although `mlx-cpu` has Windows
    wheels. The setup names `mlx-cpu` there; before, `import mlx.core` failed with "DLL load
    failed".
- **The Android NDK without Java** (`tool/google.android-ndk`):
  - **Install:** the setup downloads the NDK zip for this host OS from Google's repository, checks
    it against the SHA-1 of Google's repository index, and unpacks it with its file modes and
    symlinks. It needs no Java, no sdkmanager and no administrator rights. Before, it always went
    through the SDK command-line tools, so a machine without Java (a container, a fresh Linux)
    could not get an NDK.
  - **Fallback:** sdkmanager is still used on Linux ARM, for which Google publishes no zip.
  - **Detection:** it now also looks in Android Studio's SDK folders, and detecting an installed
    NDK no longer sets up the command-line tools first.
- **Tools for distributed runs:**
  - **`tool/ray`:** Ray `ray[default]` 2.59.0 in its own Python environment. Every node of a Ray
    cluster needs the same Python down to the patch release (3.12.3 and 3.12.14 refuse each
    other), so the tool pins Python 3.12.14 and uv installs that same build everywhere.
  - **`tool/mpi`:** `mpiexec` and the MPI library. The setup uses a system MPI when it has one
    (Open MPI, MPICH, Intel MPI, MS-MPI). Otherwise it installs one from PyPI, without root,
    with mpi4py in the same environment: Open MPI 5.0.11 (Linux, macOS), MPICH 5.0.2 (Linux,
    macOS) or the Intel MPI runtime 2021.18.1 (Linux, Windows; the default on Windows).
    `--with.mpi=openmpi|mpich|intel` picks one, and the choice is part of the cache identity.
    The launcher's folder goes on PATH (`mpicc` is next to it), and `features.python` is the
    environment's Python.
  - **`common_pyvenv`:** the spec key `bin` names the folder that holds the command, for packages
    whose programs are data files rather than console scripts (`impi-rt` on Windows:
    `Library/bin`).
- **ExecuTorch on Android, with no app and no source build** (`tool/executorch-android` and
  `tool/android-d8`, new):
  - **`executorch-android`:** the official runtime, PyTorch's AAR on Maven Central. The tool
    reads the dependencies from the POMs (fbjni, nativeloader, kotlin-stdlib), checks every file
    against Maven Central's SHA-256 (SHA-1 for old artifacts) and unpacks the native libraries per
    ABI and the Java classes.
    - Its library registers XNNPACK (CPU) only and exports only JNI. Programs use its Java API,
      from the adb shell through `app_process`.
  - **`android-d8`:** Android's dexer. It uses the `d8.jar` of an installed SDK, else downloads
    the pinned r8 jar from Google's Maven and checks its SHA-256.
  - **`setup-run`:** `run_on_host: True` runs a program with an Android target on the host, so it
    can drive the device itself: export models with the host's Python, then push and run them
    with adb.
- **Fixes:**
  - `clone-git-to-cache` now passes `branch`, `new_branch` and `update_submodules` to `clone-git`.
    They were part of its cache identity but never reached git.
  - `tool/pytorch` names `build-pytorch` by its current UID. Its build path had failed since that
    UID changed.
- **flatc, the FlatBuffers compiler** (`tool/flatc`, new). The setup uses an installed flatc when
  it finds one. Otherwise it downloads the pinned GitHub release for Windows, macOS (arm64 and
  x86_64) or Linux x86_64, whose static binary runs on every distribution, Alpine included. It
  checks the download against the SHA-256 that GitHub lists for it. Linux on other CPUs gets the
  distribution's package. ExecuTorch's exporter needs flatc on Windows: point `FLATC_EXECUTABLE`
  at it.
  - `common_release` specs can pin digests per version and asset (`checksum: {'sha256': ...}`),
    for releases that publish no checksum file.
- **setup:** the "this installation requires SUDO" warning now appears only when the sudo command
  runs. Before, it also appeared before a release download that needs no root (rclone, zstd,
  flatc).
- **JAX for every target** (`tool/pip-jax`, new; see its [README.tech.md](tool/pip-jax/README.tech.md)):
  `cx tool setup pip jax` picks JAX's plugin from the targets.
  - **Plugins:** `jax[cuda13]` or `jax[cuda12]` (from the driver and the oldest GPU),
    `jax[rocm7-local]`, `jax[oneapi]` for Intel GPUs, and `jax-metal` with JAX 0.5.0 (the newest
    JAX that Apple's last plugin runs).
  - **Refused before any download:** platforms without a plugin (Windows: CUDA runs in WSL2) and
    the integrated Intel GPUs that the oneAPI plugin cannot compute on (`--with.any_intel_gpu`
    tries anyway).
- **The Intel NPU user-space driver for Linux, without root** (`tool/intel-npu-runtime`, new; see its
  [README.tech.md](tool/intel-npu-runtime/README.tech.md)):
  - **The driver:** the kernel's `intel_vpu` driver does not bring the NPU's Level Zero driver or
    the compiler in driver that OpenVINO's NPU plugin needs.
  - **Detection:** the setup uses the system's driver (`intel-level-zero-npu`) when it has one.
  - **Install:** otherwise it unpacks Intel's release packages for the Ubuntu release (24.04 or
    26.04) into the cache, with the Level Zero loader and, when missing, oneTBB. Every archive is
    checked against its sha256.
  - **What it refuses or skips:** a glibc older than 2.38 fails before any download. The
    firmware package, which needs root, is left out.
  - **The npu-intel target:** on Linux x86_64 it sets the driver up once it finds the NPU
    (`--use.target--npu-intel.skip_runtime` skips it). When the NPU is on the PCI bus but has no
    accel device, the error says the kernel lacks its `intel_vpu` driver or its firmware.
  - **Shared helpers:** the `.deb` helpers of `tool/intel-gpu-runtime` moved to
    `category/tool/api/common_deb.py`, which both tools use.
- **The opencl, android-gpu and android-npu targets** (see [tool/opencl/README.tech.md](tool/opencl/README.tech.md)
  and [task/target/README.tech.md](task/target/README.tech.md)):
  - **opencl** (`tool/opencl`, new):
    - The OpenCL platforms and devices come from the ICD loader itself (ctypes, no SDK, no
      clinfo), on Windows, Linux and macOS.
    - On Linux, the ICD loader is installed (with sudo) only when a GPU can use it, and an Intel
      GPU gets `tool/intel-gpu-runtime` first.
    - CPU-only OpenCL fails unless `--use.target--opencl.allow_cpu`.
    - gcc, g++, clang, clang++ and MSVC now declare `supports_compute: opencl`.
  - **android-gpu** and **android-npu** cover the Android device that android-cpu selects:
    - android-gpu records the GPU: its Vulkan devices, GLES driver and OpenCL library;
    - android-npu records the NPU: the NNAPI accelerators and the vendor stack (Samsung ENN,
      MediaTek APU, Google TPU, Qualcomm);
    - programs built for them with the NDK are pushed and run over adb, like Android CPU
      programs: `setup-run` and `compile-and-run-program` treat every Android target alike, and
      the NDK clang tools declare both targets.
- **Vulkan needs a GPU** (`target--vulkan`, `tool/vulkan`, see its
  [README.tech.md](tool/vulkan/README.tech.md)):
  - **Target:** a vulkan run on a machine where Vulkan sees only CPU devices (Mesa's llvmpipe) now
    fails, instead of warning and computing on the CPU. `--use.target--vulkan.allow_cpu` accepts
    them. A cached target is checked again.
  - **Tool:** `tool/vulkan` no longer installs Mesa (with sudo) on a Linux machine with no device
    node to reach a GPU: no DRM render node, no WSL2 `/dev/dxg`, no NVIDIA or AMD node. PCI
    display devices without a node are named in the message. `--with.allow_cpu` installs it anyway.
- **CUDA toolkits of any version, without root, with the host compiler they support** (`tool/nvcc`,
  see its [README.tech.md](tool/nvcc/README.tech.md)). nvcc skips the toolkits whose programs could
  not run here: those whose oldest architecture is newer than the GPU (CUDA 13 dropped Maxwell to
  Volta), and those for a newer major CUDA version than the driver's. When none suits, or
  `--version` asks for another, it installs one from NVIDIA's redistributable archives: the newest
  release that suits the GPU and the driver, with each archive checked against NVIDIA's sha256 and
  unpacked into the cMeta cache. `--version` is nvcc's (`12.9`, `12.9.86`, a range); a CUDA release
  label gets a hint.
  - **Libraries on demand:** `--with.cuda_libs` and `lib-cuda`'s `lib_names` add cuBLAS, cuFFT and
    the others to a toolkit made from the archives, once. Without `-q`, it asks first.
  - **The host compiler** is set up once the toolkit is known: the newest GCC, clang or MSVC that
    the toolkit's `host_config.h` accepts (Visual Studio 2022 for CUDA 12.x, when Visual Studio
    2026 is also installed). It is passed to nvcc as `-ccbin`, through the new `host_compiler` flag
    of `setup-compile`.
    - `--use.<tool>.version` still decides.
    - An unsupported compiler set up earlier in the run stops the run, with the option to use.
    - `--with.any_host_compiler` adds `-allow-unsupported-compiler`.
  - **`--with.arch_flags`:** a GPU newer than the toolkit gets PTX, which the driver compiles (it
    got machine code the GPU could not run). A GPU older than the toolkit gets an error, instead of
    code for another GPU.
  - One nvcc cache entry per GPU architecture.
  - **`microsoft.visual-studio`:** a version (cl.exe's, such as `<19.50`) picks the Build Tools
    release to install. A version that no release has installs nothing; before, it installed the
    newest.
- **Agent tasks renamed: `run-claude2` -> `run-claude`, `run-codex2` -> `run-codex`,
  `run-opencode2` -> `run-opencode`**, and the first `run-claude` prototype is removed. The
  tasks keep their UIDs, so references by `alias,UID` (`run-claude2,38be73ffceaa4f67`) keep
  working; commands that name `run-claude2` alone need the new name. Also renamed:
  - the default output files (`run-claude-output.txt`, `run-codex-output.txt`,
    `run-opencode-output.txt`);
  - the `task` field of their statistics;
  - their key in a pipeline's context: a task that reads `local['run-claude2']` reads
    `local['run-claude']` now.

  After pulling, run `cx --reindex`, because task folders moved.
- **xpu on Linux sets up the Intel GPU compute runtime, without root** (`tool/intel-gpu-runtime`, see its
  [README.tech.md](tool/intel-gpu-runtime/README.tech.md)). An Intel GPU computes through a user-space
  runtime the kernel driver does not bring: the OpenCL ICD, the Level Zero driver, the graphics compiler,
  gmmlib and the Level Zero loader. The tool uses the system's when it has one; otherwise it downloads
  Intel's release packages, checks their sha256 and unpacks them into the cMeta cache. The release line
  follows the GPU's PCI id: 26.35 for Gen12 and later (also WSL2), legacy1 24.35 for Gen8-Gen11. The
  result exports `LD_LIBRARY_PATH` and `OCL_ICD_FILENAMES`, so the system's ICD loader adds the Intel GPU
  next to the others. It warns when the user cannot open `/dev/dri/renderD*` (the render group).
  - `target --compute=xpu` sets it up on Linux x86_64 once the Intel GPU is found, so every program run
    on xpu gets the runtime. In WSL2, where lspci sees a virtual adapter, the target asks Windows for
    its GPUs.
  - `test-onnxruntime` lists OpenVINO's devices in a separate process: on Linux the `openvino` package
    and `onnxruntime-openvino` each bring a `libopenvino.so.2541`, and loading both in one process broke
    the OpenVINO EP.
  - Tested on Ubuntu with a Gen12 Iris Xe (the 26.35 line) and a Gen9 HD Graphics 630 (legacy1):
    `test-openvino` and `test-onnxruntime` run on xpu.
- **LLM stacks on CPU, CUDA, Vulkan and Metal: the newest llama.cpp, vLLM 0.30.0, Ollama 0.35.0 and
  PyTorch 2.14.1**, installed or built from source with the same commands on Windows, Linux/WSL2 and
  macOS. The guide is the new [`docs/cmeta-aops/llm-stacks.md`](docs/cmeta-aops/llm-stacks.md).
  - **llama.cpp** (`tool/llama-cpp`, default build 11324): the asset comes from the release's own list
    (`releases/expanded_assets/b<N>`; the builds are prereleases and `/releases/latest` has no
    binaries), for the OS, the CPU and the backend (cpu, cuda, vulkan, rocm, sycl for xpu, openvino,
    metal). CUDA builds are matched to the driver (minor-version compatibility), the `cudart` bundle
    is installed next to them, and the Linux CUDA builds explain that they need glibc 2.38+. The
    version is read from both the new (`version: 0.5.0-dev (build N, ...)`) and the old output.
  - **llama.cpp programs**: `llama-completion` runs the generation (`llama-cli` is now the chat UI).
    The timings in `llama.log` become `perf.json` (result `perf`): prompt and generation tokens per
    second, load and total time, the device used and the layers offloaded to it (the runs pass `-v`,
    as newer builds log them only then), the build and commit, and the CUDA architectures.
    `--compute=cpu` keeps the model on the CPU (`-ngl 0 --device none`).
  - **build-llama-cpp**: Vulkan builds (`GGML_VULKAN`, the loader library from `tool/vulkan-sdk`);
    OpenSSL is optional (the system library, else `LLAMA_OPENSSL=OFF`, or `--compile.boringssl`);
    Ninja, CMake and the compilers reach nested CMake projects (`vulkan-shaders-gen`). The default
    checkout is `b11324`, the build the release tool installs (it was master as of the first clone);
    `--model` and `--prompt` work as in `program/llama-cpp`; on macOS, builds without `metal` leave
    Metal out, so a CPU build opens no GPU.
  - **Vulkan**: `tool/vulkan` lists the devices through the loader itself (ctypes, no SDK and no
    `vulkaninfo`; MoltenVK through portability enumeration). `tool/vulkan-sdk` detects an SDK in
    `$VULKAN_SDK`, the LunarG folders, the distribution or Homebrew. Otherwise it installs the pinned
    LunarG SDK 1.4.363.0 without administrator rights (Linux x86_64: the tarball; Windows: the
    installer in copy-only mode), or uses Homebrew or the distribution packages. `target--vulkan`
    is new, and gcc, g++, clang, clang++ and MSVC now declare `supports_compute: vulkan`.
  - **vLLM**: `tool/pip-vllm` picks the wheel index for the target and driver: PyPI's CUDA 13.0 build
    for driver R580+, the cu129 build for older drivers, and the CPU, ROCm and XPU indexes. It checks
    for Python 3.10–3.14 (3.12 on macOS), and on native Windows it tells you to use WSL2.
    `program/test-vllm` is rewritten (stats JSON, the venv's bin on PATH for FlashInfer's JIT,
    `libnuma` for the CPU through the new `tool/lib-numa`). The new `program/build-vllm` builds from
    source with `VLLM_TARGET_DEVICE`, `CUDA_HOME`, `TORCH_CUDA_ARCH_LIST` from the detected GPU and
    `MAX_JOBS` sized to the RAM.
  - **PyTorch** (`build-pytorch`, default `v2.14.1`): the scikit-build-core build
    (`pip install --no-build-isolation -v .` after `requirements-build.txt`), `TORCH_CUDA_ARCH_LIST`
    from the detected GPUs (without one, CUDA 13 rejects PyTorch's default list), `BUILD_TEST=0`,
    `PYTORCH_BUILD_VERSION` from the tag, `DISTUTILS_USE_SDK=1` on Windows, and
    `CMAKE_POLICY_VERSION_MINIMUM=3.5` (CMake 4 refuses the helper projects NNPACK downloads).
  - **Ollama**: `tool/ollama` installs the pinned portable release into the cMeta cache, with no
    installer, no service and no administrator rights. The Linux `.tar.zst` is unpacked by a Python
    3.14 (uv downloads one) before any `sudo` package is tried. `tool/zstd` is new, and
    `program/test-ollama` runs a private server on its own port and records Ollama's timings and VRAM
    use, and stops the model runners with it (on Windows they outlived the server, holding RAM and VRAM).
  - **Source builds size `MAX_JOBS` to the RAM** (`category/program/api/common_build.py`: 4 GiB per
    CUDA job, 2 GiB per C++ job), because PyTorch's and vLLM's builds start one job per CPU.
- **Targets: selecting, combining and comparing them on one machine**
  ([`task/target/README.tech.md`](task/target/README.tech.md)):
  - `--target` is `--compute` by another name; before, it was ignored and the program ran on the CPU.
    `cx program targets` lists the targets.
  - **Fix: a change of targets in the same build folder builds again.** The targets were read before
    the target task resolved them, so a `--compute=metal` run after a `--compute=cpu` build reused the
    CPU build and its run flags, and ran on the CPU. `cpu,cuda` -> `cuda` now counts as a change too.
  - `--target_tmp=auto`, or `cx config set task --meta.compile_and_run_program.target_tmp=auto`, gives
    every set of targets its own build folder (`tmp-cuda`, `tmp-cpu-cuda`); builds for different
    targets stay side by side.
  - `test-vllm`, `build-vllm` and `build-pytorch` set up Python in a venv of their own, one per set of
    targets (`venv-<targets>`), so the CPU and the CUDA builds of torch never replace each other.
  - Splitting a model across devices:
    - llama.cpp: `--ngl`, `--devices`, `--split_mode`, `--tensor_split`, `--main_gpu` and
      `--threads`. They are set at run time (a reused build brought back the flags of the run that
      compiled it), and `perf.json` records them with the targets.
    - Ollama: `--ngl` (its `num_gpu`).
    - vLLM: `--cpu_offload_gb`, `--tp`, `--dtype`, and `--enforce_eager=0` for CUDA graphs.
  - A llama.cpp release build refuses two GPU targets, since it has one backend. `nvcc` declares
    `supports_compute: vulkan`, so `build-llama-cpp --compute=cuda,vulkan` builds both backends.
  - `README.tech.md` files with every cMeta option: targets (`task/target`), llama.cpp
    (`tool/llama-cpp`), vLLM (`tool/pip-vllm`), Ollama (`tool/ollama`), PyTorch
    (`program/build-pytorch`) and Vulkan (`tool/vulkan`). The programs point to them.
- **The Intel NPU and OpenVINO as targets** (`task/target--npu-intel`, `task/target--openvino`,
  `program/test-openvino`; every option in
  [`program/test-openvino/README.tech.md`](program/test-openvino/README.tech.md)):
  - `npu-intel` finds the NPU without any SDK, by its PCI ID: the PnP `ComputeAccelerator` devices on
    Windows (with the driver version), the `intel_vpu` accel devices on Linux. It records the platform
    (Meteor Lake to Nova Lake) and the NPU generation. `openvino` is the stack target.
  - `test-openvino` runs a matmul and a ReLU on each device the targets name (`npu-intel` -> NPU,
    `xpu` -> GPU, `cpu` -> CPU; `openvino` alone: every device OpenVINO finds). Each device is named
    in `compile_model`, never AUTO, and checked against `EXECUTION_DEVICES`, so a failing device
    cannot pass on the CPU. It records the device's properties, the compile time, the latency and
    the error against NumPy; `--size` and `--batch` choose a bandwidth- or a compute-bound matmul.
  - `program/llama-cpp` accepts `xpu` (the SYCL release), `npu-intel` and `openvino` (the OpenVINO
    release; `npu-intel` sets `GGML_OPENVINO_DEVICE=NPU`). A release has one accelerator backend, now
    counted by backend, so `npu-intel,openvino` is one. Device names with parentheses
    (`Intel(R) Graphics`) are recorded whole.
  - Tested on a Panther Lake laptop: `test-openvino` on the NPU, the Intel iGPU, the NVIDIA GPU
    (OpenVINO's `GPU.1`) and the CPU; llama.cpp on the iGPU with the SYCL release and with the
    Vulkan release (`--devices=Vulkan0`). llama.cpp on the NPU is not tested yet.
- **ONNX Runtime per target** (`tool/pip-onnxruntime`, `program/test-onnxruntime`; see
  [`program/test-onnxruntime/README.tech.md`](program/test-onnxruntime/README.tech.md)):
  - `setup pip onnxruntime` installs the build that fits the targets: `onnxruntime-gpu[cuda,cudnn]`
    for CUDA (CUDA and cuDNN from pip), `onnxruntime-openvino` for the Intel NPU and GPU (with the
    `openvino` release it was built against), `onnxruntime-migraphx` for AMD, else `onnxruntime`.
  - `test-onnxruntime` runs a small ONNX model on each target's execution provider alone, with
    the CPU fallback disabled, and records the provider, latency and error against NumPy
    (`--size`, `--batch`, `--seconds`).
  - `image-classification-onnx` uses one venv per set of targets and the OpenVINO device of the
    target (`npu-intel` -> NPU, `xpu` -> GPU), and warns when its provider is not the active one.
  - `xpu` runs on the Intel GPU only: OpenVINO's GPU plugin also drives NVIDIA GPUs through
    OpenCL, so `test-openvino` and `test-onnxruntime` pick the GPU whose name says Intel, and fail
    when there is none.
  - `install-sys-tool --check_binary=<binary>` skips the install when the binary is on the PATH:
    `target--xpu` no longer runs `sudo apt-get install pciutils` when `lspci` is there.
  - Tested on Windows (the CPU, CUDA, the Intel NPU and GPU) and Ubuntu (the CPU, CUDA; the NPU
    target reports no NPU on machines without one).
- **llama.cpp on Android devices** (`--compute=android-cpu`, over adb; see
  [`tool/llama-cpp/README.tech.md`](tool/llama-cpp/README.tech.md)):
  - `program/llama-cpp` runs llama.cpp's own Android release (`android-arm64`, every CPU variant,
    the best one picked on the device). It is downloaded here and never run here; its build is
    recorded next to it for the version check.
  - `build-llama-cpp` builds with the NDK's CMake toolchain file and the release's settings
    (arm64-v8a, android-28, shared libraries with all CPU variants, no OpenMP, no OpenSSL).
    `--max_jobs=N` limits the parallel compile jobs on any target.
  - `task/setup-run` keeps folders and large files on the device between runs: the binary with
    its libraries in `/data/local/tmp/cmeta-llama-cpp/<variant>/` and the model in
    `/data/local/tmp/cmeta-models/`. They are pushed once, and again only when they change.
  - **Fix:** a program without a binary of its own made `task/setup-run` run
    `rm -rf /data/local/tmp/` on the device, emptying its work folder. That command now runs only
    for a program's own binary.
  - Tested on a Pixel 10 Pro (Android 17): the release and the NDK r29 source build, with several
    thread counts.
- **The Android NDK lists its versions:** `cx tool setup google.android-ndk --status` shows what
  the SDK offers (`sdkmanager --list`), and `--upgrade` installs the newest one side by side. More
  generally, `--upgrade` now installs the newest version of every tool whose install command
  takes a version and whose versions are known, instead of running the pinned install again.
- **Test sessions: a sandbox and a kept log for every test** (`task/test-session`, see its
  [README](task/test-session/README.md)). `cx task run test-session --start --type=<type>` gives a
  sandbox to work in and a record that stays when the sandbox goes, as the folder
  `<YYYYMMDD>/<HHMM>.<type>/` (the session id) of two artifacts of the local repository:
  `tmp::cmeta-aops-test-sessions` (the new `category/tmp`, for disposable folders; `cx tmp prune`)
  and `log::cmeta-aops-test-sessions` (`session.md`, `session.json`, attachments). `--list` filters by
  date, type, status and host; `--migrate` moves the folders of the first version
  (`<CMETA_HOME>/tmp|log/cmeta-tests-*`) there. The
  log records the host, cMeta, the repositories' branch, commit and changed files, and the agent
  (`CMETA_GENERATOR`, the Claude Code session). Notes, results and attached files are added during the
  test. The costs are the wall time, the sandbox size, and the tokens the Claude Code session used
  meanwhile, read from its transcripts (with configured prices, the cost in USD too). Finishing
  removes a sandbox above 1 GiB; `--list` and `--prune` keep the overview. `AGENTS.md` §7.1 makes
  test sessions the rule for every real test.
- **`cx tool setup <tool> --status` and `--upgrade`** - for every tool, with no change to its `_desc.yaml`
  (`task/setup/upgrade.py`). The tool's install **channel** on this OS is derived from its install command
  or hook - winget, Homebrew, the distro package manager (`install_cmd_sudo`), an upstream install script,
  npm, pip, or a release download - and decides which version counts as "latest" and what the upgrade runs:
  - `--status` lists every copy found (the cMeta cache entries `setup` replays first, then the PATH), the
    newest version the channel offers (`winget show --versions`, `brew info`, `apt-cache policy` /
    `dnf info` / `apk policy` / `pacman -Si` / `zypper info`), the newest upstream version (the release
    GitHub marks as latest, read from the `/releases/latest` redirect - not the newest tag, which can be a
    pre-release), the command `--upgrade` would run, and a verdict. It installs nothing and writes nothing;
    Python callers get `result['status']`.
  - `--upgrade` upgrades a detected tool through its channel (`winget upgrade`, `brew upgrade`,
    `apt-get install --only-upgrade`, the install script again, `npm install X@latest`, pip's own update,
    the release download of the newest version into the same cache entry), detects it again and reports
    `before -> after`; a tool that is not installed gets the newest version. Several copies found: the
    usual selection prompt, `-q` takes the newest. The cache entry records the new version and a
    `last_upgrade` entry. `--update` is unchanged (it rebuilds the entry from what is installed).
  - Two optional `_desc.yaml` keys override the derivation: `upgrade_cmd` (per OS) and
    `cmd_get_latest_version` (+ `_regex`, `_uses`). `task/host` gained `upgrade_cmd(_sudo)` and
    `candidate_version_cmd/_regex` per package manager.
  - Also: a `check_params` stop (`--versions`, `--status`) now returns its data to the caller;
    `common_release` names checksum files per version (an in-place upgrade reused the old release's
    checksums) and drops a download whose SHA-256 did not match; `detect` returns every matching copy
    in `detected`.
  - apt refreshes its package lists when an install cannot find the package (a fresh container has
    none), and before an upgrade, since stale lists hold no newer version.
  - Tested: Windows (winget: uv 0.11.1 -> 0.12.21, opencode and git; release: jq 1.7.1 -> 1.8.2 in place),
    Debian and Ubuntu containers as root (apt: git, curl; release: jq), Ubuntu as a user (install script:
    claude; apt status without sudo), macOS arm64 (Homebrew: gh; install script: claude; release: helm).
    Offline unit tests in `tests/cmeta_aops_basic_tests/test_tool_upgrade.py`.
- **Visual Studio: every installation, Build Tools included.** `tool/microsoft.visual-studio` lists
  installations with `vswhere`; before, it searched only `C:` and `D:\Program Files`, and Build Tools
  live under `Program Files (x86)`. `--version` picks one by its `cl.exe` version. `--install` sets up
  the newest Build Tools with the C++ workload through winget (`--with.year=2022` for an older line).
- **Fix: a cached compute target described the machine that created it.** In a `CMETA_HOME` copied or
  shared between machines, WSL with an RTX PRO 1000 (sm_120) got the RTX A500 (sm_86) of another laptop,
  and the vLLM build compiled for 8.6. Now `target--cuda`, `target--rocm` and `target--vulkan` take the
  features of the tool set up in the same call. `target--metal` and `target--xpu` parse the probe that
  runs in each call, and `target--cpu` probes again when its host fingerprint changes. `target--xpu`
  also uses PowerShell CIM instead of `wmic`, which current Windows 11 builds no longer have.
- **Fix: source builds and `test-vllm` use their own Python venv.** On the P14s, `build-pytorch` reused
  the venv `build-vllm` had filled and replaced vLLM's torch 2.13.0 with the 2.14.1 it had built. The
  new torch then failed to import ("undefined symbol: cublasLtGroupedMatrixLayoutCreate"): it was built
  with the CUDA 13.3 toolkit (cuBLAS 13.6), but loaded the pip cuBLAS 13.1 of vLLM's torch. A build
  made before keeps its venv until `--recompile`. The venv of several targets is named with dashes
  (`venv-cpu-cuda`, from the new `{{global.target.cmeta_targets_tag}}`): on Windows, a comma in the
  path split the venv's activation command. Paths with spaces work too now (a Windows user name with a
  space puts one in the default `CMETA_HOME`): `tool/python` quotes the venv's activation script and
  its pip check, and `tool/python-pip` checks Python's plain path rather than the quoted one.
- **Fix: program parameters reach the run-time environment.** `task/setup-run` expands
  `local_vars.run_time_env` with its own parameters, so `{{params.X|default}}` there always gave the
  default: `--model`, `--n`, `--max_len` and `--cpu_kv_cache_gib` of `test-vllm` and `build-vllm`, the
  options of `test-ollama`, and `--repeat` of the milepost codelet. They now read `{{local.params.X}}`,
  where `compile-and-run-program` keeps the program's parameters, and a test checks every program for it.
- **Quiet installs never wait at a sudo password prompt.** With `-q` and a `sudo` that needs a password,
  every `sudo` in an install command runs as `sudo -n`. It fails at once, where an unattended run used
  to hang (15 minutes in one case), and cMeta prints the command to run by hand.
- **Engine fixes:** a failed optional sub-task no longer clobbers the caller's context. `detect()` hooks
  receive `tool_path`/`paths`, and a forced path is checked even when a tool has `find_paths()`.
  CUDA is detected with NVIDIA drivers 610+ (`nvidia-smi` prints `CUDA UMD version`).
- **Fix: `tool/ccache` downloads the right release asset.** The macOS branch left `uarch2` unassigned
  (an `UnboundLocalError` on every Mac) and asked for `ccache-<v>-macos.tar.gz`, which upstream never
  published - the asset is `ccache-<v>-darwin.tar.gz`, one universal binary. Linux asked for `.tar.gz`,
  while upstream publishes `.tar.xz`, since 4.13 as `ccache-<v>-linux-<arch>-{glibc,musl-static}.tar.xz`
  (musl on Alpine); Windows arm64 is `windows-aarch64.zip`. Verified: 4.13.6 installs from its release
  on Windows x86_64, macOS arm64 and Linux x86_64 (Debian container).
- **Fix: `cx tool setup <tool> --versions` lists releases only** for the tools whose regex also accepted
  pre-release or unrelated tags: `kubectl`, `pytorch` and `torch-cpp` (`\b` let `v1.38.0-alpha.0` yield an
  unreleased `1.38.0`), `go` (`rcN`), `codex` (`-alpha`), `openclaw` (`-beta`), `uv` (every tag), `openjdk`
  (`jdk-(.+)` matched the nightly `jdk25u-...-beta` tags), `python` (`3.14.0rc3`, `+freethreaded`),
  `obsidian`, `llvm`/`clang`/`clang-cpp` (`-rc1`, `-init`), and the generic regex of `ccache`, `cmake`,
  `node-js`, `rclone`, `rustc` and `lib-openssl-android`. `--version=<pre-release>` still installs one.
- **Fix: versioned installs that could never work are gone**: `tool/gh` asked Homebrew for `gh@2` /
  `gh2` and `tool/kubectl` for `kubectl@1.37.1` and a snap channel `1.37.1/stable` - no such formulae or
  channel exist. Without the entries task/setup reuses `install_cmd` (current), as `az` already does.

- **Docs: `--use.<storage key>.<param>=<value>`**, which changes any sub-task of a run from the command line,
  however deep it sits: a dependency's version, or a control switch such as `update` of one step.
  - a new section in `docs/cmeta-aops/task-engine.md`, "Changing a dependency anywhere in a pipeline": how it
    works, the storage keys of `setup`, `clone-git-to-cache`, `runner`, compilers and other tasks, and the control
    switches that travel with it;
  - a line in the README;
  - notes in the `add-task` and `add-tool` skills.
- **Tested on 2026-10-01 and 2026-10-02:** llama.cpp (release and source builds), vLLM, Ollama and
  PyTorch on Windows 11, WSL2, Ubuntu and macOS, on the CPU, CUDA, Vulkan and Metal targets each
  machine has, including several targets at once (`--compute=cpu,cuda --ngl=N`, and a
  `cuda,vulkan` build run with `--devices`).

## 0.40.1
- **`task/rclone-to-ssh`: a plain `bisync` now adds `--resilient --recover`** (turn off with `--no-recover`).
  Without these flags, an interrupted run (a dropped link, a killed shell) leaves its listings as `*.lst-err` or
  `*.lst-new`, and every later run aborts with "cannot find prior Path1 or Path2 listings ... Must run --resync
  to recover". One pair stayed broken this way for three days, and the batch never ran the pairs after it. With
  the flags, the next run resumes from the backup listings. The task notes also say how to recover by hand:
  remove a leftover `*.partial` file first, because a resync would copy it across, then run
  `resync ... -- --resync-mode newer`.
- **Fix: `tool/brew` finds Homebrew on macOS when it is not on PATH.** It now searches Homebrew's default
  prefixes (`/opt/homebrew/bin` on Apple silicon, `/usr/local/bin` on Intel). Before, a shell that had not
  run `brew shellenv` (an ssh command, cron, CI) did not see an installed Homebrew, so setting up any tool
  tried to install Homebrew again.
- **Tested 0.40.0 on macOS 27 (arm64):**
  - all 13 release tools install from their pinned release with SHA-256 verified (kwok publishes none), and
    the same functional checks pass as on Windows and Linux;
  - ansible (ping), ansible-lint, yamllint and aiperf work in their uv environments;
  - `scan-git-secrets` passes its history, files-only and baseline scans;
  - `slurm` and `aks-flex-node` explain that they need Linux, WSL or a login node.

## 0.40.0
- **Thirteen new tools installed from their pinned upstream release** (install ladder tier 1), on
  Windows, Linux and macOS, amd64 and arm64 wherever upstream publishes an asset:
  - Kubernetes: `tool/helm` (4.3.0), `tool/kind` (0.33.0), `tool/k3d` (5.9.0), `tool/kwokctl` (0.8.0,
    with the `kwok` binary next to it), `tool/kustomize` (5.8.1), `tool/flux` (2.9.5), and for AKS
    `tool/kubelogin` (0.2.20);
  - infrastructure as code: `tool/terraform` (1.16.4, BUSL-1.1) and `tool/opentofu` (1.12.6, MPL-2.0,
    the `tofu` binary);
  - repository hygiene and scripting: `tool/gitleaks` (8.30.1), `tool/jq` (1.8.2), `tool/yq` (4.53.6),
    `tool/golangci-lint` (2.14.0).

  They share a new helper, `category/tool/api/common_release.py`. Each tool's `api_v1.py` declares only
  where its assets live. The helper then:
  - picks the asset for the OS and CPU;
  - downloads it through `download-file`;
  - verifies its SHA-256 against the checksums upstream publishes (all but kwok, which publishes
    none), in any of three formats: a list, a per-asset file, or yq's multi-hash table;
  - unpacks the binary with Python's zipfile/tarfile, so no tar or unzip binary is needed.

  Pairs with no upstream asset (e.g. kind, k3d and OpenTofu on Windows arm64) print the install help
  instead. Every tool also lists its released versions (`cx tool setup <tool> --versions`). An
  installation already on the PATH is detected and used first.

  **Tests:** each tool installs from its release, checks the SHA-256 and reports the pinned version, on
  Windows and in a `python:3.12` Linux container. Offline checks also pass:
  - `helm create` + `helm template` renders 4 objects;
  - `kustomize build` produces a ConfigMap;
  - `terraform apply` and `tofu apply` output `hello = "world"` with no cloud account;
  - `jq` and `yq` extract values;
  - `gitleaks` finds a fake token and reports it as `REDACTED`.
- **Four new Python tools, each in its own environment:** `tool/ansible` (ansible-core 2.21.4),
  `tool/ansible-lint` (26.9.0), `tool/yamllint` (1.38.0) and `tool/aiperf` (0.13.0, the load
  generator for OpenAI-compatible LLM servers). A new helper, `category/tool/api/common_pyvenv.py`,
  sets up `tool/uv`, creates a virtual environment with a pinned Python (3.12; uv downloads it if
  missing) inside the tool's cache entry, and installs the pinned package. So the system Python and
  other tools' packages are never touched, and aiperf (Python 3.11-3.13) works on a machine whose
  Python is 3.14. Ansible and ansible-lint do not run on Windows (POSIX-only modules), so there they
  stop with a pointer to WSL or a Linux container; yamllint and aiperf work on Windows too.
- **New `tool/slurm` (detect-only):** the Slurm client commands (`sinfo`, `srun`, `sbatch`, `squeue`,
  `scontrol`) of a login node, or of the `slurm-client` package. Every Slurm command reads the cluster
  configuration first, even `sinfo --version`, so the version comes from the cluster when it is
  configured and otherwise from the package that installed the binary (dpkg or rpm). The result
  records `configured: false/true`. Tested in a Linux container with Debian's slurm-client and no
  cluster (version 24.11.5 from dpkg).
- **`tool/kubectl`:** the default version moves from 1.31.0 to **1.37.1**, the latest stable; kubectl
  supports one minor version of skew, so `--version=1.<minor>.<patch>` matches an older cluster.
- **New `task/run-openclaw`:** the OpenClaw sibling of `run-claude2`, `run-codex2` and `run-opencode2`,
  with the same flags (`--prompt`, `--prompt_file`, `--output_file`, `--stats`, `--interactive`/`--i`,
  everything after `--` for openclaw) plus `--agent`, `--session`, `--gateway` and `--dry_run`.
  - **Headless:** one agent turn with `openclaw agent --local --agent main --message <prompt>`. With no
    prompt, or with `--interactive`, it opens `openclaw tui --local` with the prompt as the first message.
  - **Windows:** the npm `.cmd` shim is bypassed and node runs `openclaw.mjs` directly, so cmd.exe never
    parses a prompt (no `&`, `|`, `%` injection).
  - **Provenance:** `CMETA_GENERATOR` records `OpenClaw <version>` with the model and thinking level.
  - **Tested on Windows:** dry runs of the three examples, and a real turn that reaches the model call
    and stops at the missing provider key.
- **New `task/scan-git-secrets`:** gitleaks over a repository's whole history (or, with `--files`, only
  its current files, or a plain folder).
  - **Output:** file, line, rule and commit, never the values (`--redact`, and the secret, match and
    e-mail fields are dropped), plus a value-free `--report`.
  - **Baseline:** `--baseline` accepts earlier findings by fingerprint, from this task's report or a
    native gitleaks one.
  - **Exit code:** 1 when something is found (`--no_fail` to always return 0).
  - **Tested:** on Windows and in a bare `python:3.12-slim` Linux container, on a scratch repository
    whose history holds a removed fake token: the history scan finds it, the files-only scan and a
    scan with the report as baseline are clean.
- **New `tool/aks-flex-node`** (the AKS Flex Node agent, https://github.com/Azure/AKSFlexNode,
  MIT, public preview). On Linux amd64/arm64 it downloads the pinned release archive (default
  `0.2.0`, any release with `--version=`) and verifies its SHA-256 against the release's
  `checksums.txt`. `--build --skip_install` builds it from git in the cMeta cache instead - at
  `v<version>`, or at any tag, branch or commit with `--with.checkout=<ref>` - with `tool/go`,
  stamping version, commit and build time the way upstream's Makefile does (a build of `main`
  reports e.g. `v0.2.1-alpha.1-7-g7f814fb`). The agent and its dependencies are Linux-only, so on
  Windows and macOS the tool says so and points to WSL or a Linux container, where the same `cx`
  commands work. Tested on Windows (the clear refusal) and in a `python:3.12` Linux container
  (release install, build at a tag, build of `main`).
- **`clone-git` gains `filter`, and `clone-git-to-cache` forwards `depth`, `filter` and `fetch`.** `filter`
  is git's partial-clone filter: with `--filter=blob:none` the full history is fetched but file
  contents only for the commits checked out, so a pinned checkout does not download blobs that exist
  only in old history (large files, or anything that should not have been committed) - as long as
  nothing reads them: `git show <old commit>`, `git log -p`, `git blame` and `git cat-file` fetch a
  missing blob on demand (`GIT_NO_LAZY_FETCH=1` refuses). `depth` (shallow clones) was supported by
  `clone-git` but not passed on by the cache wrapper, and neither was `fetch`; together,
  `--depth=1 --fetch="--depth 1 origin <full commit sha>" --checkout=<full commit sha>` gives a pinned
  checkout with no history at all, which still works after the branch moves on.
- **Removed the `test-core-via-ctuning` workflow** (outdated; `test-core` stays)
  and its README badge.
- **Fix: `tool/curl` no longer recurses when curl is missing.** curl is the common install dependency
  of `task/setup` on Linux and macOS, so installing curl itself (on a bare container, for example) set up
  curl again, over and over. `tool/curl` now sets `skip_common_install_uses: True`, as `tool/brew` does.
  In a non-interactive shell, `--install --quiet` installs a tool and such dependencies without asking.

## 0.32.2
- **README: how to update.** The engine and this repository are updated separately - `cx --version`
  (cMeta 0.32.2+) prints the command for the engine's install route (`uv tool upgrade cmeta`,
  `pip install -U cmeta`, ...), and `cx repo pull ctuninglabs@cmeta-aops` updates this repository
  (git pull + reindex); the engine's `docs/installation.md` "Updating cMeta" covers every route.
- **The agent launchers record how the artifacts of a session were made.** `task/run-claude`,
  `task/run-claude2`, `task/run-codex2` and `task/run-opencode2` set `CMETA_GENERATOR` for the agent
  process - `{"method": "agent", "agent": "<agent> <version>", "model": ..., "effort": ...}`, with
  the model and effort as passed after `--` (claude `--model` / `--effort`, else the thinking budget of
  `MAX_THINKING_TOKENS`; codex `-m` / `-c model_reasoning_effort=...`; opencode `--model` /
  `--variant`) - unless a task that runs the agent set it already, so an import task keeps its own
  record. `run-claude`, a pure pipeline so far, gains an `api_v1.py` whose `set_generator` step puts
  the record into the aggregated env, since its `cmd` step builds claude's environment from the host
  snapshot taken at bootstrap. With the engine's `artifact_defaults` / `CMETA_GENERATOR` support,
  every artifact the agent creates through `cx` carries it as `generator`, and every one it updates
  as `last_generator`. Documented in `docs/cmeta-aops/agent-tasks.md`.
- **Fix: `task/enable-long-paths-win` never enabled anything on a stock Windows.** Its
  `enable-long-paths-win.bat` began with a UTF-8 BOM, which `cmd.exe` reads as part of the first command
  under every code page except 65001 (UTF-8) - so on an ordinary English or French install the elevated
  window failed on `'<BOM>reg' is not recognized`, closed at once, and the registry value was never
  written. Every run then asked for administrator rights again and still reported long paths as off; it
  only ever worked on machines with the system-wide UTF-8 code page. The task now starts `reg.exe`
  elevated itself (no batch file, no user path to quote - an unquoted path with a space in the user name
  broke it too), waits for it, and checks the registry rather than `RtlAreLongPathsEnabled`, which
  Windows freezes when a process starts and so could never turn true within the same run. When the
  value is already set in the registry it no longer prompts at all. The warning says up front that an
  administrator prompt is coming and what to do if it does not work (Settings > System > Advanced >
  "Enable long paths" on Windows 11, or the `reg add` command), and the error repeats it with the reason
  (prompt declined, timed out, command failed). The `.bat` is kept, BOM-free, for running by hand.
- **Batch files no longer start with a UTF-8 BOM.** 336 `.bat` test scripts and helpers under `program/`,
  `task/` and `tool/` began with one, which `cmd.exe` reads as part of the first command under every code
  page except 65001 - on an ordinary English or French Windows their first line failed with
  `'<BOM>...' is not recognized`. Nothing else in them was non-ASCII, so they are plain ASCII now and run
  the same under any code page.
- **Tool detection lists each file once on merged-/usr Linux.** On Ubuntu, Debian, Fedora, Arch and
  others `/bin` and `/sbin` (and on some `/usr/sbin`) are symlinks into `/usr`, and all of them are on
  `PATH`, so every candidate was offered two to four times: a fresh Ubuntu listed `/bin/gcc`, `/bin/gcc-13`,
  `/usr/bin/gcc`, `/usr/bin/gcc-13`, ... and the first `cx tool setup git` asked to choose between `/bin/git`
  and `/usr/bin/git`, the same file. `find_path` now skips those three system aliases when the directory
  they point to is searched anyway. Nothing else is resolved: paths that may lead to different versions
  after an update - `/usr/local/cuda` and `/usr/local/cuda-13.0`, `gcc` and `gcc-13` - are still offered
  side by side, and `-q` still takes the default where there is no terminal to ask.
- **winget installs name `--source winget`.** Without it winget also queries the Microsoft Store source,
  and where that fails - `0x8a15005e: The server certificate did not match any of the expected values`,
  typically certificate pinning broken by an HTTPS-inspecting antivirus or proxy - it refuses to install
  a package it has already found in the winget source and asks for `--source`. Every `tool/*` winget
  command and the Windows `install_cmd*` of `task/host` (used by `install-sys-tool`) now pass it, as
  `tool/swiftlang` already did. Two lines that could never have worked are fixed on the way: the
  versioned `tool/tailscale` command said `--Tailscale.Tailscale` instead of `--id=Tailscale.Tailscale`,
  and `tool/microsoft.windows.adk` used `-id`, which winget rejects.
- **The ssh client is now a declared dependency, not a word on the caller's PATH.** `task/rclone-to-ssh`
  built its sftp command as a bare `ssh`, so which binary ran depended on the shell. A Windows host can
  carry several OpenSSH clients - the system one in `System32\OpenSSH`, the MSYS build inside Git, and
  copies bundled with other products - and they disagree on one thing that matters: the Windows build
  refuses a private key whose permissions let other users read it (`UNPROTECTED PRIVATE KEY FILE`, after
  which the key is ignored and authentication fails), while the MSYS build uses it anyway. The result was
  a sync that worked in one shell and failed in another with nothing but rclone's
  `couldn't initialise SFTP: ... unexpected EOF` to go on, which reads like a network or server fault.
  The task now resolves `tool/open-ssh` through `setup`, uses the absolute path, and prints it with its
  version, so the binary in use is visible in the trace instead of being a property of the environment.
  A resolved path containing a space keeps the bare name, because rclone parses `--sftp-ssh` as a
  space-separated list and the value is already quoted; the path is still reported.
- **`tool/open-ssh` detects properly and can install itself.** It gained `extra_paths` (the Windows
  system directory, winget packages, Homebrew), a second version regex, a per-distribution package name
  (`openssh-client` on Debian and Alpine, `openssh-clients` on Fedora, RHEL and SUSE, `openssh` on Arch),
  install commands for the three platforms and help text naming the Windows optional feature. Detection
  is what runs in practice, since the client ships with Windows 10 1809 and later, macOS and nearly
  every Linux.
- **MLPerf Inference v6.1 results and the MLPerf Inference Endpoints benchmark.** `task/get-mlperf-inference-results`
  defaults to the v6.1 round (published 2026-09-15; `--version=6.0` etc. still work) with a test script, plus the
  `clone-git` example scripts for inference v6.1 and training v6.0. Two new tasks read the Endpoints benchmark:
  `task/get-mlperf-endpoints-src` (mlcommons/endpoints, optional tag or branch) and `task/get-mlperf-endpoints-results`
  (`endpoints_results_v<round>`, default 0.7), both thin wrappers over `clone-git-to-cache` like their inference siblings.
- **README rewritten for first-time readers.** A plain opening (what the repository is, the one command,
  where to start: the course, the installer, the catalogues), a "Try it" block that pulls the repository
  from GitHub and runs the first tool, task and program, and one sentence on the Collective Knowledge
  lineage with a link to the framework's history page instead of the lineage paragraph. The status
  warnings, goals and core concepts are unchanged.
- **Fix: `tool/llvm` with a partial version (`--use.llvm.version=22`, `--version=22.1`).** The
  install hook pasted the partial version into the release URL (`llvmorg-22/LLVM-22-Linux-X64.tar.xz`,
  HTTP 404), which failed the *clang++ 22* workflow on every OS. It now resolves a partial version to
  the newest published release that starts with it (from the upstream tags, like `cmd_get_versions`),
  skipping release candidates and a release whose prebuilt asset is not there yet.

## 0.32.1
- **Six generic artifacts moved in from a downstream repository** (same UIDs, so any
  existing `alias,UID` reference keeps resolving): `tool/az` + `task/run-az` (Azure CLI:
  the official prebuilt download on Windows and macOS, the package manager on Linux,
  `az login` with the terminal attached), `tool/opencode` (OpenCode.AI, the third sibling
  of `claude` and `codex`) and the prompt runners `task/run-claude2`, `task/run-codex2`,
  `task/run-opencode2` (headless or interactive; transcript and token statistics recorded
  next to the prompt file). `run-claude2` adds cMeta repositories to the agent's context
  as `--add-dir`: by default its own repository plus the aliases in the new
  `agent_add_repos` key of the local cMeta config
  (`cx config set default --meta.agent_add_repos=alias,alias`, once per machine);
  `--add_repos=<alias,alias>` adds more, `none` adds nothing. These six carry no per-file
  copyright line - the repository licence (Apache-2.0) applies. New guide:
  [`docs/cmeta-aops/agent-tasks.md`](docs/cmeta-aops/agent-tasks.md) (usage, the flags
  the three runners share, which model and reasoning effort to pass to each agent).
- **`tool/obsidian` is a real recipe.** The previous file was a copy of `tool/openclaw`
  with the name changed; Obsidian is now detected on Windows, macOS and Linux with its
  version read from the installed files, and installed with `winget`, `brew --cask` or
  the pinned AppImage (tier 1 of the install ladder on Linux).
- **Every tool, task and program carries a one-line `desc` in its `_cmeta.*`**, shown by
  the cTuning.ai catalogues (tools, tasks, programs) and available to `cx <category> list`
  without scraping `_desc.*` keys.
- **Repository version 0.32.1** (`_cmr.yaml`), released together with cMeta 0.32.1, the
  engine release it was tested with.
- **Fix: `cx tool run <tool> --versions` no longer crashes.** `setup` may stop early
  without producing a command (it only prints the available versions); `tool run` now
  returns that result instead of reading a missing `cmd`.
- **Fix: `download-file` with several URLs (mirrors).** Filenames and MD5 sums are
  matched to URLs by position; with fewer names than URLs every later mirror derives
  its own filename and skips the checksum instead of failing on an out-of-range index.
- **`tool/rclone`: default version pinned in `_desc.yaml`** (`default_version`, bump it
  there), **two download mirrors** (downloads.rclone.org and GitHub releases, walked in
  order by `download-file`), and **package-manager fallbacks** (`apt`/`dnf`/... via
  `install_cmd_sudo`, `winget` on Windows) when the binary download fails.
- **New task `rclone-to-ssh`**: sync / copy / bisync / resync a local directory to a
  plain SSH host with rclone's connection-string remote - no `rclone.conf` entry, no
  stored credentials.
- **`tool/claude`: the Windows installer is run as `.\install.cmd`**, so the command
  works when the current directory is not on PATH.
- **`add-tool` skill rewritten around the install ladder** (prebuilt binary via
  `download-file` -> non-sudo package manager -> sudo package manager), with the
  mirror pattern and `download-file`'s two positional behaviours documented;
  `AGENTS.md` and `CLAUDE.md` carry the same rule plus the git workflow (sign-off,
  dated branches and PR titles).
- **Housekeeping:** `.gitignore` now covers AI-session provenance files
  (`claude-resume-*`, `claude-summary-*`, `codex-*`), the runtime state of a
  `CMETA_HOME` created inside the repo (`index/`, `repos/`, `repos.json`), partial
  downloads (`*.partial`) and the bytecode caches under `task/target` and `task/venv`;
  the docs no longer carry a machine-local path or a LAN address.
- **Documentation: the abstraction the content rests on is now named.** Goals
  gained "Abstractions you can operate" — every tool, library, program, model,
  dataset and workflow here is one artifact that is simple, reusable, live and
  interconnected by `alias,UID`, inspectable down to its inputs and provenance,
  so results can be taken back to first principles and the content is
  [FAIR](https://www.go-fair.org/fair-principles/) by construction rather than by
  extra effort. `llms.txt` carries the same line.
- **Documentation: the purpose is stated consistently with the cMeta framework.**
  The Goals section now names all six aims — the previously missing *scalable* and
  *sustainable* were added — and the agent goal makes the point explicitly: an
  agent is only as useful as the context it can assemble, and here that context is
  already recorded and machine-readable.

## 0.32.0

**First public release, under the Apache License 2.0.**

- **Relicensed the repository from proprietary ("All rights reserved") to
  Apache-2.0**, matching the [cMeta framework](https://github.com/cTuningLabs/cmeta):
  - New `LICENSE` (Apache-2.0) and rewritten `COPYRIGHT`.
  - Copyright headers updated across the artifact collection — `_cmeta.*` metadata
    fields, Python/C/C++/Objective-C++ source headers, workflow and script comments.
    Original copyright years and holders were preserved.
- **New `THIRD-PARTY.md`** — the authoritative record of vendored third-party
  components, replacing the previous three-line `LICENSES` file. It lists each
  component's path, copyright holder and licence, and flags those whose terms are
  **more restrictive than Apache-2.0**:
  - `program/cbench-automotive-susan/` — SUSAN, Crown Copyright (UK DERA):
    research use only, must not be sold; UK Patent 2272285.
  - `program/milepost-codelet-…-susan-codelet-10-1/` — SUSAN-derived MILEPOST codelet.
  - `program/lib-milepost/` — GPL (EU FP6 MILEPOST, released by CAPS Entreprise).
  - `program/lib-polybench/` — Ohio State University Software Distribution License.
  - `program/lib-xopenme/` — BSD and LGPL.
  - `task/test-mojo-life/` — Modular Inc., Apache-2.0 with LLVM Exceptions
    (compatible; listed for attribution).
- **Removed the vendored NVIDIA cuDNN RNN sample**, whose licence prohibits
  redistribution. The affected artifacts (`program/test-rnn-cudnn-blas-nvcc-cuda`,
  `task/test-nvcc-cudnn-rnn`) were moved to a separate private repository.
- **Added community health files** for the public release: `CONTRIBUTING.md` (with
  guidance on vendoring third-party code), the verbatim `DCO` (Developer
  Certificate of Origin 1.1), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1),
  `MAINTAINERS.md`, `CITATION.cff`, and a self-contained
  `.github/workflows/dco.yml` that checks every pull-request commit is signed off.
- **Hardened `.gitignore`** against cMeta run artifacts (`tmp*/`, `tmp-cmeta-*`,
  `cmeta-task-saved-*`, `_repro_ctx_*`) and author scratch/backup siblings. These
  capture the full environment of the machine that produced them and must not be
  published; a few that had been committed were removed from tracking.
- Moved the `skill` category into this repository from the cMeta engine.
- Documentation and authoring skills (`AGENTS.md`, `CLAUDE.md`,
  `docs/cmeta-aops/`, `.claude/skills/`) updated for the Apache-2.0 licence, the
  third-party carve-outs, and the narrow-reindex guidance.

## Earlier

Development prior to 0.32.0 was not public and is not itemised here. It covered
the `task` workflow engine (API v2), the `tool` and `program` delegators, the
category cache, the compute abstraction (CPU / CUDA / Android / Metal / …), and
the growth of the artifact collection to roughly 115 tasks, 100 tools and 30
programs, plus models and datasets.
