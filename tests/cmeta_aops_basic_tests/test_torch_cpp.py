"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of LibTorch for C++ programs: tool/torch-cpp-prebuilt (the pinned archives and their
URLs, the build chosen for the compute, the GPUs and the driver, the unpacking), common_libtorch.py
(the version of a LibTorch folder), tool/torch-cpp (--with.build; the cache identity of its builds
unchanged; the prebuilt setup not cached), program/build-torch-cpp (strict compute by default) and
program/test-nmm-torch-cpp (the same options for its compile and run steps).
"""

import os
import pathlib
import re
import stat
import zipfile

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

VERSION_H = """#pragma once

/// Indicates the major version of LibTorch.
#define TORCH_VERSION_MAJOR 2

/// Indicates the minor version of LibTorch.
#define TORCH_VERSION_MINOR 7

/// Indicates the patch version of LibTorch.
#define TORCH_VERSION_PATCH 1

/// Indicates the version of LibTorch as a string literal.
#define TORCH_VERSION \\
  "2.7.1"
"""


def load(rel_path, imports = {}, inject = {}):
    """The module's namespace, with its cMeta imports replaced and names injected."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in imports.items():
        assert line in src
        src = src.replace(line, replacement)
    ns = {"__name__": path.parent.name, "__file__": str(path)}
    ns.update(inject)
    exec(compile(src, str(path), "exec"), ns)
    return ns


def desc(rel_path):
    return yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding = "utf-8"))


@pytest.fixture(scope = "module")
def common():
    return load("category/tool/api/common_libtorch.py")


@pytest.fixture(scope = "module")
def prebuilt(common):
    return load("tool/torch-cpp-prebuilt/api_v1.py",
                {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass",
                 "from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256": "",
                 "from tool_c393ba5c6fa14f66.api.common_libtorch import found_paths_with_versions, add_path_features": ""},
                {k: common[k] for k in ("found_paths_with_versions", "add_path_features")})


@pytest.fixture(scope = "module")
def torch_cpp(common):
    return load("tool/torch-cpp/api_v1.py",
                {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass",
                 "from tool_c393ba5c6fa14f66.api.common_libtorch import found_paths_with_versions, add_path_features": ""},
                {k: common[k] for k in ("found_paths_with_versions", "add_path_features")})


class FakeCM:
    def error(self, text):
        return {"return": 1, "error": text}

    def q(self, path):
        return f'"{path}"' if " " in path else path


# tool/torch-cpp-prebuilt: archives and builds

def test_archives(prebuilt):
    for version, archives in prebuilt["ARCHIVES"].items():
        for (system, cpu, build), (name, sha256) in archives.items():
            assert re.fullmatch(r"[0-9a-f]{64}", sha256)
            assert version in name and name.endswith(".zip")
            assert name.endswith(f"+{build}.zip") or (system == "darwin" and build == "cpu")
            url, _name, _sha = prebuilt["archive"](version, (system, cpu), build)
            assert url.startswith(f"https://download.pytorch.org/libtorch/{build}/libtorch-")
            assert "+" not in url and url.endswith(name.replace("+", "%2B"))


def test_cuda_builds(prebuilt):
    """Every CUDA archive has its architectures, and the CUDA version of its name."""
    for version, archives in prebuilt["ARCHIVES"].items():
        for (system, cpu, build) in archives:
            if build.startswith("cu"):
                cuda_version, archs = prebuilt["CUDA_BUILDS"][version][(system, build)]
                assert cuda_version == int(build[2:]) and archs == sorted(archs)


def test_runs_on(prebuilt):
    runs_on = prebuilt["runs_on"]
    assert runs_on([80], 86) and runs_on([50], 52) and runs_on([120], 120) and runs_on([60], 61)
    assert not runs_on([90], 86) and not runs_on([86], 80) and not runs_on([100], 120) and not runs_on([75], 80)


@pytest.mark.parametrize("system, compute, gpus, driver, variant, expected", [
    (("linux", "amd64"), ["cpu"], [], None, None, "cpu"),
    (("windows", "amd64"), ["cpu"], [], None, None, "cpu"),
    (("darwin", "arm64"), ["metal"], [], None, None, "cpu"),          # one macOS build: CPU and MPS
    (("windows", "arm64"), ["cpu"], [], None, None, "cpu"),
    (("windows", "amd64"), ["cuda"], [120], 133, None, "cu128"),     # Blackwell: only cu128
    (("linux", "amd64"), ["cuda"], [86], 132, None, "cu128"),        # the newest the driver supports
    (("linux", "amd64"), ["cuda"], [86], 126, None, "cu126"),
    (("linux", "amd64"), ["cuda"], [86], 124, None, "cu118"),
    (("linux", "amd64"), ["cuda"], [86], 110, None, "cu118"),        # minor version compatibility
    (("linux", "amd64"), ["cuda"], [90], None, None, "cu128"),       # Linux cu118 has no sm_90
    (("windows", "amd64"), ["cuda"], [90], 118, None, "cu118"),      # Windows cu118 has
    (("linux", "amd64"), ["cuda"], [37], None, None, "cu118"),       # Kepler: only cu118
    (("linux", "amd64"), ["cuda"], [86, 50], None, None, "cu128"),   # code for every GPU
    (("linux", "amd64"), ["cuda"], [86], None, "cu126", "cu126"),    # asked for
    (("linux", "amd64"), ["cpu"], [], None, "cu118", "cu118"),
])
def test_choose_variant(prebuilt, system, compute, gpus, driver, variant, expected):
    build, error = prebuilt["choose_variant"]("2.7.1", system, compute, gpus = gpus, driver_cuda = driver, variant = variant)
    assert error is None and build == expected


@pytest.mark.parametrize("version, system, compute, gpus, driver, variant, message", [
    ("2.7.1", ("linux", "amd64"), ["cuda"], [35], None, None, "has code for the GPUs"),
    ("2.7.1", ("linux", "amd64"), ["cuda"], [120], 118, None, "older than the CUDA builds"),
    ("2.7.1", ("linux", "amd64"), ["cuda"], [86], None, "cu999", 'build "cu999"'),
    ("2.7.1", ("darwin", "arm64"), ["cuda"], [], None, None, "no CUDA build"),
    ("2.7.1", ("darwin", "arm64"), ["cpu"], [], None, "cu128", 'build "cu128"'),
    ("2.7.1", ("linux", "arm64"), ["cpu"], [], None, None, "for linux arm64"),
    ("2.7.1", ("linux", "amd64"), ["rocm"], [], None, None, "rocm"),
    ("9.9.9", ("linux", "amd64"), ["cpu"], [], None, None, "known"),
])
def test_choose_variant_errors(prebuilt, version, system, compute, gpus, driver, variant, message):
    build, error = prebuilt["choose_variant"](version, system, compute, gpus = gpus, driver_cuda = driver, variant = variant)
    assert build is None and message in error


def test_compute_list(prebuilt):
    assert prebuilt["compute_list"](None) == ["cpu"]
    assert prebuilt["compute_list"]("cpu, cuda") == ["cpu", "cuda"]
    assert prebuilt["compute_list"](["cuda"]) == ["cuda"]
    ctx = {"tasks": {"global": {"target": {"compute": ["cuda"]}}}}
    assert prebuilt["requested_compute"](ctx, {}) == ["cuda"]
    assert prebuilt["requested_compute"](ctx, {"compute": "cpu"}) == ["cpu"]


def test_extract(prebuilt, tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as z:
        info = zipfile.ZipInfo("libtorch/bin/tool")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        z.writestr(info, "#!/bin/sh\n")
        z.writestr("libtorch/lib/libtorch.so", b"\x7fELF")
        if os.name != "nt":
            link = zipfile.ZipInfo("libtorch/lib/libtorch.so.2")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(link, "libtorch.so")
    prebuilt["extract"](str(archive), str(tmp_path / "content"))
    assert (tmp_path / "content" / "libtorch" / "lib" / "libtorch.so").read_bytes() == b"\x7fELF"
    if os.name != "nt":
        assert os.stat(tmp_path / "content" / "libtorch" / "bin" / "tool").st_mode & 0o777 == 0o755
        assert os.readlink(tmp_path / "content" / "libtorch" / "lib" / "libtorch.so.2") == "libtorch.so"


# common_libtorch.py: the version and the paths of a LibTorch folder

def make_home(root, version_h = None, build_version = None, config_version = None):
    home = root / "libtorch"
    (home / "lib").mkdir(parents = True)
    (home / "lib" / "libtorch.so").write_bytes(b"")
    if version_h:
        h = home / "include" / "torch" / "csrc" / "api" / "include" / "torch"
        h.mkdir(parents = True)
        (h / "version.h").write_text(version_h)
    if build_version:
        (home / "build-version").write_text(build_version)
    if config_version:
        c = home / "share" / "cmake" / "Torch"
        c.mkdir(parents = True)
        (c / "TorchConfigVersion.cmake").write_text(config_version)
    return home


def test_libtorch_version(common, tmp_path):
    v = common["libtorch_version"]
    assert v(str(make_home(tmp_path / "a", version_h = VERSION_H))) == "2.7.1"
    assert v(str(make_home(tmp_path / "b", version_h = '#define TORCH_VERSION \\\n  "2.9.1"\n'))) == "2.9.1"
    assert v(str(make_home(tmp_path / "c", build_version = "2.7.1+cpu\n"))) == "2.7.1"
    assert v(str(make_home(tmp_path / "d", config_version = 'set(PACKAGE_VERSION "2.10.0")\n'))) == "2.10.0"
    assert v(str(make_home(tmp_path / "e"))) is None


def test_found_paths_with_versions(common, tmp_path):
    home = make_home(tmp_path, version_h = VERSION_H)
    lib = str(home / "lib" / "libtorch.so")
    found = common["found_paths_with_versions"]([lib, "!" + lib, str(tmp_path / "missing.so")], {"build": "prebuilt"})
    assert list(found) == [lib]
    assert found[lib]["output"] == "2.7.1"
    assert found[lib]["features"]["paths"] == {"home": str(home), "lib": str(home / "lib"), "include": str(home / "include")}
    tool = type("Tool", (), {"cm": FakeCM()})()
    paths = common["add_path_features"](tool, [{"path": lib}])
    assert paths[0]["features"]["paths"]["qlib"] == FakeCM().q(str(home / "lib"))


# tool/torch-cpp: --with.build, the cache identity, the prebuilt setup

def torch_cpp_tool(torch_cpp):
    t = object.__new__(torch_cpp["CTool"])
    t.cm = FakeCM()
    return t


@pytest.mark.parametrize("build", [None, "", "source", "Source"])
def test_build_source(torch_cpp, build):
    params = {"with": {} if build is None else {"build": build}}
    cparams = {}
    ctx = {"tasks": {"global": {}, "local": {}}}
    assert torch_cpp_tool(torch_cpp).check_params(ctx, params, cparams)["return"] == 0
    assert "build" not in params["with"] and cparams == {}
    assert not any(k in params for k in ("skip_detect", "skip_install", "skip_build"))
    assert params["with"]["compute"] == ["cpu"] and ctx["tasks"]["local"]["compute"] == ["cpu"]


def test_build_prebuilt(torch_cpp):
    params = {"with": {"build": " Prebuilt "}}
    cparams = {}
    ctx = {"tasks": {"global": {"target": {"compute": ["cuda"]}}, "local": {}}}
    assert torch_cpp_tool(torch_cpp).check_params(ctx, params, cparams)["return"] == 0
    assert params["with"]["build"] == "prebuilt" and params["with"]["compute"] == ["cuda"]
    assert cparams["cache"] is False
    assert params["skip_detect"] is False and params["skip_install"] is True and params["skip_build"] is True
    r = torch_cpp_tool(torch_cpp).check_params(ctx, {"with": {"build": "conda"}}, {})
    assert r["return"] == 1 and "--with.build=conda" in r["error"]
    # The archives have shared libraries only
    r = torch_cpp_tool(torch_cpp).check_params(ctx, {"with": {"build": "prebuilt", "static": "True"}}, {})
    assert r["return"] == 1 and "--with.static needs a source build" in r["error"]
    assert torch_cpp_tool(torch_cpp).check_params(ctx, {"with": {"build": "prebuilt", "static": False}}, {})["return"] == 0


def test_torch_cpp_desc():
    d = desc("tool/torch-cpp/_desc.yaml")
    # The cache identity of the builds is unchanged: no "build" (or other) key was added
    assert set(d["cache_meta_const"]["params"]["with"]) == {"compute", "static", "strict_compute", "ver"}
    assert d["skip_detect"] is True and "torch.dll" in d["names"]
    assert "torch-cpp-prebuilt" in d["force_tool_path"] and d["force_tool_path"].endswith("|}}")
    uid = desc("tool/torch-cpp-prebuilt/_cmeta.yaml")["artifact"]
    [use] = [u for u in d["uses"] if u.get("name") == f"torch-cpp-prebuilt,{uid}"]
    for value, expected in [("prebuilt", True), ("Prebuilt", True), ("", False), ("source", False)]:
        assert evaluate(use["if"], {"params.with.build": value}) is expected


def evaluate(condition, values):
    """A condition of a "uses" entry, expanded and evaluated as the engine does (no builtins)."""
    for key, value in values.items():
        condition = re.sub(r"\{\{" + re.escape(key) + r"\|[^}]*\}\}", str(value), condition)
    assert "{{" not in condition
    return bool(eval(condition, {"__builtins__": {}}, {}))


def test_prebuilt_desc():
    d = desc("tool/torch-cpp-prebuilt/_desc.yaml")
    assert d["skip_detect"] is True and d["default_version"] in load(
        "tool/torch-cpp-prebuilt/api_v1.py",
        {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass",
         "from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256": "",
         "from tool_c393ba5c6fa14f66.api.common_libtorch import found_paths_with_versions, add_path_features": ""})["ARCHIVES"]
    [use] = d["uses"]
    # --with.compute as given: a list, a string or nothing (the engine also evaluates it before check_params)
    for compute, variant, expected in [("['cuda']", "", True), ("cuda", "", True), ("cpu,cuda", "", True),
                                       ("['cpu']", "", False), ("", "", False), ("None", "", False),
                                       ("['cuda']", "cu126", False)]:
        assert evaluate(use["if"], {"params.with.compute": compute, "params.with.variant": variant}) is expected


# program/build-torch-cpp and program/test-nmm-torch-cpp

def test_strict_compute_by_default():
    is_strict = load("program/build-torch-cpp/api_v1.py",
                     {"from program_22788f3c30d04e6d.api.cprogram import InitCProgram": "class InitCProgram: pass"})["is_strict"]
    for value in (None, "", True, "True", "yes", 1):
        assert is_strict(value) is True
    for value in (False, "False", "false", "no", "0", 0, "off"):
        assert is_strict(value) is False


def find(node, predicate):
    if isinstance(node, dict):
        if predicate(node):
            yield node
        for v in node.values():
            yield from find(v, predicate)
    elif isinstance(node, list):
        for v in node:
            yield from find(v, predicate)


def test_program_options():
    d = desc("program/test-nmm-torch-cpp/_desc.yaml")
    entries = list(find(d, lambda n: str(n.get("name", "")).startswith("torch-cpp,")))
    assert len(entries) == 2   # the compile and the run steps
    for e in entries:
        assert e["with"].replace(" ", "") == "{{params.setup_torch_cpp|${}}}"
        assert e["_update"].replace(" ", "") == "{{params.setup_torch_cpp_task|${}}}"
    [run] = list(find(d, lambda n: "global_keys_with_dynamic_libs" in n))
    assert run["target_exe"].startswith("{{local.target_file_name|program}}")


# The install prefix of a source build: apart from the build tree, handed to the detection

def build_torch_cpp():
    return load("program/build-torch-cpp/api_v1.py",
                {"from program_22788f3c30d04e6d.api.cprogram import InitCProgram": "class InitCProgram: pass"})


def test_install_prefix_of(tmp_path):
    install_prefix_of = build_torch_cpp()["install_prefix_of"]
    build = str(tmp_path / "build")
    assert install_prefix_of(build) == os.path.join(build, "install")
    assert install_prefix_of(build, {}) == os.path.join(build, "install")
    # A prefix the build was given (quoted on the command line) wins
    assert install_prefix_of(build, {"CMAKE_INSTALL_PREFIX": '"/opt/lib torch"'}) == "/opt/lib torch"
    assert install_prefix_of(build, {"CMAKE_INSTALL_PREFIX": r"D:\x\prefix"}) == r"D:\x\prefix"


def test_customize_pytorch_installs_apart_from_the_build(tmp_path):
    ns = build_torch_cpp()
    prog = object.__new__(ns["CProgram"])
    prog.cm = FakeCM()
    build = tmp_path / "build"
    ctx = {"tasks": {"local": {"target_path": str(build)},
                     "run_control": {},
                     "global": {"target": {"compute": ["cpu"]}, "host": {"os": {"uname": "linux"}},
                                "ninja": {"qpath": "/n/ninja"}, "compiler-c": {"qpath": "/c/cc"},
                                "compiler-cpp": {"qpath": "/c/c++", "features": {}},
                                "python": {"qpath": "/v/.venv/bin/python", "path": "/v/.venv/bin/python"}}}}
    assert prog.customize_pytorch(ctx, {}, params = {"compile": {}})["return"] == 0
    local = ctx["tasks"]["local"]
    install = os.path.join(str(build), "install")
    assert local["install_prefix"] == install
    assert f"-DCMAKE_INSTALL_PREFIX={install}" in local["cmake_d_vars"]
    assert local["target_path_exe"] == os.path.join(install, "lib", "libtorch.so")
    assert local["run_time_env"]["PYTHONPATH"].startswith(os.path.join(install, "lib", "python"))
    # The build's own prefix is kept
    ctx["tasks"]["local"] = {"target_path": str(build)}
    assert prog.customize_pytorch(ctx, {}, params = {"compile": {"d": {"CMAKE_INSTALL_PREFIX": "/opt/torch"}}})["return"] == 0
    assert ctx["tasks"]["local"]["install_prefix"] == "/opt/torch"
    assert ctx["tasks"]["local"]["target_path_exe"] == os.path.join("/opt/torch", "lib", "libtorch.so")


def test_customize_test_uses_the_install_prefix(tmp_path):
    ns = build_torch_cpp()
    prog = object.__new__(ns["CProgram"])
    prog.cm = FakeCM()
    build = tmp_path / "build"
    torch_dir = build / "install" / "share" / "cmake" / "Torch"
    torch_dir.mkdir(parents = True)
    ctx = {"tasks": {"local": {"target_path": str(build)},
                     "global": {"target": {"compute": ["cpu"]}, "host": {"os": {"uname": "linux"}},
                                "ninja": {"path": "/n/ninja", "qpath": "/n/ninja"}}}}
    assert prog.customize_test(ctx, {})["return"] == 0
    local = ctx["tasks"]["local"]
    assert f"-DTorch_DIR={torch_dir}" in local["test_cmake_d_vars"]
    assert local["run_time_env"]["LD_LIBRARY_PATH"].startswith(os.path.join(str(build), "install", "lib"))
    assert local["test_build_path"] == os.path.join(str(build), "test-build")


@pytest.mark.parametrize("uname, library", [("linux", "libtorch.so"), ("darwin", "libtorch.dylib"), ("windows", "torch.dll")])
def test_tool_build_hands_the_installed_library_to_detection(torch_cpp, tmp_path, monkeypatch, uname, library):
    tool = torch_cpp_tool(torch_cpp)
    tool.cdesc = {"build_local": {"target_sub_dir": "build"}}
    monkeypatch.chdir(tmp_path)
    ctx = {"tasks": {"global": {"host": {"os": {"uname": uname}}}}}
    r = tool.build(ctx, {})
    assert r["return"] == 1 and "did not install" in r["error"]
    # The library of the build tree does not count: only the installed one
    (tmp_path / "build" / "lib").mkdir(parents = True)
    (tmp_path / "build" / "lib" / library).write_bytes(b"")
    assert tool.build(ctx, {})["return"] == 1
    (tmp_path / "build" / "install" / "lib").mkdir(parents = True)
    (tmp_path / "build" / "install" / "lib" / library).write_bytes(b"")
    r = tool.build(ctx, {})
    assert r["return"] == 0 and r["found_path"] == str(tmp_path / "build" / "install" / "lib" / library)
