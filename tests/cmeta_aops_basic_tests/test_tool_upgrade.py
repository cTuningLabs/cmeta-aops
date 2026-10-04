"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of "cx tool setup <tool> --status" and "--upgrade" (task/setup/upgrade.py):

- the pure helpers that derive a tool's install channel from its install command,
  turn it into the upgrade command, normalise package-manager version strings and
  judge installed vs newest (real install commands of this repo's tools as input);
- both flags end to end, through the task engine, on a throwaway tool whose
  "install command" and "newest version" are Python one-liners - nothing is
  installed, no network is touched, and the cache lives in the temporary CMETA_HOME.
"""

import importlib.util
import os
import pathlib
import platform
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def up():
    """task/setup/upgrade.py loaded on its own: its helpers need no cMeta."""
    spec = importlib.util.spec_from_file_location("setup_upgrade_helpers", REPO_ROOT / "task" / "setup" / "upgrade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


###################################################################################################
# Channels: derived from the install commands the tools of this repo really use

WINGET_OPENCODE = "{{global.winget.qpath}} install --id=SST.opencode -e --no-upgrade --source winget {{global.init.winget_install_flags|}}"
WINGET_7Z = "{{global.winget.qpath}} install 7zip.7zip -e --no-upgrade --source winget {{global.init.winget_install_flags|}}"
WINGET_UV = "{{global.winget.qpath}} install --id=astral-sh.uv -e --source winget {{global.init.winget_install_flags|}}"
WINGET_HOST = "winget install {{name}} --source winget"
BREW_GH = "{{global.brew.qpath}} install gh"
BREW_CASK = "brew install --cask obsidian"
BREW_AZ = "brew update && brew install {{name}}"
SUDO = "{{global.host.os_extra.install_cmd_sudo}}"
SCRIPT_CLAUDE_SH = "{{global.curl.qpath}} -fsSL https://claude.ai/install.sh | bash"
SCRIPT_CLAUDE_CMD = "{{global.curl.qpath}} -fsSL https://claude.ai/install.cmd -o install.cmd && .\\install.cmd && del install.cmd"
SCRIPT_CODEX_PS = 'powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"'
SCRIPT_UV = "{{global.curl.qpath}} -LsSf https://astral.sh/uv/install.sh | sh"
NPM = "npm install -g openclaw"
PIP = "{{global.pip.cmd}} install {{params.with.flags|}} {{custom_package}} {{params.with.post_flags|}}"
RUSTUP = "rustup toolchain install stable"
XCODE = "xcode-select --install"
SNAP = "snap install kubectl --classic"


@pytest.mark.parametrize("cmd, channel, package", [
    (WINGET_OPENCODE, "winget", "SST.opencode"),
    (WINGET_7Z, "winget", "7zip.7zip"),
    (WINGET_UV, "winget", "astral-sh.uv"),
    (WINGET_HOST, "winget", "{{name}}"),
    (BREW_GH, "brew", "gh"),
    (BREW_CASK, "brew", "obsidian"),
    (BREW_AZ, "brew", "{{name}}"),
    (SUDO, "sudo", "{{name}}"),
    (SCRIPT_CLAUDE_SH, "script", None),
    (SCRIPT_CLAUDE_CMD, "script", None),
    (SCRIPT_CODEX_PS, "script", None),
    (SCRIPT_UV, "script", None),
    (NPM, "npm", "openclaw"),
    (PIP, "pip", None),
    (RUSTUP, "rerun", None),
    (XCODE, "rerun", None),
    ("", "none", None),
    (None, "none", None),
])
def test_derive_channel(up, cmd, channel, package):
    assert up.derive_channel(cmd) == (channel, package)


def test_brew_cask_flag(up):
    assert up.brew_formula(BREW_CASK) == ("obsidian", True)
    assert up.brew_formula(BREW_GH) == ("gh", False)


@pytest.mark.parametrize("channel, cmd, versioned, expected", [
    # winget: install -> upgrade, --no-upgrade dropped
    ("winget", WINGET_OPENCODE, False,
     "{{global.winget.qpath}} upgrade --id=SST.opencode -e --source winget {{global.init.winget_install_flags|}}"),
    ("winget", WINGET_UV, False,
     "{{global.winget.qpath}} upgrade --id=astral-sh.uv -e --source winget {{global.init.winget_install_flags|}}"),
    # a specific version keeps "install" (winget changes versions through install) but still drops --no-upgrade
    ("winget", "{{global.winget.qpath}} install --id=Git.Git -e --version=2.55.0 --no-upgrade --source winget", True,
     "{{global.winget.qpath}} install --id=Git.Git -e --version=2.55.0 --source winget"),
    # brew: the last "install" becomes "upgrade", casks included
    ("brew", BREW_GH, False, "{{global.brew.qpath}} upgrade gh"),
    ("brew", BREW_CASK, False, "brew upgrade --cask obsidian"),
    ("brew", BREW_AZ, False, "brew update && brew upgrade {{name}}"),
    ("brew", "{{global.brew.qpath}} install gh@2", True, "{{global.brew.qpath}} install gh@2"),
    # the system package manager: task/host's upgrade command
    ("sudo", SUDO, False, "{{global.host.os_extra.upgrade_cmd_sudo}}"),
    ("sudo", "{{global.host.os_extra.install_cmd_sudo_version}}", True, "{{global.host.os_extra.install_cmd_sudo_version}}"),
    # npm: @latest
    ("npm", NPM, False, "npm install -g openclaw@latest"),
    # install scripts and pip run again as they are
    ("script", SCRIPT_CLAUDE_SH, False, SCRIPT_CLAUDE_SH),
    ("pip", PIP, False, PIP),
    # other install verbs with an upgrade counterpart
    ("rerun", RUSTUP, False, "rustup update stable"),
    ("rerun", SNAP, False, "snap refresh kubectl --classic"),
    ("rerun", XCODE, False, XCODE),
])
def test_derive_upgrade_cmd(up, channel, cmd, versioned, expected):
    assert up.derive_upgrade_cmd(channel, cmd, versioned=versioned) == expected


###################################################################################################
# Versions

@pytest.mark.parametrize("raw, normalized", [
    ("1:2.53.0-1ubuntu1", "2.53.0"),   # apt: epoch and revision
    ("2.43.0-1ubuntu7.3", "2.43.0"),
    ("2.45.2-r0", "2.45.2"),           # apk
    ("2.47.0-1", "2.47.0"),            # pacman
    ("2.1.5+ds-0ubuntu0.2", "2.1.5"),  # debian source suffix
    ("2.0.0-rc1", "2.0.0-rc1"),        # a pre-release is not a revision
    ("25.0.2+10", "25.0.2+10"),        # a build number is kept
    ("1.18.33", "1.18.33"),
    ("", ""),
    (None, ""),
])
def test_normalize_pkg_version(up, raw, normalized):
    assert up.normalize_pkg_version(raw) == normalized


@pytest.mark.parametrize("installed, latest, verdict", [
    ("1.18.19", "1.18.33", "outdated"),
    ("1.18.33", "1.18.33", "up-to-date"),
    ("1.18.34", "1.18.33", "newer"),
    ("2.53.0.windows.2", "2.55.0.5", "outdated"),   # git on Windows vs winget
    ("2.49.0.windows.1", "2.49.0", "up-to-date"),   # the local part does not make it "newer"
    ("1:2.53.0-1ubuntu1", "2.53.0", "up-to-date"),  # apt string vs upstream
    ("2.43.0", "1:2.47.3-0+deb13u1", "outdated"),
    (None, "1.0", "not-installed"),
    ("", "1.0", "not-installed"),
    ("1.0", None, "unknown"),
])
def test_version_verdict(up, installed, latest, verdict):
    assert up.version_verdict(installed, latest) == verdict


def test_pick_latest_skips_prereleases(up):
    assert up.pick_latest(["1.18.9", "2.0.0-rc1", "1.18.34", "1.17.20"]) == "1.18.34"
    assert up.pick_latest(["0.159.3-alpha.1", "0.159.2"]) == "0.159.2"
    assert up.pick_latest(["1.0.0.dev3", "0.9"]) == "0.9"
    assert up.pick_latest(["1.0.0-rc1"]) is None          # only pre-releases: nothing to pick
    assert up.pick_latest(["stable", "nightly"]) == "stable"   # unparseable: first one, as a last resort
    assert up.pick_latest([]) is None
    assert up.pick_latest(None) is None


def test_is_prerelease(up):
    assert up.is_prerelease("2.0.0-rc1")
    assert up.is_prerelease("0.159.3-alpha.1")
    assert not up.is_prerelease("2.0.21")
    assert not up.is_prerelease("1:2.53.0-1ubuntu1")


###################################################################################################
# Upstream: GitHub repositories and tags, the regexes of this repo's tools

@pytest.mark.parametrize("cmd, repo", [
    ("{{global.git.qpath}} ls-remote --tags https://github.com/anomalyco/opencode", "anomalyco/opencode"),
    ("git ls-remote --tags https://github.com/jqlang/jq.git", "jqlang/jq"),
    ("{{global.git.qpath}} ls-remote --tags https://github.com/openai/codex", "openai/codex"),
    ("{{global.pip.cmd}} index versions {{params.with.package}}", None),
    ("npm view openclaw versions --json", None),
    (None, None),
])
def test_github_repo_from_cmd(up, cmd, repo):
    assert up.github_repo_from_cmd(cmd) == repo


@pytest.mark.parametrize("tag, regex, version", [
    ("v1.18.34", r"refs/tags/v([\d.]+)(?:\^\{\})?$", "1.18.34"),                               # opencode, claude
    ("rust-v0.159.3", r"refs/tags/rust-v(\d[\w.\-]*?)(?:\^\{\})?$", "0.159.3"),                 # codex
    ("jq-1.8.2", r"\brefs/tags/jq-(\d+\.\d+(?:\.\d+)?)(?![\w.-])", "1.8.2"),                    # jq
    ("v4.3.0", r"refs/tags/v(\d+\.\d+\.\d+)$", "4.3.0"),                                         # helm-style
    ("v4.3.0", None, "4.3.0"),                                                                   # no regex: first version-like token
    ("jdk-25.0.2+10", None, "25.0.2+10"),
    ("vscode-v2.0.21", r"refs/tags/v([\d.]+)(?:\^\{\})?$", None),                                # a tag the regex rejects is not a version
    ("v0.5.0", r"\brefs/tags/b(\d+)\b", None),                                                   # llama.cpp: releases are numbered builds
    ("b11322", r"\brefs/tags/b(\d+)\b", "11322"),
    ("latest", None, None),
])
def test_version_from_tag(up, tag, regex, version):
    assert up.version_from_tag(tag, regex) == version


###################################################################################################
# Package managers: the output they print

def test_parse_winget_versions(up):
    out = "Found opencode [SST.opencode]\nVersion\n-------\n1.18.33\n1.18.32\n1.18.31\n"
    assert up.parse_winget_versions(out) == "1.18.33"
    assert up.parse_winget_versions("No package found matching input criteria.") is None
    assert up.parse_winget_versions("") is None


def test_parse_candidate_versions(up):
    apt = "git:\n  Installed: 1:2.53.0-1ubuntu1\n  Candidate: 1:2.53.0-1ubuntu1\n  Version table:\n"
    assert up.parse_candidate_versions(apt, r"Candidate:\s*(\S+)") == ["1:2.53.0-1ubuntu1"]
    assert up.parse_candidate_versions("  Candidate: (none)\n", r"Candidate:\s*(\S+)") == []

    dnf = "Installed Packages\nName : git\nVersion : 2.43.0\nAvailable Packages\nName : git\nVersion : 2.47.1\n"
    found = up.parse_candidate_versions(dnf, r"^Version\s*:\s*(\S+)")
    assert found == ["2.43.0", "2.47.1"]
    assert up.pick_latest(found) == "2.47.1"

    apk = "git policy:\n  2.45.2-r0:\n    lib/apk/db/installed\n    https://dl-cdn.alpinelinux.org/alpine/v3.20/main\n"
    assert up.parse_candidate_versions(apk, r"^\s+(\d\S*):\s*$") == ["2.45.2-r0"]


windows_only = pytest.mark.skipif(os.name != "nt", reason = "a Windows path is an ordinary name elsewhere")


@pytest.mark.parametrize("path, channel", [
    pytest.param(r"C:\Users\x\AppData\Local\Microsoft\WinGet\Links\uv.exe", "winget", marks = windows_only),
    ("/opt/homebrew/bin/gh", "brew"),
    ("/home/linuxbrew/.linuxbrew/bin/gh", "brew"),
    ("/usr/bin/git", "sudo"),
    ("/bin/tar", "sudo"),
    ("/home/u/.local/bin/claude", "script"),
    ("/home/u/.opencode/bin/opencode", "script"),
    pytest.param(r"D:\x\repos\local\cache\task--setup--jq--3bd63d577f9c4bad\content\jq.exe", "release", marks = windows_only),
    ("/home/u/.nvm/versions/node/v22.0.0/lib/node_modules/openclaw/bin/openclaw.mjs", "npm"),
    ("/home/u/project/venv/bin/yamllint", "pip"),
    pytest.param(r"C:\Program Files\Git\bin\git.exe", None, marks = windows_only),
    ("", None),
    (None, None),
])
def test_guess_channel_from_path(up, path, channel):
    assert up.guess_channel_from_path(path) == channel


###################################################################################################
# Small helpers shared with task/setup/api_v1.py

def test_select_for_os(up):
    assert up.select_for_os({"windows": "w", "linux": "l"}, "darwin") == "l"    # macOS falls back to linux
    assert up.select_for_os({"windows": "w", "linux": "l", "darwin": "d"}, "darwin") == "d"
    assert up.select_for_os({"all": "a", "linux": "l"}, "linux") == "a"
    assert up.select_for_os({"linux": "l"}, "windows") is None                  # Windows never falls back
    assert up.select_for_os("s", "linux") == "s"
    assert up.select_for_os(None, "linux") is None


def test_versioned_install_cmd(up):
    """The Android NDK installs through sdkmanager "ndk;<version>": --upgrade takes the newest version."""
    ndk = {"install_cmd": {"all": 'sdkmanager "ndk;29.0.14206865"'},
           "install_cmd_version": {"all": 'sdkmanager "ndk;{{simple_version}}"'},
           "cmd_get_versions": "sdkmanager --list"}
    rerun = {"primary": up.CHANNEL_RERUN}
    cmd = up.versioned_install_cmd(ndk, "windows", rerun)
    assert cmd == 'sdkmanager "ndk;{{simple_version}}"'
    assert up.expand_version(cmd, "30.0.16248370") == 'sdkmanager "ndk;30.0.16248370"'
    # Without known versions, or through another channel: none
    assert up.versioned_install_cmd(dict(ndk, cmd_get_versions = None), "windows", rerun) is None
    assert up.versioned_install_cmd(ndk, "windows", {"primary": up.CHANNEL_WINGET}) is None


def test_split_version(up):
    assert up.split_version("1.2.3") == {"version_pip": "==1.2.3", "version_simple": "1.2.3", "version_major": "1"}
    assert up.split_version("==1.2.3")["version_simple"] == "1.2.3"
    assert up.split_version(">=1.2")["version_simple"] is None
    assert up.split_version("") == {}


###################################################################################################
# End to end, offline: a throwaway tool whose commands are Python one-liners

FAKE_TOOL = "test-upgrade-fake"


@pytest.fixture(scope="module")
def fake_tool(cm):
    """A tool in the temporary CMETA_HOME's local repo, detected at sys.executable."""
    r = cm.access({"category": "tool", "command": "add", "arg1": f"local:{FAKE_TOOL}", "con": False, "quiet": True, "yaml": True})
    assert r["return"] == 0, r.get("error")

    python = sys.executable
    desc = {
        "names": [os.path.basename(python)],
        "match_version": [{"regex": r"Python (\d+\.\d+\.\d+)", "group": 1}],
        "cmd_get_version": "{{tool_path}} --version",
        # "the newest version" and "the install command" are Python one-liners: no network
        "cmd_get_latest_version": f'"{python}" -c "import sys; sys.stdout.write(str(99) + chr(46) + str(0) + chr(46) + str(0))"',
        "cmd_get_latest_version_regex": r"(\d+\.\d+\.\d+)",
        "install_cmd": {"all": f'"{python}" -c "print(1)"'},
        # setup's common install_uses would set up winget / curl / brew first
        "skip_common_install_uses": True,
    }
    with open(os.path.join(r["path"], "_desc.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(desc, f)

    return r["path"]


def _setup(cm, **params):
    ii = {"category": "task", "command": "run", "arg1": "setup", "name": FAKE_TOOL,
          "tool_path": sys.executable, "con": False, "quiet": True}
    ii.update(params)
    return cm.access(ii)


def test_status_reports_installed_and_newest(cm, fake_tool):
    r = _setup(cm, status=True)
    assert r["return"] == 0, r.get("error")

    status = r["status"]
    assert status["installed"] is True
    assert status["version"] == platform.python_version()
    assert os.path.normcase(status["path"]) == os.path.normcase(sys.executable)
    assert status["upstream_version"] == "99.0.0"
    assert status["latest_version"] == "99.0.0"
    assert status["verdict"] == "outdated"
    assert status["channel"] == "rerun"                       # a plain command: run again to upgrade
    assert status["upgrade_cmd"].endswith('-c "print(1)"')
    assert "cmd" not in r                                     # --status stops before anything is set up


def test_status_through_tool_run_does_not_run_the_tool(cm, fake_tool):
    r = cm.access({"category": "tool", "command": "run", "arg1": FAKE_TOOL, "status": True,
                   "tool_path": sys.executable, "con": False, "quiet": True})
    assert r["return"] == 0, r.get("error")
    assert r["status"]["installed"] is True
    assert "cmd" not in r


def test_upgrade_runs_the_channel_command_and_detects_again(cm, fake_tool):
    r = _setup(cm, upgrade=True)
    assert r["return"] == 0, r.get("error")

    assert r["version"] == platform.python_version()
    record = r["last_upgrade"]
    assert record["from"] == platform.python_version()
    assert record["to"] == platform.python_version()
    assert record["changed"] is False
    assert "failed" not in record
    assert record["cmd"].endswith('-c "print(1)"')

    # the cache entry of this tool now carries the record, and a plain setup replays it
    r2 = _setup(cm)
    assert r2["return"] == 0, r2.get("error")
    assert r2["version"] == platform.python_version()
    assert r2["last_upgrade"]["changed"] is False
