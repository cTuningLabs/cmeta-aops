# torch-cpp — LibTorch, the PyTorch C++ distribution

`cx tool setup torch-cpp` gives C++ programs LibTorch (`libtorch.so`, `libtorch.dylib`, `torch.dll`
with its headers and CMake config) in one of two ways, each with its own default version:

| | Source build (the default) | Prebuilt (`--with.build=prebuilt`) |
|---|---|---|
| How | PyTorch is cloned, configured, built and installed by [`program/build-torch-cpp`](../../program/build-torch-cpp/) (CMake, Ninja, the C and C++ compilers of cMeta) | PyTorch's official archive, downloaded and checked by [`tool/torch-cpp-prebuilt`](../torch-cpp-prebuilt/README.md) |
| Default version | the git tag `default_checkout` of `_desc.yaml` (`v2.14.1`, the tested one) | `default_version` of `_desc.yaml` (`2.7.1`, the release whose archives are pinned) |
| Another version | `--version=<x.y.z>` checks out the tag `v<x.y.z>` | `--version=<x.y.z>` needs a release with pinned archives |
| Backends | those of the target (`--with.compute=cpu,cuda,...`): CUDA, ROCm, MPS and XPU are off unless asked for (`--with.strict_compute=False` lets PyTorch enable what it finds) | the CPU build, or a CUDA build chosen for the GPUs and the driver (`--with.variant=cu118|cu126|cu128`); macOS: CPU with MPS |
| Static | `--with.static` | no (the archives have shared libraries only) |
| Time | hours | a download |
| Cache entry | `task--setup--torch-cpp--<uid>`: the build tree in `build/`, the installed LibTorch in `build/install/` (`lib`, `include`, `share/cmake/Torch`) | `task--setup--torch-cpp-prebuilt--<uid>`, one per build; the setup of `torch-cpp` with it is not cached |

```bash
cx tool setup torch-cpp                                   # a source build of v2.14.1 for the CPU
cx tool setup torch-cpp --version=2.12.0                  # a source build of the tag v2.12.0
cx tool setup torch-cpp --with.compute=cuda               # a source build with CUDA
cx tool setup torch-cpp --with.build=prebuilt             # PyTorch's archive, 2.7.1
cx tool setup torch-cpp --with.build=prebuilt --with.compute=cuda --with.variant=cu126
cx tool setup torch-cpp --versions                        # the release tags of PyTorch
```

The result gives later tasks `global.torch-cpp.path` (the main library), `features.paths.home`,
`lib` and `include`, and `features.build` (`source` or `prebuilt`); the `lib` folder is on the run-time
library path of the programs that use it ([`program/test-nmm-torch-cpp`](../../program/test-nmm-torch-cpp/README.md)).

## Notes

- **The two defaults differ on purpose.** The prebuilt archives are pinned per release and checked
  against their SHA-256, so their default stays at a release with archives for every system; the
  source build follows PyTorch's tags and its default is the tag that was built and tested last.
  Changing either default changes nothing for the entries already in the cache.
- **Cache identity.** A source build is identified by the target's backends, `static`,
  `strict_compute` and `ver`, plus the version it reports from its installed headers; the checkout is
  not part of it (`--version` is).
- **A detected LibTorch is never used** (`skip_detect`): a `libtorch` in `PATH` could be any build.
- **Install tree.** The build installs apart from its build tree (`build/install/`): installing into
  the build tree itself made CMake delete `protoc` while installing it onto itself.
