# lib-jitterentropy — the Jitter RNG as a static library

`cx tool setup lib-jitterentropy` builds the static library of the
[Jitter RNG](https://github.com/smuellerDD/jitterentropy-library) (jitterentropy-library),
`libjitterentropy.a`, from its pinned source release with the C compiler of cMeta, into the tool's
cache entry: no root, no system package, the same version on every machine.

```bash
cx tool setup lib-jitterentropy
cx tool setup lib-jitterentropy --version=<version> --with.sha256=<SHA-256 of the release archive>
```

The Jitter RNG gathers entropy from the timing jitter of the CPU. OpenSSL 3.5 and newer can seed
its random generator from it, and the static `libcrypto.a` of some distributions (Ubuntu 26.04)
refers to it, so a static link of OpenSSL there needs `libjitterentropy.a`.
[`tool/lib-openssl`](../lib-openssl/README.md) sets this tool up by itself for a static link on
Linux when the system has no such archive. A program that uses it directly gets
`-I<include>`, `-L<lib>` and `-ljitterentropy` from `setup-compile`, like with the other `lib-*`
tools; it also needs pthreads (`-lpthread`).

## How it is built

1. The project publishes no release files, so the release is GitHub's archive of its tag
   `v<version>`, checked against the SHA-256 pinned in `api_v1.py`.
2. Its sources (`src/*.c`) are compiled with the C compiler of cMeta's compiler task as the
   project's own Makefile builds them:
   - `-O0`: without optimization, which `jitterentropy-base.c` requires (it stops on
     `__OPTIMIZE__`), since the noise source depends on the code that the CPU runs;
   - `-fwrapv -std=c11 -fPIC`;
   - `JENT_CONF_ENABLE_INTERNAL_TIMER`: the internal timer thread for CPUs whose high-resolution
     timer is too coarse, which is why the library needs pthreads.
3. The objects are archived with the compiler's archiver; the cache entry keeps only the result:

```
install/lib/libjitterentropy.a
install/include/jitterentropy.h, jitterentropy-base-user.h
install/_source.json     the source URL, its SHA-256, the compiler and the flags
```

The build is shared with [`lib-zlib`](../lib-zlib/README.md) and
[`lib-zstd`](../lib-zstd/README.md): `category/tool/api/common_static_lib.py`.

## Systems

Linux and macOS, with gcc or clang. On Windows the tool stops with a message: the static
libraries of OpenSSL for Windows do not need it.

## Versions

The pinned versions and their digests are `SPEC['sha256']` in `api_v1.py`. The Jitter RNG is
dual licensed under BSD (3-clause) and GPLv2.
