"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/pip-jax: the JAX plugin for the targets and the host (CUDA 13 or 12, ROCm,
Intel oneAPI, Apple Metal), the platforms without one, the integrated Intel GPUs that the oneAPI
plugin does not run, and what check_params2 asks pip for.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def jax():
    """tool/pip-jax/api_v1.py with a stand-in for its cMeta base class."""
    path = REPO_ROOT / "tool" / "pip-jax" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "class InitCTool:\n    pass")
    ns = {"__name__": "pip_jax", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


IRIS_XE = "Intel Corporation Raptor Lake-P [Iris Xe Graphics] (rev 04)"
HD_630 = "Intel Corporation HD Graphics 630 (rev 04)"
ARC_A770 = "Intel Corporation DG2 [Arc A770] (rev 08)"
ARC_LUNAR = "Intel Corporation Lunar Lake [Intel Arc Graphics 130V / 140V] (rev 04)"


@pytest.mark.parametrize("compute, uname, uarch, driver, arch, want", [
    (["cpu"], "windows", "amd64", None, None, []),
    (["cuda"], "linux", "amd64", "13.3", 86, ["cuda13"]),       # RTX A500
    (["cuda"], "linux", "amd64", "13.3", 120, ["cuda13"]),      # Blackwell, in WSL2
    (["cuda"], "linux", "amd64", "13.0", 50, ["cuda12"]),       # 940MX: CUDA 13 builds for sm_75+
    (["cuda"], "linux", "aarch64", "12.4", 87, ["cuda12"]),     # a CUDA 12 driver
    (["cpu", "cuda"], "linux", "amd64", None, None, ["cuda13"]),
    (["rocm"], "linux", "amd64", None, None, ["rocm7-local"]),
])
def test_the_plugin(jax, compute, uname, uarch, driver, arch, want):
    extras, packages, error = jax["jax_plugin"](compute, uname, uarch, driver, arch)
    assert (extras, packages, error) == (want, [], None)


@pytest.mark.parametrize("compute, uname, uarch, driver, hint", [
    (["cuda"], "windows", "amd64", "13.3", "WSL2"),
    (["cuda"], "darwin", "arm64", None, "Linux only"),
    (["cuda"], "linux", "amd64", "11.8", "CUDA 12 or newer"),
    (["rocm"], "windows", "amd64", None, "Linux x86_64 only"),
    (["xpu"], "windows", "amd64", None, "Linux x86_64 only"),
    (["metal"], "linux", "amd64", None, "Apple silicon"),
])
def test_no_plugin_here(jax, compute, uname, uarch, driver, hint):
    extras, packages, error = jax["jax_plugin"](compute, uname, uarch, driver)
    assert extras is None and hint in error


def test_metal(jax):
    assert jax["jax_plugin"](["cpu", "metal"], "darwin", "arm64") == ([], [jax["METAL_PLUGIN"]], None)


def test_extras_given(jax):
    assert jax["jax_plugin"](["cuda"], "windows", "amd64", extras = "cuda13-local, tpu") == (["cuda13-local", "tpu"], [], None)


def test_the_intel_gpus(jax):
    old = jax["old_intel_gpus"]
    assert old([IRIS_XE]) == [IRIS_XE]
    assert old([HD_630, "NVIDIA Corporation GM108M [GeForce 940MX] (rev a2)"]) == [HD_630]
    assert old([ARC_A770]) == [] and old([ARC_LUNAR]) == []
    assert old([IRIS_XE, ARC_A770]) == []          # an Arc next to the iGPU: try the plugin
    assert old([]) == []

    plugin = jax["jax_plugin"]
    extras, _, error = plugin(["xpu"], "linux", "amd64", intel_gpus = [IRIS_XE])
    assert extras is None and "Iris Xe" in error and "--with.any_intel_gpu" in error
    assert plugin(["xpu"], "linux", "amd64", intel_gpus = [IRIS_XE], any_intel_gpu = True)[0] == ["oneapi"]
    assert plugin(["xpu"], "linux", "amd64", intel_gpus = [ARC_A770])[0] == ["oneapi"]
    assert "WSL2" in plugin(["xpu"], "linux", "amd64", intel_gpus = [ARC_A770], wsl = True)[2]


class FakeCM:
    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)


def context(compute, uname = "linux", uarch = "amd64", python = "3.13.15", cuda = None, xpu = None):
    g = {"host": {"os": {"uname": uname, "uarch": uarch}}, "target": {"compute": compute, "features": {}},
         "python": {"version": python}}
    if cuda:
        g["cuda"] = {"features": cuda}
    if xpu:
        g["target--xpu"] = {"features": {"devices": [{"name": n} for n in xpu]}}
    return {"control": {"con": False}, "tasks": {"global": g}}


def tool(jax):
    t = jax["CTool"].__new__(jax["CTool"])
    t.cm = FakeCM()
    return t


def test_check_params_cuda(jax):
    params = {"with": {"package": "jax"}}
    ctx = context(["cuda"], cuda = {"versions": {"cuda version": "13.0"}, "compute_cap_int_min": 50})
    assert tool(jax).check_params2(ctx, params, {})["return"] == 0
    assert params["with"]["extras"] == ["cuda12"]
    assert params["with"]["variations"] == {"compute": ["cuda"], "jax_plugin": "cuda12"}
    assert "version" not in params


def test_check_params_metal(jax):
    params = {"with": {"package": "jax"}}
    assert tool(jax).check_params2(context(["cpu", "metal"], "darwin", "arm64"), params, {})["return"] == 0
    assert params["version"] == jax["METAL_JAX"]
    assert params["with"]["post_flags"] == jax["METAL_PLUGIN"]
    assert params["with"]["variations"]["jax_plugin"] == jax["METAL_PLUGIN"]

    # a newer Python has no wheels of that JAX
    r = tool(jax).check_params2(context(["metal"], "darwin", "arm64", python = "3.14.4"), {"with": {}}, {})
    assert r["return"] == 1 and '--use.python.version=">=3.10,<3.14"' in r["error"]

    # another JAX asked for: no Python check, the plugin still added
    params = {"with": {"package": "jax"}, "version": "0.4.35"}
    assert tool(jax).check_params2(context(["metal"], "darwin", "arm64", python = "3.14.4"), params, {})["return"] == 0
    assert params["version"] == "0.4.35" and jax["METAL_PLUGIN"] in params["with"]["post_flags"]


def test_check_params_old_intel_gpu(jax, monkeypatch):
    monkeypatch.setattr(jax["os"].path, "exists", lambda p: False)     # not WSL2
    r = tool(jax).check_params2(context(["xpu"], xpu = [HD_630]), {"with": {}}, {})
    assert r["return"] == 1 and "HD Graphics 630" in r["error"]
    params = {"with": {"any_intel_gpu": True}}
    assert tool(jax).check_params2(context(["xpu"], xpu = [HD_630]), params, {})["return"] == 0
    assert params["with"]["extras"] == ["oneapi"]
