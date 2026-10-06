<!--
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. Licensed under Apache-2.0 (see LICENSE).
-->

# Coding agents and cloud CLIs as tasks

How to launch **Claude Code**, **OpenAI Codex**, **OpenCode.AI**, Google's
**Antigravity CLI** and **Gemini CLI**, and the **Azure CLI** through cMeta, so that
the same command works on every machine, the agent starts with the right context,
and a headless run leaves a transcript and its token statistics next to the prompt
file - and, with **`run-ai`**, how to run any of these agents on a cMeta artifact so
that its memory, skills and conversations stay inside that artifact.

| Artifact | What it does |
|---|---|
| [`task/run-ai`](../../task/run-ai/README.md), [`task/import-ai`](../../task/import-ai/_desc.yaml) | One front door to the agents below, on a cMeta artifact: the agent's memory, skills, logs and conversations are kept in the artifact's `!AI` folder, a run continues the last conversation with any agent and model, and other artifacts' memory is read-only context. `import-ai` brings existing memories and skills in. |
| [`tool/claude`](../../tool/claude/_desc.yaml), [`tool/codex`](../../tool/codex/_desc.yaml), [`tool/opencode`](../../tool/opencode/_desc.yaml), [`tool/agy`](../../tool/agy/_desc.yaml), [`tool/gemini`](../../tool/gemini/_desc.yaml) | Detect or install the agent CLIs, pin a release, list the published versions. |
| [`task/run-claude`](../../task/run-claude/_desc.yaml), [`task/run-codex`](../../task/run-codex/_desc.yaml), [`task/run-opencode`](../../task/run-opencode/_desc.yaml), [`task/run-agy`](../../task/run-agy/_desc.yaml), [`task/run-gemini`](../../task/run-gemini/_desc.yaml) | Run an agent on an assembled prompt — headless or interactive — and record the output and the token statistics. `run-claude` also adds cMeta repositories to the agent's context. |
| [`tool/az`](../../tool/az/_desc.yaml), [`task/run-az`](../../task/run-az/_desc.yaml) | Detect or install the Azure CLI and run it with the terminal attached (`az login` works). |

The `run-<agent>` tasks share one design: the prompt is the text of
`--prompt_file` (when given), then a new line, then `--prompt`; the full output is
streamed to the console and recorded into `<prompt_file without extension>-output.txt`
unless `--output_file` says otherwise; with no prompt at all the task opens an
interactive session instead of failing. Their `_desc.yaml` files carry the full
per-agent reasoning (which CLI flags implement `--yes`, `--reproducible`, `--stats`).

## One front door, with the memory in the project — `task/run-ai`

`run-ai` runs any of the agents on this page **on a cMeta artifact** and keeps what
the agent learns and produces inside that artifact, in a folder named `!AI`: its
memory, its skills, the log and the token counts of every run, and the
conversations. The knowledge travels with the project - another folder, another
machine, an archive - and nothing has to be installed in the user's home.

```bash
cxt run-ai                                           # continue the latest conversation of the artifact around the current directory
cxt run-ai "one prompt"                              # one more turn of it, then exit
cxt run-ai --project="project::my-app" -i            # the artifact named explicitly (category::artifact)
cxt run-ai --harness=codex --model=gpt-6.1-sol,high  # the same conversation with another agent: the transcript is handed over
cxt run-ai --new "..."                               # a new conversation; --conversations lists them
cxt run-ai --summarize                               # a summary of the latest conversation, read first at the next hand-over
cxt run-ai -w "..."                                  # no questions, write anywhere (--write=all); --write=project|none; the config sets the default
cxt run-ai --list_models                             # the models and efforts of every agent, ready to copy
cxt run-ai --dry_run                                 # everything that would be given to the agent; nothing runs
cxt import-ai --project="project::my-app" --skills="<repo>/.claude/skills"   # bring memories and skills into !AI
```

(`cxt <task>` is short for `cx task run <task>`.)

- **The agent** (`--harness`): `claude` (the default), `codex`, `opencode`, `openclaw`,
  `antigravity` (also `agy`), `gemini`, or any `<x>` for which a task `run-<x>` exists.
  The model and the effort are given in the agent's own names -
  `--model=<model>,<effort>` - and turned into its flags from
  `tool/<agent>/_desc_models.yaml`.
- **The project:** `--project=<cref>`, else the artifact the current directory is in,
  else the current directory. The agent works in the artifact's root folder.
- **Memory and skills:** Claude Code reads and writes `!AI/memory` (its
  `autoMemoryDirectory` is set for the run) and loads `!AI/skills` as a plugin; the
  other agents are given the memory index and the list of skills, and write there by
  the convention they are told. Codex keeps its threads in `!AI/codex`.
- **Conversations:** a run continues the conversation with the latest activity
  through the agent's own session (`claude --resume`, `codex resume`, ...). When the
  agent changes, the new one is handed the transcript `!AI/log/<id>.transcript.md`,
  which is rewritten after every run.
- **Context from other artifacts:** `ai_uses` in the artifact's `_desc.yaml` (or in
  its repository's `_cmr.yaml`, for all its artifacts) names the artifacts whose memory
  and skills the sessions read; `--context=<cref>;<cref>` adds some for one run. Those
  stay read-only for a run: a session proposes a change under `!AI/pending`, and
  `cxt run-ai --apply_pending` shows each difference and applies it on your word.
- **Git:** `run-ai` never runs git. This repository ignores `!AI` (the `.gitignore`
  line is `\!AI/`, since a leading `!` negates); in a repository of your own, commit
  it or ignore it.

The full reference - every flag, the layout of `!AI`, what each agent is given, the
proposals and the guard, the settings - is
[`task/run-ai/README.md`](../../task/run-ai/README.md).

## Claude Code — `task/run-claude`

Uses `tool/claude`; see [Which model, which effort](#which-model-which-reasoning-effort)
for `--model` / `--effort`.

```bash
cx task run run-claude                                      # open an interactive session
cx task run run-claude --prompt="explain this repo"          # headless, one prompt
cx task run run-claude --prompt_file=review.txt --yes --stats
cx task run run-claude --prompt_file=review.txt --interactive
cx task run run-claude --prompt="fix the tests" -- --model opus --effort xhigh
```

## OpenAI Codex — `task/run-codex`

Uses `tool/codex`.

```bash
cx task run run-codex                                       # open an interactive session
cx task run run-codex --prompt="explain this repo"           # headless, one prompt
cx task run run-codex --prompt_file=review.txt --yes --stats
cx task run run-codex --prompt="fix the tests" -- -m gpt-5.6-sol -c model_reasoning_effort="xhigh"
```

## OpenCode.AI — `tool/opencode` + `task/run-opencode`

```bash
cx tool setup opencode --install        # detect or install the CLI
cx tool run opencode -- --version       # 1.18.19
cx tool setup opencode --versions       # every published release

cx task run run-opencode                                    # open an interactive session
cx task run run-opencode --prompt="explain this repo"        # headless, one prompt
cx task run run-opencode --prompt_file=review.txt --yes --stats
cx task run run-opencode --prompt_file=review.txt --interactive
cx task run run-opencode --prompt="fix the tests" -- -m anthropic/claude-opus-5 --variant high
```

## Google Antigravity CLI — `tool/agy` + `task/run-agy`

Antigravity CLI (`agy`) is Google's terminal coding agent for **personal Google
accounts** (free, Google AI Pro, Google AI Ultra), which Gemini CLI no longer serves.

```bash
cx tool setup agy --install             # the release binary from GitHub, into the cMeta cache
cx tool run agy                         # sign in once (the browser opens), then /quit
cx tool run agy -- --version
cx tool run agy -- models               # what the signed-in account can use

cx task run run-agy                                         # open an interactive session
cx task run run-agy --prompt="explain this repo"             # headless, one prompt
cx task run run-agy --prompt_file=review.txt --yes --stats
cx task run run-agy --prompt="fix the tests" -- --model gemini-3.1-pro-high
```

The effort is part of the model name here (`gemini-3.8-flash-high`,
`gemini-3.1-pro-low`); `tool/agy/_desc_models.yaml` has the list. Sign in **before**
the first headless run: without a stored login a headless `agy` prints the login
URL, may open it in the browser, waits and fails, and `run-agy` then stops with a
sign-in hint. The binary is kept in the cMeta cache and is not put on `PATH`;
`run-agy` switches its self-update off for the run.

## Google Gemini CLI — `tool/gemini` + `task/run-gemini`

Gemini CLI serves **Gemini Code Assist Standard/Enterprise licences, paid API keys
(`GEMINI_API_KEY`) and Vertex AI**. Since 2026-06-18 it refuses personal Google
accounts - use Antigravity CLI above for those.

```bash
cx tool setup gemini --install          # the release bundle from GitHub, run through Node.js (itself a cMeta tool)
cx tool run gemini                      # sign in once - or set GEMINI_API_KEY instead
cx tool run gemini -- --version

cx task run run-gemini                                       # open an interactive session
cx task run run-gemini --prompt="explain this repo"           # headless, one prompt
cx task run run-gemini --prompt_file=review.txt --yes --stats
cx task run run-gemini --prompt="fix the tests" -- --model gemini-3.1-pro-preview
```

A headless run trusts the current folder for that run (`--skip-trust`) and never
opens a browser (`NO_BROWSER=true`). Without a usable login it fails with a hint
that names the case: nothing configured, a personal account that is refused, or a
key the API does not accept. Gemini CLI has no reasoning-effort flag: the default
model, `auto`, routes between a Pro and a Flash model.

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

## Flags shared by `run-claude` / `run-codex` / `run-opencode` / `run-agy` / `run-gemini`

| Flag | Effect |
|---|---|
| `--prompt="…"` / `--prompt_file=<file>` | The prompt: file text, then `\n`, then `--prompt` text. |
| *(none of the above)* | **Opens an interactive session** instead of failing. |
| `--interactive`, `--i`, `-i` | Preload the prompt, then keep the terminal (follow up by hand). |
| `--yes` | Run unattended (auto-approve every permission question). |
| `--add_repos=<alias,alias>` (`run-claude`) | cMeta repositories added to the agent's context as `--add-dir <path>`, resolved on this machine — see [the next section](#repositories-in-the-agents-context-run-claude). `none` adds nothing at all. |
| `--reproducible` | Strip the per-machine parts of the session. Never fully deterministic — pin the model too. |
| `--stats` / `--stats_file=<file>` | Token counters + cost of this prompt (via the agent's JSON event stream). |
| `--output_file=<file>` | Where to record the transcript (default: `<prompt_file>-output.txt`). |
| `--skip_output_file`, `--append_output_file`, `--skip_output_header` | Output-file tweaks. |
| `-- <extra flags>` | Everything after `--` is appended to the agent's own command line. |

An interactive session owns the terminal, so `--stats`, `--stats_file` and
`--output_file` are switched off there, and a non-zero exit code is reported but
does not fail the task (quitting a session is normal).

## Repositories in the agent's context (`run-claude`)

Claude Code reads the `CLAUDE.md`, `AGENTS.md` and the skills under `.claude/skills/`
of every directory it is given with `--add-dir`. `run-claude` builds those flags
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

## How the artifacts of a session record who made them

`run-claude`, `run-codex`, `run-opencode`, `run-agy` and `run-gemini` set
`CMETA_GENERATOR` for the agent process, unless a task that runs the agent has set it already (an import task keeps its
own `task` record):

```json
{"method": "agent", "agent": "Claude Code 2.1.282", "model": "<model>", "effort": "<effort>"}
```

| Task | `agent` | `model` from | `effort` from |
|---|---|---|---|
| `run-claude` | `Claude Code <version>` | `--model` | `--effort`; else `thinking_budget` = `MAX_THINKING_TOKENS` |
| `run-codex` | `OpenAI Codex <version>` | `-m` / `--model` | `-c model_reasoning_effort=...` |
| `run-opencode` | `OpenCode <version>` | `--model` / `-m` | `--variant` |
| `run-agy` | `Antigravity CLI <version>` | `--model` | `--effort` |
| `run-gemini` | `Gemini CLI <version>` | `--model` / `-m` | - (no effort flag) |

The model and effort are recorded only when they are passed after `--` (`run-ai` passes its
`--model` and `--effort` that way): a model or effort chosen in the agent's own config file, or
switched inside an interactive session, is not seen.
cMeta writes the record as `generator` into each artifact the agent creates through `cx`, and as
`last_generator` (with the date) into each one it updates - see the engine's
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
>
> **The maintained list is `tool/<name>/_desc_models.yaml`** (`tool/claude`, `tool/codex`,
> `tool/opencode`, `tool/openclaw`, `tool/agy`, `tool/gemini`; since 2026-10-04) -
> `cxt run-ai --list_models` prints it, one `--model=<model>,<effort>` line per
> combination: the models with a description,
> context, price and the efforts each takes, the harness's flags for a model and an
> effort, and the bookkeeping (`updated`, `checked_with`, `sources`). Retired models stay
> with `disabled: true`, so that a `generator.model` of an old artifact can still be read.
> `run-ai` reads it for its `--model=<model>,<effort>`; the tables below are the snapshot
> of 2026-08-21.

### `run-claude` → Claude Code

Pass the model and the reasoning effort as CLI flags:

```bash
cx task run run-claude --prompt="…" -- --model opus --effort xhigh
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

### `run-codex` → OpenAI Codex

Codex takes the model with `-m` and the reasoning effort through a config
override:

```bash
cx task run run-codex --prompt="…" -- -m gpt-5.6-sol -c model_reasoning_effort="xhigh"
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

### `run-opencode` → OpenCode.AI

OpenCode is provider-agnostic: a model is `provider/model`, and the reasoning
effort is a provider-specific **variant**:

```bash
cx task run run-opencode --prompt="…" -- -m anthropic/claude-opus-5 --variant high
cx task run run-opencode --prompt="…" -- -m openai/gpt-5.6-sol --variant xhigh
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
  on Linux), so `run-opencode` warns above 30K chars. Use `run-claude` or
  `run-codex` for a very long prompt file.
- **Windows installs `opencode` through winget** (`SST.opencode`), because
  upstream publishes no `.cmd`/`.ps1` installer — `https://opencode.ai/install.ps1`
  is a 404. Linux/macOS use the official install script, which drops a prebuilt
  binary into `~/.opencode/bin` and pins an exact version with
  `--version X.Y.Z`.
- **OpenCode's JSON event schema is not frozen.** `run-opencode` walks the
  events for text/tool-calls/usage instead of hard-coding one shape, and passes
  anything it cannot recognize through unchanged — so a schema change degrades
  the `--stats` output rather than losing the transcript.
- **These tasks are never cached** (`cache: False` in every `_desc.yaml`): they
  launch a live agent or talk to live cloud resources, so memoizing a run on disk
  would make no sense.
