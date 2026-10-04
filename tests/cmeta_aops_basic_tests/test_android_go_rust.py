"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the Android builds of Go and Rust programs: tool/go-android (GOOS, GOARCH and
-buildmode=pie from the device's ABI), tool/rustc-android (the Rust target, the NDK's clang as the
linker, the target's standard library added once with rustup), the environment that
task/setup-compile passes to the compile command (a cross-compiler's own, then the program's; a
host compiler without one gets exactly the program's as before), and the compute targets that the
tools and programs declare.
"""

import json
import os
import pathlib
import types

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel_path, imports):
    """The module's namespace, with its cMeta imports replaced."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in imports.items():
        assert line in src
        src = src.replace(line, replacement)
    ns = {"__name__": path.parent.name.replace("-", "_"), "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


TOOL_IMPORT = {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass"}
TASK_IMPORT = {"from task_c36be4b9314a45e0.api.ctask import InitCTask": "class InitCTask: pass"}


def quote(path):
    return f'"{path}"' if " " in path else path


def fake_cm(run = None):
    """The part of cMeta the hooks use: error, catch_error, q and utils.sys.run."""
    return types.SimpleNamespace(
        error = lambda text, code = 1: {"return": code, "error": text},
        catch_error = lambda r, fail16 = False: r["return"] > 0,
        q = quote,
        utils = types.SimpleNamespace(sys = types.SimpleNamespace(run = run)))


def instance(ns, cls, cm):
    obj = object.__new__(ns[cls])
    obj.cm = cm
    return obj


def android_ctx(abi = "arm64-v8a", **globals_):
    return {"control": {"con": False},
            "tasks": {"global": {"target--android-cpu": {"features": {"ro.product.cpu.abi": abi}},
                                 "host": {"os_env": {}}, **globals_},
                      "aggregated": {"env": {"RUSTUP_HOME": "/r", "CARGO_HOME": "/r"}}}}


def meta(rel_path):
    path = REPO_ROOT / rel_path
    text = path.read_text(encoding = "utf-8")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


# tool/go-android

@pytest.fixture(scope = "module")
def go():
    return load("tool/go-android/api_v1.py", TOOL_IMPORT)


def test_go_env_per_abi(go):
    assert go["android_env"]("arm64-v8a") == ({"GOOS": "android", "GOARCH": "arm64", "CGO_ENABLED": "0"}, None)
    assert go["android_env"]("armeabi-v7a")[0] == {"GOOS": "android", "GOARCH": "arm", "GOARM": "7", "CGO_ENABLED": "0"}
    assert go["android_env"]("x86_64")[0]["GOARCH"] == "amd64"
    assert go["android_env"]("x86")[0]["GOARCH"] == "386"
    env, error = go["android_env"]("mips")
    assert env is None and "mips" in error


def test_go_finish_dynamic_result(go):
    tool = instance(go, "CTool", fake_cm())
    result = {"path": "go", "features": {"flags": {"force_build": "build"}}}
    assert tool.finish_dynamic_result(android_ctx(), result)["return"] == 0
    assert result["features"]["env"] == {"GOOS": "android", "GOARCH": "arm64", "CGO_ENABLED": "0"}
    assert result["features"]["target_arch"]["flags"] == "-buildmode=pie"
    assert result["features"]["flags"] == {"force_build": "build"}

    # No Android target (e.g. "cx tool setup go-android" alone): nothing is set
    result = {"path": "go", "features": {}}
    ctx = {"control": {}, "tasks": {"global": {}}}
    assert tool.finish_dynamic_result(ctx, result) == {"return": 0} and result["features"] == {}

    assert tool.finish_dynamic_result(android_ctx(abi = "riscv64"), {"features": {}})["return"] > 0


# tool/rustc-android

@pytest.fixture(scope = "module")
def rust():
    return load("tool/rustc-android/api_v1.py", TOOL_IMPORT)


def test_rust_targets_and_flags(rust):
    assert rust["RUST_TARGETS"]["arm64-v8a"] == "aarch64-linux-android"
    assert rust["RUST_TARGETS"]["armeabi-v7a"] == "armv7-linux-androideabi"
    linker = "C:\\Program Files (x86)\\Android\\ndk\\clang.exe"
    assert rust["target_flags"]("aarch64-linux-android", linker, "aarch64-linux-android35", quote) == \
        '--target aarch64-linux-android -C linker="C:\\Program Files (x86)\\Android\\ndk\\clang.exe" ' \
        '-C link-arg=--target=aarch64-linux-android35'


class FakeRun:
    """utils.sys.run for "rustc --print sysroot" and "rustup target add" (which makes the folder)."""

    def __init__(self, sysroot, add_ok = True):
        self.sysroot, self.add_ok, self.commands = sysroot, add_ok, []

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        assert kwargs["envs"] == {"RUSTUP_HOME": "/r", "CARGO_HOME": "/r"}
        if "--print sysroot" in cmd:
            return {"return": 0, "returncode": 0, "stdout": str(self.sysroot) + "\n", "stderr": ""}
        if self.add_ok:
            os.makedirs(os.path.join(self.sysroot, "lib", "rustlib", "aarch64-linux-android", "lib"))
            return {"return": 0, "returncode": 0, "stdout": "", "stderr": ""}
        return {"return": 0, "returncode": 1, "stdout": "", "stderr": "error: no network"}


def rust_globals(tmp_path):
    return {"android-ndk-clang": {"path": "/ndk/bin/clang",
                                  "features": {"target_arch": {"clang_target": "aarch64-linux-android35",
                                                               "api_level": 35}}},
            "rustup": {"path": "/r/bin/rustup"}}


def test_rust_finish_dynamic_result_adds_the_target_once(rust, tmp_path):
    sysroot = tmp_path / "toolchains" / "stable-x86_64-pc-windows-msvc"
    sysroot.mkdir(parents = True)
    run = FakeRun(sysroot)
    tool = instance(rust, "CTool", fake_cm(run))
    ctx = android_ctx(**rust_globals(tmp_path))

    result = {"path": "/r/bin/rustc", "features": {}}
    assert tool.finish_dynamic_result(ctx, result)["return"] == 0
    arch = result["features"]["target_arch"]
    assert arch["rust_target"] == "aarch64-linux-android" and arch["clang_target"] == "aarch64-linux-android35"
    assert arch["flags"] == ("--target aarch64-linux-android -C linker=/ndk/bin/clang "
                             "-C link-arg=--target=aarch64-linux-android35")
    assert run.commands == ["/r/bin/rustc --print sysroot",
                            "/r/bin/rustup target add aarch64-linux-android --toolchain stable-x86_64-pc-windows-msvc"]

    # Installed now: only the sysroot is asked for
    run.commands.clear()
    assert tool.finish_dynamic_result(ctx, {"path": "/r/bin/rustc", "features": {}})["return"] == 0
    assert run.commands == ["/r/bin/rustc --print sysroot"]


def test_rust_errors(rust, tmp_path):
    sysroot = tmp_path / "toolchain"
    sysroot.mkdir()
    tool = instance(rust, "CTool", fake_cm(FakeRun(sysroot, add_ok = False)))
    r = tool.finish_dynamic_result(android_ctx(**rust_globals(tmp_path)), {"path": "rustc", "features": {}})
    assert r["return"] > 0 and "rustup target add aarch64-linux-android" in r["error"] and "no network" in r["error"]

    no_clang = android_ctx(rustup = {"path": "rustup"})
    assert "NDK" in tool.finish_dynamic_result(no_clang, {"path": "rustc", "features": {}})["error"]
    assert tool.finish_dynamic_result(android_ctx(abi = "mips"), {"features": {}})["return"] > 0

    ctx = {"control": {}, "tasks": {"global": {}}}
    assert tool.finish_dynamic_result(ctx, {"features": {}}) == {"return": 0}


# task/setup-compile: the environment of the compile command

@pytest.fixture(scope = "module")
def setup_compile():
    return load("task/setup-compile/api_v1.py", TASK_IMPORT)


def compile_with(setup_compile, tmp_path, features, program_env):
    task = instance(setup_compile, "CTask", fake_cm())
    ctx = {"tasks": {"global": {"compiler-go": {"qpath": "go", "features": features}}}}
    src = tmp_path / "src"
    src.mkdir(exist_ok = True)
    return task.run(ctx, lang = "go", target_path = str(tmp_path / "out"), src_path = str(src),
                    src_file_names = ["program.go"], **{"with": {"env": program_env, "pre_target_exe_flag": True}})


def test_setup_compile_env(setup_compile, tmp_path):
    host = {"flags": {"force_build": "build", "exe_file": "-o "}, "vars": {"file_ext_exe": ".exe"}}
    r = compile_with(setup_compile, tmp_path, host, {"GOFLAGS": "-mod=mod"})
    assert r["compile_env"] == {"GOFLAGS": "-mod=mod"}                      # as before: the program's only
    assert r["add_to_local"]["compile_cmds"][0].startswith("go build -o ")
    assert r["target_exe"] == "program.exe"

    android = {"flags": {"force_build": "build", "exe_file": "-o "}, "vars": {"file_ext_exe": None},
               "env": {"GOOS": "android", "GOARCH": "arm64", "CGO_ENABLED": "0"},
               "target_arch": {"flags": "-buildmode=pie"}}
    r = compile_with(setup_compile, tmp_path, android, {"CGO_ENABLED": "1"})
    assert r["compile_env"] == {"GOOS": "android", "GOARCH": "arm64", "CGO_ENABLED": "1"}   # the program's wins
    assert " -buildmode=pie " in r["add_to_local"]["compile_cmds"][0]
    assert r["target_exe"] == "program"


# The compute targets declared

def test_declared_targets():
    for tool, tag in [("go-android", "lang-go"), ("rustc-android", "lang-rust")]:
        m = meta(f"tool/{tool}/_cmeta.yaml")
        assert tag in m["tags"] and m["constraints"]["supports_compute"] == ["android-cpu"]
    # The host tools stay as they were, so a cpu build selects them
    for tool in ["go", "rustc"]:
        assert meta(f"tool/{tool}/_cmeta.yaml")["constraints"]["supports_compute"] == ["cpu"]

    for program in ["test-nmm-go-cpu", "test-nmm-rust-cpu"]:
        assert set(meta(f"program/{program}/_cmeta.json")["constraints"]["supported_compute"]) == {"android-cpu", "cpu"}
    # No Swift compiler for Android: the program does not claim it
    assert meta("program/test-nmm-swift-cpu/_cmeta.json")["constraints"]["supported_compute"] == ["cpu"]

    # The tools reuse the host toolchains (the same go and rustc)
    assert yaml.safe_load((REPO_ROOT / "tool/go-android/_desc.yaml").read_text())["force_tool_path"] == "{{global.go.path}}"
    assert yaml.safe_load((REPO_ROOT / "tool/rustc-android/_desc.yaml").read_text())["force_tool_path"] == "{{global.rustc.path}}"
