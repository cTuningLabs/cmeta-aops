# go-android — Go programs for Android

The compiler that `task/compiler` selects for Go programs (`lang-go`) on the `android-cpu`
target. It is the host's Go toolchain ([`tool/go`](../go/README.md)), the same `go` binary as for
host builds, set up to cross-compile for the Android device that `target--android-cpu` selected:

```bash
cx program run test-nmm-go-cpu android-cpu
```

- **The target:** from the device's ABI (`ro.product.cpu.abi`): `GOOS=android` and `GOARCH`
  (`arm64` for `arm64-v8a`, `arm` with `GOARM=7` for `armeabi-v7a`, `amd64`, `386`). The tool puts
  them in `features.env`, which `task/setup-compile` gives to the compile command only.
- **Pure Go:** `CGO_ENABLED=0`. The Go linker makes the position-independent executable that
  Android requires (`-buildmode=pie`, for `/system/bin/linker64`) itself, so no Android NDK is
  needed. A Go program that uses cgo would need the NDK's clang as `CC`, which this tool does not
  set up.
- **The executable** has no extension on any host (`program`, also on Windows).

Host builds (`cpu`) use `tool/go` as before: this tool supports only `android-cpu`.
