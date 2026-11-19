# start-after-restart

Keep the servers of this machine: start them after every restart, before anyone logs in, and start or stop them now.
A server is the cMeta server (`cserver`), the ssh server, or any server the host artifact of this machine declares.
You can then reach the machine over Tailscale from elsewhere: its pages, a shell, and a way to restart things.

```bash
cx task run start-after-restart                                    # status: enabled? running? the last lines of its log
cx task run start-after-restart enable --what=cserver,ssh          # ssh: the fleet's key for this machine (cx host whoami)
cx task run start-after-restart enable --what=cserver              # the cserver alone
cx task run start-after-restart enable --what=cserver --workdir=D:\Work   # started in that folder (default: the user's)
cx task run start-after-restart enable --what=my-server            # a server the host artifact declares (server: run)
cx task run start-after-restart disable --what=cserver,ssh         # nothing starts after a restart any more (those running keep running)
cx task run start-after-restart off --what=cserver                 # the switch: registered as before, but a restart passes it over
cx task run start-after-restart on --what=cserver                  # ... and it starts after a restart again
cx task run start-after-restart on --what=cserver --at=login       # Windows: at your login, in a window (no administrator)
cx task run start-after-restart off --what=cserver --at=login      # ... no longer at login
cx task run start-after-restart start --what=cserver,ssh           # now, the way a restart starts them
cx task run start-after-restart start --what=cserver --window      # now, in a console window of its own (Windows)
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
- **A server the host artifact declares.** Any other `--what=<name>` is a project of the host artifact this machine
  is (`cx host whoami`) whose server block says how to run it in the foreground:

  ```yaml
  projects:
    my-server:
      server:
        url: http://127.0.0.1:8401/health                  # where it answers: status asks it there
        run: cxt run-my-server --foreground                # its command in the foreground: the task keeps it
        workdir: 'D:\Work'                                 # optional: the folder it starts in
  ```

  A command that begins with `cx`, `cxt` or `cmeta` is run by the Python cMeta runs on (a restart has no PATH to find
  the launchers with), with `-q` added: a supervisor has no terminal, so a question of the command (which of several
  tools or models to take) would wait forever. Any other command goes to the system's shell as it is written. The
  command is read from the artifact at each start, so a change of the artifact needs no new `enable`. A project named
  `cserver` or `ssh` that declares `run` takes the place of the task's own server of that name. The hosts page of
  the cserver and `cx host up|down|autostart <host> --project=<name>` work through these commands.

**The folder they start in.** `--workdir=<folder>` is the current folder of the supervisor and of the servers it
starts (default: the user's folder, where cron starts its jobs too; for a declared server, the `workdir` of its
declaration). It must exist when you `enable` or `start`; `status` shows the folder of the registered start. Two
things keep their own folder whatever it is: `cx app run` runs the cserver's web server from its app folder, and
OpenSSH begins every login in the user's folder.

## The switch: off and on

`enable` registers the start after a restart and `disable` removes it. On Windows both need an administrator.
`off` and `on` need none: `off` keeps the registered start and makes a restart pass it over, `on` makes it a
restart's again, as it was registered. Use them to turn the start after a restart off for a while.

- `off` stops nothing: a server that runs keeps running. `start` starts it whatever the switch says.
- `on` of a server that is not registered yet is `enable`, with the settings of its command line.
- `enable` also switches on; `disable` removes the switch with the registration.
- `status` says `ENABLED`, `registered, but SWITCHED OFF` or `not enabled`.

## At login, in a window (Windows)

A start after a restart runs in the session without a login. A server started there has no desktop, so what it opens
shows nowhere: Far, a shell or a folder opened from the cserver's pages (/browse, the AI gateway page). `--at=login`
starts the server when you log in instead, in a console window of its own, in your session:

```bash
cx task run start-after-restart on --what=cserver --at=login       # (or enable --at=login)
cx task run start-after-restart off --what=cserver --at=login      # no longer at login
```

- It is a value of your own Run key (`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`, named
  `cMeta <server> at login`). The value runs `<server>.login.cmd` beside the logs. No administrator is asked, also
  from a page served in the session without a login.
- One or the other. The start at login switches the start after a restart off (`<server>.off`; the registered task is
  kept). `on` or `enable` without `--at=login` removes the start at login. `off` without `--at` removes both.
- The window is titled after the server: closing it, or Ctrl-C in it, stops the server. Until then the supervisor
  keeps the server as after a restart (it starts it again when it ends), and `stop` stops it.
- `status` says `at login: ON`. `cx host autostart <host> login --project=<name>` and the hosts page's "AutoStart at
  Login (window)" button switch it.
- Linux and macOS: not built; a server starts at the boot there (crontab `@reboot`), and `--at=login` is refused.

## How it runs

Each server runs under a supervisor, the `run` action of this task:

1. It moves into `--workdir`. If that folder is gone since the `enable` (renamed, its drive missing), it logs a
   warning and stays in the user's folder: a restart never leaves the machine unreachable over a folder.
2. It waits until the Tailscale address exists, for `--wait` seconds (600 by default). A server started before that
   would listen on 127.0.0.1 only. A declared server waits only when its URL is on the Tailscale address.
3. It starts the server in the foreground.
4. If the server ends, it starts it again 30 s later.
5. It stops when `stop` asks it to: it ends its server and everything that one started, then goes. `disable` and
   `off` leave it running: they only change the start after a restart.

Because the supervisor ends its own server, whoever asks for the stop needs no right over these processes. A
console that is not an administrator's, or a page served from another session, can stop a server that was started
without a login. Only a supervisor that does not go within 15 s (or one started by a version before 0.75.1) is ended
by the `stop` command itself, as before.

The logs and records live in the log artifact `log::local:start-after-restart`:

| file | what |
|---|---|
| `<server>.log` | the supervisor and the server |
| `<server>.boot.log` | what the start printed before the supervisor took over |
| `<server>.json` | the supervisor's process number and start time, whether it runs in a window |
| `<server>.off` | the switch: the registered start is passed over by a restart |
| `<server>.login.cmd` | what your Run key starts at login (Windows, `--at=login`) |

**Windows.** One startup task per server in the Task Scheduler, in the folder `\cMeta\`, named
`cMeta <server> after restart`. It starts 30 s after the boot, as the user who enabled it, with no login and no stored
password (S4U). It runs on battery too, with no time limit, and has no window. Its "Start in" is the user's folder,
which always exists (a missing one would stop the task from starting); `--workdir` is on its command line.
Registering or removing such a task needs an administrator: from a console that is not one, `enable` and `disable`
ask Windows for one (UAC). In the session without a login Windows has no desktop to ask on: `enable` says so there
and names the command to run once in a terminal of the machine.
The machine needs:

- Tailscale unattended (`tailscale set --unattended=true`);
- the drive of the cMeta home readable before a login: BitLocker auto-unlock, or no BitLocker.

`status` reports both.

**Linux and macOS.** A line in the user's crontab, `@reboot`, marked `# cmeta start-after-restart <server>`. cron
starts it as the user at the boot, with the home and a PATH of its own. The other lines of the crontab stay as they
are. A cron daemon must run; on macOS, cron may need Full Disk Access to read a home on an external drive.

## A start now

`start` runs what a restart runs: on Windows the registered task, on Linux and macOS the crontab line, without the
wait after the boot. The settings of `enable` apply, not those of the `start` command line. Only when nothing is
enabled does `start` use its own command line.

On Windows a server that is not registered is started by the system as a process of its own, without a window. It
then belongs to no job of the command that asked. A command that is run with a time limit (`cx host up --project`,
the Start button of the hosts page) ends everything it started as its children when it returns, so a server started
as a child would be gone a second later. Such a process gets the account's own environment, as after a restart, not
the variables of the console that asked.

`start --window` (Windows) starts the server in a console window of its own, on the desktop of the session that
asked, also when it is registered. The supervisor's lines and the server's output show in the window; they are not
in the log then. Closing the window, or Ctrl-C in it, stops the server. A start after a restart never has a window,
and a command that runs in the session without a login has no desktop to show one on.

`status --quick` says what is registered and what runs, and nothing else: no port is asked and the machine is not
looked at. `cx host autostart` asks it for all the kept servers of a host at once.

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

`--name=<n>` makes a second set with its own tasks, logs and ports, for tests. It is always of the task's own
cserver and ssh, never of a declared server.
