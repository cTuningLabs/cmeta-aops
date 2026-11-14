"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/firefox and tool/google-chrome (2026-11-14): the installed version read from the output or the
files of each system, the newest one from the vendors' answers and from snap's channel, and how Firefox is installed
on Linux. Nothing is installed, nothing is downloaded: the answers are copies of their real shape.
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
