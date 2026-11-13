# lid-close-action

What closing a laptop's lid does. A laptop that is reached from elsewhere, say over Tailscale while you travel,
must keep running with its lid closed. The usual setting sends it to sleep or hibernation, and then nothing reaches
it until someone opens the lid.

```bash
cx task run lid-close-action                         # status: what closing the lid does now, on AC power and on battery
cx task run lid-close-action disable                 # closing the lid does nothing, while on AC power
cx task run lid-close-action disable --power=both    # ... on battery too
cx task run lid-close-action enable                  # what it did before the disable, again
cx task run lid-close-action enable --to=hibernate   # Windows, with nothing kept from a disable: this action (default: sleep)
```

`--power` is `ac` by default. A laptop that keeps running with its lid closed on battery, in a bag for instance,
empties its battery and heats up. `--power=both` makes it so on battery too; `--power=battery` changes the battery
setting alone.

## Windows

The lid action of the active power plan, the one `powercfg` shows as `LIDACTION`: 0 nothing, 1 sleep, 2 hibernate,
3 shut down. `disable` keeps the values it replaces in `log::local:lid-close-action` (`previous.json`), and
`enable` puts them back. With nothing kept, `enable` sets `--to` (sleep by default). When Windows refuses the change
to a console that is not an administrator's, the task asks Windows for one (UAC), once.

## Linux

systemd-logind decides, from `HandleLidSwitch` (on battery) and `HandleLidSwitchExternalPower` (on AC power; empty:
as on battery). `disable` writes a drop-in file of this task, `/etc/systemd/logind.conf.d/50-cmeta-lid-close-action.conf`,
with sudo. `enable` removes it, and the settings of the system apply again. logind is asked to read its configuration
again (`systemctl reload systemd-logind`) when it can. The task never restarts logind, since a restart may end the
graphical session; an older logind takes the change at the next restart of the machine. `status` also names the
programs that hold the lid switch (`systemd-inhibit --list`): while one runs, it decides.

## macOS

macOS has no lid action of its own: closing the lid of a MacBook puts it to sleep, unless it runs with an external
display. `disable` runs `pmset -a disablesleep 1` (sudo), which keeps the whole machine from sleeping, on every power
source, and keeps the value it replaced. Since that switch governs all the sleep of the machine, `enable` puts back
only what this task changed; a `disablesleep` set otherwise (by `prevent-mac-to-sleep`, by hand) stays, unless
`--to=sleep` asks for 0.
