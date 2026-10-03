"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/openssh-server (the pinned Win32-OpenSSH assets, the version pattern of the
Windows, Linux and macOS builds, sshd.exe in the unpacked release) and task/run-openssh (the keys it
allows, the Tailscale address it listens on by default, its sshd_config, its checks of --port and
--name, status and stop without a server, and a recorded PID that another program has now).
"""

import os
import pathlib
import re
import socket
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOv2xbm5Yx5tSdyFiK0gYn6kSPW0C3ZoD2b0CtEhKsZm test@example"
OTHER = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTY other@example"


def load(rel_path, imports):
    """The module's namespace, with its cMeta imports replaced."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in imports.items():
        assert line in src
        src = src.replace(line, replacement)
    ns = {"__name__": path.parent.name, "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def task():
    return load("task/run-openssh/api_v1.py",
                {"from task_c36be4b9314a45e0.api.ctask import InitCTask": "class InitCTask: pass"})


@pytest.fixture(scope = "module")
def tool():
    return load("tool/openssh-server/api_v1.py",
                {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass",
                 "from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256": ""})


def desc(rel_path):
    return yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding = "utf-8"))


# tool/openssh-server

def test_tool_assets(tool):
    assert set(tool["ASSETS"]) == {"amd64", "arm64"}
    for name, sha256 in tool["ASSETS"].values():
        assert name.endswith(".zip") and re.fullmatch(r"[0-9a-f]{64}", sha256)
    url = tool["URL"].format(release = tool["RELEASE"], asset = "OpenSSH-Win64.zip")
    assert url == f"https://github.com/PowerShell/Win32-OpenSSH/releases/download/{tool['RELEASE']}/OpenSSH-Win64.zip"


def test_tool_version_pattern():
    match = desc("tool/openssh-server/_desc.yaml")["match_version"][0]
    for text, version in [("OpenSSH_for_Windows_10.0p2 Win32-OpenSSH-GitHub, LibreSSL 4.1.0", "10.0p2"),
                          ("OpenSSH_9.6p1 Ubuntu-3ubuntu13.14, OpenSSL 3.0.13 30 Jan 2024", "9.6p1"),
                          ("OpenSSH_10.3p1, LibreSSL 3.3.6", "10.3p1")]:
        assert re.search(match["regex"], text).group(match["group"]) == version


def test_find_sshd(tool, tmp_path):
    assert tool["find_sshd"](str(tmp_path)) is None
    (tmp_path / "OpenSSH-Win64").mkdir()
    (tmp_path / "OpenSSH-Win64" / "sshd.exe").write_bytes(b"")
    assert tool["find_sshd"](str(tmp_path)) == str(tmp_path / "OpenSSH-Win64" / "sshd.exe")


def test_task_uses_the_tool():
    uid = desc("tool/openssh-server/_cmeta.yaml")["artifact"]
    d = desc("task/run-openssh/_desc.yaml")
    assert d["cache"] is False and d["params_map"]["arg2"] == "action"
    assert [u for u in d["uses"] if u.get("name") == f"openssh-server,{uid}"]


# task/run-openssh: helpers

def test_read_keys(task, tmp_path):
    read_keys = task["read_keys"]
    assert read_keys("") == ([], None)
    assert read_keys(KEY) == ([KEY], None)
    keys = tmp_path / "authorized_keys"
    keys.write_text(f"# a comment\n\n{KEY}\n{OTHER}\n{KEY}\n", encoding = "utf-8")
    assert read_keys(f"{keys}, {KEY}") == ([KEY, OTHER], None)
    for bad in ["not-a-key", "ssh-ed25519", str(tmp_path / "missing.pub")]:
        lines, error = read_keys(f"{keys},{bad}")
        assert lines is None and "neither a key file nor a public key" in error


class FakeSubprocess:
    """subprocess.run for the tailscale command: its output, or an exception."""
    SubprocessError = subprocess.SubprocessError

    def __init__(self, stdout = "", exception = None):
        self.stdout, self.exception, self.commands = stdout, exception, []

    def run(self, command, **kwargs):
        self.commands.append(command)
        if self.exception:
            raise self.exception
        return subprocess.CompletedProcess(command, 0, stdout = self.stdout, stderr = "")


def test_tailscale_address(task, monkeypatch):
    fake = FakeSubprocess("100.94.236.2\n")
    monkeypatch.setitem(task, "subprocess", fake)
    monkeypatch.setitem(task, "local_address", lambda address: address == "100.94.236.2")
    assert task["tailscale_address"](cli = "tailscale") == "100.94.236.2"
    assert fake.commands == [["tailscale", "ip", "-4"]]

    # Not this machine's, outside Tailscale's range, no answer, no tailscale command
    monkeypatch.setitem(task, "local_address", lambda address: False)
    assert task["tailscale_address"](cli = "tailscale") is None
    monkeypatch.setitem(task, "local_address", lambda address: True)
    monkeypatch.setitem(task, "subprocess", FakeSubprocess("192.168.1.5\n"))
    assert task["tailscale_address"](cli = "tailscale") is None
    monkeypatch.setitem(task, "subprocess", FakeSubprocess(exception = OSError("not found")))
    assert task["tailscale_address"](cli = "tailscale") is None
    monkeypatch.setitem(task, "tailscale_cli", lambda: None)
    assert task["tailscale_address"]() is None


def test_local_address_and_listening(task):
    assert task["local_address"]("127.0.0.1")
    assert not task["local_address"]("192.0.2.1")          # TEST-NET-1, on no machine
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(8)                                     # two connections, none accepted
        port = s.getsockname()[1]
        assert task["listening"]("127.0.0.1", port)
        assert task["listening"]("0.0.0.0", port)          # asked on 127.0.0.1
    assert not task["listening"]("127.0.0.1", port, timeout = 0.5)


def test_sshd_config(task):
    lines = task["sshd_config"](2222, "100.94.236.2", "C:\\Users\\A B\\host_key", "C:\\cache\\50%\\authorized_keys",
                                pidfile = "C:\\cache\\sshd.pid", sftp = "C:\\o\\sftp-server.exe", windows = True)
    assert lines[:2] == ["Port 2222", "ListenAddress 100.94.236.2"]
    assert 'HostKey "C:/Users/A B/host_key"' in lines
    assert "AuthorizedKeysFile C:/cache/50%%/authorized_keys" in lines
    assert "Subsystem sftp C:/o/sftp-server.exe" in lines
    assert {"PasswordAuthentication no", "KbdInteractiveAuthentication no", "PubkeyAuthentication yes"} <= set(lines)
    assert not [line for line in lines if line.startswith(("PidFile", "UsePAM"))]

    lines = task["sshd_config"](2222, "127.0.0.1", "/s/host_key", "/s/authorized_keys", pidfile = "/s/sshd.pid")
    assert "PidFile /s/sshd.pid" in lines and "UsePAM no" in lines and "HostKey /s/host_key" in lines
    assert not [line for line in lines if line.startswith("Subsystem")]


# task/run-openssh: run() without starting a server

class FakeCM:
    """The cache entry of the task in a temporary folder."""

    def __init__(self, path):
        self.path = path

    def access(self, p):
        assert p["command"] == "get" and p["arg1"] == "task--run-openssh"
        return {"return": 0, "artifact": {"path": str(self.path)}}

    def catch_error(self, r):
        return r["return"] > 0

    def error(self, text):
        return {"return": 1, "error": text}


@pytest.fixture
def run(task, tmp_path, monkeypatch):
    """CTask.run with the cache entry in tmp_path, no home keys and no Tailscale."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setitem(task, "tailscale_address", lambda: None)
    t = object.__new__(task["CTask"])
    t.cm = FakeCM(tmp_path)
    t.cmeta = {"uses_categories": {"cache": "cache,1ebdcc1cc30c4022"}}
    ctx = {"control": {"con": False}, "tasks": {"global": {"openssh-server": {"path": "sshd"}}}}
    return lambda **params: t.run(ctx, **params)


def test_run_checks(run):
    assert "unknown action" in run(action = "restart")["error"]
    for port in ["70000", "0", "ssh"]:
        assert "--port" in run(port = port)["error"]
    for name in ["../x", "a b", ".."]:
        assert "--name" in run(name = name)["error"]
    assert "no public keys" in run(port = 2299)["error"]
    assert "neither a key file nor a public key" in run(port = 2299, keys = "missing.pub")["error"]


def test_status_and_stop_without_a_server(run, tmp_path):
    r = run(action = "status", port = 2299)
    assert r["return"] == 0 and r["running"] is False and (tmp_path / "default-2299").is_dir()
    r = run(action = "stop", port = 2299, name = "other")
    assert r["return"] == 0 and r["stopped"] is False and (tmp_path / "other-2299").is_dir()


def test_pid_of_another_program(run, tmp_path):
    """The PID an earlier server recorded, now another program's, is not taken for the server."""
    state = tmp_path / "default-2299"
    state.mkdir()
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (state / "sshd.pid").write_text(str(other.pid))
        assert run(action = "status", port = 2299)["running"] is False
        r = run(action = "stop", port = 2299)
        assert r["stopped"] is False and not (state / "sshd.pid").exists()
        assert other.poll() is None                         # left alone
    finally:
        other.kill()
        other.wait()
