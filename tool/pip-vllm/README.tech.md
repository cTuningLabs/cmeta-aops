# vLLM in cMeta: wheels, source builds, runs and every option

| Artifact | Does |
|---|---|
| `tool/pip-vllm` | installs the vLLM wheel for the targets and the driver into a Python venv |
| `program/test-vllm` | installs the wheel and generates once, recording vLLM's load and generation time |
| `program/build-vllm` | builds vLLM from source for the targets, then runs it the same way |

Targets are chosen with `--compute` (or `--target`); see [task/target/README.tech.md](../../task/target/README.tech.md).
vLLM does not run on native Windows: use the same commands in WSL2.

## The wheel: tool/pip-vllm

| Target | Wheel |
|---|---|
| `cuda`, driver with CUDA 13+ | PyPI (the CUDA 13.0 build, torch from PyPI) |
| `cuda`, driver with CUDA 12.x | `https://wheels.vllm.ai/<version>/cu129` + torch `cu129` |
| `cpu` | `https://wheels.vllm.ai/<version>/cpu` (+ torch `+cpu` on Linux); Linux wheels need glibc 2.39 |
| `rocm` | `https://wheels.vllm.ai/rocm/<version>/rocm723` (Python 3.12) |
| `xpu` | `https://wheels.vllm.ai/<version>/xpu` + torch `xpu` |

- Without a version the newest vLLM on PyPI is used and recorded.
- vLLM needs Python 3.10–3.14 (not 3.14.1), and 3.12 on macOS. A wrong Python gets an error
  that says which one to use.
- Pip installs are cached per target variation (`with.variations.compute`: `cpu`, `cuda`,
  `cu130`, ...).

## Running: program/test-vllm

```bash
cx program run test-vllm --compute=cuda
cx program run test-vllm --compute=cuda --enforce_eager=0           # CUDA graphs
cx program run test-vllm --compute=cpu --cpu_kv_cache_gib=1 --max_len=2048     # a 7 GB laptop
cx program run test-vllm --compute=cuda --model=Qwen/Qwen2.5-1.5B-Instruct --dtype=float16
```

| Option | Default | vLLM setting |
|---|---|---|
| `--model` | `Qwen/Qwen2.5-0.5B-Instruct` | the Hugging Face model |
| `--n` | 64 | `max_tokens` |
| `--max_len` | 4096 | `max_model_len` |
| `--gpu_mem` | 0.8 | `gpu_memory_utilization` (GPU targets) |
| `--cpu_kv_cache_gib` | 4 | `VLLM_CPU_KVCACHE_SPACE` (CPU target) |
| `--enforce_eager` | 1 | 0 allows CUDA graphs |
| `--cpu_offload_gb` | | `cpu_offload_gb`: weights kept in CPU memory (`--compute=cpu,cuda` experiments) |
| `--dtype` | auto | `dtype` |
| `--tp` | 1 | `tensor_parallel_size` (GPUs) |
| `--vllm_version` | newest | the wheel version |
| `--python_version` | `>=3.10,<3.15` (3.12 on macOS) | the venv's Python |

- The prompt is fixed: "How does a computer work? Answer in two sentences." It is decoded
  greedily (temperature 0) with seed 12345.
- Each set of targets has its own venv in the program's build folder (`venv-<targets>`), so the
  CPU and the CUDA wheels never replace each other.
- On a Linux CPU, `libnuma` comes from `tool/lib-numa`. In Docker, give `/dev/shm` room
  (`--shm-size=2g`).
- The venv's `bin` is on `PATH`: FlashInfer compiles kernels at run time with its `ninja`.

**Result** `stats`:
- `vllm`, `torch`, `torch_cuda` and `device` (the GPU's name);
- `load_s`, `generate_s`, `generated_tokens` and `tokens_per_second` (the tokens divided by the
  time of `generate()`, prefill included);
- `settings` (the vLLM arguments) and `response`.

## Building from source: program/build-vllm

```bash
cx program run build-vllm --compute=cuda                    # v0.30.0 for the detected GPU (one to several hours)
cx program run build-vllm --compute=cpu --checkout=v0.30.0
cx program run build-vllm --compute=cuda --cuda_arch_list="8.6;12.0" --max_jobs=4 --nvcc_threads=2
```

| Option | Default | Meaning |
|---|---|---|
| `--checkout` | `v0.30.0` | tag, branch or commit |
| `--cuda_arch_list` | the detected GPUs | `TORCH_CUDA_ARCH_LIST` (one architecture shortens the build a lot) |
| `--max_jobs` | sized to the RAM (4 GiB per CUDA job) | `MAX_JOBS` |
| `--nvcc_threads` | 1 | `NVCC_THREADS` |
| `--build_type` | Release | `CMAKE_BUILD_TYPE` |
| `--compile.env.<VAR>=<value>` | | any other build variable (vLLM's `setup.py`, `vllm/envs.py`) |
| `--python_version` | `>=3.10,<3.14` | vLLM 0.30.0's vllm-flash-attn rejects Python 3.14 |

- The build installs `requirements/build/<device>.txt` with a torch matching the toolkit's CUDA
  major version, then runs `pip install --no-build-isolation -v .`.
- The variables it sets are `VLLM_TARGET_DEVICE`, `CUDA_HOME` (the toolkit of `nvcc`),
  `TORCH_CUDA_ARCH_LIST`, `MAX_JOBS` and `NVCC_THREADS`. A CPU build also sets
  `-DCMAKE_DISABLE_FIND_PACKAGE_CUDA=ON`, so a local CUDA toolkit stays out of it.
- The run takes the options of `test-vllm` and records the same `stats`.
