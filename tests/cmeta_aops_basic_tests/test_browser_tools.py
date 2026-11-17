"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/firefox and tool/google-chrome (2026-11-14) and tool/thunderbird (2026-11-17): the installed
version read from the output or the files of each system, the newest one from the vendors' answers and from snap's
channel, and how Firefox and Thunderbird are installed on Linux; for Thunderbird also its update channel (release or
ESR) and winget's package of that channel and language. Nothing is installed, nothing is downloaded: the answers are
copies of their real shape.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def helpers(tool):
    """The functions of a tool's api_v1.py before its CTool class (the class needs the engine)."""
    path = REPO_ROOT / "tool" / tool / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    head = src[:src.index("\nclass CTool")].replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "")
    ns = {"__name__": tool.replace("-", "_") + "_helpers", "__file__": str(path)}
    exec(compile(head, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def ff():
    return helpers("firefox")


@pytest.fixture(scope = "module")
def gc():
    return helpers("google-chrome")


# "snap info firefox" on Ubuntu 26.04 before the refresh (2026-11-14)
SNAP_INFO = """name:      firefox
summary:   Mozilla Firefox web browser
publisher: Mozilla**
tracking:     latest/stable/ubuntu-26.04
refresh-date: 2026-08-18
channels:
  latest/stable:    160.0-1      2026-11-12 (9181) 312MB -
  latest/candidate: 161.0b2-1    2026-11-13 (9230) 312MB -
  latest/beta:      161.0b2-1    2026-11-13 (9230) 312MB -
  esr/stable:       153.7.0esr-1 2026-11-10 (9170) 300MB -
installed:          153.0.4-1               (8754) 270MB -
"""


def test_firefox_versions(ff):
    assert ff["version_of_output"]("Mozilla Firefox 160.0\n") == "160.0"
    assert ff["version_of_output"]("Mozilla Firefox 153.7.0esr") == "153.7.0esr"
    assert ff["version_of_output"]("update.go:193: cannot change mount namespace") is None
    ini = "[App]\nVendor=Mozilla\nName=Firefox\nVersion=160.0\nBuildID=20261110000000\n"
    assert ff["version_of_application_ini"](ini) == "160.0"
    assert ff["version_of_application_ini"]("not an ini") is None


def test_the_snap_offers_its_tracked_channel(ff):
    assert ff["snap_versions"](SNAP_INFO) == ("153.0.4", "160.0")
    esr = SNAP_INFO.replace("latest/stable/ubuntu-26.04", "esr/stable")
    assert ff["snap_versions"](esr) == ("153.0.4", "153.7.0esr")
    assert ff["snap_versions"]("") == (None, None)


def test_how_firefox_is_installed_on_linux(ff):
    assert ff["linux_channel"]("/snap/firefox/9181/usr/lib/firefox/firefox", False, None) == "snap"
    # Ubuntu's transitional firefox package: /usr/bin/firefox, the snap installed
    assert ff["linux_channel"]("/usr/bin/firefox", True, None) == "snap"
    assert ff["linux_channel"]("/usr/lib/firefox/firefox", False, "firefox") == "deb"
    assert ff["linux_channel"]("/opt/firefox/firefox", False, None) == "other"


def test_chrome_versions(gc):
    assert gc["version_of_output"]("Google Chrome 157.0.8103.78 \n") == "157.0.8103.78"
    assert gc["version_of_output"]("Chromium 157.0.8103.78") is None
    names = ["chrome.exe", "151.0.7922.137", "157.0.8103.78", "chrome_proxy.exe", "SetupMetrics", "99.0.4844.51"]
    assert gc["version_of_folder"](names) == "157.0.8103.78"
    assert gc["version_of_folder"](["chrome.exe"]) is None


def test_chrome_platforms_and_the_version_history(gc):
    assert gc["platform_of"]("linux", "amd64") == "linux"
    assert gc["platform_of"]("windows", "amd64") == "win64" and gc["platform_of"]("windows", "arm64") == "win_arm64"
    assert gc["platform_of"]("darwin", "arm64") == "mac_arm64" and gc["platform_of"]("darwin", "amd64") == "mac"
    answer = {"versions": [{"name": "chrome/platforms/linux/channels/stable/versions/157.0.8103.78",
                            "version": "157.0.8103.78"}], "nextPageToken": "x"}
    assert gc["newest_of_history"](answer) == "157.0.8103.78"
    assert gc["newest_of_history"]({}) is None
    assert "{platform}" in gc["VERSION_HISTORY"] and "order_by=version%20desc" in gc["VERSION_HISTORY"]


############################################################ tool/thunderbird

@pytest.fixture(scope = "module")
def tb():
    return helpers("thunderbird")


# Mozilla's answer of 2026-11-17 (product-details.mozilla.org/1.0/thunderbird_versions.json)
TB_VERSIONS = {"LATEST_THUNDERBIRD_ALPHA_VERSION": "54.0a2", "LATEST_THUNDERBIRD_DEVEL_VERSION": "161.0b3",
               "LATEST_THUNDERBIRD_NIGHTLY_VERSION": "162.0a1", "LATEST_THUNDERBIRD_VERSION": "160.0",
               "THUNDERBIRD_ESR": "153.7.0esr", "THUNDERBIRD_ESR_NEXT": ""}

# "snap info thunderbird" on Ubuntu 26.04 without the snap (the P14s Gen 4, 2026-11-17; stdout - snap's "1 new
# warning" line goes to stderr): since July 2026 the snap's latest/stable is the monthly release, the ESR esr/stable
TB_SNAP_INFO = """name:      thunderbird
summary:   Mozilla Thunderbird email application
publisher: Canonical**
store-url: https://snapcraft.io/thunderbird
contact:   https://www.thunderbird.net/contact/
license:   MPL-2.0
description: |
  **ANNOUNCEMENT:** The snap channels have changed. Action was required by
  July 21, 2026 to stay on ESR.

  Read more about this change:
  https://support.mozilla.org/kb/channel-choices-thunderbird-snap-and-flatpak

  Thunderbird is a free email application that’s easy to set up and customize
  - and it’s loaded with great features!
snap-id: k1Ml1O9GzSO2QftV0ZlWSbUfQ78nN460
channels:
  latest/stable:    160.0-1      2026-11-16 (1333) 234MB -
  latest/candidate: 160.0-1      2026-11-13 (1333) 234MB -
  latest/beta:      161.0b3-1    2026-11-14 (1337) 257MB -
  latest/edge:      ^
  esr/stable:       153.6.0esr-1 2026-10-27 (1310) 236MB -
  esr/candidate:    153.7.0esr-3 2026-11-13 (1331) 236MB -
  esr/beta:         ^
  esr/edge:         ^
"""


def test_thunderbird_versions(tb):
    assert tb["version_of_output"]("Thunderbird 153.7.0esr\n") == "153.7.0esr"
    # macOS, Mozilla's disk image of the ESR (2026-11-17): the "esr" here is the only sign of the ESR on a Mac - its
    # application.ini says 153.7.0 and the channel is in ChannelPrefs.framework, not in a channel-prefs.js
    assert tb["version_of_output"]("Mozilla Thunderbird 153.7.0esr\n") == "153.7.0esr"
    assert tb["version_of_output"]("Mozilla Thunderbird 160.0") == "160.0"
    assert tb["version_of_output"]("update.go:85: cannot change mount namespace") is None
    assert tb["plain"]("153.7.0esr") == "153.7.0" and tb["plain"]("160.0") == "160.0" and tb["plain"]("") is None
    # the application.ini beside thunderbird.exe of the ESR on Windows 11 (no "esr" in Version)
    ini = "[App]\nVendor=Mozilla\nName=Thunderbird\nRemotingName=thunderbird\nVersion=153.7.0\nBuildID=20261110162734\n"
    assert tb["version_of_application_ini"](ini) == "153.7.0"
    assert tb["version_of_application_ini"]("not an ini") is None


def test_thunderbird_update_channel(tb):
    prefs = ('/* This Source Code Form is subject to the terms of the Mozilla Public\n * License, v. 2.0. */\n\n'
             'pref("app.update.channel", "esr");\n')
    assert tb["channel_of_prefs"](prefs) == "esr"
    assert tb["channel_of_prefs"]("pref('app.update.channel', 'release');") == "release"
    assert tb["channel_of_prefs"]("") is None
    assert tb["channel_of_update_settings"]("[Settings]\nACCEPTED_MAR_CHANNEL_IDS=thunderbird-comm-esr\n") == "esr"
    assert tb["channel_of_update_settings"]("[Settings]\nACCEPTED_MAR_CHANNEL_IDS=thunderbird-comm-release\n") == "release"
    assert tb["channel_of_update_settings"](None) is None
    # the first hint that tells: a channel name, else a version with the ESR's suffix
    assert tb["channel_of"](None, "esr", "release") == "esr"
    assert tb["channel_of"](None, None, "153.7.0esr") == "esr"
    assert tb["channel_of"]("default", None, "160.0") is None
    assert tb["newest_of"](TB_VERSIONS, "esr") == "153.7.0"
    assert tb["newest_of"](TB_VERSIONS, "release") == "160.0" and tb["newest_of"](TB_VERSIONS, None) == "160.0"
    assert tb["newest_of"]({}, "esr") is None


def test_thunderbird_on_windows(tb):
    # the Uninstall entry of the ESR on Windows 11, and winget's package of a channel and language
    assert tb["arp_name_locale"]("Mozilla Thunderbird ESR (x64 en-US)") == ("esr", "en-US")
    assert tb["arp_name_locale"]("Mozilla Thunderbird (x64 de)") == ("release", "de")
    assert tb["arp_name_locale"]("Mozilla Thunderbird 115.3.0 (x86 ja-JP-mac)") == ("release", "ja-JP-mac")
    assert tb["arp_name_locale"]("Mozilla Firefox (x64 en-US)") == (None, None)
    assert tb["winget_id"]("esr", "en-US") == "Mozilla.Thunderbird.ESR"
    assert tb["winget_id"]("release", None) == "Mozilla.Thunderbird"
    assert tb["winget_id"]("release", "de") == "Mozilla.Thunderbird.de"
    assert tb["winget_id"]("esr", "fr") == "Mozilla.Thunderbird.ESR.fr"
    # winget's "no installed package found" as Python reports it on Windows, and as a signed value
    assert 2316632084 & 0xFFFFFFFF == tb["WINGET_NOT_INSTALLED"] == -1978335212 & 0xFFFFFFFF
    assert -1978335189 & 0xFFFFFFFF == tb["WINGET_NO_UPGRADE"]


def test_thunderbird_snap_and_apt(tb):
    info = tb["snap_info"](TB_SNAP_INFO)
    assert info["installed"] is None and info["tracking"] is None and info["offered"] is None
    assert info["channels"]["latest/stable"] == "160.0" and info["channels"]["esr/stable"] == "153.6.0"
    assert info["channels"]["esr/candidate"] == "153.7.0"
    # the same with the ESR snap installed (the lines snap adds then: tracking, refresh-date, installed)
    installed = TB_SNAP_INFO.replace("channels:\n", "tracking:     esr/stable\nrefresh-date: 2026-10-30\nchannels:\n") + \
        "installed:          153.6.0esr-1               (1310) 236MB -\n"
    info = tb["snap_info"](installed)
    assert (info["installed"], info["tracking"], info["offered"]) == ("153.6.0", "esr/stable", "153.6.0")
    assert tb["snap_channel"]("esr/stable") == "esr" and tb["snap_channel"]("latest/stable/ubuntu-26.04") == "release"
    assert tb["snap_channel"](None) == "release"
    # Debian's package (the ESR) before the install, and Ubuntu's transitional deb that only installs the snap
    debian = "thunderbird:\n  Installed: (none)\n  Candidate: 1:140.5.0esr-1~deb12u1\n  Version table:\n"
    assert tb["apt_policy"](debian) == (None, "140.5.0", True)
    ubuntu = "thunderbird:\n  Installed: 2:1snap1-0ubuntu2\n  Candidate: 2:1snap1-0ubuntu2\n"
    assert tb["apt_policy"](ubuntu) == (None, None, False)
    assert tb["apt_policy"]("") == (None, None, False)


def test_how_thunderbird_is_installed(tb):
    assert tb["linux_kind"]("/snap/thunderbird/1333/thunderbird", False, None, None) == "snap"
    assert tb["linux_kind"]("/usr/bin/thunderbird", True, None, None) == "snap"
    assert tb["linux_kind"]("/usr/lib/thunderbird/thunderbird", False, "140.5.0", None) == "deb"
    assert tb["linux_kind"]("/usr/lib64/thunderbird/thunderbird", False, None, "140.5.0") == "rpm"
    assert tb["linux_kind"]("/opt/thunderbird/thunderbird", False, None, None) == "other"
    mac = tb["install_folder"]("/Applications/Thunderbird.app/Contents/MacOS/thunderbird", "darwin")
    assert mac.replace("\\", "/") == "/Applications/Thunderbird.app/Contents/Resources"
    win = tb["install_folder"](r"C:\Program Files\Mozilla Thunderbird\thunderbird.exe", "windows")
    assert win.replace("\\", "/").endswith("Mozilla Thunderbird")
    assert tb["install_folder"](None, "linux") is None


def test_thunderbird_channel_asked(tb):
    assert tb["wanted_channel"]({"with": {"channel": "ESR"}}) == ("esr", None)
    assert tb["wanted_channel"]({"with": {"channel": "release"}}) == ("release", None)
    assert tb["wanted_channel"]({}) == (None, None) and tb["wanted_channel"](None) == (None, None)
    channel, error = tb["wanted_channel"]({"with": {"channel": "beta"}})
    assert channel is None and "--with.channel" in error


# "winget show --id Mozilla.Thunderbird.ESR -e --source winget" on Windows 11 (2026-11-17), its first lines
TB_WINGET_SHOW = """Found Mozilla Thunderbird ESR (en-US) [Mozilla.Thunderbird.ESR]
Version: 153.7.0
Publisher: Mozilla
Publisher Url: https://www.mozilla.org/
Moniker: thunderbird-esr
"""

# "brew info --json=v2 --cask thunderbird@esr" on macOS (2026-11-17), the keys the tool reads
TB_CASK_INFO = """{"formulae": [], "casks": [{"token": "thunderbird@esr", "version": "153.7.0esr", "auto_updates": true,
"artifacts": [{"app": ["Thunderbird.app"]}]}]}"""


def test_thunderbird_versions_of_the_system_channels(tb):
    assert tb["version_of_winget_show"](TB_WINGET_SHOW) == "153.7.0"
    assert tb["version_of_winget_show"]("No package found matching input criteria.") is None
    assert tb["version_of_cask_info"]("==> Downloading\n" + TB_CASK_INFO) == "153.7.0"
    assert tb["version_of_cask_info"]('{"casks": []}') is None and tb["version_of_cask_info"]("") is None
    assert tb["older"]("160.0", "160.0.1") and tb["older"]("153.7.0", "160.0") and not tb["older"]("160.0", "160.0")
    assert not tb["older"]("153.10.0", "153.9.1")


# "dnf info thunderbird" in a Fedora 44 container without Thunderbird (2026-11-17): Fedora's package is 157.0
TB_DNF_INFO = """Updating and loading repositories:
Repositories loaded.
Available packages
Name           : thunderbird
Epoch          : 0
Version        : 157.0
Release        : 2.fc44
Architecture   : x86_64
Repository     : updates
Summary        : Mozilla Thunderbird mail/newsgroup client
"""


def test_thunderbird_dnf(tb):
    assert tb["newest_of_dnf_info"](TB_DNF_INFO) == "157.0"
    # installed and available: the newest one
    both = TB_DNF_INFO.replace("Available packages", "Installed packages\nName : thunderbird\nVersion : 155.0\n"
                               "Release : 1.fc44\n\nAvailable packages")
    assert tb["newest_of_dnf_info"](both) == "157.0"
    assert tb["newest_of_dnf_info"]("No matching packages to list") is None


def test_thunderbird_lists_moved_on(tb):
    # setup detects the tool again at the version it asked for: a refreshed list that offers another one stops the
    # install before anything is installed
    error = tb["moved_on"]("140.17.0", "153.7.0", "apt's refreshed package lists")
    assert error.startswith("apt's refreshed package lists offer Thunderbird 153.7.0 now, not 140.17.0")
    assert "run the upgrade again to get 153.7.0" in tb["moved_on"]("140.17.0", "1:153.7.0esr", "x")
    assert tb["moved_on"]("153.7.0", "153.7.0esr", "x") is None
    assert tb["moved_on"](None, "153.7.0", "x") is None and tb["moved_on"]("153.7.0", None, "x") is None


def test_thunderbird_quarantine_on_macos(tb):
    # a quarantined app's first start waits for Gatekeeper's question (a Homebrew cask's thunderbird --version hung,
    # 2026-11-17): the tool starts it only without the attribute or once the user allowed it (flag 0x40)
    assert tb["quarantine_waits"]("0081;6939f0a1;Safari;6B2F4E0C-1D2E-4F3A-9B8C-7D6E5F4A3B2C")
    assert not tb["quarantine_waits"]("00c1;6939f0a1;Safari;6B2F4E0C-1D2E-4F3A-9B8C-7D6E5F4A3B2C")
    assert not tb["quarantine_waits"]("") and not tb["quarantine_waits"](None)
    assert tb["quarantine_waits"]("not flags")
