# lib-zlib — zlib as a static library

`cx tool setup lib-zlib` builds the static library of [zlib](https://zlib.net), `libz.a`, from
zlib's pinned source release with the C compiler of cMeta, into the tool's cache entry: no root,
no system package, the same version on every machine.

```bash
cx tool setup lib-zlib                       # the default version
cx tool setup lib-zlib --version=1.3.1       # another pinned version
cx tool setup lib-zlib --version=<version> --with.sha256=<SHA-256 of zlib-<version>.tar.gz>
```

A program uses it like the other `lib-*` tools: `setup-compile` adds `-I<include>`, `-L<lib>`
and `-lz`. [`tool/lib-openssl`](../lib-openssl/README.md) sets it up by itself for a static link
on Linux when the distribution's static OpenSSL needs zlib and the system has no `libz.a`.

## How it is built

1. The release `zlib-<version>.tar.gz` is downloaded from zlib's GitHub releases (zlib.net's
   archive as a mirror) and checked against the SHA-256 pinned in `api_v1.py`, the digest that
   zlib.net publishes. A version the tool does not pin needs `--with.sha256`.
2. Its 15 library sources are compiled with the C compiler of cMeta's compiler task (the one of
   the program that asks for the library, its C counterpart for a C++ program, otherwise the one
   the task selects), with `-O2 -fPIC` and what zlib's configure sets on Linux and macOS
   (`HAVE_UNISTD_H`, `HAVE_STDARG_H`), and archived with that compiler's archiver (`ar`,
   `llvm-ar`).
3. The cache entry keeps only the result:

```
install/lib/libz.a
install/include/zlib.h, zconf.h
install/_source.json     the source URL, its SHA-256, the compiler and the flags
```

The build is shared with [`lib-zstd`](../lib-zstd/README.md) and
[`lib-jitterentropy`](../lib-jitterentropy/README.md):
`category/tool/api/common_static_lib.py`.

## Systems

Linux and macOS, with gcc or clang. On Windows the tool stops with a message: the static
libraries of OpenSSL for Windows do not need zlib.

## Versions

The pinned versions and their digests are `SPEC['sha256']` in `api_v1.py`; `default_version` is
the one built without `--version`. zlib is under the [zlib license](https://zlib.net/zlib_license.html).
