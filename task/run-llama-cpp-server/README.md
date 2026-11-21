# run-llama-cpp-server - a llama.cpp server on this machine

Starts `llama-server` detached with a GGUF model from a model artifact, waits until it answers `/health`, and keeps
its record (`server.json`: pid, port, model, command) and its log in the state artifact `local:llama-cpp-server-<port>`.
The server speaks three wires on one port - the Anthropic Messages API (`/v1/messages`), chat completions
(`/v1/chat/completions`) and the Responses API (`/v1/responses`, the builds since 2026-10-16) - so Claude Code, Codex
and OpenCode can all use it through an `ai.gateway` artifact where a repository provides the AI gateways (one
named `llama-cpp-local`, say: `base_url http://127.0.0.1:8686`, both wires, no key, `provided_by: this task`).

```
cx task run run-llama-cpp-server                                      # Qwen3-8B Q4_K_M (about 5 GB) on CUDA, port 8686
cx task run run-llama-cpp-server --model=hf-ggml-org@gpt-oss-20b-GGUF                   # a larger model: the layers that fit on the GPU, the rest on the CPU
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
  Responses format; the file gpt-oss-20b-MXFP4.gguf, about 12 GB: on an 8 GB GPU `--fit` keeps part of it on the CPU).
  The file is downloaded once into cMeta's file cache by the model task (`get-hf-model`).
- **The GPU layers** are left to llama.cpp's `--fit` by default (`--gpu_layers=auto`): the builds since 2026 load as many
  layers as the device memory takes, with the context below, and keep the rest on the CPU - gpt-oss-20b on an 8 GB
  GPU loads without a number; `--gpu_layers=<n>` pins it (`-ngl`).
- **The context** is 32k tokens by default (`--ctx_size`): Claude Code's first request alone carries about 17k tokens
  of system prompt and tools (the T470p round of 2026-10-25: "request (17382 tokens) exceeds the available context size
  (16384)"), so a smaller window stops it before the first answer; the KV cache grows with it (a few GB at 32k).
- **Which harness works with which model** depends on the model's tool calling: Claude Code and Codex send large
  tool sets; a model of eight billion parameters follows them slowly and sometimes badly, OpenCode is the forgiving
  one. The matrix of 2026-10-25 is in the fgg work item of the AI gateway.
- `--host=0.0.0.0` serves other machines (a remote gateway artifact then names this host's address); there is no key,
  so only on a private network.

**Its defaults: `config::task-run-llama-cpp-server`** (since 2026-11-19). What a start takes when its command line does
not say - the model, the file, the build (`compute`: the hardware it runs on), the context, the GPU layers, the alias,
the requests at once - comes from this config of the machine, else from the values above:

```
cx config set task-run-llama-cpp-server --meta.model=hf-ggml-org@gpt-oss-20b-GGUF --meta.ctx_size=65536
cx config read task-run-llama-cpp-server
```

A word on the command line wins. A server a host keeps (`server: run: cxt run-llama-cpp-server --foreground` in a
project of its host artifact) takes a change at its next start; a page of the server can set the keys and restart it.

**Another model, or several** (since 2026-11-20).

- **A server that is up is left as it is.** A start that names a model it does not serve says so (and answers
  `other_model: true`): nothing is replaced behind a caller's back. `--swap` replaces it: the server this task
  started is stopped and started with the model asked for. A server another program started is never replaced.
  `--swap` looks at the models only; another context or limit is a `--action=restart`.

  ```
  cx task run run-llama-cpp-server --model=hf-Qwen@Qwen2.5-0.5B-Instruct-GGUF --swap
  ```

- **Several models behind one port:** `--models="<a>;<b>;<c>"` (or the config key `models`). llama-server is then
  started without a model, as llama.cpp's *router*: every model is listed in `/v1/models`, a request names one in its
  `"model"` field, and that model is loaded then, as an instance of its own. `--models_max=<n>` (1 by default) says
  how many stay loaded: beyond it the least recently used one is unloaded, never one that is answering. With 1 the
  models swap on demand, which is what a small GPU needs; a request for a model that is not listed gets a 400.

  ```
  cx task run run-llama-cpp-server --models="hf-Qwen@Qwen3-8B-GGUF;hf-Qwen@Qwen2.5-0.5B-Instruct-GGUF" --models_max=1
  cx task run run-llama-cpp-server --action=status          # which are loaded now
  ```

  The models are the artifacts named and no others: their files are written into `models.ini` of the server's state
  (llama.cpp's preset file; the context, the requests at once and the GPU layers are its common section), and
  llama.cpp's own cache of downloads is pointed at an empty folder. A model's name is its file's name, as for one
  model. One model named on the command line (`--model=`) is one model served, whatever the config says of several.

**Its numbers.** The server starts with `--metrics`: llama.cpp's own counters at `http://127.0.0.1:<port>/metrics`
(Prometheus' format, `llamacpp:` names - tokens in and out, their speeds, requests being served and waiting), beside
`/health`, `/props` (the model, the context, the build) and `/slots` (what each slot is doing). A server in the
foreground keeps its record too (`server.json` of its state, gone when it ends), so `--action=status` knows what runs.
