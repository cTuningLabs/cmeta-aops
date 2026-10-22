# tool/paperclip

[Paperclip](https://github.com/paperclipai/paperclip) (MIT) is an open-source control plane for teams of AI agents:
issues with goals and blockers, budgets, approval gates, routines, an org chart of agents reached through adapters
(Claude Code, Codex, OpenCode, OpenClaw, Hermes, Gemini CLI, a process, an HTTP endpoint). Its CLI `paperclipai` is
an npm package (Node.js 24.11 or newer); it sets up an instance, runs its server (one Node.js process with an embedded
PostgreSQL; the UI and the API on port 3100) and talks to it.

```sh
cx tool setup paperclip                       # detect, else install the pinned version
cx tool setup paperclip --versions            # what npm publishes
cx tool run paperclip -- --version
cx tool run paperclip -- --help
cx task run run-paperclip                     # its server, in a session of its own (task/run-paperclip)
```

## How it is installed

Into the cache entry, with cMeta's Node.js ([`tool/node-js`](../node-js/README.md)) - not into a global npm prefix
and not through `npx` (which keeps the package in npm's cache and resolves `@latest` at every start):

```sh
npm install --prefix content --no-save --registry https://registry.npmjs.org paperclipai@<version>
```

with npm's cache in the entry, then a launcher `content/bin/paperclipai` (`paperclipai.cmd` on Windows) that runs
`content/node_modules/paperclipai/dist/index.js` with that Node. A Node.js found on the machine that is older than
24.11 is not used: the node-js tool's LTS (24.21.0) is set up instead.

The launcher turns Paperclip's anonymous usage telemetry off (`PAPERCLIP_TELEMETRY_DISABLED=1`, which upstream
honours), unless the caller set the variable.

| | |
|---|---|
| default version | `2026.1012.0` (upstream's CalVer: year, month and day, number) |
| Node.js | 24.11 or newer (`engines` of the package) |
| data | `~/.paperclip` by default; the task `run-paperclip` uses `~/.local/state/paperclip` (`PAPERCLIP_HOME`) |

Tested on Ubuntu 26.04 (the P14s Gen 4) on 2026-10-22. On Windows the CLI installs the same way; its server is run
in WSL2 or on another host (the task says so).
