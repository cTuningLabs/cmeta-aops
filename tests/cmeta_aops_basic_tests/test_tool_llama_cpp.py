"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the llama.cpp release-asset selection in tool/llama-cpp/api_v1.py:
the asset lists below are copied from real releases (b11324, b10000), so the choice of
platform, backend, CUDA build and cudart bundle is checked without network access.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ll():
    """The module-level helpers of tool/llama-cpp/api_v1.py (the CTool class needs cMeta)."""
    path = REPO_ROOT / "tool" / "llama-cpp" / "api_v1.py"
    src = path.read_text(encoding="utf-8")
    head = src[:src.index("\nclass CTool")]
    head = head.replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "")
    ns = {}
    exec(compile(head, str(path), "exec"), ns)
    return type("LlamaHelpers", (), {k: staticmethod(v) for k, v in ns.items() if callable(v)})


B11324 = [
    "cudart-llama-b11324-bin-ubuntu-cuda-12.8-x64.tar.gz",
    "cudart-llama-b11324-bin-ubuntu-cuda-13.4-arm64.tar.gz",
    "cudart-llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz",
    "cudart-llama-bin-win-cuda-12.4-x64.zip",
    "cudart-llama-bin-win-cuda-13.4-arm64.zip",
    "cudart-llama-bin-win-cuda-13.4-x64.zip",
    "llama-b11324-bin-macos-arm64.tar.gz",
    "llama-b11324-bin-macos-x64.tar.gz",
    "llama-b11324-bin-ubuntu-arm64.tar.gz",
    "llama-b11324-bin-ubuntu-cuda-12.8-x64.tar.gz",
    "llama-b11324-bin-ubuntu-cuda-13.4-arm64.tar.gz",
    "llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz",
    "llama-b11324-bin-ubuntu-openvino-2026.4-x64.tar.gz",
    "llama-b11324-bin-ubuntu-rocm-10.0-x64.tar.gz",
    "llama-b11324-bin-ubuntu-sycl-fp16-x64.tar.gz",
    "llama-b11324-bin-ubuntu-sycl-fp32-x64.tar.gz",
    "llama-b11324-bin-ubuntu-vulkan-arm64.tar.gz",
    "llama-b11324-bin-ubuntu-vulkan-x64.tar.gz",
    "llama-b11324-bin-ubuntu-x64.tar.gz",
    "llama-b11324-bin-win-cpu-arm64.zip",
    "llama-b11324-bin-win-cpu-x64.zip",
    "llama-b11324-bin-win-cuda-12.4-x64.zip",
    "llama-b11324-bin-win-cuda-13.4-arm64.zip",
    "llama-b11324-bin-win-cuda-13.4-x64.zip",
    "llama-b11324-bin-win-openvino-2026.4-x64.zip",
    "llama-b11324-bin-win-rocm-10.0-x64.zip",
    "llama-b11324-bin-win-sycl-x64.zip",
    "llama-b11324-bin-win-vulkan-x64.zip",
]

# Before Linux CUDA builds existed, with CUDA 13.3 on Windows
B10000 = [
    "cudart-llama-bin-win-cuda-12.4-x64.zip",
    "cudart-llama-bin-win-cuda-13.3-x64.zip",
    "llama-b10000-bin-macos-arm64.tar.gz",
    "llama-b10000-bin-ubuntu-arm64.tar.gz",
    "llama-b10000-bin-ubuntu-vulkan-x64.tar.gz",
    "llama-b10000-bin-ubuntu-x64.tar.gz",
    "llama-b10000-bin-win-cpu-x64.zip",
    "llama-b10000-bin-win-cuda-12.4-x64.zip",
    "llama-b10000-bin-win-cuda-13.3-x64.zip",
    "llama-b10000-bin-win-vulkan-x64.zip",
]


@pytest.mark.parametrize("uname, uarch, backend, driver, asset, cudart", [
    # CPU
    ("windows", "amd64", "cpu", None, "llama-b11324-bin-win-cpu-x64.zip", None),
    ("windows", "arm64", "cpu", None, "llama-b11324-bin-win-cpu-arm64.zip", None),
    ("linux", "amd64", "cpu", None, "llama-b11324-bin-ubuntu-x64.tar.gz", None),
    ("linux", "arm64", "cpu", None, "llama-b11324-bin-ubuntu-arm64.tar.gz", None),   # was "linux-arm64": a 404
    ("darwin", "arm64", "metal", None, "llama-b11324-bin-macos-arm64.tar.gz", None),
    ("darwin", "arm64", "cpu", None, "llama-b11324-bin-macos-arm64.tar.gz", None),
    ("darwin", "amd64", "cpu", None, "llama-b11324-bin-macos-x64.tar.gz", None),

    # CUDA: the newest build of the driver's major version (minor-version compatibility)
    ("windows", "amd64", "cuda", "13.3", "llama-b11324-bin-win-cuda-13.4-x64.zip", "cudart-llama-bin-win-cuda-13.4-x64.zip"),
    ("windows", "amd64", "cuda", "12.8", "llama-b11324-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"),
    ("windows", "arm64", "cuda", "13.3", "llama-b11324-bin-win-cuda-13.4-arm64.zip", "cudart-llama-bin-win-cuda-13.4-arm64.zip"),
    ("linux", "amd64", "cuda", "13.3", "llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz", "cudart-llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz"),
    ("linux", "amd64", "cuda", "13.0", "llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz", "cudart-llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz"),
    ("linux", "amd64", "cuda", "12.9", "llama-b11324-bin-ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-b11324-bin-ubuntu-cuda-12.8-x64.tar.gz"),
    ("linux", "arm64", "cuda", "13.3", "llama-b11324-bin-ubuntu-cuda-13.4-arm64.tar.gz", "cudart-llama-b11324-bin-ubuntu-cuda-13.4-arm64.tar.gz"),

    # Vulkan, SYCL, ROCm, OpenVINO
    ("windows", "amd64", "vulkan", None, "llama-b11324-bin-win-vulkan-x64.zip", None),
    ("linux", "amd64", "vulkan", None, "llama-b11324-bin-ubuntu-vulkan-x64.tar.gz", None),
    ("linux", "arm64", "vulkan", None, "llama-b11324-bin-ubuntu-vulkan-arm64.tar.gz", None),
    ("windows", "amd64", "sycl", None, "llama-b11324-bin-win-sycl-x64.zip", None),
    ("linux", "amd64", "sycl", None, "llama-b11324-bin-ubuntu-sycl-fp16-x64.tar.gz", None),
    ("linux", "amd64", "rocm", None, "llama-b11324-bin-ubuntu-rocm-10.0-x64.tar.gz", None),
    ("windows", "amd64", "openvino", None, "llama-b11324-bin-win-openvino-2026.4-x64.zip", None),
])
def test_select_asset_b11324(ll, uname, uarch, backend, driver, asset, cudart):
    sel = ll.select_asset("11324", uname, uarch, backend, assets=B11324, cuda_driver=driver)
    assert sel.get("asset") == asset, sel
    assert sel.get("cudart") == cudart, sel


def test_minor_version_compatibility_note(ll):
    sel = ll.select_asset("11324", "windows", "amd64", "cuda", assets=B11324, cuda_driver="13.3")
    assert sel["cuda"] == "13.4"
    assert "minor-version compatibility" in sel["note"]
    sel = ll.select_asset("11324", "windows", "amd64", "cuda", assets=B11324, cuda_driver="13.4")
    assert "note" not in sel


def test_select_asset_older_release(ll):
    sel = ll.select_asset("10000", "windows", "amd64", "cuda", assets=B10000, cuda_driver="13.3")
    assert sel["asset"] == "llama-b10000-bin-win-cuda-13.3-x64.zip"
    assert sel["cudart"] == "cudart-llama-bin-win-cuda-13.3-x64.zip"

    # no Linux CUDA build in that release: an error, so setup falls back to a source build
    assert "error" in ll.select_asset("10000", "linux", "amd64", "cuda", assets=B10000, cuda_driver="13.3")


def test_forced_cuda_version(ll):
    sel = ll.select_asset("11324", "windows", "amd64", "cuda", assets=B11324, cuda_driver="13.3", cuda_wanted="12.4")
    assert sel["asset"] == "llama-b11324-bin-win-cuda-12.4-x64.zip"
    sel = ll.select_asset("11324", "windows", "amd64", "cuda", assets=B11324, cuda_driver="13.3", cuda_wanted="11.8")
    assert "error" in sel and "13.4, 12.4" in sel["error"]


def test_driver_too_old_and_unsupported(ll):
    assert "error" in ll.select_asset("11324", "linux", "amd64", "cuda", assets=B11324, cuda_driver="11.8")
    assert "error" in ll.select_asset("11324", "darwin", "arm64", "vulkan", assets=B11324)
    assert "error" in ll.select_asset("11324", "linux", "amd64", "metal", assets=B11324)
    assert "error" in ll.select_asset("11324", "linux", "riscv64", "cpu", assets=B11324)


def test_offline_naming_rules(ll):
    """Without the asset list: the naming rules, and the newest CUDA build of the driver's major."""
    sel = ll.select_asset("11324", "linux", "amd64", "cuda", assets=None, cuda_driver="13.3")
    assert sel["asset"] == "llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz"
    assert ll.select_asset("11324", "windows", "amd64", "vulkan")["asset"] == "llama-b11324-bin-win-vulkan-x64.zip"


@pytest.mark.parametrize("compute, uname, backend", [
    (["cpu"], "linux", "cpu"),
    (["cpu"], "darwin", "metal"),
    (["cpu", "cuda"], "windows", "cuda"),
    (["vulkan"], "linux", "vulkan"),
    (["metal"], "darwin", "metal"),
    (["xpu"], "linux", "sycl"),
])
def test_backend_from_compute(ll, compute, uname, backend):
    assert ll.backend_from_compute(compute, uname, llama_target_backends()) == backend


def test_a_cuda_build_must_carry_kernels_for_the_gpu(ll):
    """CUDA 13 dropped Maxwell, Pascal and Volta: a GeForce 940MX (sm_50) with a driver for CUDA 13.0 gets the CUDA 12
    build, never the CUDA 13.4 one (its run ended with exit 99 on the T470p, 2026-10-30)."""
    sel = ll.select_asset("11324", "linux", "amd64", "cuda", assets=B11324, cuda_driver="13.0", gpu_arch_min=50)
    assert sel["asset"] == "llama-b11324-bin-ubuntu-cuda-12.8-x64.tar.gz", sel
    assert sel["cudart"] == "cudart-llama-b11324-bin-ubuntu-cuda-12.8-x64.tar.gz" and "sm_50" in sel["note"]
    sel = ll.select_asset("11324", "windows", "amd64", "cuda", assets=B11324, cuda_driver="13.0", gpu_arch_min=61)
    assert sel["asset"] == "llama-b11324-bin-win-cuda-12.4-x64.zip", sel

    # a newer GPU keeps the newest build; an unknown GPU too
    for arch in (75, 86, 120, None):
        sel = ll.select_asset("11324", "linux", "amd64", "cuda", assets=B11324, cuda_driver="13.4", gpu_arch_min=arch)
        assert sel["asset"] == "llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz" and "note" not in sel, (arch, sel)

    # a forced build is taken as asked; a GPU no build carries kernels for is an error that names the way out
    sel = ll.select_asset("11324", "linux", "amd64", "cuda", assets=B11324, cuda_driver="13.0", cuda_wanted="13.4",
                          gpu_arch_min=50)
    assert sel["asset"] == "llama-b11324-bin-ubuntu-cuda-13.4-x64.tar.gz"
    sel = ll.select_asset("11324", "linux", "amd64", "cuda", assets=B11324, cuda_driver="13.0", gpu_arch_min=35)
    assert "error" in sel and "build-llama-cpp" in sel["error"]


# Stable releases (v1.0.0 = build 12359, 2026-11-13): names of builds, resolved from the releases the tool lists,
# else from upstream's file nightly-tag.txt of the release

def _releases():
    import yaml

    desc = yaml.safe_load((REPO_ROOT / "tool" / "llama-cpp" / "_desc.yaml").read_text(encoding="utf-8"))
    return desc


def test_a_stable_release_is_the_build_the_tool_lists(ll):
    desc = _releases()
    known = desc["releases"]

    assert ll.build_of_release("1.0.0", known)["build"] == "12359"
    assert ll.build_of_release("v1.1.0", known)["build"] == "12774"

    # every key is a release name and every value a build number; the pin is a build
    import re

    assert all(re.fullmatch(r"[0-9]+[.][0-9]+[.][0-9]+", k) and str(v).isdigit() for k, v in known.items())
    assert str(desc["default_version"]).isdigit()


def test_a_build_number_a_range_and_a_word_are_no_release_names(ll):
    for version in (12774, "12774", ">=1.0.0", "latest", "known", "1.1", "b12774", "", None):
        assert ll.build_of_release(version, {"1.1.0": 12774}) is None, version


def test_a_release_the_tool_does_not_list_is_read_from_upstream(ll, monkeypatch):
    import io
    import urllib.error
    import urllib.request

    asked = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout = None):
        asked.append(request.full_url)
        if "/v2.0.0/" in request.full_url:
            return Answer(b"b13000\n")
        if "/v2.0.1/" in request.full_url:
            return Answer(b"<html>not a build</html>")
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    r = ll.build_of_release("2.0.0", {"1.1.0": 12774})
    assert r["build"] == "13000" and r["release"] == "2.0.0"
    assert asked == ["https://github.com/ggml-org/llama.cpp/releases/download/v2.0.0/nightly-tag.txt"]

    # a listed release asks nobody
    assert ll.build_of_release("1.1.0", {"1.1.0": 12774})["build"] == "12774" and len(asked) == 1

    # no such release, and a file that names no build: an error that says so, never a guess
    assert "no stable release 9.9.9" in ll.build_of_release("9.9.9", {})["error"]
    assert "names no build" in ll.build_of_release("2.0.1", {})["error"]


def llama_target_backends():
    """`target_backends` of tool/llama-cpp/_desc.yaml: the targets that select a backend of a release build."""
    import pathlib

    import yaml

    desc = pathlib.Path(__file__).resolve().parents[2] / 'tool' / 'llama-cpp' / '_desc.yaml'
    return yaml.safe_load(desc.read_text(encoding = 'utf-8'))['target_backends']
