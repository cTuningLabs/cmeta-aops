# host - the login endpoints of a fleet

A **host** is one thing a command can be run on: an OS reachable over ssh (this machine included), a
WSL distro, a container, a phone over adb. A **machine** (category `machine`) is the asset it lives on -
one laptop carries a Windows host, a WSL host and a Docker host. The host points at its machine with
`machine: <cRef>`, and may be reached `via` another host (a container on a remote machine).

**A device that moves between machines** (a phone or a tablet plugged into whichever machine is at
hand) is still one machine and one host: the host is the Android OS on that device, the parent is only
the route to it. Its `via` is a **list** of candidate parents; `status`, `probe`, `run` and `restart` ask
every candidate at once, and among the parents whose adb lists the serial the one that saw it last
(`state.yaml`: `via_now`, `via_seen_at`) wins, then the declared order. adb on a parent is taken from
PATH, else from the copy cMeta set up as a tool (`cx tool run adb -q --con-`, which installs the
platform tools on first use). `status` shows the device `up ... via <parent> (moves)` or
`down ... (moves: <the candidates>)` - what each parent answered, with the time it took, is in the result
(`parents`) and under the row with `-d`. One host per machine-device pairing would duplicate the declared facts,
split the probed state and put something that changes into an alias; when the route matters for a
measurement, it is provenance of that run, not a second identity.

Declared by hand in `_desc.yaml`; observed by `cx host probe` in `state.yaml` (never edited by hand).

## Naming

`<owner>-<machine>` for machines, `<machine>-<environment>` for hosts:

```
my-pc            my-pc-win   my-pc-wsl2   my-pc-docker-ubuntu24-amd64
lab-laptop                lab-laptop-ubuntu
lab-mac-mini             lab-mac-mini-macos
my-phone         my-phone-android
dapple-labs-azure-vm     dapple-labs-azure-vm-ubuntu
prod-azure-vm      prod-azure-vm-ubuntu
prod-vm-2   prod-vm-2-ubuntu
```

Nothing that changes (OS version, IP, Tailscale name) goes into an alias - those are fields. A docker host's
alias carries the architecture of its image (`-amd64`, `-arm64`): Docker Desktop runs several under emulation
and one machine may hold both (since 2026-10-08).

Renames use `cx host migrate <old> <new>` to preserve the host UID and leave an alias redirect.
Host fleet lists and selections skip redirect stubs; an explicit old alias resolves to the renamed host.
The Azure host was renamed on 2026-10-10; its underlying machine alias remains `prod-azure-vm`.

## Commands

```
cx host ls [--tags=ubuntu] [--machine=my-pc] [--type=ssh] [--status|--active] [--made]   (--made: the instances cMeta made, also for status)
                                      columns: HOST TYPE MACHINE (STATUS) OS SUDO DOCKER PODMAN CMETA AOPS PROBED
                                      (DOCKER/PODMAN: the client version the probe saw, "-" = not installed,
                                      "(daemon down)" = a Docker client without a running daemon)
cx host status [host] [-d] [--timeout=3] [--cmd_timeout=20]
                                      one line per host: HOST TYPE OS STATUS ADDRESS; -d (--details) adds TIME and, under a
                                      moving device, what each parent answered and how long it took
                                      here | up | stopped (a WSL distro between uses: wsl.exe starts it for the next command, so probe, sync, upgrade and restart take it) | down | missing | via <parent> down | timeout (...)
cx host probe [host|selection]        -> state.yaml: OS, kernel, GPU, sudo, python, uv, cx, cMeta version/home, AOPS version, disk, repos
cx host show <host>                   _desc.yaml + state.yaml
cx host run <host> "<command>"        locally when the host is this machine, else ssh / wsl.exe / docker exec / adb shell
cx host run <host> -- <command words> the same, the words after "--" joined (cMeta parses none of them; a word with a space is quoted)
cx host run --tags=ubuntu "<command>" the same on a selection (--machine, --type, --all)
cx host run <host> --script=<file>    a local script on the host's shell stdin ("bash -l -s < file"; PowerShell: base64 lines on stdin, decoded as UTF-8 and run by an -EncodedCommand reader - never "-Command -")
cx host run <host> "<command>" --interactive   a terminal for the command (ssh -t / docker exec -it): it can ask its questions; needs a terminal here (not with --capture or --script)
cx host ssh <host> [--screen[=<name>]] [--x11] [--forward=1455,8080:80] [--dry_run]   interactive shell (also: shell, login)
cx host up|down <host>                WSL distro, container (created from its image on the first up), or "commands: up/down"
cx host destroy <instance> [--image] [--keep_artifact] [--force]   an instance cMeta made (get-host--docker / get-host--wsl): the container (or the WSL distribution and its disk), the artifact, with --image its image
cx host snapshot <instance> [--name=<name>] [--note=<text>]       the instance's state kept: docker/podman commit to cmeta/snapshot:<instance>-<name>, a WSL export next to its disk; recorded under "snapshots" in its _desc
cx host restore <instance> [--name=<snapshot>]                    the instance back to a snapshot (the last one by default): the container made again from the image, the distribution imported again
cx host restart <host> [--yes] [--no-wait] [--timeout=600] [--skip_after] [--dry_run]   (also: reboot)
cx host sync [host|selection] [--repos=a,b] [--resync [--resync_mode=newer|path1|path2]] [--unlock] [--dry_run] [--skip_after]
cx host push <host> <repo> --dirs=task/x/,tool/y/ [--dry_run] [--delete] [--index-]   then "cx repo reindex <repo>" on the host, so a new artifact is found there
cx host push <host> <local path> --to=<remote path>      a folder goes under --to, a single file lands AT --to (rclone copyto)
cx host pull <host> <remote file or folder> [--to=<local folder>] [--files=*.jsonl,steps.txt] [--dry_run]   the other way: host -> here (rclone copy --from_remote of rclone-to-ssh); nothing here is deleted
                                      (push and pull with -q set rclone up again when the cMeta cache was cleaned)
cx host backup <host> [--to=<folder>] [--dry_run] [--skip_commands]   what only the host has (its "backup:" block: config, state, secrets, scripts; root-only files through sudo)
                                      into <its machine artifact>/backup/<host>/<YYYYMMDD-HHMM>/ with backup.yaml
cx host restore <host> [--source=<backup folder>] [--into=<folder>] [--paths=a,b] [--dry_run] [--yes]   a backup back onto the host (the newest of its own by default,
                                      --source: another host's - a rebuilt VM), then "backup: commands: after_restore"; a production host needs --yes; --into: under a folder (a test)
cx host upgrade [host|selection] [--version=0.33.0] [--sync] [--restart [--yes] [--timeout=600]] [--dry_run]
                                      (sync, upgrade and restart probe the host again afterwards: "cx host ls" shows what is there now)
cx host upgrade <host> [--engine-] --system [--firmware] [--check]   the OS packages (and firmware) too: "cx task run upgrade-os" on the host
```

## Persistent terminals with GNU Screen

```console
cx host ssh my-host --screen
cx host ssh my-host --screen=work
cxt run-ai --project="work::my-project" --on=my-host --on_screen
cxt run-ai --project="work::another-project" --on=my-host --on_screen=another-task
```

A bare or explicitly empty `--screen` / `--screen=` uses `cx-host`. A bare or explicitly empty
`--on_screen` / `--on_screen=` uses the command's artifact alias (`run-ai` for
`cxt run-ai`). A name selects a screen belonging to the remote user on that host. Names contain 1-64 letters,
digits, underscores or hyphens and start with a letter or digit. Omit the flag to keep the usual shell/task behavior.

The first invocation creates the screen and starts its shell or task. Repeating it reconnects to that screen;
the new command, prompt and project are ignored while the existing session lives. The existing window titles
are printed before attaching, including a run-ai project's reference. Use distinct names for independent tasks.
Reattaching transfers the screen's display from its previous connection.

Closing SSH or hibernating the client leaves the remote programs running. Repeat the same command after
reconnecting. `Ctrl-a d` detaches deliberately. `exit` at the shell prompt closes its window; quitting an AI
harness normally lets run-ai save its records and finish. The screen ends with its last window. A later
invocation creates a new terminal; run-ai retains its normal conversation continuation rules.

GNU Screen is detected or installed through `tool/screen` on the target POSIX host (Linux/macOS, WSL or a
container). An interactive terminal is required on the client. A native Windows target and Android are refused.
`--on_screen` cannot be combined with `--on_detach`, `--on_pull`, `--on_rm` or `--on_isolated`: disconnecting
from a terminal must not clean up an environment whose task is still running. A target reboot ends its screens.
Screen keeps terminal processes alive; concurrent sessions still share the host's files and repositories.

`cx host run my-host "my-command" --screen=my-task` uses the same behavior. A screen run does not support
capture, scripts on stdin, raw commands, timeouts or a host selection. Its return code describes the terminal
attachment; the task's own records describe its outcome.

A Windows batch launcher can pass an optional first argument as `--screen="%~1"`. With no argument the empty
value selects `cx-host`; an argument selects that name. Omit the flag entirely for an ordinary SSH shell.

## Status: what is checked, and how long it takes

Set `retired: true` in a host's `_desc.yaml` to keep its historical record without
checking its old endpoint. Both `cx host ls` and `cx host status` show `retired`;
`status` skips transport and project-server checks, and `--active` excludes it.
JSON rows include `retired: true`, including saved listings. A failed connection
or an alias containing `destroyed` does not declare retirement. Remove the flag
or set it to `false` when reusing a host with its new connection details.
The linked machine has its own `retired: true` declaration: retiring an OS host
does not automatically retire a machine that may still have other active hosts.

`status` (and `ls --status`) checks every host at once: an ssh host is a TCP connect to its port
(`--timeout`, 3 s); a WSL distro `wsl -l -v`; a container `docker inspect`; an adb device `adb devices` on
its parent, through the parent's ssh when the parent is another machine - and a device that moves asks all
its candidate parents at once. Every check that runs a command is killed at `--cmd_timeout` (20 s) and
reported as `timeout (...)`: a hung adb server or ssh never holds the table. The table appears when the
slowest check has answered, so a warm fleet takes 2-3 s and a cold one (peers asleep behind Tailscale, adb
servers not yet started, Python and cMeta caches cold, the WSL service down) tens of seconds the first
time - that is the fleet waking up, not a check waiting. `-d` (`--details`, also for `ls --status`) adds a
TIME column and, for a moving device, the answer of each parent with its time, to see which host was slow;
`--cmd_timeout=120` gives a slow host a thorough chance. The result carries the same (`hosts[].status_time`,
`parents`). The OS column is the declared `os:` of the host (ubuntu, windows, macos, android); `ls` shows
the probed one. (The global `-v` is not the switch: `CMETA_VERBOSE=true` sits in the user's environment.)

A host named outright that is down is an error; in a selection it is skipped and reported.
`restart` asks y/N unless `--yes` or `-q`, reboots (`sudo -n shutdown -r now`; Windows `shutdown /r /t 5`;
WSL `wsl -t` + start; `docker restart`; `adb reboot`; or the host's `commands: restart`), waits until the
host answers again, then runs its `commands: after_restart` on it (the servers to bring up).

`upgrade` replaces the engine under whatever runs on the host and never stops or restarts a server:
a running cserver keeps the modules it has loaded and reads every later import from the new tree (or
fails when `uv tool install --force` has removed the old one). The start scripts declared as
`after_restart` do not kill a running server either, so the full update of a host that runs servers is
**sync, then upgrade, then restart - in that order** (a reboot before the upgrade brings the servers up
on the old engine, and they would need a second one). `--sync` and `--restart` do the three steps per
host: `cx host upgrade dapple-labs-azure-vm-ubuntu --sync --restart --yes`. The restart asks y/N like
`cx host restart`, happens only after a successful upgrade (including "already <version>"), and this
machine is never restarted when it is part of a selection. Services are not declared per host on purpose
(the user's decision, 2026-10-06): the reboot is the restart.

`--system` (and `--firmware`) upgrade the operating system too, before the engine: the public task
`upgrade-os` runs on the host (`cx task run upgrade-os -q [--firmware] [--check]`) and picks the OS's own
commands from what its host task detected - apt/dnf/zypper/pacman/apk on Linux, `softwareupdate` and
Homebrew on macOS, `winget upgrade --all` on Windows, fwupd for the firmware on Linux - with `sudo -n`,
so a host whose `state.sudo` is `password` is skipped with a note (run the task in a terminal on it, or
add a NOPASSWD rule). `--check` only lists what would be upgraded (no sudo needed where the OS allows;
apt's index refresh is then skipped with a note), `--engine-` leaves the engine alone, and the result line
carries the task's verdict, including whether the OS asks for a reboot: `OS: ubuntu (apt-get): update,
upgrade ok; a reboot is required` - then `--restart --yes`, or `cx host restart`.
`cx host upgrade lab-laptop-ubuntu --engine- --system --firmware --check` shows what is pending.

## _desc.yaml

```yaml
machine: machine,fc0812696c6a4145::lab-laptop,bca369ecc0aa4b0e
type: ssh                      # ssh | wsl | docker | adb
os: ubuntu
via: host,...::my-pc-win,...     # wsl / docker / adb only: the host that runs wsl.exe / docker / adb
via:                                     # or a LIST of candidate parents for a device that moves (adb):
  - host,...::lab-thinkpad-ubuntu,...   #   tried after the one in state.yaml via_now, first that sees the serial wins
  - host,...::my-pc-win,...

access:
  hostname: lab-laptop       # the OS hostname: when it is the local one, commands run here without ssh
  address: lab-laptop.local  # DNS / Tailscale name or IP (ssh)
  user: user
  key: fgg.crypt::ssh-universal4-without-pass/20250130-without-pass/id_ed25519_fgg_universal4
                               # <category>::<artifact>/<file>, or a path: C:\keys\id_ed25519, ~/.ssh/id_ed25519, %USERPROFILE%\...
                               # a reference whose artifact is not on this machine: the copy a secret holds ("cx secret
                               # which"), else ~/.ssh/<file name> with a warning (see "Another orchestrator")
  port: 22                     # optional
  options: "-o ..."            # extra ssh flags, optional
  x11: true                    # ssh -X for "cx host ssh", optional
  shell: bash -l               # bash -l (default) | sh | powershell | cmd | none - wraps every command
  distro: ubuntu-24.04-on-usb-x        # wsl
  container: cmeta-ubuntu24-amd64            # docker (+ image, keepalive, run_args for the first "up"; engine: podman for a podman container)
  serial: R52Y80BXRAK                  # adb

cmeta:
  home: /home/user/CMETA
  install: uv-tool             # uv-tool | pip | editable (+ source) - drives "upgrade"
  extras: [server]             # uv-tool: the extras to keep on an upgrade (else read from uv's receipt of the tool)
  upgrade: uv tool upgrade cmeta       # or the literal command

sync:
  repos_path: /home/user/CMETA/repos   # optional; without it: <the cMeta home of the last probe>/repos (what "cx --version"
                               # reports there), else <cmeta: home>/repos, else ~/CMETA/repos; "cx host sync" says which
  default: git                 # bisync (two-way, rclone over ssh) | copy (one-way, never deletes) | git (pull --ff-only there) | none
  workdir: '%LOCALAPPDATA%\rclone\bisync-<name>'   # bisync listings and lock (default: bisync-<alias>)
  blacklist: [tmp*/, __pycache__/, .venv/, .git/, .claude/, __symlinks/]
  repos:
    - ctuninglabs@cmeta-aops
    - myorg@my-private-repo: {method: copy}
    - dappledev@dapple-lab-emulation: {blacklist: [runs/, dle.egg-info/]}
    - some-repo: {remote: /other/path, workdir: ...}
    - my-big-repo:             # a PARTIAL repository: only these artifacts travel (cRef patterns, see below)
        artifacts: [my.project::x/!AI, work::2026*, machine::*]
  after: [cx --reindex]        # run on the host after a sync that did something

commands:                      # optional
  up: az vm start ...          # run locally: a cloud VM, a service
  down: az vm deallocate ...
  restart: ...                 # run locally, instead of the default reboot command
  after_restart:               # run ON THE HOST once it answers again (servers); let ssh return:
    - setsid nohup ~/work/start-server.sh > ~/cmeta-tests/server.log 2>&1 < /dev/null &

backup:                        # optional: what only this host has ("cx host backup", see below)
  paths:                       # on the host, relative to the login home (or absolute): a folder, a file, or a few files of a folder
    - CMETA/repos/local/config
    - CMETA/repos/local/state
    - {path: CMETA, files: ["__run_*.sh"]}
    - _start.sh
  sudo_paths:                  # root-only files and folders, read through sudo (passwordless) into a staging folder first
    - /etc/cloudflared/token
  exclude: ["**/__pycache__/**", "**/*.tmp"]   # rclone filter patterns left out of every folder
  keep: 10                     # dated backups kept per host (older ones removed after a successful one; default: all)
  commands:
    before: []                 # on the host before the copy (a dump, a stop)
    after_restore: [cx --reindex]   # on the host after "cx host restore" put the files back

requires: the USB drive        # free text, shown to agents
ai:                            # what an agent may do there (declared; the probe writes the observed "sudo" to state.yaml)
  workdir: /home/user/cmeta-tests
  sudo: passwordless
  do_not_touch: [/home/user/CMETA]
  disposable: true
  production: true
  notes: ...
```

## Project environments

A host can retain its global `cx` / cMeta home and also declare independent projects:

```yaml
projects:
  my-server:
    path: /home/user/projects/my-server
    venv: /home/user/projects/my-server/.venv
    cmeta:
      home: /home/user/projects/my-server/CMR
      install: pip
    server:
      url: http://127.0.0.1:8118/
      # expected_status: [200, 302]  # optional; default: any HTTP 200-399
    # sync: {repos_path: ..., default: copy, repos: [...], after: [...]}
```

`path`, `venv`, and `cmeta.home` are required. Use absolute paths. A named project does
not inherit the global cMeta upgrade command, sync repositories or restart commands.
POSIX and PowerShell shells support project environments; cmd-only and Android shells
do not. The project's `cx` must exist: a missing project/venv fails instead of falling
back to global cx. POSIX projects require the venv activation script; PowerShell uses
the venv's Scripts directory explicitly.

```text
cx host run <host> "cx --version" --project=my-server
cx host run <host> --script=inspect.sh --project=my-server
cx host probe <host> --project=my-server
cx host sync <host> --project=my-server --dry_run
cx host push <host> <repo> --dirs=category/example/ --project=my-server
cx host upgrade <host> --project=my-server --dry_run
cx host show <host> --project=my-server
```

Run/scripts, probes, sync after-hooks, push indexing and upgrades select the project's
working directory, venv and CMETA_HOME. A pip project upgrades through `uv pip install
--python <project interpreter>`; a literal `cmeta.upgrade` can override this. Without
`--project`, operations retain the existing global environment. A global `probe` also
probes declared projects, storing their observations under `state.yaml: projects`;
a selected project's probe preserves the global and other project observations.

Both `ls` and `status` show project lines beginning with `  * ` below their host.
Plain `ls` uses the last probe's server result. `status` and `ls --status` check HTTP
readiness live from the host, separately from SSH liveness, with bounded timeouts.
`--project=<name>` limits the child rows/checks to that project. JSON host rows include
a `projects` list. Readiness does not follow redirects or use HTTP proxies: a redirect
response can be healthy without accidentally checking another public server. HTTP
errors report `unhealthy`; connection failures report `down` or `timeout`; missing
server configuration reports `not configured`. The host needs Python for HTTP checks.
These checks never start a project and do not test external firewall reachability.

Reboots and OS/firmware upgrades remain host-wide. `upgrade --project` rejects
`--restart`, `--system`, and `--firmware`; use a separate whole-host command explicitly.
Interactive `ssh`, `up/down`, and `restart` remain host operations.

## Probe observations

`probe` writes `probed_at`, `hostname`, `os`, `kernel`, `arch`, `uptime`, `user`, `home`, `sudo`, `python`,
`uv`, `git`, `docker`, `cx`, `cmeta_version`, `cmeta_home`, `aops_version`, `disk`, `gpu`, `cpus` and `repos`
(per registered repository - `cx repo find`, plugged ones included; the folders under `<cMeta home>/repos`
when there is no `cx`: git branch/commit/date/changed files or `copy`, the `_cmr.yaml` `version` and
`artifact`). `aops_version` is the version of the cMeta AOPS repository (ctuninglabs@cmeta-aops, recognised
by its UID whatever its folder is called); `cx host ls` shows it as AOPS - `none` when a probed host has
no AOPS, `-` when the host was never probed.

`sudo` is what an unattended system upgrade needs to know: `passwordless` (`sudo -n true` works), `password`,
`none` (no sudo), `root`. Windows has no sudo - there it is `elevated` (the session holds an Administrator
token: true for an OpenSSH login of a member of Administrators, false for a UAC-limited desktop shell) or
`not elevated`; `windows_sudo: available` when "sudo for Windows" (11 24H2+) is enabled.

## Sync, push and the bisync baseline

`sync` is the declared method per repository. A **bisync** pair keeps a baseline (rclone's listings in
`workdir`); when one side was replaced behind rclone's back (a `git archive | tar`, a fresh clone), the
next run stops with "Safety abort: all files were changed" - run it once with `--resync` (`--resync_mode`:
`newer` = the newer file wins on each side, `path1` = this machine wins, `path2` = the host wins), as the
old `_7-resync-*.bat` did. A few directories once are a one-way **push** (`rclone copy` with an anchored
whitelist, `--dirs`).

`--dry_run` shows what would move and changes nothing (rclone `--dry-run`, `git fetch --dry-run`).

### A partial repository: `artifacts:`

A repository too big to copy (a personal one of hundreds of GB) can travel as a selection of its artifacts, two-way
like any other, with `artifacts:` in its sync entry (or `--artifacts="a;b"` on a push) - cRef patterns whose
aliases compare without case, `*` and `?` as wildcards:

```
fgg.project::cMeta/!AI     the !AI folder of that artifact, with its _cmeta and _desc (not the rest of it)
fgg.project::cmeta-aops    the whole artifact (it must exist on this machine)
work::2026*                every artifact of the category whose alias starts with 2026 - a folder glob through
                           the category's shard folders (work/2026/2026*), so an artifact made later on EITHER
                           side is in it
machine::*                 every artifact of that category
```

The repository's `_cmr.yaml` and the definitions of the categories it holds itself come along (an artifact found
in the folder of a nested repository - the engine's internal repository inside a source tree - is not one of
it), so the copy is a repository the host's cMeta indexes: the first sync or push plugs it there, later ones
reindex it. rclone filters by the anchored rules the patterns give (`--ignore-case`, as cMeta's aliases).

A **filtered bisync** is safe only while the filter stays the same - rclone's listings hold what it let through,
and other rules would read the difference as deletions. The rules depend on the patterns, not on which artifacts
exist, and `cx host sync` keeps the rules of the last run next to the listings (`cmeta-selection-<repo>.txt` in
the bisync workdir): a run whose rules changed - or the first one - stops and asks for one
`--resync --resync_mode=path1`. After every sync or push the host's copy gets `PARTIAL.md` at its root: what it
holds, from which machine, since when (outside the rules, so it never comes back). An artifact made on the host
outside the patterns stays there.

A partial repository is never pushed whole: `cx host push <host> <repo>` without `--dirs` takes its patterns.

### A repository of secrets

A repository whose `_cmr.yaml` says `secrets: true` (the `secret` category's identities and keys) is never synced -
`cx host sync` refuses it - and goes to a host only by name, on purpose:

```
cx host push <host> my-secrets --artifacts="secret::git-work-without-pass;secret::ssh-azure-x" --secrets
```

The folder there is made readable by the host's user alone first (`chmod 700`), then the secrets are copied,
the repository is plugged, and `cx secret check --fix` there makes every private key owner-only (rclone's sftp
does not keep a file's mode: the keys arrive as 664). The repository is not a registered repository of the host's
sync list: `push` finds it by its alias here and sends it to `<repos path>/<folder>` there.

## Backup and restore: what only the host has

A host's repositories come back from their sources (git, a bisync pair); what does not is what the host alone holds:
cMeta's own configuration artifacts there (`<home>/repos/local/config`), the state of its sites (accounts, API
keys, runtime data), the secrets its servers read, the scripts that start them, a tunnel token under `/etc`. The
host's `backup:` block names those paths and `cx host backup <host>` copies them, one way, into a dated folder of
the **machine artifact** the host belongs to - `<machine>/backup/<host alias>/<YYYYMMDD-HHMM>/` - with
`backup.yaml` saying what came, from where (the login home), how big it was and which mode it had - and, for a
folder, the mode of everything inside it (`modes`, up to 5,000 entries; GNU find's `-printf`), since the copy
itself keeps no mode. The machine artifact is the asset's record and a private repository on the orchestrating
machine, so the files of a rebuild sit next to it; a repository of secrets stays one (`secrets: true`: it is
never synced, see above).

- Relative paths are under the login home and land under `home/<path>` of the backup, absolute ones under
  `root/<path>`; a few files of a folder: `{path: CMETA, files: ["__run_*.sh"]}` (rclone include patterns).
- `sudo_paths` are copied by `sudo cp -a` into a staging folder the host's user owns, fetched, and the staging
  folder is removed again - the host needs passwordless sudo (`ai: sudo: passwordless`).
- `--dry_run` asks the host what each path is (a folder, a file, missing) and how big, copies nothing.
- `keep: N` removes the oldest dated backups beyond N after a successful one; without it every backup stays.

`cx host restore <host>` puts the newest backup of that host back where it came from - or `--source=<folder>`,
any backup folder: the backup of the host this one replaces, on a freshly set-up VM, once cMeta is installed
there and its repositories synced (the order of a rebuild: install cx, `cx host sync`, `cx host restore
--source=...`, then the host's `commands: after_restart`). Root-only paths go back through sudo; every recorded
mode is put back (a private key lands owner-only again, as it was); a folder that was empty on the host has no
copy in the backup and is made again, empty; then the host's `backup: commands: after_restore` run (`cx
--reindex` for the config artifacts).
`--into=<folder>` lands everything under that folder on the host instead (a look at what a backup holds, or a
test of the mechanics on a disposable host), with no sudo and no after commands; `--paths=a,b` restores a part. A
production host (`ai: production: true`) restores only with `--yes`. Nothing on the host is deleted by a restore:
what the backup does not hold stays as it is.

## Drivers

Every verb is built on four primitives per type - status, up/down, run, push/pull - so a new access
type is one more branch in `_cmd_run`, `_status`, `_up_one`, `_down_one` of `api/v1.py`. Commands are
wrapped in the host's shell: `bash -l -c '...'` through ssh (the remote shell parses it), `bash -l -c "..."`
for a local Windows process (wsl.exe, docker, adb get their arguments from cmd.exe, which only groups with
double quotes). On Windows a remote command holding a double quote (or `^`, `%`) is sent on the host shell's
stdin from a temporary script instead - cmd.exe toggles its quoting on every `"`, so a `|` behind one would
run locally. Keep commands simple; anything with quotes of its own is better off in `--script` (in PowerShell
write `--script=$path`, not `--script=(...)`, which PowerShell splits into two arguments). The cMeta CLI
parser also reads `-la` or `*` inside a quoted command as its own flags - the same answer: `--script`.

A Windows host with an OpenSSH server is `type: ssh` with `shell: powershell` (untested until one exists).

## WSL and Docker hosts (tested 2026-10-06 on my-pc)

Both are reached through the host that runs `wsl.exe` / `docker` (`via:`); when that host is this machine
the commands run directly, otherwise through its ssh.

**WSL** (`type: wsl`, `access: {distro, user, shell}`): `status` parses `wsl -l -v` (missing | down | up);
`up` = `wsl -d <distro> -- true`, `down` = `wsl -t <distro>`, `restart` = both; `run` = `wsl -d <distro>
--user <user> -- bash -l -c "..."`; `probe` = the same with `bash -l -s < probe.sh`. The distro of the main
PC lives on the USB drive (`requires:`), sees the Windows repositories through `/mnt/d` (so `sync: none`)
and reports `sudo: password` - `user` is not in its sudoers without a password (the ThinkPads' script
`1a-current-user-to-sudoers-without-password.sh` would change that). Its cMeta is a pip install in
`/home/user/work999/.venv` (`cmeta: install: pip` + the literal `upgrade:` command).

**Docker** (`type: docker`, `access: {container, image, keepalive, run_args, user, shell, engine}`; `engine:
podman` makes every command below a podman one - the two engines share the words): `status` =
`docker inspect` (missing | down | up); the first `up` creates the container from `image` with
`docker run -d --name <container> <run_args> <image> <keepalive>` (default `sleep infinity`), later `up`/`down`/
`restart` = `docker start/stop/restart`; `run` = `docker exec <container> bash -l -c "..."`, `probe` adds `-i`
for stdin. The container keeps its files across stop/start; `docker rm <container>` throws it away and the
next `up` creates a fresh one. A plain `ubuntu:24.04` has no python3 and no `cx` (the probe shows `cMeta -`):
for cMeta work use one of the `cmeta/host-ubuntu:24.04-cmetalocal-*` images as `image:`, or install inside
with `cx host run`. Inside the container the user is `root` (`sudo: root`). `--gpus all` goes into
`run_args` (Docker Desktop on the main PC supports it). Docker Desktop itself lives on the USB drive and is
started by the user, never by `cx host up`.

**after_restart commands** run through ssh: a script that starts servers must detach, or ssh waits for the
servers' stdout. `nohup ... &` alone is not enough when the script's stdout is a pipe (no terminal, so nohup
does not redirect); write `setsid nohup bash <script> > <log> 2>&1 < /dev/null &`, or make the script redirect.
The `bash` matters: a script without a `#!` line is run by bash when typed as `./script` in an interactive
bash, but `nohup`'s exec of it fails and falls back to `/bin/sh` - dash on Ubuntu, no `pushd`, different
quoting (seen on a server: every line "not found", no servers after the reboot).

## Another orchestrator

The artifacts are not tied to one machine: whichever machine runs `cx host` sees the host whose
`access.hostname` is its own as "here" and reaches the others over ssh. For that it needs the repository
with the host artifacts, `cx`, `rclone` (set up by the first sync) and the keys.

**The keys of another orchestrator** (since 2026-10-22). A host names its key by a reference into a private
repository (`key: fgg.crypt::ssh-x/2026/id_ed25519`) that stays on the first machine. The second one gets the
`secret` artifacts that hold copies of those keys - their `files.from` names the referenced folder and
`files.names` the file - pushed once with `--secrets` (above). `cx host` then finds a key whose artifact is not
there through `cx secret which <the reference>`; a key without such a secret falls back, as before, to
`~/.ssh/<file name>`, with a warning (names in `~/.ssh` can collide).

**Its known hosts.** The new machine has never seen the servers' host keys, and a batch ssh refuses an unknown
host ("Host key verification failed") - before any key is tried. Compare what it sees
(`ssh-keyscan -t ed25519 <address> | ssh-keygen -lf -`) with the fingerprint the first machine trusts
(`ssh-keygen -lF <address>`) and add only a key that matches; never `StrictHostKeyChecking=no`.

**The orchestrator's own repositories.** The second machine works on a partial copy of the first one's private
repository (`artifacts:`, above) and keeps its own `local` repository (its cache, its test sessions). The first
machine stays the hub that runs the syncs and holds the git clones: what the second one changes comes back by
bisync.
