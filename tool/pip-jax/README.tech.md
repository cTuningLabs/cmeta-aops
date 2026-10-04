# pip-jax — JAX with the plugin of the target compute

`cx tool setup pip jax` installs JAX with pip. `jax` and `jaxlib` have CPU wheels for Linux
(x86_64, aarch64), macOS (Apple silicon) and Windows (x86_64). Each accelerator comes as a PJRT
plugin, and this sub-tool of `tool/pip` (its `check_params2` hook) picks the plugin from the
targets:

| Target | What pip installs | Where |
|---|---|---|
| `cpu` (or none) | `jax` | everywhere |
| `cuda` | `jax[cuda13]`: the CUDA 13 libraries come from pip | Linux x86_64 and aarch64, with a CUDA 13 driver and GPUs of compute capability 7.5 (Turing) or newer |
| `cuda` | `jax[cuda12]` | Linux, for older GPUs (CUDA 13 builds for none before Turing) and CUDA 12 drivers |
| `rocm` | `jax[rocm7-local]` | Linux x86_64, with the system's ROCm 7 |
| `xpu` | `jax[oneapi]`: Intel's oneAPI runtime comes from pip | Linux x86_64, not WSL2 |
| `metal` | `jax==0.5.0` and `jax-metal==0.1.1` | macOS on Apple silicon |

```bash
cx tool setup pip jax                                  # the CPU
cx program run <program> --compute=cuda                # a program's pip jax gets jax[cuda13] or jax[cuda12]
cx tool setup pip jax --with.jax_extras=cuda13-local   # other extras: the system's CUDA, tpu
```

The plugin is part of the cache identity (`with.variations`), so a CPU install is not reused for
a GPU. Programs keep one venv per set of targets.

## Choosing and refusing before the install

The plugin is chosen before anything is downloaded, from what the targets found:

- **CUDA:** the driver's CUDA version and the oldest GPU's compute capability come from
  `tool/cuda`. A driver older than CUDA 12 is refused.
- **No GPU plugin for the platform:** Windows has no JAX GPU plugin, and CUDA runs in WSL2. The
  CUDA plugins are for Linux only, and ROCm and oneAPI for Linux x86_64 only.
- **Intel GPUs:** JAX's oneAPI plugin is an alpha release, validated by Intel on the Arc Pro
  B-series and the Data Center GPU Max. It sees the integrated GPUs up to Xe-LP but does not
  compute on them. When every Intel GPU that the xpu target found is an HD, UHD or Iris GPU, the
  setup stops before the install; `--with.any_intel_gpu` tries anyway. Newer integrated GPUs
  are named "Arc" and are tried. The plugin needs the GPU's Level Zero driver, which the xpu
  target sets up on Linux (`tool/intel-gpu-runtime`).
- **Metal:** Apple's `jax-metal` 0.1.1 is the last release. The newest JAX it runs is 0.5.0:
  - JAX 0.5.1 and later fail to compile even `x @ y` (StableHLO bytecode errors, also with
    `ENABLE_PJRT_COMPATIBILITY=1`);
  - JAX 0.5.3 and later report that `default_memory_space` is not supported.

  The setup therefore pins JAX 0.5.0, whose wheels are for Python 3.10-3.13. With a newer
  Python it stops with the `--use.python.version` to add. `--version` picks another JAX.
