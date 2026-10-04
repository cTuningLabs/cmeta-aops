"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/executorch-android and tool/android-d8: the dependencies read from the POMs,
the layout of an unpacked AAR, and installs from a fake Maven repository checked against its
SHA-256 (SHA-1 where there is none).
"""

import hashlib
import io
import json
import os
import pathlib
import zipfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel_path):
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool:\n    pass")
    ns = {"__name__": "tool_under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def et():
    return load("tool/executorch-android/api_v1.py")


@pytest.fixture(scope = "module")
def d8():
    return load("tool/android-d8/api_v1.py")


def pom(deps):
    items = "".join(f"<dependency><groupId>{g}</groupId><artifactId>{a}</artifactId><version>{v}</version>"
                    f"<scope>{s}</scope></dependency>" for g, a, v, s in deps)
    return ('<?xml version="1.0"?><project xmlns="http://maven.apache.org/POM/4.0.0">'
            f"<dependencies>{items}</dependencies></project>")


AAR_POM = pom([("org.jetbrains.kotlin", "kotlin-stdlib", "1.9.23", "compile"),
               ("com.facebook.fbjni", "fbjni", "0.7.0", "runtime"),
               ("androidx.core", "core-ktx", "1.13.1", "runtime"),
               ("junit", "junit", "4.13", "test")])
FBJNI_POM = pom([("com.facebook.soloader", "nativeloader", "0.10.5", "runtime")])


def test_pom_dependencies(et):
    deps = et["pom_dependencies"](AAR_POM)
    assert ("org.jetbrains.kotlin", "kotlin-stdlib", "1.9.23") in deps
    assert not any(a == "junit" for _, a, _ in deps)                  # test scope left out


def test_needed_artifacts(et):
    found = et["needed_artifacts"]({("org.pytorch", "executorch-android"): AAR_POM, ("com.facebook.fbjni", "fbjni"): FBJNI_POM})
    assert found == {("org.jetbrains.kotlin", "kotlin-stdlib"): "1.9.23", ("com.facebook.fbjni", "fbjni"): "0.7.0",
                     ("com.facebook.soloader", "nativeloader"): "0.10.5"}             # no androidx


def aar(libs):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("classes.jar", b"PK classes")
        z.writestr("AndroidManifest.xml", "<manifest/>")
        for path in libs:
            z.writestr(path, b"\x7fELF " + path.encode())
    return buf.getvalue()


def test_unpack_an_aar(et, tmp_path):
    f = tmp_path / "x.aar"
    f.write_bytes(aar(["jni/arm64-v8a/libexecutorch.so", "jni/x86_64/libexecutorch.so", "jni/armeabi-v7a/libexecutorch.so"]))
    et["unpack"](str(f), str(tmp_path / "root"), "executorch-android")
    root = tmp_path / "root"
    assert (root / "jars" / "executorch-android.jar").read_bytes() == b"PK classes"
    assert (root / "jni" / "arm64-v8a" / "libexecutorch.so").is_file()
    assert (root / "jni" / "x86_64" / "libexecutorch.so").is_file()
    assert not (root / "jni" / "armeabi-v7a").exists()                # not an ABI of the tool


class FakeCM:
    """download-file from a dict {url: bytes}; a missing URL fails like a 404."""

    def __init__(self, server):
        self.server = server

    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def access(self, ii):
        data = self.server.get(ii["url"])
        if data is None:
            return {"return": 1, "error": "404 " + ii["url"]}
        d = os.path.join(os.getcwd(), ii["directory"])
        os.makedirs(d, exist_ok = True)
        with open(os.path.join(d, ii["filename"]), "wb") as f:
            f.write(data)
        return {"return": 0}


def maven(et):
    url = et["maven_url"]
    files = {
        url("org.pytorch", "executorch-android", "1.5.1", "aar"): aar(["jni/arm64-v8a/libexecutorch.so",
                                                                       "jni/x86_64/libexecutorch.so"]),
        url("org.pytorch", "executorch-android", "1.5.1", "pom"): AAR_POM.encode(),
        url("com.facebook.fbjni", "fbjni", "0.7.0", "aar"): aar(["jni/arm64-v8a/libfbjni.so",
                                                                 "jni/arm64-v8a/libc++_shared.so"]),
        url("com.facebook.fbjni", "fbjni", "0.7.0", "pom"): FBJNI_POM.encode(),
        url("com.facebook.soloader", "nativeloader", "0.10.5", "jar"): b"PK nativeloader",
        url("com.facebook.soloader", "nativeloader", "0.10.5", "pom"): pom([]).encode(),
        url("org.jetbrains.kotlin", "kotlin-stdlib", "1.9.23", "jar"): b"PK kotlin",
        url("org.jetbrains.kotlin", "kotlin-stdlib", "1.9.23", "pom"): pom([]).encode(),
    }
    for u, data in list(files.items()):
        if u.endswith((".aar", ".jar")):
            if "kotlin" in u:      # an old artifact: SHA-1 only
                files[u + ".sha1"] = hashlib.sha1(data).hexdigest().encode()
            else:
                files[u + ".sha256"] = (hashlib.sha256(data).hexdigest() + "\n").encode()
    return files


def tool(ns, server):
    t = ns["CTool"].__new__(ns["CTool"])
    t.cm = FakeCM(server)
    t.cdesc = {"default_version": "1.5.1"}
    return t


CTX = {"control": {}, "tasks": {"nested_call": 0, "global": {}}}


def test_install_from_maven(et, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = tool(et, maven(et))
    r = t.install(CTX, {"control": {}})
    assert r["return"] == 0, r
    root = tmp_path / "content" / "1.5.1"
    assert pathlib.Path(r["found_path"]) == root / "jni" / "arm64-v8a" / "libexecutorch.so"
    assert sorted(p.name for p in (root / "jars").iterdir()) == ["executorch-android.jar", "fbjni.jar",
                                                                 "kotlin-stdlib.jar", "nativeloader.jar"]
    marker = json.loads((root / et["MARKER"]).read_text())
    assert marker["artifacts"]["org.jetbrains.kotlin:kotlin-stdlib"]["digest"].startswith("sha1:")
    assert marker["artifacts"]["org.pytorch:executorch-android"]["digest"].startswith("sha256:")
    assert not (tmp_path / "downloads").exists()

    # what detect() reports for it
    parsed = t.detect(CTX, {})["parsed_paths_with_versions"]
    assert len(parsed) == 1 and parsed[0]["detected_version"] == "1.5.1"
    assert set(parsed[0]["features"]["jni"]) == {"arm64-v8a", "x86_64"}


def test_install_refuses_a_wrong_digest(et, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    files = maven(et)
    files[et["maven_url"]("com.facebook.fbjni", "fbjni", "0.7.0", "aar") + ".sha256"] = b"0" * 64
    r = tool(et, files).install(CTX, {"control": {}})
    assert r["return"] == 1 and "fbjni-0.7.0.aar: sha256" in r["error"]


def test_d8_checks_the_published_digest(d8, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url = d8["GOOGLE_MAVEN"].format(version = "9.4.28")
    jar = b"PK r8"
    t = tool(d8, {url: jar, url + ".sha256": hashlib.sha256(jar).hexdigest().encode()})
    t.cdesc = {"default_version": "9.4.28"}
    r = t.install(CTX, {"control": {}})
    assert r["return"] == 0 and pathlib.Path(r["found_path"]).name == "r8.jar"

    t = tool(d8, {url: jar, url + ".sha256": b"f" * 64})
    t.cdesc = {"default_version": "9.4.28"}
    r = t.install(CTX, {"control": {}, "version": None})
    assert r["return"] == 1 and "SHA-256" in r["error"] and not (tmp_path / "content" / "r8.jar").exists()
