# lib-zstd — Zstandard as a static library

`cx tool setup lib-zstd` builds the static library of [Zstandard](https://facebook.github.io/zstd/),
`libzstd.a`, from its pinned source release with the C compiler of cMeta, into the tool's cache
entry: no root, no system package, the same version on every machine.

```bash
cx tool setup lib-zstd
cx tool setup lib-zstd --version=<version> --with.sha256=<SHA-256 of zstd-<version>.tar.gz>
```

A program uses it like the other `lib-*` tools: `setup-compile` adds `-I<include>`, `-L<lib>`
and `-lzstd`. [`tool/lib-openssl`](../lib-openssl/README.md) sets it up by itself for a static
link on Linux when the distribution's static OpenSSL needs zstd and the system has no
`libzstd.a`.

## How it is built

1. The release `zstd-<version>.tar.gz` is downloaded from Zstandard's GitHub releases and checked
   against the SHA-256 pinned in `api_v1.py`, the digest of the release's `.sha256` file.
2. The library's compression, decompression and dictionary builder sources (`lib/common`,
   `lib/compress`, `lib/decompress`, `lib/dictBuilder`) are compiled with the C compiler of cMeta's
   compiler task with `-O3 -fPIC`, as zstd's own `lib/Makefile` builds `libzstd.a`:
   - `XXH_NAMESPACE=ZSTD_`: its xxhash functions carry the `ZSTD_` prefix, so they do not clash
     with another xxhash in the same program;
   - single-threaded (no `ZSTD_MULTITHREAD`), so the library needs no pthreads;
   - `ZSTD_LEGACY_SUPPORT=0`: no decoder of the pre-1.0 formats;
   - `ZSTD_DISABLE_ASM`: the C Huffman decoder instead of the x86-64 assembly one, so every system
     builds the same sources.
3. The objects are archived with the compiler's archiver; the cache entry keeps only the result:

```
install/lib/libzstd.a
install/include/zstd.h, zstd_errors.h, zdict.h
install/_source.json     the source URL, its SHA-256, the compiler and the flags
```

The build is shared with [`lib-zlib`](../lib-zlib/README.md) and
[`lib-jitterentropy`](../lib-jitterentropy/README.md):
`category/tool/api/common_static_lib.py`.

## Systems

Linux and macOS, with gcc or clang. On Windows the tool stops with a message: the static
libraries of OpenSSL for Windows do not need zstd.

## Versions

The pinned versions and their digests are `SPEC['sha256']` in `api_v1.py`. Zstandard is dual
licensed under BSD and GPLv2.
