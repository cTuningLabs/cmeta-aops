# OpenVINO in cMeta: the Intel NPU, GPU and CPU, and every option

| Artifact | Does |
|---|---|
| `task/target--npu-intel` | detects the Intel NPU without any SDK: its PCI ID, platform, generation and driver |
| `task/target--openvino` | the OpenVINO stack target; with a device target it says where OpenVINO runs |
| `program/test-openvino` | runs a small model on each selected device and records the device, compile time, latency and error |

Targets are chosen with `--compute` (or `--target`); see [task/target/README.tech.md](../../task/target/README.tech.md).

## The NPU target: task/target--npu-intel

- **Windows:** the `ComputeAccelerator` devices from the PnP manager (PowerShell CIM), with their
  driver version (`DEVPKEY_Device_DriverVersion`).
- **Linux:** `/sys/class/accel/accel*` devices of the `intel_vpu` driver.
- The NPU is matched by its PCI ID, not by name: Intel documents "Intel(R) AI Boost", and some
  laptops report "Intel(R) NPU".

| PCI ID | Platform | NPU generation |
|---|---|---|
| `8086:7d1d` | Meteor Lake | 37xx |
| `8086:ad1d` | Arrow Lake | 37xx |
| `8086:643e` | Lunar Lake | 40xx |
| `8086:b03e` | Panther Lake | 50xx |
| `8086:fd3e` | Wildcat Lake | 50xx |
| `8086:d71d` | Nova Lake | 60xx |

Features: `{{global.target.features.npu-intel.devices}}`, each with `pci_id`, `platform`,
`npu_generation` and `name`. On Windows there are also `driver_version`, `status` and
`instance_id`; on Linux, `node` and `driver`. Without an NPU the target fails and names what
it looked for. The variable is `CMETA_TARGET_NPU_INTEL`.

## Running: program/test-openvino

```bash
cx program run test-openvino --compute=npu-intel            # the NPU
cx program run test-openvino --compute=cpu,npu-intel        # the CPU and the NPU, side by side
cx program run test-openvino --compute=xpu                  # the Intel GPU
cx program run test-openvino --compute=openvino             # every device OpenVINO finds
cx program run test-openvino --compute=npu-intel --size=2048 --iterations=500 --precision=f32
cx program run test-openvino --compute=openvino --size=4096 --batch=256   # compute, not bandwidth
```

| Option | Default | Meaning |
|---|---|---|
| `--size` | 1024 | n: a (batch x n) @ (n x n) matmul and a ReLU |
| `--batch` | 1 | the rows of the input: 1 is a matrix-vector product, which memory bandwidth limits; 256 and more use the compute units |
| `--iterations` | 200 | timed inferences per device, after 5 warm-up ones |
| `--precision` | the device's | `f16` or `f32` (`INFERENCE_PRECISION_HINT`); the NPU computes in f16 |
| `--devices` | from the targets | OpenVINO device names instead (`NPU,GPU.1,CPU`) |
| `--openvino_version` | the newest | the `openvino` pip package's version |
| `--python_version` | `>=3.10,<3.15` | the Python of the program's venv (one per set of targets) |

- Each device is named in `compile_model` ("NPU", "GPU", "CPU"), never AUTO, and
  `EXECUTION_DEVICES` must name it. A device that fails cannot pass by falling back to the CPU.
- A device passes when its largest error against NumPy is at most 1% of the output's scale.
- The run fails (exit code 1) when a selected device is missing, fails, or computes wrong results.

## What a run records

`tmp-cmeta-program-stats.json` (the run's `stats`):

- the OpenVINO version, the targets, the size and the devices OpenVINO finds;
- per device:
  - the properties: `FULL_DEVICE_NAME`, `DEVICE_ARCHITECTURE`, `DEVICE_TYPE`,
    `OPTIMIZATION_CAPABILITIES` and `DEVICE_GOPS` (peak per element type); for the NPU also
    `NPU_DRIVER_VERSION`, `NPU_COMPILER_VERSION` and `NPU_DEVICE_TOTAL_MEM_SIZE`; for a GPU,
    `GPU_DEVICE_TOTAL_MEM_SIZE` and `GPU_EXECUTION_UNITS_COUNT`;
  - `compile_ms`, `execution_devices` and `inference_precision`;
  - `latency_us` (min, median, p90, max, mean), `inferences_per_second` and `gflops`;
  - `max_abs_error`, `max_rel_error`, `passed`, or `error`.

With the defaults the model is small, so the latency measures how long a call to the device
takes. A larger `--size` with `--batch=1` measures memory bandwidth (the weights are read once
per call); a large `--batch` measures compute.
