# Ollama in cMeta: the portable release, runs and every option

| Artifact | Does |
|---|---|
| `tool/ollama` | detects or installs the pinned portable release into the cMeta cache |
| `program/test-ollama` | starts a private server, generates once and records Ollama's timings |

Targets are chosen with `--compute` (or `--target`); see [task/target/README.tech.md](../../task/target/README.tech.md).

## The release: tool/ollama

```bash
cx tool setup ollama                        # the pinned release (0.35.0), else what is installed
cx tool setup ollama --version=<x.y.z>      # another release
cx tool setup ollama --versions             # the released versions
cx tool setup ollama --with.variant=rocm    # rocm, mlx, jetpack6: the other Linux/Windows builds
cx tool setup ollama --status | --upgrade
```

- No installer, no system service, no administrator rights.
- The assets:
  - Windows: `ollama-windows-<arch>.zip`;
  - Linux: `ollama-linux-<arch>.tar.zst`, which a Python 3.14 unpacks (uv downloads one if
    needed) before the `zstd` CLI is tried;
  - macOS: `ollama-darwin.tgz` (Metal).
- Fallbacks: winget (`Ollama.Ollama`), Homebrew (`ollama`), the official script (Linux, root).

## Running: program/test-ollama

```bash
cx program run test-ollama --compute=cuda          # cpu, cuda, metal, rocm, vulkan
cx program run test-ollama --compute=cpu,cuda --ngl=12
cx program run test-ollama --model=qwen2.5:1.5b --n=128 --port=11436 --models_dir=/data/ollama
```

| Option | Default | Meaning |
|---|---|---|
| `--model` | `qwen2.5:0.5b` (Q4_K_M) | model from the Ollama library, pulled if missing |
| `--n` | 64 | `num_predict` |
| `--ngl` | | `num_gpu`: layers on the GPU, the rest on the CPU |
| `--port` | 11435 | the private server's port; an Ollama already running elsewhere keeps running |
| `--models_dir` | `~/.ollama/models` | `OLLAMA_MODELS` |

- `--compute=cpu` keeps the model on the CPU (`num_gpu 0`).
- `--compute=vulkan` sets `OLLAMA_VULKAN=1`.
- The prompt is fixed: "How does a computer work? Answer in two sentences." It runs with
  temperature 0 and seed 12345, after a one-token warm-up, so the measured run does not include
  loading the model.
- The server and its model runners (`llama-server`) stop at the end. On Windows the runners used
  to survive the server, holding RAM and VRAM.

**Result** `stats`:
- `ollama` (the version), `model` and `targets`;
- `pull_s` and `load_s`;
- `prompt_tokens`, `prompt_tokens_per_second`, `generated_tokens`,
  `generation_tokens_per_second` (Ollama's `eval_count / eval_duration`) and `total_s`;
- `size_mib` and `size_vram_mib` (how much of the model sits on the GPU);
- `settings`, `response` and `error`.

The server's log is `ollama-serve.log` in the program's build folder.

## Measured (2026-10-01/02, generation tokens per second)

| Machine | GPU | CPU | Partial (`--ngl=12`) |
|---|---|---|---|
| Windows laptop, RTX PRO 1000 | CUDA 273.7 | 116.7 | |
| Mac mini M4 | Metal 190.5 | 159.8 | |
| ThinkPad P14s, RTX A500 | CUDA 160.6 | | 118.0 (306 MiB in VRAM; 11.0 on the first run after the install) |
| ThinkPad T470p, GeForce 940MX | Vulkan 37.3 | 41.2 | 40.9 (395 MiB in VRAM) |

More results: [docs/cmeta-aops/llm-stacks.md](../../docs/cmeta-aops/llm-stacks.md).
