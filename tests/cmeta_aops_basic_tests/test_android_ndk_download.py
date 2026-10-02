"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/google.android-ndk's download: the NDK zip of a version and host OS in
Google's repository index, the unpacking (file modes, symlinks, nothing outside the target), and
the fallback to sdkmanager where Google publishes no zip.
"""

import io
import os
import pathlib
import stat
import zipfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def ndk():
    path = REPO_ROOT / "tool" / "google.android-ndk" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool:\n    pass")
    ns = {"__name__": "ndk_tool", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


INDEX = """<?xml version="1.0"?>
<sdk:sdk-repository xmlns:sdk="http://schemas.android.com/sdk/android/repo/repository2/03">
  <remotePackage path="ndk;29.0.14206865">
    <archives>
      <archive><complete><size>783549481</size><checksum>87E2BB7E9BE5D6A1C6CDF5EC40DD4E0C6D07C30B</checksum>
        <url>android-ndk-r29-linux.zip</url></complete><host-os>linux</host-os></archive>
      <archive><complete><size>1049519838</size><checksum>03d29fbb57e3c05a7d53597dd011d856c1456a4f</checksum>
        <url>android-ndk-r29-darwin.zip</url></complete><host-os>macosx</host-os></archive>
    </archives>
  </remotePackage>
  <remotePackage path="ndk;30.0.16248370"><archives></archives></remotePackage>
</sdk:sdk-repository>
"""


def test_the_archive_of_a_version(ndk):
    assert ndk["ndk_archive"](INDEX, "29.0.14206865", "linux") == (
        "android-ndk-r29-linux.zip", 783549481, "87e2bb7e9be5d6a1c6cdf5ec40dd4e0c6d07c30b")
    assert ndk["ndk_archive"](INDEX, "29.0.14206865", "macosx")[0] == "android-ndk-r29-darwin.zip"
    assert ndk["ndk_archive"](INDEX, "29.0.14206865", "windows") is None
    assert ndk["ndk_archive"](INDEX, "28.0.0", "linux") is None


def zip_with(entries):
    """A zip of (name, data, unix mode) entries; a mode with S_IFLNK makes a symlink."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            z.writestr(info, data)
    return buf.getvalue()


def test_unpacking_keeps_modes_and_symlinks(ndk, tmp_path):
    archive = tmp_path / "ndk.zip"
    archive.write_bytes(zip_with([
        ("android-ndk-r29/ndk-which", b"#!/bin/sh\n", stat.S_IFREG | 0o755),
        ("android-ndk-r29/bin/clang-21", b"\x7fELF clang", stat.S_IFREG | 0o755),
        ("android-ndk-r29/bin/clang", b"clang-21", stat.S_IFLNK | 0o777),
        ("android-ndk-r29/source.properties", b"Pkg.Revision = 29.0.14206865\n", stat.S_IFREG | 0o644)]))
    ndk["extract_zip"](str(archive), str(tmp_path / "out"))
    root = tmp_path / "out" / "android-ndk-r29"
    assert (root / "source.properties").read_text().startswith("Pkg.Revision")
    if os.name != "nt":
        assert os.access(root / "ndk-which", os.X_OK) and os.access(root / "bin" / "clang-21", os.X_OK)
        assert os.path.islink(root / "bin" / "clang") and os.readlink(root / "bin" / "clang") == "clang-21"


def test_unpacking_refuses_paths_outside(ndk, tmp_path):
    archive = tmp_path / "evil.zip"
    archive.write_bytes(zip_with([("../outside.txt", b"x", stat.S_IFREG | 0o644)]))
    with pytest.raises(ValueError):
        ndk["extract_zip"](str(archive), str(tmp_path / "out"))
    assert not (tmp_path / "outside.txt").exists()


class FakeCM:
    def __init__(self):
        self.calls = []

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def error(self, text):
        return {"return": 1, "error": text}

    def access(self, ii):
        self.calls.append(ii["name"])
        ii["ctx"]["tasks"]["global"]["google-android-sdk-command-line-tools"] = {"qpath": "/sdk/bin/sdkmanager"}
        return {"return": 0}


def test_linux_arm_falls_back_to_sdkmanager(ndk):
    t = ndk["CTool"].__new__(ndk["CTool"])
    t.cm = FakeCM()
    t.cdesc = {"default_version": "29.0.14206865"}
    ctx = {"control": {}, "tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "linux", "uarch": "aarch64"}}}}}
    r = t.install(ctx, {"control": {}})
    assert r["return"] == 16 and r["install_cmd"] == '/sdk/bin/sdkmanager "ndk;29.0.14206865"'
    assert t.cm.calls == ["google.android-sdk.command-line-tools,2ee8eb31da764eef"]
