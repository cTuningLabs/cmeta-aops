# run-vllm-server - a vLLM server on this machine

Runs vLLM's own container image (`vllm/vllm-openai`) with the GPU passed in, publishes its port on this machine,
waits until it answers `/health`, and keeps its record (`server.json`: the container, the image, the model, the
settings) in the state artifact `local:vllm-server-<port>`. The server speaks the OpenAI wires
(`/v1/chat/completions`, `/v1/responses`, `/v1/models`) and keeps its numbers at `/metrics` (Prometheus' format,
`vllm:` names).

```
cx task run run-vllm-server                                     # Qwen3-0.6B on the GPU, port 8868, detached
cx task run run-vllm-server --model=Qwen/Qwen3-4B --max_model_len=16384
cx task run run-vllm-server --action=status
cx task run run-vllm-server --action=logs --lines=100
cx task run run-vllm-server --action=stop
cx task run run-vllm-server --foreground                        # attached: its log on the screen (a host keeps it so)
cx task run run-vllm-server -- --enable-auto-tool-choice --tool-call-parser hermes    # more words for vLLM
```

- **Where it runs.** In Docker (the docker client is cMeta's tool `docker`; Docker Desktop on Windows, Docker with the
  NVIDIA container toolkit on Linux), with `--gpus all`. The container is named `cmeta-vllm-<port>`; a start removes a
  container of that name that ended before.
- **The port** is 8868 by default; vLLM's own 8000 stays inside the container. `--host=0.0.0.0` publishes it to other
  machines: there is no key, so only on a private network.
- **The models** are downloaded once by vLLM into the state artifact `local:vllm-cache`, mounted as the container's
  `/root/.cache` (vLLM's compiled kernels are kept there too, so a second start is quicker). A model that needs a
  Hugging Face login takes `HF_TOKEN` of this console, passed through a temporary env file, never on a command line.
- **The memory.** `--gpu_memory_utilization` (0.85) is the share of the GPU's memory vLLM takes for the model and its
  KV cache, `--max_model_len` (8192) the context window; a context the memory cannot hold stops the start, with
  vLLM's own words in the error.
- **A first start** pulls the image (vllm/vllm-openai:v0.31.0 is 32 GB once unpacked) and the model, then
  compiles: it may take minutes (the laptop, 2026-11-19: 239 s with the model's download, 142 s the next time).
  `--timeout` (1200 s) bounds the wait; the last line of the container's log is shown meanwhile.

**Its defaults: `config::task-run-vllm-server`.** What a start takes when its command line does not say - the model,
the image (the vLLM release), the context, the memory share, the name it serves the model under, the requests at
once - comes from this config of the machine, else from the values above:

```
cx config set task-run-vllm-server --meta.model=Qwen/Qwen3-4B --meta.max_model_len=16384
cx config read task-run-vllm-server
```

A word on the command line wins. A server a host keeps (`server: run: cxt run-vllm-server --foreground` in a project
of its host artifact, with `stop: cxt run-vllm-server --action=stop`) takes a change at its next start; a page of the
server can set the keys and restart it.
