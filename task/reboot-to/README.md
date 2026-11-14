# reboot-to

Restart this machine into another system of its firmware's boot menu - Windows, Ubuntu, any other - once or always,
on Windows and Linux: the same command on each system of a dual-boot machine.

```bash
cx task run reboot-to                       # the systems, numbered: asks which one, then whether to restart
cx task run reboot-to ubuntu                # restart into ubuntu once: the start after it is the usual one again
cx task run reboot-to windows --always      # Windows first in the boot order, then a restart
cx task run reboot-to --list                # the systems and the word --os takes for each (--all: every boot entry)
cx task run reboot-to ubuntu --reboot=no    # only set the next start; restart later
cx task run reboot-to --cancel              # take back a "once" that was set
cx task run reboot-to ubuntu --dry_run      # what it would do; nothing changes
```

`cxt reboot-to ubuntu` is the same as `cx task run reboot-to --os=ubuntu`.

## Which system: --os

`--list` shows what the firmware starts, in its boot order, and the word of `--os` that names each one:

```text
  0)  Windows Boot Manager  --os=windows  Boot0000  \EFI\Microsoft\Boot\bootmgfw.efi on partition 1 {1a2b3c4d}  booted this session, first in the boot order
  1)  ubuntu                --os=ubuntu   Boot0001  \EFI\ubuntu\shimx64.efi on partition 1 {1a2b3c4d}

Next restart: Windows Boot Manager (Boot0000), the first in the boot order (no "once" is set).
```

"Booted this session" is the entry the firmware started this time (`BootCurrent`); "Next restart" says what the next
one starts. `--os` takes, by the first rule that finds any: the entry itself (`Boot0001`, or `0001`), the name,
`windows` or `linux`, a part of the name - ignoring case. Entries that start the same loader on the same partition are
one system (Windows makes a new entry after a firmware update or a repair and the old one stays): the first in the boot
order is taken. Two different systems of the same name, say two Ubuntu on two disks, are told apart by their entry,
which the list shows with the partition of each loader (on Linux its device, `nvme0n1p1`).

Without `--os` the task shows the list and asks for a number (Enter: none). The list holds the systems, a loader file
on a disk; `--all` adds the other entries of the firmware: network starts, USB, its own applications, the firmware
updater of Linux.

## Once or always

- **Once** (the default): the firmware's `BootNext`. The firmware starts that entry at the next start and forgets
  it; the start after it follows the boot order again. If that system does not start, the next restart brings back
  the usual one. `--cancel` takes it back before a restart.
- **Always** (`--always`): the firmware's `BootOrder`, with the entry moved first and the others kept in their order.
  A "once" set to another entry is taken back, or it would start next. A Windows update sometimes puts Windows Boot
  Manager first again: run it again. If the order does not change at all, or comes back after a restart although the
  task read it changed, a BIOS setting may lock it (on some laptops a "Boot Order Lock" setting must be off) -
  the once works either way, and on Linux `--grub --always` decides in GRUB instead.

The task asks before restarting ("Restart ... into ubuntu (Boot0001), once? [y/N]"); `--yes` restarts without the
question, and a run without a terminal needs it. `--reboot=no` sets the entry and does not restart. The restart is the
task `reboot`'s (Linux: `systemctl reboot -i`, which ignores the session's inhibitors; Windows: `shutdown /r`), and
`--delay_seconds` delays it.

## Administrator rights

- **Windows:** only an administrator reads or changes the firmware's boot entries (the privilege
  SeSystemEnvironmentPrivilege; `bcdedit /enum firmware` needs it too). From a console started with "Run as
  administrator" nothing is asked. From any other console Windows asks (UAC) for the helper that reads or changes
  them: once for the list, once more for the change - once in all when `--os` names the system.
- **Linux:** everyone reads the boot entries; root changes them. The task runs the helper with `sudo`, without a
  question when it can, else sudo asks for the password in the terminal.

The helper is `uefi_boot.py` of this task, the standard library only. Nothing else of the task runs with those
rights.

## BitLocker and Secure Boot

The firmware starts the chosen entry's loader itself, as at any start - Windows Boot Manager for Windows, shim and
GRUB for Ubuntu - so BitLocker measures nothing new and asks for no recovery key, and Secure Boot checks what it always
checks. The task never starts Windows through GRUB's menu, nor with `grub-reboot`: a chainload through shim and GRUB
changes what is measured and can make BitLocker ask for the recovery key.

## Through GRUB: --grub (Linux)

On a machine where GRUB starts every system - its menu shown a few seconds at each boot, its default the system one
uses most - the choice belongs in GRUB rather than in the firmware:

```bash
cxt reboot-to --grub --list                  # GRUB's menu, its default, the next boot, how long the menu shows
cxt reboot-to windows --grub                 # once: grub-reboot - the next boot starts Windows, then the default again
cxt reboot-to windows --grub --always        # GRUB's default is Windows from now on (grub-set-default)
cxt reboot-to ubuntu --grub --always         # ... and Ubuntu again
cxt reboot-to --grub --grub_timeout=5        # its menu shown 5 s at every boot (0: hidden)
cxt reboot-to --grub --cancel                # take back a once
```

- **Once** sets GRUB's `next_entry` (`grub-reboot`), which `grub.cfg` honours whatever `GRUB_DEFAULT` is.
- **Always** sets GRUB's `saved_entry` (`grub-set-default`), which counts with `GRUB_DEFAULT=saved`: the first time,
  `/etc/default/grub` is changed to it (the old file kept beside it, `grub.default.cmeta-reboot-to-<time>`) and
  `update-grub` makes `grub.cfg` again. `--grub_timeout` changes `GRUB_TIMEOUT_STYLE` / `GRUB_TIMEOUT` the same way.
- Entries are named by their id (`osprober-efi-...`, `gnulinux-simple-<uuid>`), which stays when kernels change.
- When the firmware would not start GRUB next (Windows Boot Manager first in its order), the task also sets it to
  (`BootNext` for once, the boot order for always), so GRUB runs.
- `--grub` is `--via=grub`. A machine that always chooses this way says so once:
  `cx config set task-reboot-to --meta.via=grub`; then `--via=firmware` for the firmware's way.
- From Windows GRUB's files are out of reach (the Linux partition): there the firmware's way only.

GRUB then starts Windows by chaining its boot manager. On most machines BitLocker sees nothing new (Secure Boot's
measurement, PCR 7, stays); where it asks for the recovery key after such a start, the firmware's way avoids it.

## GRUB's own default

A Linux entry starts GRUB (through shim), and GRUB then starts its own default entry. When that default is Windows
(GRUB's menu lists Windows through os-prober), a once into Ubuntu ends in Windows: the firmware did start GRUB, as the
list shows afterwards ("booted this session" on the Ubuntu entry while Windows runs, and a line under the list that
says so). Make Ubuntu GRUB's default, on Ubuntu:

```bash
grep -E '^GRUB_(DEFAULT|SAVEDEFAULT|TIMEOUT)' /etc/default/grub     # what GRUB does now
sudo sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=0/' /etc/default/grub   # the first entry: Ubuntu
sudo update-grub
```

With `GRUB_DEFAULT=saved` and `GRUB_SAVEDEFAULT=true`, GRUB starts what was chosen in its menu the last time, so a
Windows chosen there once becomes the default. To start Windows, prefer the firmware (`reboot-to windows`, which
starts Windows Boot Manager directly) over GRUB's menu.

## Where it does not apply

A machine that did not start through UEFI - a legacy BIOS start, WSL, a container - has no firmware boot entries, and
the task says so. macOS chooses its startup disk in System Settings.
