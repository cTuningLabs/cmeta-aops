# Changelog

All notable changes to cMeta AOps are documented here, newest first.

## 0.41.0
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
- **Test sessions: a sandbox and a kept log for every test** (`task/test-session`, see its
  [README](task/test-session/README.md)). `cx task run test-session --start --type=<type>` gives
  `<CMETA_HOME>/tmp/cmeta-tests-<YYYYMMDD>/<HHMM>.<type>/` to work in, and a log in
  `<CMETA_HOME>/log/cmeta-tests-<YYYYMMDD>/` (Markdown and JSON) that stays when the sandbox goes. The
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
  made before keeps its venv until `--recompile`.
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
- **Tested on 2026-10-01 and 2026-10-02** (generation tokens per second, 64 tokens; on the P14s, T470p
  and Mac the mean of three warm runs):

  | Machine | llama.cpp release | llama.cpp from source (build time) | vLLM | Ollama | PyTorch from source |
  |---|---|---|---|---|---|
  | Windows 11, RTX PRO 1000 Blackwell | CPU 103, CUDA 330, Vulkan 264 | CUDA 315 (320 s), Vulkan 269 (130 s) | WSL2 only | CUDA 274, CPU 117 | |
  | WSL2 Ubuntu 24.04 (same laptop) | CUDA 318 | | CUDA wheel 66.5 (Python 3.14) | | |
  | ThinkPad P14s, RTX A500 (sm_86) | CPU 79, CUDA 157, Vulkan 107 | CPU 77 (241 s), CUDA 157 (780 s), Vulkan 108 (298 s) | CUDA wheel 78.8, from source 77.8 (6,749 s) | CUDA 160.6 | CUDA works (2 h 53 min) |
  | ThinkPad T470p, GeForce 940MX | CPU 40.8, Vulkan 35.9 | CPU 40.8 (316 s), Vulkan 36.2 (474 s) | CPU wheel 13.0 (1 GiB KV cache) | CPU 41.2, Vulkan 37.3 | |
  | Mac mini M4, macOS 27 | Metal 184, CPU 158 | Metal 185 (87 s), CPU 158 (60 s), Vulkan/MoltenVK 136 (81 s) | CPU wheel 54.8, from source 54.7 | Metal 190.5, CPU 159.8 | MPS works (1,000 s) |
  | Docker `python:3.12` (x86_64) | | | CPU wheel 17.9 | | |

  - **Release against source builds:** alternating on an idle machine, they agree within 1% (llama.cpp
    on the Mac, the T470p and the P14s; vLLM on the Mac and the P14s). The gaps seen before (P14s
    CPU: 50 against 81) came from runs made right after a compile.
  - **Several targets on the P14s:**
    - `--compute=cpu,cuda --ngl=12` (12 of 25 layers on the RTX A500): llama.cpp 111 tokens/s, against
      79 on the CPU and 177 on the GPU; Ollama 118, against 161 on the GPU.
    - `build-llama-cpp --compute=cuda,vulkan --target_tmp=auto` (866 s): one binary with both
      backends. `--devices=CUDA0` gives 175.6, `--devices=Vulkan0` 140.6, and both with
      `--tensor_split=1,1` 148.6, on the same RTX A500.
  - **On the T470p:** `--compute=cpu,vulkan --ngl=12`: llama.cpp 39.4, Ollama 40.9 (the 940MX is
    slower than the CPU for this model).

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
