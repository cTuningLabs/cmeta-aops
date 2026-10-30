# test-on-hosts: cx commands on several hosts at once, in throwaway homes

`cx task run test-on-hosts` runs cx commands on several hosts at once, each in a throwaway cMeta home with a
repository's tree plugged in, then shows how they go, collects their results here and removes their folders. It is
how a self-test or an exploration runs on the fleet. It works through `cx host` only, never hand-written ssh or
scp: `push -q`, `run --script` and `pull -q`.

```
cx task run test-on-hosts --cmds="task run explore-tool-versions yq;tool check-updates"            # launch, round id printed
cx task run test-on-hosts --cmds="..." --hosts=lab-laptop-ubuntu,lab-mac-mini-macos,here --id=yq1  # hosts and id chosen
cx task run test-on-hosts --action=peek --id=yq1 [--hosts=...]                                     # running or done, the steps
cx task run test-on-hosts --action=collect --id=yq1 [--files=*.jsonl] [--to=<folder>]              # the results here
cx task run test-on-hosts --action=remove --id=yq1                                                 # the hosts' folders removed
cx task run test-on-hosts --cmds="task run test-python -q" --hosts="docker:ubuntu,docker:debian,wsl,lab-laptop-ubuntu"   # a matrix of OS images and hosts
```

## Launch

The parameters:

- **`--cmds`:** the commands, separated by `;`. Each one is the words after `cx`. A command that starts with `!` is
  a shell line of the host (bash, or cmd on Windows), with `TREE`, `WORK` and `CMETA_HOME` set, for example
  `!uv run --no-project --with pytest ... python -m pytest $TREE/tests`.
- **`--hosts`:** host aliases separated by `,`. `here` is this machine. The default is the key `hosts` of the
  config artifact `task-test-on-hosts` (`cx config set task-test-on-hosts --meta.hosts=a,b,c`: the test machines of
  a fleet, never a production host), else `here`. A ref of the run-on-any-host design - `docker:ubuntu`,
  `podman:debian`, `wsl`, with `--on_*` words after it (`docker:ubuntu --on_template.os_version=24.04`) - is the
  instance of that template on this machine, made on first use (`get-host--docker`, `get-host--wsl`): the round
  runs inside it, and when the tree is the repository the instance carries, nothing is pushed - the runner reads
  it where it is mounted. An instance made this way stays (`cx host ls --made`, `cx host destroy <instance>`).
  A ref whose instance cannot be made (an image that does not build) is said and left out: the rest of a matrix
  runs. The launch records the round in `round.json` of its local folder (the hosts, the instances, the refs that
  failed): peek, collect and remove without `--hosts` take the hosts from there.
- **`--tree`:** the repository folder that is tested. The default is the local clone of `ctuninglabs@cmeta-aops`,
  as it is now, released or not.
- **`--id`:** the name of the round. The default is the time; the other actions need it.

How it runs:

- The tree is packed once (without `.git` and caches). It is pushed with `runner.py` to `~/cmeta-tests/test-on-hosts-<id>/`
  of each host and started there with `nohup <python> runner.py`, so a dropped ssh connection does not stop it. The
  Python is the host's `python3`, else the one its `cx` runs on (`cx --version`): a bare container has no system
  Python. A container or WSL distribution that declares no `access.user` takes the files under its own user's home
  (`cx host push` asks it for `$HOME`; before 2026-10-30 they landed under `/` and the round never started).
- A Windows host (its access shell PowerShell or cmd, or `os: windows`) gets PowerShell instead of bash: the runner
  is started through WMI (`Win32_Process.Create`, a process the ssh session does not take along when it ends) with
  the Python its `cx` runs on, and its commands go in `commands.json` next to the runner, out of reach of cmd.exe's
  quoting. Peek and remove are PowerShell there too.
- `here` runs the same runner on this machine, detached, with the tree folder as it is, in
  `<here_dir>/test-on-hosts-<id>/`: the key `here_dir` of the config artifact `task-test-on-hosts`, else
  `~/cmeta-tests` as on a remote host (`cx config set task-test-on-hosts --meta.here_dir=D:\cmeta-tests`). Keep it
  short on Windows: MSVC writes no file beyond 260 characters, and a round's home inside a test session's sandbox
  was too deep for a CMake build. The launch records the folder in `round.json`.
- The runner gives each host a throwaway home (`<root>/home`) and plugs the tree into it. It runs each command in
  `<root>/work`, writes `step-<n>.log` and a line of `steps.txt` per command, then `DONE`.
- The host's own home, cache and repositories are never touched.

## Peek, collect, remove

- **peek:** for each host, `done <time>`, `running` (its runner's process is there), `stopped` (the runner ended
  before its last command) or `not started` (with the launch's own reason, and the end of `run.out`), then the steps
  with their exit codes and seconds. The round is `done everywhere`, `still running somewhere`, or `finished - not
  done on <hosts>` when nothing runs any more (before 2026-10-30 a runner that never started was `running` for ever).
  The result carries `done`, `finished` and each host's `state`.
- **collect:** the work folder of each host goes into `<to>/<host>`; `--files` keeps only some files. The default
  `<to>` is the round's local folder plus `collected`. For the verdicts of explorations, promote them with
  `cx task run explore-tool-versions --promote --verdicts=<to>`.
- **remove:** the round's folder on each host is removed, and here the `here` copy.

The round's local folder is `test-on-hosts-<id>` in the sandbox of the shell's test session (`CMETA_TEST_SESSION`),
else in the current directory. It holds `round.json`, the tarball, the generated launchers and the collected
results; peek, collect and remove look for it there (from another directory they say where they looked, and make
nothing). This machine's part runs in `here_dir` (above), which `round.json` names.
