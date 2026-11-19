# ai.gateway - where the AI harnesses get their models

An artifact of this category is one place that serves models: a company's gateway (Azure API Management in front of
OpenAI and Anthropic), a vendor's own API, a llama.cpp or vLLM server on this machine or on a host. It names the base
URL, the wires the place speaks, the catalog of its models, how the key travels and WHICH secret holds it - never a
value. The harness tasks reach it through `set-ai-gateway` (`--gateway=<alias>`, `-gw`, `-ln`, the config keys): the
same Claude Code, Codex or OpenCode, the bill moved to the gateway's credits, or a local model.

```yaml
# ai.gateway/<alias>/_desc.yaml
description: the company gateway
base_url: https://acme-llm-gateway.azure-api.net
wires:                                  # what it speaks, each with its path under base_url
  anthropic: /anthropic                 #   the Messages API (/v1/messages under it) - Claude Code; '' = right under the base
  openai: /openai/v1                    #   chat completions and the Responses API - Codex, OpenCode
catalog: /v1/models                     # the list of usable models; catalogs: {anthropic: /anthropic/v1/models} per wire
auth:
  header: x-api-key                     # x-api-key | bearer | none | login (the harness's own account: "A pass-through")
  secret: acme-ai-gateway              # the secret artifact (kind token) that holds the key - cx secret ls
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
cx ai.gateway models acme --harness=claude          # what Claude Code can use there (the anthropic wire's catalog)
cx ai.gateway models acme --harness=codex            # the openai wire: every model the gateway serves on it
cx ai.gateway test acme                               # hello on every wire, the usage reported, the catalog's size
cx ai.gateway connect acme --harness=codex           # the environment names and the words a harness needs (no value)
cx ai.gateway default                                 # this machine's default gateway for the harness runs
cx ai.gateway default acme                            # ... set (--harness=codex: Codex's own, where it has one)
cx ai.gateway default --unset                         # ... removed: the tools run on their own logins
cx ai.gateway pick --harness=claude                   # the gateways Claude Code can use, numbered, and a question: which one
```

The default lives in `config::default` (`run_ai_gateway`, `run_ai_gateway_name`, and `run_ai_gateway_<harness>` for a
harness that has its own): `default` writes those keys and nothing else. A run takes it only when nothing closer
says otherwise - a flag, what its project ran with last, what its project declares. `--unset` never removes a key
that pins a harness to its login. `pick` is for a person at a terminal: a run nobody watches names its gateway.

The wire each harness speaks: Claude Code the Anthropic Messages API only (a GPT name on that wire is "unknown
model"); Codex the Responses API (`codex_wire: chat` for a chat-only server); OpenCode both, through its provider
packages. A gateway that translates (a Responses route that takes Claude models too) shows them in the openai wire's
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

## A pass-through: `upstream` and `auth.header: login`

A pass-through is a server between a harness and the place its requests go to - one that logs them, counts their
tokens or forwards them - and it is an artifact like any other: its `base_url` is the server's own address. Two keys
say the rest.

```yaml
# a company's gateway through a server of this machine: the same key, the same gateway, the same bill
base_url: http://127.0.0.1:8401/local-acme
upstream: acme                          # the gateway its traffic goes to
provided_by: {task: <the task that starts the server>, params: {port: 8401}}

# each harness's own login through that server: the same account, the vendor's own address behind it
base_url: http://127.0.0.1:8401/local-login
upstream: {anthropic: 'https://api.anthropic.com', openai: 'https://chatgpt.com/backend-api/codex'}
wires: {anthropic: /anthropic, openai: /openai}
auth: {header: login}                   # no key, no secret: the harness sends its own login
provided_by: {task: <the task that starts the server>, params: {port: 8401}}
```

- **`upstream`** says where the traffic goes: another gateway's alias, an address, or an address per wire. It is the
  server's to read. Given as an alias, it also saves repeating that gateway: what the pass-through does not say
  itself - `wires`, `catalog`, `catalogs`, `auth`, `models`, `codex_wire`, `opencode_openai_npm` - is taken from it,
  so a model name or a secret's name changes in one place. Only one step is followed.
- **`auth.header: login`** says the harness keeps its own account and only the address changes. `connect` then reads
  no secret and sets nothing of a key: Claude Code gets the address alone (no key variable, no helper, no settings -
  the session stays a login session), Codex a provider that asks for its own login (`requires_openai_auth`). Who pays
  is the harness's own account, as with `-ln`. The run is marked `own_login`, and the harness tasks clean the
  environment as they do for a login run: a key of the user's own would otherwise go in the login's place. Claude
  Code and Codex have a recipe; another harness is told so. `test` has no login to send and says so.
- A pass-through that names the task providing it and has no catalog to read (a login's has none) must at least
  accept a connection: `connect` fails with the start command when nothing listens at its address.

## Which run a request comes from: `run_header`

A server of one's own between a harness and its models - a pass-through that keeps a line per request, a local model
server - can be told which cMeta artifact and conversation each request comes from, so that what it records can be
put beside the session it belongs to. The artifact names the header it wants:

```yaml
run_header: x-cmeta-run                 # letters, digits and "-"
```

run-ai puts the run into the variable `CMETA_AI_RUN` - `project=<cRef>;conversation=<id>;run=<stamp>`, each value
percent-encoded - and `connect` has the harness send it in that header with every request: Claude Code through
`ANTHROPIC_CUSTOM_HEADERS`, Codex through its provider's `env_http_headers` (the variable's name, never its value, on
the command line), OpenCode through its provider's `headers`. A gateway without `run_header` - a company's, a
vendor's - is never sent it, and outside run-ai (no `CMETA_AI_RUN`) nothing is sent. The server should take the header
out of what it passes on.
