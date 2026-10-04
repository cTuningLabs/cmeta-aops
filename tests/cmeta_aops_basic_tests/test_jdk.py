"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of common_jdk (the archive and SHA-256 of each vendor's JDK for each system, the javac
of an unpacked JDK) and the tools jdk-<vendor> (the major version in the cache identity, the result
stored as "openjdk"), of tool/javac and tool/java (the default JDK as before, a vendor's with
--with.vendor; the version pattern of OpenJDK and Oracle builds) and of task/compiler's tool_with.
"""

import json
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def jdk():
    path = REPO_ROOT / "category" / "tool" / "api" / "common_jdk.py"
    src = path.read_text(encoding = "utf-8").replace(
        "from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256", "")
    ns = {"__name__": "common_jdk", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def desc(rel_path):
    return yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding = "utf-8"))


def fake_get(pages):
    """A get() that answers from {url prefix: text} and records the URLs asked for."""
    asked = []

    def get(url, timeout = 60):
        asked.append(url)
        for prefix, text in pages.items():
            if url.startswith(prefix):
                return text
        raise AssertionError(f"unexpected URL {url}")
    get.asked = asked
    return get


def test_temurin(jdk):
    release = {"binaries": [{"package": {"link": "https://x/OpenJDK25U.tar.gz", "checksum": "AB", "name": "OpenJDK25U.tar.gz"}}]}
    get = fake_get({"https://api.adoptium.net/v3/assets/feature_releases/25/ga": json.dumps([release]),
                    "https://api.adoptium.net/v3/assets/release_name/eclipse/jdk-25.0.2%2B10": json.dumps(release)})
    info, error = jdk["resolve"]("temurin", "25", None, "darwin", "arm64", get = get)
    assert error is None and info == {"url": "https://x/OpenJDK25U.tar.gz", "sha256": "AB", "filename": "OpenJDK25U.tar.gz"}
    assert "architecture=aarch64&os=mac" in get.asked[-1]
    jdk["resolve"]("temurin", "25", "25.0.2+10", "linux", "amd64", musl = True, get = get)
    assert "jdk-25.0.2%2B10?architecture=x64&os=alpine-linux" in get.asked[-1]


def test_microsoft_corretto_oracle(jdk):
    get = fake_get({"https://aka.ms/": "d3b0  microsoft-jdk-25.0.4.1-windows-x64.zip\n",
                    "https://corretto.aws/downloads/latest_sha256/": "a45f\n",
                    "https://download.oracle.com/": "dd7e\n"})
    info, _ = jdk["resolve"]("microsoft", "25", None, "windows", "amd64", get = get)
    assert info["url"] == "https://aka.ms/download-jdk/microsoft-jdk-25-windows-x64.zip" and info["sha256"] == "d3b0"
    assert info["filename"] == "microsoft-jdk-25.0.4.1-windows-x64.zip"
    info, _ = jdk["resolve"]("corretto", "21", None, "darwin", "arm64", get = get)
    assert info["url"] == "https://corretto.aws/downloads/latest/amazon-corretto-21-aarch64-macos-jdk.tar.gz"
    info, _ = jdk["resolve"]("oracle", "25", None, "linux", "arm64", get = get)
    assert info["url"] == "https://download.oracle.com/java/25/latest/jdk-25_linux-aarch64_bin.tar.gz" and info["sha256"] == "dd7e"
    assert "--with.feature" in jdk["resolve"]("oracle", "25", "25.0.1", "linux", "amd64", get = get)[1]


def test_zulu(jdk):
    get = fake_get({"https://api.azul.com/metadata/v1/zulu/packages/?": json.dumps(
                        [{"package_uuid": "u1", "download_url": "https://cdn.azul.com/z.zip", "name": "z.zip"}]),
                    "https://api.azul.com/metadata/v1/zulu/packages/u1": json.dumps({"sha256_hash": "c2e6"})})
    info, error = jdk["resolve"]("zulu", "25", None, "windows", "amd64", get = get)
    assert error is None and info == {"url": "https://cdn.azul.com/z.zip", "sha256": "c2e6", "filename": "z.zip"}
    assert "crac_supported=false" in get.asked[0] and "archive_type=zip" in get.asked[0]


def test_no_build(jdk):
    assert "musl" in jdk["resolve"]("zulu", "25", None, "linux", "amd64", musl = True)[1]
    assert "no JDK" in jdk["resolve"]("temurin", "25", None, "linux", "riscv64")[1]
    assert "unknown JDK vendor" in jdk["resolve"]("sun", "25", None, "linux", "amd64", get = fake_get({}))[1]


def test_find_javac(jdk, tmp_path):
    mac = tmp_path / "mac" / "zulu25-macosx_aarch64" / "zulu-25.jdk" / "Contents" / "Home" / "bin"
    mac.mkdir(parents = True)
    (mac / "javac").write_text("")
    (mac.parents[3] / "jmods" / "bin").mkdir(parents = True)
    assert jdk["find_javac"](str(tmp_path / "mac")) == str(mac / "javac")
    win = tmp_path / "win" / "jdk-25.0.4.1" / "bin"
    win.mkdir(parents = True)
    (win / "javac.exe").write_text("")
    assert jdk["find_javac"](str(tmp_path / "win"), ".exe") == str(win / "javac.exe")
    assert jdk["find_javac"](str(tmp_path / "none")) is None


def test_vendor_tools(jdk):
    params = {}
    jdk["jdk_init"](None, params)
    assert params["with"] == {"feature": "25"}
    params = {"with": {"feature": 21}}
    jdk["jdk_init"](None, params)
    assert params["with"]["feature"] == "21"
    for vendor in ("temurin", "microsoft", "corretto", "zulu", "oracle"):
        d = desc(f"tool/jdk-{vendor}/_desc.yaml")
        assert d["storage_key"] == "openjdk" and d["skip_detect"] is True and d["cache_params"] == ["with.feature"]
        api = (REPO_ROOT / "tool" / f"jdk-{vendor}" / "api_v1.py").read_text(encoding = "utf-8")
        assert f"VENDOR = '{vendor}'" in api


def test_java_and_javac_keep_the_default(tmp_path):
    for tool in ("java", "javac"):
        d = desc(f"tool/{tool}/_desc.yaml")
        assert "cache_params" not in d                 # the identity follows the JDK's path, as before
        default, vendor = d["uses"]
        assert default["name"] == "openjdk,5bc3b6e965174534" and "with" not in default
        assert default["if"] == '"{{params.with.vendor|}}" == ""' and vendor["if"] == '"{{params.with.vendor|}}" != ""'
        assert vendor["name"] == "jdk-{{params.with.vendor}}"


def test_compiler_tool_with():
    path = REPO_ROOT / "task" / "compiler" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace(
        "from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask:\n    pass")
    ns = {"__name__": "compiler", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    t = ns["CTask"].__new__(ns["CTask"])

    class CM:
        def check_params(self, params, keys, name):
            return {"return": 0}

        def catch_error(self, r):
            return r["return"] > 0
    t.cm = CM()
    params = {"lang": "javac", "tool_with": {"vendor": None, "feature": None}}
    t.init({}, params)
    assert "tool_with" not in params                # no vendor: the cache identity is unchanged
    params = {"lang": "javac", "tool_with": {"vendor": "zulu", "feature": None}}
    t.init({}, params)
    assert params["tool_with"] == {"vendor": "zulu"}
    assert "tool_with" not in desc("task/compiler/_desc.yaml")["cache_params"]


def test_java_version_pattern():
    desc = yaml.safe_load((REPO_ROOT / "tool" / "java" / "_desc.yaml").read_text(encoding = "utf-8"))
    pattern = desc["match_version"][0]["regex"]
    for text, want in (('openjdk version "25.0.4.1" 2026-07-21 LTS\nOpenJDK Runtime Environment', "25.0.4.1"),
                       ('java version "21.0.5" 2024-10-15 LTS\nJava(TM) SE Runtime Environment', "21.0.5"),
                       ('openjdk version "21.0.7" 2025-04-15 LTS', "21.0.7")):
        assert re.search(pattern, text).group(1) == want


def test_openjdk_build_for_the_libc(monkeypatch):
    """tool/openjdk (the default JDK): Temurin's alpine-linux build on musl Linux, the linux build on glibc."""
    import types
    path = REPO_ROOT / "tool" / "openjdk" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool: pass")
    ns = {"__name__": "tool_openjdk", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)

    asked = []
    tool = object.__new__(ns["CTool"])
    tool.cm = types.SimpleNamespace(debug = False, access = lambda p: asked.append(p) or {"return": 0},
                                    catch_error = lambda r: r["return"] > 0)
    ctx = {"tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "linux", "uarch": "amd64"},
                                                           "vars": {"file_ext_exe": ""}}}}}
    for libc, build in [(("glibc", "2.39"), "_x64_linux_"), (("", ""), "_x64_alpine-linux_"), (("musl", "1.2.5"), "_x64_alpine-linux_")]:
        monkeypatch.setattr(ns["platform"], "libc_ver", lambda *a, **k: libc)
        assert tool.install(ctx, {"control": {}})["return"] == 0
        assert build in asked[-1]["url"]
