"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/upgrade-os: the commands it plans per OS and package manager (from the host task's os_extra), the
sudo rule, --check, --full, --autoremove, --firmware, Windows Update only when asked, and the reboot probes.
Offline: plan() is pure, nothing runs.
"""

import pytest


@pytest.fixture(scope = "module")
def up(task_namespace):
    return task_namespace("upgrade-os")


def names(steps):
    return [s[0] for s in steps]


def cmd_of(steps, name):
    return next(s[1] for s in steps if s[0] == name)


def test_ubuntu_apt(up):
    steps = up["plan"]("linux", {"id": "ubuntu", "package_manager": "apt-get"})
    assert names(steps) == ["update", "mounts aside", "configure", "upgrade", "mounts back", "reboot?"]
    assert cmd_of(steps, "update") == "apt-get update"
    assert cmd_of(steps, "upgrade").endswith(" upgrade") and "DEBIAN_FRONTEND=noninteractive" in cmd_of(steps, "upgrade")
    assert cmd_of(steps, "configure").endswith("dpkg --configure -a --force-confdef --force-confold")
    assert cmd_of(steps, "reboot?") == "test -f /var/run/reboot-required"
    update, aside, configure, upgrade, back, probe = steps
    assert update[2] is True and upgrade[2] is True and probe[2] is False and probe[3] == "reboot?" and probe[4] == (0,)
    assert aside[2] is True and back[2] is True and back[3] == "restore"

    steps = up["plan"]("linux", {"package_manager": "apt-get"}, full = True, autoremove = True)
    assert names(steps) == ["update", "mounts aside", "configure", "upgrade", "autoremove", "mounts back", "reboot?"]
    assert cmd_of(steps, "upgrade").endswith(" dist-upgrade") and cmd_of(steps, "autoremove").endswith(" autoremove")

    # --check: apt refreshes its index (root), then lists; no upgrade, no reboot probe
    steps = up["plan"]("linux", {"package_manager": "apt"}, check = True)
    assert names(steps) == ["update", "check"] and cmd_of(steps, "check") == "apt list --upgradable"

    # root: nothing needs sudo
    steps = up["plan"]("linux", {"package_manager": "apt-get"}, root = True)
    assert all(s[2] is False for s in steps)


def test_other_linux_package_managers(up):
    steps = up["plan"]("linux", {"package_manager": "dnf"})
    assert names(steps) == ["mounts aside", "upgrade", "mounts back", "reboot?"] and cmd_of(steps, "upgrade") == "dnf -y upgrade --refresh"
    assert cmd_of(steps, "reboot?") == "needs-restarting -r" and steps[-1][4] == (1,)
    steps = up["plan"]("linux", {"package_manager": "zypper"})
    assert names(steps) == ["update", "mounts aside", "upgrade", "mounts back", "reboot?"] and steps[-1][4] == (102,)
    assert names(up["plan"]("linux", {"package_manager": "pacman"})) == ["mounts aside", "upgrade", "mounts back"]
    assert names(up["plan"]("linux", {"package_manager": "apk"})) == ["update", "mounts aside", "upgrade", "mounts back"]
    assert names(up["plan"]("linux", {"package_manager": "dnf"}, check = True)) == ["check"]

    # a package manager this task does not know: nothing planned (the run says so)
    assert up["plan"]("linux", {"package_manager": "emerge"}) == []


def test_firmware_and_brew_on_linux(up):
    steps = up["plan"]("linux", {"package_manager": "apt-get", "brew_present": True}, firmware = True)
    assert names(steps) == ["update", "mounts aside", "configure", "upgrade", "mounts back", "reboot?", "brew upgrade",
                            "firmware refresh", "firmware update"]
    assert cmd_of(steps, "firmware update") == "fwupdmgr update -y" and cmd_of(steps, "brew upgrade") == "brew update && brew upgrade"
    assert next(s for s in steps if s[0] == "firmware update")[2] is True            # fwupd needs root over ssh
    steps = up["plan"]("linux", {"package_manager": "apt-get"}, firmware = True, check = True, system = False, apps = False)
    assert names(steps) == ["firmware refresh", "firmware check"] and cmd_of(steps, "firmware check") == "fwupdmgr get-updates"


def test_macos(up):
    steps = up["plan"]("darwin", {"id": "darwin", "package_manager": "brew"})
    assert names(steps) == ["system upgrade", "reboot?", "brew upgrade"]
    assert cmd_of(steps, "system upgrade") == "softwareupdate -ia" and steps[0][2] is True and steps[2][2] is False
    # a prepared macOS update is still listed with "Action: restart": the probe reads the text, without root
    assert cmd_of(steps, "reboot?") == "softwareupdate -l" and steps[1][2] is False and steps[1][4] == "Action: restart"
    steps = up["plan"]("darwin", {}, check = True)
    assert names(steps) == ["system check", "brew check"] and cmd_of(steps, "system check") == "softwareupdate -l" and steps[0][2] is False
    assert names(up["plan"]("darwin", {}, firmware = True, system = False, apps = False)) == []     # firmware is in softwareupdate


def test_windows(up):
    steps = up["plan"]("windows", {"id": "windows", "package_manager": "winget"})
    assert names(steps) == ["apps upgrade"] and cmd_of(steps, "apps upgrade").startswith("winget upgrade --all")
    steps = up["plan"]("windows", {"package_manager": "winget"}, windows_update = True)
    assert names(steps) == ["apps upgrade", "windows update", "reboot?"] and steps[-1][4] == (1,)
    # the script next to the task, run without a question (-NonInteractive) and whatever the execution policy
    wu = cmd_of(steps, "windows update")
    script = up["WINDOWS_UPDATE_SCRIPT"]
    assert wu == f'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{script}"'
    steps = up["plan"]("windows", {"package_manager": "winget"}, check = True, windows_update = True)
    assert names(steps) == ["apps check", "windows update check"] and cmd_of(steps, "windows update check") == wu + " -Check"
    assert all(s[2] is False for s in steps)


def test_the_windows_update_script(up):
    """windows-update.ps1: no question nobody can answer (TLS 1.2 and the NuGet provider before Install-Module), no
    drivers, and the install as SYSTEM in a scheduled task of its own - Windows Update installs nothing for a remote
    session such as ssh ("Access is denied", 2026-10-29) - which is removed when it ends."""
    import pathlib
    text = pathlib.Path(up["WINDOWS_UPDATE_SCRIPT"]).read_text(encoding = "ascii")       # Windows PowerShell reads ANSI
    assert text.index("Tls12") < text.index("Install-PackageProvider -Name NuGet") < text.index("Install-Module PSWindowsUpdate")
    assert "Get-WindowsUpdate -UpdateType Software\n" in text
    assert "Get-WindowsUpdate -UpdateType Software -AcceptAll -Install -IgnoreReboot" in text
    assert "New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\\SYSTEM'" in text and "-AllowStartIfOnBatteries" in text
    assert text.index("Start-ScheduledTask") < text.index("Unregister-ScheduledTask")
    assert "-AsSystem -Log" in text and "$PSCommandPath" in text


def test_a_failed_upgrade_still_puts_the_file_mounts_back(up):
    """The WSL kernel mounts its perf over /usr/bin/perf of linux-tools-common, and dpkg failed on it (2026-10-29): the
    mounts go aside before the upgrade, and back after it even when it fails - then nothing else runs."""
    import types
    ran = []

    def run(line, **kw):
        ran.append(line)
        return {"returncode": 100 if "Dpkg::Options" in line else 0, "stdout": "", "stderr": ""}

    task = up["CTask"].__new__(up["CTask"])
    task.cm = types.SimpleNamespace(utils = types.SimpleNamespace(sys = types.SimpleNamespace(run = run)))
    task.logger = None
    ctx = {"control": {"con": False, "quiet": True},
           "tasks": {"global": {"host": {"os": {"uname": "linux"}, "os_extra": {"id": "ubuntu", "package_manager": "apt-get"}}}}}
    r = task.run(ctx, full = True)

    assert r["return"] == 1 and "upgrade failed" in r["error"]
    assert [s["name"] for s in r["steps"]] == ["update", "mounts aside", "configure", "upgrade", "mounts back"]
    assert "file-mounts.sh" in ran[1] and ran[1].endswith(" aside") and "file-mounts.sh" in ran[-1] and ran[-1].endswith(" back")
    assert all(line.startswith("sudo -n ") for line in ran)


def test_the_file_mounts_script(up):
    """file-mounts.sh: only the files a package owns, under the system folders and not /etc, bound to a place of their
    own and unmounted; back over their file, a run cut short first put back; plain sh for any Linux."""
    import pathlib
    path = pathlib.Path(up["FILE_MOUNTS"].split(" ", 1)[1].strip("'\""))
    text = path.read_text(encoding = "ascii")
    assert text.startswith("#!/bin/sh\n") and "\r" not in path.read_bytes().decode("ascii")
    assert "dpkg -S" in text and "rpm -qf" in text and "pacman -Qo" in text and "apk info --who-owns" in text
    assert "/usr/*|/bin/*|/sbin/*|/lib/*" in text and "/etc/*" not in text and '[ -f "$path" ]' in text
    aside = text[text.index("aside() {"):]
    assert aside.index("back || return 1") < aside.index('mount --bind "$path" "$place" && umount "$path"')
    assert 'mount --bind "$place" "$path" && umount "$place"' in text and "STATE=/run/cmeta-upgrade-os" in text


def test_what_a_check_found(up):
    """The counts of a check, carried by the final line ("cx host upgrade --check" shows only the last lines)."""
    apt = "Listing...\nudev/resolute-updates 259.9 amd64 [upgradable from: 259.5]\nsnapd/noble-updates 2.77 amd64 [upgradable from: 2.76]\n"
    assert up["pending"]("check", apt, "apt-get") == (2, [], "packages")
    assert up["pending"]("check", "anything", "dnf") is None
    su = ("Software Update found the following new or updated software:\n* Label: macOS 27.2-26B123\n"
          "\tTitle: macOS 27.2, Version: 27.2, Size: 6067473KiB, Recommended: YES, Action: restart,\n")
    assert up["pending"]("system check", su) == (1, ["macOS 27.2-26B123"], "macOS updates")
    assert up["pending"]("system check", "") == (0, [], "macOS updates")
    assert up["pending"]("brew check", "openssl@3\ntailscale\n==> Auto-updated Homebrew!\n") == (2, [], "brew packages")
    assert up["pending"]("apps check", "Name  Id  Version  Available\n...\n8 upgrades available.\n") == (8, [], "winget apps")
    assert up["pending"]("windows update check", "ComputerName Status KB Size Title\nNUC ------- KB5127936 90MB 2026-10 Preview\n") == (1, [], "Windows updates")


def test_sudo_rule(up):
    assert up["with_sudo"]("apt-get update", True, interactive = False) == "sudo -n apt-get update"
    assert up["with_sudo"]("apt-get update", True, interactive = True) == "sudo apt-get update"
    assert up["with_sudo"]("brew upgrade", False, interactive = False) == "brew upgrade"
    assert up["truthy"]("true") and up["truthy"]("1") and not up["truthy"]("no") and not up["truthy"](None)
