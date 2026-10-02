# test-session — a sandbox and a kept log for every test

Every real test, build or benchmark gets one dated place to work in and a record that
stays when the work is cleaned up, the same on every machine. All sessions live in two
cMeta artifacts of the `local` repository, a folder per day and a subfolder per session,
so a session adds no index entry (`--repo=<alias>` and `--artifact=<name>` for others):

```
tmp::cmeta-aops-test-sessions/20261002/0915.llama-drift/   sandbox: scripts, outputs, clones, venvs (deletable)
log::cmeta-aops-test-sessions/20261002/0915.llama-drift/   record (kept):
    session.md        what was done, by whom, results, costs
    session.json      the same as data
    attachments/      attached files
```

The session id is that path, `<YYYYMMDD>/<HHMM>.<type>` (local time; a second session of
the same type in the same minute gets `-2`; `20261002-0915.llama-drift` works too). The two
artifacts are made on first use. What cMeta builds and downloads still goes to its cache,
where the next test reuses it; the sandbox holds everything else a test creates.

## Commands

```bash
# Start: prints the sandbox and the log (--print=id|sandbox|log|json prints only that, last line)
cx task run test-session --start --type=llama-drift --title="llama.cpp release vs source" \
   [--cmd="cx program run llama-cpp cuda"] [--repos=<another repository>]

# While it runs: notes, results, files to keep
cx task run test-session --id=20261002/0915.llama-drift --note="CUDA release done"
cx task run test-session --id=20261002/0915.llama-drift --results.cuda_release_tps=<value> --results_file=bench.json
cx task run test-session --id=20261002/0915.llama-drift --attach=bench.txt,logs/*.log

# Finish: status (default passed), summary; removes a sandbox above 1 GiB unless --keep
cx task run test-session --finish --id=20261002/0915.llama-drift --status=passed --summary="<what was found>"

# List (the default action) and clean up
cx task run test-session [--list] [--date=20261002] [--type=llama-drift] [--status=failed] [--host=<name>]
cx task run test-session --prune [--days=7]   # sandboxes of finished sessions; the logs stay
cx task run test-session --prune --id=20261002/0915.llama-drift --all   # also one finished with --keep
```

Where the two artifacts are:

```bash
cx log find cmeta-aops-test-sessions        # the records
cx tmp find cmeta-aops-test-sessions        # the sandboxes
```

The id is also the first argument: `cx task run test-session 20261002/0915.llama-drift --note=...`.

Capturing the id in a script (the task banner comes first when `CMETA_VERBOSE` is on):

```bash
ID=$(cx task run test-session --start --type=build --print=id | tail -n 1 | tr -d '\r')   # bash
```
```bat
for /f "delims=" %i in ('cx task run test-session --start --type=build --print=id') do set ID=%i
```
```powershell
$ID = (cx task run test-session --start --type=build --print=id | Select-Object -Last 1).Trim()
```

## What a record holds

| Key | Content |
|---|---|
| `id`, `type`, `title`, `status` | `running` until finished, then `passed`, `failed`, or what `--status` says |
| `started`, `finished` | ISO times with the UTC offset |
| `host` | name, OS, release, architecture, CPUs, RAM, Python |
| `cmeta` | version, `CMETA_HOME`, the engine's path, and its branch and commit for a checkout |
| `repositories` | this repository and each `--repos`: branch, commit, changed tracked files |
| `agent` | from `CMETA_GENERATOR` (agent, model, effort), the Claude Code session (`CLAUDE_CODE_SESSION_ID`), or `--agent`, `--model`, `--effort`, `--session` |
| `command` | `--cmd` |
| `notes`, `results`, `attachments` | `--note`; `--results.<key>=<value>` and `--results_file`; `--attach` (files up to 20 MiB, `--attach_max_mib`) |
| `costs` | `wall_time_s`, `sandbox_mib`, `agent_usage`, `--tokens` (`agent_tokens`), `--cost_usd` (`agent_cost_usd`), `--costs.<key>=<value>` |

Numbers given on the command line are stored as numbers.

## The agent's costs

With a Claude Code session, finishing sums the tokens of the API requests that the
session and its subagents made while the test session was open, from the transcripts
under `~/.claude/projects` (or `CLAUDE_CONFIG_DIR`): requests, input, output,
cache-write and cache-read tokens, by model. That is all the agent's work in that time,
so a session that overlaps another counts the same tokens; `--skip_usage` leaves it out.

With prices configured (USD per million tokens), the cost is estimated too:

```bash
cx config set task --meta.test_session.prices.<model>.input=<price> \
                   --meta.test_session.prices.<model>.output=<price> \
                   --meta.test_session.prices.<model>.cache_write=<price> \
                   --meta.test_session.prices.<model>.cache_read=<price>
```

Without them, record what the agent reports (Claude Code: `/cost`) with `--cost_usd`.

## Remote machines

Run the session on the machine that does the work, so the sandbox is there, and pass
the agent explicitly (the variables stay on the local machine):

```bash
ssh <host> 'bash -lc "cx task run test-session --start --type=vllm-build --agent=\"Claude Code\" \
  --model=claude-opus-5-5 --effort=max --session=<id> --print=id"'
```

For the agent's costs, open a local session for the same work too; at the end attach the
remote `session.md` to it, so one local log holds the whole story.

## Configuration

```bash
cx config set task --meta.test_session.max_keep_mib=4096   # finish keeps sandboxes up to 4 GiB
cx config set task --meta.test_session.repo=<alias>        # another repository than local
cx config show task
```

## Sessions kept as folders before 0.42.0

Earlier versions kept the sessions in `<CMETA_HOME>/tmp/cmeta-tests-<YYYYMMDD>/` and
`<CMETA_HOME>/log/cmeta-tests-<YYYYMMDD>/`. This turns them into artifacts (moving the
sandboxes that are still there, and the attachments) and, with `--remove_old`, removes the
old folders:

```bash
cx task run test-session --migrate [--from=<another CMETA_HOME>] [--remove_old]
```
