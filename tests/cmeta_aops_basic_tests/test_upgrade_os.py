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
    assert names(steps) == ["update", "upgrade", "reboot?"]
    assert cmd_of(steps, "update") == "apt-get update"
    assert cmd_of(steps, "upgrade").endswith(" upgrade") and "DEBIAN_FRONTEND=noninteractive" in cmd_of(steps, "upgrade")
    assert cmd_of(steps, "reboot?") == "test -f /var/run/reboot-required"
    update, upgrade, probe = steps
    assert update[2] is True and upgrade[2] is True and probe[2] is False and probe[3] == "reboot?" and probe[4] == (0,)

    steps = up["plan"]("linux", {"package_manager": "apt-get"}, full = True, autoremove = True)
    assert names(steps) == ["update", "upgrade", "autoremove", "reboot?"]
    assert cmd_of(steps, "upgrade").endswith(" dist-upgrade") and cmd_of(steps, "autoremove").endswith(" autoremove")

    # --check: apt refreshes its index (root), then lists; no upgrade, no reboot probe
    steps = up["plan"]("linux", {"package_manager": "apt"}, check = True)
    assert names(steps) == ["update", "check"] and cmd_of(steps, "check") == "apt list --upgradable"

    # root: nothing needs sudo
    steps = up["plan"]("linux", {"package_manager": "apt-get"}, root = True)
    assert all(s[2] is False for s in steps)


def test_other_linux_package_managers(up):
    steps = up["plan"]("linux", {"package_manager": "dnf"})
    assert names(steps) == ["upgrade", "reboot?"] and cmd_of(steps, "upgrade") == "dnf -y upgrade --refresh"
    assert cmd_of(steps, "reboot?") == "needs-restarting -r" and steps[-1][4] == (1,)
    steps = up["plan"]("linux", {"package_manager": "zypper"})
    assert names(steps) == ["update", "upgrade", "reboot?"] and steps[-1][4] == (102,)
    assert names(up["plan"]("linux", {"package_manager": "pacman"})) == ["upgrade"]
    assert names(up["plan"]("linux", {"package_manager": "apk"})) == ["update", "upgrade"]
    assert names(up["plan"]("linux", {"package_manager": "dnf"}, check = True)) == ["check"]
    # a package manager this task does not know: nothing planned (the run says so)
    assert up["plan"]("linux", {"package_manager": "emerge"}) == []


def test_firmware_and_brew_on_linux(up):
    steps = up["plan"]("linux", {"package_manager": "apt-get", "brew_present": True}, firmware = True)
    assert names(steps) == ["update", "upgrade", "reboot?", "brew upgrade", "firmware refresh", "firmware update"]
    assert cmd_of(steps, "firmware update") == "fwupdmgr update -y" and cmd_of(steps, "brew upgrade") == "brew update && brew upgrade"
    assert next(s for s in steps if s[0] == "firmware update")[2] is True            # fwupd needs root over ssh
    steps = up["plan"]("linux", {"package_manager": "apt-get"}, firmware = True, check = True, system = False, apps = False)
    assert names(steps) == ["firmware refresh", "firmware check"] and cmd_of(steps, "firmware check") == "fwupdmgr get-updates"


def test_macos(up):
    steps = up["plan"]("darwin", {"id": "darwin", "package_manager": "brew"})
    assert names(steps) == ["system upgrade", "brew upgrade"]
    assert cmd_of(steps, "system upgrade") == "softwareupdate -ia" and steps[0][2] is True and steps[1][2] is False
    steps = up["plan"]("darwin", {}, check = True)
    assert names(steps) == ["system check", "brew check"] and cmd_of(steps, "system check") == "softwareupdate -l" and steps[0][2] is False
    assert names(up["plan"]("darwin", {}, firmware = True, system = False, apps = False)) == []     # firmware is in softwareupdate


def test_windows(up):
    steps = up["plan"]("windows", {"id": "windows", "package_manager": "winget"})
    assert names(steps) == ["apps upgrade"] and cmd_of(steps, "apps upgrade").startswith("winget upgrade --all")
    steps = up["plan"]("windows", {"package_manager": "winget"}, windows_update = True)
    assert names(steps) == ["apps upgrade", "windows update", "reboot?"]
    assert "PSWindowsUpdate" in cmd_of(steps, "windows update") and steps[-1][4] == (1,)
    steps = up["plan"]("windows", {"package_manager": "winget"}, check = True, windows_update = True)
    assert names(steps) == ["apps check", "windows update check"]
    assert all(s[2] is False for s in steps)


def test_sudo_rule(up):
    assert up["with_sudo"]("apt-get update", True, interactive = False) == "sudo -n apt-get update"
    assert up["with_sudo"]("apt-get update", True, interactive = True) == "sudo apt-get update"
    assert up["with_sudo"]("brew upgrade", False, interactive = False) == "brew upgrade"
    assert up["truthy"]("true") and up["truthy"]("1") and not up["truthy"]("no") and not up["truthy"](None)
