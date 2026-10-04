# OpenCL: the runtime and the opencl target

```bash
cx tool setup opencl -j                       # the library, its platforms and devices
cx tool setup opencl --tool_path=<library>    # a given library (OpenCL.dll, libOpenCL.so.1, the macOS framework)
cx task run target --compute=opencl           # the opencl target
```

## The runtime: tool/opencl

- The platforms and devices come from the OpenCL library itself (`opencl_probe.py` through
  ctypes): no OpenCL SDK and no `clinfo`.
- The library:
  - on Windows, `OpenCL.dll` (System32), which the GPU drivers bring;
  - on Linux, the ICD loader `libOpenCL.so.1` (ocl-icd), found by its soname;
  - on macOS, the OpenCL framework.
- The features are `platforms`, `devices` (each with its platform), `gpus`, `vendors`, `version`
  (the newest OpenCL version of the platforms) and `paths.library`. Each device has its name,
  type (gpu, cpu, accelerator), vendor, version, driver version, compute units, clock and global
  memory.
- **Installing:**
  - Windows and macOS: nothing to install; the GPU drivers bring OpenCL.
  - Linux: the ICD loader (`ocl-icd-libopencl1` and the distribution's names), with sudo. The
    drivers register their ICDs in `/etc/OpenCL/vendors`, or through `OCL_ICD_FILENAMES`, as
    `tool/intel-gpu-runtime` exports.
  - Without a GPU to use (no `/dev/dri` render node, no `/dev/dxg`, no `/dev/nvidia0` or
    `/dev/kfd`), the setup stops before installing. `--with.allow_cpu` installs anyway.

## The opencl target

- It fails when the library lists no device. It also fails when it lists only CPU devices
  (Intel's CPU runtime, PoCL), because an opencl run there would compute on the CPU.
  `--use.target--opencl.allow_cpu` accepts them. A cached target is checked again.
- On Linux x86_64 with an Intel GPU on the PCI bus, it sets up `tool/intel-gpu-runtime` first:
  the system's runtime, or Intel's packages without root. Its ICD then joins the system's, so
  OpenCL lists the Intel GPU next to an NVIDIA one. `--use.target--opencl.skip_intel_runtime`
  skips that.
- It sets `CMETA_TARGET_OPENCL=1`.

## Android

The `android-gpu` target (`task/target--android-gpu`) records the device's OpenCL library and
whether apps may load it (`/vendor/etc/public.libraries.txt`).

From the adb shell, a vendor `libOpenCL.so` can be an ICD loader that finds no platform (error
-1001, on Mali). Loaded in the vendor ("sphal") namespace through
`android_load_sphal_library()` (`libvndksupport.so`), as Android loads GPU drivers, it finds
the platform.
