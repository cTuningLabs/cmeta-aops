"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/pip-mlx: the MLX backend for the targets and the host (Metal, CUDA 13 or
12, CPU), the platforms without one, and mlx-cpu named on Windows (its extra is Linux-only).
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def mlx():
    path = REPO_ROOT / "tool" / "pip-mlx" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool:\n    pass")
    ns = {"__name__": "pip_mlx", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.mark.parametrize("compute, uname, uarch, driver, arch, want", [
    (["cpu"], "darwin", "arm64", None, None, []),                 # Metal and the CPU in the macOS wheel
    (["cpu", "metal"], "darwin", "arm64", None, None, []),
    (["cpu"], "linux", "amd64", None, None, ["cpu"]),
    (["cpu"], "windows", "amd64", None, None, ["cpu"]),
    (["cuda"], "linux", "amd64", "13.3", 120, ["cuda13"]),
    (["cuda"], "linux", "amd64", "13.0", 50, ["cuda12"]),
    (["cuda"], "linux", "aarch64", "12.8", 87, ["cuda12"]),
])
def test_the_backend(mlx, compute, uname, uarch, driver, arch, want):
    assert mlx["mlx_extras"](compute, uname, uarch, driver, arch) == (want, None)


@pytest.mark.parametrize("compute, uname, uarch, driver, hint", [
    (["cuda"], "windows", "amd64", "13.3", "Linux only"),
    (["cuda"], "linux", "amd64", "11.8", "CUDA 12 or newer"),
    (["cpu"], "darwin", "amd64", None, "Apple silicon"),
    (["metal"], "linux", "amd64", None, "Apple silicon"),
])
def test_no_backend_here(mlx, compute, uname, uarch, driver, hint):
    extras, error = mlx["mlx_extras"](compute, uname, uarch, driver)
    assert extras is None and hint in error


class FakeCM:
    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}


def check(mlx, uname, params, compute = ("cpu",)):
    t = mlx["CTool"].__new__(mlx["CTool"])
    t.cm = FakeCM()
    ctx = {"control": {"con": False},
           "tasks": {"global": {"host": {"os": {"uname": uname, "uarch": "amd64"}},
                                "target": {"compute": list(compute), "features": {}}}}}
    return t.check_params2(ctx, params, {})


def test_windows_names_mlx_cpu(mlx):
    params = {"with": {"package": "mlx"}}
    assert check(mlx, "windows", params)["return"] == 0
    assert params["with"]["extras"] == ["cpu"] and params["with"]["post_flags"] == "mlx-cpu"
    params = {"with": {"package": "mlx"}, "version": "0.32.3"}
    check(mlx, "windows", params)
    assert params["with"]["post_flags"] == "mlx-cpu==0.32.3"
    params = {"with": {"package": "mlx"}}
    check(mlx, "linux", params)
    assert params["with"]["extras"] == ["cpu"] and "post_flags" not in params["with"]
    assert params["with"]["variations"]["mlx_backend"] == "cpu"
