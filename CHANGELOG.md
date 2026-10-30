# Changelog

All notable changes to cMeta AOps are documented here, newest first.

## 0.60.0
- **`tool/nvidia-driver`: the NVIDIA driver installed and upgraded by cx.** `cx tool setup nvidia-driver --status` shows
  the installed driver and the newest one for this GPU, and `cx tool upgrade nvidia-driver [--version=<branch or
  release>]` installs it with NVIDIA's own packages:
  - **Windows:** the driver NVIDIA's download service lists for the GPU, on both branches (production and new
    feature). Its NVIDIA signature is checked, and it runs silently with administrator rights (a UAC prompt; a quiet run
    asks for nothing, so it refuses in a terminal that is not elevated).
  - **Linux:** the `.run` installer of NVIDIA's archive, checked against its sha256 and built by DKMS with the kernel
    module type in use. It is installed next to the running driver, and the next boot loads it. A driver from the
    distribution's packages, or Secure Boot, is refused.
  - **Older GPUs** stop at their last branch: Maxwell, Pascal and Volta at 580.
  - After an install the cached record of `tool/cuda` is dropped, so `tool/nvcc` reads the new driver. Since CUDA 13.1
    on Windows and 13.4 on Linux the toolkit installers carry no driver.
- **`tool/nvcc` knows its newest version:** the nvcc of the newest CUDA release this driver and GPU run (NVIDIA's
  list of releases), so `cx tool setup nvcc --status` says whether it is outdated and `cx tool upgrade nvcc` installs
  that toolkit into the cache.
- **task/setup asks a tool for its newest version:** a `latest_version()` in the tool's API answers when the newest
  version depends on the machine (the driver of its GPU). A tool with `installs_into_system: true` is not said to
  come from another channel because of where its files are.

## 0.59.0
- **Mistral Vibe, the eighth harness of run-ai.** `tool/vibe` installs the PyPI package `mistral-vibe` with cMeta's uv
  into an environment of its own inside the cache entry (a CPython 3.12; nothing in the user's Python, no PATH change)
  and lists its releases from PyPI, so `cx tool upgrade vibe` works; `task/run-vibe` runs it headless (`-p`, or
  `--prompt-file` for a long prompt) or interactive, `--yes` is `--auto-approve`, and the export of an `--output-dir`
  gives the tokens, the cost and the session; `cxai --harness=vibe` (`--login` = `vibe --setup`).
- **`cx tool install <tool>` and `cx tool upgrade <tool>`:** `cx tool setup <tool> --install` and `--upgrade` in short.
- **`--check_versions` works, for the tool named on the command line:** the cached version is re-detected and a
  stale entry replaced (a driver updated under the cache: the laptop's record said CUDA 13.3 while the driver gave 13.2).
  The reader took a missing `skip_cache_version_check` as true, so nothing was ever checked; the global
  `check_versions` setting and the nested tools stay unchecked on purpose - a check of every reused tool costs seconds
  per run (a CUDA chain) and would throw away the entries of tools that update themselves.

## 0.58.0
- **A project remembers its harness: `run_ai_config`.** A project that is a cMeta artifact keeps the harness, the model
  and the effort of its last run in its `_desc.yaml`, and `cxai` / run-ai without those flags takes them again; a flag
  changes them. The model and the effort travel together and only with their harness. Only that block is written (the
  rest of the file, comments included, stays); nothing is recorded by a dry run, the listing views, `--no_log`, a
  scratch workspace or a plain folder.
- **A run no longer inherits a parent's gateway, for every harness.** A gateway run names the variables it puts into its
  process (`CMETA_AI_GATEWAY_VARS`); every harness task run-ai drives (Claude Code, Codex, OpenCode, OpenClaw, Gemini
  CLI, agy, Hermes) drops those of a parent's gateway first - OpenClaw's claude-cli backend went through the parent's
  gateway, OpenCode and Hermes saw its key. A login run of Claude Code, Codex or OpenCode also drops the variables that
  harness reaches its models with, wherever they came from: `ANTHROPIC_*` (also the `DEFAULT_*_MODEL` names a login
  kept until now), `OPENAI_*` / `AZURE_OPENAI_*`, and for OpenCode every provider it reads (OpenAI, Mistral, Google,
  OpenRouter, ...). The user's own keys stay for the harnesses whose keys are one of their ways in. One list:
  `drop_provider_variables` in the task category's `ctask.py`.
- **`test-on-hosts` starts where there is no system Python, and says when a runner never started.** The POSIX launcher
  takes `python3`, else the Python of the host's `cx` (a bare container has none: its round never started); peek finds
  the runner's process and says `running`, `stopped` (it ended before its last command) or `not started` (with the
  launch's own reason) - such a host was `running` for ever - and a round where nothing runs any more is `finished`;
  collect skips a host where the round did not start.
- **`cx host push` / `pull` into a container or WSL distribution without a declared user** put a relative path under
  the instance's own home (`printenv HOME`), as an ssh host does - a bare ubuntu image runs as root, and the files
  landed under `/` instead of `/root`.

## 0.57.2
- **`upgrade-os --windows_update` works over ssh and asks nothing:** Windows Update installs nothing for a remote
  logon ("Access is denied"), so the install runs as SYSTEM in a scheduled task of its own, which the new
  `windows-update.ps1` of the task registers, waits for, prints the log of and removes. The stock PowerShellGet of
  Windows asked whether to install the NuGet provider before `Install-Module PSWindowsUpdate`, and a run over ssh
  waited for an answer nobody could give: now `-NonInteractive`, TLS 1.2 and the NuGet provider first. Software
  updates only (`-UpdateType Software`: no drivers).
- **`upgrade-os` on WSL and any Linux with files mounted over those of packages:** WSL mounts its kernel's `perf`
  read-only over the `/usr/bin/perf` of `linux-tools-common`, and dpkg could neither back it up ("Invalid
  cross-device link") nor replace it - the upgrade stopped with dozens of packages unpacked and not configured. The
  new `file-mounts.sh` of the task moves such mounts (regular files of packages under the system folders, never
  `/etc`) aside before the upgrade and back after it, also after a failed one; with apt, `dpkg --configure -a`
  first finishes what a run cut short left.
- **Shell scripts are LF in every checkout** (`.gitattributes`: `*.sh text eol=lf`): a Windows clone with Git's
  default `core.autocrlf=true` gave them CRLF, and they run on Linux and macOS - `file-mounts.sh` from the tree
  (WSL reads a Windows clone), the container's `entrypoint.sh`, the host probes.
- **`upgrade-os --check` says how much is pending** on its verdict line (`pending: 12 packages`, the macOS updates by
  name, brew packages, winget apps, Windows updates), since `cx host upgrade --check` shows only the last lines of
  each host (on a Mac the update's label and the `brew outdated` list were lost among brew's own news). After an
  upgrade, a macOS update that is still listed with `Action: restart` means a reboot is due, with the command that
  installs it at its restart.
- **`test-on-hosts` on a Windows host:** the launcher, the peek and the removal were bash scripts for every remote
  host, so a round could not start on a Windows host. A Windows host gets PowerShell: the runner started through
  WMI with the Python of its `cx`, its commands in `commands.json` (`runner.py <root> <tree> @commands.json`).
- **`test-on-hosts` leaves out links that lead out of the tree:** a git-ignored link to another clone went into the
  tarball, and the tarfile of Python 3.14 refuses to unpack a link to an absolute path - the round failed at once.
- **`cx host run --script` on a PowerShell host like a command:** the script runs with `-ExecutionPolicy Bypass`, as
  a command already did (under Windows' default policy an `Import-Module` of a gallery module in a script waited
  without a word), and without progress records. A PowerShell host writes its errors to stderr as a `#< CLIXML` blob
  when it runs what cx sends with `-EncodedCommand`: captured output now shows their text.

## 0.57.1
- **`cx host restart` requires what answered before it:** the projects of the host are checked once just before
  the restart, and only the checks that answered then must answer again; a server started on demand only (down
  before the restart, down after it) is reported with a note instead of failing every restart of its host, as it
  did in 0.57.0. A check that cannot run before the restart counts as required.

## 0.57.0
- **`cx host restart` waits for the servers it brought up.** A host with `projects` is checked after its
  `after_restart` commands as `cx host status` checks it - each server on the host, its public URLs from here -
  every 15 s until all of them answer or `--check_timeout` (300 s) runs out; one that still does not answer makes
  the restart fail (exit code 1, the projects named), and `cx host upgrade --restart` with it. A launcher that
  detaches returns 0 at once, so its exit code said nothing about the servers: a site's backend that failed at
  every start after a reboot went unseen for two days. `--skip_check` restarts without the wait; `--skip_after`
  skips it too.
- **`cx host status` behind a VPN that splits per program:** when this machine refuses Python's own socket
  (WinError 10013 - a local firewall, or a VPN with per-program split tunnelling that lets ssh out and not Python),
  an ssh host is asked through its own ssh command (`exit` there, about a second, and only then): `up`,
  `down (through ssh)` or `timeout (..., through ssh)` instead of every such host shown as down. The status checks
  run with stdin closed: Windows' ssh.exe on a console stdin (a cserver or a `cx` started in cmd.exe) waits for a
  key after the remote command ended.
- **The public URLs of one site tell apart:** `cx host status` names a public URL by its host and the folders before
  its file (`example.org/wiki`, `example.org/cm/repo`; `example.org/healthz` stays `example.org`) instead of the host
  alone; the full URL stays in the ADDRESS column.

## 0.56.1
- **A login run is a login run:** `run-claude` with the login (the flag, a project's `ai_gateway: login`, the config)
  drops the gateway variables inherited from the parent process (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
  `ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS`) before starting Claude Code: an import launched from a session that
  runs through a company gateway (the HubSpot and Teams fetches, 2026-10-27) found the claude.ai connectors switched
  off ("ANTHROPIC_API_KEY ... takes precedence over your claude.ai login"); it says which variables it dropped.
- **A stopped website lets its port go:** `__run_server.sh --stop` (manage-cmeta-project `kill_tree`) ends with
  SIGKILL any process of the server's tree that is still alive after the SIGTERM and the wait - the worker processes
  of the site's process pool survived a stop and kept the port, so the next start failed with "address already in
  use" (the Dapple Labs site, 2026-10-27).
- **run-ai with OpenCode reads its context folders and finishes a one-prompt run:** the folders handed over with
  `--add-dir` are outside the project, which OpenCode's permission `external_directory` asks about - and refuses in
  `opencode run` - so `OPENCODE_CONFIG_CONTENT` now allows them (subfolders included); a refused tool call ended
  OpenCode's loop with no answer at all (1.18), so a headless run sets `experimental.continue_loop_on_deny` and the
  model is told about the refusal instead. A test covers the configuration.

## 0.56.0
- **`cx host sync` finishes and proves it.** A failing repository no longer stops the run: every repository of every
  selected host is synced, and a failing bisync is repaired where the cure is known and run again - a stale lock
  dropped, rclone's delete guard ("too many deletes") passed with `--force` only when the side that lost the files
  is still a repository (its `_cmr.*` there, not empty; the host keeps its copies in its sync-backup artifact), a
  new pair seeded from this machine, a transient error tried again (`--retries`, 2). A pair that needs a new
  baseline while both sides hold files is reported with the `--resync ... --dry_run` to read: which side wins is a
  person's call. After every sync the two sides are compared name by name and size by size (`rclone check` with the
  sync's filters, one way for a copy): a CHECK column (`identical (2384)` or the differences, the listing kept in the
  bisync workdir), a difference right after a sync - a file changed during the run - synced once more. Conflict
  copies rclone left (`<name>.conflict1/2`) are noted; the ones of a memory index (`MEMORY.md`, two sessions each
  adding a line) are merged by line union and settled on both sides by the run; a conflict made by the run is named
  as a problem. The run ends with `STATUS: SUCCESS` or `STATUS: FAILED` in large letters with the problems under it,
  exits 1 when anything needs a person, and waits for Enter at a terminal on problems (never with `-q` or
  `--pause-`). `--skip_check` turns the check off. A git repository says what its pull did. The task
  `rclone-to-ssh` hands its output back on request (`capture`: no colour, the return code judged by the caller).
- **The indexes follow the files:** after a sync that moved files the repository is reindexed where its files
  changed - the host after a git pull or a copy, each side of a bisync whose rclone listings show a changed meta
  file (`_cmeta.*`, `_cmr.*`): an artifact by itself here, the whole repository when a meta is gone. A sync of
  records only touches no index; `sync: after: [cx --reindex]` is no longer needed.
- **X11 from Windows:** `cx host ssh --x11` forwards with `-Y` and sets `DISPLAY=localhost:0.0` for the client when
  it is unset; `cx host ssh --screen --x11` hands the display to the windows of the session (the attach writes
  `~/.cmeta-screen-display`, the windows' prompt hook sources it), so a window made before the login opens X11
  programs too. `cx host upgrade` of a uv-tool engine installs pip into the tool environment.
- **run-openssh on Windows runs the server on a hidden desktop** (`--hidden_desktop`, on by default), so the console
  window of every command a client runs stays off the screen; the server's output reaches the log through a pipe.
- **Docs and examples** with neutral names for the hosts, the gateway and its secret.

## 0.55.2
- **Login or a gateway for every AI run:** the new category `ai.gateway` - an artifact per place that serves models
  (a company's gateway such as Azure API Management in front of OpenAI and Anthropic, a vendor's own API, a llama.cpp
  or vLLM server here or on a host): the base URL, the wires it speaks (`anthropic`: the Messages API; `openai`: chat
  completions and the Responses API), its catalog, how the key travels and which `secret` artifact holds it, never a
  value (`cx ai.gateway ls | models | test | connect`). The new task `set-ai-gateway` makes the choice for a run - the
  flag, the project's `_desc.yaml` (`ai_gateway: <alias> | login`), this machine's `config::default`
  (`run_ai_gateway_<harness>`, else `run_ai_gateway` with `run_ai_gateway_name`), else the tool's own login - and gives
  the harness what it needs. `--gateway=<alias | login>`, `-gw` (the configured gateway) and `-ln` (login) on
  run-claude, run-codex, run-opencode and run-ai; the same tools, the bill moved to the gateway's credits or a local
  model; run-ai records the gateway of every run and `--list_models --gateway=<alias>` lists the gateway's catalog for
  the harness. Claude Code speaks the Anthropic wire only; Codex the Responses wire (`codex_wire: chat` for a chat-only
  server); OpenCode both. On an API key Claude Code has no claude.ai connectors: run-ai says so at the start of a
  gateway session.
- **An interactive OpenCode session takes its prompt through `--prompt`:** the positional argument of `opencode
  [project]` is the folder to open, so the hand-over prompt run-opencode appended as a positional ended with "Failed
  to change directory to <cwd>/<the prompt>"; `opencode run [message..]` keeps the positional.
- **A gateway that does not answer is an error with its start command:** `cx ai.gateway connect` (and so
  `set-ai-gateway` and every harness run) probes the catalog of the wire the harness speaks and fails naming the URL
  and the `provided_by` command of a local server - a harness is never started without a model towards a dead
  gateway, where OpenCode could fall back to a provider it is logged into.
- **`run-llama-cpp-server`:** a llama.cpp server on this machine, detached, with the Anthropic, chat and Responses wires
  on one port (8686 by default, not llama.cpp's crowded 8080), its record and log in the state artifact
  `local:llama-cpp-server-<port>`; `--action=status|stop`; a 32k context by default (Claude Code's first request alone
  is about 17k tokens) and the GPU layers left to llama.cpp's `--fit` (`--gpu_layers=auto`: a model larger than the
  GPU's memory keeps part of itself on the CPU; a number pins `-ngl`); it runs inside an instance of the run-on-any-host
  design too (`--on=<instance> --host=0.0.0.0`, the port published when the instance is made); the model from a model artifact (`hf-Qwen@Qwen3-8B-GGUF`
  by default, `hf-ggml-org@gpt-oss-20b-GGUF` the larger one), the tool for `--compute=cuda|cpu|metal`. The artifacts
  `ai.gateway::anthropic` and `openai` (key-less examples) are in this repository; a fleet's own gateways and its local
  servers (`llama-cpp-local` on 8686, `vllm-local` on 8868) live in its private repository.

## 0.55.1
- **A server as the world sees it:** `projects: <name>: server: public: [<url>, ...]` names the public URLs of a
  project's server (a site behind a tunnel or a proxy); `cx host status` checks them from this machine, one line
  each under the project - `works` (HTTP 2xx or 3xx, a redirect not followed), `http <code>`, `timeout`,
  `unreachable` - so a site that serves while its host's ssh is down shows as such; a `server.url` that is not a
  local address is checked from here the same way. The rows carry them (`projects[].public`); the host page of the
  cserver shows them as links.
- **The sync backups are result artifacts:** what `cx host sync --backup` and `cxt sync` keep goes to the result
  artifact `sync-backup--<repository>` (`sync-backup--<alias>--<uid>` for a named sync) of each side's `local`
  repository, under `<the other side>/<run id>/` (`<run id>/` for a named sync) - listed by `cx result ls`; the host's
  copy gets its `_cmeta` after a run that put files there (and a reindex of its `local` for `cx host sync`). The
  remote side of a named sync uses the `local` repository of the host's cMeta home (its declared `sync: repos_path`,
  else the probed home; `cx host sync_endpoint` carries it), whatever folder is synced: a web root's parent belongs
  to root, and rclone moves the replaced files, so the synced folder and the home must share a filesystem. Before:
  `.cmeta-sync-backups/` beside the synced folder, which no index knew.
- **A pair's identity is its own definition, not the task's built-in filters:** a built-in state filter added by a
  release (this one added `- **/result/sync-backup--*/**`) made every named sync stop with "endpoints/filters changed;
  review --plan, then explicitly use --resync". The identity now digests the definition's own filters, the mode and the
  endpoints; a state digested the old way (0.55.0 and before) is accepted and rewritten at the next success. The backup
  artifact of a pair carries `backup_of`, not `sync_uid` (which is how the pair's state is found).
- **The step that marks a sync's backup artifact on the host cannot hang:** its rclone calls run with the sftp
  hash check off (an `lsf` through the external ssh never returned without it, and a finished sync hung for ever)
  and a time limit; a failure of that step is a warning on stdout, never an error of the sync that succeeded.

## 0.55.0
- **A machine serves the fleet with the key the fleet reaches it with:** `cx task run run-openssh --host=<the host
  artifact this machine is>` allows the public key of that host's `access: key`, as this machine finds it. New:
  `cx host key <host | <category>::<artifact>/<file>>` - the key file cx uses for a host (the artifact the reference
  names when it is here, else the copy a secret holds, else `~/.ssh`) and the public key beside it; it prints paths,
  never a key. `--keys` of run-openssh takes references too: `secret::<alias>` (the secret's `ssh.public_key`) and
  `<category>::<artifact>/<file>` (a private key named there stands for the `.pub` beside it); a private key file is
  refused. Without `--host` or `--keys` the user's `~/.ssh/authorized_keys` is allowed, as before.
- **`cxai`** (cMeta 0.37.6) is named beside `cxt run-ai` in the documents of run-ai: `cxai ...` = `cx task run run-ai ...`,
  `ucxai` with a bare `--home` first.
- **run-openssh in the foreground, to watch it:** `--foreground` keeps the server attached to the console that started it
  (its log on the screen instead of the log file; Ctrl-C, the window closed or `stop` from another window ends it);
  `--sshd_log_level=INFO|VERBOSE|DEBUG..DEBUG3` is sshd's LogLevel (VERBOSE: every session started - shell, command or
  subsystem - with the client's address; sshd never prints a command's text). The name avoids `--log_level`, cMeta's own
  flag, which swallows a task parameter of that name. Two lines of noise gone from the log: sshd writes its pid file
  into the server's folder on Windows too (no "Couldn't create pid file __PROGRAMDATA__\ssh" - a user cannot write
  there), and the readiness and status probes bind the port instead of connecting to it (OpenSSH 9.8+ wrote a
  "penalty ... connections without attempting authentication" line for each probe).
- **`cxt run-ai --cx`** is `--harness=codex` in short (an error together with another `--harness`).
- **`cx host sync --backup`:** what a run overwrites or deletes is kept in `.cmeta-sync-backups/<repository>/<run id>/`
  beside the `repos` folder of each side (rclone's `--backup-dir1` / `--backup-dir2` for a bisync, `--backup-dir` on the
  host for a copy; nothing for git) - the convention of the named syncs of `cxt sync`, which keep such a backup on every
  run; outside every repository, so never indexed; nothing prunes it.
- **`cx host screens <host> --quit=<name>`** ends that Screen session there (its shell and what ran in it - a cancel for
  a run-ai session started on another machine), then lists what is left; the answer says whether Screen found it.
- **`cx host status` asks sshd for its identification line,** not only for an open port: a host whose port accepts and
  closes at once is `refused`, one that stays silent is `no banner` - neither can run a command, and the table said `up`
  for both (a VM of 2026-10-25: up in the table, every ssh reset). The projects of such a host say `host
  refused` / `host no banner`.
- **A tool without compiler flags is refused as a compiler** by setup-compile (before: `--use.compiler-c.name=llvm` on
  Windows ran `clang program.c` with no flags, built `a.exe` and stopped at "Target file hello was not created"); the
  message names the mistake: the toolchain is `llvm`, the compiler `clang`.

## 0.54.2
- **`cx host screens <host>`:** the GNU Screen sessions of a host's user from here - name, pid, state (attached,
  detached), the start time where Screen prints one and the titles of the windows (a run-ai terminal shows its
  project) where Screen answers `-Q`; read only (nothing installed: no Screen means no screens), exit 0 also when there
  is none, `--tags` / `--machine` / `--type` for several hosts.
- **The persistent terminals work with any GNU Screen** (the user's rule: tools adapt to every version): the launch
  asks for no version any more (0.54.1 asked for 4.2 or later). A Screen with `-Q` (4.2+) lists the windows of an
  existing session before attaching; an older one answers `-Q` with its usage and exit 1, so nothing is listed, and
  creating, detaching and reattaching work the same - checked for real with Screen 4.00.03 (macOS), 4.08, 4.09 and
  5.0. The list of windows now asks the Screen the session runs with (before: the first `screen` on the PATH, Apple's
  4.00.03 on a Mac whose sessions run with Homebrew's). The lifecycle test runs with whatever Screen is installed,
  reads the window title only where `-Q` exists and reconnects as a real client does (Apple's 4.00.03 accepts a
  reattach about a second after a drop, no earlier).
- **`cmd_get_version_exit_codes` in a tool's `_desc.yaml`:** the exit codes of `cmd_get_version` that still carry the
  version (default `[0]`). `tool/screen` declares `[0, 1]`: macOS's own `/usr/bin/screen` (4.00.03) prints its version
  for `-v` and exits 1, so the detection never took it before; of several copies the newest is used (Homebrew's next
  to Apple's).

## 0.54.1
- **The persistent terminals ask for GNU Screen 4.2 or later:** `cx host ssh --screen` and `--on_screen` read a
  session's windows with `-Q` (Screen 4.2), so their launch asks `cx tool run screen --version=">=4.2"`
  (`SCREEN_VERSION` of the host category); `tool/screen` itself still takes any version. macOS ships Screen 4.00.03
  in `/usr/bin`, so on a Mac the setup takes Homebrew's current Screen (it asks before installing; `-q` installs);
  `tool/screen` searches Homebrew's folders on macOS even when a non-login shell lacks them on its PATH.

## 0.54.0
- **run-ai resumes an existing workspace automatically:** plain `cxt run-ai` finds the nearest `!AI` in the
  current directory or its parents and continues that workspace's latest conversation without asking. This
  works inside dated scratch workspaces and their subdirectories, as well as ordinary folders. Detection
  stops at a known cMeta artifact or repository boundary; an explicit `--project` still wins, and `-l` starts
  a fresh workspace.
- **run-ai scratch projects and first-run confirmation:** `-l` / `--log_project` creates a new dated workspace
  under the active home's local `log::task-run-ai` artifact, with its own `!AI`. Its directory is named
  `YYYYMMDD-HHMM`; `-l="quick question"` adds `.quick question`. A prompt uses `--prompt="..."` separately.
  Names are portable and collisions get a numeric suffix. The agent works there, and the directory is printed
  before and after it runs. A first real run outside cMeta asks before creating a new `!AI` (Enter continues);
  `-q` keeps unattended behavior, existing `!AI` folders do not ask again, and dry runs create nothing.
- **Persistent interactive terminals:** `cx host ssh <host> --screen[=<name>]` creates or reconnects a GNU Screen
  shell (`cx-host` by default). `cxt run-ai --project=<cRef> --on=<host> --on_screen[=<name>]` does the same for
  run-ai (default `run-ai`; other task commands use their artifact alias). SSH disconnections leave the command
  running; repeating the name attaches without starting it again or resubmitting the prompt. Existing window
  titles identify the project; normal shell/task exit closes its last window. GNU Screen is a cMeta tool on the
  POSIX target. The flags require an interactive terminal and refuse incompatible cleanup/detach options.
  Explicitly empty values (`--screen=` / `--on_screen=`) also choose the default name, for batch launchers
  with an optional argument; omitting the flag keeps the ordinary behavior.
- **`cx host backup` and `cx host restore`: what only a host holds, kept in its machine artifact.** A host's
  `backup:` block names its config artifacts, state, secrets, start scripts (`paths`, relative to the login home or
  absolute; `{path, files: [globs]}` for a few files of a folder) and root-only files (`sudo_paths`, copied through a
  staging folder with passwordless sudo); `cx host backup <host>` copies them into
  `<machine>/backup/<host>/<YYYYMMDD-HHMM>/` with `backup.yaml` (where each entry came from, its size and the mode of
  every file inside), `keep: N` dated backups. `cx host restore <host>` puts the newest one back - or `--source=<a
  backup folder>`, the backup of the host a rebuilt one replaces - with the recorded modes (sudo for root-only entries),
  makes a folder that was empty on the host again, then runs `backup: commands: after_restore`; `--into=<folder>` lands
  everything under a folder instead (a look, or a test on a disposable host), `--paths=a,b` restores a part, a
  production host needs `--yes`; nothing on the host is deleted by a restore. Tested by restoring a production VM's
  backup into a folder of a test host.
- **run-ai on several machines:** a project's `!AI` folder can be bisynced between machines and worked on from
  either. Every run record names its host (`--conversations` shows `on <host>`); `!AI/log/<stamp>.running` marks a
  live run (removed when it ends, also when the harness dies), and the next run reports one of another machine in
  one line - `--other_runs=ask|refuse` (config key `other_runs`) asks or refuses instead, a marker of this machine
  whose process is gone is removed. The two copies rclone bisync keeps of a file changed on both sides
  (`<name>.conflict1`, `.conflict2`) are folded back at the start of every run and of `--conversations` for run-ai's
  own records (the conversation's runs and sessions merged, the transcript's segments kept) and listed for the agent
  to merge for memories and skills. The orientation tells every harness to write a location inside an artifact as
  `{{{<category>::<alias>,<UID>}}}/<relative path>`, which resolves on any machine; `--project=<cRef>` with the task
  engine's `--on=<host> --on_detach` starts a run on another machine that outlives this one.
- **host: a partial repository (`artifacts:`):** a repository too big to copy travels as a selection of its
  artifacts, two-way like any other: `artifacts:` in its sync entry (or `--artifacts="a;b"` on a push) takes cRef
  patterns - `fgg.project::cMeta/!AI` (a path inside an artifact, with its `_cmeta` and `_desc`), `work::2026*` (a
  folder glob through the category's shard folders, so an artifact made later on either side is in it). The
  repository's `_cmr.yaml` and the definitions of the categories it holds itself come along (not those of a
  repository nested in its folder), and the first sync or push plugs it on the host. A filtered bisync is kept safe:
  the rules of the last run are recorded beside rclone's listings and a run whose rules changed stops and asks for
  `--resync`. `PARTIAL.md` at the root of the host's copy says what it holds, from where and since when. A partial
  repository is never pushed whole.
- **host: the keys of another orchestrator, and a repository of secrets:** a host key named by a reference whose
  artifact is not on this machine (`key: fgg.crypt::ssh-x/2026/id_ed25519` on a second orchestrator) is the copy a
  `secret` artifact holds (its `files.from` and `files.names`), before the old fallback to `~/.ssh/<name>`, which now
  warns. A repository with `secrets: true` is never synced; `cx host push <host> <repo> --artifacts="secret::a;..."
  --secrets` sends the secrets a host needs, by name, into a folder only its user can read, plugs it and runs
  `cx secret check --fix` there. `cx host push` also takes a repository registered here by its alias.
- **secret: `cx secret which` and `cx secret check --fix`:** `which <category>::<artifact>/<file>` names the secret
  holding a copy of that file and its path; `check --fix` makes a key of the artifact that others can read
  owner-only (a copy over sftp arrives as 664). `cx secret ls` shows the repository of each secret again.
- **tool/paperclip and task/run-paperclip:** [Paperclip](https://github.com/paperclipai/paperclip) (MIT), a
  control plane for teams of AI agents. The tool installs its npm CLI `paperclipai` (2026.1012.0) into the cache
  entry with cMeta's Node.js 24.11+ (an older Node found is replaced by the node-js tool's LTS), with a launcher that
  turns its telemetry off. The task runs a server of this user: onboarded with the quickstart defaults the first time
  (an embedded PostgreSQL), then `paperclipai run`, in a session of its own, its data in `~/.local/state/paperclip`
  (`--data_dir`), loopback by default (`--bind=lan|tailnet` with a login), until `/api/health` answers; `status` and
  `stop`. Linux and macOS (Windows: `--on=wsl` or a host).
- **`--on_detach` and `cx host run` from a Windows terminal keep quoted words intact:** a detached run asks for no
  terminal, so its words reach the host on stdin from a temporary script; a command run WITH a terminal that holds a
  double quote, `^`, `%` or a line break travels base64-encoded to a POSIX host and runs there from a temporary
  script. Before, cmd.exe stripped the double quotes on the way to ssh.exe and bash saw `'''...'''` ("syntax error
  near unexpected token `('").
- **run-ai: `--login` and `--login_status`:** a harness signed in on this machine, in this terminal, through its tool
  (`cx tool run <tool> -- <words>`: the tool set up first when missing) - the words are facts of each tool's
  `_desc.yaml` (`login:`, `login_status:`): claude `auth login` / `auth status`, codex `login --device-auth` (a URL
  and a code, no callback port: works over ssh) / `login status`, opencode `auth login` / `auth list`, openclaw
  `onboard` / `models status`, hermes `model`, antigravity and gemini an interactive start. With `--on=<host>` from a
  terminal it signs the harness in there. `--login_status` needs no terminal.

## 0.53.0
- **Retired hosts and machines:** `retired: true` in a host's or a machine's `_desc.yaml` keeps its record
  without contacting its old endpoint. `cx host ls` and `cx host status` show `retired` (status skips the
  transport and project-server checks; `--active` leaves it out), `cx machine ls` gets a STATUS column, and
  JSON rows and `show` carry `retired` and `status`. Retirement is declared, never inferred from a failed
  connection or an alias; a machine and its hosts are retired separately.
- **run-website: the repositories in place for Docker:** `--repositories=global` now works in Docker too: the
  repositories of the website task, of its inputs and of the tooling are mounted into the instance and
  plugged into its own home, and the worker comes from there. A state prepared that way keeps no `src/`,
  `inputs/` or tooling copy, so an edited or synced recipe is what the next start runs; a state without
  copies refuses an isolated run. Natively, `global` runs the orchestrator's launcher instead of a copy.
  Isolated deployments are unchanged.
- **run-website: `deployment.data`:** a website task may name a result for what the site changes while it
  runs (logs, uploads); it is made on first use, bind-mounted read-write like the backups (a host folder,
  also on Windows) and described in `CMETA_ARTIFACT_MOUNTS` as `data`.

## 0.52.0
- **tool/cmeta: cMeta 0.37.5 by default** (declarative website task adapters in the engine).
- **secret: a secret of kind file names its file as `file: {path: files/<name>}`:** `cx secret show` and
  `cx secret check` see it, and `check` reports any other reader of a token or a file secret the way it did
  for a private key.
- **`cx host status` / `cx host ls`: project rows in the host columns:** the projects of a host are printed
  aligned under its row (status, health URL, versions after the last column). The host rows returned to
  programs also carry the address, the artifact UID, the tags and whether the host was made from a template.
- **Website instances in the invoking cMeta home:** a `project.yaml` with `home: current` describes a site that
  runs in the home that calls it (one site on a machine with its global repositories) instead of in a project
  home of its own. `manage-cmeta-project` checks the declared repositories, creates the instance's `state`
  artifact (data, secrets, runtime) and generates `__info`, `__run_server`, `__run_server_in_docker` and
  `__run_server_nohup.sh`, plus `___sync_all.bat`/`.sh` from a `syncs:` list (`host::` steps run
  `cx host sync`, the others `sync --require-initialized --live`). A native run starts in the background with
  `--detach` and answers `--status`, `--logs` and `--stop` (the whole process tree). A Docker run mounts the
  declared repositories read-only by alias, the state's data read-write (shared with native runs) and its
  secrets read-only, and keeps an empty-seeded persistent local repository in the state. `{state}`,
  `{secrets}` and `{cmeta_home}` in the declared parameters expand per mode. Project homes keep their behavior.
- **sync: optional removal of empty directories:** `remove_empty_dirs: true` in a bisync definition (or
  `--remove-empty-dirs` for one run) removes the included empty directories on both endpoints after a
  successful run, including the empty ancestors of deleted artifacts. Transfer roots, excluded and nonempty
  directories are kept, a dry run only previews, and an established baseline needs no resync. Off by default.
- **Standalone cMeta projects:** `manage-cmeta-project` bootstraps/adopts a project home,
  discovers its repositories and generates thin root shell scripts for setup, reindex,
  Git updates and native/Docker execution. Optional new venvs inherit the invoking
  Python/cMeta unless explicitly overridden; existing environments are preserved.
  `run-website` can use these projects or run natively in the current home. Docker
  data is seeded once into a persistent host local repository; legacy website state
  deployments remain compatible. No automatic remote deployment or sync is added.
- **Windows-owned website deployments:** `run-website --mode=docker` can create protected state in the
  Windows orchestrator while its legacy runtime uses an artifact-owned Linux volume. `get-host--docker`
  supports optional state-volume storage, persistent UID-based ownership records and labels, refusal of
  missing/foreign volumes, and retained volumes across container recreation. Existing bind mounts remain
  compatible. Portable source/diagnostics and completed backup results stay visible in Windows; generated
  Bash launch scripts use LF line endings. Host recreation checks registered volumes before starting.
- **Website deployments inside cMeta:** new protected `state` category holds mutable deployed source,
  private repositories/environments and service volumes. `run-website` stages a movable recipe and its
  checked result inputs once, then runs that same task natively or through Docker with separate result
  backup histories. Private-home paths rebase when state moves; source edits survive preparation.
  Optional declared Linux software capture supports native execution without installing host services.
  Selected Docker mounts now also accept contained state subdirectories; existing result/cache roots
  and named volumes retain their behavior.
- **Selected artifact mounts for Docker instances:** container templates can declare `instance_artifacts`,
  or tasks can pass `--on_artifacts.<key>=result::local:<name>`, to bind individual host cache/result roots.
  Writable results are created if missing; read-only mounts must exist. The container receives paths in
  `CMETA_ARTIFACT_MOUNTS`. Real paths support state on another disk without sharing the host's local repo.
  Existing named-volume instances retain their mounts; saved Docker arguments replay correctly on Windows.
- **Elasticsearch and OpenSearch tools:** detect existing installations or install checked official archives
  with their bundled Java runtimes. Defaults live in each tool's description, with standard explicit-version,
  version-list and update controls. Setup does not start a service or configure security/data storage.
  Windows launchers avoid cmd delayed-expansion damage to paths containing `!`.
- **Complete release distributions:** the shared release installer can retain a full archive tree and check
  per-asset SHA-512 files, alongside its existing single-binary/SHA-256 behavior. Extraction rejects escaping
  paths/links and special files.

## 0.51.0
- **`tool/cmeta` installs cMeta 0.37.4 by default** (was 0.37.1).
- **Optional persistent instance volumes for container templates:** `get-host--docker` accepts
  `instance_volumes` with `{instance}` / `{home}` placeholders. A template can keep its own CMETA on a named
  Linux volume across container recreation, without sharing the orchestrator's local repository or cache.
- **Tools at newer default versions**, after an exploration of the pinned and the newest versions on Windows, Linux
  and macOS (`cx tool check-updates`, `explore-tool-versions` on each machine through `test-on-hosts`, `--promote`):
  ansible 2.21.5, ansible-lint 26.10.1, az 2.91.0, cloudflared 2026.10.1, flux 2.9.6, golangci-lint 2.15.0, helm
  4.3.1, hyperfine 2.0.0, kubelogin 0.2.21, kustomize 5.8.3, llama-cpp 11707 (the release tool, and `b11707` as the
  default checkout of `build-llama-cpp`, built from source on Windows, Linux and macOS; the `llama-cpp` container
  stack follows the tool), llvm 23.1.3 (with the C matmul program through clang), opentofu 1.13.1, rclone 1.75.2,
  terraform 1.16.6. Ansible and ansible-lint stay Linux and macOS tools (no Windows
  control node). `lib-litert-android` keeps 2.2.0: LiteRT 2.3.0 publishes no `litert_npu_runtime_libraries_jit.zip`,
  which its install unpacks - a `latest_limits` entry (`>=2.3.0`) says so, and the install now names the missing file
  instead of guessing that the GitHub API was unreachable. `flm` knows the checksums of 1.0.9 (an unknown release
  failed at once; the default stays 1.0.7 until an NPU machine runs it).
- **Windows installs that need administrator rights say so** (`requires_sudo: windows: True`): git, gh, cloudflared,
  node-js, llvm, microsoft.windows.adk, podman, tailscale, vulkan-sdk and open-ssh, whose winget packages install per
  machine or elevate themselves (read from the winget manifests). A quiet run (`-q`) that is not elevated no longer
  starts their winget fallback with a UAC prompt nobody answers; the release downloads of cloudflared, llvm and
  node-js need no rights and are not affected. open-ssh installs `Microsoft.OpenSSH.Preview` (winget renamed the
  `Microsoft.OpenSSH.Beta` package).
- **`explore-tool-versions --promote`: a failure the known version shares is no limit.** A newer version that failed
  on an OS where the known version fails with the same class of error (Ansible on Windows, a missing system library,
  no NPU) was proposed as a `latest_limits` entry and never as the next default; such a failure now says that the
  machine cannot run the tool at all, and the newer version is promoted where it works. The README shows how to
  explore a tool that another tool sets up with a version of its own (`llvm` under `clang`: `--use_key=compiler-c`).
- **`test-on-hosts --action=peek|collect` from another directory.** The round's local folder is the sandbox of the
  shell's test session, else the current directory: a peek from elsewhere made a `test-on-hosts-<id>` folder there
  for its helper script (also inside a repository) and reported this machine's part as running, a collect copied
  nothing without a word. The helper script now goes to a temporary folder, and both say where they looked. And
  `--action=remove` removes this machine's part on Windows also when its cache holds a git clone (read-only object
  files, which `shutil.rmtree` left: the round stayed on disk) - through the engine's `safe_delete_directory`.
- **One compiler family per build** (task `compiler`). A request that names no compiler takes the family of the
  other language's compiler of the same run - the one already set up, else the one asked for with
  `--use.compiler-<lang>.name` (`compiler_families` in its `_desc.yaml`). `--use.compiler-c.name=clang` alone now
  builds the C++ sources with clang-cpp too, whichever language a program sets up first; before, a build could get C
  by clang and C++ by the OS's preferred compiler (MSVC on Windows: CMake stopped; gcc on Linux: an unresolved OpenMP
  symbol at the link). An INFO line says which compiler leads, set up or asked for. And a request without a name is
  cached as `selected: auto`: it never takes an entry made by a request that named a compiler, so one run with
  clang no longer makes clang the default C compiler of every later run of the home. An entry made before has no
  `selected` and counts as named: the first default request makes its own entry once.
- **certbot 5.8.0 by default, installed on a bare system.** Its Apache plugin needs `python-augeas`, which has no
  wheels: the new tool `lib-augeas` sets up the Augeas development files (the distribution's package with sudo:
  Debian, Ubuntu, Fedora, RHEL, openSUSE, Alpine, Arch; brew on macOS), and the C extension is built with the C
  compiler of cMeta's compiler task. `common_pyvenv` has a new SPEC key for that, `c_compiler: True`: the compiler is
  set up first and passed to the build as `CC`, so a machine without `cc` on its PATH works too.
- **Android NDK 30.0.16248370 by default** (was 29.0.14206865), and its version list reads both forms of
  sdkmanager's package names (`ndk;<version>`, and `ndk/<version>` of the command-line tools 23.0).
- **The Android SDK command-line tools download from Google's repository** (`cmdline-tools;<release>` of
  `repository2-3.xml`, SHA-1 checked, unpacked as `cmdline-tools/latest` in the cache entry, no administrator
  rights): winget no longer has their package, which was the only Windows route, and Linux no longer needs brew for
  them; brew stays the macOS fallback. The default release is 22.0: in 23.0 sdkmanager is a shim of the new Android
  CLI (`android sdk`), with other output and without the Java entry point the tools here use, so a `latest_limits`
  entry keeps it out of `latest` until they are ported. On Windows the tool's command is sdkmanager's Java entry
  point: Google's `sdkmanager.bat` drops every `!` of JAVA_HOME and of its own folder ("Java version 17 or higher is
  required" with a JDK in such a folder). Its versions are listed from the same index (`--versions`, `check-updates`).
- **LibTorch 2.14.1 prebuilt** (`torch-cpp-prebuilt`, and the prebuilt default of `torch-cpp`; was 2.7.1, which stays
  pinned for `--version=2.7.1`): the archives of Linux (cpu, cu126, cu130, cu132, rocm7.2), Windows (cpu, cu126,
  cu130, cu132, ARM64 cpu) and macOS arm64 with their SHA-256 and the GPU architectures of each CUDA build. The CUDA 13
  builds have no code for Maxwell, Pascal and Volta GPUs, which take cu126. The Linux archives lost `cxx11-abi` from
  their names (the C++11 ABI is the only one since 2.8).
- **`test-on-hosts`: this machine's part of a round in a folder of its own choosing** (`cx config set
  task-test-on-hosts --meta.here_dir=<folder>`, default `~/cmeta-tests`, as on the other hosts). On Windows a round
  home under a deep session folder made MSVC fail on paths over 260 characters (C1083 in CMake's test compile of
  build-llama-cpp); `D:\cmeta-tests` keeps them short. `round.json` records the folder, so peek, collect and remove
  find it from any directory.
- **Container images say the cMeta inside** (category `container`). A base built under a moving tag is read once
  after its build and tagged with what it holds: `-cmeta-latest` (the newest PyPI release at its build) also gets
  `-cmeta-0.37.4`, a git install is named apart as `-cmeta-git[-<ref>]` and also gets `-cmeta-git-<commit8>` (before,
  a git build and a PyPI build overwrote each other's `-cmeta-latest`). The version comes from the image itself, not
  from PyPI or a cTuning.ai service. Nothing is rebuilt for a new release: `--refresh_cmeta` (`build`, `run`,
  `start`, `test`; `--on_refresh_cmeta` for an instance) builds the layers of uv and cMeta again with the OS layers
  from the cache, and an image on a base is built again when the base image it was built on changed (label
  `cmeta.base_image_id`). `cx container ps` lists one line per image with the cMeta inside; `cx container clean
  --old` removes the images a newer build replaced (an image a container uses is kept). The refresh lines of
  `Containerfile.base` are no part of a build's identity, so the images built before are used as they are.
- **New tools: NVIDIA OpenShell and NemoClaw.** `tool/openshell` installs OpenShell's CLI and gateway from the pinned
  release (0.1.4: the static CLI and the glibc gateway on Linux, both on macOS on Apple Silicon), each checked against
  the release's SHA-256 list; Windows runs it in WSL2. `task/run-openshell-gateway` runs a gateway of this user
  without upstream's package or service (`start`, `status`, `test`, `stop`, `remove`): its keys, configuration,
  database and log in a folder of its own, plaintext on 127.0.0.1 only, telemetry off, a session of its own, the
  registration with the CLI, a test sandbox. Without `--driver` it takes Docker when its daemon answers, else Podman
  5 or newer (the gateway's own detection tried an old Podman first, and found no Docker Desktop); the Podman driver
  starts the user's Podman socket when it is not running, and a sandbox that cannot reach the gateway through Docker
  Desktop names the cure (its host networking).
  `tool/nemoclaw` builds NemoClaw's CLI from the pinned release tag (0.0.135) with cMeta's git and Node.js, as
  upstream's installer builds it but without its system changes (the npm package `nemoclaw` is a placeholder, not
  NVIDIA's), and points it at cMeta's OpenShell.
- **Fix: `--on=docker`, `--on=podman` and `--on=wsl` did not see an artifact added after the instance was made.**
  The instance sees its repositories live, but its index knew only what it saw when it indexed them, so a tool added
  that afternoon was "not found" inside. An instance that is reused now reindexes inside each repository whose
  folders changed here since (a signature of its first-level folders, `mounted-signatures.json` next to the
  instance's artifact; the repository only, `cx repo reindex <alias>`). `--on=<host>` does the same for a WSL host
  of this machine that plugs this machine's repositories from `/mnt/<drive>`. `--on_refresh_cmeta` on an existing
  instance says that the instance keeps its image.
- **ollama 0.40.5 and obsidian 1.14.4 by default**; nginx keeps its stable line (1.30): a `latest_limits` entry
  leaves out the 1.31 mainline. **Fix: an ollama next to a running Ollama server got the server's version** -
  `ollama --version` names the server first and this binary only on a second line ("client version is"), which now
  wins.

## 0.50.1
- **Fix: `cx host pull --files` from a container or a WSL instance deleted local files.** The whole folder was copied
  into the local folder (the current directory by default) and every file there that did not match the patterns was
  then deleted - also the files that were there before the pull. Now only the matching files come, with their
  sub-folders, and nothing else in the local folder is touched: a container's folder lands in a folder of its own
  first (`docker cp` cannot choose files), a WSL instance copies the matching files alone (`find` + `cp --parents`) -
  its copy of the whole folder also failed on names that differ by case only (NTFS), which broke the collect of
  `test-on-hosts` rounds on WSL hosts. Tests: `test_host_pull_files.py`.
- **Fix: a deadline just opened has its whole length left.** A deadline ends at the monotonic clock + N seconds; with
  the clock just below a power of two (512 s after a boot - a fresh CI runner) the sum takes a coarser exponent and
  rounds up, and a deadline of 60 s just opened had 60.00000000000006 s left, reported as 61 (`test_compile_deadline`
  failed now and then on CI). The time left is rounded to the microsecond before it is rounded up to whole seconds.

## 0.50.0
- **Run any command on another host: `--on`.** `--on=<target>` on any `cx task run`, `cx program run`, `cx tool setup`
  or `cx app run` hands the whole command line, as typed, to another host and returns its result: a fleet host (ssh;
  a Windows host through PowerShell), or an instance made on first use from a container template - `docker[:<template>]`,
  `podman[:<template>]` (rootless, kept alive by lingering), `wsl[:<template>]` (a WSL 2 distribution made from the
  template's image). An instance is a host artifact named after the machine that carries it
  (`<machine>-docker-<template>-<version>`); its cMeta home and cache are its own, the machine's repositories are
  mounted into it live. `--on_template.<key>` (an OS version, another FROM, the cmeta-aops checkout of a stack),
  `--on_distro` (the base of an app template), `--on_instance`, `--on_repos`, `--on_data`, `--on_arch`, `--on_pull`
  (the run's folder comes back), `--on_rm` (a throwaway instance), `--on_detach` with `--on_ports` (a server kept
  running, its ports on 127.0.0.1), `--on_isolated` (this machine's repositories in a throwaway home on an ssh host)
  and `--on=here` (stay local) shape it. The inner run's provenance and repro records carry `run_on`. An artifact may
  carry its own route in an `'on':` block of its `_desc.yaml` (`requires_os`, a route per OS, `default`): test-sglang
  goes into the SGLang stack on Windows and macOS, test-vllm into docker on Windows. `cx host run --interactive` and
  the terminal pass-through let a delegated run ask its questions.
- **Hosts, machines and containers as artifacts.** The `host` and `machine` categories: `cx host ls` (`--made` for
  instances), `show`, `status`, `probe`, `run`, `ssh`, `push`, `pull`, `upgrade`, `restart`, `snapshot` / `restore`
  (docker: a committed image; WSL: an exported tar) and `destroy`. A host knows the machine it runs on by a system id
  (a hash of the OS's machine id, recorded by the probe) before its hostname; `cx host whoami` names this machine's
  host artifact; `cx host push` rescans only the pushed repository. The `container` category builds and runs docker
  and podman containers from templates: base templates `ubuntu` (26.04 by default), `debian`, `fedora`, `rockylinux`,
  `amazonlinux`, `azurelinux` and `opensuse` (zypper), with compute overlays (`cuda`, `rocm`) and the OpenMP runtime
  prebuilt binaries need; app templates on a base (`cmeta-test`, `cmeta-cserver`, `llama-cpp` with llama.cpp set up by
  cMeta in the image); stack bases on a project's own image (`vllm-cuda`, `sglang` per compute) with cMeta on top,
  pointed at the image's Python. The user inside takes the machine user's uid on a Linux engine; a distribution whose
  Python is older than 3.9 gets one from uv; sudo works under rootless podman; podman gets full image names; instances
  run with an init process; Docker Desktop over ssh (macOS, Windows) uses a config without the credential store and
  the classic builder. An app's compute overlay adds to its base's: the keys the base declares (llama-cpp's CUDA
  builds on the devel image), the base's GPU run flags kept; ubuntu's CUDA images name their CUDA version and flavour;
  an instance made with other template keys (another FROM, CUDA version or flavour) has a name of its own.
  `cx container render` needs no engine installed. The `docker` stub category is gone.
- **Matrices with `test-on-hosts`.** `--hosts` takes instance refs (`docker:debian --on_template.os_version=13`,
  `podman:fedora`, `wsl`): each instance runs the commands in a throwaway cMeta home on the tree it mounts. A ref that
  cannot be made is said and left out while the others run; the round is recorded (`round.json`), so `peek`, `collect`
  and `remove` need no `--hosts`; a WSL host starts the round with `setsid`; a host whose `cx` keeps a home of its own
  is said in the round and its home is not plugged into.
- **Data repositories and portable cached results.** A data task (get-hf-model, get-hf-dataset: `cache_repo_key:
  data`) keeps its entries in the repository named by `cache_repos.<key>` of `config::task` (or
  `--use.init.cache_repos.<key>=<repo>`); with `--on` those repositories are mounted into the instance and indexed
  again after the run. A cached result reused from another place (a moved entry, another mount path, another OS) has
  its paths rewritten to the entry's current place.
- **Secrets.** The `secret` category keeps identities and credentials as artifacts with their files inside (a
  repository flagged `secrets: true` is never synced or mounted): `cx secret ls`, `show`, `check`, `import`, and
  `generate` (an ed25519 pair without a passphrase where the identity names it), `use` (a git identity in one clone,
  or `--git_global`), `render` (a git include file). `task fix-ssh-key-permissions` gives a private key the
  permissions OpenSSH wants on any OS (on Windows an ACL of the user, SYSTEM and Administrators by SIDs, rules of
  others set on the file itself removed) and with `--check` says who else can read it.
- **GPU containers and machine defaults.** `tool::nvidia-container-toolkit` (Linux: NVIDIA's repository, the pinned
  packages, docker's `nvidia` runtime and podman's CDI file); a CUDA instance on a Linux engine without it stops with
  that cure. `use` in `config::task` holds a machine's own defaults of `--use` (the command line wins).
- **New tools: `apache2`, `nginx`, `lima`, `colima`.** Apache and nginx from the distribution's packages with their
  service enabled where systemd runs, Homebrew, winget, nginx's own zip on Windows. tool/docker installs the client on
  macOS and Windows from Docker's static release and adds the user to the docker group on Linux;
  tool/microsoft.visual-studio installs on a machine without the Windows SDK.
- **Fixes found by running the matrix across distributions and architectures.** `host.os.uarch` is `arm64` on ARM
  Linux too (it was `aarch64`, which the tools did not know; the OS's own name is in `uarch_native`). A package name
  falls back through the distribution's `ID_LIKE` (Rocky, Alma and Amazon Linux get their family's `gcc-c++` and
  `openssl-devel`); Fedora and openSUSE get their own. A gcc without binutils next to it, or on Linux without the C
  library headers, is not taken, so the setup installs the toolchain. tool/lib-openssl reads OpenSSL 1.1's version.
  tool/llama-cpp builds from source when the release binary does not start (an older C++ runtime), without AVX-VNNI
  where the assembler predates it; build-llama-cpp sizes its parallel compile jobs to the free RAM. `'on':` keys are
  quoted (YAML 1.1 reads a bare `on` as true). The host and container code measures durations on the monotonic clock.
  run-ai orders conversations started in the same second by their id.
- **Wireless Android fleet connections.** `cx host connect` reuses
  `keep-adb-connection-alive` for guided pairing, a verified one-shot connection
  or a foreground reconnect loop. It follows advertised connection ports using
  saved hardware identity, keeps non-secret connection state across fleet probes,
  and can require watch hardware. Wireless host commands and an optional Android
  CPU target `device_host` reconnect before use. Legacy endpoint/period loops and
  USB host behavior remain supported; pairing PINs stay with interactive ADB.
  Host selection also accepts program contexts containing loaded API modules.
- **Android APKs through the program abstraction.** Programs inherit
  `template-android-gradle-app` and use the existing compile/run/cache/source
  tracking/provenance driver. The additive `android-app` target allows compilation
  without a device; command variants install or launch through ADB. Gradle,
  Android XML and resource changes are tracked, and generated files live inside
  the program build workspace. Native Android program targets keep their behavior.
- **Android Gradle app lifecycle through `task::android-gradle-app`.** Build with
  a project's own Gradle wrapper, install an APK with ADB, or launch an installed
  activity. Sources resolve by cRef or an explicit directory; generated files and
  verified build receipts live in cMeta cache. Device selection refuses ambiguity,
  install keeps application data, and a failed build invalidates its deploy receipt.
  Android SDK detection includes Android Studio's standard user directories and
  reads installed package revisions, preserving command detection for older layouts.
- **Apache certificates through `setup-ssl-certificate` and `tool::certbot`.**
  Discover enabled Apache hostnames, issue/install Let's Encrypt certificates,
  renew existing lineages without losing their SANs, and test renewal. Plans and
  staging dry-runs are separate from installation; all-domain selection is distinct
  from wildcard certificates, which require a configured DNS-01 plugin. Certbot
  detects an installed version first or installs a pinned Python environment with
  the matching Apache plugin. Scheduled renewal remains owned by the host.
- **Reusable `sync` definitions and `task::sync`.** Describe local/local or
  local/SSH directory and repository pairs, run ordered batches, and list them
  when no name is given. Bisync initializes on first use and keeps its listings
  in permanent cMeta result artifacts; copy and mirror are also supported.
  Previews, confirmation, backups and explicit recovery protect established state.
  Plans show full selected repository paths; `exclude_categories` optionally omits
  whole category directories across selected repositories without deleting them.
  Optional `initial_mode: mirror` seeds from the source with destination backups
  before the first successful baseline, then automatically uses ordinary bisync.
  Explicit `--initialize` and `--require-initialized` separate first use from
  regular bisync; legacy task-sync cache state is imported without resetting it.
  Optional `--live` displays rclone file operations and statistics during the run,
  retaining the complete log in the result artifact.
  Existing fleet sync and `rclone-to-ssh` entry points retain their behavior.
- **Add `tool::cmeta` for a selected Python.** Detect an existing engine or install
  from PyPI, a Git ref or a local development source. The declared default pin,
  available versions, status, upgrade and check-updates use the shared tool setup
  framework. The runtime command uses the selected interpreter's `-m cmeta`.
- **Fix named task cache lookup.** API v2 now passes `cache_name` to the cache find,
  as API v1 does. Previously a named request could search all cache entries and reuse
  an unrelated result, including when selecting a named Python environment. Regression
  coverage creates two named entries alongside an unrelated entry and verifies independent reuse.
- **Cloudflare Tunnels: `tool::cloudflared` and `task::manage-cloudflare-tunnel`.** The tool detects an installed
  cloudflared (the distribution package, brew, winget) or installs the pinned release, its SHA-256 checked against
  the asset digests of GitHub's release API (upstream lists sums only in the release notes). The task manages the
  remotely managed tunnel of a machine, whose routes are set in the Cloudflare dashboard. `status` (the default,
  no root needed) reads the connector's own metrics server for its connections and routes, tries each route's
  origin and asks each public hostname over HTTPS (a login, a Cloudflare Access redirect and an unreachable origin
  are told apart); `--strict` turns a problem into an error for monitoring. `install --token_file=<file>` runs
  cloudflared as a systemd unit (Linux) or a launchd daemon (macOS) with the token in a root-only file passed by
  `--token-file`, so it never shows on a command line or in a unit file, and copies a release out of the cMeta
  cache to `/usr/local/bin` first. `restart`, `upgrade` (through the channel the binary came from: apt, dnf, brew or
  the release) and `uninstall` complete it; every action has `--plan`, checks `sudo -n` before changing anything
  and waits for the connector, quoting cloudflared's last error when it does not come up. Windows: status only.
- **`cx host probe` forgets a retired project.** A host's `state.yaml` kept the last state of every project the host
  had ever declared, so a project taken out of its `_desc.yaml` went on showing its repositories in `cx host show`.
  The probe now keeps the saved states of the declared projects only.

## 0.47.2
- **A quiet run never answers a prompt of the system, on Windows too.** On Linux and macOS a quiet run (`-q`)
  already runs `sudo` as `sudo -n`, which fails at once instead of waiting at a password prompt nobody sees. Now
  Windows has the same rule: a tool declares `requires_sudo: windows: True` when its Windows install needs
  administrator rights (the installer asks with a UAC prompt), and a quiet run from a process that is not
  elevated does not start it. The UAC prompt would wait on the desktop for nobody, or fail without one. The setup
  ends with an error that names the command to run in an elevated terminal, or says to run the command without
  `-q` and answer the prompt. From an elevated process (an administrator terminal, a CI runner) it runs, as with
  passwordless sudo; without `-q` nothing changes. task/host records `elevated` in the Windows `os_extra`. Visual
  Studio Build Tools, WSL and the MSI fallback of az declare it. Tests: the rule for every OS
  (`test_build_and_target_helpers.py`) and a real quiet setup on Windows (`test_no_terminal_prompts.py`).
- **rclone-to-ssh copies the other way too: `--from_remote`** (copy, copyto, sync from the host to `local_dir`;
  not bisync, which goes both ways already). It is what `cx host pull` of the private fleet category builds on.

## 0.47.1
- **`cx tool check-updates`: the tools behind upstream, as a report.** For every tool with a `default_version`
  (`--all`: every tool; or the tools named, `cx tool check-updates yq,jq`), the version cMeta installs by default
  (the pin in the tool's meta, not what a machine has installed: that is `--status`) against the newest one
  `latest` may take - the cached lookups of `cx tool setup <tool> --versions` (`--refresh_versions` asks again) -
  with a status: `behind` (and its step: major, minor, patch), `current`,
  `ahead` (the pin is newer than the channel's newest), `unknown` (no source of the newest version) or `no pin`;
  `--output=<file>` writes it as Markdown (`.json`: JSON), the Python API returns a row per tool and the counts.
  Nothing is installed or changed: the lookups use only the helpers already on the machine (the rule of
  `--status`; a missing one makes that answer `unknown`). It runs on a new switch of the setup task, `--check_update` (one quiet line per
  tool; a tool's own condition for an install, such as the Android target of lib-openssl-android, is a note there,
  not a stop). lib-zlib, lib-zstd and lib-jitterentropy now list their versions (the release tags on GitHub), so
  their newest version is known too.
- **The limits of `latest` in a tool's meta.** `latest_limits` in a tool's `_desc.yaml` names the versions `latest`
  must not take, each with a reason and a date (`exclude`: a PEP 440 specifier such as `>=3.15`, `reason`,
  `since`); `latest` - the word or the policy - is then the newest version no limit excludes (the versions are
  listed only when the newest one is excluded; with no list, the known version with one warning). A version asked
  for by number is taken as asked, with a warning when a limit excludes it. `--versions` and `check-updates` show
  the limits. tool/python carries the first one: `>=3.15` (PyYAML 6.0.3 has no cp315 wheels for Windows), the cap
  of cMeta's own installer.
- **A new task, `explore-tool-versions`: a tool tried at several versions, a verdict per version, and the
  proposals they support.** `cx task run explore-tool-versions <tool>` tries the tool's known version and the newest
  one `latest` may take (and the newest one, when a limit excludes it); `--versions=a,b,latest` names the versions,
  `--last=<n>` takes the `n` newest released ones of the tool's list (`cmd_get_versions`, the cached lookup of
  `cx tool setup <tool> --versions`; `--refresh_versions` asks again) - never a range by itself, and the first lines
  of a run name each version and why it is tried. Each version is set up in a fresh cache entry (removed afterwards
  unless `--keep`), the program runs with it when asked (`--program`), and a verdict per version is appended to a
  JSONL file (`--output`, by default `explore-tool-versions-<tool>-<host>-<stamp>.jsonl` in the current directory;
  works or fails, why the version was tried, the class of the error - not available, checksum, download, build,
  crash, else the stage -, the machine, the versions of cMeta and cmeta-aops), copied into the test session of the
  shell. A sub-task that raises is a failed verdict of class `crash`, and the exploration goes on.
  `--promote --verdicts=<files or folders>` reads the verdict files of one or many machines (put in one folder; it
  never contacts a machine), prints the evidence - per tool and version, where it worked and where it failed - and
  the proposals as YAML lines: the next `default_version` (the newest version that worked wherever it was tried, on
  at least `--min_os` (2) operating systems), a new limit of `latest` (a newer version that failed somewhere), or a
  note for a version a machine's channel does not offer (an older uv) - a note, not a limit. It never writes a
  tool's meta. Tests: `test_explore_tool_versions.py`.
- **yq: `default_version` 4.53.6 -> 4.54.1**, the first bump made from the verdicts of `explore-tool-versions` (it
  works on Windows, Linux and macOS).
- **Fix: task/venv stopped the run with a traceback for a Python version uv cannot install.** `resolve_with_uv`
  raised `ValueError` ("No matching Python version for '3.14.8'", met with an older uv on Linux and macOS); now it
  is an error that names the version and where the versions come from. Test: `test_venv_python_version.py`.
- **A guard: no `run()` parameter of a task is named like a control word of the task category** (`save`, `path`,
  `new`, `info`, `tags`, ...): such a parameter never reaches `run()` - `--save=<file>` saves the context of the run
  instead. The two existing ones work by their own route and are listed (run-ai's `new`, scan-git-secrets' `path`).
- **The skills for contributors (`.claude/skills/add-task`, `add-program`, `add-tool`) follow the rules of new
  code:** no copyright line in a new file (`authors:` and the Apache-2.0 pointer only; the generated `copyright:`
  key is removed), the life of a cache entry (resumed in place after a failed or killed attempt), the typed words
  of the command line and the control words a `run()` parameter must not take.

## 0.47.0
- **Fix: only the words of the command line are read as what a task's `run()` expects; a value a parent's
  code passes to a sub-task stays as it is.** In 0.46.0 the task category converted every string parameter of
  every task of a run started from the command line, so a path that `common_release.py` handed to
  download-file's `check_file` (then annotated `bool`) stopped the run with "Invalid bool value ... for
  'check_file'": every fresh release download (`cx tool setup jq`, `yq`, `helm`, ...) failed. Now a parameter
  is converted only when the command line holds that word for it (`--key=value`, `-key=value`, `key=value`,
  `--use.<storage key>.key=value`; `cli_words` in `category/task/api/v2.py` and `v1.py`), at any depth: the
  words forwarded by `cx tool setup` and `cx program run` are still read, the Python values of a `uses` list,
  a `cm.access` call or an `@file` are not. `check_file` of download-file is a `str` (it always was a file
  name). Tests: `test_task_cli_types.py` (a parent's code calling the child with a path for a bool parameter;
  the `--use` word read in the same child).
- **Fix (Windows, since 0.42.0): the tools installed in Program Files are found again.** The tool search
  skipped a pattern such as `C:\Program Files**\OpenSSL**\**` as "a recursive search from a filesystem root",
  because it judged a pattern by the text before its first star (`C:\`). Only a whole `**` component recurses
  in Python's glob; `Program Files**` is one level, as `*`. So lib-openssl, openssl, llama-cpp,
  microsoft.windows.adk and windirstat were never found in their Program Files folders: winget answered that
  OpenSSL was already installed, the search found nothing, and every C program that links OpenSSL
  (`cx program run test-nmm-c-cpu`) failed on a fresh Windows cache. Now the folder the recursion starts from
  is what is checked (`glob_pattern_is_safe` in `category/tool/api/v1.py`): a wildcard before it is expanded
  one level and each folder it gives must be a real folder below a root, not a pseudo file system; `/*/**`
  (every folder of a disk) stays refused. Tests: `test_find_path_safety.py`.
- **Fix: the Hugging Face downloads work with huggingface_hub 2.x.** `get-hf-dataset` and `get-hf-model` gave
  `hf download` the file names of a description as `--include` patterns as they were written: the doubled
  separator of `dataset/hf-ylecun@mnist` (`mnist//train-00000-of-00001.parquet`) matched with huggingface_hub
  1.x and matches nothing with 2.2.0 - only the README came, and the MNIST program failed in a fresh cMeta home.
  Each pattern is now a clean POSIX path; the file names of the cache entries stay as described, so the entries
  already made are reused.
- **The switches of seven more tasks whose `run()` reads `**kwargs` are described in `cli_params`**, so a word
  is read as a boolean: `compile-and-run-program` (`here`, `recompile`, `skip_compile`, `skip_run`,
  `skip_size_check`), `setup-compile` and `setup-run` (`profile`, `profile_python`, `profile_cuda`,
  `profile_cuda_kernels`, `run_on_host`), `target` (`ask`, `add_env`), `clone-git-to-cache` (`version_to_dir`,
  `skip_checkout_dir`), `finish-run` (`print_line`) and `test-session` (`start`, `finish`, `prune`, `migrate`,
  `list`, `keep`, `all`, `remove_old`, `skip_usage`). Before, `cx program run <p> --recompile=no` handed on the
  text "no", which is true. The flags (`--recompile`, `--recompile-`) behave as before.
- **Guard tests over the whole repository, for the kinds of bugs found in this release**
  (`test_guards_cli_words_and_search.py`): no parameter annotated `bool` in a task or a category is used as
  text; every switch a `**kwargs` task reads (with a boolean default, or named `skip_*`, `ignore_*`, `force_*`,
  `custom_*`) is described in its `cli_params`, and the known switches stay described as `bool`; every
  `cli_params` description uses a type the engine converts; no search pattern a tool declares (`names`,
  `extra_paths`, `only_paths`, every OS) is refused by the tool search. The words of the command line are also
  tested through the real `cx` and `cxt` in a child process (`test_task_cli_types.py`): `--key=value` in any
  case, `key=value`, the flags `--key` and `--key-`, `--use.<key>.<param>` for a sub-task, a value a parent's code
  passes, an `@file`, the words after `--`, the messages of a wrong word and `CMETA_CLI_TYPES=off`; and
  `task/init` takes `file_cache`, `version_policy` and `versions_ttl_hours` from the flag, the variable and the
  config in that order (`test_init_default_cache_repo.py`).
- **`tool/docker-compose`: Docker Compose as its own binary.** `cx tool setup docker-compose` finds the
  program on the PATH and in Docker's CLI plugin folders (Docker Desktop's included), else installs the pinned
  release of docker/compose (`default_version` 5.6.0) into the cMeta cache with its SHA-256 checked against
  the release's checksums; `--versions` lists the release tags. Installing it does not install or start Docker
  Engine.
- **`tool/wsl` installs and updates the WSL runtime with Microsoft's own commands.** `cx tool setup wsl
  --install` runs `wsl.exe --install --no-distribution --web-download` (no Linux distribution is added),
  `--upgrade` runs `wsl.exe --update --web-download`; the tool's README explains the administrator terminal,
  the restart Windows may ask for, and how to add, import and set up a distribution.
- **Versions by name: `--version=known` and `--version=latest`, a policy for a request without a version,
  and the newest version of every tool looked up once and cached** (`task/setup/upgrade.py`, the setup task's
  `check_params`). `known` is `default_version` of the tool's `_desc.yaml`; `latest` is the newest version the
  tool's channel or upstream offers - the rule of `--status`: the channel's for winget, Homebrew and the system
  package manager, upstream's (the GitHub release marked latest, else the newest tag) for a release download.
  Both words are resolved to a concrete version BEFORE the cache lookup, so the cache entry's key and the
  provenance record hold a real version, and they travel to a sub-task as a version does
  (`--use.python.version=latest`). A request without a version follows a policy: `known` (the default: whatever
  is found first, else the pin - the behaviour before), `latest`, or `ask` (the question "the newest is X, the
  known one is Y: install the newest?", the known one without a terminal or with `-q`); set for one tool by
  `--use.<tool>.version_policy`, for the run by `--use.init.version_policy`, for a shell by
  `CMETA_VERSION_POLICY`, for the machine by the key `version_policy` of `config::task` (the flag wins over the
  variable, the variable over the config; `task/init` carries it as `init.version_policy`), for a tool by
  `version_policy` in its `_desc.yaml` (`latest` for a tool whose newest is always right), else `known`.
  A version chosen by a word that cannot be determined or installed falls back to the other one, once, with one
  `cMeta warning:` line, and the cache entry records the version obtained (`version_fallback` in the result);
  a version the request names is never replaced. The lookup of the newest version is cached per tool in
  `tmp::tool-versions/<tool>.json` of the local repository for `versions_ttl_hours` (24; `--use.init.
  versions_ttl_hours`, `CMETA_VERSIONS_TTL_HOURS`, `config::task`), asked once per run, refreshed with
  `--refresh_versions`; offline, the cached answer, else the known version with a line. `cx tool setup <tool>
  --versions` now also prints the known and the newest version, their source and the policy, works for a tool
  without `cmd_get_versions` (its channel's newest), and returns `known`, `latest`, `latest_source`, `policy`
  and the lookup record for the Python API; the result of a setup carries `version_resolved` (the word and
  the version it became). Tests: `test_tool_versions.py` (the helpers; the words, the policy sources, the two
  fallbacks and the cache end to end on throwaway tools, offline).
- **Reproduce a run: `cx ... -r` writes `repro/<stamp>/` and `cx @repro/<stamp>/repro.json` reruns it with
  every tool pinned to the version it used** (`category/task/api/provenance.py` `write_repro`, called by the
  task category when the outermost task of a run started with `-r` (`--repro`) ends). In the directory the
  command was run from: `repro.json` - the original request with `use.<tool>.version` = the version each tool of
  the run was used at (what the request named for a tool - a word, a partial version such as `3.12`, a range -
  becomes what it resolved to: `3.12.14`), which the engine's `@file` include replays; `tools.json` - every tool
  with its version, path, cache entry and
  parameters; `run.json` - the command line, the directory, the time, the result, the host and the cMeta version;
  `README.md` - how to rerun and how to change one version at a time. A pinned version that is no longer there is
  installed where cMeta can and fails loudly otherwise: remove the pin to let that tool float. The engine's own
  `cmeta-repro-*.json` files are written as before. Tests: `test_repro.py` (the request, the README, a run with
  `-r` and its rerun from the file, a pin that cannot be met).
- **`--use.init.file_cache=<folder>` names the file cache of one run** (the folder of large downloads and
  clones that `clone-git-to-cache`, `get-hf-model` and `get-hf-dataset` keep outside the cache entries), as the
  key `file_cache` of `config::task` does for every run; before, `task/init` refused the parameter.
- **The switches of `cx tool setup` are read as words** (`--skip_install=no`, `--use.<tool>.install=yes`): the
  setup task reads its parameters through `**kwargs`, so its 21 boolean switches are now named in `cli_params`
  of `task/setup/_desc.yaml` - before, `--skip_install=no` kept the text "no", which is true.
- **The version a tool installs by default is declared in its `_desc.yaml` only.** `default_version` of the
  tool's description is the one place that says which version cMeta installs when none is asked for, so that
  `cx tool show <tool>` answers it and a bump is one edit. The shared installers (`common_release.py`,
  `common_pyvenv.py`, `common_static_lib.py`) read it from the description (`common_release.default_version`),
  and the SPEC dicts of the 25 tools on them lose their copy; the three static libraries get the key, and
  `tool/mpi` gets `default_versions`, one per implementation. A SPEC `default_version` of a tool written before
  this version is still read when the description has none; a tool with neither gets an error naming the key.
  No behaviour change: the same versions as before. Test: `test_tool_default_version.py` (every tool on a
  shared installer declares the key, no code copy, the installers read the description). The first step of the
  work on default and latest versions of tools.
- **Prototype `setup-cmeta-host`: optional host services for Windows, Linux and macOS.**
  Terminal runs explain and ask about SSH, Tailscale, sleep settings and Windows BitLocker
  data-volume boot unlock, then ask before applying. `-q` suppresses questions; scripted changes
  require `--apply`, while `--check` and `--dry_run` inspect only. Existing services/configuration
  remain when deselected. Windows setup can keep portable SSH on the OS disk, enable unattended
  Tailscale, and provision a protected SYSTEM startup unlock task using an existing external-key
  protector without exporting key contents to cMeta. `managed`, `slurm`, `kubernetes`, `aks` and
  `mpi` profiles select no services by default; controller registration and workload launchers
  remain separate. Includes safe metadata reports and a usage/maintenance guide. Validation:
  13 focused tests, interactive/quiet Windows CLI checks and read-only NucBox inspection;
  generalized live provisioning and Linux/macOS apply still need disposable-host integration tests.

## 0.46.0
- **The words of the command line reach a task as what its `run()` expects (cMeta 0.37+).** On a run started
  from the command line, the words given to a task - on its command line or through `--use.<key>.<param>` for a
  sub-task - become booleans for the parameters `run()` annotates `bool` (`flag: bool = False`): yes/no,
  true/false, on/off and 1/0, any case; any other word stops the run with a message naming the parameter and the
  task. Before, `--x=no` handed the task the string `'no'`, which is true. A task can also describe its sensitive
  parameters in its `_desc.yaml` (`cli_params`: a type among bool, int, float and str, allowed `values`, a `min`
  and a `max`) and the task category converts and checks exactly those. The Python API is not read, nor are the
  parameters a task's own code passes to a sub-task. `cli_types: false` in a task's `_desc.yaml` and
  `CMETA_CLI_TYPES=off` keep the words text; an older engine has no helper and the words stay text too.
  The task category calls the engine's `typed_params_from_cli` before a task's `check_params` hook, in API v1
  and v2. Test: `tests/cmeta_aops_basic_tests/test_task_cli_types.py`.

## 0.45.2
- **A new task, `sync-system-clock`: the system clock measured against a time server and put right with the
  OS's own commands.** `cx task run sync-system-clock` measures the offset (w32tm on Windows, chronyc or
  timedatectl's timesync-status on Linux, sntp on macOS) and the state of the time service, and when the clock
  is off by more than `--max_offset` (1 s) or the service is not running, fixes it: Windows - the Windows Time
  service set to start automatically, started and told to resync (an elevated PowerShell, the administrator
  prompt); Linux - `timedatectl set-ntp true` and systemd-timesyncd restarted or chrony stepped; WSL2 -
  `hwclock -s` (the clock is a copy of the Windows host's; the lasting fix is the host's service); macOS -
  `sntp -sS` and network time on. `--check` reports only, `--force` fixes anyway. Root steps run with `sudo -n`
  unless the run is interactive. Why: a laptop's WSL2 clock was seen stepping by seconds every 30 s because the
  Windows host's time service was stopped - every program that compares timestamps suffers from such a clock.
  Tests: `test_sync_system_clock.py` (the parsers, the plan per OS, a `--check` on the machine).
- **A new task, `reboot`: a reboot of Windows, Linux or macOS scheduled with the OS's own command.**
  `cx task run reboot --dry_run` shows the command (`shutdown.exe /r /t <seconds>` on Windows, `shutdown -r +<minutes>`
  on Linux and macOS, through `sudo -n` unless the user is root); `--yes` schedules it after `--delay_seconds` (60;
  0 to 3600, rounded up to whole minutes on Linux and macOS). Without `--yes` nothing happens. Tests:
  `test_reboot_task.py` (the commands per OS, the limits, no reboot without `--yes`).
- **A timeout stays a timeout when the wall clock is set.** `task/cmd` told a timeout from another failure by the
  time the command took, on the wall clock: a clock set back meanwhile (NTP, a virtual machine's clock sync - WSL2
  was seen stepping it by seconds every 30 s) turned a real timeout into "failed with return code -1". Now the
  engine's own word comes first (`timed_out`, cMeta after 0.35.1), and the elapsed time of an older engine is
  measured on the monotonic clock. The deadline of a phase (`--compile_timeout`, `category/task/api/deadlines.py`)
  is kept on the monotonic clock too. Tests: `test_cmd_timeout.py` (the wall clock set back 10 s on purpose),
  `test_compile_deadline.py`.
- **More tests of timeouts and of the cache attempts.** `test_cmd_timeout.py` allows a slow system its time (the
  child 20 s, the call within 15 s - the 4 s it allowed were eaten by WSL2's clock); `test_task_cache_states.py`:
  three identical requests with the first one killed (one resumes the attempt, the other uses its result - two
  attempts in all, never two at once), a request that waits longer than `CMETA_LOCK_TIMEOUT` (the wait for an
  attempt has its own limit), and one that gives up after a short `CMETA_CACHE_WAIT_TIMEOUT` with a message that
  names it. Durations in these tests are measured on the monotonic clock.
- **`rclone-to-ssh` (and so `cx host push` and `sync`) works with a login name that contains a space.** The ssh
  command handed to rclone (`--sftp-ssh`) is quoted as one argument for the shell, and the login inside it as one
  item for rclone, which splits that value at spaces and keeps a quoted item whole: the login of a Windows account
  such as `First Last` was cut in two. A login without a space gives the same command as before.
- README: `cx --print-home` prints the path of the cMeta home alone, for scripts (cMeta after 0.35.1).
- **Every duration a task measures is on the monotonic clock.** The agent tasks (run-claude, run-codex,
  run-gemini, run-agy, run-hermes, run-opencode, run-openclaw: "Duration" and the `duration` of the result), the
  run time of run-ai, the elapsed time of rclone-to-ssh and the `self_time_*` of compile-and-run-program took the
  difference of two wall-clock times: a clock set meanwhile (NTP, a virtual machine's clock sync) made them wrong,
  even negative. A start that is also a time of day (run-openclaw's session file, run-ai's native session and
  guard) stays on the wall clock next to the monotonic one. The names and units of the results are unchanged; on
  Linux and macOS a run that spans a sleep of the machine now counts the time it was awake. A guard test keeps the
  rule for category/, task/ and tool/ (`test_durations_use_the_monotonic_clock.py`, the twin of the engine's).
  The MNIST benchmark program (`model-cnn-ylecun-mnist-pytorch`) times its imports, epochs and evaluation with
  `time.perf_counter()`.

## 0.45.1
- **Of the usable cache entries that are equal for a request, the one made last is taken - on every
  machine.** A request that matches several usable entries takes the first in this order: the task's own
  `sort_keys` or, by default, the highest version, then the priority, then the path; then the entry's `sort`
  value. Entries that were still equal fell to their aliases, which end in a random UID: a second entry made
  with `--new`, or the two entries that identical requests at once made before 0.45, were taken by chance -
  the older one on one machine, the newer on the next. Now the time of creation decides before the alias,
  the newest first (`cmeta.creation_timestamp-` after the keys above, in `category/task/api/v2.py`); nothing
  changes for entries that differ in version, priority, path or the task's own keys, and an entry without a
  time of creation comes after those that have one, in the order of before. A quiet run says in one line
  when the time decided (`NOTE: 2 cache entries have the same version, priority, path: the newest is used -
  <alias>, made <time>`), a run that asks says that such entries are listed newest first, and without the
  console nothing is printed. `cx cache show --duplicates` and `cx cache clean --duplicates` of the engine
  (cMeta 0.35.1 and later) list and remove the entries that no request can tell apart. Docs: "Several usable
  entries: which one a request takes" in `docs/cmeta-aops/task-engine.md`. Tests:
  `tests/cmeta_aops_basic_tests/test_task_cache_selection.py`.
- **The running file of a short attempt no longer stays in its finished entry on Windows.** The end of an
  attempt removes `cmeta-task-running.json`; Windows refuses to remove a file that another handle has open,
  and the file is read by everyone who classifies the entry - the lookup of another request, `cx cache
  show`. An attempt of a few milliseconds ended while such a reader was there, the refusal was swallowed,
  and the usable entry kept the file of an attempt that was over (no harm to the result; the entry looked
  as if something had run in it). The removal is now tried again until the reader is gone. Found by the
  test of identical requests at once, which failed now and then on Windows; a test holds the file open
  across the end of an attempt.
- **Python 3.15.** The suite runs on Python 3.15 in CI, next to 3.9 and 3.14 (Linux, Windows, macOS); nothing
  in the repository needed a change. Two tests did: `test_tool_upgrade.py` compared a tool's version with
  `platform.python_version()`, which carries the suffix of a pre-release (`3.15.0rc2`), and
  `test_task_cache_states.py` compared the process id on record with the one it had started, which in a
  virtual environment on Windows is the `python.exe` launcher and not the interpreter that runs the task.

## 0.45.0
- **The cache entry of a run: a failed or interrupted attempt is resumed in place by the same request, never
  served as a result, never inherited by another request; identical requests at once make one entry.** The
  task engine (`category/task/api/v2.py`) classifies the entries that match a cache query with the engine's
  `cx cache classify` (ok, running, crashed, failed, broken - cMeta 0.34.2) and: serves the usable ones as
  before; resumes, for a request without a usable entry, the newest crashed, failed or broken entry made for
  THE SAME request (`request_params`, recorded in the entry at its creation: the request's cache meta params
  with the fuzzy `@version` under its plain name and the constant match params a tool adds - a different
  version, or none where the attempt had one, gets its own new entry and the failed one stays); waits for a running one (a
  notice after 3 s, `CMETA_CACHE_WAIT_TIMEOUT`, 86400 s) and then uses its result; creates a new entry
  otherwise - the find-then-create under the lock of the cache repository's category folder, the attempt
  under the lock of its entry's folder (`cmeta-task-running.json` says who runs it). At the end the result
  and ctx files are written first (atomically), then the entry's `params` are REPLACED by the request's full
  cache meta params (the identity keys and the constant match params, what the find of the next request
  matches) plus the task's `_update_params` (before: deep-merged over the old ones, so a stale version of a
  failed attempt survived - the torchvision incident of 2026-10-08), then the `tmp` tag goes (before: the tag
  went before the result existed) or `failed` is set. A task sees what it resumes in
  `ctx['tasks']['run_control']['cache_resumed']`. Legacy entries without the record resume by the subset
  rule of before. `--update`, `--clean`, `--new`, `--path`, `cache_name`, the hooks and the files are
  unchanged. Tests: `tests/cmeta_aops_basic_tests/test_task_cache_states.py` (a synthetic task that
  downloads once, fails on demand and counts its attempts: the retry, the other configuration, the legacy
  entry, the broken entries, a kill and the resume, identical requests at once, `--new`/`--update`,
  `show`/`clean` by state, a running entry neither cleaned nor deleted, a full reindex during a build, and
  the invariants - index == disk, one entry per configuration, no lock or temporary file left, usable
  entries untouched). Needs cMeta 0.34.2 (`min_cmeta_version` of the task category).
- **Source builds size `MAX_JOBS` to the RAM that is free, with 3 GiB per C++ job.**
  `category/program/api/common_build.py` (build-pytorch, build-pytorchvision, build-vllm) counted 2 GiB per
  C++ job of the machine's whole RAM: 15 jobs on a 30 GiB laptop, where PyTorch 2.14's vectorized ATen
  kernels pass that, and the kernel's out-of-memory killer ended a compiler and the user's desktop session
  with it. Now 3 GiB per C++ job (4 GiB per CUDA/ROCm job as before), 2 GiB kept for the system, and the
  budget is the RAM available now (`MemAvailable` on Linux, the free physical memory on Windows, the
  machine's RAM on macOS): a build next to a browser, a VM or another build gets fewer jobs. `--max_jobs`
  overrides as before. Tests: `tests/cmeta_aops_basic_tests/test_build_and_target_helpers.py`.
- **`task/download-file`: a file gets its name only when it is complete, and an interrupted download is
  continued.** A transfer cut by the network is an error now (cMeta 0.34.2 checks the size the server
  announced; before, the short file was renamed and unpacked, and since a failed attempt is resumed in its
  entry the same request would have failed on it every time). The bytes that arrived stay in
  `<name>.download` and the next attempt asks only for the rest (`download(resume=True)` of the engine: a
  range request that the server answers only for the same file; `--resume-` starts over every time; an
  older engine starts over as before). The partial file and its record live in the working directory, not in
  `directory`: the tools ask for a clean `directory` on every attempt, which used to throw the partial
  download away with it. A checksum (`md5sum`) is compared BEFORE the file gets its name, and a file found
  under its name is checked again - before, the check ran only right after a download, so the attempt after a
  failed check (and the second mirror after a bad first one) took the bad file. Mirrors never complete each
  other's files. When an archive left by an earlier attempt cannot be unpacked, the error names the file to
  delete. Tests: `tests/cmeta_aops_basic_tests/test_download_file_resume.py`.
- **One venv is one python: a folder is recorded under the name the request gave it.** `task/venv` reported
  the venv under `os.getcwd()`, which on Linux and macOS is the physical path, while every later request
  looked for it under the path it named: with a link in the path (a home moved to another disk behind a
  link, `/tmp` on every Mac) the run that made a venv and the runs that used it recorded two pythons, each
  with its own entry for every pip package. The venv (and the conda environment of `--conda`) is now
  reported under the name of the folder the task was asked to work in (`folder_as_named` of the task API);
  no link is resolved - a link is what survives when the disk behind it changes. Without a link in the path
  nothing changes, and Windows already kept the name. The same folder named by another path is another
  name, with its own entry. Tests: `tests/cmeta_aops_basic_tests/test_folder_as_named.py`.
- **`tool/pip`: the CUDA or ROCm line of a torch that is installed is kept by requests that name none.**
  When a request names no line (`with.ver`, an index, the target's), torch and the packages built against it
  (torchvision, torchaudio, flash-attn) took the newest line of the machine whatever was installed: a quiet
  run replaced torch 2.14.1+cu130 by 2.14.1+cu132, and a cu130 torch got a cu132 torchvision. Now the torch
  already in the Python of the request decides: its packages come from its index, and a request for torch
  itself keeps it when it is what the request asks for (the same version, or none). A request for another
  torch version takes the line of the machine as before, and a line that is named is taken whatever is
  installed. A CPU wheel, a source build and AMD's builds have no say. Tests:
  `tests/cmeta_aops_basic_tests/test_pip_torch_wheel_line.py`.
- **A question without a terminal is an error that names the flag, not a traceback.** A setup without `-q`
  in a detached job ended in `EOFError` at "would you like to install ... (Y/n)?". Every prompt of the task
  engine, of `task/setup` and of the tasks that select or confirm goes through `ask` of the task API: no
  terminal is an error of the run (`-q` or `--install`, `--build`, `--update`, `--skip_size_check`, `-f`:
  whatever answers the question in advance), never a made-up yes - an install may need sudo; the attempt
  ends `failed` and the same request with the flag resumes it. A pause ("Press Enter to continue") is
  skipped. A quiet run no longer stops at the two questions about an outdated cache entry
  (`--check_versions`): it takes their defaults. A terminal and a piped answer are as before. Tests:
  `tests/cmeta_aops_basic_tests/test_no_terminal_prompts.py`.
- **`program/build-pytorchvision` says before the clone that the torch is for another CUDA.** torch does not
  compile CUDA operators with a toolkit of another major version than the one it was built for; with a torch
  for CUDA 12 in the Python of the run and a CUDA 13 toolkit the build ended inside pip's output with
  "return code 1", after the clone. The program checks it when it pairs the checkout with the torch and
  names the ways out (a Python whose torch fits, `--compute=cpu`). Tests:
  `tests/cmeta_aops_basic_tests/test_build_pytorchvision.py`.
- **`run-ai`: the guard of the used artifacts tells "in the meantime" from the records, not from a clock.**
  Whether an `--apply_pending` record was written during a run was decided by the record's file time against
  the clock of the machine at the run's start, and whether the artifact ran a session of its own by the
  recorded times of its runs against that clock. The files of a project are not always stamped by that clock:
  on a Windows drive inside WSL2, a network share or a folder mounted into a container the times come from
  another machine, recorded times can come from another time zone, and some file systems keep times to the
  whole second. A change the user had just applied could then be taken for a direct change of the session (put
  back and staged again), and a record from before the run could approve the same change made again by the
  session. The snapshot taken before the harness starts now also keeps the artifact's `applied` records (names
  and content) and the runs of its conversation records, read before the files; after the run, a record that
  is new or reads differently was written since, a run that is new was started since, and one that had no end
  and has one now ended since. One time rule is left on purpose: a run without an end counts as running for
  48 hours from its start. With it: the record of a decision takes its name by creating the file (two projects
  started within the same second carry the same stamp and could write one record over the other), a record
  caught while it is being written is read again, and the lock of a starting run (`<stamp>.lock`) is old when
  it is ten minutes older than the lock the new run has just made - by the folder's own file times. Tests:
  `tests/cmeta_aops_basic_tests/test_run_ai_pending.py`, `test_run_ai_engine.py`.
- **`run-ai --conversations` lists every run with its harness, model and effort; `--cs` is its short name.**
  Under each conversation the listing now has one line per run: the stamp, the harness (also when it was the
  default one), the model and the effort the run was given with `--model=<model>,<effort>` or `--effort`
  (`default` when none was given: the harness used its own), the mode and when it started and ended. The
  listing still starts no harness and writes nothing; `-j` gives the same records as before. Tests:
  `tests/cmeta_aops_basic_tests/test_run_ai_engine.py`, `test_run_ai_conversations.py`.

## 0.44.1
- **`tool/pytorchvision`: torchvision as a tool, the mirror of `tool/pytorch`.** Detected when the Python of the
  run has torchvision (built earlier, or PyTorch's wheel), built from source by `program/build-pytorchvision`
  otherwise - against the torch of that Python, at the vision release that pairs with it (`--version=0.29.1`
  names one; `--with.torch=pip` puts PyTorch's wheel torch there first); cached per compute, torch source and
  version. `cx tool setup pytorch ...` then `cx tool setup pytorchvision ...` with the same
  `--use.python.venv_path` give the built pair; verified on a ThinkPad with CUDA 13.3 (detection of the pair
  built before, a build in a fresh venv with the wheel torch, the second call cached, the test program on it).
  **Fixed on the way: `tool/pytorch` never found its own torch.** The generic detection looks for a file of
  each name under the search paths, and the tool named only the package (`torch`), so every setup went to a
  build, even with the torch there. Both tools now name the package's `__init__.py` under the Python's
  site-packages (Linux, macOS, Windows layouts) and set up the Python first, so `--use.python.venv_path`
  selects the venv they look in. And after a build the setup task hands the detection the entry's own build
  folder, where a package installed into the Python never is, so every build of `tool/pytorch` ended with
  "failed to find tool" after hours of compiling: both tools now point the detection that follows a build at
  the Python's home. `tool/pytorch`'s default version is the release its build program checks out (2.14.1; it
  was 2.7.1).
- **`program/build-pytorchvision` pairs itself with the torch of the Python.** torchvision's compiled operators
  must be built against the exact torch they run with. The program now probes the torch in the Python of the
  run, checks out the vision release that pairs with it by PyTorch's numbering (torch 2.14.1 -> `v0.29.1`; a
  development torch takes `main`; `--checkout` overrides), versions the package as that tag (`BUILD_VERSION`) and
  makes it require that torch (`PYTORCH_VERSION`), builds the GPU operators for the target (`FORCE_CUDA`, this
  machine's CUDA architectures) and stops with the two ways to get a torch when the Python has none. `--torch=pip`
  installs PyTorch's wheel for the target first. One venv shared through `--use.python.venv_path=<folder>` ties
  the torch build, this build and the programs that use the pair: the pip steps of `test-pytorch-with-vision`
  then find both satisfied. Before, the program built `main` in the default Python against whatever torch was
  there, and nothing paired or consumed it. Verified on a ThinkPad with CUDA 13.3, all three mixed combinations:
  torch built from source (2.14.1) with torchvision from PyTorch's wheels (0.29.1+cu132: the versions pair and the
  CUDA major versions agree), the built torch with torchvision built against it (v0.29.1, chosen by the program),
  and PyTorch's wheel torch (2.14.1+cu132) with torchvision built against it - each runs its operators on the GPU
  through `test-pytorch-with-vision`. The README has the recipes of the four combinations. Tests:
  `tests/cmeta_aops_basic_tests/test_build_pytorchvision.py`.

## 0.44.0
- **cMeta inside AMD's containers: the ROCm that lives in a Python is detected.** `tool/rocm` also finds AMD's
  Python distribution of ROCm through its CLI `rocm-sdk` (the `rocm` pip package: what the `rocm/vllm` and
  `rocm/pytorch` images hold, or a venv made by hand; there is no rocm-smi there): the folders from
  `rocm-sdk path`, the version from the amd-smi next to hipcc, the GPUs from amd-smi's JSON turned into
  rocm-smi's, and one candidate per installation (an install of this tool has both, its rocm-smi answers).
  With it, cMeta installed in `rocm/vllm:rocm10.1.0_ubuntu24.04_py3.14-pytorch_2.13.0_vllm-0.29.0` (uv is in
  the image: `uv tool install cmeta`, `cx repo pull ctuninglabs@cmeta-aops`) ran `test-vllm --compute=rocm
  --use.python.tool_path=/opt/python/bin/python3 --use.python.with.venv- --python_version='>=3.14'
  --vllm_version=<the image's>` on the image's Python 3.14 and its preinstalled vLLM 0.29.1 on an MI300X: the
  route for vLLM on a ROCm 10 machine, whose wheels are built for ROCm 7.2 (below). Tests:
  `tests/cmeta_aops_basic_tests/test_tool_rocm.py`.
- **`program/test-sglang`: SGLang's offline engine, the way `test-vllm` does vLLM.** One generation with
  `sglang.Engine` after a short warm-up (the first call compiles the attention kernels), recorded with the
  versions, the device, the load, warm-up and generation times and the tokens per second; `--model`, `--n`,
  `--gpu_mem` (`mem_fraction_static`), `--max_len`, `--tp`, `--attention_backend`, `--sglang_version`,
  `--cuda_graph=0` (graphs stay on by default: SGLang's eager decoding is no usable default on ROCm). CUDA takes
  `sglang[all]` from PyPI in the program's venv; SGLang publishes no ROCm wheels, so on ROCm the program runs
  inside SGLang's official image with cMeta installed there and the image's venv as its python
  (`--use.python.tool_path=/opt/venv/bin/python --sglang_version=<the image's>`; README.md has the steps) -
  verified on an MI300X in `lmsysorg/sglang:v0.5.21-rocm10-mi30x`.
- **torchvision paired with torch on AMD's ROCm index, as on PyTorch's.** `tool/pip-torchvision` reads the
  torch that is installed (`pip show torch`, not the version a previous step recorded), computes the pair by
  PyTorch's numbering (2.x.y -> 0.(x+15).y) and, for a torch from AMD's index (`2.14.0+rocm10.1.0`), reads that
  index: the pair when it is there, its pre-release while torchvision's release is pending (`0.29.0a0+rocm10.1.0`
  next to torch 2.14.0 in October 2026: taken, its operators load), else a clear error naming the
  `--use.pip-torch.version` that has a pair; torchvision then comes from the same index and channel as torch
  whatever the auto route would pick. Verified on an MI300X: AMD's index (gfx942 forced onto it) 2.14.0 /
  0.29.0a0, PyTorch's ROCm index 2.13.0+rocm7.2 / 0.28.0+rocm7.2 - the pairing CUDA has had. Tests:
  `tests/cmeta_aops_basic_tests/test_pip_torchvision.py`.
- **`program/test-onnxruntime` records why a provider failed.** ONNX Runtime prints the cause (`EP Error ...
  Failed to load library ... libmigraphx_c.so.3: cannot open shared object file`) and retries on the CPU, which
  the program's disabled fallback refuses; the recorded error was that refusal. The program now captures the
  printed cause and adds what a missing library means. Found on the way: ONNX Runtime's ROCm EP is gone
  (removed in 1.23; `onnxruntime-rocm` on PyPI stops at 1.22.2) and the MIGraphX EP is the AMD provider -
  `onnxruntime-migraphx` 1.27.1 installs from PyPI through `tool/pip-onnxruntime` and needs AMD's MIGraphX
  library, which neither the ROCm 10.1 core apt repository nor AMD's pip distribution carried on 2026-10-08
  (the `migraphx` package of the ROCm 7.x apt repositories and the `rocm/onnxruntime` images have it): on an
  MI300X with ROCm 10.1 the provider could not load, and the program now says exactly that.
- **`task/setup-amd-gpu`: a Linux machine made ready for its AMD GPU and NPU.** A fresh account cannot open the
  nodes the kernel drivers create (`/dev/dri/renderD*`, `/dev/kfd` for ROCm, `/dev/accel/accel*` for a Ryzen AI
  NPU: all `root:render`; a desktop login gets them through its seat, a login over ssh does not), and the NPU
  runtime locks more memory than a login allows. The task adds the user to the groups that own the nodes (and to
  `video` with a GPU), gives the nodes at once with an ACL so that the calling run goes on, and for an NPU writes a
  memory-lock limit file and lifts the limit of the running process. Only what is missing runs; `--check` reports,
  `--dry_run` prints the commands, `--npu-` leaves the NPU alone; `sudo -n` unless the run is interactive, and a
  clear list of commands when sudo needs a password. The `rocm` target runs it first on Linux, so
  `cx program run <program> --compute=rocm` on a fresh machine sets the access up by itself. `tool/rocm` now installs
  its detection tool (`rocm-smi`) from the distribution's archive where it has one (Ubuntu 26.04 and later).
  Tests: `tests/cmeta_aops_basic_tests/test_setup_amd_gpu.py`.
- **ROCm as a first-class target, the way CUDA is.** `tool/rocm` now knows the ROCm version itself (amd-smi,
  the rocm-sdk CLI, `/opt/rocm/.info`), the GPU families from the kernel (`gfx942`, `gfx1152`: `/sys/class/kfd`)
  and the folders of the installation, and installs ROCm without root from AMD's Python distribution (TheRock):
  `cx tool setup rocm --install [--version=10.1.0] [--with.channel=stable|nightly|rc|dev] [--with.gfx=gfx942]`
  puts `rocm[libraries,devel,device-<gfx>]` - libraries, hipcc, headers, the device code of this machine's GPU -
  into a venv of the cache entry (the nightly and dev channels are the way to the development versions). The
  distribution's own packages (Ubuntu 26.04: ROCm 7.1) stay the fallback. `tool/hipcc` is the compiler of the
  `rocm` target (tag `lang-hip`, found next to rocm-smi, in `/opt/rocm*/bin`, `/opt/rocm*/core-*/bin`), and
  `target--rocm` sets it up as the target's SDK. `program/test-nmm-hipcc-rocm` is the CUDA test program carried
  over to HIP with hipify-perl, the first program of the target. `--use.target--rocm.gfx_override=<v>` exports
  `HSA_OVERRIDE_GFX_VERSION` on request (never by itself). PyTorch for ROCm (`tool/pip`): two sources of wheels -
  PyTorch's own index per ROCm line, and AMD's index with torch built against each ROCm 10 release for each GPU
  family (`torch[device-gfx1152]`, the way for a GPU that PyTorch's wheels lack kernels for);
  `--with.rocm_source=auto|pytorch|amd` (auto: AMD's index only for a GPU family PyTorch's wheels do not carry,
  Krackan Point's gfx1152 for one; an MI300X stays on PyTorch's index), `--with.rocm_channel=<channel>`;
  torchvision then comes from the same index, paired (above). `program/llama-cpp` and `program/lib-xopenme` accept the `rocm`
  target (the llama.cpp tool already knew the ROCm release builds).
- **The AMD Ryzen AI NPU as a target: `target--npu-amd`, `tool/flm`, `program/test-flm`.** The target finds the
  NPU without an SDK (Linux: the accel device of the kernel's amdxdna driver with its firmware and board name;
  Windows: AMD's ComputeAccelerator device), names its generation from the PCI ID and revision (1502 = XDNA1
  Phoenix / Hawk Point; 17F0 rev 10/11/20 = XDNA2 Strix Point / Strix Halo / Krackan Point) and runs
  `setup-amd-gpu` first on Linux (the device node's group, the memory-lock limit). `tool/flm` is FastFlowLM
  (MIT), the LLM runtime for the XDNA2 NPU: the portable release from GitHub (it bundles AMD's XRT runtime,
  no root), checked against its sha256; `flm validate --json` becomes the tool's features. `test-flm` runs one
  generation on the NPU through FastFlowLM's private server and records its timings, the way `test-ollama`
  does. Tests: `tests/cmeta_aops_basic_tests/test_target_npu_amd.py`.
- **Ollama on ROCm computes on the GPU now.** `tool/ollama` unpacks Ollama's ROCm runtime archive
  (`ollama-linux-<arch>-rocm.tar.zst`, about 1 GB) over the plain one when the target is rocm or
  `--with.variant=rocm` is asked: without it a `test-ollama --compute=rocm` ran on the CPU (`size_vram_mib: 0`).
- **Prebuilt LibTorch for ROCm.** `tool/torch-cpp-prebuilt` knows PyTorch's ROCm archive of LibTorch 2.7.1
  (`rocm6.3`, with the ROCm runtime inside) and picks the newest ROCm build for the `rocm` target, so
  `test-nmm-torch-cpp --compute=rocm --setup_torch_cpp.build=prebuilt` needs no source build. It downloads,
  configures and builds; at run time the archive's ROCm 6.3 libraries and a system ROCm of another line meet
  (seen with ROCm 10.1: `libamdhip64.so.7: undefined symbol hsa_ext_sampler_create_v2`), so it serves a machine
  whose ROCm is of the archive's line.
- **`tool/docker` and `tool/podman` install on Linux** (the distribution's packages: `docker.io` / `docker`,
  `podman`), Podman on macOS (Homebrew) and Windows (winget) too; before, both only detected.
- **`tool/aocc` and `tool/aocc-cpp`: AMD's optimizing C/C++ compiler as a cMeta compiler.** AOCC (AMD's clang for
  the Zen CPUs, closed source, behind AMD's EULA) is detected in `/opt/AMD/aocc-compiler-*` or installed without
  root from AMD's archive once the user accepts the EULA (`cx tool setup aocc --install --with.accept_eula=yes`;
  the archive's sha256 is checked); `cx program run test-nmm-c-cpu cpu --use.compiler-c.name=aocc
  --use.aocc.with.accept_eula=yes` compiles with it.
- **`task/expand-tmp-to-full-disk`: /tmp on the disk, not in RAM.** Ubuntu 26.04 (like Fedora and Arch) mounts
  `/tmp` as a tmpfs of half the RAM with a per-user quota; a 6 GB wheel that pip unpacks there fails with "Disk
  quota exceeded". The task masks systemd's `tmp.mount` (or comments the fstab line) and unmounts the tmpfs now,
  lazily when a process holds a file there, so `/tmp` is the root filesystem's folder from then on; `--check`,
  `--dry_run`; reports and does nothing on macOS, stops on Windows.
- **Fixed: `test-vllm --compute=rocm` took Python 3.14.** vLLM's ROCm wheels are built for Python 3.12 only; the
  generic range gave 3.14 and pip fell back to a CUDA torch from PyPI ("Device string must not be empty"). The
  program sets up Python 3.12 for the rocm target (`--python_version` still overrides).
- **Fixed: no program could start with `--compute=rocm`.** No C or C++ compiler tool listed the `rocm` target, so
  the compiler step of every such program stopped with "couldn't find tool artifact(s) with tags ['lang-c'] and
  constraints {... 'supports_compute': ['rocm']}". `tool/gcc`, `tool/gcc-cpp`, `tool/clang` and `tool/clang-cpp`
  now list it.
- **`task/select-src-by-tool-version`: one program, sources for several versions of a tool.** A step for a
  program's pipeline that picks the source folder by the version of a tool set up earlier in the run
  (`rules: [{version: '>=1.0.0', src_dir: src-v2}]`, the first match wins, comparators joined by commas), so a
  program follows a language that breaks its old sources and still serves the old tool. First user:
  `program/test-nmm-mojo-cpu`, whose `src/` was written before Mojo 1.0 and no longer compiled with the Mojo that
  pip installs today (`fn` removed, `var` required for new names, no `len()` of a `String`); `src-v2/` is the same
  program in the 1.x syntax, taken for Mojo 1.0.0 and later. Tests:
  `tests/cmeta_aops_basic_tests/test_select_src_by_tool_version.py`.

## 0.43.4
- **Hermes Agent as a harness: `tool/hermes`, `task/run-hermes`, `cxt run-ai --harness=hermes`.** Nous Research's
  open-source agent (MIT) joins Claude Code, Codex, OpenCode, OpenClaw, Antigravity CLI and Gemini CLI. The tool
  installs it with its official installer (downloaded first, non-interactive, without the browser tools and the
  computer-use driver; the code, its own uv, Python and Node, the configuration, keys, skills, memory and the session
  store stay under `HERMES_HOME`: `~/.hermes`, `%LOCALAPPDATA%\hermes` on Windows; the `hermes` command is a shim in
  `~/.local/bin` or `%LOCALAPPDATA%\hermesin`), pins a release (`--version=2026.9.24`, the git tag) and lists them.
  `run-hermes` has the flags of its sister tasks: headless `hermes chat -Q -q <prompt>` (one shot; the prompt on stdin
  with `--query-file -` when it is long or the command is the Windows .cmd shim), `--yes` = `--yolo`, `--stats` =
  `--format stream-json` turned back into text with the token counters and the session id, an interactive session
  seeded with the prompt, `--model <provider>/<model>` and `--reasoning none ... ultra` after `--`, a hint with the ways
  to connect a provider when none is (`cx tool run hermes -- model`, `auth add`, a key, a local server as the `custom`
  provider - which must serve a 64K context window). `run-ai` knows it: the memory index and the skills go in front of
  the prompt (Hermes reads `AGENTS.md` from the project by itself), a session resumes with `--resume <id>`, the id is
  read from the stream or the quiet run's `session_id:` line or `hermes sessions list`, and the transcript is exported
  with `hermes sessions export --format jsonl`. Tests: `tests/cmeta_aops_basic_tests/test_run_hermes.py` (the
  stream, the quiet tail, the sessions list and the export, from what hermes v0.21.5 printed with a local model).
- **`via: cmeta <version>` in the generator record of an agent session.** Every `run-<agent>` task now adds it to the
  `CMETA_GENERATOR` record it sets (`{"method": "agent", "agent": "Claude Code 2.1.292", "via": "cmeta 0.33.1", ...}`),
  so an artifact says whether the agent ran through cMeta (`run-ai`, `run-claude`, ...) or by hand. One constant in the
  task category API (`GENERATOR_VIA_KEY`) holds the word.
- **`tool/node-js` installs Node.js.** Before it only detected a Node and pointed at nodejs.org. Now, when none is
  found, the official release archive of the pinned version (the current LTS by default, 24.21.0 on 2026-10-07;
  `--version=<x>` pins another, `--versions` lists them) is downloaded from nodejs.org for this OS and CPU, its SHA-256
  checked against the SHASUMS256.txt of the release, and the whole tree - node, npm, npx, `lib/node_modules/npm` -
  unpacked into the cache entry, nothing on the PATH and nothing in the system; winget (`OpenJS.NodeJS.LTS`), Homebrew
  and the distribution's `nodejs npm` are the fallbacks. A tool that needs npm declares `node-js` with
  `add_tool_path_to_env`, as `openclaw` does. Tested on Windows, macOS (arm64) and Ubuntu (x64).
- **`tool/nix`: Nix detected and installed.** Found in `/nix/var/nix/profiles/default/bin` or `~/.nix-profile/bin`;
  installed with the Determinate Nix installer (downloaded first, `install --no-confirm`; it elevates with sudo, so a
  host with passwordless sudo installs unattended; multi-user daemon, flakes on); Windows only inside WSL2. Nix as a
  rung of the install ladder (`nix profile install`) is a later step.

## 0.43.3.1
- **`upgrade-os`: the OS packages and firmware, with the OS's own commands.** `cx task run upgrade-os` picks the
  commands from what the host task detected - apt-get/apt, dnf, yum, microdnf, tdnf, zypper, pacman, apk and xbps on
  Linux (index refresh, upgrade, `--full` for apt's dist-upgrade, `--autoremove`), `softwareupdate -ia` and Homebrew
  on macOS, `winget upgrade --all` on Windows (Windows Update only with `--windows_update`, through PSWindowsUpdate) -
  runs the system steps with `sudo -n` (plain `sudo`, which may ask once, in a terminal), adds the firmware with
  `--firmware` (fwupd on Linux; macOS and Windows carry firmware in their system updates), lists instead of upgrading
  with `--check`, and says whether the OS asks for a reboot (`/var/run/reboot-required`, `needs-restarting -r`,
  `zypper needs-rebooting`, the Windows Update registry key); `--reboot` then reboots, `--dry_run` prints the plan.
  Nothing is cached: every run is a real run. Tests: `tests/cmeta_aops_basic_tests/test_upgrade_os.py`.

## 0.43.3
- **An edited program is rebuilt, not run as it was.** The build stamp (`.cmeta-build-stamp.json`) now records the
  SHA-256 of the program's sources - the declared source files and the code and build files under its `src/`
  folder (headers, CMake lists, Cargo/Go manifests; data and binaries left out) - and `compile-and-run-program`
  recompiles when one differs, with `INFO: the program's sources changed since this build (<files>)`. Before, a
  reused build was checked for its targets, host, compiler, compile parameters and Android device, but not for
  its sources: an edited program silently ran the old binary until `--recompile` (seen 2026-10-07 with a benchmark
  whose binary was four days older than its source). A stamp written before this version has no digests and
  compares nothing until the next compile.
- **`tool/conda` installs Miniforge when no conda is found.** The pinned Miniforge release for this OS and CPU
  (Linux x86_64/aarch64, macOS x86_64/arm64, Windows x86_64) is downloaded, its SHA-256 checked against the
  per-asset file upstream publishes, and its installer run silently into the cache entry: user-level, no
  administrator rights, nothing registered, nothing on the PATH. The version is conda's own (`--version=26.7.2`
  = Miniforge 26.7.2-0); `--versions` lists the releases. The usual folders of Miniforge, Miniconda and Anaconda
  are searched first. On Windows the installer refuses a destination holding `!`, `%`, `^`, `&`, `;`, `=` or `,`
  (a cMeta home such as `D:\!FGG_Repos`): the installation then goes to `%LOCALAPPDATA%\cmeta\tools\conda`.
- **A conda environment as the Python of a request: `--use.python.with.conda`.** The `venv` task has `--conda`: a
  conda environment in `.conda-env` of the python entry (or of the request's venv path) instead of a uv venv, made
  by the conda cMeta set up (`tool/conda`) with `conda create -y -p ... python[=<version>] pip`
  (`with.conda_packages` and `with.channel` go into the command); the environment carries `.cmeta-conda-env.json`
  (who made it). Such an entry is private to conda requests, never shared with a venv request, and a conda request
  takes no detected python; a named interpreter at the same time is refused (the conda is chosen with
  `--use.conda.tool_path`). The new `tool/conda-package` is the conda analogue of `tool/pip`: `cx tool setup
  conda-package --with.package=numpy` installs into that environment with `conda install -p`, cached per python
  entry. `detect-python-env` now classifies with the record's rule (venv, conda base, conda environment, system -
  a conda environment is virtual, with its folders and `CONDA_PREFIX` as its environment instead of an activation
  script; an environment made with `conda create -p` anywhere is an environment, not a base). The provenance record
  says `the conda environment .conda-env made by conda 26.7.2`, lists what conda installed under
  `runtime.python.conda_packages`, and the `python` check passes only when a conda request ran in a conda
  environment. Checked with Miniconda on Windows and Miniforge on Ubuntu.
- **OpenClaw is driven through its tool.** cMeta installs OpenClaw when it is missing, so the docs, hints and
  README now say `cx tool run openclaw -- models status` / `-- models set claude-cli/<model>` instead of a bare
  `openclaw`, which may be another copy or none.
- **A requested conda base gets its venv on every OS, and a program's venv path keeps a requested interpreter.**
  Three corner cases of `--use.python.tool_path=<a conda or system python>`, found while assessing conda
  environments: (1) on Linux and macOS a conda base counts as "virtual" (its root has `condabin/`), so the
  requested base was accepted as the venv itself and no venv was made - pip would have installed into the
  user's conda base - while Windows made the venv; now the interpreter a venv is to be made on is never taken
  as the venv, and a venv's python (a symlink to its base on Linux and macOS) is never mistaken for the base.
  (2) `detect-python-env` looked one folder too high for a conda base on Windows, where `python.exe` sits at
  the root: it is virtual there too now (an activated conda base is extended like an activated venv, as before
  on Linux). (3) A request with a venv path of its own (a program's venv in its build folder) dropped the
  interpreter and made the venv on a uv-managed python; now `python_base` is kept, the venv at that path is
  made on the interpreter, and a venv found there that was made on another python (the `home` of its
  `pyvenv.cfg`) is left aside and remade. Checked with Miniconda on Windows and Miniforge on Ubuntu.
- **Provenance: a wheel's libraries belong to the pip tool that installed them.** A Python program's venv lives in
  the program's build folder, so the libraries a wheel brings along (ONNX Runtime's CUDA provider, the `nvidia-*`
  runtime wheels, numpy's OpenBLAS) were listed in `provenance.json` as unattributed (`tool: null`). The record now
  reads the venv's own metadata - every distribution's `RECORD` for its files, its `METADATA` for the distributions
  it requires - and attributes such a library to the `pip-<package>` tool of the run whose package is that
  distribution or requires it, directly or through other distributions (`nvidia-cudnn-cu13` <- `onnxruntime-gpu[cuda]`
  -> `pip-onnxruntime`). The nearest tool wins, a tool claims only files of the venv it installed into, and a file of
  a distribution that no tool of the run pulled stays unattributed. The library's distribution is recorded as `dist`
  and shown in `cx program provenance` when it is not the tool's own package. Seen with `--provenance=loaded` on
  Linux and macOS, where the loader log lists what a Python process really loaded. The NVIDIA driver's own libraries
  (`libcuda`, `libnvidia-*`, `nvcuda.dll`) are attributed to the `cuda` entry of the run (the driver and GPU the
  target recorded), marked `(driver)`.
- **Provenance: the frameworks of a Python run, and a requested CUDA version that a wheel ignores.** The record's
  `runtime.frameworks` lists the distributions behind the loaded wheel libraries and the package of every pip tool
  of the run, with their versions (`nvidia-cuda-runtime 13.4.92` is the CUDA runtime a wheel brought, a torch version
  ending in `+cu130` says which CUDA it was built for), read from the venv's metadata, no extra process. A
  `--use.nvcc.version` (or `cuda`, `lib-cudnn`) on a run whose `libcudart` (`libcudnn`) came with a wheel is now an
  error-level `wheel` check naming the wheel and the tool: the request cannot apply to a prebuilt binary, the package
  must be pinned instead.
- **Provenance: the toolchain a Go or Rust binary says it was built with.** `build.toolchain` reads the binary itself
  (a Go binary's buildinfo; a Rust binary's `rustc version` string, or the toolchain commit in its `/rustc/<commit>/`
  source paths, compared with the resolved `rustc -vV`) and the `toolchain` check compares it with the compiler cMeta
  resolved: a Go that `GOTOOLCHAIN` fetched or a rustup default toolchain other than the one set up is a warning, an
  error when that compiler's version was requested with `--use`.
- **Provenance: which Python ran, and whether a requested interpreter was used.** `runtime.python.environment` says
  what kind of Python a run took - a venv (and what made it, uv or not, and the base it was made on), a conda base
  or a conda environment (by name), a uv-managed interpreter, or the system's - read from `pyvenv.cfg` and
  `conda-meta/`; the checks carry it in one line. A `--use.python.tool_path=<interpreter>` request is now checked
  (`python`): the run used that interpreter, or a venv made on it, else an error names what ran instead (found on
  2026-10-06: a plain program run with a Miniconda interpreter requested got a uv venv on a uv-managed Python).
- **A reused build completes its tools' features from the current cache entries.** A reused build replays its
  compile-time context, with every tool's features of that day; a tool entry re-detected since
  (`cx tool setup <tool> --update`) may carry keys the snapshot lacks. `compile-and-run-program` now completes
  them from the entry's current cached result (`build_identity.complete_restored_tools`): keys the snapshot has
  keep their values, the record of what the build used (found with the quantized model added to
  `lib-litert-android` after an Android build).
- **`tool/lib-litert-android`: the quantized MobileNet v2 as a second model.** Next to the release's float32 test
  model (`features.model`), the setup fetches TensorFlow's hosted quantized MobileNet v2 (uint8 in and out) and keeps
  its `.tflite` as `features.model_int8` for the integer paths of NPUs; both digests are recorded. An entry made
  before gets it with `cx tool setup lib-litert-android --update`.
- **A requested interpreter that is no venv gets its venv made on it.** `--use.python.tool_path=<a conda env's
  python, a system python>` (or `--here`) while a venv is wanted used to be dropped by the venv rule, and the venv was
  then made on a uv-managed Python: the interpreter the user named never ran. `tool/python` now turns such a request
  into `python_base`, the `venv` task makes the venv on it (`uv venv --python <interpreter>`, its new `--python`
  parameter), the entry is matched on `python_base` on the next request and is never handed to a plain request, and a
  version given at the same time is refused (the interpreter decides the version). `--use.python.with.venv-` runs the
  interpreter itself, as before. Checked with Miniconda on Windows: the record says `venv made by uv on a conda base`
  and the `python` check passes.
- **`run-openclaw`: the sub-agents OpenClaw calls come from cMeta's tools.** OpenClaw may run claude, codex, opencode,
  gemini or agy; they are now set up as cMeta tools before openclaw starts (detected only, never installed from here)
  and their folders go first on the PATH of the openclaw process, with openclaw's own, so a sub-agent is the pinned,
  recorded copy and not whatever the shell's PATH holds. `--agents=claude,codex` narrows the list, `--agents=` leaves
  the PATH alone; agents not on the machine are reported and skipped; `--dry_run` prints what was found. Checked
  live on 2026-10-07: a headless turn through OpenClaw's `claude-cli` backend (the Claude Code login) saw cMeta's
  copy of `claude` first on its PATH, from a shell whose own PATH had none; `claude-cli/claude-opus-5-5` answers
  although OpenClaw 2026.6.10's catalog stops at Opus 4.8 (`tool/openclaw/_desc_models.yaml`).
- **New tools `hyperfine` and `sccache`, from their pinned releases.** hyperfine 1.21.0 (the command-line benchmark:
  warmup, outliers, JSON/CSV/Markdown exports; upstream publishes no checksums, HTTPS only) and sccache 0.18.0
  (Mozilla's shared compilation cache for gcc/clang/MSVC, Rust and nvcc; SHA-256 checked against the per-asset
  file) through `common_release`, x86_64 and aarch64 on Windows, Linux and macOS; an installation on the PATH or in
  cargo's bin is detected first. Checked on Windows x86_64, Ubuntu x86_64 and macOS arm64.

## 0.43.2
- **Long prompts for every agent task: a file instead of a command line argument.** An interactive session
  preloads its first prompt as a command line argument, and `opencode run` / `openclaw agent` have no stdin mode at
  all - but Windows caps a whole command line at 32767 characters (`[WinError 206] The filename or extension is too
  long`: `cxt run-ai --harness=codex`, whose context alone is ~57K characters, could not start an interactive codex).
  `run-claude`, `run-codex`, `run-opencode`, `run-openclaw`, `run-agy` and `run-gemini` now write a prompt longer
  than 30000 characters to a file and pass a one-line request to read it first (the shared `prompt_via_file()` of
  the task category API, which also replaces run-gemini's own launcher-script fallback); the agent reads it, follows
  it and stays interactive. The file is `--long_prompt_file=<file>` - run-ai names `!AI/log/<stamp>.<harness>.prompt.md`
  and keeps it as the record of the run - else `<prompt_file>-prompt.md`, else a temporary file removed after the
  run. Headless runs of claude, codex, gemini and agy still send the prompt on stdin.

## 0.43.1
- **`run-ai --write=ask|project|all|none`, `-w`: what a run may write, in one switch.** It sets the harness's own
  approvals and the guard of the used artifacts together: `ask` (the default) as before; `project` lifts the
  harness's questions (what `--yes` does); `all` (`-w`) also lets a session change the memory and skills of the used
  artifacts directly - the changes are listed, recorded in the artifact and the versions before the run saved in
  the project's `!AI/log/<stamp>.before/` (the guard's new mode `keep`); `none` runs the harness in its plan or
  read-only mode (Claude Code, Codex, OpenCode, Antigravity, Gemini CLI). The key `write` of the config
  `task-run-ai` is the default of a machine; a flag wins over it.
- **`run-ai`, `import-ai`: long project paths.** Claude Code cuts a project slug longer than 200 characters and
  appends a hash of the path; the conversations, the transcript export, the seed and `import-ai --claude_folder`
  now find such a folder (by its prefix, checked against the working directory its sessions recorded) instead of
  reporting nothing exported.
- **`run-ai`: runs started within the same second.** A run that writes records reserves its stamp with an
  exclusive `!AI/log/<stamp>.lock` (released once the run record holds it), so two terminals or a script starting
  runs of one project at once never share a conversation or records.
- **`run-ai` with OpenClaw, checked live** (OpenClaw 2026.6.10, `claude-cli` models: new sessions, resume,
  transcript, hand-overs both ways). OpenClaw works in its own workspace whatever the current directory is, so the
  orientation now names the project folder. Its terminal UI gets `--session agent:main:explicit:<id>` instead of
  the flags of `openclaw agent` it refuses (`--session-id`, `--model`: run-ai says to pick the model with `/model`),
  and the id the UI gives a new session is read back from OpenClaw's index. Session files are found under any agent
  and `OPENCLAW_STATE_DIR`; tool calls are kept in the transcript as one line.
- **`run-openclaw`: the reply and the token counts.** The reply is the result's `payloads` (it was the whole JSON);
  the usage is the turn's (`meta.agentMeta.usage`), counted like run-claude (sent = new + cache write + cache read);
  for the `claude-cli` provider, whose usage OpenClaw reports for the last model call only, the counts come from
  Claude Code's own session of the turn. A provider without a key fails with a hint to `openclaw models list` and
  `--model=claude-cli/<model>`.
- **`import-ai` / `run-ai`: skill copies that went apart from their source.** `import-ai` records where each skill
  came from and a hash of what it copied (`!AI/skills/.sources.json`); every run compares the copies with their
  sources on this machine and says which side changed - a warning with the `import-ai ... --overwrite` command when
  the source is newer, a note when the copy was changed in the project.
- **`run-ai --summarize`.** One prompt to the harness (claude: its `haiku` unless `--model` says otherwise) writes a
  summary of a conversation's transcript to `!AI/log/<id>.summary.md`; a later hand-over points to it first, then to
  the transcript, and `--conversations` marks it. The conversation is not continued by it.
- **`run-ai --trim_context`: a token budget.** Over the limit of the context estimate, the context sources are left
  out from the last (this machine's mapping, the repository default, the deeper levels) until the estimate fits,
  instead of stopping; `trim_context: true` in the config `task-run-ai` makes it the default of a machine.
- **`run-ai --apply_pending`: one question per change.** Besides "yes" (all of an artifact's changes) and "no",
  "e" asks for each change; what is not applied stays staged.
- **`run-ai`: the transcript keeps the request.** For the harnesses that get the hand-over, the orientation and the
  context in the prompt, a mark line ends them; the transcript shows what follows it, with a note. Gemini and
  OpenClaw times are shown in local time like the others.

## 0.43.0
- **`run-ai`: a coding agent on a cMeta artifact, with its memory in the artifact** (`task/run-ai`). One front
  door to the agent tasks - `--harness=claude|codex|opencode|openclaw|antigravity|gemini`, or any `<x>` with a
  task `run-<x>` - that keeps what the agent learns and produces inside the artifact it works on, in a folder
  named `!AI`: `memory/` (Claude Code reads and writes it through its `autoMemoryDirectory` setting; the other
  agents are given the index), `skills/` (loaded as a Claude plugin, listed for the others), `log/` (the run
  record, the output and the token counts of every run) and the conversations. A run continues the
  conversation with the latest activity through the agent's own session; `--new` starts another,
  `--conversation=<id>` picks one, `--conversations` lists them; when the agent changes, the new one is handed
  the transcript `!AI/log/<id>.transcript.md`, rewritten after every run from the agents' own session stores.
  The project is `--project=<cref>`, else the artifact the current directory is in, else the directory itself.
  `--model=<model>,<effort>` and `--effort` are given in the agent's own names and turned into its flags from
  `tool/<agent>/_desc_models.yaml`; `--list_models` prints the lists. `--dry_run` shows what the agent would
  be given and runs nothing. The first run of a project copies the memory Claude Code keeps for that folder
  into an empty `!AI/memory` (`--no_seed`: not). Reference: `task/run-ai/README.md`; overview in
  `docs/cmeta-aops/agent-tasks.md`.
- **`ai_uses`: whose memory the AI sessions of an artifact read** (`task/run-ai`). A list of cRefs in the
  artifact's `_desc.yaml` - or in its repository's `_cmr.yaml`, as the default of all its artifacts - names the
  artifacts whose `!AI/memory` and `!AI/skills` a session is given as read-only context; `--context=<cref>;<cref>`
  adds some for one run, `--context_depth` follows the lists further, `--skip_ai_uses` reads none. A mapping in
  the config artifact `task-run-ai` of the local repository (`local_ai_uses`, by repository or by artifact) lets
  the sessions of a shared repository read a private artifact on one machine without the repository naming it.
  The context is estimated in tokens before the run and compared with `--max_context_tokens` (or
  `max_context_tokens` of that config). The used artifacts stay read-only for a run, for every agent and
  permission mode alike: a session stages a change under the project's `!AI/pending/<alias>--<UID>/`,
  `--pending` lists the proposals with their differences, `--apply_pending` applies them on the user's word,
  and after every run `--context_guard` (`ask`, `restore`, `report`, `off`) deals with what was changed there
  directly.
- **`import-ai`** (`task/import-ai`) copies memories (Claude Code memory files or folders of them;
  `--claude_folder=<folder>` for the memory Claude Code keeps for a folder) and skills (a repository's
  `.claude/skills`) into the `!AI` folder of an artifact: identical files are skipped, the newer one wins,
  `--overwrite` forces; `MEMORY.md` keeps its lines, their order and its headings and gains an entry per new
  memory, and an import of skills only leaves it alone; the plugin manifest and a record of what came from
  where are written.
- **Antigravity CLI and Gemini CLI as tools and tasks** (`tool/agy` + `task/run-agy`, `tool/gemini` +
  `task/run-gemini`): Google's two terminal agents with the flags of `run-claude`, `run-codex` and
  `run-opencode`. `agy` - for personal Google accounts - is installed as the release binary from GitHub;
  `gemini` - for Gemini Code Assist Standard/Enterprise licences, API keys and Vertex AI, since it refuses
  personal accounts - as the release bundle over the `node-js` tool, with npm as the fallback. Both carry a
  `_desc_models.yaml`. `run-gemini` never opens a browser in a headless run and tells a failed run which case
  it is: nothing configured, a personal account that is refused, or a key the API does not accept.
  Tests of the four items above: `tests/cmeta_aops_basic_tests/test_run_ai_pending.py`,
  `test_run_ai_context.py`, `test_run_ai_conversations.py`, `test_run_ai_engine.py` (the task through the
  engine with a stand-in harness that calls no model), `test_run_agy_gemini.py`, `test_import_ai.py`.
- **`--use.init.default_cache_repo=<repo>` takes effect** (`task/init`): the run-wide cache repo given on the
  command line was stored under a key named after the repo, so the task engine never saw it and every entry
  still went to `local`. It is now stored as `default_cache_repo`, the key the engine reads and `config::task`
  may set: every task of such a run, dependencies included, finds and creates its cache entries in that repo,
  an unknown repo is an error, and a repo whose name equals a key of `config::task` (or `return`) no longer
  replaces that key. Described in `docs/cmeta-aops/task-engine.md`; tests in
  `tests/cmeta_aops_basic_tests/test_init_default_cache_repo.py`.
- **A program's builds live in one cache entry per request** (`category/task/api/build_identity.py`,
  `task/compile-and-run-program`): the entry is found by its params like every other task entry - the program,
  the explicit choices of the request (the `--use` tree with tool names, versions and variants, `--compile.*`,
  `--with.*`) and the compute targets the run resolved - so `--use.nvcc.version=12.9` and `--use.nvcc.version=13.3`
  build side by side and compare, and the same request comes back to its own entry, whose build-folder
  stamp guards against a changed resolution. The plain request (no explicit choice, cpu) keeps the entry
  name `task--program--<program>` every program had before and adopts such an entry when it exists without
  params, so the builds made before stay where they are; the others are `task--program--<program>--<uid>`.
  The entry's params hold the request, its digest (the key the lookup matches) and, after a run, the
  resolved toolchain (name, version and path of every tool). `cx program provenance --all` groups the
  records by entry and names each entry's request, `--entry=<alias|uid|digest>` picks one,
  `--diff=<entry>:<folder>` compares across entries, and the default is the newest record;
  `cx program clean` works over every entry (`--entry` for one).
- **Every program run leaves its provenance record** (`task/compile-and-run-program`,
  `category/task/api/provenance.py`): `provenance.json` in the build folder, next to the build stamp - what the
  request made explicit (`--use.<tool>.*`, `--compile.static`, `--compute`, `--with.*`, the program parameters,
  taken before the program's defaults join), every tool the run resolved (name, version, path, cache entry,
  library names), the binary's dependencies as the loader would resolve them under the run's environment
  (the pure-Python inspector), the driver and GPU, Python, and the checks: a static build loads no shared
  library beyond the documented set for its targets (CPU: fully static, or the OS runtime and the OpenMP DLL
  on Windows; CUDA: also the C++ runtime, the driver and NVIDIA's shared libraries - `libcudart`, `libgomp`,
  `libcrypto` present are violations), a library of a resolved tool comes from that tool's folders, every
  `--use.<tool>.version` matches the resolved version, an accelerator the program required was available. A
  failed check is an error when its configuration was requested explicitly and a warning when it came from a
  default; failed checks are printed as `PROVENANCE: ...`. The record is passive: it changes no command and no
  environment, and a problem writing it is a warning. `--provenance=off` writes nothing; `--provenance=loaded`
  also records what the processes really loaded (Linux: the dynamic loader's log into a file per process,
  macOS: dyld's log; elsewhere the resolution stands in); `--provenance=strict` fails the run (99) on a failed
  error-level check, after writing the record.
- **`cx program provenance <program>`** shows the provenance record of a run (`provenance.json` in the
  program's build folder): the header, one row per tool with what was requested, what was resolved and where,
  and the libraries the process loaded from that tool's entry, the checks and the libraries loaded from
  outside any tool; `--target_tmp=<name>` picks a build folder, `--all` lists every folder with a record,
  `--diff=<other folder | record file>` prints the differences between two records (request, resolved
  versions and paths, libraries added and removed, checks that changed), `--as_flags` prints the options
  that reproduce the resolved configuration, `--as_json` the record. The program category declares the
  `cache` category it reads the build folders from. Documented in `docs/cmeta-aops/provenance.md`.
- **A compiler's runtime library is attributed to the compiler of the run** in the provenance record: GCC's
  `libgomp`, `libstdc++` and `libgcc_s`, LLVM's `libomp` and `libc++`, Intel's `libiomp5`, MSVC's `vcomp140`
  live in the shared system folders, where no tool names them. The record asks the compiler itself
  (`-print-file-name`) and attributes the library when the compiler links against the same file; MSVC's DLLs
  are known by name and must lie in the Visual Studio installation or in `System32`; a compiler installed in
  a folder of its own (LLVM on Windows, MinGW, a Homebrew GCC, an Android NDK) owns the runtime-named
  libraries under it. The library then shows under the compiler's row with `(runtime)` and carries
  `role: runtime`; a `libgomp` loaded from elsewhere stays unattributed.
- **`CMETA_PROVENANCE`** sets the provenance mode of every `cx program run` that names none: a test session
  or a CI job exports `CMETA_PROVENANCE=strict`, an interactive shell keeps the passive default
  (`--provenance=<mode>` always wins).
- **The test session of a shell:** `cx task run test-session --start` prints the line that makes the new
  session the shell's current one (`export CMETA_TEST_SESSION=<id>`; `set` on cmd, `$env:` on PowerShell;
  `--shell=`, `--print=export`). With the variable set, every `cx program run` attaches its provenance
  record to the session (`attachments/provenance--<program>--<build folder>--<HHMMSS>.json`, with a note)
  and runs with `--provenance=strict` unless the run names a mode or `CMETA_PROVENANCE` is set.
  `--attach_as=<name>` stores a single attached file under another name.
- **The library folders of the tools from cMeta's cache come before the shared system folders on the link
  line** (`task/setup-compile`), and in the run's library path. With OpenSSL's `/usr/lib/x86_64-linux-gnu`
  first, a clang build of an OpenMP program linked the distribution's `libomp` instead of the one
  `lib-openmp` had resolved in the LLVM entry, and loaded it at run time; the provenance record's origin
  check found it.
- **`cx program clean <program>`** removes the build folders of the program's cache entry
  (`task--program--<program>`), where `cx program run` builds and runs since 2026-06 (`--target_tmp=<name>`
  for one folder, `--all` for every program); before, it deleted `tmp*` folders inside the program artifacts,
  where nothing is built any more. Folders left inside artifacts are listed, not removed. The docs now
  describe the build folder, `--target_path`, `--work_path`, `--here` and `{pwd}`, the cleanup commands and
  the Python venv policy of programs (`docs/cmeta-aops/program-and-compute.md`).
- **`_desc_models.yaml` in `tool/claude`, `tool/codex`, `tool/opencode`, `tool/openclaw`:** the models and
  efforts of each coding-agent harness as data next to the tool - the flags that select them (`flags.model`,
  `flags.effort`, with `{{model}}` / `{{effort}}`), the effort vocabulary with a line of advice each, and one
  entry per model (description, context window, default effort, API price, plans, aliases, the efforts it takes).
  Retired models stay with `disabled: true` so that an old `generator.model` can still be read; `legacy`, `until`
  and `unverified` mark the rest; `updated`, `checked_with` and `sources` say when and against what the list was
  checked. `run-ai` reads it for `--model=<model>,<effort>` and prints it with `--list_models`;
  `docs/cmeta-aops/agent-tasks.md` points at the files.
- **`run-codex --resume=<session id>`** continues a recorded Codex session instead of starting one:
  `codex exec resume <id> -` with the prompt on stdin, `codex resume <id> [prompt]` for an interactive session
  (the picker is never shown); the model and effort flags apply as to a new session.
- **A test session names the model of a Claude Code session started with its default model**
  (`task/test-session`): `CMETA_GENERATOR` then carries no model, so `--finish` takes it from the session's
  transcript - the model that wrote the most output (subagents may run a smaller one) - and records
  `agent.model` with `model_from: transcript`. A model given by `CMETA_GENERATOR` or `--model` is kept.
- **`.gitignore` ignores `!AI/`**: the folder in which AI sessions run through cMeta keep their memory, skills,
  conversations and logs inside the artifact they work on (written `\!AI/`, since a leading `!` negates).

## 0.42.0
- **A reused tool entry is completed from its tool's current `_desc.yaml`** (`task/setup`): a cached entry
  carries the features of the time it was detected, so a key the meta gained afterwards (a compiler flag
  such as `openmp_static_archive`, nvcc's `linker_option_prefix`) was missing on every reuse until `--update`.
  Now `finish_dynamic_result` lays the meta's declarative `features` block (the `all` / host-OS / `linux`
  block the detection starts from) under the cached features on every use: the keys the entry lacks come
  from the meta, what was detected keeps its value, lists are not appended, and the entry's files are not
  rewritten (they stay the record of what was detected; `--update` re-detects). `-v` names the keys added.
  `task/setup-compile` no longer reads the archive flag from the tool's meta itself.
- **One Visual Studio, no question** (`tool/microsoft.visual-studio`): a request that names no exact
  version - clang's dependency `msvc` asks for none, nvcc asks for a range - takes the newest installation
  among the cached ones that match, with an INFO line that names the others and
  `--use.microsoft-visual-studio.version=<version>`. Before, two installations meant "More than 1 cache
  entry found" in every such run, and `-q` took the first - the newest, now the answer without the
  question. An exact version matches or fails as before; the entries of one version (one per Windows SDK)
  stay for the engine's own choice.
- **`task/host` no longer waits for a hostname nobody resolves:** `get_hostname_info()` resolved the
  hostname with `getaddrinfo()` to add its addresses; on a machine whose name no resolver knows (a CI
  runner, a host without a DNS entry) that waited for the resolver's timeouts - half a minute on some
  macOS machines - on every task run, since the host task is not cached on disk. The lookup now runs in
  a daemon thread, is given one second and is asked once per process; afterwards the task goes on with
  the addresses it found without DNS (the outbound ones).
- **A static build links GCC's OpenMP runtime statically too** (`task/setup-compile`, `tool/gcc`, `tool/gcc-cpp`,
  `tool/nvcc`): with `with.static` and OpenMP, the static runtime of the compiler that provides it - `libgomp.a`,
  which the compiler reports with `-print-file-name` (`openmp_static_archive` in the compiler's meta; the host
  compiler's when nvcc runs the link) - goes to the linker by its path, with `-lpthread -ldl` and `--as-needed`
  after it, so that the `-lgomp` gcc appends for `-fopenmp` adds no shared library: a static CUDA binary no
  longer loads `libgomp.so`. A compiler without the archive stops the static build with what provides it (the
  archive comes with gcc itself on Debian, Ubuntu, Fedora, RHEL-likes, openSUSE and Alpine; Arch Linux ships
  none), as the static OpenSSL rule does. clang keeps `lib-openmp`'s `libomp.a`; Windows keeps its DLL note.
- **The compiler of every build is chosen without a prompt** (`task/compiler`): when several compilers
  suit a request that names none - several compiler tools on the machine, or several cached compilers of
  a CPU build - the preferred compiler of the OS is taken (`preferred_compilers` in
  `task/compiler/_desc.yaml`: MSVC on Windows, GCC on Linux, clang on macOS), then the tool the
  repository ranks first, then the newest version; of several cached versions of one compiler, the
  newest. An INFO line names the others and the option that picks one of them
  (`--use.compiler-<lang>.name=<tool>`, `--use.compiler-<lang>.version=<version>`). Before, such a build
  asked "Select tool" or "More than 1 cache entry", and `-q` took the newest version - clang over MSVC or
  GCC on a machine with both; the rule the CUDA host compiler got below now holds for every compiler
  choice (the CUDA polybench's CPU part was the last to ask). Android targets are unaffected: only the
  NDK's clang builds them.
- **The compilers of a CUDA run are chosen without a prompt** (`task/compiler`, `tool/nvcc`): among
  the cached C++ compilers that match a CUDA run, those the toolkit rejects (the limits of its
  `host_config.h`, which `tool/nvcc` sets as version limits of the compiler tools) or that lack the
  request's `extra_tags` / `extra_match` are no longer offered; of the rest, the compiler the
  repository ranks first (MSVC, GCC, clang: the compiler of the OS) is taken, then the newest version -
  the order of a machine without cached compilers - said in an INFO line. Cache entries of one
  compiler and version made for different compute lists (`cuda`, then `cuda,vulkan`) count as one
  compiler, for every language; and the entry of nvcc itself follows the toolkit set up for the `cuda`
  target in the run. Before, a CUDA run on a machine with such entries asked "More than 1 cache entry"
  up to three times, and `-q` took the newest version: a clang the toolkit rejects on some machines,
  after which the setup tried to install an older one. `--use.compiler-cpp.name=<tool>` still picks
  another compiler; a `--use.compiler-cpp.version` the toolkit rejects now stops the run with the
  toolkit's message (before, the version was quietly replaced by one within the limits). Once a
  compiler is decided, the version range set for its tool narrows to that version, and `tool/msvc`
  passes the version asked of it on to the Visual Studio installation it sets up, as `gcc-cpp` and
  `clang-cpp` do with theirs: a machine with two Visual Studios is not asked which one once the MSVC
  version is known. Choices between different compilers for other targets are asked as before.
- **`tool/mpi`: Intel MPI on Linux hosts.** `--with.mpi=intel` on Linux puts the environment's `lib`
  folder on `LD_LIBRARY_PATH` as well (the impi-rt wheel's `mpiexec`, Hydra proxies and `IMB-MPI1`
  carry no RPATH, so `cx tool run mpi -- -n 2 IMB-MPI1 PingPong` failed to load `libmpi.so.12`);
  `features.lib` names it. An Intel MPI job spans Linux hosts or Windows hosts, not both: the
  Windows launchers are PowerShell and the Hydra service, the Linux bootstrap servers ssh and the
  schedulers, and no `-hostos` exists in the 2021 references. Verified across two Linux hosts over ssh.
- **Tests:** the hermetic suite passes on Linux as on Windows (the Windows-path cases of
  `test_tool_upgrade` run on Windows only; the Intel NPU install tests pin the glibc version they
  assume). `task/compiler` accepts `version` (its `run()` read it, `init()` rejected it: a static C++
  build that had to build a static dependency failed with `unknown input parameter "version"`).
- **The tool search never recurses from a filesystem root** (`category/tool/api/v1.py`): a search
  pattern with `**` whose fixed part is `/`, a drive root or a pseudo file system (`/proc`, `/sys`,
  `/dev`, `/run`) is skipped (said in verbose mode). On Debian, `/usr/bin/clang` is a link into
  `/usr/lib/llvm-<N>`; `tool/llvm` gave it the home `/` and `tool/lib-openmp`'s `<home>/**` walked
  `/proc` for ever. `tool/llvm` now takes the folders of the real binary behind a link, and
  `tool/lib-openmp` searches the LLVM's `lib` folders and the usual places, not a whole home.
- **`tool/llvm`, `tool/clang`, `tool/clang-cpp`: a Swift toolchain's clang ranks last.** The clang of
  swiftly or of a Swift toolchain (its `--version` names swiftlang) is often first on `PATH` but has no
  OpenMP headers or runtime; detection now places every other clang before it, whatever the version,
  and warns when it is the only one (`cx tool setup llvm` installs LLVM). Before, an OpenMP program
  built with it failed on `omp.h`. Debian's and Ubuntu's `/usr/lib/llvm-<N>/bin` are searched too.
- **`tool/lib-cudnn` installs cuDNN** from NVIDIA's public redistributable site when no cuDNN matching
  the CUDA toolkit is installed: the archive for the OS, CPU (Linux x86_64/arm64, Windows x64/arm64)
  and CUDA major version (12, 13), cuDNN 9.27.0.42 pinned with NVIDIA's SHA-256 digests, unpacked
  into the cache; `--version=9.x.y` takes another release from NVIDIA's index. It refuses a cuDNN too
  new for the machine's GPU (cuDNN 9.11 and later need compute capability 7.5; the earlier releases
  run on Maxwell) with the releases that still run there; `--with.any_gpu` overrides. README,
  `_desc_sizes.yaml`.
- **A build folder is used only for what it was built for** (`task/compile-and-run-program`,
  `task/setup-compile`, `category/task/api/build_stamp.py`): after a compile the build folder gets
  `.cmeta-build-stamp.json` (targets, host, compiler, the compile parameters that change the output,
  the Android device). A run that asks for other targets, another compiler (`--use.compiler-<lang>.name`),
  a static instead of a dynamic build, or another device in that folder is refused with "was built
  for …; use --target_tmp=<name>, --recompile or --clean"; before, the folder was silently reused (on
  macOS a host build of llama.cpp was pushed to an Android device, CMake having kept its cache).
  Optimization, debug and profiling flags are recorded, not refused for. `--recompile` and `--clean`
  go on; a folder made before the stamps is used as before and gets one.
- **Disk space of program builds:** `program/<name>/_desc_sizes.yaml` (the rules of tools) is checked
  against the free space of the build folder's volume before the compile phase (`min_free_gb`,
  `--skip_size_check` as for tools); the size of the build folder is recorded after a successful
  compile (`_impact.disk_gb`). Rules for `build-pytorch`, `build-vllm`, `build-llama-cpp`,
  `build-executorch-android`, `build-torch-cpp`, `build-pytorchvision`.
- **A static build links OpenSSL's static archives, or stops** (`tool/lib-openssl`, `task/setup-compile`):
  on Linux and macOS `libssl.a` and `libcrypto.a` go to the linker by their paths - named, a link
  without `-static` (nvcc's host link of a CUDA program) took `libcrypto.so` of the same folder, so a
  "static" CUDA binary loaded the shared OpenSSL; the libraries they need come by the paths of their
  archives too (the system's, or the one `lib-zlib`, `lib-zstd` or `lib-jitterentropy` builds). Without
  the archives (Fedora's `openssl-devel`, Arch Linux, macOS without Homebrew's OpenSSL) a request with
  `with.static` fails at the setup, and any static build stops in `setup-compile`
  (`features.static_unavailable`), with what gives them on this system (`libssl-dev` on Debian and
  Ubuntu, `openssl-libs-static` on Alpine, Homebrew's `openssl@3`, the OpenSSL developer package on
  Windows; Fedora, RHEL-likes, Arch Linux and openSUSE package none: how to build and register one):
  a static build never falls back to a shared library. `setup-compile` passes a library given
  as the path of a file to the linker as it is, so any lib tool can hand archives that way (the `lib-*`
  tools of `common_static_lib.py` do). On macOS "static" means static third-party libraries with the
  dynamic system library, `libSystem` (README); the copies of Homebrew's archives in a `static` folder
  of the cache entry are no longer made. `test-nmm-c-cpu`, `test-nmm-cpp-cpu` and `test-nmm-nvcc-cuda`
  pass `with.static` to `lib-openssl` on macOS as on Linux.
- **OpenMP runtime for clang on every OS** (`tool/lib-openmp`): on Windows the folder of clang's
  `libomp.dll` goes on the program's run-time path (before, a clang build with OpenMP started only when
  Visual Studio's own LLVM folder happened to be on the path); a distribution's `libomp-dev`
  (`/usr/lib/llvm-<N>/lib`) is detected. The matmul and polybench programs ask for it on every OS when
  clang is the compiler. README.
- **No static OpenMP runtime exists on Windows** (LLVM's build refuses one, MSVC's vcomp is a DLL):
  `setup-compile` says so for a static build with OpenMP, which keeps the runtime as a DLL next to its
  static C run time and libraries.
- **`polybench-cpu-gemm`, `polybench-gemm-cpu-cuda`:** pass `compile.static` to `lib-polybench` and
  `lib-xopenme`, so a static build uses the static entries, as the matmul programs do.
- **Disk space of tools** (`task/setup`, `category/tool/api/common_sizes.py`, new; `_desc_sizes.yaml`
  of 16 tools, new):
  - **`tool/<name>/_desc_sizes.yaml`** declares what a setup needs: a list of rules (first match
    wins) with `peak` and `kept` GB, matched by `version` (fuzzy), `os`, `arch`, `method`
    (`install`, `build`), `compute` and `with.*`. `_desc.yaml` is not involved.
  - **The check:** before an install or a build, `task/setup` compares the free space of the
    folder that receives the data (the cache entry or `--path`) with the rule's `peak` and with
    the configured minimum (`cx config set task --meta.min_free_gb=<GB>`, off by default). A
    quiet run stops before downloading anything, with the sizes and the ways out (free space,
    `--path`, `--skip_size_check`); an interactive run warns and asks. Tools without a size file
    behave as before.
  - **Learning:** every install or build records its size (`_impact.disk_gb`, with method, OS and
    CPU; `peak_gb` when the tool's `install()` reports it). `cx tool setup <tool> --sizes` lists
    the records and suggests the rules to paste.
  - Rules for llvm, nvcc, vulkan-sdk, ollama, google.android-ndk, rustup, go, openjdk and the
    `jdk-*` tools, pytorch, mpi and executorch-android. Documentation: `docs/cmeta-aops/tool-sizes.md`.
  - **Real peaks:** `task/download-file` measures every download it unpacks — the archive, the
    files the unpacking added and their sum, taken before the archive is removed — returns them as
    `download_sizes` and records them in `.cmeta-download-sizes.json` of the folder it fills. In a
    tool's cache entry `task/setup` takes the largest of that peak, what `install()` reports and
    the entry's size as `_impact.peak_gb` (and the archives' total as `download_gb`), so the rules
    `--sizes` suggests carry the peak of every tool that downloads a release, not only what it keeps.
- **Static and dynamic library variants keep their own cache entries** (`tool/lib-xopenme`,
  `lib-polybench`, `lib-milepost`): a request's `with.static` and `with.debug_info` always carry a
  value, so a dynamic build no longer matches the static entry as well (a program's
  `'{{params.compile.static|$None}}'` left the key out of the query, and quiet mode could reuse the
  static entry). Existing entries keep matching.
- **Static builds with clang get a static OpenMP runtime** (`tool/lib-openmp`): `libomp.a` in the
  library's cache entry, the archive shipped with Homebrew's libomp on macOS, else built from the
  pinned OpenMP 21.1.8 source release (SHA-256 checked) with cMeta's cmake and ninja on Linux; before,
  `-static -fopenmp` failed on `-lomp`. `test-nmm-c-cpu`, `test-nmm-cpp-cpu`, `polybench-cpu-gemm`
  and `polybench-gemm-cpu-cuda` pass `compile.static` to it.
- **`test-nmm-nvcc-cuda`:** a static build uses the static xopenme and, on Linux, lib-openssl's
  static libraries, like the C programs (static for CUDA is `-cudart=static` with static third-party
  libraries: a fully static host binary cannot load the CUDA driver).
- **`test-nmm-c-cpu`:** links the math library on Linux; before, the dynamic build linked only with
  `--compile.fastest`.
- **`--compile_timeout` is a deadline for the whole compile phase** (`task/compile-and-run-program`,
  `task/cmd`, `category/task/api/deadlines.py`): every command that runs before it ends gets at most
  the time left, the builds that tools run inside the phase included (a LibTorch or llama.cpp built
  from source by a dependency); a command stopped by it fails with "stopped after N s: the compile
  deadline of M s (--compile_timeout) passed", one that would start after it is not started. Before,
  only the program's own compile command was limited. The deadline ends with the compile phase, so
  `--timeout` alone governs the run phase; without the option nothing is limited.
- **LibTorch source build:** `cmake --install` installs into `<entry>/build/install`, apart from the
  build tree (`program/build-torch-cpp`); before, the prefix was the build tree itself and CMake
  deleted `protoc` while installing it onto itself (its RPATH check), so the install never finished
  on Linux. `tool/torch-cpp` hands the installed library to the detection. The test programs of
  `build-torch-cpp` and `test-nmm-torch-cpp` take the C++ standard LibTorch's CMake config asks for
  (17 up to 2.8, 20 from 2.9, whose headers use `requires`); `--cxx_standard` overrides it.
  - **Two defaults, one per way:** a source build checks out `default_checkout` of `tool/torch-cpp`
    (`v2.14.1`, the tag built and tested) when no `--version` is given; before, the clone step took
    whatever PyTorch clone the machine had, or PyTorch's default branch. The prebuilt archives keep
    `default_version` (2.7.1). README of `tool/torch-cpp`.
- **A program's Python venv stays its own** (`category/task/api/v2.py`, `task/setup`, `tool/python`):
  - **A request without a venv of its own** (no `with.venv_path`, `with.venv_here`, `tool_path`,
    `with.here` or `--path`) no longer reuses the venv that a program or a tool made inside its own
    cache entry (`venv_path` under `task--program--<name>/`). Before, such a venv matched too, and in
    quiet mode its higher version often won, so it received the packages of unrelated tasks. The
    rest is as before: detected Pythons (the venv cMeta runs from, an activated venv), venvs made in
    their own cache entry (plain requests, `--version`) and venvs at places the user chose (`--path`,
    `--use.venv.path`, `venv_here`) are shared by version. README with the rules.
  - **A request with its own venv path** looks for a python only in that venv: an existing venv
    there is reused, else it is made. Before, a venv found on `PATH` (an activated one, or the one
    cMeta runs from) could be recorded as that request's venv, and in quiet mode an existing venv
    at that path without a cache entry was wiped and made again.
  - **Task engine:** a task can drop cache entries that match the cache query but are not meant
    for the request (`filter_cache_artifacts`); `task/setup` passes it on to the tool
    (`filter_tool_cache_artifacts`). Tasks and tools without it behave as before.
  - **`task/venv`:** an error message used an undefined name; `qpath_to_python` held the activate
    script.
- **Static Linux links of OpenSSL** (`tool/lib-zlib`, `tool/lib-zstd`, `tool/lib-jitterentropy`,
  new; `category/tool/api/common_static_lib.py`; `tool/lib-openssl`):
  - **New tools:** zlib, Zstandard and the Jitter RNG as static libraries built from their pinned
    source releases (SHA-256 checked) with the C compiler of cMeta, into the cache: no root, no
    system package. Linux and macOS.
  - **`tool/lib-openssl`:** a static link on Linux links only the libraries that the
    distribution's `libssl.a`/`libcrypto.a` need (`nm -u`), each from the system's static archive,
    else from its tool; `--with.static_deps=cmeta` always uses the tools. Before, `-lz -lzstd` were
    always added and the link failed where those archives were missing. Dynamic links and
    macOS/Windows are unchanged.
  - **`test-nmm-c-cpu`, `test-nmm-cpp-cpu`:** pass `with.static` to `lib-openssl` for static builds
    on Linux.
- **Go and Rust programs on Android** (`tool/go-android`, `tool/rustc-android`, new):
  - **`cx program run test-nmm-go-cpu android-cpu`** builds with the host's Go for the device's ABI
    (`GOOS=android`, `GOARCH`, `CGO_ENABLED=0`, `-buildmode=pie`; no NDK needed) and runs it over adb.
  - **`cx program run test-nmm-rust-cpu android-cpu`** builds with the host's rustc for the device's
    Rust target, whose standard library rustup adds the first time, linked by the Android NDK's clang
    for the device's API level.
  - Host builds keep `tool/go` and `tool/rustc`: the new tools support only `android-cpu`.
  - **`task/setup-compile`:** the compile command also gets the compiler tool's `features.env` (the
    program's own env wins); no other tool sets one.
- **`test-nmm-rust-cpu`:** writes `tmp-cmeta-program-stats.json` like the C and Go versions; before,
  the file its description declares was missing.
- **`test-nmm-swift-cpu`:** no longer declares `android-cpu`, which no Swift compiler tool supports,
  so a run for it stops at once.
- **`tool/openjdk`:** on musl Linux (Alpine) the default JDK is Temurin's `alpine-linux` build;
  before, the glibc build was downloaded and did not run there.
- **LibTorch for C++ programs** (`tool/torch-cpp`, `program/build-torch-cpp`, `program/test-nmm-torch-cpp`;
  `tool/torch-cpp-prebuilt`, new; `category/tool/api/common_libtorch.py`, new):
  - **Prebuilt LibTorch:** `--with.build=prebuilt` (`--setup_torch_cpp.build=prebuilt` for
    `test-nmm-torch-cpp`) uses PyTorch's official archive instead of a source build: 2.7.1 for Linux
    x86_64 and Windows x64 (cpu, cu118, cu126, cu128), Windows ARM64 (cpu) and macOS arm64 (cpu, with
    MPS), SHA-256 pinned. For CUDA the newest build with code for every GPU that the driver supports is
    chosen; `--with.variant` picks one. `tool/torch-cpp-prebuilt` caches the archive; the setup of
    `tool/torch-cpp` with it is not cached, so its source-build entries keep their cache identity.
  - **Source builds enable only the target's backends by default:** CUDA, cuDNN, ROCm, MPS and XPU are
    off unless the target asks for them; before, PyTorch's CMake enabled what it found (a CPU build on
    a machine with CUDA tried to build CUDA). `--with.strict_compute=False` restores that. Existing
    cache entries keep matching. On Linux, programs linked with LibTorch find LLVM's libomp.
  - **`tool/torch-cpp`:** detects the LibTorch a build installed (its library, its version from the
    headers).
  - **`test-nmm-torch-cpp`:** compiles (`customize_compile` failed) and runs its program (the run step
    had no command); the compile and run steps get the same `--setup_torch_cpp.*` options; `Torch_DIR`
    is set; CUDA builds of LibTorch get `nvcc` and `USE_SYSTEM_NVTX`; on Windows the MSVC-built archive
    is compiled with `clang-cl` when cMeta chose `clang++`. README with the options.
- **An OpenSSH server run as the user** (`tool/openssh-server`, `task/run-openssh`, new):
  - **`cx task run run-openssh --keys=<public key file>`** starts sshd on a port of its own (2222)
    with key-only logins, as the user: no service, no administrator. `status` shows it, and `stop`
    ends it together with its logins.
  - **Address:** the machine's Tailscale address (`tailscale ip -4`) by default, else 127.0.0.1;
    `--listen` picks another.
  - **Keys:** `--keys` takes public key files, `authorized_keys` files or keys; without it, the
    user's `~/.ssh/authorized_keys`.
  - **The server:** Windows gets the portable Win32-OpenSSH release (x64, ARM64, SHA-256 pinned) in
    the cache, and logins get cmd.exe; Linux and macOS use the system sshd. Its host key,
    configuration and log stay in a cache entry, one per `--name` and port.
- **JDKs of five vendors** (`tool/jdk-temurin`, `jdk-microsoft`, `jdk-corretto`, `jdk-zulu`,
  `jdk-oracle`, new; `category/tool/api/common_jdk.py`):
  - **Install:** the latest release of `--with.feature` (the major version, default 25) for this OS
    and CPU (x64, aarch64), from the vendor's API or download site, checked against the vendor's
    SHA-256. Temurin also has a musl (Alpine) build. `--version` pins a release (Temurin, Microsoft,
    Zulu). Oracle's license applies to the Oracle JDK.
  - **Separate tools, so nothing changes for `tool/openjdk`:** its detection of an installed JDK,
    its Temurin download and its cache entries stay as they were. The vendor tools store their
    result as `openjdk` too.
  - **`tool/javac`, `tool/java`:** `--with.vendor=<vendor>` (and `--with.feature`) uses that vendor's
    JDK; without it, `tool/openjdk` as before.
  - **`test-nmm-java-cpu --jdk=<vendor>`** (and `--jdk_feature`) compiles and runs with it.
  - **`task/compiler`:** `tool_with` passes `with` to the setup of the compiler tool (the javac of a
    vendor); without it nothing changes.
- **`tool/java`:** the version is read from `openjdk version "…"` and `java version "…"` (Oracle
  JDK); before, the word "version" was taken as the version, and Oracle's output was not read.
- **`task/setup-compile`:** the program's target name is also used with an explicit target extension
  (Java's `Program.class`); before, `program.class` was expected, which only file systems that ignore
  case found.
- **`tool/rustup`:** runs `rustup-init` by its full path; it failed where cmd.exe does not search the
  current directory (`NoDefaultCurrentDirectoryInExePath`).
- **`polybench-gemm-cpu-cuda`:** sets up `lib-cuda` for CUDA targets, so a CUDA runtime from the
  cMeta cache (CUDA 12 for an older GPU) is on the run-time library path.
- **`tool/mpi`:** `--with.build=source|pip`. The source build compiles Open MPI from its release
  tarball (SHA-256 pinned) into the tool's environment, with mpi4py built against it, so that macOS
  and Linux nodes can run one job; it is the default on macOS (it needs the Xcode Command Line
  Tools). The build is part of the cache identity, so the first setup after this change installs the
  wheel again into a new entry.
- **Timeouts for program runs:** `cx program run <program> --timeout=<seconds>` limits each run
  command, `--compile_timeout=<seconds>` each compile command (the template passes them to its
  `cmd` steps). The default stays without a limit.
- **`task/cmd`:**
  - **Timeouts:** a command that runs past `--timeout` is stopped with all its subprocesses (a
    process group on Linux and macOS, a Job Object on Windows), and the task fails with "timed
    out". Before, the stopped command's return code (-1) counted as a success. With
    `fail_if_nonzero_return_code=False` the result has `timed_out: True`.
  - **Any return code but 0 fails:** a negative code (a command ended by a signal on Linux and
    macOS) passed as a success before.
  - The working directory is restored when the command fails, too.
- **LiteRT for Android from its official releases** (`tool/lib-litert-android`, new):
  - **Contents:** the AAR from Google Maven (`libLiteRt.so` with its C API and the GPU
    accelerator, per ABI; Maven's SHA-256), the C/C++ SDK headers (with the `build_config.h` that
    CMake would generate), the NPU dispatch libraries (Google Tensor; Qualcomm HTP v69-v81) and
    the release's MobileNet v2 test model. GitHub's SHA-256 digests come from the release API,
    pinned for the default release (2.2.0).
  - **As a `lib-*` tool:** an NDK build links `-lLiteRt` with its headers, and setup-run pushes
    the arm64-v8a runtime, GPU accelerator and Google Tensor NPU libraries to the device.
- **ExecuTorch for Android from source** (`program/build-executorch-android`, new): builds
  `executor_runner` with the XNNPACK (CPU) and Vulkan (GPU) backends, which the prebuilt runtime
  lacks. It cross-compiles with the NDK and uses the LunarG `glslc` for the shaders (NDK r29's
  lacks `GL_KHR_cooperative_matrix`). A CPU torch, in a venv next to the build folder, does the
  code generation.
  - **Options:** `--checkout=<tag|branch|commit>` (default v1.5.1, cloned with its submodules),
    `--vulkan=OFF`, `--android_abi`, `--android_api` and `--cmake_flags`.
  - **The binary** is stripped (15 MB).
  - **Build environment:** ninja goes on PATH, because XNNPACK's nested CMake builds look for it
    there.
- **`tool/pip-mlx`:** refuses CUDA for GPUs older than Volta (7.0) before the install, because
  MLX's CUDA kernels need `__grid_constant__`.
- **Apple MLX for every target** (`tool/pip-mlx`, new): `cx tool setup pip mlx` picks the
  backend from the targets.
  - **Backends:** Metal on Apple silicon, `mlx[cuda13]` or `mlx[cuda12]` on Linux with NVIDIA
    GPUs (from the driver and the oldest GPU), and `mlx[cpu]` on Linux and Windows.
  - **Windows:** MLX 0.32 declares its `cpu` extra for Linux only, although `mlx-cpu` has Windows
    wheels. The setup names `mlx-cpu` there; before, `import mlx.core` failed with "DLL load
    failed".
- **The Android NDK without Java** (`tool/google.android-ndk`):
  - **Install:** the setup downloads the NDK zip for this host OS from Google's repository, checks
    it against the SHA-1 of Google's repository index, and unpacks it with its file modes and
    symlinks. It needs no Java, no sdkmanager and no administrator rights. Before, it always went
    through the SDK command-line tools, so a machine without Java (a container, a fresh Linux)
    could not get an NDK.
  - **Fallback:** sdkmanager is still used on Linux ARM, for which Google publishes no zip.
  - **Detection:** it now also looks in Android Studio's SDK folders, and detecting an installed
    NDK no longer sets up the command-line tools first.
- **Tools for distributed runs:**
  - **`tool/ray`:** Ray `ray[default]` 2.59.0 in its own Python environment. Every node of a Ray
    cluster needs the same Python down to the patch release (3.12.3 and 3.12.14 refuse each
    other), so the tool pins Python 3.12.14 and uv installs that same build everywhere.
  - **`tool/mpi`:** `mpiexec` and the MPI library. The setup uses a system MPI when it has one
    (Open MPI, MPICH, Intel MPI, MS-MPI). Otherwise it installs one from PyPI, without root,
    with mpi4py in the same environment: Open MPI 5.0.11 (Linux, macOS), MPICH 5.0.2 (Linux,
    macOS) or the Intel MPI runtime 2021.18.1 (Linux, Windows; the default on Windows).
    `--with.mpi=openmpi|mpich|intel` picks one, and the choice is part of the cache identity.
    The launcher's folder goes on PATH (`mpicc` is next to it), and `features.python` is the
    environment's Python.
  - **`common_pyvenv`:** the spec key `bin` names the folder that holds the command, for packages
    whose programs are data files rather than console scripts (`impi-rt` on Windows:
    `Library/bin`).
- **ExecuTorch on Android, with no app and no source build** (`tool/executorch-android` and
  `tool/android-d8`, new):
  - **`executorch-android`:** the official runtime, PyTorch's AAR on Maven Central. The tool
    reads the dependencies from the POMs (fbjni, nativeloader, kotlin-stdlib), checks every file
    against Maven Central's SHA-256 (SHA-1 for old artifacts) and unpacks the native libraries per
    ABI and the Java classes.
    - Its library registers XNNPACK (CPU) only and exports only JNI. Programs use its Java API,
      from the adb shell through `app_process`.
  - **`android-d8`:** Android's dexer. It uses the `d8.jar` of an installed SDK, else downloads
    the pinned r8 jar from Google's Maven and checks its SHA-256.
  - **`setup-run`:** `run_on_host: True` runs a program with an Android target on the host, so it
    can drive the device itself: export models with the host's Python, then push and run them
    with adb.
- **Fixes:**
  - `clone-git-to-cache` now passes `branch`, `new_branch` and `update_submodules` to `clone-git`.
    They were part of its cache identity but never reached git.
  - `tool/pytorch` names `build-pytorch` by its current UID. Its build path had failed since that
    UID changed.
- **flatc, the FlatBuffers compiler** (`tool/flatc`, new). The setup uses an installed flatc when
  it finds one. Otherwise it downloads the pinned GitHub release for Windows, macOS (arm64 and
  x86_64) or Linux x86_64, whose static binary runs on every distribution, Alpine included. It
  checks the download against the SHA-256 that GitHub lists for it. Linux on other CPUs gets the
  distribution's package. ExecuTorch's exporter needs flatc on Windows: point `FLATC_EXECUTABLE`
  at it.
  - `common_release` specs can pin digests per version and asset (`checksum: {'sha256': ...}`),
    for releases that publish no checksum file.
- **setup:** the "this installation requires SUDO" warning now appears only when the sudo command
  runs. Before, it also appeared before a release download that needs no root (rclone, zstd,
  flatc).
- **JAX for every target** (`tool/pip-jax`, new; see its [README.tech.md](tool/pip-jax/README.tech.md)):
  `cx tool setup pip jax` picks JAX's plugin from the targets.
  - **Plugins:** `jax[cuda13]` or `jax[cuda12]` (from the driver and the oldest GPU),
    `jax[rocm7-local]`, `jax[oneapi]` for Intel GPUs, and `jax-metal` with JAX 0.5.0 (the newest
    JAX that Apple's last plugin runs).
  - **Refused before any download:** platforms without a plugin (Windows: CUDA runs in WSL2) and
    the integrated Intel GPUs that the oneAPI plugin cannot compute on (`--with.any_intel_gpu`
    tries anyway).
- **The Intel NPU user-space driver for Linux, without root** (`tool/intel-npu-runtime`, new; see its
  [README.tech.md](tool/intel-npu-runtime/README.tech.md)):
  - **The driver:** the kernel's `intel_vpu` driver does not bring the NPU's Level Zero driver or
    the compiler in driver that OpenVINO's NPU plugin needs.
  - **Detection:** the setup uses the system's driver (`intel-level-zero-npu`) when it has one.
  - **Install:** otherwise it unpacks Intel's release packages for the Ubuntu release (24.04 or
    26.04) into the cache, with the Level Zero loader and, when missing, oneTBB. Every archive is
    checked against its sha256.
  - **What it refuses or skips:** a glibc older than 2.38 fails before any download. The
    firmware package, which needs root, is left out.
  - **The npu-intel target:** on Linux x86_64 it sets the driver up once it finds the NPU
    (`--use.target--npu-intel.skip_runtime` skips it). When the NPU is on the PCI bus but has no
    accel device, the error says the kernel lacks its `intel_vpu` driver or its firmware.
  - **Shared helpers:** the `.deb` helpers of `tool/intel-gpu-runtime` moved to
    `category/tool/api/common_deb.py`, which both tools use.
- **The opencl, android-gpu and android-npu targets** (see [tool/opencl/README.tech.md](tool/opencl/README.tech.md)
  and [task/target/README.tech.md](task/target/README.tech.md)):
  - **opencl** (`tool/opencl`, new):
    - The OpenCL platforms and devices come from the ICD loader itself (ctypes, no SDK, no
      clinfo), on Windows, Linux and macOS.
    - On Linux, the ICD loader is installed (with sudo) only when a GPU can use it, and an Intel
      GPU gets `tool/intel-gpu-runtime` first.
    - CPU-only OpenCL fails unless `--use.target--opencl.allow_cpu`.
    - gcc, g++, clang, clang++ and MSVC now declare `supports_compute: opencl`.
  - **android-gpu** and **android-npu** cover the Android device that android-cpu selects:
    - android-gpu records the GPU: its Vulkan devices, GLES driver and OpenCL library;
    - android-npu records the NPU: the NNAPI accelerators and the vendor stack (Samsung ENN,
      MediaTek APU, Google TPU, Qualcomm);
    - programs built for them with the NDK are pushed and run over adb, like Android CPU
      programs: `setup-run` and `compile-and-run-program` treat every Android target alike, and
      the NDK clang tools declare both targets.
- **Vulkan needs a GPU** (`target--vulkan`, `tool/vulkan`, see its
  [README.tech.md](tool/vulkan/README.tech.md)):
  - **Target:** a vulkan run on a machine where Vulkan sees only CPU devices (Mesa's llvmpipe) now
    fails, instead of warning and computing on the CPU. `--use.target--vulkan.allow_cpu` accepts
    them. A cached target is checked again.
  - **Tool:** `tool/vulkan` no longer installs Mesa (with sudo) on a Linux machine with no device
    node to reach a GPU: no DRM render node, no WSL2 `/dev/dxg`, no NVIDIA or AMD node. PCI
    display devices without a node are named in the message. `--with.allow_cpu` installs it anyway.
- **CUDA toolkits of any version, without root, with the host compiler they support** (`tool/nvcc`,
  see its [README.tech.md](tool/nvcc/README.tech.md)). nvcc skips the toolkits whose programs could
  not run here: those whose oldest architecture is newer than the GPU (CUDA 13 dropped Maxwell to
  Volta), and those for a newer major CUDA version than the driver's. When none suits, or
  `--version` asks for another, it installs one from NVIDIA's redistributable archives: the newest
  release that suits the GPU and the driver, with each archive checked against NVIDIA's sha256 and
  unpacked into the cMeta cache. `--version` is nvcc's (`12.9`, `12.9.86`, a range); a CUDA release
  label gets a hint.
  - **Libraries on demand:** `--with.cuda_libs` and `lib-cuda`'s `lib_names` add cuBLAS, cuFFT and
    the others to a toolkit made from the archives, once. Without `-q`, it asks first.
  - **The host compiler** is set up once the toolkit is known: the newest GCC, clang or MSVC that
    the toolkit's `host_config.h` accepts (Visual Studio 2022 for CUDA 12.x, when Visual Studio
    2026 is also installed). It is passed to nvcc as `-ccbin`, through the new `host_compiler` flag
    of `setup-compile`.
    - `--use.<tool>.version` still decides.
    - An unsupported compiler set up earlier in the run stops the run, with the option to use.
    - `--with.any_host_compiler` adds `-allow-unsupported-compiler`.
  - **`--with.arch_flags`:** a GPU newer than the toolkit gets PTX, which the driver compiles (it
    got machine code the GPU could not run). A GPU older than the toolkit gets an error, instead of
    code for another GPU.
  - One nvcc cache entry per GPU architecture.
  - **`microsoft.visual-studio`:** a version (cl.exe's, such as `<19.50`) picks the Build Tools
    release to install. A version that no release has installs nothing; before, it installed the
    newest.
- **Agent tasks renamed: `run-claude2` -> `run-claude`, `run-codex2` -> `run-codex`,
  `run-opencode2` -> `run-opencode`**, and the first `run-claude` prototype is removed. The
  tasks keep their UIDs, so references by `alias,UID` (`run-claude2,38be73ffceaa4f67`) keep
  working; commands that name `run-claude2` alone need the new name. Also renamed:
  - the default output files (`run-claude-output.txt`, `run-codex-output.txt`,
    `run-opencode-output.txt`);
  - the `task` field of their statistics;
  - their key in a pipeline's context: a task that reads `local['run-claude2']` reads
    `local['run-claude']` now.

  After pulling, run `cx --reindex`, because task folders moved.
- **xpu on Linux sets up the Intel GPU compute runtime, without root** (`tool/intel-gpu-runtime`, see its
  [README.tech.md](tool/intel-gpu-runtime/README.tech.md)). An Intel GPU computes through a user-space
  runtime the kernel driver does not bring: the OpenCL ICD, the Level Zero driver, the graphics compiler,
  gmmlib and the Level Zero loader. The tool uses the system's when it has one; otherwise it downloads
  Intel's release packages, checks their sha256 and unpacks them into the cMeta cache. The release line
  follows the GPU's PCI id: 26.35 for Gen12 and later (also WSL2), legacy1 24.35 for Gen8-Gen11. The
  result exports `LD_LIBRARY_PATH` and `OCL_ICD_FILENAMES`, so the system's ICD loader adds the Intel GPU
  next to the others. It warns when the user cannot open `/dev/dri/renderD*` (the render group).
  - `target --compute=xpu` sets it up on Linux x86_64 once the Intel GPU is found, so every program run
    on xpu gets the runtime. In WSL2, where lspci sees a virtual adapter, the target asks Windows for
    its GPUs.
  - `test-onnxruntime` lists OpenVINO's devices in a separate process: on Linux the `openvino` package
    and `onnxruntime-openvino` each bring a `libopenvino.so.2541`, and loading both in one process broke
    the OpenVINO EP.
  - Tested on Ubuntu with a Gen12 Iris Xe (the 26.35 line) and a Gen9 HD Graphics 630 (legacy1):
    `test-openvino` and `test-onnxruntime` run on xpu.
- **LLM stacks on CPU, CUDA, Vulkan and Metal: the newest llama.cpp, vLLM 0.30.0, Ollama 0.35.0 and
  PyTorch 2.14.1**, installed or built from source with the same commands on Windows, Linux/WSL2 and
  macOS. The guide is the new [`docs/cmeta-aops/llm-stacks.md`](docs/cmeta-aops/llm-stacks.md).
  - **llama.cpp** (`tool/llama-cpp`, default build 11324): the asset comes from the release's own list
    (`releases/expanded_assets/b<N>`; the builds are prereleases and `/releases/latest` has no
    binaries), for the OS, the CPU and the backend (cpu, cuda, vulkan, rocm, sycl for xpu, openvino,
    metal). CUDA builds are matched to the driver (minor-version compatibility), the `cudart` bundle
    is installed next to them, and the Linux CUDA builds explain that they need glibc 2.38+. The
    version is read from both the new (`version: 0.5.0-dev (build N, ...)`) and the old output.
  - **llama.cpp programs**: `llama-completion` runs the generation (`llama-cli` is now the chat UI).
    The timings in `llama.log` become `perf.json` (result `perf`): prompt and generation tokens per
    second, load and total time, the device used and the layers offloaded to it (the runs pass `-v`,
    as newer builds log them only then), the build and commit, and the CUDA architectures.
    `--compute=cpu` keeps the model on the CPU (`-ngl 0 --device none`).
  - **build-llama-cpp**: Vulkan builds (`GGML_VULKAN`, the loader library from `tool/vulkan-sdk`);
    OpenSSL is optional (the system library, else `LLAMA_OPENSSL=OFF`, or `--compile.boringssl`);
    Ninja, CMake and the compilers reach nested CMake projects (`vulkan-shaders-gen`). The default
    checkout is `b11324`, the build the release tool installs (it was master as of the first clone);
    `--model` and `--prompt` work as in `program/llama-cpp`; on macOS, builds without `metal` leave
    Metal out, so a CPU build opens no GPU.
  - **Vulkan**: `tool/vulkan` lists the devices through the loader itself (ctypes, no SDK and no
    `vulkaninfo`; MoltenVK through portability enumeration). `tool/vulkan-sdk` detects an SDK in
    `$VULKAN_SDK`, the LunarG folders, the distribution or Homebrew. Otherwise it installs the pinned
    LunarG SDK 1.4.363.0 without administrator rights (Linux x86_64: the tarball; Windows: the
    installer in copy-only mode), or uses Homebrew or the distribution packages. `target--vulkan`
    is new, and gcc, g++, clang, clang++ and MSVC now declare `supports_compute: vulkan`.
  - **vLLM**: `tool/pip-vllm` picks the wheel index for the target and driver: PyPI's CUDA 13.0 build
    for driver R580+, the cu129 build for older drivers, and the CPU, ROCm and XPU indexes. It checks
    for Python 3.10–3.14 (3.12 on macOS), and on native Windows it tells you to use WSL2.
    `program/test-vllm` is rewritten (stats JSON, the venv's bin on PATH for FlashInfer's JIT,
    `libnuma` for the CPU through the new `tool/lib-numa`). The new `program/build-vllm` builds from
    source with `VLLM_TARGET_DEVICE`, `CUDA_HOME`, `TORCH_CUDA_ARCH_LIST` from the detected GPU and
    `MAX_JOBS` sized to the RAM.
  - **PyTorch** (`build-pytorch`, default `v2.14.1`): the scikit-build-core build
    (`pip install --no-build-isolation -v .` after `requirements-build.txt`), `TORCH_CUDA_ARCH_LIST`
    from the detected GPUs (without one, CUDA 13 rejects PyTorch's default list), `BUILD_TEST=0`,
    `PYTORCH_BUILD_VERSION` from the tag, `DISTUTILS_USE_SDK=1` on Windows, and
    `CMAKE_POLICY_VERSION_MINIMUM=3.5` (CMake 4 refuses the helper projects NNPACK downloads).
  - **Ollama**: `tool/ollama` installs the pinned portable release into the cMeta cache, with no
    installer, no service and no administrator rights. The Linux `.tar.zst` is unpacked by a Python
    3.14 (uv downloads one) before any `sudo` package is tried. `tool/zstd` is new, and
    `program/test-ollama` runs a private server on its own port and records Ollama's timings and VRAM
    use, and stops the model runners with it (on Windows they outlived the server, holding RAM and VRAM).
  - **Source builds size `MAX_JOBS` to the RAM** (`category/program/api/common_build.py`: 4 GiB per
    CUDA job, 2 GiB per C++ job), because PyTorch's and vLLM's builds start one job per CPU.
- **Targets: selecting, combining and comparing them on one machine**
  ([`task/target/README.tech.md`](task/target/README.tech.md)):
  - `--target` is `--compute` by another name; before, it was ignored and the program ran on the CPU.
    `cx program targets` lists the targets.
  - **Fix: a change of targets in the same build folder builds again.** The targets were read before
    the target task resolved them, so a `--compute=metal` run after a `--compute=cpu` build reused the
    CPU build and its run flags, and ran on the CPU. `cpu,cuda` -> `cuda` now counts as a change too.
  - `--target_tmp=auto`, or `cx config set task --meta.compile_and_run_program.target_tmp=auto`, gives
    every set of targets its own build folder (`tmp-cuda`, `tmp-cpu-cuda`); builds for different
    targets stay side by side.
  - `test-vllm`, `build-vllm` and `build-pytorch` set up Python in a venv of their own, one per set of
    targets (`venv-<targets>`), so the CPU and the CUDA builds of torch never replace each other.
  - Splitting a model across devices:
    - llama.cpp: `--ngl`, `--devices`, `--split_mode`, `--tensor_split`, `--main_gpu` and
      `--threads`. They are set at run time (a reused build brought back the flags of the run that
      compiled it), and `perf.json` records them with the targets.
    - Ollama: `--ngl` (its `num_gpu`).
    - vLLM: `--cpu_offload_gb`, `--tp`, `--dtype`, and `--enforce_eager=0` for CUDA graphs.
  - A llama.cpp release build refuses two GPU targets, since it has one backend. `nvcc` declares
    `supports_compute: vulkan`, so `build-llama-cpp --compute=cuda,vulkan` builds both backends.
  - `README.tech.md` files with every cMeta option: targets (`task/target`), llama.cpp
    (`tool/llama-cpp`), vLLM (`tool/pip-vllm`), Ollama (`tool/ollama`), PyTorch
    (`program/build-pytorch`) and Vulkan (`tool/vulkan`). The programs point to them.
- **The Intel NPU and OpenVINO as targets** (`task/target--npu-intel`, `task/target--openvino`,
  `program/test-openvino`; every option in
  [`program/test-openvino/README.tech.md`](program/test-openvino/README.tech.md)):
  - `npu-intel` finds the NPU without any SDK, by its PCI ID: the PnP `ComputeAccelerator` devices on
    Windows (with the driver version), the `intel_vpu` accel devices on Linux. It records the platform
    (Meteor Lake to Nova Lake) and the NPU generation. `openvino` is the stack target.
  - `test-openvino` runs a matmul and a ReLU on each device the targets name (`npu-intel` -> NPU,
    `xpu` -> GPU, `cpu` -> CPU; `openvino` alone: every device OpenVINO finds). Each device is named
    in `compile_model`, never AUTO, and checked against `EXECUTION_DEVICES`, so a failing device
    cannot pass on the CPU. It records the device's properties, the compile time, the latency and
    the error against NumPy; `--size` and `--batch` choose a bandwidth- or a compute-bound matmul.
  - `program/llama-cpp` accepts `xpu` (the SYCL release), `npu-intel` and `openvino` (the OpenVINO
    release; `npu-intel` sets `GGML_OPENVINO_DEVICE=NPU`). A release has one accelerator backend, now
    counted by backend, so `npu-intel,openvino` is one. Device names with parentheses
    (`Intel(R) Graphics`) are recorded whole.
  - Tested on a Panther Lake laptop: `test-openvino` on the NPU, the Intel iGPU, the NVIDIA GPU
    (OpenVINO's `GPU.1`) and the CPU; llama.cpp on the iGPU with the SYCL release and with the
    Vulkan release (`--devices=Vulkan0`). llama.cpp on the NPU is not tested yet.
- **ONNX Runtime per target** (`tool/pip-onnxruntime`, `program/test-onnxruntime`; see
  [`program/test-onnxruntime/README.tech.md`](program/test-onnxruntime/README.tech.md)):
  - `setup pip onnxruntime` installs the build that fits the targets: `onnxruntime-gpu[cuda,cudnn]`
    for CUDA (CUDA and cuDNN from pip), `onnxruntime-openvino` for the Intel NPU and GPU (with the
    `openvino` release it was built against), `onnxruntime-migraphx` for AMD, else `onnxruntime`.
  - `test-onnxruntime` runs a small ONNX model on each target's execution provider alone, with
    the CPU fallback disabled, and records the provider, latency and error against NumPy
    (`--size`, `--batch`, `--seconds`).
  - `image-classification-onnx` uses one venv per set of targets and the OpenVINO device of the
    target (`npu-intel` -> NPU, `xpu` -> GPU), and warns when its provider is not the active one.
  - `xpu` runs on the Intel GPU only: OpenVINO's GPU plugin also drives NVIDIA GPUs through
    OpenCL, so `test-openvino` and `test-onnxruntime` pick the GPU whose name says Intel, and fail
    when there is none.
  - `install-sys-tool --check_binary=<binary>` skips the install when the binary is on the PATH:
    `target--xpu` no longer runs `sudo apt-get install pciutils` when `lspci` is there.
  - Tested on Windows (the CPU, CUDA, the Intel NPU and GPU) and Ubuntu (the CPU, CUDA; the NPU
    target reports no NPU on machines without one).
- **llama.cpp on Android devices** (`--compute=android-cpu`, over adb; see
  [`tool/llama-cpp/README.tech.md`](tool/llama-cpp/README.tech.md)):
  - `program/llama-cpp` runs llama.cpp's own Android release (`android-arm64`, every CPU variant,
    the best one picked on the device). It is downloaded here and never run here; its build is
    recorded next to it for the version check.
  - `build-llama-cpp` builds with the NDK's CMake toolchain file and the release's settings
    (arm64-v8a, android-28, shared libraries with all CPU variants, no OpenMP, no OpenSSL).
    `--max_jobs=N` limits the parallel compile jobs on any target.
  - `task/setup-run` keeps folders and large files on the device between runs: the binary with
    its libraries in `/data/local/tmp/cmeta-llama-cpp/<variant>/` and the model in
    `/data/local/tmp/cmeta-models/`. They are pushed once, and again only when they change.
  - **Fix:** a program without a binary of its own made `task/setup-run` run
    `rm -rf /data/local/tmp/` on the device, emptying its work folder. That command now runs only
    for a program's own binary.
  - Tested on a Pixel 10 Pro (Android 17): the release and the NDK r29 source build, with several
    thread counts.
- **The Android NDK lists its versions:** `cx tool setup google.android-ndk --status` shows what
  the SDK offers (`sdkmanager --list`), and `--upgrade` installs the newest one side by side. More
  generally, `--upgrade` now installs the newest version of every tool whose install command
  takes a version and whose versions are known, instead of running the pinned install again.
- **Test sessions: a sandbox and a kept log for every test** (`task/test-session`, see its
  [README](task/test-session/README.md)). `cx task run test-session --start --type=<type>` gives a
  sandbox to work in and a record that stays when the sandbox goes, as the folder
  `<YYYYMMDD>/<HHMM>.<type>/` (the session id) of two artifacts of the local repository:
  `tmp::cmeta-aops-test-sessions` (the new `category/tmp`, for disposable folders; `cx tmp prune`)
  and `log::cmeta-aops-test-sessions` (`session.md`, `session.json`, attachments). `--list` filters by
  date, type, status and host; `--migrate` moves the folders of the first version
  (`<CMETA_HOME>/tmp|log/cmeta-tests-*`) there. The
  log records the host, cMeta, the repositories' branch, commit and changed files, and the agent
  (`CMETA_GENERATOR`, the Claude Code session). Notes, results and attached files are added during the
  test. The costs are the wall time, the sandbox size, and the tokens the Claude Code session used
  meanwhile, read from its transcripts (with configured prices, the cost in USD too). Finishing
  removes a sandbox above 1 GiB; `--list` and `--prune` keep the overview. `AGENTS.md` §7.1 makes
  test sessions the rule for every real test.
- **`cx tool setup <tool> --status` and `--upgrade`** - for every tool, with no change to its `_desc.yaml`
  (`task/setup/upgrade.py`). The tool's install **channel** on this OS is derived from its install command
  or hook - winget, Homebrew, the distro package manager (`install_cmd_sudo`), an upstream install script,
  npm, pip, or a release download - and decides which version counts as "latest" and what the upgrade runs:
  - `--status` lists every copy found (the cMeta cache entries `setup` replays first, then the PATH), the
    newest version the channel offers (`winget show --versions`, `brew info`, `apt-cache policy` /
    `dnf info` / `apk policy` / `pacman -Si` / `zypper info`), the newest upstream version (the release
    GitHub marks as latest, read from the `/releases/latest` redirect - not the newest tag, which can be a
    pre-release), the command `--upgrade` would run, and a verdict. It installs nothing and writes nothing;
    Python callers get `result['status']`.
  - `--upgrade` upgrades a detected tool through its channel (`winget upgrade`, `brew upgrade`,
    `apt-get install --only-upgrade`, the install script again, `npm install X@latest`, pip's own update,
    the release download of the newest version into the same cache entry), detects it again and reports
    `before -> after`; a tool that is not installed gets the newest version. Several copies found: the
    usual selection prompt, `-q` takes the newest. The cache entry records the new version and a
    `last_upgrade` entry. `--update` is unchanged (it rebuilds the entry from what is installed).
  - Two optional `_desc.yaml` keys override the derivation: `upgrade_cmd` (per OS) and
    `cmd_get_latest_version` (+ `_regex`, `_uses`). `task/host` gained `upgrade_cmd(_sudo)` and
    `candidate_version_cmd/_regex` per package manager.
  - Also: a `check_params` stop (`--versions`, `--status`) now returns its data to the caller;
    `common_release` names checksum files per version (an in-place upgrade reused the old release's
    checksums) and drops a download whose SHA-256 did not match; `detect` returns every matching copy
    in `detected`.
  - apt refreshes its package lists when an install cannot find the package (a fresh container has
    none), and before an upgrade, since stale lists hold no newer version.
  - Tested: Windows (winget: uv 0.11.1 -> 0.12.21, opencode and git; release: jq 1.7.1 -> 1.8.2 in place),
    Debian and Ubuntu containers as root (apt: git, curl; release: jq), Ubuntu as a user (install script:
    claude; apt status without sudo), macOS arm64 (Homebrew: gh; install script: claude; release: helm).
    Offline unit tests in `tests/cmeta_aops_basic_tests/test_tool_upgrade.py`.
- **Visual Studio: every installation, Build Tools included.** `tool/microsoft.visual-studio` lists
  installations with `vswhere`; before, it searched only `C:` and `D:\Program Files`, and Build Tools
  live under `Program Files (x86)`. `--version` picks one by its `cl.exe` version. `--install` sets up
  the newest Build Tools with the C++ workload through winget (`--with.year=2022` for an older line).
- **Fix: a cached compute target described the machine that created it.** In a `CMETA_HOME` copied or
  shared between machines, WSL with an RTX PRO 1000 (sm_120) got the RTX A500 (sm_86) of another laptop,
  and the vLLM build compiled for 8.6. Now `target--cuda`, `target--rocm` and `target--vulkan` take the
  features of the tool set up in the same call. `target--metal` and `target--xpu` parse the probe that
  runs in each call, and `target--cpu` probes again when its host fingerprint changes. `target--xpu`
  also uses PowerShell CIM instead of `wmic`, which current Windows 11 builds no longer have.
- **Fix: source builds and `test-vllm` use their own Python venv.** On the P14s, `build-pytorch` reused
  the venv `build-vllm` had filled and replaced vLLM's torch 2.13.0 with the 2.14.1 it had built. The
  new torch then failed to import ("undefined symbol: cublasLtGroupedMatrixLayoutCreate"): it was built
  with the CUDA 13.3 toolkit (cuBLAS 13.6), but loaded the pip cuBLAS 13.1 of vLLM's torch. A build
  made before keeps its venv until `--recompile`. The venv of several targets is named with dashes
  (`venv-cpu-cuda`, from the new `{{global.target.cmeta_targets_tag}}`): on Windows, a comma in the
  path split the venv's activation command. Paths with spaces work too now (a Windows user name with a
  space puts one in the default `CMETA_HOME`): `tool/python` quotes the venv's activation script and
  its pip check, and `tool/python-pip` checks Python's plain path rather than the quoted one.
- **Fix: program parameters reach the run-time environment.** `task/setup-run` expands
  `local_vars.run_time_env` with its own parameters, so `{{params.X|default}}` there always gave the
  default: `--model`, `--n`, `--max_len` and `--cpu_kv_cache_gib` of `test-vllm` and `build-vllm`, the
  options of `test-ollama`, and `--repeat` of the milepost codelet. They now read `{{local.params.X}}`,
  where `compile-and-run-program` keeps the program's parameters, and a test checks every program for it.
- **Quiet installs never wait at a sudo password prompt.** With `-q` and a `sudo` that needs a password,
  every `sudo` in an install command runs as `sudo -n`. It fails at once, where an unattended run used
  to hang (15 minutes in one case), and cMeta prints the command to run by hand.
- **Engine fixes:** a failed optional sub-task no longer clobbers the caller's context. `detect()` hooks
  receive `tool_path`/`paths`, and a forced path is checked even when a tool has `find_paths()`.
  CUDA is detected with NVIDIA drivers 610+ (`nvidia-smi` prints `CUDA UMD version`).
- **Fix: `tool/ccache` downloads the right release asset.** The macOS branch left `uarch2` unassigned
  (an `UnboundLocalError` on every Mac) and asked for `ccache-<v>-macos.tar.gz`, which upstream never
  published - the asset is `ccache-<v>-darwin.tar.gz`, one universal binary. Linux asked for `.tar.gz`,
  while upstream publishes `.tar.xz`, since 4.13 as `ccache-<v>-linux-<arch>-{glibc,musl-static}.tar.xz`
  (musl on Alpine); Windows arm64 is `windows-aarch64.zip`. Verified: 4.13.6 installs from its release
  on Windows x86_64, macOS arm64 and Linux x86_64 (Debian container).
- **Fix: `cx tool setup <tool> --versions` lists releases only** for the tools whose regex also accepted
  pre-release or unrelated tags: `kubectl`, `pytorch` and `torch-cpp` (`\b` let `v1.38.0-alpha.0` yield an
  unreleased `1.38.0`), `go` (`rcN`), `codex` (`-alpha`), `openclaw` (`-beta`), `uv` (every tag), `openjdk`
  (`jdk-(.+)` matched the nightly `jdk25u-...-beta` tags), `python` (`3.14.0rc3`, `+freethreaded`),
  `obsidian`, `llvm`/`clang`/`clang-cpp` (`-rc1`, `-init`), and the generic regex of `ccache`, `cmake`,
  `node-js`, `rclone`, `rustc` and `lib-openssl-android`. `--version=<pre-release>` still installs one.
- **Fix: versioned installs that could never work are gone**: `tool/gh` asked Homebrew for `gh@2` /
  `gh2` and `tool/kubectl` for `kubectl@1.37.1` and a snap channel `1.37.1/stable` - no such formulae or
  channel exist. Without the entries task/setup reuses `install_cmd` (current), as `az` already does.

- **Docs: `--use.<storage key>.<param>=<value>`**, which changes any sub-task of a run from the command line,
  however deep it sits: a dependency's version, or a control switch such as `update` of one step.
  - a new section in `docs/cmeta-aops/task-engine.md`, "Changing a dependency anywhere in a pipeline": how it
    works, the storage keys of `setup`, `clone-git-to-cache`, `runner`, compilers and other tasks, and the control
    switches that travel with it;
  - a line in the README;
  - notes in the `add-task` and `add-tool` skills.
- **Tested on 2026-10-01 and 2026-10-02:** llama.cpp (release and source builds), vLLM, Ollama and
  PyTorch on Windows 11, WSL2, Ubuntu and macOS, on the CPU, CUDA, Vulkan and Metal targets each
  machine has, including several targets at once (`--compute=cpu,cuda --ngl=N`, and a
  `cuda,vulkan` build run with `--devices`).

## 0.40.1
- **`task/rclone-to-ssh`: a plain `bisync` now adds `--resilient --recover`** (turn off with `--no-recover`).
  Without these flags, an interrupted run (a dropped link, a killed shell) leaves its listings as `*.lst-err` or
  `*.lst-new`, and every later run aborts with "cannot find prior Path1 or Path2 listings ... Must run --resync
  to recover". One pair stayed broken this way for three days, and the batch never ran the pairs after it. With
  the flags, the next run resumes from the backup listings. The task notes also say how to recover by hand:
  remove a leftover `*.partial` file first, because a resync would copy it across, then run
  `resync ... -- --resync-mode newer`.
- **Fix: `tool/brew` finds Homebrew on macOS when it is not on PATH.** It now searches Homebrew's default
  prefixes (`/opt/homebrew/bin` on Apple silicon, `/usr/local/bin` on Intel). Before, a shell that had not
  run `brew shellenv` (an ssh command, cron, CI) did not see an installed Homebrew, so setting up any tool
  tried to install Homebrew again.
- **Tested 0.40.0 on macOS 27 (arm64):**
  - all 13 release tools install from their pinned release with SHA-256 verified (kwok publishes none), and
    the same functional checks pass as on Windows and Linux;
  - ansible (ping), ansible-lint, yamllint and aiperf work in their uv environments;
  - `scan-git-secrets` passes its history, files-only and baseline scans;
  - `slurm` and `aks-flex-node` explain that they need Linux, WSL or a login node.

## 0.40.0
- **Thirteen new tools installed from their pinned upstream release** (install ladder tier 1), on
  Windows, Linux and macOS, amd64 and arm64 wherever upstream publishes an asset:
  - Kubernetes: `tool/helm` (4.3.0), `tool/kind` (0.33.0), `tool/k3d` (5.9.0), `tool/kwokctl` (0.8.0,
    with the `kwok` binary next to it), `tool/kustomize` (5.8.1), `tool/flux` (2.9.5), and for AKS
    `tool/kubelogin` (0.2.20);
  - infrastructure as code: `tool/terraform` (1.16.4, BUSL-1.1) and `tool/opentofu` (1.12.6, MPL-2.0,
    the `tofu` binary);
  - repository hygiene and scripting: `tool/gitleaks` (8.30.1), `tool/jq` (1.8.2), `tool/yq` (4.53.6),
    `tool/golangci-lint` (2.14.0).

  They share a new helper, `category/tool/api/common_release.py`. Each tool's `api_v1.py` declares only
  where its assets live. The helper then:
  - picks the asset for the OS and CPU;
  - downloads it through `download-file`;
  - verifies its SHA-256 against the checksums upstream publishes (all but kwok, which publishes
    none), in any of three formats: a list, a per-asset file, or yq's multi-hash table;
  - unpacks the binary with Python's zipfile/tarfile, so no tar or unzip binary is needed.

  Pairs with no upstream asset (e.g. kind, k3d and OpenTofu on Windows arm64) print the install help
  instead. Every tool also lists its released versions (`cx tool setup <tool> --versions`). An
  installation already on the PATH is detected and used first.

  **Tests:** each tool installs from its release, checks the SHA-256 and reports the pinned version, on
  Windows and in a `python:3.12` Linux container. Offline checks also pass:
  - `helm create` + `helm template` renders 4 objects;
  - `kustomize build` produces a ConfigMap;
  - `terraform apply` and `tofu apply` output `hello = "world"` with no cloud account;
  - `jq` and `yq` extract values;
  - `gitleaks` finds a fake token and reports it as `REDACTED`.
- **Four new Python tools, each in its own environment:** `tool/ansible` (ansible-core 2.21.4),
  `tool/ansible-lint` (26.9.0), `tool/yamllint` (1.38.0) and `tool/aiperf` (0.13.0, the load
  generator for OpenAI-compatible LLM servers). A new helper, `category/tool/api/common_pyvenv.py`,
  sets up `tool/uv`, creates a virtual environment with a pinned Python (3.12; uv downloads it if
  missing) inside the tool's cache entry, and installs the pinned package. So the system Python and
  other tools' packages are never touched, and aiperf (Python 3.11-3.13) works on a machine whose
  Python is 3.14. Ansible and ansible-lint do not run on Windows (POSIX-only modules), so there they
  stop with a pointer to WSL or a Linux container; yamllint and aiperf work on Windows too.
- **New `tool/slurm` (detect-only):** the Slurm client commands (`sinfo`, `srun`, `sbatch`, `squeue`,
  `scontrol`) of a login node, or of the `slurm-client` package. Every Slurm command reads the cluster
  configuration first, even `sinfo --version`, so the version comes from the cluster when it is
  configured and otherwise from the package that installed the binary (dpkg or rpm). The result
  records `configured: false/true`. Tested in a Linux container with Debian's slurm-client and no
  cluster (version 24.11.5 from dpkg).
- **`tool/kubectl`:** the default version moves from 1.31.0 to **1.37.1**, the latest stable; kubectl
  supports one minor version of skew, so `--version=1.<minor>.<patch>` matches an older cluster.
- **New `task/run-openclaw`:** the OpenClaw sibling of `run-claude2`, `run-codex2` and `run-opencode2`,
  with the same flags (`--prompt`, `--prompt_file`, `--output_file`, `--stats`, `--interactive`/`--i`,
  everything after `--` for openclaw) plus `--agent`, `--session`, `--gateway` and `--dry_run`.
  - **Headless:** one agent turn with `openclaw agent --local --agent main --message <prompt>`. With no
    prompt, or with `--interactive`, it opens `openclaw tui --local` with the prompt as the first message.
  - **Windows:** the npm `.cmd` shim is bypassed and node runs `openclaw.mjs` directly, so cmd.exe never
    parses a prompt (no `&`, `|`, `%` injection).
  - **Provenance:** `CMETA_GENERATOR` records `OpenClaw <version>` with the model and thinking level.
  - **Tested on Windows:** dry runs of the three examples, and a real turn that reaches the model call
    and stops at the missing provider key.
- **New `task/scan-git-secrets`:** gitleaks over a repository's whole history (or, with `--files`, only
  its current files, or a plain folder).
  - **Output:** file, line, rule and commit, never the values (`--redact`, and the secret, match and
    e-mail fields are dropped), plus a value-free `--report`.
  - **Baseline:** `--baseline` accepts earlier findings by fingerprint, from this task's report or a
    native gitleaks one.
  - **Exit code:** 1 when something is found (`--no_fail` to always return 0).
  - **Tested:** on Windows and in a bare `python:3.12-slim` Linux container, on a scratch repository
    whose history holds a removed fake token: the history scan finds it, the files-only scan and a
    scan with the report as baseline are clean.
- **New `tool/aks-flex-node`** (the AKS Flex Node agent, https://github.com/Azure/AKSFlexNode,
  MIT, public preview). On Linux amd64/arm64 it downloads the pinned release archive (default
  `0.2.0`, any release with `--version=`) and verifies its SHA-256 against the release's
  `checksums.txt`. `--build --skip_install` builds it from git in the cMeta cache instead - at
  `v<version>`, or at any tag, branch or commit with `--with.checkout=<ref>` - with `tool/go`,
  stamping version, commit and build time the way upstream's Makefile does (a build of `main`
  reports e.g. `v0.2.1-alpha.1-7-g7f814fb`). The agent and its dependencies are Linux-only, so on
  Windows and macOS the tool says so and points to WSL or a Linux container, where the same `cx`
  commands work. Tested on Windows (the clear refusal) and in a `python:3.12` Linux container
  (release install, build at a tag, build of `main`).
- **`clone-git` gains `filter`, and `clone-git-to-cache` forwards `depth`, `filter` and `fetch`.** `filter`
  is git's partial-clone filter: with `--filter=blob:none` the full history is fetched but file
  contents only for the commits checked out, so a pinned checkout does not download blobs that exist
  only in old history (large files, or anything that should not have been committed) - as long as
  nothing reads them: `git show <old commit>`, `git log -p`, `git blame` and `git cat-file` fetch a
  missing blob on demand (`GIT_NO_LAZY_FETCH=1` refuses). `depth` (shallow clones) was supported by
  `clone-git` but not passed on by the cache wrapper, and neither was `fetch`; together,
  `--depth=1 --fetch="--depth 1 origin <full commit sha>" --checkout=<full commit sha>` gives a pinned
  checkout with no history at all, which still works after the branch moves on.
- **Removed the `test-core-via-ctuning` workflow** (outdated; `test-core` stays)
  and its README badge.
- **Fix: `tool/curl` no longer recurses when curl is missing.** curl is the common install dependency
  of `task/setup` on Linux and macOS, so installing curl itself (on a bare container, for example) set up
  curl again, over and over. `tool/curl` now sets `skip_common_install_uses: True`, as `tool/brew` does.
  In a non-interactive shell, `--install --quiet` installs a tool and such dependencies without asking.

## 0.32.2
- **README: how to update.** The engine and this repository are updated separately - `cx --version`
  (cMeta 0.32.2+) prints the command for the engine's install route (`uv tool upgrade cmeta`,
  `pip install -U cmeta`, ...), and `cx repo pull ctuninglabs@cmeta-aops` updates this repository
  (git pull + reindex); the engine's `docs/installation.md` "Updating cMeta" covers every route.
- **The agent launchers record how the artifacts of a session were made.** `task/run-claude`,
  `task/run-claude2`, `task/run-codex2` and `task/run-opencode2` set `CMETA_GENERATOR` for the agent
  process - `{"method": "agent", "agent": "<agent> <version>", "model": ..., "effort": ...}`, with
  the model and effort as passed after `--` (claude `--model` / `--effort`, else the thinking budget of
  `MAX_THINKING_TOKENS`; codex `-m` / `-c model_reasoning_effort=...`; opencode `--model` /
  `--variant`) - unless a task that runs the agent set it already, so an import task keeps its own
  record. `run-claude`, a pure pipeline so far, gains an `api_v1.py` whose `set_generator` step puts
  the record into the aggregated env, since its `cmd` step builds claude's environment from the host
  snapshot taken at bootstrap. With the engine's `artifact_defaults` / `CMETA_GENERATOR` support,
  every artifact the agent creates through `cx` carries it as `generator`, and every one it updates
  as `last_generator`. Documented in `docs/cmeta-aops/agent-tasks.md`.
- **Fix: `task/enable-long-paths-win` never enabled anything on a stock Windows.** Its
  `enable-long-paths-win.bat` began with a UTF-8 BOM, which `cmd.exe` reads as part of the first command
  under every code page except 65001 (UTF-8) - so on an ordinary English or French install the elevated
  window failed on `'<BOM>reg' is not recognized`, closed at once, and the registry value was never
  written. Every run then asked for administrator rights again and still reported long paths as off; it
  only ever worked on machines with the system-wide UTF-8 code page. The task now starts `reg.exe`
  elevated itself (no batch file, no user path to quote - an unquoted path with a space in the user name
  broke it too), waits for it, and checks the registry rather than `RtlAreLongPathsEnabled`, which
  Windows freezes when a process starts and so could never turn true within the same run. When the
  value is already set in the registry it no longer prompts at all. The warning says up front that an
  administrator prompt is coming and what to do if it does not work (Settings > System > Advanced >
  "Enable long paths" on Windows 11, or the `reg add` command), and the error repeats it with the reason
  (prompt declined, timed out, command failed). The `.bat` is kept, BOM-free, for running by hand.
- **Batch files no longer start with a UTF-8 BOM.** 336 `.bat` test scripts and helpers under `program/`,
  `task/` and `tool/` began with one, which `cmd.exe` reads as part of the first command under every code
  page except 65001 - on an ordinary English or French Windows their first line failed with
  `'<BOM>...' is not recognized`. Nothing else in them was non-ASCII, so they are plain ASCII now and run
  the same under any code page.
- **Tool detection lists each file once on merged-/usr Linux.** On Ubuntu, Debian, Fedora, Arch and
  others `/bin` and `/sbin` (and on some `/usr/sbin`) are symlinks into `/usr`, and all of them are on
  `PATH`, so every candidate was offered two to four times: a fresh Ubuntu listed `/bin/gcc`, `/bin/gcc-13`,
  `/usr/bin/gcc`, `/usr/bin/gcc-13`, ... and the first `cx tool setup git` asked to choose between `/bin/git`
  and `/usr/bin/git`, the same file. `find_path` now skips those three system aliases when the directory
  they point to is searched anyway. Nothing else is resolved: paths that may lead to different versions
  after an update - `/usr/local/cuda` and `/usr/local/cuda-13.0`, `gcc` and `gcc-13` - are still offered
  side by side, and `-q` still takes the default where there is no terminal to ask.
- **winget installs name `--source winget`.** Without it winget also queries the Microsoft Store source,
  and where that fails - `0x8a15005e: The server certificate did not match any of the expected values`,
  typically certificate pinning broken by an HTTPS-inspecting antivirus or proxy - it refuses to install
  a package it has already found in the winget source and asks for `--source`. Every `tool/*` winget
  command and the Windows `install_cmd*` of `task/host` (used by `install-sys-tool`) now pass it, as
  `tool/swiftlang` already did. Two lines that could never have worked are fixed on the way: the
  versioned `tool/tailscale` command said `--Tailscale.Tailscale` instead of `--id=Tailscale.Tailscale`,
  and `tool/microsoft.windows.adk` used `-id`, which winget rejects.
- **The ssh client is now a declared dependency, not a word on the caller's PATH.** `task/rclone-to-ssh`
  built its sftp command as a bare `ssh`, so which binary ran depended on the shell. A Windows host can
  carry several OpenSSH clients - the system one in `System32\OpenSSH`, the MSYS build inside Git, and
  copies bundled with other products - and they disagree on one thing that matters: the Windows build
  refuses a private key whose permissions let other users read it (`UNPROTECTED PRIVATE KEY FILE`, after
  which the key is ignored and authentication fails), while the MSYS build uses it anyway. The result was
  a sync that worked in one shell and failed in another with nothing but rclone's
  `couldn't initialise SFTP: ... unexpected EOF` to go on, which reads like a network or server fault.
  The task now resolves `tool/open-ssh` through `setup`, uses the absolute path, and prints it with its
  version, so the binary in use is visible in the trace instead of being a property of the environment.
  A resolved path containing a space keeps the bare name, because rclone parses `--sftp-ssh` as a
  space-separated list and the value is already quoted; the path is still reported.
- **`tool/open-ssh` detects properly and can install itself.** It gained `extra_paths` (the Windows
  system directory, winget packages, Homebrew), a second version regex, a per-distribution package name
  (`openssh-client` on Debian and Alpine, `openssh-clients` on Fedora, RHEL and SUSE, `openssh` on Arch),
  install commands for the three platforms and help text naming the Windows optional feature. Detection
  is what runs in practice, since the client ships with Windows 10 1809 and later, macOS and nearly
  every Linux.
- **MLPerf Inference v6.1 results and the MLPerf Inference Endpoints benchmark.** `task/get-mlperf-inference-results`
  defaults to the v6.1 round (published 2026-09-15; `--version=6.0` etc. still work) with a test script, plus the
  `clone-git` example scripts for inference v6.1 and training v6.0. Two new tasks read the Endpoints benchmark:
  `task/get-mlperf-endpoints-src` (mlcommons/endpoints, optional tag or branch) and `task/get-mlperf-endpoints-results`
  (`endpoints_results_v<round>`, default 0.7), both thin wrappers over `clone-git-to-cache` like their inference siblings.
- **README rewritten for first-time readers.** A plain opening (what the repository is, the one command,
  where to start: the course, the installer, the catalogues), a "Try it" block that pulls the repository
  from GitHub and runs the first tool, task and program, and one sentence on the Collective Knowledge
  lineage with a link to the framework's history page instead of the lineage paragraph. The status
  warnings, goals and core concepts are unchanged.
- **Fix: `tool/llvm` with a partial version (`--use.llvm.version=22`, `--version=22.1`).** The
  install hook pasted the partial version into the release URL (`llvmorg-22/LLVM-22-Linux-X64.tar.xz`,
  HTTP 404), which failed the *clang++ 22* workflow on every OS. It now resolves a partial version to
  the newest published release that starts with it (from the upstream tags, like `cmd_get_versions`),
  skipping release candidates and a release whose prebuilt asset is not there yet.

## 0.32.1
- **Six generic artifacts moved in from a downstream repository** (same UIDs, so any
  existing `alias,UID` reference keeps resolving): `tool/az` + `task/run-az` (Azure CLI:
  the official prebuilt download on Windows and macOS, the package manager on Linux,
  `az login` with the terminal attached), `tool/opencode` (OpenCode.AI, the third sibling
  of `claude` and `codex`) and the prompt runners `task/run-claude2`, `task/run-codex2`,
  `task/run-opencode2` (headless or interactive; transcript and token statistics recorded
  next to the prompt file). `run-claude2` adds cMeta repositories to the agent's context
  as `--add-dir`: by default its own repository plus the aliases in the new
  `agent_add_repos` key of the local cMeta config
  (`cx config set default --meta.agent_add_repos=alias,alias`, once per machine);
  `--add_repos=<alias,alias>` adds more, `none` adds nothing. These six carry no per-file
  copyright line - the repository licence (Apache-2.0) applies. New guide:
  [`docs/cmeta-aops/agent-tasks.md`](docs/cmeta-aops/agent-tasks.md) (usage, the flags
  the three runners share, which model and reasoning effort to pass to each agent).
- **`tool/obsidian` is a real recipe.** The previous file was a copy of `tool/openclaw`
  with the name changed; Obsidian is now detected on Windows, macOS and Linux with its
  version read from the installed files, and installed with `winget`, `brew --cask` or
  the pinned AppImage (tier 1 of the install ladder on Linux).
- **Every tool, task and program carries a one-line `desc` in its `_cmeta.*`**, shown by
  the cTuning.ai catalogues (tools, tasks, programs) and available to `cx <category> list`
  without scraping `_desc.*` keys.
- **Repository version 0.32.1** (`_cmr.yaml`), released together with cMeta 0.32.1, the
  engine release it was tested with.
- **Fix: `cx tool run <tool> --versions` no longer crashes.** `setup` may stop early
  without producing a command (it only prints the available versions); `tool run` now
  returns that result instead of reading a missing `cmd`.
- **Fix: `download-file` with several URLs (mirrors).** Filenames and MD5 sums are
  matched to URLs by position; with fewer names than URLs every later mirror derives
  its own filename and skips the checksum instead of failing on an out-of-range index.
- **`tool/rclone`: default version pinned in `_desc.yaml`** (`default_version`, bump it
  there), **two download mirrors** (downloads.rclone.org and GitHub releases, walked in
  order by `download-file`), and **package-manager fallbacks** (`apt`/`dnf`/... via
  `install_cmd_sudo`, `winget` on Windows) when the binary download fails.
- **New task `rclone-to-ssh`**: sync / copy / bisync / resync a local directory to a
  plain SSH host with rclone's connection-string remote - no `rclone.conf` entry, no
  stored credentials.
- **`tool/claude`: the Windows installer is run as `.\install.cmd`**, so the command
  works when the current directory is not on PATH.
- **`add-tool` skill rewritten around the install ladder** (prebuilt binary via
  `download-file` -> non-sudo package manager -> sudo package manager), with the
  mirror pattern and `download-file`'s two positional behaviours documented;
  `AGENTS.md` and `CLAUDE.md` carry the same rule plus the git workflow (sign-off,
  dated branches and PR titles).
- **Housekeeping:** `.gitignore` now covers AI-session provenance files
  (`claude-resume-*`, `claude-summary-*`, `codex-*`), the runtime state of a
  `CMETA_HOME` created inside the repo (`index/`, `repos/`, `repos.json`), partial
  downloads (`*.partial`) and the bytecode caches under `task/target` and `task/venv`;
  the docs no longer carry a machine-local path or a LAN address.
- **Documentation: the abstraction the content rests on is now named.** Goals
  gained "Abstractions you can operate" — every tool, library, program, model,
  dataset and workflow here is one artifact that is simple, reusable, live and
  interconnected by `alias,UID`, inspectable down to its inputs and provenance,
  so results can be taken back to first principles and the content is
  [FAIR](https://www.go-fair.org/fair-principles/) by construction rather than by
  extra effort. `llms.txt` carries the same line.
- **Documentation: the purpose is stated consistently with the cMeta framework.**
  The Goals section now names all six aims — the previously missing *scalable* and
  *sustainable* were added — and the agent goal makes the point explicitly: an
  agent is only as useful as the context it can assemble, and here that context is
  already recorded and machine-readable.

## 0.32.0

**First public release, under the Apache License 2.0.**

- **Relicensed the repository from proprietary ("All rights reserved") to
  Apache-2.0**, matching the [cMeta framework](https://github.com/cTuningLabs/cmeta):
  - New `LICENSE` (Apache-2.0) and rewritten `COPYRIGHT`.
  - Copyright headers updated across the artifact collection — `_cmeta.*` metadata
    fields, Python/C/C++/Objective-C++ source headers, workflow and script comments.
    Original copyright years and holders were preserved.
- **New `THIRD-PARTY.md`** — the authoritative record of vendored third-party
  components, replacing the previous three-line `LICENSES` file. It lists each
  component's path, copyright holder and licence, and flags those whose terms are
  **more restrictive than Apache-2.0**:
  - `program/cbench-automotive-susan/` — SUSAN, Crown Copyright (UK DERA):
    research use only, must not be sold; UK Patent 2272285.
  - `program/milepost-codelet-…-susan-codelet-10-1/` — SUSAN-derived MILEPOST codelet.
  - `program/lib-milepost/` — GPL (EU FP6 MILEPOST, released by CAPS Entreprise).
  - `program/lib-polybench/` — Ohio State University Software Distribution License.
  - `program/lib-xopenme/` — BSD and LGPL.
  - `task/test-mojo-life/` — Modular Inc., Apache-2.0 with LLVM Exceptions
    (compatible; listed for attribution).
- **Removed the vendored NVIDIA cuDNN RNN sample**, whose licence prohibits
  redistribution. The affected artifacts (`program/test-rnn-cudnn-blas-nvcc-cuda`,
  `task/test-nvcc-cudnn-rnn`) were moved to a separate private repository.
- **Added community health files** for the public release: `CONTRIBUTING.md` (with
  guidance on vendoring third-party code), the verbatim `DCO` (Developer
  Certificate of Origin 1.1), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1),
  `MAINTAINERS.md`, `CITATION.cff`, and a self-contained
  `.github/workflows/dco.yml` that checks every pull-request commit is signed off.
- **Hardened `.gitignore`** against cMeta run artifacts (`tmp*/`, `tmp-cmeta-*`,
  `cmeta-task-saved-*`, `_repro_ctx_*`) and author scratch/backup siblings. These
  capture the full environment of the machine that produced them and must not be
  published; a few that had been committed were removed from tracking.
- Moved the `skill` category into this repository from the cMeta engine.
- Documentation and authoring skills (`AGENTS.md`, `CLAUDE.md`,
  `docs/cmeta-aops/`, `.claude/skills/`) updated for the Apache-2.0 licence, the
  third-party carve-outs, and the narrow-reindex guidance.

## Earlier

Development prior to 0.32.0 was not public and is not itemised here. It covered
the `task` workflow engine (API v2), the `tool` and `program` delegators, the
category cache, the compute abstraction (CPU / CUDA / Android / Metal / …), and
the growth of the artifact collection to roughly 115 tasks, 100 tools and 30
programs, plus models and datasets.
