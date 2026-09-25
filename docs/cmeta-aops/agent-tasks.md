<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
-->

# Coding agents and cloud CLIs as tasks

How to launch **Claude Code**, **OpenAI Codex**, **OpenCode.AI** and the **Azure CLI**
through cMeta, so that the same command works on every machine, the agent starts
with the right context, and a headless run leaves a transcript and its token
statistics next to the prompt file.

| Artifact | What it does |
|---|---|
| [`tool/claude`](../../tool/claude/_desc.yaml), [`tool/codex`](../../tool/codex/_desc.yaml), [`tool/opencode`](../../tool/opencode/_desc.yaml) | Detect or install the three agent CLIs, pin a release, list the published versions. |
| [`task/run-claude`](../../task/run-claude/_desc.yaml) | Open Claude Code interactively; everything after `--` goes straight to it. |
| [`task/run-claude2`](../../task/run-claude2/_desc.yaml), [`task/run-codex2`](../../task/run-codex2/_desc.yaml), [`task/run-opencode2`](../../task/run-opencode2/_desc.yaml) | Run an agent on an assembled prompt — headless or interactive — and record the output and the token statistics. `run-claude2` also adds cMeta repositories to the agent's context. |
| [`tool/az`](../../tool/az/_desc.yaml), [`task/run-az`](../../task/run-az/_desc.yaml) | Detect or install the Azure CLI and run it with the terminal attached (`az login` works). |

The three `run-*2` tasks share one design: the prompt is the text of
`--prompt_file` (when given), then a new line, then `--prompt`; the full output is
streamed to the console and recorded into `<prompt_file without extension>-output.txt`
unless `--output_file` says otherwise; with no prompt at all the task opens an
interactive session instead of failing. Their `_desc.yaml` files carry the full
per-agent reasoning (which CLI flags implement `--yes`, `--reproducible`, `--stats`).

## Claude Code — `task/run-claude2`

Uses `tool/claude`; see [Which model, which effort](#which-model-which-reasoning-effort)
for `--model` / `--effort`.

```bash
cx task run run-claude2                                      # open an interactive session
cx task run run-claude2 --prompt="explain this repo"          # headless, one prompt
cx task run run-claude2 --prompt_file=review.txt --yes --stats
cx task run run-claude2 --prompt_file=review.txt --interactive
cx task run run-claude2 --prompt="fix the tests" -- --model opus --effort xhigh
```

## OpenAI Codex — `task/run-codex2`

Uses `tool/codex`.

```bash
cx task run run-codex2                                       # open an interactive session
cx task run run-codex2 --prompt="explain this repo"           # headless, one prompt
cx task run run-codex2 --prompt_file=review.txt --yes --stats
cx task run run-codex2 --prompt="fix the tests" -- -m gpt-5.6-sol -c model_reasoning_effort="xhigh"
```

## OpenCode.AI — `tool/opencode` + `task/run-opencode2`

```bash
cx tool setup opencode --install        # detect or install the CLI
cx tool run opencode -- --version       # 1.18.19
cx tool setup opencode --versions       # every published release

cx task run run-opencode2                                    # open an interactive session
cx task run run-opencode2 --prompt="explain this repo"        # headless, one prompt
cx task run run-opencode2 --prompt_file=review.txt --yes --stats
cx task run run-opencode2 --prompt_file=review.txt --interactive
cx task run run-opencode2 --prompt="fix the tests" -- -m anthropic/claude-opus-5 --variant high
```

## Azure CLI — `tool/az` + `task/run-az`

```bash
cx tool setup az --install               # detect or install the CLI
cx tool run az -- --version              # azure-cli 2.89.1
cx tool setup az --versions              # every published release
cx tool setup az --version=2.88.0 --install

cx task run run-az -- login                          # interactive; the terminal stays attached
cx task run run-az -- account show
cx task run run-az -- group list --output table
cx task run run-az --install -- --version            # bring the CLI up unattended (CI/agents)
cx task run run-az --version=2.88.0 -- --version     # pin a release
```

`az` is a Python application rather than a single static binary, so `tool/az` takes
the highest rung of the install ladder each platform actually offers — the comments
in its `_desc.yaml` and `api_v1.py` carry the full reasoning:

| OS | How it installs | Notes |
|---|---|---|
| **Windows** | **Download** — the official x64 ZIP, unpacked into the cMeta cache | Self-contained (bundles its own `python.exe`), needs no admin rights, pins an exact version. Falls back to `winget`. |
| **macOS** | **Download** — the official `macos` tarball from the GitHub release | Relocatable, but *not* self-contained: the upstream launcher demands `AZ_PYTHON`, so a small `bin/az` wrapper supplies it. Falls back to `brew` when the host has no matching CPython. |
| **Linux** | Package manager | Upstream publishes **no** portable download (the `.deb`/`.rpm` bundle a venv wired to `/opt/az`). apt-based distros get the Microsoft repo script — plain `apt install azure-cli` fails on stock Debian/Ubuntu — everything else the generic sudo package manager. |

## Flags shared by `run-claude2` / `run-codex2` / `run-opencode2`

| Flag | Effect |
|---|---|
| `--prompt="…"` / `--prompt_file=<file>` | The prompt: file text, then `\n`, then `--prompt` text. |
| *(none of the above)* | **Opens an interactive session** instead of failing. |
| `--interactive`, `--i`, `-i` | Preload the prompt, then keep the terminal (follow up by hand). |
| `--yes` | Run unattended (auto-approve every permission question). |
| `--add_repos=<alias,alias>` (`run-claude2`) | cMeta repositories added to the agent's context as `--add-dir <path>`, resolved on this machine — see [the next section](#repositories-in-the-agents-context-run-claude2). `none` adds nothing at all. |
| `--reproducible` | Strip the per-machine parts of the session. Never fully deterministic — pin the model too. |
| `--stats` / `--stats_file=<file>` | Token counters + cost of this prompt (via the agent's JSON event stream). |
| `--output_file=<file>` | Where to record the transcript (default: `<prompt_file>-output.txt`). |
| `--skip_output_file`, `--append_output_file`, `--skip_output_header` | Output-file tweaks. |
| `-- <extra flags>` | Everything after `--` is appended to the agent's own command line. |

An interactive session owns the terminal, so `--stats`, `--stats_file` and
`--output_file` are switched off there, and a non-zero exit code is reported but
does not fail the task (quitting a session is normal).

## Repositories in the agent's context (`run-claude2`)

Claude Code reads the `CLAUDE.md`, `AGENTS.md` and the skills under `.claude/skills/`
of every directory it is given with `--add-dir`. `run-claude2` builds those flags
from **repository aliases**, resolving each path on the current machine through
cMeta's own registry (`cx repo find`) — so the same command works everywhere, and
nobody has to build the path with a shell substitution by hand.

What is added, in this order and without duplicates:

1. **The repository this task lives in** — the first `_cmr.yaml` above the task
   folder, i.e. `cmeta-aops` here (its `AGENTS.md`, `CLAUDE.md` and skills).
2. **The aliases in the `agent_add_repos` key of the local cMeta config** — a
   comma-separated string or a list. Set it once per machine and your own
   repositories are in context on every launch, with no flag to remember:

   ```bash
   cx config set default --meta.agent_add_repos=myorg@my-knowledge-repo,myorg@other-repo
   cx config show default                         # check
   ```
3. **`--add_repos=<alias,alias>`** for this launch only. A repository that is not
   plugged in (`cx repo list`) is reported and skipped.

`--add_repos=none` adds nothing, not even the defaults. A path that was already
passed after `--` as `--add-dir <path>` is never added twice.

## How the artifacts of a session record who made them (`run-claude2`)

`run-claude2` sets `CMETA_GENERATOR` for the claude process, unless a task that runs claude
has set it already:

```json
{"method": "agent", "agent": "Claude Code 2.1.282", "model": "<--model>", "effort": "<--effort>"}
```

The model and effort are recorded when they are passed after `--`; otherwise the thinking
budget, if `MAX_THINKING_TOKENS` is set. A model switched inside an interactive session is not
seen. cMeta writes the record as `generator` into each artifact claude creates through `cx`,
and as `last_generator` (with the date) into each one it updates - see the engine's
`docs/using-cmeta.md` §7.6 (`artifact_defaults` of `_cmr.yaml`, `CMETA_GENERATOR`).

## Which model, which reasoning effort

Which model an agent uses is **not** a cMeta setting — it is passed straight
through to the agent CLI after `--`. Cost and speed below are relative within
each agent's own line-up; the exact per-token price only applies when the agent
is authenticated with an **API key**. Under a subscription login (Claude Max,
a ChatGPT plan, or OpenCode's bundled provider) the marginal token cost is zero
and the limit is a rate limit, not a bill.

> Verified on **2026-08-21** with `claude` 2.1.238, `codex` 0.148.0 and
> `opencode` 1.18.19. Model line-ups move fast — re-check with `/model` (claude,
> codex) or `opencode models` before trusting a table.

### `run-claude2` → Claude Code

Pass the model and the reasoning effort as CLI flags:

```bash
cx task run run-claude2 --prompt="…" -- --model opus --effort xhigh
```

`--model` takes an alias (`fable`, `opus`, `sonnet`, `haiku`) or a full name
(`claude-opus-5`). `--effort` takes `low`, `medium`, `high`, `xhigh`, `max`
(`xhigh` is the Claude Code default and the sweet spot for coding/agentic work;
`max` when correctness matters more than cost; `low` for subagents and simple
mechanical work).

| Model | Strength | Cost (API, in/out per MTok) | Speed | Reasoning effort |
|---|---|---|---|---|
| `claude-fable-5` (`fable`) | Most capable — hardest reasoning and long-horizon agentic runs | $10 / $50 | Slowest (hard tasks can run many minutes) | Always thinking; `low` … `max` |
| `claude-opus-5` (`opus`) | **Default pick** — strongest general coding + agentic work | $5 / $25 | Medium | `low` … `max`, thinking on by default |
| `claude-sonnet-5` (`sonnet`) | Strong workhorse at ~⅔ the price | $3 / $15 (intro $2 / $10 through 2026-08-31) | Fast | `low` … `max` |
| `claude-haiku-4-5` (`haiku`) | Light, mechanical, high-volume work (200K context) | $1 / $5 | Fastest | Not supported (effort is an Opus/Sonnet-5-generation feature) |
| `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6` | Previous generations, still selectable | same as their tier | — | `low` … `max` (4.6: no `xhigh`) |

Context window is 1M on everything except Haiku 4.5 (200K). For
`--reproducible`, pin an **exact** version (`--model claude-haiku-4-5-20251001`)
— an alias moves to another model over time.

### `run-codex2` → OpenAI Codex

Codex takes the model with `-m` and the reasoning effort through a config
override:

```bash
cx task run run-codex2 --prompt="…" -- -m gpt-5.6-sol -c model_reasoning_effort="xhigh"
```

| Model | Strength | Cost | Speed | Reasoning effort |
|---|---|---|---|---|
| `gpt-5.6-sol` | **Default pick** — complex code changes, research, long ambitious work | $$$ | Medium; *"highly capable at lower reasoning efforts"* — start low, turn it up | `low`/`medium`/`high`/`xhigh` |
| `gpt-5.6-terra` | Mid tier, the successor to `gpt-5.4` | $$ | Fast | `low` … `xhigh` |
| `gpt-5.6-luna` | Light tier, the successor to `gpt-5.4-mini` | $ | Fastest | `low` … `xhigh` |
| `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.2` | Previous generations; Codex nudges 5.4/5.4-mini users to Terra/Luna | — | — | `low` … `xhigh` |

`xhigh` is *"maximum reasoning depth for the hardest problems"*. Codex has no
`--effort` flag — it is always `-c model_reasoning_effort="…"` (or `/model` in
the TUI).

### `run-opencode2` → OpenCode.AI

OpenCode is provider-agnostic: a model is `provider/model`, and the reasoning
effort is a provider-specific **variant**:

```bash
cx task run run-opencode2 --prompt="…" -- -m anthropic/claude-opus-5 --variant high
cx task run run-opencode2 --prompt="…" -- -m openai/gpt-5.6-sol --variant xhigh
```

| Provider | Reach it with | `--variant` values (reasoning effort) |
|---|---|---|
| `anthropic/*` | `opencode auth login` → Anthropic (Claude Pro/Max or an API key) | `high`, `max` |
| `openai/*` | `opencode auth login` → OpenAI | `none`, `minimal`, `low`, `medium`, `high`, `xhigh` |
| `opencode/*` | Bundled, no login needed | provider-dependent |
| 75+ others (Google, local Ollama/LM Studio, …) | `opencode auth login`, see <https://models.dev> | provider-dependent |

`opencode models` lists exactly what the current login can reach. **With no
credentials configured** it is only the bundled free tier — rotating
preview/community models, capability varies, treat them as experimental and
rate-limited, not as a baseline for real work:

| Model | Cost | Notes |
|---|---|---|
| `opencode/big-pickle`, `opencode/hy3-free`, `opencode/mimo-v2.5-free`, `opencode/muse-spark-1.2-contributor-free`, `opencode/nemotron-3-ultra-free`, `opencode/nemotron-3.5-lightning-free`, `opencode/x-preview-f-free` | Free (rate-limited) | Preview/community models that come and go with releases. Verify with `opencode models`. |

Once Anthropic or OpenAI is authenticated, the tables in the two sections above
apply unchanged — same models, same strength/cost/speed, with the effort level
expressed as `--variant` instead of `--effort` / `model_reasoning_effort`.

## Gotchas

- **`opencode run` has no stdin mode.** Unlike `claude -p` and `codex exec -`,
  the prompt always travels as a command line argument — in both interactive and
  headless mode. The OS caps a command line (~32K chars on Windows, ~2MB of argv
  on Linux), so `run-opencode2` warns above 30K chars. Use `run-claude2` or
  `run-codex2` for a very long prompt file.
- **Windows installs `opencode` through winget** (`SST.opencode`), because
  upstream publishes no `.cmd`/`.ps1` installer — `https://opencode.ai/install.ps1`
  is a 404. Linux/macOS use the official install script, which drops a prebuilt
  binary into `~/.opencode/bin` and pins an exact version with
  `--version X.Y.Z`.
- **OpenCode's JSON event schema is not frozen.** `run-opencode2` walks the
  events for text/tool-calls/usage instead of hard-coding one shape, and passes
  anything it cannot recognize through unchanged — so a schema change degrades
  the `--stats` output rather than losing the transcript.
- **These tasks are never cached** (`cache: False` in every `_desc.yaml`): they
  launch a live agent or talk to live cloud resources, so memoizing a run on disk
  would make no sense.
