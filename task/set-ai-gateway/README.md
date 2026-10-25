# set-ai-gateway - login or a gateway for an AI harness

The dependency of `run-claude`, `run-codex`, `run-opencode` and `run-ai`: which way a harness reaches its models - the
tool's own account (a Claude subscription, a ChatGPT login: `login`) or an `ai.gateway` artifact (a company's gateway,
a vendor's API key, a llama.cpp or vLLM server) - and, for a gateway, what the harness needs: the environment, the
extra command-line words, the model to pass when the user named none. The choice, in order:

1. the flag: `--gateway=<alias>` (`-gw=<alias>`), a bare `-gw` = the configured gateway, `-ln` = login;
2. the project's `_desc.yaml`: `ai_gateway: <alias> | login` (run-ai reads it: a Dapple work item says `dapple`, a task
   that needs the claude.ai connectors says `login`);
3. this machine's `config::default`: `run_ai_gateway_<harness>: login | <alias>` (per harness), else `run_ai_gateway:
   true` with `run_ai_gateway_name: <alias>`;
4. `login`.

```
cx task run set-ai-gateway --harness=claude                       # the choice, and the environment it means
cx task run set-ai-gateway --harness=codex -gw                    # the configured gateway
cx task run set-ai-gateway --harness=opencode --gateway=llama-cpp-local --connect-   # the choice only

cx config set default --meta.run_ai_gateway=true --meta.run_ai_gateway_name=dapple   # the gateway by default
cx config set default --meta.run_ai_gateway_codex=login                              # except Codex
```

The result: `gateway` (the alias or `login`), `how`, and for a gateway `env` (the variables, the key included - the
task is never cached, the result is for the harness task only), `args` (Codex's `-c` provider words), `model`,
`wire`, `opencode_config` (a provider block to merge into `OPENCODE_CONFIG_CONTENT`), `notes` (Claude Code on an API
key has no claude.ai connectors). The harness tasks put `env` into the environment of the tool they start and add
`args` to its command line; run-ai records the gateway of every run. With `login` the result is the choice alone and
the harness runs exactly as before.
