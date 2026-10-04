# rustc-android — Rust programs for Android

The compiler that `task/compiler` selects for Rust programs (`lang-rust`) on the `android-cpu`
target. It is the host's Rust compiler ([`tool/rustc`](../rustc/README.md), through rustup), the
same `rustc` as for host builds, set up to cross-compile for the Android device that
`target--android-cpu` selected:

```bash
cx program run test-nmm-rust-cpu android-cpu
```

- **The target:** the Rust target of the device's ABI (`ro.product.cpu.abi`):
  `aarch64-linux-android` for `arm64-v8a`, `armv7-linux-androideabi`, `x86_64-linux-android`,
  `i686-linux-android`.
- **Its standard library:** added to rustc's toolchain with `rustup target add <target>` the first
  time it is missing (a download into the rustup home that cMeta uses; no administrator rights).
- **The linker:** the Android NDK's clang ([`tool/google.android-ndk.clang`](../google.android-ndk.clang),
  installed through the Android SDK tools when missing), linking for the device's API level (capped
  at the highest level of the NDK):

  ```
  rustc --target aarch64-linux-android -C linker=<NDK clang> -C link-arg=--target=aarch64-linux-android<API> program.rs
  ```

- **The executable** has no extension on any host (`program`, also on Windows) and links only with
  Android's own libraries (libc, libm, libdl).

Host builds (`cpu`) use `tool/rustc` as before: this tool supports only `android-cpu`.
