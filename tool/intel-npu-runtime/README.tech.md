# intel-npu-runtime — the Intel NPU user-space driver for Linux, without root

On Linux the kernel's `intel_vpu` driver runs an Intel NPU (Meteor Lake and later, the
`npu-intel` target) and gives it a device node (`/dev/accel/accel*`). Computing on the NPU also
needs a user-space driver, which the distribution does not ship:

- the NPU's Level Zero driver, `libze_intel_npu.so.1` (package `intel-level-zero-npu`);
- the compiler in driver, `libopenvino_intel_npu_compiler.so` (package
  `intel-driver-compiler-npu`), which compiles OpenVINO models for the NPU;
- the Level Zero loader, `libze_loader.so.1` (package `libze1`), through which OpenVINO's NPU
  plugin finds the driver;
- oneTBB, `libtbb.so.12` (package `libtbb12`), which the compiler needs.

```bash
cx tool setup intel-npu-runtime            # the system's driver, else Intel's packages in the cache
cx task run target --compute=npu-intel     # on Linux x86_64 this sets it up too, once it finds the NPU
```

## Detection

A system driver counts when two things hold:

- `libze_intel_npu.so.1` is in a system library folder;
- `dpkg-query` reports the version of its `intel-level-zero-npu` package.

The setup exports nothing for a system driver. A driver that this setup unpacked has the
install's marker file (`cmeta-intel-npu-runtime.json`) in its root, three folders above the
library.

## Install: Intel's packages unpacked into the cache

When the system has no driver, the setup does the following:

1. It downloads Intel's release archive (`intel/linux-npu-driver`, release 1.38.0) for the Ubuntu
   release from GitHub and checks it against GitHub's sha256.
2. It unpacks two of the archive's packages into the cache entry (`content/1.38.0/`). It uses
   `dpkg-deb -x` when available, otherwise Python (`category/tool/api/common_deb.py`, shared with
   `tool/intel-gpu-runtime`).

Nothing is installed in the system. Without `-q` or `--install`, the setup asks before it
installs anything.

| Distribution | Archive | Download |
|---|---|---|
| Ubuntu 24.04 to 25.10, other distributions with glibc 2.38 or newer | `linux-npu-driver-v1.38.0.…-ubuntu2404.tar.gz` | 56 MB |
| Ubuntu 26.04 and later | `linux-npu-driver-v1.38.0.…-ubuntu2604.tar.gz` | 58 MB |

On an older glibc (Ubuntu 22.04, Debian 12), the setup fails before it downloads anything.

The setup also adds two libraries:

- **The Level Zero loader 1.34.0** (`libze1` from `oneapi-src/level-zero`), pinned as in
  `tool/intel-gpu-runtime`.
- **oneTBB** (`libtbb12` from the release's Ubuntu archive, pinned to the sha256 in its apt
  index), only when the system has no `libtbb.so.12`.

Unpacked, the driver and its compiler take about 135 MB. The marker file records the sha256 of
every archive and package.

The setup skips the archive's third package, `intel-fw-npu`: it installs the NPU firmware to
`/lib/firmware/updates/intel/vpu`, which needs root. The kernel instead loads the firmware from
`linux-firmware` (`/lib/firmware/intel/vpu/vpu_<generation>_v1.bin`).

## What the result exports

For a driver in the cache, the steps that follow get
`LD_LIBRARY_PATH += content/1.38.0/usr/lib/x86_64-linux-gnu`. That folder holds the driver, its
compiler, the Level Zero loader and oneTBB, so the loader finds the NPU driver by name.

## Device access and firmware

On Ubuntu, `/dev/accel/accel*` is `root:render 0660`. The user needs the `render` group
(`sudo usermod -aG render $USER`, then log in again) or a desktop session on the machine. The
setup warns in two cases:

- the user cannot open the device;
- `/lib/firmware` has no NPU firmware.

When an Intel NPU is on the PCI bus but has no accel device, `target--npu-intel` says so. Either
the kernel has no `intel_vpu` driver for the NPU, or the driver could not load the NPU's firmware.
The kernel log (`sudo dmesg | grep -i vpu`) tells which.

## Other systems

- **Windows:** the Intel NPU driver comes from Windows Update or Intel's driver package
  ("Intel(R) AI Boost"). The setup reports this instead of installing anything.
- **macOS, and Linux on other architectures:** Intel publishes the Linux NPU driver for x86_64
  only.
