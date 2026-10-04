"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/flatc and of the digests pinned in a common_release spec: the release asset
of each platform, the fallback to the package manager where there is none, and an install from a
fake GitHub release checked against the pinned SHA-256.
"""

import hashlib
import io
import os
import pathlib
import shutil
import zipfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel_path, ns_name, stubs):
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in stubs:
        src = src.replace(line, replacement)
    ns = {"__name__": ns_name, "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def release():
    return load("category/tool/api/common_release.py", "common_release", [])


@pytest.fixture(scope = "module")
def flatc(release):
    ns = load("tool/flatc/api_v1.py", "flatc", [
        ("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "class InitCTool:\n    pass"),
        ("from tool_c393ba5c6fa14f66.api.common_release import install_release", "")])
    ns["install_release"] = release["install_release"]
    return ns


def test_the_asset_of_each_platform(flatc):
    assert flatc["asset_for"]("windows", "amd64") == "Windows.flatc.binary.zip"
    assert flatc["asset_for"]("linux", "amd64") == "Linux.flatc.binary.g++-13.zip"     # static: any distribution
    assert flatc["asset_for"]("darwin", "arm64") == "Mac.flatc.binary.zip"
    assert flatc["asset_for"]("darwin", "amd64") == "MacIntel.flatc.binary.zip"
    assert flatc["asset_for"]("linux", "aarch64") is None
    assert flatc["asset_for"]("windows", "arm64") is None
    pinned = flatc["SPEC"]["checksum"]["sha256"][flatc["SPEC"]["default_version"]]
    assert set(pinned) == set(flatc["ASSETS"].values())
    assert all(len(d) == 64 for d in pinned.values())


def test_pinned_digests(release):
    checksum = {"sha256": {"1.0.0": {"a.zip": "AB" * 32}}}
    r = release["_expected_sha256"](None, None, None, checksum, {"version": "1.0.0"}, "a.zip", "content")
    assert r == {"return": 0, "sha256": "ab" * 32}
    # another version, or an asset not pinned: downloaded over HTTPS only
    assert release["_expected_sha256"](None, None, None, checksum, {"version": "2.0.0"}, "a.zip", "content")["sha256"] is None
    assert release["_expected_sha256"](None, None, None, checksum, {"version": "1.0.0"}, "b.zip", "content")["sha256"] is None


class FakeCM:
    """download-file from a dict {url: bytes}."""

    def __init__(self, server):
        self.server = server

    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def access(self, ii):
        data = self.server.get(ii["url"])
        if data is None:
            return {"return": 1, "error": f'404 {ii["url"]}'}
        d = os.path.join(os.getcwd(), ii["directory"])
        os.makedirs(d, exist_ok = True)
        with open(os.path.join(d, ii["filename"]), "wb") as f:
            f.write(data)
        return {"return": 0}


def zipped(name, data):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, data)
    return buf.getvalue()


def context(uname, uarch):
    exe = ".exe" if uname == "windows" else ""
    return {"control": {}, "tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": uname, "uarch": uarch},
                                                                            "vars": {"file_ext_exe": exe}}}}}


def tool(flatc, server):
    t = flatc["CTool"].__new__(flatc["CTool"])
    t.cm = FakeCM(server)
    return t


def test_install_checks_the_pinned_digest(flatc, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asset = zipped("flatc", b"\x7fELF flatc")
    url = flatc["RELEASES"].format(version = "25.12.19") + "Linux.flatc.binary.g++-13.zip"
    spec = dict(flatc["SPEC"], checksum = {"sha256": {"25.12.19": {"Linux.flatc.binary.g++-13.zip":
                                                                   hashlib.sha256(asset).hexdigest()}}})
    monkeypatch.setitem(flatc, "SPEC", spec)
    r = tool(flatc, {url: asset}).install(context("linux", "amd64"), {"control": {}})
    assert r["return"] == 0 and r["install_cmd"] is None
    assert pathlib.Path(r["found_path"]).read_bytes() == b"\x7fELF flatc"
    assert pathlib.Path(r["found_path"]).name == "flatc"


def test_install_refuses_another_digest(flatc, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url = flatc["RELEASES"].format(version = "25.12.19") + "Windows.flatc.binary.zip"
    r = tool(flatc, {url: zipped("flatc.exe", b"MZ not the release")}).install(context("windows", "amd64"), {"control": {}})
    assert r["return"] == 1 and "SHA-256 mismatch" in r["error"]


def test_no_release_binary_falls_back(flatc, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = tool(flatc, {}).install(context("linux", "aarch64"), {"control": {}}, "sudo apt-get install -y flatbuffers-compiler")
    assert r["return"] == 16 and r["install_cmd"] == "sudo apt-get install -y flatbuffers-compiler"
