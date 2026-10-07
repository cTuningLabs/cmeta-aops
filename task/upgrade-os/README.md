# upgrade-os — the OS packages and firmware, with the OS's own commands

`cx task run upgrade-os` brings the operating system's packages up to date the way the OS does it,
chosen from what cMeta's host task already detected: the package manager of a Linux distribution,
`softwareupdate` and Homebrew on macOS, `winget` on Windows. It then says whether the OS wants a
reboot. Firmware is a switch (`--firmware`: fwupd on Linux; macOS and Windows deliver firmware through
their system updates).

```bash
cx task run upgrade-os                           # the OS packages, then brew / winget apps
cx task run upgrade-os --check                   # only list what would be upgraded
cx task run upgrade-os --firmware                # also the firmware (fwupd on Linux)
cx task run upgrade-os --full --autoremove       # apt: dist-upgrade, then drop what nothing needs
cx task run upgrade-os --reboot                  # reboot at the end when the OS asks for it
cx task run upgrade-os --dry_run                 # print the commands, run nothing
```

## What runs where

| OS | system (`--system`, default on) | apps (`--apps`, default on) | `--firmware` | reboot due? |
|---|---|---|---|---|
| Debian, Ubuntu (apt-get / apt) | `update`, `-y upgrade` (`--full`: `dist-upgrade`), `--autoremove` | Homebrew on Linux when present | `fwupdmgr refresh --force`, `fwupdmgr update -y` | `/var/run/reboot-required` |
| Fedora, RHEL (dnf / yum) | `dnf -y upgrade --refresh`, `--autoremove` | the same | the same | `needs-restarting -r` |
| openSUSE (zypper) | `refresh`, `--non-interactive update` | the same | the same | `zypper needs-rebooting` |
| Arch (pacman), Alpine (apk), Void (xbps) | `pacman -Syu --noconfirm`, `apk update` + `apk upgrade`, `xbps-install -Syu -y` | the same | the same | - |
| macOS | `softwareupdate -ia` (root) | `brew update && brew upgrade` | in the system updates | the output of softwareupdate |
| Windows | Windows Update only with `--windows_update` (PSWindowsUpdate, elevated) | `winget upgrade --all` | through Windows Update | the `RebootRequired` registry key |

`--check` runs the listing of each row instead (`apt list --upgradable`, `dnf check-update`,
`softwareupdate -l`, `brew outdated`, `winget upgrade`, `fwupdmgr get-updates`), which needs no root
except apt's index refresh.

## Root and sudo

The system steps run with `sudo -n` (never a hidden prompt) unless the run is interactive (a terminal
and not `-q`), where `sudo` may ask once. Without passwordless sudo a non-interactive run says so and
stops - over ssh, add a `NOPASSWD` rule for the user, or run it in a terminal on the machine. A root
shell needs no sudo. Windows needs an elevated shell only for `--windows_update`.

## On a fleet

A fleet command can run this task on each host through its shell (`cx task run upgrade-os -q
[--firmware] [--check]`), read the `upgrade-os:` verdict line and reboot the hosts that ask for it.

## Result

`os`, `package_manager`, `steps` (`name`, `cmd`, `returncode`), `reboot_required` (`true`, `false`,
or `null` when the OS does not say), and `return 1` with the names of the failed steps unless
`--ignore_errors`. Nothing is cached: every run is a real run.
