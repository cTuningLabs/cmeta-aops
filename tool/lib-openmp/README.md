# lib-openmp — LLVM's OpenMP runtime (libomp) for clang

`cx tool setup lib-openmp` finds the OpenMP runtime that clang links with `-fopenmp`: the `libomp`
of the LLVM release that cMeta set up (`tool/llvm`), or Homebrew's `libomp` on macOS, where it is
installed with Homebrew when missing (Linux: the distribution's `libomp-dev`). gcc needs none of
this: its runtime, libgomp, comes with the compiler. The programs that use OpenMP ask for it only
when clang is the compiler (`"{{global.llvm.path|None}}" != "None"` in their `_desc.yaml`), on every
OS.

## Dynamic and static builds

| Build | Linux | macOS | Windows |
|---|---|---|---|
| dynamic | `libomp.so` of the LLVM release or the distribution's `libomp-dev` (its folder is put on the run-time library path) | Homebrew's `libomp.dylib` | clang's `libomp.dll` (`C:\Program Files\LLVM\bin`, put on the run-time path) |
| static (`with.static`) | `libomp.a` built from the pinned OpenMP source release, into the tool's cache entry | Homebrew's `libomp.a`, copied into the tool's cache entry | no static runtime exists: the program keeps `libomp.dll`, as for a dynamic build (`setup-compile` says so) |

The LLVM releases ship no `libomp.a` for Linux, so for a static build the tool builds one with
cMeta's cmake and ninja and the clang of the build, from `openmp-21.1.8.src.tar.xz` and
`cmake-21.1.8.src.tar.xz` of LLVM's releases (SHA-256 checked; the 22.x releases publish no
standalone OpenMP tarball, and the runtime's ABI is stable across versions). The archive lands in
`static/libomp.a` of the same cache entry, so the identity of the entry does not change: one entry
serves dynamic and static builds, as the entries of the libraries cMeta builds itself do. On macOS,
where Apple's linker takes a dylib over an archive in the same folder, Homebrew's `libomp.a` is
copied into that `static/` folder too.

On Windows, LLVM's build of the runtime refuses a static library ("Static libraries requested but
not available on Windows") and MSVC's OpenMP runtime, vcomp, is a DLL as well. A static build on
Windows therefore means the static C run time and static libraries with the OpenMP runtime as a
DLL; `setup-compile` prints a warning for such a build.

## gcc's runtime, libgomp, in a static build

gcc needs no `lib-openmp`: `-fopenmp` compiles with its own runtime, libgomp, and appends `-lgomp`
to the link. A fully static build (`-static`) resolves that to `libgomp.a`; a link without `-static`
- nvcc's host link of a static CUDA program (`-cudart=static`) - would take `libgomp.so`. So for a
static build with OpenMP, `task/setup-compile` asks the compiler that provides the runtime (gcc, or
nvcc's host compiler) for its archive with `-print-file-name=libgomp.a` (`openmp_static_archive` in
`tool/gcc` and `tool/gcc-cpp`) and hands it to the linker by its path, followed by `-lpthread -ldl`
(what the archive needs on older glibc) and `--as-needed` (so the `-lgomp` that gcc appends after
the inputs adds no shared library). A compiler without the archive stops the static build with what
provides it on this system; the build never falls back to the shared runtime.

Where `libgomp.a` comes from (checked in containers, 2026-10): with the compiler itself on Debian and
Ubuntu (`libgcc-<N>-dev`, installed with `gcc-<N>`), Fedora and RHEL-likes (`gcc`), openSUSE (`gcc<N>`)
and Alpine (`gcc`); Arch Linux ships none (only its cross compilers do) - use clang there, whose
`libomp.a` this tool builds, or a dynamic build.

```bash
cx program run test-nmm-c-cpu --compile.static          # with clang: libomp linked statically (Linux, macOS)
cx tool setup lib-openmp --with.static                    # the static archive on its own
```
