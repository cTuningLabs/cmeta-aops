# sync-system-clock — the system clock measured against a time server and put right

`cx task run sync-system-clock` measures how far the system clock is from a time server and whether the time
service that keeps it is running; when the clock is off by more than `--max_offset` seconds (1 by default) or
the service is down, it puts the clock right with the OS's own commands, then measures again.

```
cx task run sync-system-clock                   # measure; fix when the clock is off or the service is down
cx task run sync-system-clock --check           # measure and report only
cx task run sync-system-clock --force           # fix even when the clock looks right
cx task run sync-system-clock --server=pool.ntp.org --max_offset=0.5
cx task run sync-system-clock --check -j        # the result as JSON (offset_seconds, service, ok, fixed)
```

One line says what it found, for example:

```
clock: Windows, w32time running, offset -0.014 s (w32tm against the server, 3 sample(s)) against time.windows.com - OK
clock: WSL2 (a copy of the Windows host's clock), systemd-timesyncd running, offset +6.118 s (...) - OFF by more than 1 s
```

## Per OS

| OS | Measured with | The fix |
|---|---|---|
| Windows | `w32tm /stripchart` against the server, `sc query w32time` | the Windows Time service set to start automatically, started and told to resync — an elevated PowerShell: **expect the administrator prompt (UAC)** |
| Linux | `chronyc tracking` when chrony keeps the clock, else `timedatectl timesync-status`; `timedatectl show` for the service | `timedatectl set-ntp true`, then `systemctl restart systemd-timesyncd` or `chronyc makestep` |
| WSL2 | the same as Linux | `hwclock -s`: the clock is set again from the hardware clock, which is the Windows host's — the lasting fix is the host's time service (run this task on the Windows host) |
| macOS | `sntp <server>` | `sntp -sS <server>` and `systemsetup -setusingnetworktime on` |

Root: the system steps run with `sudo -n` (never a hidden prompt) unless the run is interactive (a terminal,
not `-q`), where sudo may ask once; without passwordless sudo a non-interactive run says so and prints the
commands to run by hand. The offset is reported with the sign the measuring tool prints.

## Why

A clock that is set while programs run — by NTP, by a virtual machine's sync with its host — breaks every
program that compares timestamps: TLS certificates, git, make, Kerberos, file syncs, and timeouts measured on
the wall clock. On 2026-10-12 the clock of WSL2 on a laptop was seen stepping by -3.3 s and +6.2 s every 30 s:
the Windows host's time service was stopped and its clock 6 s off, WSL2 copied it, and the distribution's NTP
kept correcting the copy. cMeta measures its own durations on the monotonic clock since then; this task makes
the fix one command on every machine of a fleet.

## On a fleet

```
cx host run <host> "cx task run sync-system-clock --check"
cx host run --tags=ubuntu "cx task run sync-system-clock -q"
```

This task is never memoized: every run measures.
