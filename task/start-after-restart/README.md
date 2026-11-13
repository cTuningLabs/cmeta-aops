# start-after-restart

Start a cMeta server (`cserver`) and an ssh server of this machine after every restart, before anyone logs in. You
can then reach the machine over Tailscale from elsewhere: its pages, a shell, and a way to restart things.

```bash
cx task run start-after-restart                                    # status: enabled? running? the last lines of its log
cx task run start-after-restart enable --what=cserver,ssh          # ssh: the fleet's key for this machine (cx host whoami)
cx task run start-after-restart enable --what=cserver              # the cserver alone
cx task run start-after-restart enable --what=cserver --workdir=D:\Work   # started in that folder (default: the user's)
cx task run start-after-restart disable --what=cserver,ssh         # nothing starts after a restart any more (those running stop)
cx task run start-after-restart start --what=cserver,ssh           # now, the way a restart starts them
cx task run start-after-restart stop --what=cserver,ssh
```

## What starts

- **cserver**: `cx app run cserver --param.host=tailscale --param.port=8004`. It listens on the machine's Tailscale
  address, behind the sign-in its `cserver` config sets: a password, and `login_mfa` for a code by mail.
  `--cserver_host` and `--cserver_port` change the address and the port.
- **ssh**: `cx task run run-openssh --host=<ssh_host> --foreground`, the OpenSSH server run as the user. It allows key
  logins only, on port 2222 of the Tailscale address. It allows the key the fleet reaches this machine with: that of
  the host artifact this machine is, found by `cx host whoami`, or named with `--ssh_host`. With no host artifact for
  the machine, the keys of `~/.ssh/authorized_keys` are allowed.

**The folder they start in.** `--workdir=<folder>` is the current folder of the supervisor and of the servers it
starts (default: the user's folder, where cron starts its jobs too). It must exist when you `enable` or `start`;
`status` shows the folder of the registered start. Two things keep their own folder whatever it is: `cx app run`
runs the cserver's web server from its app folder, and OpenSSH begins every login in the user's folder.

## How it runs

Each server runs under a supervisor, the `run` action of this task:

1. It moves into `--workdir`. If that folder is gone since the `enable` (renamed, its drive missing), it logs a
   warning and stays in the user's folder: a restart never leaves the machine unreachable over a folder.
2. It waits until the Tailscale address exists, for `--wait` seconds (600 by default). A server started before that
   would listen on 127.0.0.1 only.
3. It starts the server in the foreground.
4. If the server ends, it starts it again 30 s later.
5. It stops when `stop` or `disable` asks it to.

The logs and records live in the log artifact `log::local:start-after-restart`:

| file | what |
|---|---|
| `<server>.log` | the supervisor and the server |
| `<server>.boot.log` | what the start printed before the supervisor took over |
| `<server>.json` | the supervisor's process number and start time |

**Windows.** One startup task per server in the Task Scheduler, in the folder `\cMeta\`, named
`cMeta <server> after restart`. It starts 30 s after the boot, as the user who enabled it, with no login and no stored
password (S4U). It runs on battery too, with no time limit. Its "Start in" is the user's folder, which always exists
(a missing one would stop the task from starting); `--workdir` is on its command line. Registering or removing such
a task needs an administrator: from a console that is not one, `enable` and `disable` ask Windows for one (UAC). The
machine needs:

- Tailscale unattended (`tailscale set --unattended=true`);
- the drive of the cMeta home readable before a login: BitLocker auto-unlock, or no BitLocker.

`status` reports both.

**Linux and macOS.** A line in the user's crontab, `@reboot`, marked `# cmeta start-after-restart <server>`. cron
starts it as the user at the boot, with the home and a PATH of its own. The other lines of the crontab stay as they
are. A cron daemon must run; on macOS, cron may need Full Disk Access to read a home on an external drive.

`start` runs what a restart runs: on Windows the registered task, on Linux and macOS the crontab line, without the
wait after the boot. The settings of `enable` apply, not those of the `start` command line. Only when nothing is
enabled does `start` use its own command line.

**One supervisor per server.** A second one, started while the first runs, logs that and ends at once. On macOS
this happens after `enable`: launchd starts cron when a crontab changes for the first time after a boot, and cron
runs the `@reboot` lines then. So the server starts within a minute of the `enable` on macOS too.

**macOS and network permissions.** macOS may keep a server run by a Python that does not come with it (uv's,
Homebrew's) from getting connections on the Tailscale address, while Apple's own programs (sshd, `/usr/bin/python3`)
get them: the kernel takes the connection, the program never sees it. `status` tells this apart. It asks the cserver
for an HTTP answer and the ssh server for its banner, and says "takes the connection but answers nothing" when only
the connection works. Allow that Python on the network in the Mac's settings (Privacy & Security, Local Network; the
firewall) and check again; the ssh server is not affected.

**Stale records.** A process number kept in a file is trusted only while the record was written after the last boot
and the process did not start after it. After a restart the numbers are given out again, so a stale record is never
"running" and never stopped. The same rule applies to every task that records a process.

`--name=<n>` makes a second set with its own tasks, logs and ports, for tests.
