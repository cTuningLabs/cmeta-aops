# test-nmm-rust-cpu — a naive matrix multiplication in Rust

A naive (triple loop) matrix multiplication in Rust with a configurable element type, sizes and
repeats. It prints the timing and writes `tmp-cmeta-program-stats.json` for cMeta, in the same
layout as the C and Go versions. The same program runs on the host CPU and on an Android device.

```bash
cx program run test-nmm-rust-cpu                      # the host CPU (Windows, Linux, macOS)
cx program run test-nmm-rust-cpu android-cpu          # the Android device connected over adb
cx program run test-nmm-rust-cpu --compile.fastest    # rustc -C opt-level=3 (--compile.fast: 1)
cx program run test-nmm-rust-cpu --precision=int32 --dim_m=500 --dim_n=500 --dim_k=500 --repeat=5
```

Without `--compile.fast` or `--compile.fastest`, rustc builds without optimization.

## Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `--precision` | `float32` | the element type: `float32`, `float64`, `int64`, `int32`, `int16`, `int8` |
| `--dim_m`, `--dim_n`, `--dim_k` | `1500` | the sizes: (M x N) * (N x K) |
| `--repeat` | `3` | how many times the multiplication runs |
| `--clean` | `1` | refill the inputs with random values before each repeat |
| `--seed` | `12345` | the seed of the random inputs |

## Targets

- **`cpu`:** [`tool/rustc`](../../tool/rustc/README.md), the Rust compiler of a rustup toolchain
  (rustup is downloaded into the cMeta cache when none is found), builds `program` (`program.exe`
  on Windows).
- **`android-cpu`:** [`tool/rustc-android`](../../tool/rustc-android/README.md): the same rustc
  compiles for the Rust target of the device's ABI (`aarch64-linux-android` for 64-bit Arm), whose
  standard library rustup adds to the toolchain the first time, and links with the Android NDK's
  clang for the device's API level. `setup-run` pushes the binary to `/data/local/tmp` over adb,
  runs it there and pulls the statistics back.

## Output

`tmp-cmeta-program-stats.json` holds the input (type, sizes, repeats, seed), `aggregated_value`
(the sum of all elements of the results, to compare runs) and the timing in seconds (`matmul_time`,
`data_prep`, `sum`, `total`: the minimum, the maximum and every repeat).
