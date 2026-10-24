# GNU Screen

Detect GNU Screen or install it with the Linux distribution's package manager or Homebrew on macOS.
Screen keeps terminal programs running after their SSH connection closes. It runs on the target POSIX host;
a Windows client can connect through cMeta.

```console
cx tool run screen -- --version
cx host ssh my-host --screen
cx host ssh my-host --screen=work
cxt run-ai --project="work::my-project" --on=my-host --on_screen
```

The shell defaults to the screen name `cx-host`; run-ai defaults to `run-ai`. An explicit name selects another
session. Repeating a command reconnects to an existing screen without starting its command again. `Ctrl-a d`
detaches; exiting the shell or finishing the task closes its last window and ends the screen. Sessions survive
client disconnections, including laptop hibernation; they do not survive a reboot of the target host.

The tool takes whatever Screen is installed, of several copies the newest: macOS's own `/usr/bin/screen` (4.00.03,
whose `-v` exits 1 - `cmd_get_version_exit_codes` in `_desc.yaml`) as well as Homebrew's (`brew install screen`, which
the setup offers when no Screen is found). The persistent terminals (`cx host ssh --screen`, `--on_screen`) work with
any version; with 4.2 or later they also list the windows of an existing session (`-Q`) before attaching.

Screen installed through a package manager is removed with that package manager. Removing a cMeta setup cache
entry only removes its detection record.
