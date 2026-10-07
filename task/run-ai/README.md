# `task::run-ai` - one front door to the coding-agent harnesses, with the memory, skills and conversations kept in the project

`run-ai` runs a coding agent **on a cMeta artifact** through a **harness** (`--harness`: the CLI that runs the model -
Claude Code by default; Codex, OpenCode, OpenClaw, Google's Antigravity CLI and Gemini CLI, Nous Research's Hermes
Agent, or any `run-<harness>` task), and keeps
everything the agent learns and produces inside that artifact, in a folder named `!AI`: the memory, the skills, the
logs, the token use and the **conversations**. A run continues where the last one stopped, with any harness and any
model; `--new` starts afresh. The knowledge travels with the project - another folder, another machine, an archive -
with no path in the way and nothing to install in the user's home.

```bash
cxt run-ai                                           # continue the latest conversation of the project around the cwd, interactively
cxt run-ai "one prompt"                              # one more turn of that conversation, then exit
cxt run-ai --new "a fresh start"                     # a new conversation (the memory and the skills stay)
cxt run-ai --conversations                           # the conversations of the project: id, runs, harnesses, title
cxt run-ai --conversation=20261004-18 -i             # continue a given one (id or prefix)
cxt run-ai --harness=codex --model=gpt-6.1-sol,high  # the same conversation with codex: the transcript is handed over
cxt run-ai --project="project::my-app" -i            # the project named explicitly (category::artifact)
cxt run-ai --project=. "..."                         # the current directory itself, no artifact detection
cxt run-ai --harness=claude --model=claude-opus-5-5,high "..."     # or --model=claude-opus-5-5 --effort=high
cxt run-ai --harness=codex --list_models             # the models and efforts of a harness, one --model=<model>,<effort> line each
cxt run-ai --list_models                             # the same for every harness, compact
cxt run-ai --harness=antigravity "..."               # Google's agy (also --harness=agy); sign in once with "cx tool run agy"
cxt run-ai --harness=gemini "..."                    # Gemini CLI: a Code Assist Standard/Enterprise licence or an API key
cxt run-ai --harness=hermes --model=anthropic/claude-sonnet-4.6,high "..."   # Hermes Agent; connect a provider once with "cx tool run hermes -- model"
cxt run-ai --context="organization::my-org" "..."    # read one more artifact's memory and skills for this run
cxt run-ai --dry_run                                 # the project, its !AI, the context, the conversation and the command - nothing runs
cxt run-ai -w "..."                                  # no questions, write anywhere (--write=all); --write=project|none|ask; the config sets the default
cxt run-ai --pending                                 # the changes staged for the artifacts this project uses
cxt run-ai --apply_pending                           # show each of them and apply it on your word
cxt run-ai --info                                    # every flag of this task, one line each
cxt import-ai --project="project::my-app" --plan=import-plan.yaml   # bring memories and skills into a project's !AI
```

The prompt is the first argument, `--prompt="..."`, or the text of `--prompt_file=<file>` (the file first, then
`--prompt`). **A prompt that contains `=` goes through `--prompt=`**: cMeta's command line reads a bare argument with
an `=` in it as a parameter (`key=value`), so `cxt run-ai "set x=1 in the config"` is not taken as a prompt, while
`cxt run-ai --prompt="set x=1 in the config"` is. Without a prompt the run is an interactive session.

## Help from the command line

```bash
cxt run-ai --info       # the flags of this task: its run() signature with a comment per flag; nothing runs
cxt run-ai --help       # (or -h) the flags every cMeta command takes: -v, -q, -j, --repro, --dump, --home, --debug, ...
cx task --help          # the commands of the task category (run, use) and the common ones (find, list, info, ...)
cx task find run-ai     # the folder of the task: this README is in it
```

`cxt <task>` is short for `cx task run <task>`, and `--info` works for every task. The switches of the task engine
itself (`--update`, `--new`, `--clean`, `--cache_repo`, `--use.<key>.<param>`) are in `docs/cmeta-aops/task-engine.md`
of cmeta-aops. The read-only views of this task: `--dry_run`, `--conversations`, `--pending`, `--list_models`.

## The project

| Given | The project is |
|---|---|
| `--project=<cref>` | that artifact: `category::artifact`, alias or `alias,UID` on either side; it must resolve to exactly one |
| nothing | the cMeta artifact the current directory is in - any folder inside it; the detection behind `cx . <command>`, which knows the plugged repositories (a nested artifact wins: the innermost folder with a `_cmeta.*`) |
| nothing, and no artifact | the current directory itself |
| `--project=.` | the current directory itself, no detection |

The task engine changes into the project folder for the agent's task (its `path` control parameter) and comes back
afterwards, so the agent works in the artifact's root and finds the project's own `CLAUDE.md` or `AGENTS.md`, exactly
as if it had been started there. A plain `claude` or `codex` started in a folder never detects artifacts: only
`run-ai` does.

## `!AI/` - what the project keeps

```
<project>/!AI/
    memory/MEMORY.md                   the index the agent loads first
    memory/<name>.md                   one file per memory, as the agent writes it
    skills/<name>/SKILL.md             the project's skills (import-ai brings them; claude loads them as a plugin)
    skills/.sources.json               where import-ai copied each skill from (run-ai warns when a copy and its source went apart)
    .claude-plugin/plugin.json         the manifest that makes !AI a claude plugin (written by run-ai or import-ai)
    log/<stamp>.<harness>.run.md       how this run was made: harness, task, project, model, effort, conversation, session, flags, result
    log/<stamp>.<harness>.output.txt   the agent's output (the header names the prompt and the command)
    log/<stamp>.<harness>.stats.json   token use and cost (one-prompt runs)
    log/<stamp>.claude.settings.json   the settings file given to claude for this run (the memory folder)
    log/<stamp>.<harness>.context.md   what the agent was told first: the orientation and the context (other artifacts' memory and skills)
    log/<stamp>.<harness>.prompt.md    the prompt, when it was too long for a command line argument (an interactive session; opencode and
                                       openclaw always): the harness is asked to read it first, then goes on as before
    log/<id>.conversation.json         a conversation: its runs and, per harness, the native session it continues
    log/<id>.transcript.md             the whole conversation, re-exported from the harnesses' own stores after every run
    log/<id>.summary.md                its summary, written on request (--summarize) and read first at a hand-over
    log/<stamp>.import.md              what import-ai brought in, from where
    log/<stamp>.apply_pending.md       what --apply_pending applied to the artifacts this project uses
    log/<stamp>.applied.json           what was applied to THIS artifact from a project that uses it (or kept by the guard)
    pending/<alias>--<UID>/            changes proposed for an artifact this project uses, until --apply_pending (below)
    codex/                             Codex's own state for this project: its threads, their history, its memories (CODEX_SQLITE_HOME)
```

The folders are created on the first real run; `--dry_run` creates nothing. `--no_log` leaves `log/` out (the
settings file then goes to the temp directory, and no conversation is recorded or continued).

## Conversations: continue by default, `--new`, `--conversation`, the transcript

A **conversation** is a thread of runs on one project. Without a flag, a run continues the conversation with the
latest activity; `--new` starts another; `--conversation=<id or prefix>` picks one (`--resume=` is the same flag);
`--conversations` lists them. The id is the stamp of the first run (`20261004-181659`; a run started within the
same second as another of the same project gets `-2`, `-3`, ...: the stamp is reserved with an exclusive
`log/<stamp>.lock`, removed once the run record holds it).

Each harness keeps its own **native session** for a conversation, and `run-ai` remembers it in
`!AI/log/<id>.conversation.json`:

| Harness | New session | Continue | The id comes from |
|---|---|---|---|
| `claude` | `--session-id <uuid>` (run-ai chooses it) and `--name "run-ai <id> <project>"` | `--resume <uuid>` | run-ai |
| `codex` | - | `run-codex --resume=<id>` -> `codex resume <id>` (interactive) / `codex exec resume <id> -` (one prompt) | the `thread.started` event, else `state_*.sqlite` (the newest thread of the folder) in the project's `!AI/codex` - Codex's SQLite state lives there (`CODEX_SQLITE_HOME`; `--codex_state=home` keeps it in `CODEX_HOME`); the rollout files stay in `CODEX_HOME` |
| `antigravity` (`agy`) | - | `--conversation <id>` | the `result` event's `conversation_id`, else `~/.gemini/antigravity-cli/cache/last_conversations.json` (the folder's entry), else the newest `conversations/*.db` |
| `opencode` | - | `--session <id>` | `~/.local/share/opencode/opencode.db` (the newest session of the folder) |
| `openclaw` | `--session-id <uuid>` (run-ai chooses it); the terminal UI: `--session agent:main:explicit:<uuid>` | `--session-id <uuid>`; the UI: `--session <key>` | run-ai; for a new session of the UI, OpenClaw's `sessions.json` (the id it filed the key under) |
| `gemini` | `--session-id <uuid>` (run-ai chooses it) | `--resume <uuid>` (a session of the project folder) | run-ai |
| `hermes` | - | `--resume <id>` | the `init` / `result` events of the stream (`session_id`), else the `session_id:` line a quiet run prints, else the newest entry of `hermes sessions list`; the transcript comes from `hermes sessions export --format jsonl` |

So `cxt run-ai` after `cxt run-ai` is `claude --resume` of the same session, with the memory folder and the records as
before - and the model may change (`--model=claude-opus-5-5,high` on a conversation started with another model
works). When the harness changes (`--harness=codex` on a conversation held with claude), or when a harness's session
is gone from its store, the new harness starts a new native session and is **handed the transcript** in the prompt:
"You continue conversation <id> ... Before anything else, read its transcript: `!AI/log/<id>.transcript.md` ... then
answer the request at the end of this message". From then on that harness has its own session in the conversation
too, and both are resumed natively. (How a conversation began is not quoted there: in front of a prompt the first
words of an old request read like an instruction.) A conversation
whose earlier runs left nothing to hand over (a session quit before its first message) gets a fresh session and no
hand-over text.

A long conversation can be **summarized**: `cxt run-ai --summarize` (the latest conversation, or
`--conversation=<id>`) gives the transcript to the harness in one prompt - claude with its `haiku` unless `--model`
says otherwise; a transcript over 120,000 characters is read by the agent from its file - and writes the answer to
`!AI/log/<id>.summary.md` (goal, what was done, the state, open items, facts to keep). The conversation itself is not
continued and keeps its place in the list. From then on a hand-over says "read its summary ... (written after run N of
M), then its transcript as far as you need", and `--conversations` marks it `[summary after run N]`. Run it again
when the conversation has gone on.

The **transcript** `!AI/log/<id>.transcript.md` is re-exported after every run from the harnesses' own stores
(Claude's `~/.claude/projects/<slug>/<id>.jsonl`; Codex's `thread_history_*.sqlite`, the rollout files for older
versions; OpenCode's database; Gemini's `~/.gemini/tmp/<project>/chats/session-*.jsonl`; OpenClaw's
`~/.openclaw/agents/<agent>/sessions/<id>.jsonl`): one segment per harness session, the user and assistant texts,
tool calls as one line each, tool results and thinking left out. What run-ai puts in front of a request for the
harnesses that take it in the prompt (a hand-over, the orientation, the context) ends with the line
`<!-- run-ai: the request of this run follows -->`; the transcript keeps what follows it and says that the rest is
in the run's records. Antigravity keeps protobuf blobs:
the readable runs are recovered as a best effort (the prompts, the model's reasoning, the tool calls with their
arguments; a short final answer may be lost), and run-ai's own record of each run (the prompt and the output) follows.
A segment whose store is gone keeps the text of the previous export. The transcript is the portable record: it is
what another harness, another machine or a reader gets.

Every harness is told first **where it is**: an orientation at the top of the system prompt (claude), the
instructions (opencode) or the prompt (the others) names the project's memory and skills folders, says which
conversation this run starts or continues, lists the earlier conversations of the project with their transcripts,
says that a question about a previous conversation is answered from those transcripts and not from the harness's own
session history, and states the rule for the artifacts the project uses (read-only; a change is proposed, below).
Without it, an agent asked "what was our last conversation?" goes looking in its own session store.

No resume scripts are needed: `run-ai` is the way back. Codex is told in the prompt that run-ai keeps the record, so
instructions that ask it for session files of its own do not apply.

`conversations.py` next to this file holds the adapters (new, resume, discover, exists, export) and the transcript
writer; `api_v1.py` picks the conversation, writes the record before the run and closes it after.

### `--conversations`: what a project has

`cxt run-ai --conversations` lists the conversations of the project and stops: no harness starts and nothing is
written - it reads `!AI/log/*.conversation.json`. The one with the latest activity comes first; that is the one a
plain `cxt run-ai` continues.

```
RUN-AI: conversations of <project> (<project>/!AI/log)
  20260101-120000  4 run(s), claude, last 2026-01-01T12:30 with claude  - interactive session 20260101-120000
      claude session <uuid> (1 run(s), started 2026-01-01T12:30)
      files: 20260101-120000.conversation.json, 20260101-120000.transcript.md
  20260101-110000  4 run(s), claude/codex, last 2026-01-01T11:40 with claude  - interactive session 20260101-110000
      claude session <uuid> (1 run(s), started 2026-01-01T11:35)
      codex session <uuid> (1 run(s), started 2026-01-01T11:00)
      files: 20260101-110000.conversation.json, 20260101-110000.transcript.md

  cxt run-ai                      continues the first one listed (the latest activity)
  cxt run-ai --conversation=<id>  continues that one;  cxt run-ai --new  starts another
```

| In the listing | Meaning |
|---|---|
| `20260101-120000` | the id: the stamp of the first run, and the name of the two files. `--conversation=` takes it or any prefix that matches one conversation only |
| `4 run(s)` | every `cxt run-ai` on this conversation, interactive or one prompt - also a session quit before its first message |
| `claude/codex` | the harnesses that took part, in the order they joined |
| `last ... with claude` | when the latest run ended (or started, while it is running) and with which harness |
| `- interactive session ...` | the title: the first prompt (90 characters), or "interactive session <stamp>" / "run <stamp>" without one |
| `claude session <id> (1 run(s), started ...)` | the native session of that harness, which the next run with it resumes. Its count starts again when the harness gets a new native session; the earlier ids stay in the file under `previous` |
| `files:` | in `!AI/log`: the record run-ai keeps, and the transcript - the portable copy to read or hand to another harness |

```bash
cxt run-ai --conversations --project="project::my-app"   # the conversations of another project
cxt run-ai --conversations -j                            # the same as JSON: "conversations" (id, title, started, updated,
                                                         # cref, project, runs[], sessions{}) and "text"
cxt run-ai --conversation=20260101-12                    # continue one by a prefix of its id
```

A `--conversation` value that matches nothing is an error that names the folder; one that matches several lists them.
A conversation is never deleted by run-ai: to drop one, remove its two files from `!AI/log` (the harness's own session
stays in the harness's store).

## Where new memories and skills go

Claude's memory goes into the project by **mechanism**: `autoMemoryDirectory` points at `!AI/memory` for the run, so
whatever Claude decides to remember lands there, and nothing is written to `~/.claude/projects/<slug>/memory` (that
folder then holds the session transcript only). The other harnesses have no memory of their own that run-ai could
redirect (agy and OpenCode have none; OpenClaw and Gemini keep theirs in their homes; Codex's store is in the
project's `!AI/codex`); for them, and for **skills** with every harness, it is a **convention stated in the orientation**: a new
memory is a Markdown file in `!AI/memory/` plus a line in `MEMORY.md`, a new skill is `!AI/skills/<name>/SKILL.md`,
never `~/.claude/skills` or `.claude/skills`. A skill made during a session is loaded on the next run (plugins are read
at start). Outside run-ai's reach: Claude Code's own `#` shortcut and `/init`, which write `CLAUDE.md` files, and a
plain `claude` started in the folder, which uses its own memory folder again.

## Skills in `!AI/skills`

A skill is a folder with a `SKILL.md` (the Claude Code / agent-skills layout; `import-ai` copies them from a
repository's `.claude/skills`, for instance). For **claude**, `!AI` is loaded as a plugin: `run-ai` writes
`!AI/.claude-plugin/plugin.json` when it is missing and passes `--plugin-dir <project>/!AI`, so the skills appear as
`<project>:<skill>`. The other harnesses get the list of skills - name, description, path of the `SKILL.md` - in the
prompt, and read a skill when they need it. The skills of the **context** artifacts (below) come along the same way:
`--plugin-dir` on each `!AI` that has a manifest, the list in the context text otherwise.

A skill copied into `!AI/skills` from a repository is a copy: when the repository's skill changes, import it again
with `--overwrite`. `import-ai` records where each skill came from, when, and a hash of what it copied in
`!AI/skills/.sources.json`; every run compares each copy with its source when that source is on this machine and
says which side changed since the import - the source (a WARNING with the `import-ai ... --overwrite` command that
renews the copy), the copy (a note: carry the change over to the source if it should stay), or both.

## How each harness is pointed at `!AI` - the tool's own settings, no API keys

| Harness | Mechanism | Memory |
|---|---|---|
| `claude` | a settings file per run, `--settings <!AI/log/<stamp>.claude.settings.json>`: `autoMemoryDirectory = <project>/!AI/memory`; `--plugin-dir <project>/!AI` for the skills; `--session-id` / `--resume` for the conversation; `--append-system-prompt-file` and `--add-dir` for the context | **read and written** there |
| `opencode` | `OPENCODE_CONFIG_CONTENT = {"instructions": ["!AI/memory/MEMORY.md", "!AI/memory/*.md", the context file]}` - the variable is merged with the user's config | read only: OpenCode has no memory of its own |
| `codex` | the `!AI/memory` index and the skills are prepended to the prompt; one-prompt runs get `--skip-git-repo-check`, because `codex exec` refuses a folder that is neither a git repository nor a trusted project; `CODEX_SQLITE_HOME=<project>/!AI/codex` keeps Codex's threads, their history and its memories inside the project (`--codex_state=home` keeps `CODEX_HOME`) | read only through the prompt; Codex's own memory store lives in the project's `!AI/codex` |
| `antigravity` (also `agy`) | `task/run-agy` with `tool/agy`: the index and the skills are prepended to the prompt; context folders join the workspace with `--add-dir`. agy is Google's successor of Gemini CLI for personal Google accounts. The `stream-json` events give the answer, the token counters and the conversation id, and `--conversation <id>` resumes it. Without a login agy prints the login URL and waits; `run-agy` then fails with a sign-in hint - sign in once with `cx tool run agy` | read only; agy has no memory of its own, only conversations (`~/.gemini/antigravity-cli`) |
| `gemini` | `task/run-gemini` with `tool/gemini`: the index and the skills are prepended to the prompt; context folders join the workspace with `--include-directories`; headless runs get `--skip-trust` and never open a browser (`NO_BROWSER`). Gemini CLI serves Gemini Code Assist Standard/Enterprise licences, paid API keys (`GEMINI_API_KEY`) and Vertex AI; a personal Google account is refused, and the run then fails with a hint that says so - use `--harness=antigravity` for those | read only; Gemini's own memory is its global `GEMINI.md` |
| `openclaw` | `task/run-openclaw` (`openclaw agent --local --json`): the index and the skills are prepended to the prompt; `--session-id` names the session and resumes it. OpenClaw works in its own workspace (`~/.openclaw/workspace`, from its config, with its persona files `AGENTS.md`, `SOUL.md`, ...) whatever the current directory is, so the orientation tells it the project folder and it uses absolute paths there. Its default model (`openai/gpt-5.5`) needs an OpenAI key; `--model=claude-cli/<model>` runs through the local Claude Code login, and the token counts of such a turn are read from Claude Code's own session (OpenClaw reports only the last model call). The terminal UI (`--interactive`) takes the session's key, `--session agent:main:explicit:<id>`, and no `--model`: run-ai leaves it out and says so - type `/model <provider/model>` in the UI, or set the default once with `cx tool run openclaw -- models set <provider/model>` (drive OpenClaw through the tool: cMeta installs it when missing, a bare `openclaw` may be another copy or none). The UI files a new session under an id of its own; run-ai reads it from OpenClaw's index afterwards, so that the next turn continues that session | read only; OpenClaw's own memory lives in its workspace |
| `hermes` | `task/run-hermes` with `tool/hermes` (`hermes chat -Q -q`, one shot; the JSON event stream with `--stats`): the index and the skills are prepended to the prompt. Hermes reads `AGENTS.md` from the project folder by itself, and keeps its own memory (`memories/MEMORY.md`, `USER.md`) and skills under `HERMES_HOME` (`~/.hermes`); the session ids come back from its events and `--resume <id>` continues them. A provider is connected once by hand (`cx tool run hermes -- model`); without one a headless run fails with the ways to connect | read only through the prompt; Hermes's own memory lives in `HERMES_HOME` |
| others | the task `run-<harness>` with the shared parameters (`--yes` and `--reproducible` are forwarded only when given); the index is prepended to the prompt | - |

A prompt that tells the agent to *search* for something makes OpenCode and Codex reach for tools, and a tool that
needs a permission then hangs a one-prompt run until the timeout. Ask them to answer from the prompt or their
instructions; the interactive mode is the place for tool use.

Everything else goes to `run-<harness>` unchanged: the prompt (positional or `--prompt_file`), `-i`, `--yes`,
`--stats` (on by default; the cost lands in `!AI/log`), `--reproducible`, `--add_repos` (claude), and every flag after
`--`. A `--settings` of your own after `--` is read and merged: your keys and hooks stay, the memory folder is added.
Without a prompt the run is interactive; with one it is a single turn unless `-i` says otherwise.

## The model and the effort: `--model`, `--effort`, `--list_models`

The model and the reasoning effort are given **in the harness's own names**, either together or apart:

```bash
cxt run-ai --harness=claude --model=claude-opus-5-5,xhigh "..."     # <model>,<effort>
cxt run-ai --harness=codex --model=gpt-6.1-sol --effort=high "..."  # the same, apart (--effort wins when both say an effort)
cxt run-ai --harness=codex --list_models                            # what this harness knows, every combination ready to copy
cxt run-ai --list_models                                            # every harness, compact
```

`run-ai` turns them into the harness's flags, so that the run task records them as `generator.model` /
`generator.effort` (`CMETA_GENERATOR`, stamped on what the session creates) and `--reproducible` sees a pinned model:

| Harness | `--model=m` | `--effort=e` |
|---|---|---|
| `claude` | `--model m` | `--effort e` (`low`, `medium`, `high`, `xhigh`, `max`) |
| `codex` | `--model m` | `-c model_reasoning_effort=e` (`low` ... `xhigh`, `max`, `ultra`; per model) |
| `opencode` | `--model provider/m` | `--variant e` (the provider's: Anthropic `high`, `max`; OpenAI `none` ... `xhigh`) |
| `openclaw` | `--model provider/m` | `--thinking e` (`off` ... `xhigh`, `adaptive`, `max`) |
| `antigravity` (`agy`) | `--model m` | `--effort e` (`low`, `medium`, `high`; `xhigh`, `max` accepted by the flag) |
| `gemini` | `--model m` | none: Gemini CLI has no effort flag, so `--effort` is dropped with a note |
| `hermes` | `--model provider/m` | `--reasoning e` (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`) |

Without `--model` the harness runs its default model, which run-ai cannot know in advance: the run's stats name the
model afterwards, and a test session (`cx task run test-session`) takes it from the session's transcript.

The knowledge lives **with each tool**, in `tool/<harness>/_desc_models.yaml` (`tool/claude`, `tool/codex`,
`tool/opencode`, `tool/openclaw`, `tool/agy`, `tool/gemini`, `tool/hermes`): the `flags` templates above, the `efforts` vocabulary with a line of
advice each, and one entry per model with a description, the context window, the default effort, the API price, the
plans, the `aliases` the harness also accepts, and the efforts the model takes when they differ from the vocabulary.
The files are hand-maintained (`updated`, `checked_with`, `sources`) and keep history: a model that went away stays
with `disabled: true`, so that an old `generator.model` can still be read and the run repeated on purpose;
`legacy: true` marks a previous generation that is still served; `until` the announced end; `unverified: true` a name
not yet confirmed with the tool itself. `--list_models` prints all of it, retired entries last. The harness's own
listing (`opencode models`, `cx tool run openclaw -- models list`, `agy models`, `/model` inside claude and codex) is the truth of
the day; the files are the memory of what was true when.

The checks are **warnings, never errors**: an unknown model or effort is passed through as it is (the list may be
behind the vendor), a retired one says "the harness may refuse it", an effort a model does not list says so. A
`--model`/`--effort`-type flag given after `--` as well is replaced by the `--model`/`--effort` of `run-ai`, with a
note. The old name `--agent` of `--harness` still works and says so.

## The first run of a project: the seed, `--no_seed`, and `import-ai`

When `!AI/memory` holds no memory yet and Claude Code's own memory folder for this path
(`~/.claude/projects/<slug>/memory`, the slug being the path with every non-alphanumeric character turned into `-`,
both spellings of the drive letter tried; a slug longer than 200 characters is cut there by Claude Code and followed
by a hash, so the folders with that prefix are taken whose sessions ran in this path; `CLAUDE_CONFIG_DIR` moves
`~/.claude`) does, the files are **copied** in.
Nothing is lost, the original folder is left as it is, and the project starts with the memories it already had. A
folder that holds only a `MEMORY.md` index (a pointer left behind when the memories moved elsewhere) has nothing to
copy. From then on `run-ai` reads and writes `!AI/memory` only; a plain `claude` started in the same folder still uses
its own folder, so the two drift apart until that folder is cleaned or redirected too (a `.claude/settings.local.json`
with `autoMemoryDirectory`; not written by run-ai). `--dry_run` says what would be copied; **`--no_seed`** copies
nothing and the project starts with an empty memory (the dry run then says what was left out).

Memories that live elsewhere - the Claude folders of other directories, a repository's skills - are brought in with
the sister task **`import-ai`**:

```bash
cxt import-ai --project="project::my-app" --plan=import-plan.yaml       # memories: [files or folders], skills: [folders]
cxt import-ai --project="project::my-app" --memories="<file>;<folder>" --skills="<repo>/.claude/skills"
cxt import-ai --project="project::my-app" --claude_folder="<folder>"    # the memory Claude Code keeps for that folder
cxt import-ai ... --overwrite                                           # replace what is there (e.g. a skill that changed at its source)
cxt import-ai ... --dry_run
```

Files are copied as they are (identical ones skipped, the newer one wins, `--overwrite` forces). `MEMORY.md` keeps its
lines, their order and its headings: a memory without an entry gets one at the end (its line of the source index when
there is one, else one made from the file's front matter), the entry of a memory replaced with `--overwrite` is
renewed where it stands, and an import of skills only does not touch the index. Skills land in `!AI/skills/<name>/`
with the plugin manifest (one that is there and differs is replaced with `--overwrite` only); and
`!AI/log/<stamp>.import.md` records what came from where. Paths are separated by `;`, since folder names may contain
commas. A set of rules shared by several projects is better kept in one artifact that the others read through
`ai_uses` (next section) than copied into each.

## Context from other artifacts: `ai_uses` and `--context`

Other artifacts' memory and skills can be read by the agent, never written by it - a change to them is proposed and
applied on the user's word (the section after next). The sources, in this order:

| Source | Where it is written | Kind in the dry run |
|---|---|---|
| `--context` | the command line, for this run: entries separated by `;` - a cRef, or `claude:<folder>` for the memory Claude Code keeps for a folder | `context`, `claude` |
| the project's `ai_uses` | its `_desc.yaml` | `ai_uses` |
| the repository default | an `ai_uses` list in the `_cmr.yaml` of the project's repository: every artifact of that repository reads it, on top of its own list | `ai_uses, repository default` |
| this machine's mapping | the config artifact `task-run-ai` of this machine, key `local_ai_uses` (next section) | `ai_uses, machine-local: <key>` |

```yaml
# _desc.yaml of the project: whose memory and skills its AI sessions read (one list, one direction, like `uses` in tasks)
ai_uses:
  - project,1d3c5e7f9a2b4c6d::shared-rules,0a1b2c3d4e5f6a7b
  - cref: organization::my-org                  # the dict form takes a note
    note: the project belongs to this organisation
```

```bash
cxt run-ai --context="organization::my-org"                       # one more source for this run
cxt run-ai --context="organization::my-org;claude:<folder>"       # several: ";" separates (cRefs and folder names contain commas)
cxt run-ai --context_depth=2                                      # follow ai_uses transitively (default 1: the lists are what you get)
cxt run-ai --skip_ai_uses                                         # this run reads none of the ai_uses sources (the project's, the repository's, this machine's)
cxt run-ai --context_limit=5                                      # at most 5 sources (default 20)
cxt run-ai --max_context_tokens=20000                             # the limit of the estimate below (default: the config, else 30,000)
cxt run-ai --trim_context                                         # over that limit, leave sources out (the last first) instead of stopping
```

- **`ai_uses`** is the directed counterpart of `connections`: `connections` say "these two have something to do with
  each other" and stay the undirected links of the knowledge graph; `ai_uses` says "my AI sessions read these" - a
  task its project, a plugin the engine, a work folder its organisation - and is written once, at the artifact that
  reads. Nothing flows the other way: an engine does not read the memory of its plugins. An explicit empty list
  (`ai_uses: []`) is a decision too: this artifact has no list of its own (a repository default and this machine's
  mapping still apply). `cserver.browse` draws an `ai_uses` edge as a dashed arrow and lists "AI uses" in the detail.
  An entry is a cRef string (`category,UID::artifact,UID`; UIDs optional) or a dict with `cref` and an optional `note`.
- **A repository-wide default** (`ai_uses` in `_cmr.yaml`, the first one found walking up from the project folder):
  all the work folders, notes and meetings of a private repository read their organisation's memory without a list
  of their own. A shared repository should not point at a private artifact this way - its `_cmr.yaml` travels with
  every clone; that is what this machine's mapping is for.
- **`--context`** entries count like `ai_uses` entries (they are read-only, guarded, and followed with
  `--context_depth`); `claude:<folder>` is useful until such memories are moved into artifacts.
- A source counts when it holds memory (`!AI/memory/*.md`) or skills (`!AI/skills/*/SKILL.md`); the others are listed
  as skipped, with the reason (no `!AI` yet, not found, not a cRef, over `--context_limit`).
- **The estimate:** before the run, the orientation, the memory index, the skills, the context sources, the hand-over
  and the prompt are counted (chars / 4, within about 25%) and printed with the limit; over the limit the run fails
  under `-q`, `--yes` or without a terminal, and asks otherwise. With `--trim_context` (or `trim_context: true` in the
  config, for every run of this machine) the context sources are left out instead, from the last - this machine's
  mapping, the repository default and the deeper levels come after the project's own list and `--context` - until
  the estimate fits; the notes and the skipped sources name them. When the project's own part alone is over the
  limit, the run stops or asks as before. The estimate goes into the run record and the
  conversation file, next to the harness's own counters afterwards; "last turn N min ago" says whether the harness's
  prompt cache (Claude: 5 min, 60 with extended caching) is probably still warm.
- **What the agent gets:** one rendered file, `!AI/log/<stamp>.<harness>.context.md` (always written: the orientation,
  then per source its `MEMORY.md` index with the links turned into absolute paths, and its skills). Claude receives it
  with `--append-system-prompt-file`, gets `--add-dir` on each source folder (so it can read a memory on demand) and
  `--plugin-dir` on each source `!AI` that has a manifest (so the skills are native); agy gets the text in front of
  the prompt and `--add-dir` (its workspace mount), gemini the same with `--include-directories`; Codex gets the text only - its `--add-dir` means *more writable
  roots*, and Codex refuses to start with it under its read-only sandbox, while reading the files named in the text
  needs nothing; OpenCode gets the file in its `instructions`. A `--append-system-prompt[-file]` of your own is kept in
  front of the context.

## This machine's mapping: `local_ai_uses`

A repository that is **shared** (cloned by colleagues, synced to servers) must not name a private artifact - not in
its artifacts' `ai_uses`, not in its `_cmr.yaml`. Yet on your own machine a session started in it may well need your
private memory: the rules of your organisation, your notes on the project. The mapping says so **on this machine
only**: it lives in the config artifact `task-run-ai` of the `local` repository (`<CMETA_HOME>/repos/local/config/
task-run-ai/data.json`), which is never synced, and run-ai reads it after the project's own list and the repository
default.

```bash
# every artifact of a shared repository reads a private artifact here (the key: the repository's alias,UID from its _cmr.yaml)
cx config set task-run-ai "--meta.local_ai_uses.shared-repo,1111222233334444=organization,f3c0a1b2c3d4e5f6::my-org,59a0b1c2d3e4f5a6"

# one artifact only (its UID, or its cRef - UIDs optional), and two sources at once (";" between them)
cx config set task-run-ai "--meta.local_ai_uses.0123456789abcdef=organization::my-org;project::my-notes"

cx config show task-run-ai                                  # what is set, and the data.json it lives in
cxt run-ai --project=<an artifact of that repository> --dry_run   # the source shows with the kind "ai_uses, machine-local: <key>"
```

| A key | matches |
|---|---|
| `<repository alias>,<UID>`, `<alias>` or `<UID>` | every artifact of that repository (its `_cmr.yaml`, the first one walking up from the project folder) |
| an artifact cRef (`category::artifact`, UIDs optional) or the artifact's UID | that artifact only |

- The value is one cRef, several separated by `;` (cRefs contain commas, so the CLI's list syntax cannot carry them),
  or - written into `data.json` by hand - a list of cRefs or `{cref, note}` dicts.
- The CLI turns the dots of a `--meta.` key into levels (`--meta.local_ai_uses.cserver.page::x=...` is stored as
  `cserver` -> `page::x`); run-ai joins them back, so a cRef with dots works as a key.
- The config artifact is named after the task because config artifacts are global: `task-run-ai` cannot collide with
  another tool's settings. Reading it never creates it (`cx config get` would).
- The mapped artifacts are used artifacts like the others: read-only, guarded, followed with `--context_depth`,
  skipped with `--skip_ai_uses`, counted in the estimate.
- To remove a key, delete it from the `data.json` that `cx config show task-run-ai` names.
- A small `.bat` or shell script next to the private artifact, with one `cx config set` line per shared repository,
  is an easy way to remember the setup and to repeat it on another machine. Keep it on the private side: a script in
  the shared repository would name the private artifact there.

## Configuration: `cx config ... task-run-ai`

| Key | Meaning |
|---|---|
| `local_ai_uses` | this machine's mapping (the section above) |
| `max_context_tokens` | the limit of the context estimate when `--max_context_tokens` is not given (default 30,000); the older key `run_ai_max_context_tokens` of the config `default` is still read |
| `trim_context` | `true`: every run leaves context sources out to fit the limit, as `--trim_context` does |
| `write` | what a run may write when no flag says so: `ask` (the default), `project`, `all` or `none` (the next section) |

```bash
cx config set task-run-ai --meta.max_context_tokens=40000
cx config set task-run-ai --meta.trim_context=true
cx config set task-run-ai --meta.write=all
cx config show task-run-ai
```

## What a run may write: `--write`, `-w`, and the config

Two things decide what a session can change: the harness's own approvals and sandbox, and run-ai's guard of the
artifacts the project uses. One switch sets both:

```bash
cxt run-ai -w "..."                           # --write=all: no questions, write anywhere, the used artifacts' memory too
cxt run-ai --write=project "..."              # no questions; the used artifacts still take proposals only (what --yes does)
cxt run-ai --write=none "..."                 # read-only
cx config set task-run-ai --meta.write=all    # this machine's default, for every run and harness
cxt run-ai --write=ask "..."                  # one careful run on a machine whose default is all
```

| `--write=` | The harness | The project | Memory and skills of the used artifacts |
|---|---|---|---|
| `ask` (default) | asks before it edits a file or runs a command; a one-prompt run has nobody to ask, so there it mostly cannot write | after your approval | proposals only; you are asked about a direct change |
| `project` (also `--yes`) | asks nothing | free | proposals only; a direct change is put back and staged |
| `all` (also `-w`) | asks nothing | free | may be changed directly: kept, recorded, the versions before the run saved |
| `none` | runs in its plan / read-only mode | no writes | no writes; a direct change is put back and staged |

A flag wins over the config, and the config is read only when neither `--write`, `-w` nor `--yes` is given. The config
artifact lives in the `local` repository, so the default of one machine travels nowhere: whoever clones a repository
starts from `ask`.

| Harness | `project` and `all` (its task's `--yes`) | `none` |
|---|---|---|
| `claude` | `--permission-mode bypassPermissions` | `--permission-mode plan` |
| `codex` | `--dangerously-bypass-approvals-and-sandbox` | `-c sandbox_mode="read-only"` |
| `opencode` | `--auto` | `--agent plan` |
| `antigravity` | `--dangerously-skip-permissions` | `--mode plan` |
| `gemini` | `--yolo` | `--approval-mode plan` |
| `hermes` | `--yolo` | none that run-ai knows (Hermes has approval modes, no read-only mode): told to change nothing |
| `openclaw`, others | none that run-ai knows: the harness follows its own settings (a task `run-<x>` gets `yes` from `--yes` itself) | told to change nothing; nothing enforces it |

The same setting given after `--` (`-- --permission-mode acceptEdits`) is your own choice for that run and is left
alone.

**With `all`**, the session is told that it may change the memory and skills of the used artifacts where they are.
After the run, run-ai lists what changed there, writes `<artifact>/!AI/log/<stamp>.applied.json` (what, when, from
which project - the same record an applied proposal leaves) and saves the version every changed or deleted file had
before the run under the project's `!AI/log/<stamp>.before/<alias>--<UID>/`. To take a change back, copy the file from
there. This is the guard's mode `keep`; `--context_guard=<mode>` still overrides it (`--write=all
--context_guard=restore` lifts the harness's questions and keeps the proposals).

**What it means.** With `project` and `all` nothing technical stands between the session and any command the harness
can run - a push, a delete outside the project, an installation - and with `all` a weak model can spoil a memory that
many projects read (the saved versions are the way back). Rules such as "commit only on my word" then hold as
instructions in the memory, not as a barrier. `none` relies on the harness's own read-only mode where it has one.

## Changing a used artifact: proposals in `!AI/pending`, `--apply_pending`, the context guard

Unless a run is given write access to them (`--write=all`, the section above), the memory and skills of the artifacts
a project uses stay **read-only for a run** and are changed **only on the user's word**. run-ai does this itself, with plain files and the standard library, so it is the same for every
harness, platform and permission mode and for whoever runs the project on another machine - no setting of a harness
or of one PC is involved (a harness's own permission rule covers one harness, its path syntax one OS).

Why it is needed. A project that uses another artifact (`ai_uses`, `--context`) is given that artifact's memory and
skills to read. Nothing writes there by itself - run-ai writes only into the project's own `!AI`, Claude's memory goes
to the project's `!AI/memory`, Codex keeps its state in the project's `!AI/codex`, OpenCode has no memory - but the
session can decide to edit a file there, and what stands in its way depends on the harness and on how it was started:

| Harness | How it gets the used artifacts | What stops a direct edit there, without the guard |
|---|---|---|
| `claude` | the context text in the system prompt; `--add-dir` on each artifact (to read a memory on demand); `--plugin-dir` for their skills | `--add-dir` makes them working directories: asked in the default mode, accepted without a question in accept-edits mode and under `--yes`, left to a classifier in auto mode |
| `codex` | the context text in front of the prompt; it opens the files itself. No `--add-dir` | its sandbox keeps writes inside the project - unless `--yes` (`--dangerously-bypass-approvals-and-sandbox`), often the only way it can write at all on Windows |
| `opencode` | the context file among its `instructions` | nothing: no sandbox, and `--yes` (`--auto`) approves what is not denied |
| `antigravity`, `gemini` | the context text in front of the prompt; the artifacts join the workspace (`--add-dir`, `--include-directories`) | their own approval modes |
| `hermes` | the context text in front of the prompt; it opens the files itself | its approval modes (`smart` by default; `--yes` is `--yolo`) |

So the rule cannot rest on the harnesses. It rests on three steps that run-ai takes for all of them.

**1. A session proposes.** Every harness is told the rule in the orientation, and each used artifact is listed with
its staging folder. The session writes the new version under the project's own `!AI/pending/<alias>--<UID>/`, with the
path the file has under the artifact's `!AI`:

| Staged file | Meaning |
|---|---|
| `memory/<name>.md`, `skills/<skill>/SKILL.md` | the whole file: a new one, or the replacement of one |
| `<file>.append` (e.g. `memory/MEMORY.md.append`) | lines to add to an existing file; lines it already has are skipped, its line ends are kept |
| `<file>.delete` (empty) | remove that file |
| `_note.md` | why - shown before applying, never applied |

Only `memory/` and `skills/` can be proposed; anything else is listed as refused. The folder name is
`<alias>--<artifact UID>` from the cRef, so it is the same on every machine.

**2. The user applies.**

```bash
cxt run-ai --pending            # what is staged, with the difference each proposal would make; nothing changes
cxt run-ai --apply_pending      # the same, then one question per artifact: Apply N change(s) to <artifact>? [y]es, all / [e]ach, one by one / [N]o
cxt run-ai --apply_pending -q   # without the question (also --yes); with nobody to ask and neither flag, nothing is applied
```

Applying writes the files into the artifact, leaves `<artifact>/!AI/log/<stamp>.applied.json` there (what, when, from
which project) and `!AI/log/<stamp>.apply_pending.md` in the project, and removes what it applied from the staging
folder. A folder under `!AI/pending` that matches no artifact the project uses is named and left alone.

**3. The guard checks every run.** Before the harness starts, `memory/` and `skills/` of each used artifact are
snapshotted; when it is back they are compared. For what changed without going through a proposal:

| `--context_guard=` | A direct change |
|---|---|
| `ask` (default with `--write=ask`) | you are asked, per artifact: *Keep them? [y/N]*. Yes: kept, and recorded like an applied proposal. No - or nobody to ask (`-q`, `--yes`, no terminal, an API call): as `restore` |
| `restore` (default with `--write=project` and `none`) | is turned into a proposal under `!AI/pending` (nothing is lost) and the file is put back as it was before the run |
| `report` | is listed in the run record and on the console; nothing is touched |
| `keep` (default with `--write=all`) | stays: listed, recorded in the artifact like an applied proposal, the version before the run saved in the project's `!AI/log/<stamp>.before/` |
| `off` | is not looked for |

Why a question and not a silent restore: a run cannot tell *who* changed a file. A `git pull`, a sync or your own edit
during a long interactive session looks exactly like an edit of the session, and putting such a file back would hand
the older version to the next sync. Two cases are recognised and left alone: what `--apply_pending` wrote in the
meantime (its record says so), and the changes of an artifact that was itself run as a project during that time (its
conversation records) - its own session writes its own memory. A direct change to a file that already has a staged
proposal is kept aside in `_direct-<stamp>/` instead of replacing the proposal. The run record and the task result
(`context_changes`, `pending`) carry what was found.

**An example.** A project `project::my-app` uses `project::shared-rules`. Its session learnt something that belongs to
the shared rules, and wrote three files under its own `!AI`:

```
!AI/pending/shared-rules--0a1b2c3d4e5f6a7b/_note.md
!AI/pending/shared-rules--0a1b2c3d4e5f6a7b/memory/release-checklist.md
!AI/pending/shared-rules--0a1b2c3d4e5f6a7b/memory/MEMORY.md.append
```

```
> cxt run-ai --pending
RUN-AI: changes staged for the artifacts this project uses (<my-app>/!AI/pending)

  project,1d3c5e7f9a2b4c6d::shared-rules,0a1b2c3d4e5f6a7b
    in <shared-rules>/!AI
    note: the release checklist the team agreed on ...
    APPEND  memory/MEMORY.md
        + - [Release checklist](release-checklist.md) — the steps before a release ...
    NEW     memory/release-checklist.md
        + ---
        + name: release-checklist
        ...

  "cxt run-ai --apply_pending" shows them again and applies them on your word
```

`cxt run-ai --apply_pending` shows the same, asks *Apply 2 change(s) to ...shared-rules...? [y]es, all / [e]ach, one
by one / [N]o* and applies on "y": the memory and the index line are in `shared-rules`, an `applied.json` is in its
`!AI/log`, an `apply_pending.md` in the project's, and the staging folder is gone. "e" asks for each change
(*NEW memory/two.md? [y/N]*), and what is not applied stays staged.

**The words of a listing:** `NEW` a file the artifact does not have; `CHANGE` a replacement, shown as a unified
difference; `APPEND` the lines that would be added; `DELETE` a removal; `SAME` the artifact has it already (cleared
when applying); `REFUSED` a path outside `memory/` and `skills/`.

**What is left behind, and where:**

| Record | Where | Says |
|---|---|---|
| `<stamp>.applied.json` | `!AI/log` of the artifact that was changed | what was applied (path, action, sha1), when, from which project; also what the guard kept on your word |
| `<stamp>.apply_pending.md` | `!AI/log` of the project that proposed | which artifact got which change |
| the lines "context guard: ..." | the run record `!AI/log/<stamp>.<harness>.run.md` and the console | the guard's mode at the start; after the run every direct change and what was done about it; how many proposals wait |
| `context_guard`, `context_changes`, `pending` | the task's result (`-j`) | the mode, the direct changes found, the number of waiting proposals |
| `write`, `write_from` | the task's result (`-j`) and the row "write" of the run record | what the run could write, and whether a flag, `--yes` or the config said so |
| `<stamp>.before/<alias>--<UID>/` | `!AI/log` of the project | with `--write=all`: the version each directly changed or deleted file of a used artifact had before the run |

**Questions that come up:**

- *Reject a proposal?* Delete its file under `!AI/pending` (or the whole `<alias>--<UID>` folder). Nothing else knows about it.
- *Change it before applying?* Edit the staged file; `--pending` shows the new difference.
- *Apply only some?* The question is per artifact, for all its proposals: move the others out of the folder first.
- *Where is it run?* In the project that staged them - the proposals live in that project's `!AI/pending` - or from
  anywhere with `--project=<cref>`.
- *A used artifact I do want changed by hand, or by a pull, during a session?* Answer "y" to the guard's question, or
  run with `--context_guard=report` / `off`.
- *The project's own memory?* Never guarded: a session writes its own `!AI/memory` and `!AI/skills` freely.

**Limits:**

- The guard looks when the harness is back, not while it runs: a direct change exists until then, and a run-ai that
  is killed never looks.
- It covers `memory/` and `skills/` of the used artifacts, nothing else in them: their `log/`, `codex/` and the
  artifact's other files are not compared.
- A file above 8 MB is fingerprinted but not kept, so it is reported and cannot be put back.
- An artifact counts as "running its own session" for 48 hours after a run of it that has no end (a crash leaves
  none); its changes are then reported and left.
- `--add-dir` still gives Claude write access to the used artifacts; the guard is what undoes a write, not what
  prevents it.

## What stays as it is

- **`CLAUDE.md` discovery is Claude's own**, and `run-ai` leaves it alone: `~/.claude/CLAUDE.md`, the `CLAUDE.md`
  files from the project folder upwards, `--add-dir` folders. `--settings '{"claudeMdExcludes":[...]}'` after `--`
  drops a named file for one run while keeping every other setting and the hooks. The rules of a machine are **not**
  duplicated into `!AI`.
- **One memory folder per run.** With the memory in the project, the memories of `~/.claude/projects/<slug>/` are not
  loaded for that run (except through the seed). A shared set (who you are, how you work, the rules of a codebase) is
  what `ai_uses` gives.
- **Native sessions** stay in the harnesses' own stores on this machine (Codex's in the project's `!AI/codex`, the rest
  in the home); the conversation file names them and the transcript is the portable copy.

## Git

`run-ai` never runs git. `!AI` is a folder inside the artifact: in a private repository you may commit it (the
knowledge travels with the project); in a public or shared one, ignore it with the `.gitignore` line `\!AI/` - escaped,
because a leading `!` means "negate" in gitignore (cmeta-aops ignores it). `codex exec` refuses to run in a folder that
is neither a git repository nor a trusted project, so `run-ai` adds `--skip-git-repo-check` to one-prompt Codex runs.

## Tests

```bash
python -m pytest tests -q -p no:cacheprovider -k "run_ai or import_ai or run_agy or run_openclaw"
```

In the repository's hermetic suite (`tests/cmeta_aops_basic_tests/`; no network, no harness, a throwaway
`CMETA_HOME`):

| File | What it covers |
|---|---|
| `test_run_ai_pending.py` | the proposals and the guard, on plain folders |
| `test_run_ai_context.py` | the `--context` entries, cRef matching, the `ai_uses` values, this machine's mapping, the seed, folder names with brackets, the harnesses and their model lists |
| `test_run_ai_conversations.py` | the conversation files, how each harness starts and resumes a session, the Claude and Gemini session readers, the transcript, the hand-over |
| `test_run_ai_engine.py` | the task through the engine with a stand-in harness that calls no model: records, conversations, context sources, the config artifact, the seed, the write modes, proposals and the guard end to end |
| `test_run_agy_gemini.py` | the event streams of Antigravity CLI and Gemini CLI turned into text and token counts; what a failed Gemini run is told |
| `test_run_openclaw.py` | OpenClaw's `--json` result turned into the reply and the token counts (from Claude Code's own session for the `claude-cli` provider) |
| `test_import_ai.py` | import-ai: what is copied, skipped and replaced, the index, the manifest, the record |

A dry run (`--dry_run -j`) shows a real setup without starting a harness: the context with the kind of each
source, the estimate and the limit, the flags, the notes.

## Not covered

- OpenClaw is checked live with the `claude-cli` provider (OpenClaw 2026.6.10: new sessions, resume, the
  transcript, hand-overs both ways), not with an API-key provider, whose tool calls may be written differently in
  its session file. Its terminal UI (`--interactive`) was started on a run-ai session key (it attaches to that
  session) but not used for a whole conversation, since it takes no `--model` and the default model of the test
  machine had no key. Antigravity's transcript is a best
  effort (protobuf store). Gemini CLI's flags, event stream and session files are checked against the CLI itself and
  runs that fail on purpose, not against a session with a licensed account.
- The write modes are checked live with Claude Code (`ask`, `project`, `all`, `none`), Codex (`ask`, `all`, `none`),
  OpenCode and Antigravity (`all`, `none`). Gemini's plan mode is taken from the CLI's own help and not run;
  OpenClaw has no switch. In its plan mode a one-prompt Antigravity run writes nothing but may also give
  no answer (it stops at the first tool it cannot ask about).
- Only Claude writes `!AI/memory` by itself; the other harnesses write memories there by following the orientation.
- No check yet that a used artifact's layer allows it to be read from the project (a shared repository reading a
  private artifact through its own files is prevented by convention and by the mapping living on one machine).
