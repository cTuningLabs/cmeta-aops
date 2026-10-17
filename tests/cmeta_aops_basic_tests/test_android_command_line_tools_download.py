"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/google.android-sdk.command-line-tools' download: the zip of a release for a host OS and CPU
in Google's repository index, the unpacking into cmdline-tools/latest/ (file modes, nothing outside the target), and
the declared routes (no winget package since 2026-10, brew only as macOS's fallback).
"""

import io
import os
import pathlib
import stat
import zipfile

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tool" / "google.android-sdk.command-line-tools"


@pytest.fixture(scope = "module")
def cli():
    path = TOOL / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "class InitCTool:\n    pass")
    ns = {"__name__": "cli_tool", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


INDEX = """<?xml version="1.0"?>
<sdk:sdk-repository xmlns:sdk="http://schemas.android.com/sdk/android/repo/repository2/03">
  <remotePackage path="cmdline-tools;23.0">
    <archives>
      <archive><complete><size>181052239</size><checksum type="sha1">E025545C62A8E64C7559119566A569FB1DEC5F60</checksum>
        <url>commandlinetools-linux-16111833_latest.zip</url></complete><host-os>linux</host-os></archive>
      <archive><complete><size>155582504</size><checksum type="sha1">112cf9618794a997ff273537d55bee02c22abffe</checksum>
        <url>commandlinetools-mac_x86_64-16111833_latest.zip</url></complete><host-os>macosx</host-os><host-arch>x64</host-arch></archive>
      <archive><complete><size>155384151</size><checksum type="sha1">ad03dc49bfacfd52c110b14104ea548b8a07e830</checksum>
        <url>commandlinetools-mac_arm64-16111833_latest.zip</url></complete><host-os>macosx</host-os><host-arch>aarch64</host-arch></archive>
      <archive><complete><size>154957218</size><checksum type="sha1">57d04f2d75eb8e8fffc5000a987e5de4b5a63e9d</checksum>
        <url>commandlinetools-win-16111833_latest.zip</url></complete><host-os>windows</host-os></archive>
    </archives>
  </remotePackage>
  <remotePackage path="cmdline-tools;21.0">
    <archives>
      <archive><complete><size>152127646</size><checksum type="sha1">0123456789abcdef0123456789abcdef01234567</checksum>
        <url>commandlinetools-mac-15641748_latest.zip</url></complete><host-os>macosx</host-os></archive>
    </archives>
  </remotePackage>
</sdk:sdk-repository>
"""


def test_the_archive_of_a_release(cli):
    a = cli["archive_of"]
    assert a(INDEX, "23.0", "linux", "x64") == ("commandlinetools-linux-16111833_latest.zip", 181052239,
                                                "e025545c62a8e64c7559119566a569fb1dec5f60")
    assert a(INDEX, "23.0", "linux", "aarch64")[0] == "commandlinetools-linux-16111833_latest.zip"   # Java: any CPU
    assert a(INDEX, "23.0", "windows", "x64")[0] == "commandlinetools-win-16111833_latest.zip"
    assert a(INDEX, "23.0", "macosx", "aarch64")[0] == "commandlinetools-mac_arm64-16111833_latest.zip"
    assert a(INDEX, "23.0", "macosx", "x64")[0] == "commandlinetools-mac_x86_64-16111833_latest.zip"
    assert a(INDEX, "21.0", "macosx", "aarch64")[0] == "commandlinetools-mac-15641748_latest.zip"   # one zip before 22.0
    assert a(INDEX, "23", "linux", "x64") is None and a(INDEX, "22.0", "linux", "x64") is None


def zip_with(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            z.writestr(info, data)
    return buf.getvalue()


def test_the_version_lookup_reads_the_index():
    import re
    desc = yaml.safe_load((TOOL / "_desc.yaml").read_text(encoding = "utf-8"))
    assert re.findall(desc["cmd_get_versions_regex"], INDEX) == ["23.0", "21.0"]


def test_unpacking_into_latest(cli, tmp_path):
    archive = tmp_path / "cli.zip"
    archive.write_bytes(zip_with([
        ("cmdline-tools/bin/sdkmanager", b"#!/bin/sh\n", stat.S_IFREG | 0o755),
        ("cmdline-tools/lib/sdkmanager-classpath.jar", b"PK", stat.S_IFREG | 0o644),
        ("cmdline-tools/source.properties", b"Pkg.Revision=23.0\n", stat.S_IFREG | 0o644)]))
    dest = tmp_path / "content" / "cmdline-tools" / "latest"
    cli["unpack"](str(archive), str(dest))
    assert (dest / "source.properties").read_text().startswith("Pkg.Revision")
    assert (dest / "lib" / "sdkmanager-classpath.jar").is_file()
    if os.name != "nt":
        assert os.access(dest / "bin" / "sdkmanager", os.X_OK)


def test_unpacking_refuses_paths_outside(cli, tmp_path):
    archive = tmp_path / "evil.zip"
    archive.write_bytes(zip_with([("cmdline-tools/../../outside.txt", b"x", stat.S_IFREG | 0o644)]))
    with pytest.raises(ValueError):
        cli["unpack"](str(archive), str(tmp_path / "out"))
    assert not (tmp_path / "outside.txt").exists()


def test_sdkmanager_runs_through_java_on_windows(cli, tmp_path):
    """Google's .bat drops the "!" of JAVA_HOME: on Windows the tool's command is sdkmanager's Java entry point."""
    tools = tmp_path / "!sdk" / "cmdline-tools" / "latest"
    (tools / "bin").mkdir(parents = True)
    (tools / "lib").mkdir()
    (tools / "lib" / "sdkmanager-classpath.jar").write_bytes(b"PK")
    jdk = tmp_path / "!Progs" / "jdk-21" / "bin"
    jdk.mkdir(parents = True)
    (jdk / "java.exe").write_bytes(b"MZ")

    def ctx(uname):
        return {"tasks": {"global": {"host": {"os": {"uname": uname}}, "openjdk": {"path_bin": str(jdk)}}}}

    cmd = cli["sdkmanager_java_cmd"](ctx("windows"), str(tools / "bin"))
    assert cmd.startswith(f'"{jdk / "java.exe"}" "-Dcom.android.sdklib.toolsdir={tools}" -classpath ')
    assert cmd.endswith("com.android.sdklib.tool.sdkmanager.SdkManagerCli")
    assert cli["sdkmanager_java_cmd"](ctx("linux"), str(tools / "bin")) is None

    # 23.0: no jar (its .bat is a shim of the Android CLI)
    (tools / "lib" / "sdkmanager-classpath.jar").unlink()
    assert cli["sdkmanager_java_cmd"](ctx("windows"), str(tools / "bin")) is None


def test_the_declared_routes():
    desc = yaml.safe_load((TOOL / "_desc.yaml").read_text(encoding = "utf-8"))
    assert desc["default_version"] and int(desc["default_version"].split(".")[0]) < 23
    assert any(x["exclude"] == ">=23" for x in desc["latest_limits"])
    assert set(desc["install_cmd"]) == {"darwin"} and set(desc["install_cmd_version"]) == {"darwin"}
    assert "install_uses" not in desc
