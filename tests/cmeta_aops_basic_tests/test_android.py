"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of running llama.cpp on an Android device (--compute=android-cpu):

* task/setup-run/android.py - the stamp that decides whether a folder is pushed again;
* tool/llama-cpp - the Android release asset, and its build recorded for detect_versions;
* category/program/api/common_llama_cpp.py - what a run keeps on the device, and its paths;
* task/setup-run - no "rm -rf /data/local/tmp/" for a program without a binary of its own.
"""

import os
import pathlib
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_head(rel_path, class_line, imports):
    """The module-level code of a hook file, up to its class (which needs cMeta)."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    head = src[:src.index(class_line)] if class_line else src
    for line in imports:
        head = head.replace(line, "")
    ns = {"__name__": "helpers"}
    exec(compile(head, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def android():
    return load_head("task/setup-run/android.py", None, [])


@pytest.fixture(scope = "module")
def tool():
    return load_head("tool/llama-cpp/api_v1.py", "\nclass CTool",
                     ["from tool_c393ba5c6fa14f66.api.ctool import InitCTool"])


@pytest.fixture(scope = "module")
def common():
    return load_head("category/program/api/common_llama_cpp.py", None, [])


def test_stamp_changes_with_the_files(android, tmp_path):
    a, b = tmp_path / "llama-completion", tmp_path / "libllama.so"
    a.write_bytes(b"x" * 10)
    b.write_bytes(b"y" * 20)
    s1 = android["stamp_of"]([str(a), str(b)])
    assert s1 == android["stamp_of"]([str(b), str(a)]), "the order of the files does not matter"
    b.write_bytes(b"y" * 21)
    assert android["stamp_of"]([str(a), str(b)]) != s1


def test_device_paths(android):
    assert android["device_path"]("/data/local/tmp", "cmeta-models/m.gguf") == "/data/local/tmp/cmeta-models/m.gguf"
    assert android["device_path"]("/data/local/tmp", "/sdcard/x") == "/sdcard/x"


def test_push_folder_refuses_missing_files(android, tmp_path):
    pushed, error = android["push_folder"]("adb", "serial", [str(tmp_path / "missing.so")], "/data/local/tmp/x")
    assert not pushed and "no such file" in error


def test_android_release_assets(tool):
    sel = tool["select_asset"]
    assert sel("11324", "android", "arm64", "cpu") == {"asset": "llama-b11324-bin-android-arm64.tar.gz"}
    assert sel("11324", "android", "aarch64", "snapdragon") == {"asset": "llama-b11324-bin-android-arm64-snapdragon.tar.gz"}
    assert "error" in sel("11324", "android", "arm64", "vulkan")
    assert tool["backend_from_compute"](["android-cpu"], "android") == "cpu"


def test_android_release_version_marker(tool, tmp_path):
    exe = tmp_path / "llama-cli"
    exe.write_bytes(b"\x7fELF")
    assert tool["android_release_version"](str(exe)) is None
    (tmp_path / tool["ANDROID_RELEASE_FILE"]).write_text("version: (build 11324) llama-b11324-bin-android-arm64.tar.gz\n",
                                                         encoding = "utf-8")
    text = tool["android_release_version"]("!" + str(exe))
    assert "(build 11324)" in text


def test_android_run_keeps_binary_libraries_and_model(common, tmp_path):
    for name in ("llama-completion", "libllama.so", "libggml-cpu-android_armv9.2_2.so", "llama-server"):
        (tmp_path / name).write_bytes(b"x")
    model = tmp_path / "qwen.gguf"
    model.write_bytes(b"m")
    a = common["android_run"](str(tmp_path), "llama-completion", "release-b11324-cpu", str(model))
    assert a["exe"] == "/data/local/tmp/cmeta-llama-cpp/release-b11324-cpu/llama-completion"
    assert a["model"] == "/data/local/tmp/cmeta-models/qwen.gguf"
    files = [os.path.basename(f) for f in a["setup_run"]["android_push_folders"]["cmeta-llama-cpp/release-b11324-cpu"]]
    assert files == ["llama-completion", "libggml-cpu-android_armv9.2_2.so", "libllama.so"], "only the run binary and the libraries"
    assert a["setup_run"]["android_push_files"] == {"cmeta-models/qwen.gguf": str(model)}
    assert a["setup_run"]["android_ld_library_path"] == ["cmeta-llama-cpp/release-b11324-cpu"]
    assert a["setup_run"]["android_skip_pull"] == ["perf.json"]


def test_target_run_here_and_on_android(common, tmp_path):
    class CM:
        @staticmethod
        def q(p):
            return f'"{p}"' if " " in p else p

    exe = tmp_path / "bin" / "llama-completion"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    model = tmp_path / "m.gguf"
    model.write_bytes(b"m")

    def ctx(compute):
        return {"tasks": {"local": {"model": {"path": str(model)}}, "global": {"target": {"compute": compute}}}}

    c = ctx(["cuda"])
    assert common["target_run"](CM, c, str(exe), "v") is False
    assert c["tasks"]["local"]["llama_cpp_exe"] == CM.q(str(exe)) and c["tasks"]["local"]["llama_cpp_setup_run"] == {}

    c = ctx(["android-cpu"])
    assert common["target_run"](CM, c, str(exe), "source-b11324-tmp") is True
    local = c["tasks"]["local"]
    assert local["llama_cpp_exe"] == "/data/local/tmp/cmeta-llama-cpp/source-b11324-tmp/llama-completion"
    assert local["llama_cpp_model"] == "/data/local/tmp/cmeta-models/m.gguf"


def test_setup_run_never_empties_the_device_work_folder():
    """With no binary of its own (a release), "rm -rf /data/local/tmp/" would delete everything there."""
    src = (REPO_ROOT / "task" / "setup-run" / "api_v1.py").read_text(encoding = "utf-8")
    rm = src.index("shell \"rm -rf {adb_tmp_path}/{target_exe}\"")
    guard = src.rfind("if target_exe:", 0, rm)
    assert guard != -1 and rm - guard < 400
