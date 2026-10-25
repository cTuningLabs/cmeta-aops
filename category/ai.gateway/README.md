# ai.gateway - where the AI harnesses get their models

An artifact of this category is one place that serves models: a company's gateway (Azure API Management in front of
OpenAI and Anthropic), a vendor's own API, a llama.cpp or vLLM server on this machine or on a host. It names the base
URL, the wires the place speaks, the catalog of its models, how the key travels and WHICH secret holds it - never a
value. The harness tasks reach it through `set-ai-gateway` (`--gateway=<alias>`, `-gw`, `-ln`, the config keys): the
same Claude Code, Codex or OpenCode, the bill moved to the gateway's credits, or a local model.

```yaml
# ai.gateway/<alias>/_desc.yaml
description: Dapple's AI gateway
base_url: https://dapple-llm-gateway.azure-api.net
wires:                                  # what it speaks, each with its path under base_url
  anthropic: /anthropic                 #   the Messages API (/v1/messages under it) - Claude Code; '' = right under the base
  openai: /openai/v1                    #   chat completions and the Responses API - Codex, OpenCode
catalog: /v1/models                     # the list of usable models; catalogs: {anthropic: /anthropic/v1/models} per wire
auth:
  header: x-api-key                     # x-api-key | bearer | none
  secret: dapple-ai-gateway             # the secret artifact (kind token) that holds the key - cx secret ls
models:                                 # optional: the names behind the tools' aliases and a default per harness
  claude: {opus: claude-opus-5-5, sonnet: claude-sonnet-5-5, haiku: claude-haiku-5-5, default: claude-opus-5-5}
  codex: {default: gpt-5.5}
  opencode: {default: claude-sonnet-5-5}
codex_wire: responses                   # optional: chat for a server without the Responses API
opencode_openai_npm: '@ai-sdk/openai'   # optional: '@ai-sdk/openai-compatible' for a server that takes max_tokens (llama.cpp)
provided_by: {task: run-llama-cpp-server, params: {port: 8686}}   # optional: the task that starts a local server
```

```
cx ai.gateway ls                                      # alias, base URL, wires, auth, repository
cx ai.gateway models dapple --harness=claude          # what Claude Code can use there (the anthropic wire's catalog)
cx ai.gateway models dapple --harness=codex           # the openai wire: every model the gateway serves on it
cx ai.gateway test dapple                             # hello on every wire, the usage reported, the catalog's size
cx ai.gateway connect dapple --harness=codex          # the environment names and the words a harness needs (no value)
```

The wire each harness speaks: Claude Code the Anthropic Messages API only (a GPT name on that wire is "unknown
model"); Codex the Responses API (`codex_wire: chat` for a chat-only server); OpenCode both, through its provider
packages. A gateway that translates (Dapple's Responses route takes Claude models too) shows them in the openai wire's
catalog, and Codex can use them - with prompts tuned for GPT. A llama.cpp server (the builds since 2026-10-16) speaks
all three wires, so every harness can use it; vLLM speaks chat and Responses.

`connect` (and so `set-ai-gateway` and every harness run) fails with the URL and the start command when the gateway's
catalog does not answer - a harness is never started towards a dead gateway, where OpenCode could fall back to a
provider it is logged into. A gateway without a `catalog` is not probed.

The key: `auth.secret` names a `secret` artifact of kind `token` (`files/token`, or `env: NAME`); it lives in a
repository of secrets (never synced) and reaches another machine by name only: `cx host push <host> <secrets
repository> --artifacts="secret::<alias>" --secrets`. `connect` returns the value inside `env` for the harness task
that starts the tool; nothing prints it, and `set-ai-gateway` is never cached. A gateway with `auth.header: none`
(a local server) needs no secret.

Costs: the gateway answers carry the vendor's usage block; Claude Code reports its own cost line; run-ai records the
gateway of every run beside the harness, the model and the effort. A monthly budget shows itself as a 403.
