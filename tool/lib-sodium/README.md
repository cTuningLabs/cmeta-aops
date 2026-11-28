# tool `lib-sodium`

[libsodium](https://libsodium.org) for cMeta programs: the pinned release in the tool's own cache entry,
installed the same way on Linux, macOS and Windows, with the static and the shared library side by side.
Nothing goes into the system and no package manager is asked.

```
cx tool setup lib-sodium                       # the pinned release (default_version of _desc.yaml) into the cache
cx tool setup lib-sodium --version=1.0.21      # another release that _desc.yaml pins
cx tool setup lib-sodium --with.check-         # Linux, macOS: without upstream's test suite
cx tool setup lib-sodium --with.toolset=v143   # Windows: the libraries of this MSVC toolset
cx tool setup lib-sodium --tool_path=<prefix>/include/sodium.h    # a libsodium that is already there
cx cache show | findstr lib-sodium             # the entries (grep on Linux and macOS)
```

## What it installs

| System | From | Into `<cache entry>/install` |
|---|---|---|
| Linux, macOS | upstream's source release `libsodium-<version>.tar.gz`, built with its own `configure` and `make` and the C compiler of cMeta, then its test suite (`make check`) | `include/`, `lib/libsodium.a`, `lib/libsodium.so` or `lib/libsodium.dylib` |
| Windows | upstream's build for MSVC `libsodium-<version>-msvc.zip` (clang links the same libraries) | `include/`, `<arch>/Release/<toolset>/static/libsodium.lib`, `.../dynamic/libsodium.lib` + `libsodium.dll` |

Each file is checked against the SHA-256 pinned in `_desc.yaml` (`release: sha256:`) before it is used; the
two addresses of `release: urls:` are tried in order. `install/_source.json` records what was installed,
from where, with which compiler, and whether the tests passed. The build logs stay in the entry
(`build-configure.log`, `build-make.log`, `build-check.log`, `build-install.log`).

Linux and macOS need a C compiler and `make` (cMeta sets both up; on macOS they come with the Xcode Command
Line Tools). Windows needs nothing besides the download.

## What a program gets

Task `setup-compile` links every global key that starts with `lib-`, so a program only sets the tool up:

```yaml
- task: setup,a2f9b61079ce4333
  name: lib-sodium,604ec3c64fab44b1
```

| Build | Linked | At run time |
|---|---|---|
| dynamic (the default) | the shared library (`-lsodium`; on Windows the import library by its path) | the library's folder is in `features.paths.found_dynamic_lib_paths`: `cx program run` puts it on the loader's path |
| `--compile.static` | the static library by its path, with what it needs (`Libs.private` of the installed `libsodium.pc`; on Windows the library names `advapi32` itself) | nothing |

One cache entry serves both builds. `features.static_lib` and `features.dynamic_lib` name the two files.
A static link on Windows needs `-DSODIUM_STATIC` in the program (libsodium's own rule; the other
compilers ignore it).

On Windows the oldest MSVC toolset of the package is taken unless `--with.toolset` names one: Microsoft's
linkers take libraries of the same and of older toolsets, so it links with the most compilers. A toolset
the package does not have is refused.

## Another version

`_desc.yaml` holds the facts that change with a release (`release:`). A new version is an edit of that
block: its two SHA-256 - GitHub publishes them for the files of a release (`digest` in
`https://api.github.com/repos/jedisct1/libsodium/releases`) - and `default_version` once it is tested.
A version that is not pinned is refused; for one try: `--version=<version> --with.sha256=<SHA-256 of the file>`.

## A libsodium that is already there

`--tool_path=<prefix>/include/sodium.h` describes an installation instead of installing one (a prefix with
`lib/`, such as Homebrew's `/opt/homebrew/opt/libsodium`, or an unpacked MSVC package); it is never
changed. Without a static library there, a static build stops and says so. That choice is an entry of the
cache like the others: `cx cache rm <entry>` goes back to the pinned release.

## Systems

| System | Compilers | What is installed |
|---|---|---|
| Linux x86-64 and arm64 (Debian, Ubuntu, Fedora, the RHEL family, openSUSE, Amazon Linux, Azure Linux) | gcc, clang | built from the source release, upstream's test suite run |
| macOS arm64 | Apple clang | built from the source release, upstream's test suite run |
| Windows x64 | MSVC, clang | upstream's build for MSVC |
| Android | the NDK's clang | another tool: [`lib-sodium-android`](../lib-sodium-android/README.md) |

libsodium is under the [ISC license](https://github.com/jedisct1/libsodium/blob/master/LICENSE).
