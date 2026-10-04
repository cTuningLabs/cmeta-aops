# test-nmm-go-cpu — a naive matrix multiplication in Go

A naive (triple loop) matrix multiplication in Go with a configurable element type, sizes and
repeats. It prints the timing and writes `tmp-cmeta-program-stats.json` for cMeta. The same
program runs on the host CPU and on an Android device.

```bash
cx program run test-nmm-go-cpu                        # the host CPU (Windows, Linux, macOS)
cx program run test-nmm-go-cpu android-cpu            # the Android device connected over adb
cx program run test-nmm-go-cpu --precision=float64 --dim_m=500 --dim_n=500 --dim_k=500 --repeat=5
```

## Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `--precision` | `float32` | the element type: `float32`, `float64`, `int64`, `int32`, `int16`, `int8` |
| `--dim_m`, `--dim_n`, `--dim_k` | `1500` | the sizes: (M x N) * (N x K) |
| `--repeat` | `3` | how many times the multiplication runs |
| `--clean` | `1` | refill the inputs with random values before each repeat |
| `--seed` | `12345` | the seed of the random inputs |

## Targets

- **`cpu`:** [`tool/go`](../../tool/go/README.md), the host's Go toolchain (downloaded into the cMeta
  cache when none is found), builds `program` (`program.exe` on Windows).
- **`android-cpu`:** [`tool/go-android`](../../tool/go-android/README.md): the same Go toolchain
  cross-compiles for the ABI of the device that the target selected (`GOOS=android`, `GOARCH` from
  the ABI, `CGO_ENABLED=0`, `-buildmode=pie`). The program is pure Go, so no Android NDK is
  needed. `setup-run` pushes the binary to `/data/local/tmp` over adb, runs it there and pulls
  the statistics back.

## Output

`tmp-cmeta-program-stats.json` holds the input (type, sizes, repeats, seed), `aggregated_value`
(the sum of all elements of the results, to compare runs) and the timing in seconds (`matmul_time`,
`data_prep`, `sum`, `total`: the minimum, the maximum and every repeat).
