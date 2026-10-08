# test-sglang

One generation with [SGLang](https://github.com/sgl-project/sglang)'s offline engine (`sglang.Engine`),
recorded in `tmp-cmeta-program-stats.json`: the SGLang and torch versions, the device, the load and
generation time, the generated tokens and tokens per second - the way `test-vllm` does for vLLM.

```bash
cx program run test-sglang --compute=cuda
cx program run test-sglang --compute=cuda --model=Qwen/Qwen2.5-1.5B-Instruct --n=128 --gpu_mem=0.6
```

The result file holds the load time, a short warm-up (the first generation compiles kernels), the measured
generation and its tokens per second.

| Parameter | Default | Meaning |
|---|---|---|
| `--model` | `Qwen/Qwen2.5-0.5B-Instruct` | the Hugging Face model |
| `--n` | 64 | tokens to generate |
| `--gpu_mem` | 0.8 | `mem_fraction_static`: the share of the GPU memory for the weights and the KV cache |
| `--max_len` | 4096 | `context_length` |
| `--cuda_graph` | 1 | 0 runs without CUDA / HIP graphs (a shorter start; SGLang's eager decoding is no usable default on ROCm) |
| `--tp` | | `tp_size` (GPUs) |
| `--attention_backend` | SGLang's choice | `flashinfer`, `triton`, `torch_native`, `aiter` ... |
| `--sglang_version` | newest | the SGLang release |
| `--python_version` | `>=3.10,<3.13` | the Python of the program's venv (sgl-kernel's wheels) |

## Where SGLang comes from

- **CUDA**: `sglang[all]` from PyPI (sgl-kernel, flashinfer and the torch SGLang pins), in the program's
  own venv per set of targets.
- **ROCm**: SGLang publishes no ROCm wheels; its route is the official image
  `lmsysorg/sglang:<version>-rocm<N>-mi30x` (also for the RDNA/APU families as published). cMeta runs this
  program inside that container on the image's venv, which already holds SGLang:

  ```bash
  docker run -d --name cmeta-sglang --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 16g \
    lmsysorg/sglang:v0.5.21-rocm10-mi30x sleep infinity
  docker exec -it cmeta-sglang bash
  # in the container (root): uv, cMeta and the repository
  curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH=/root/.local/bin:$PATH
  uv tool install cmeta && cx repo pull ctuninglabs@cmeta-aops
  cx program run test-sglang --compute=rocm --use.python.tool_path=/opt/venv/bin/python --sglang_version=0.5.21 --gpu_mem=0.3
  ```

  The image's `/opt/venv/bin/python` is a venv, so the python step takes it as the program's environment;
  `--sglang_version` names the release the image holds (pip then leaves it alone); the rocm target finds the
  image's ROCm through the `rocm-smi` of that venv. A fleet host of type `docker` does the same through
  `cx host run`.
- **CPU** is not a target of this program (SGLang's CPU backend is a separate, Intel-specific build).
