# run-llama-cpp-server - a llama.cpp server on this machine

Starts `llama-server` detached with a GGUF model from a model artifact, waits until it answers `/health`, and keeps
its record (`server.json`: pid, port, model, command) and its log in the state artifact `local:llama-cpp-server-<port>`.
The server speaks three wires on one port - the Anthropic Messages API (`/v1/messages`), chat completions
(`/v1/chat/completions`) and the Responses API (`/v1/responses`, the builds since 2026-10-16) - so Claude Code, Codex
and OpenCode can all use it through an `ai.gateway` artifact (`ai.gateway::llama-cpp-local`: `base_url
http://127.0.0.1:8686`, both wires, no key, `provided_by: this task`).

```
cx task run run-llama-cpp-server                                      # Qwen3-8B Q4_K_M (about 5 GB) on CUDA, port 8686
cx task run run-llama-cpp-server --model=hf-ggml-org@gpt-oss-20b-GGUF --gpu_layers=16   # a larger model, part of it on the CPU
cx task run run-llama-cpp-server --action=status
cx task run run-llama-cpp-server --action=stop
cxai --gateway=llama-cpp-local "..."                                  # Claude Code on the local model
```

- **The port** is 8686 by default, not llama.cpp's own 8080: that one is the busiest port of a developer's machine.
  `--port` changes it; the gateway artifact's `base_url` must say the same.
- **The tool** comes from `tool/llama-cpp` for the chosen `--compute` (cuda by default; cpu, metal), built or installed
  by the setup task on first use; `--jinja` is on, so the model's chat template and its tool calling are used.
- **The model** is a model artifact with a GGUF file (`cx model ls`): `hf-Qwen@Qwen3-8B-GGUF` (the default: a small
  tool-calling model that fits an 8 GB GPU) and `hf-ggml-org@gpt-oss-20b-GGUF` (OpenAI's open model, made for the
  Responses format; about 13 GB, so `--gpu_layers` below the whole on an 8 GB GPU). The file is downloaded once into
  cMeta's cache by the model task.
- **Which harness works with which model** depends on the model's tool calling: Claude Code and Codex send large
  tool sets; a model of eight billion parameters follows them slowly and sometimes badly, OpenCode is the forgiving
  one. The matrix of 2026-10-25 is in the fgg work item of the AI gateway.
- `--host=0.0.0.0` serves other machines (a remote gateway artifact then names this host's address); there is no key,
  so only on a private network.
