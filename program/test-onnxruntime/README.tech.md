# ONNX Runtime in cMeta: one package per target, and every option

| Artifact | Does |
|---|---|
| `tool/pip-onnxruntime` | `setup pip onnxruntime`: installs the ONNX Runtime build that fits the targets |
| `program/test-onnxruntime` | runs a small model on each target's execution provider and records the provider, latency and error |
| `program/image-classification-onnx` | image classification with a Hugging Face ONNX model, on the same packages |

Targets are chosen with `--compute` (or `--target`); see [task/target/README.tech.md](../../task/target/README.tech.md).

## The package: tool/pip-onnxruntime

Each build of ONNX Runtime is its own PyPI package, and they all install the same `onnxruntime`
module, so one Python environment holds one of them. The programs keep a venv per set of
targets (`venv-<targets>` in the build folder).

| Targets | Package | Notes |
|---|---|---|
| `cuda` | `onnxruntime-gpu[cuda,cudnn]` | CUDA 13 and cuDNN 9 come from pip; Windows and Linux |
| `npu-intel`, `xpu`, `openvino` | `onnxruntime-openvino` | Windows and Linux x86_64, Python 3.11-3.13; on Windows the `openvino` package it was built against comes along |
| `rocm` | `onnxruntime-migraphx` | Linux |
| `cpu`, `metal`, others | `onnxruntime` | CoreML is in the macOS package |

`--with.ort_package=<package>` picks another one (`onnxruntime-directml`, `onnxruntime-qnn`, ...).

## Running: program/test-onnxruntime

```bash
cx program run test-onnxruntime --compute=cpu                   # CPUExecutionProvider
cx program run test-onnxruntime --compute=cuda                  # CUDAExecutionProvider
cx program run test-onnxruntime --compute=npu-intel             # OpenVINO EP on the NPU
cx program run test-onnxruntime --compute=xpu                   # OpenVINO EP on the Intel GPU
cx program run test-onnxruntime --compute=cpu,cuda --size=4096 --batch=256 --seconds=30
```

| Option | Default | Meaning |
|---|---|---|
| `--size` | 1024 | n: a (batch x n) @ (n x n) matmul and a ReLU, as an ONNX model |
| `--batch` | 1 | the rows of the input: 1 is a matrix-vector product, which memory bandwidth limits |
| `--iterations` | 200 | timed runs per provider, after 5 warm-up ones |
| `--seconds` | | run each provider this long instead, printing its progress |
| `--providers` | from the targets | provider names instead (`CUDAExecutionProvider,CPUExecutionProvider`) |
| `--onnxruntime_version` | the newest | the version of the ONNX Runtime package |
| `--python_version` | `>=3.11,<3.15` (`<3.14` for OpenVINO) | the Python of the venv |

| Target | Provider |
|---|---|
| `cpu` | `CPUExecutionProvider` |
| `cuda` | `CUDAExecutionProvider` |
| `npu-intel` | `OpenVINOExecutionProvider`, `device_type=NPU` |
| `xpu` | `OpenVINOExecutionProvider`, `device_type=GPU` |
| `openvino` alone | `OpenVINOExecutionProvider`, `device_type=CPU` |
| `metal` | `CoreMLExecutionProvider` |
| `rocm` | `MIGraphXExecutionProvider` |

- Each provider runs alone, with the session's CPU fallback disabled
  (`session.disable_cpu_ep_fallback`). A provider that cannot run the model fails instead of
  passing on the CPU; the run fails (exit code 1) then, or when the error against NumPy is
  above 1% of the output's scale.
- With several targets, each provider runs in turn (`--compute=cpu,cuda`).

## What a run records

`tmp-cmeta-program-stats.json` (the run's `stats`): the ONNX Runtime version and the available
providers. Per provider it records `session_ms`, the providers of the session, `calls`,
`latency_us` (min, median, p90, max, mean), `gflops`, `max_abs_error`, `passed` or `error`, and
for `--seconds` also `gflops_sustained` and `gflops_per_second`.
