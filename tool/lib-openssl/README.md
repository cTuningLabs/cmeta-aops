# lib-openssl — OpenSSL's headers and libraries

`cx tool setup lib-openssl` finds OpenSSL's development headers and libraries for programs that
link OpenSSL (`test-nmm-c-cpu`, `test-nmm-cpp-cpu`, `test-nmm-nvcc-cuda`, ...), and installs them
with the system's package manager when they are missing:

| System | Where OpenSSL comes from |
|---|---|
| Linux | the distribution's `libssl-dev` (`openssl-devel` on Amazon Linux, Rocky Linux and Azure Linux), or Homebrew's |
| macOS | Homebrew's `openssl` |
| Windows | the `OpenSSL` developer package of winget (`C:\Program Files\OpenSSL-Win64`, with the libraries) |

The version is read from `opensslv.h`. The result gives `setup-compile` the include folder, the
lib folder and the libraries: `ssl` and `crypto` for a dynamic build, and for a static build the
static libraries described below.

## Static builds

A static build (`cx program run <program> --compile.static`) links OpenSSL's static libraries and
never falls back to the shared ones: a build that says "static" is static, or it stops with the
reason. On Linux and macOS the programs pass `with.static` to `lib-openssl` (see the two
`lib-openssl` entries in `program/test-nmm-c-cpu/_desc.yaml`); on Windows the static libraries
are chosen by name.

**Linux and macOS.** `libssl.a` and `libcrypto.a` go to the linker by their paths rather than as
`-lssl -lcrypto`: a link without `-static` — nvcc's host link of a CUDA program — would otherwise
take `libcrypto.so` of the same folder. A distribution's archives may refer to other libraries,
depending on how the distribution built OpenSSL: Ubuntu 24.04's and Debian's to none, Ubuntu
26.04's to zlib, zstd and the Jitter RNG, Homebrew's to zlib. `lib-openssl`:

1. reads the symbols that `libssl.a` and `libcrypto.a` leave undefined (`nm -u`: binutils, Xcode's
   command line tools, or `llvm-nm` next to the compiler) and links only the libraries they need,
   each by the path of its static archive, in the order of a static link:
   `libssl.a libcrypto.a [libjitterentropy.a] [libz.a] [libzstd.a] -lpthread -ldl -lm`
   (`-lm` alone on macOS: libSystem has the rest);
2. uses the system's static archive of each needed library when the compiler's linker finds one
   (`<compiler> -print-file-name=lib<name>.a`, and OpenSSL's own lib folder);
3. builds a needed library that the system has no static archive of with its tool, from a pinned
   source release: [`lib-zlib`](../lib-zlib/README.md), [`lib-zstd`](../lib-zstd/README.md),
   [`lib-jitterentropy`](../lib-jitterentropy/README.md) — its archive in the tool's cache entry,
   by its path as well.

`--with.static_deps=cmeta` uses the tools' libraries even when the system has its own, for the
same versions on every machine. Without `nm` the needs cannot be read: the archives are linked
with the system's static archives of the three, if any (a WARNING says so).

On macOS a static build means static third-party libraries with the dynamic system library
(`libSystem`): Apple's linker has no `-static`, and the system has no static C library. `otool -L`
of a static build lists `libSystem` only.

**Without the archives the build stops.** When the OpenSSL found has no `libssl.a` and
`libcrypto.a` (Fedora's `openssl-devel`, Arch Linux, macOS without Homebrew's OpenSSL), a request
with `with.static` fails at the setup, and a static build of a program that did not pass
`with.static` stops in `setup-compile` — both with what gives the archives on this system:

| System | The static OpenSSL |
|---|---|
| Debian, Ubuntu | `libssl-dev` (the development package ships the archives) |
| Alpine | `openssl-libs-static` |
| Fedora, RHEL-likes (Rocky, Alma, CentOS Stream), Arch Linux, openSUSE | not packaged (no package provides `libcrypto.a`, not even in CRB): build OpenSSL from source (`./Configure no-shared --prefix=<prefix>`) and register it with `cx tool setup lib-openssl --tool_path=<prefix>/include/openssl/opensslv.h` |
| macOS | Homebrew's `openssl@3` |
| Windows | the OpenSSL developer package (`winget install OpenSSL -e --source winget`, id `ShiningLight.OpenSSL.Dev`): `lib\VC\x64\MT\libssl_static.lib` and `libcrypto_static.lib`; the "Light" packages ship no libraries |

The check runs with every setup, also when the cache entry is reused, so a package installed
later is seen at once (`cx tool setup lib-openssl --update` refreshes the detection itself).

**Windows.** A static build (`/MT` with MSVC) links `libssl_static.lib` and `libcrypto_static.lib`
of the `MT` folder (static C run time) and the Windows libraries OpenSSL needs (`ws2_32`,
`crypt32`, `advapi32`, `user32`); a debug build takes `MTd`. The program then imports system DLLs
only.

```bash
cx program run test-nmm-c-cpu --compile.static
cx program run test-nmm-c-cpu --compile.static --use.lib-openssl.with.static_deps=cmeta
cx program run test-nmm-nvcc-cuda --compile.static   # static CUDA runtime and third-party libraries, the C library shared
```

A library the tools build is installed like any other tool: interactively after a confirmation,
with `-q` at once.
