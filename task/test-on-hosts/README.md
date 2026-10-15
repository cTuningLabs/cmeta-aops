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
```

## Launch

The parameters:

- **`--cmds`:** the commands, separated by `;`. Each one is the words after `cx`. A command that starts with `!` is
  a shell line of the host (bash, or cmd on Windows), with `TREE`, `WORK` and `CMETA_HOME` set, for example
  `!uv run --no-project --with pytest ... python -m pytest $TREE/tests`.
- **`--hosts`:** host aliases separated by `,`. `here` is this machine. The default is the key `hosts` of the
  config artifact `task-test-on-hosts` (`cx config set task-test-on-hosts --meta.hosts=a,b,c`: the test machines of
  a fleet, never a production host), else `here`.
- **`--tree`:** the repository folder that is tested. The default is the local clone of `ctuninglabs@cmeta-aops`,
  as it is now, released or not.
- **`--id`:** the name of the round. The default is the time; the other actions need it.

How it runs:

- The tree is packed once (without `.git` and caches). It is pushed with `runner.py` to `~/cmeta-tests/test-on-hosts-<id>/`
  of each host and started there with `nohup python3 runner.py`, so a dropped ssh connection does not stop it.
- `here` runs the same runner on this machine, detached, with the tree folder as it is.
- The runner gives each host a throwaway home (`<root>/home`) and plugs the tree into it. It runs each command in
  `<root>/work`, writes `step-<n>.log` and a line of `steps.txt` per command, then `DONE`.
- The host's own home, cache and repositories are never touched.

## Peek, collect, remove

- **peek:** for each host, `done <time>` or `running`, then the steps with their exit codes and seconds.
- **collect:** the work folder of each host goes into `<to>/<host>`; `--files` keeps only some files. The default
  `<to>` is the round's local folder plus `collected`. For the verdicts of explorations, promote them with
  `cx task run explore-tool-versions --promote --verdicts=<to>`.
- **remove:** the round's folder on each host is removed, and here the `here` copy.

The round's local folder is `test-on-hosts-<id>` in the sandbox of the shell's test session (`CMETA_TEST_SESSION`),
else in the current directory. It holds the tarball, the generated launcher and peek scripts, and the collected
results.
