# lib-opencl

What a C or C++ program needs to build against OpenCL for the `opencl` target (task `target--opencl` finds the
devices; `tool/opencl` the ICD loader that the drivers register with) and for `android-gpu`: the Khronos OpenCL
headers and the library to link.

```bash
cx tool setup lib-opencl
```

| Target | Headers | Library to link | What the program loads |
|---|---|---|---|
| Windows | `install/include/CL/*.h` (KhronosGroup/OpenCL-Headers) | `install/lib/OpenCL.lib`: the import library of `OpenCL.dll`, made from the export list of the Khronos ICD loader (`loader/windows/OpenCL.def`) by the archiver of the program's C compiler (MSVC's `lib.exe`, clang's `llvm-lib`) - the loader is not built | the `OpenCL.dll` of the GPU drivers |
| Linux | the same | the system's ICD loader (`libOpenCL.so`, else `libOpenCL.so.1`; `cx tool setup opencl --install` installs it), by its path | the drivers' ICDs (`/etc/OpenCL/vendors`) |
| macOS | the same (programs include `<OpenCL/opencl.h>` of the SDK) | the SDK's OpenCL framework (`OpenCL.tbd`; `xcrun --show-sdk-path`) | Apple's OpenCL |
| Android (`android-gpu` ...) | the same | a stub `libOpenCL.so` with every function of the same export list, built once per target triple by the program's NDK compiler (`install/android/<triple>/`) | the device's own `libOpenCL.so` (the same soname) |
| iOS | - | refused: iOS has no OpenCL | - |

The releases are pinned (`default_version` in `_desc.yaml`, the SHA-256 of both archives in `api_v1.py`); another
one: `cx tool setup lib-opencl --version=<YYYY.MM.DD> --with.sha256=<headers> --with.sha256_loader=<ICD loader>`.
Both projects are Apache-2.0; their licences are copied next to the headers (`install/LICENSE.*`).

A program sets it up after its compiler, gated on its targets - `setup-compile` then adds the include folder and
the library:

```yaml
updates:
  compile:
    uses:
      - match:
          internal_func: customize2
        append:
          - task: setup,a2f9b61079ce4333
            if: '"opencl" in {{global.target.compute|$[]}} or "android-gpu" in {{global.target.compute|$[]}}'
            name: lib-opencl,c209094321c94530
```

Define `CL_TARGET_OPENCL_VERSION` (`120` for OpenCL 1.2 code) to choose the API the headers declare; without it
they default to 3.0 and say so.
