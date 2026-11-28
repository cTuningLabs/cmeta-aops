# tool `lib-sodium-android`

[libsodium](https://libsodium.org) for an Android device: upstream's pinned source release, compiled with
the NDK's clang for the ABI of the attached device, in the tool's own cache entry - the static and the
shared library side by side. The same on a Windows, Linux or macOS host; nothing goes into the system or
into the NDK. The host's own libsodium is another tool: [`lib-sodium`](../lib-sodium/README.md).

```
cx tool setup lib-sodium-android                      # for the device attached (adb); upstream's tests run on the device
cx tool setup lib-sodium-android --with.check-        # without the tests
cx tool setup lib-sodium-android --with.abi=arm64-v8a # no device attached: this ABI, no tests
cx tool setup lib-sodium-android --version=1.0.21     # another release that _desc.yaml pins
```

## What it installs

```
<cache entry>/install/include/sodium.h, sodium/*.h
<cache entry>/install/lib/libsodium.a, libsodium.so
<cache entry>/install/_source.json     the source and its SHA-256, the ABI, the clang target, the compiler,
                                       the tests' verdict
```

1. The release `libsodium-<version>.tar.gz` is fetched (GitHub's release, libsodium.org as a mirror) and
   checked against the SHA-256 pinned in `_desc.yaml` (`release: sha256:`). A version that is not pinned
   needs `--with.sha256=<SHA-256 of the file>`.
2. Its library sources are compiled directly with the NDK's clang and archived with the NDK's `llvm-ar`
   (upstream's `configure` needs a POSIX shell, which a Windows host does not have). What that configure
   decides for Android - the sources, the flags, the definitions - is data in `_desc.yaml` (`build:`).
3. The library is built for the lowest Android API level of that block (21, as upstream's own Android
   builds), so one entry serves every device of the ABI and every program, whatever API level the
   program is built for. The shared library is linked with a 16 KB page size where the NDK's default is
   that.
4. Upstream's test programs are compiled against the shared library, pushed to the attached device with
   adb into a folder of their own (`/data/local/tmp/cmeta-lib-sodium-check`), run there, and the folder is
   removed. A test that fails stops the setup. `--with.check-` skips them; with `--with.abi` and no device
   they are not run (`--with.check` then asks for the device).

ABIs: `arm64-v8a` and `armeabi-v7a`. Another ABI is refused with the list.

## What a program gets

A program for `--compute=android-cpu` sets the tool up after the target; task `setup-compile` links every
global key that starts with `lib-`:

```yaml
- task: setup,a2f9b61079ce4333
  if: '"android-cpu" in {{global.target.compute|$[]}}'
  name: lib-sodium-android,64d4a023c2e74206
  with:
    static: '{{local.params.compile.static|$None}}'
```

| Build | Linked | On the device |
|---|---|---|
| dynamic | the shared library (`-lsodium`) | `features.paths.found_dynamic_libs` names `libsodium.so`: the run pushes it beside the program |
| static (`with.static`) | the static library by its path | nothing |

## A new version of libsodium

`_desc.yaml` holds everything that changes with a release: `release:` (the SHA-256 of the source, which
GitHub publishes for the files of a release) and `build:`. To check the `build:` block against a new
release, run upstream's own build once on a Linux machine with the NDK and compare:

```
CC="<ndk>/toolchains/llvm/prebuilt/linux-x86_64/bin/clang --target=aarch64-linux-android21" \
  ./configure --host=aarch64-linux-android --disable-dependency-tracking --with-pic --disable-soname-versions
make V=1
```

- `DEFS`, `CFLAGS` and `LDFLAGS` of `src/libsodium/Makefile` are `build: defines` (with `defines_abi` for
  what one ABI adds), `cflags` and `ldflags_shared`;
- the sources that `make V=1` compiles are `build: sources` without `build: skip`;
- the library this tool builds and the one `make` builds export the same symbols
  (`llvm-nm --defined-only -g libsodium.a`, `llvm-nm -D --defined-only libsodium.so`).

Configure defines more at later API levels (getrandom and getentropy from 28, memset_explicit later);
libsodium does without them, and the library built for the lowest level runs on every later one.

## Systems

Hosts: Windows, Linux, macOS (the NDK cMeta sets up). Devices: Android on 64-bit and 32-bit ARM. The
library is checked on a device by upstream's test suite at each setup.

libsodium is under the [ISC license](https://github.com/jedisct1/libsodium/blob/master/LICENSE).
