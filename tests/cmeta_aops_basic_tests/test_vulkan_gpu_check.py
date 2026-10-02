"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the Vulkan hardware checks: tool/vulkan finds no GPU before it would install
Mesa (sudo) for Vulkan on the CPU only, and target--vulkan fails when Vulkan sees only CPU
devices (llvmpipe), unless allow_cpu.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel_path, base_import, base_class):
    """A hook file with a stand-in for its base class (the real one needs cMeta)."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8").replace(base_import, f"class {base_class}:\n    pass")
    ns = {"__name__": "hooks", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def vulkan_tool():
    return load("tool/vulkan/api_v1.py", "from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "InitCTool")


@pytest.fixture(scope = "module")
def vulkan_target():
    return load("task/target--vulkan/api_v1.py", "from task_c36be4b9314a45e0.api.ctask import InitCTask", "InitCTask")


def pci(root, name, cls, vendor, device):
    d = root / name
    d.mkdir(parents = True)
    for key, value in (("class", cls), ("vendor", vendor), ("device", device)):
        (d / key).write_text(value + "\n")


def test_pci_display_devices(vulkan_tool, tmp_path):
    pci_display_devices = vulkan_tool["pci_display_devices"]
    sys_pci = tmp_path / "pci"
    sys_pci.mkdir()

    # a server without a GPU: an Ethernet and a USB controller
    pci(sys_pci, "0000-00-1f.6", "0x020000", "0x8086", "0x15bb")
    pci(sys_pci, "0000-00-14.0", "0x0c0330", "0x8086", "0xa36d")
    assert pci_display_devices(str(sys_pci)) == []

    # an AMD iGPU (VGA) and an NVIDIA GPU (3D controller)
    pci(sys_pci, "0000-c4-00.0", "0x030000", "0x1002", "0x1114")
    pci(sys_pci, "0000-01-00.0", "0x030200", "0x10de", "0x2c39")
    assert pci_display_devices(str(sys_pci)) == ["0000-01-00.0 10de:2c39", "0000-c4-00.0 1002:1114"]


def test_gpu_device_nodes(vulkan_tool, tmp_path):
    gpu_nodes = vulkan_tool["gpu_nodes"]
    dev = tmp_path / "dev"
    dev.mkdir()
    # a container of Docker on WSL2 without --gpus: the VM's virtual GPUs are on PCI, but no node
    assert gpu_nodes(str(dev)) == []

    (dev / "dri").mkdir()
    (dev / "dri" / "renderD128").write_text("")      # a GPU with its driver (also an Arm SoC's GPU)
    (dev / "dxg").write_text("")                     # WSL2's GPU
    found = gpu_nodes(str(dev))
    assert any(f.endswith("renderD128") for f in found) and any(f.endswith("dxg") for f in found)


class FakeCM:
    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)


def target(vulkan_target):
    t = vulkan_target["CTask"].__new__(vulkan_target["CTask"])
    t.cm = FakeCM()
    return t


def ctx(features):
    return {"control": {"con": False, "verbose": False},
            "tasks": {"nested_call": 0, "global": {"vulkan": {"features": features}}}}


LLVMPIPE = {"name": "llvmpipe (LLVM 19.1.7, 256 bits)", "type": "cpu"}
RADV = {"name": "AMD Radeon 860M Graphics (RADV GFX1152)", "type": "integrated"}


def test_the_target_needs_a_gpu(vulkan_target):
    t = target(vulkan_target)

    cpu_only = {"devices": [LLVMPIPE], "gpus": []}
    r = t.run(ctx(cpu_only))
    assert r["return"] == 1 and "only CPU devices" in r["error"] and "allow_cpu" in r["error"]
    assert t.run(ctx(cpu_only), allow_cpu = True)["return"] == 0

    with_gpu = {"devices": [RADV, LLVMPIPE], "gpus": [RADV]}
    assert t.run(ctx(with_gpu))["features"]["gpus"] == [RADV]

    r = t.run(ctx({"devices": [], "gpus": [], "error": "vkCreateInstance failed"}))
    assert r["return"] == 1 and "no Vulkan device" in r["error"]


def test_a_cached_target_is_checked_again(vulkan_target):
    t = target(vulkan_target)
    cached = {"features": {"devices": [RADV], "gpus": [RADV]}}

    # the GPU driver is gone since the entry was made: only llvmpipe now
    r = t.finish_dynamic_result(ctx({"devices": [LLVMPIPE], "gpus": []}), dict(cached), {})
    assert r["return"] == 1 and "only CPU devices" in r["error"]

    r = t.finish_dynamic_result(ctx({"devices": [RADV], "gpus": [RADV]}), dict(cached), {})
    assert r["return"] == 0 and r["result"]["features"]["gpus"] == [RADV]
