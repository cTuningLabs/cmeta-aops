# test-vllm

Installs the vLLM wheel for the targets and the driver, and generates once.

All the cMeta options of the vLLM artifacts (targets, versions, build and run parameters,
results, recipes): [tool/pip-vllm/README.tech.md](../../tool/pip-vllm/README.tech.md).

Targets (`--compute`, `--target`, `cx program targets`): [task/target/README.tech.md](../../task/target/README.tech.md).

## ROCm

vLLM's ROCm wheels (`wheels.vllm.ai/rocm/<version>/rocm723`) are built for Python 3.12 and ROCm 7.2: the program
sets up Python 3.12 and Open MPI for the `rocm` target and they run on a ROCm 7.x machine. On a ROCm 10 machine the
wheel's `amdsmi` package does not match the system library (`libamd_smi.so.27: undefined symbol
amdsmi_set_gpu_clk_range`, seen on an MI300X with ROCm 10.1): there the route is AMD's official image, with cMeta
inside it running this program on the image's own Python and its preinstalled vLLM:

```bash
docker run -d --name cmeta-vllm --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 16g \
  rocm/vllm:rocm10.1.0_ubuntu24.04_py3.14-pytorch_2.13.0_vllm-0.29.0 sleep infinity
docker exec -it cmeta-vllm bash
# in the container (root; uv is in the image)
uv tool install cmeta && export PATH=/root/.local/bin:$PATH && cx repo pull ctuninglabs@cmeta-aops
cx program run test-vllm --compute=rocm --use.python.tool_path=/opt/python/bin/python3 --use.python.with.venv- \
  --python_version=">=3.14" --vllm_version=$(python3 -m pip show vllm | sed -n 's/^Version: //p') --gpu_mem=0.4
```

`--use.python.tool_path` names the image's interpreter, `--use.python.with.venv-` runs it directly (no venv on
top), `--python_version` widens the program's 3.12 for rocm to what the image has, and `--vllm_version` names the
vLLM already installed (pip's version string, `+...rocm101`), so pip leaves it alone. The `rocm` target finds the
image's ROCm through `rocm-sdk` (AMD's Python distribution: no rocm-smi in these images). Verified on an MI300X
on 2026-10-08 with the image's vLLM 0.29.1 and torch 2.13.0+rocm10.1.0. A fleet host of type `docker` does the
same through `cx host run`.
