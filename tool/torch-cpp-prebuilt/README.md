# torch-cpp-prebuilt — PyTorch's prebuilt LibTorch

`cx tool setup torch-cpp-prebuilt` gives LibTorch, the PyTorch C++ distribution, from PyTorch's
prebuilt archives at <https://download.pytorch.org/libtorch/> instead of a local build: the archive
of a release for this system, CPU and build is downloaded into the cMeta cache, checked against the
SHA-256 pinned in `api_v1.py` and unpacked. [`tool/torch-cpp`](../torch-cpp/) uses it with
`--with.build=prebuilt`, and so do programs such as
[`test-nmm-torch-cpp`](../../program/test-nmm-torch-cpp/README.md)
(`--setup_torch_cpp.build=prebuilt`).

```bash
cx tool setup torch-cpp-prebuilt                         # the CPU build (macOS: CPU and MPS)
cx tool setup torch-cpp-prebuilt --with.compute=cuda     # the CUDA build for this machine's GPUs
cx tool setup torch-cpp-prebuilt --with.variant=cu126    # a given build
cx tool setup torch-cpp-prebuilt --version=2.7.1         # a release with pinned archives

cx tool setup torch-cpp --with.build=prebuilt            # the same through tool/torch-cpp
```

## Builds

| System | Builds (2.7.1) |
|---|---|
| Linux x86_64 | `cpu`, `cu118`, `cu126`, `cu128` |
| Windows x64 | `cpu`, `cu118`, `cu126`, `cu128` |
| Windows ARM64 | `cpu` |
| macOS arm64 | `cpu` (with MPS, for Apple GPUs) |

Other systems, versions and backends (ROCm, XPU) have no pinned archive: the setup says so, and
`tool/torch-cpp` builds LibTorch from source for them.

**The CUDA build** for `--with.compute=cuda` is the newest one that has code for every GPU of the
machine (their compute capability, from `tool/cuda`) and whose CUDA version the NVIDIA driver
supports; with an older driver of the same CUDA major version, a build is still chosen (CUDA's minor
version compatibility). The architectures each build has code for are listed in `api_v1.py`
(`CUDA_BUILDS`), read with `cuobjdump --list-elf` from its CUDA library; code for compute capability
X.y also runs on X.z for z >= y. For example, cu128 is the only 2.7.1 build with code for Blackwell
GPUs (compute capability 10.0 and 12.0). The archives bring the CUDA run-time libraries they need;
only the driver must be installed.

Each build has a cache entry of its own (`with.variant` is part of its cache identity).

## Through tool/torch-cpp

With `--with.build=prebuilt`, `tool/torch-cpp` sets up this tool and points to its library. That
setup of `tool/torch-cpp` is not cached: its cache entries are those of source builds, and an entry
marked "prebuilt" would also match the requests without `--with.build` (a cMeta cache entry matches
every request whose parameters it contains). The archive itself is cached here.

## Adding a release

1. Find the archives of the release at <https://download.pytorch.org/libtorch/cpu/> (and `cu118/`,
   `cu126/`, ...).
2. Add their file names and SHA-256 digests to `ARCHIVES` in `api_v1.py`: PyTorch publishes no
   checksums, so take them from the downloaded archives.
3. Add the CUDA builds to `CUDA_BUILDS` with their architectures (`cuobjdump --list-elf` of
   `lib/libtorch_cuda.so` and `lib/torch_cuda.dll`; the `a` variants, such as `sm_90a`, run only on
   their own architecture and are left out).
4. Optionally make it the `default_version` in `_desc.yaml`.
