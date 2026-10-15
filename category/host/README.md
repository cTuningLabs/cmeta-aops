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
cx host ls [--tags=ubuntu] [--machine=my-pc] [--type=ssh] [--status|--active]
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
cx host ssh <host> [--x11] [--forward=1455,8080:80] [--dry_run]   interactive shell (also: shell, login)
cx host up|down <host>                WSL distro, container (created from its image on the first up), or "commands: up/down"
cx host restart <host> [--yes] [--no-wait] [--timeout=600] [--skip_after] [--dry_run]   (also: reboot)
cx host sync [host|selection] [--repos=a,b] [--resync [--resync_mode=newer|path1|path2]] [--unlock] [--dry_run] [--skip_after]
cx host push <host> <repo> --dirs=task/x/,tool/y/ [--dry_run] [--delete] [--index-]   then "cx --reindex" on the host (a second), so a new artifact is found there
cx host push <host> <local path> --to=<remote path>      a folder goes under --to, a single file lands AT --to (rclone copyto)
cx host pull <host> <remote file or folder> [--to=<local folder>] [--files=*.jsonl,steps.txt] [--dry_run]   the other way: host -> here (rclone copy --from_remote of rclone-to-ssh); nothing here is deleted
                                      (push and pull with -q set rclone up again when the cMeta cache was cleaned)
cx host upgrade [host|selection] [--version=0.33.0] [--sync] [--restart [--yes] [--timeout=600]] [--dry_run]
                                      (sync, upgrade and restart probe the host again afterwards: "cx host ls" shows what is there now)
cx host upgrade <host> [--engine-] --system [--firmware] [--check]   the OS packages (and firmware) too: "cx task run upgrade-os" on the host
```

## Status: what is checked, and how long it takes

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
                               # a reference whose artifact is not on this machine falls back to ~/.ssh/<file name>
  port: 22                     # optional
  options: "-o ..."            # extra ssh flags, optional
  x11: true                    # ssh -X for "cx host ssh", optional
  shell: bash -l               # bash -l (default) | sh | powershell | cmd | none - wraps every command
  distro: ubuntu-24.04-on-usb-x        # wsl
  container: cmeta-ubuntu24-amd64            # docker (+ image, keepalive, run_args for the first "up")
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
  after: [cx --reindex]        # run on the host after a sync that did something

commands:                      # optional
  up: az vm start ...          # run locally: a cloud VM, a service
  down: az vm deallocate ...
  restart: ...                 # run locally, instead of the default reboot command
  after_restart:               # run ON THE HOST once it answers again (servers); let ssh return:
    - setsid nohup ~/work/start-server.sh > ~/cmeta-tests/server.log 2>&1 < /dev/null &

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
old `_7-resync-*.bat` did. A partial sync is always a one-way **push** (`rclone copy` with an anchored
whitelist), never a filtered bisync: rclone's listings go stale when the filter changes between runs.

`--dry_run` shows what would move and changes nothing (rclone `--dry-run`, `git fetch --dry-run`).

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

**Docker** (`type: docker`, `access: {container, image, keepalive, run_args, user, shell}`): `status` =
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
with the host artifacts, `cx`, `rclone` (set up by the first sync) and the keys - as the `fgg.crypt`
artifacts, or copied into `~/.ssh` under the same file names (the fallback).
