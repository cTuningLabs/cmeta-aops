# run-paperclip

A [Paperclip](https://github.com/paperclipai/paperclip) server of this user: the CLI of
[`tool/paperclip`](../../tool/paperclip/README.md) run as a background process, with no service, no root rights, and
its data in a folder of its own.

```sh
cx task run run-paperclip                      # start (or find) the instance "default", then its status
cx task run run-paperclip status
cx task run run-paperclip stop                 # its process group; the data stays
cx task run run-paperclip --bind=tailnet       # reachable on the tailnet, with a login
cx task run run-paperclip --on=<host>          # on another machine of the fleet (Windows: --on=wsl)
cx tool run paperclip -- --help                # the CLI itself, afterwards (PAPERCLIP_HOME as below)
```

| Option | Default | What it does |
|---|---|---|
| `--instance` | `default` | Paperclip's instance (`PAPERCLIP_INSTANCE_ID`): its configuration, database, logs and files |
| `--port` | `3100` | the port of its UI and API (`PORT`) |
| `--bind` | `loopback` | `loopback` (127.0.0.1, trusted local mode, no login), `lan` or `tailnet` (reachable from there; `PAPERCLIP_DEPLOYMENT_MODE=authenticated`: a login) |
| `--data_dir` | `~/.local/state/paperclip` | the data root (`PAPERCLIP_HOME`), apart from the `~/.paperclip` of an `npx paperclipai` of the user |
| `--wait` | `180` | seconds to wait for `/api/health` (the first start sets up its database) |
| `--version` | the tool's pinned one | the version of the CLI |

## What start does

1. The CLI through `cx tool setup paperclip` (installed with cMeta's Node.js when missing).
2. The first time - no `<data_dir>/instances/<instance>/config.json` yet - `paperclipai onboard --yes`: Paperclip's
   quickstart defaults (an embedded PostgreSQL, local disk storage, no LLM provider), then the server. Later starts:
   `paperclipai run` (a doctor with repair, then the server).
3. In a session of its own, so that it outlives the shell and an ssh connection that started it; its output in
   `<data_dir>/cmeta-<instance>.log`, its pid in `<data_dir>/cmeta-<instance>.pid`; telemetry off
   (`PAPERCLIP_TELEMETRY_DISABLED=1`, `DO_NOT_TRACK=1`), no browser (`PAPERCLIP_NO_BROWSER=1`).
4. A wait until `http://127.0.0.1:<port>/api/health` answers.

An instance that already runs is found again. `stop` ends its process group (its embedded PostgreSQL shuts down with
it). An LLM provider, the agents and the companies are Paperclip's own settings: its UI, or
`cx tool run paperclip -- configure` with the same `PAPERCLIP_HOME`.

## Limits

- Linux and macOS. On Windows: `--on=wsl`, or `--on=<host>` for a machine of the fleet.
- Local Claude or Codex subscriptions as agents need the provider's CLI on the same machine (`cx tool setup claude`,
  `cx tool setup codex`) and Python 3, as upstream says.
- Paperclip keeps its work in its own PostgreSQL; cMeta does not read it. The record of a project stays its cMeta
  artifact (with run-ai, its `!AI` folder); Paperclip's company export (`paperclipai` "company packages") is the way
  to keep a copy of an organisation in an artifact.
