# lib-openssl — OpenSSL's headers and libraries

`cx tool setup lib-openssl` finds OpenSSL's development headers and libraries for programs that
link OpenSSL (`test-nmm-c-cpu`, `test-nmm-cpp-cpu`, ...), and installs them with the system's
package manager when they are missing:

| System | Where OpenSSL comes from |
|---|---|
| Linux | the distribution's `libssl-dev` (`openssl-devel` on Amazon Linux, Rocky Linux and Azure Linux), or Homebrew's |
| macOS | Homebrew's `openssl` |
| Windows | the `OpenSSL` package of winget (`C:\Program Files\OpenSSL-Win64`) |

The version is read from `opensslv.h`. The result gives `setup-compile` the include folder, the
lib folder and the libraries: `ssl` and `crypto`, and for a static link on Windows `ssl_static`,
`crypto_static` and the Windows libraries they need.

## Static links on Linux

A distribution's static `libssl.a` and `libcrypto.a` may refer to other libraries, depending on
how the distribution built OpenSSL: Ubuntu 24.04's refer to none, Ubuntu 26.04's to zlib, zstd
and the Jitter RNG. For a static link on Linux (`with.static`), `lib-openssl`:

1. reads the symbols that `libssl.a` and `libcrypto.a` leave undefined (`nm -u`, binutils) and
   links only the libraries they need, in the order of a static link:
   `-lssl -lcrypto [-ljitterentropy -lpthread] [-lz] [-lzstd] -lm`;
2. uses the system's static archive of each needed library when the compiler's linker finds one
   (`<compiler> -print-file-name=lib<name>.a`, and OpenSSL's own lib folder);
3. builds a needed library that the system has no static archive of with its tool, from a pinned
   source release: [`lib-zlib`](../lib-zlib/README.md), [`lib-zstd`](../lib-zstd/README.md),
   [`lib-jitterentropy`](../lib-jitterentropy/README.md). `setup-compile` then adds its lib
   folder, before the system's.

`--with.static_deps=cmeta` uses the tools' libraries even when the system has its own, for the
same versions on every machine. Without `nm`, or for an OpenSSL without static archives, the
libraries stay `ssl crypto z m zstd`, as before. Dynamic links, and static links on macOS and
Windows, are not affected.

A program passes `with.static` for its static builds on Linux (see the two `lib-openssl` entries
in `program/test-nmm-c-cpu/_desc.yaml`):

```bash
cx program run test-nmm-c-cpu --compile.static
cx program run test-nmm-c-cpu --compile.static --use.lib-openssl.with.static_deps=cmeta
```

A library the tools build is installed like any other tool: interactively after a confirmation,
with `-q` at once.
