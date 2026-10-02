# intel-gpu-runtime — the Intel GPU compute runtime for Linux, without root

An Intel GPU (the `xpu` target) computes through a user-space runtime that the distribution's
kernel driver (`i915` or `xe`) does not bring:

- the OpenCL ICD, `libigdrcl.so`, from `intel-opencl-icd` (OpenVINO's GPU plugin and ONNX
  Runtime's OpenVINO EP use it);
- the Level Zero driver `libze_intel_gpu.so.1` and the Level Zero loader (SYCL, PyTorch XPU);
- the Intel Graphics Compiler (`libigc`, `libigdfcl`, `libopencl-clang`) and `gmmlib`.

```bash
cx tool setup intel-gpu-runtime                            # the system's, else install the right line
cx tool setup intel-gpu-runtime --version=24.35.30872.36   # the legacy1 line
cx task run target --compute=xpu                           # does the same on Linux x86_64
```

## Detection

The system's runtime counts when `/etc/OpenCL/vendors/*.icd` names `libigdrcl.so` and its
package has a version (`dpkg-query`: `intel-opencl-icd`, `intel-opencl-icd-legacy1`; `rpm`:
`intel-compute-runtime`). Nothing is exported for it: the system's ICD loader already lists it.

## Install: Intel's packages unpacked into the cache

Without a system runtime, the setup downloads the packages of one release line from GitHub,
checks their sha256 and unpacks them into the cache entry (`content/<version>/`), with
`dpkg-deb -x` or, where there is none, in Python (ar, then zstd through Python 3.14, the
`zstandard` module or the `zstd` tool). Nothing is installed in the system.

| Line | For | Packages |
|---|---|---|
| `26.35.39758.10` | Gen12 and later: Tiger Lake, Rocket Lake, Alder/Raptor Lake, Meteor/Arrow/Lunar/Panther/Wildcat Lake, Arc (DG1, Alchemist, Battlemage); also in WSL2 | intel-opencl-icd 26.35.39758.10, libze-intel-gpu1, libigdgmm12 22.10.0, intel-igc-core-2 and intel-igc-opencl-2 2.41.5, libze1 1.34.0 |
| `24.35.30872.36` (legacy1) | Gen8, Gen9, Gen11: Broadwell, Skylake, Kaby Lake, Coffee/Comet Lake, Apollo/Gemini Lake, Ice Lake, Elkhart/Jasper Lake | intel-opencl-icd-legacy1, intel-level-zero-gpu-legacy1, libigdgmm12 22.5.0, intel-igc-core and intel-igc-opencl 1.0.17537.24, libze1 1.34.0 |

Without `--version` the line follows the Intel GPU's PCI device id in `/sys/bus/pci/devices`
(no `lspci` needed): legacy1 when every Intel GPU is Gen8-Gen11, else 26.35 (also in WSL2,
where the GPU is `/dev/dxg`). The packages need glibc 2.38 or newer (Ubuntu 24.04 and later).
Every package is checked against its sha256 (Intel's lists; for the legacy graphics compiler and
the Level Zero loader, which have none, the sha256 of the first download), and the marker file of
the install (`cmeta-intel-gpu-runtime.json`) records them. The legacy1 packages name their files
`libigdrcl_legacy1.so`, `libze_intel_gpu_legacy1.so.1` and `intel_legacy1.icd`.

## What the result exports

For a runtime in the cache, the steps that follow get:

- `LD_LIBRARY_PATH` += `content/<version>/usr/lib/x86_64-linux-gnu` and `content/<version>/usr/local/lib`
  (the graphics compiler lives in `usr/local/lib`);
- `OCL_ICD_FILENAMES` += the absolute path of `libigdrcl.so`. The system's ICD loader (ocl-icd)
  adds it to the ICDs of `/etc/OpenCL/vendors`, so an NVIDIA GPU stays visible next to it.
  (`OCL_ICD_VENDORS` would replace the system's list; `content/<version>/etc/OpenCL/vendors/intel.icd`
  is there for tools that want that.)

## Device access

Computing also needs the GPU device: `/dev/dri/renderD*` is `root:render 0660` on Ubuntu, so the
user needs the `render` group (`sudo usermod -aG render $USER`, then log in again) or a desktop
session on the machine. The setup warns when the device cannot be opened. In WSL2 the device is
`/dev/dxg`, which every user can open.

## Other systems

- **Windows:** the Intel graphics driver brings the OpenCL and Level Zero runtimes; the setup
  reports that instead of installing anything.
- **macOS:** no Intel GPU compute (OpenVINO on macOS runs on the CPU).
- **Linux on other architectures:** Intel publishes x86_64 packages only.
