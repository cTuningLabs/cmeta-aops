"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the opencl target (tool/opencl and task/target--opencl) and of the Android GPU
and NPU targets (task/target--android-gpu, task/target--android-npu): what they read from the
OpenCL library, sysfs, 'cmd gpu vkjson', SurfaceFlinger, 'service list' and lshal, with samples
from a Windows laptop, a Galaxy Tab S10+ (MediaTek), a Galaxy Tab S10 FE (Exynos) and a Pixel.
"""

import json
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


TOOL = ("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "InitCTool")
TASK = ("from task_c36be4b9314a45e0.api.ctask import InitCTask", "InitCTask")


@pytest.fixture(scope = "module")
def opencl_tool():
    return load("tool/opencl/api_v1.py", *TOOL)


@pytest.fixture(scope = "module")
def opencl_target():
    return load("task/target--opencl/api_v1.py", *TASK)


@pytest.fixture(scope = "module")
def android_gpu():
    return load("task/target--android-gpu/api_v1.py", *TASK)


@pytest.fixture(scope = "module")
def android_npu():
    return load("task/target--android-npu/api_v1.py", *TASK)


# What opencl_probe.py printed on a Windows laptop (an NVIDIA GPU, an Intel iGPU, Intel's CPU runtime)
LAPTOP = {"library": r"C:\WINDOWS\System32\OpenCL.dll", "platforms": [
    {"name": "NVIDIA CUDA", "vendor": "NVIDIA Corporation", "version": "OpenCL 3.0 CUDA 13.3.80",
     "devices": [{"name": "NVIDIA RTX PRO 1000 Blackwell Generation Laptop GPU", "type": "gpu", "vendor": "nvidia",
                  "compute_units": 20, "global_memory_mib": 8150}]},
    {"name": "Intel(R) OpenCL Graphics", "vendor": "Intel(R) Corporation", "version": "OpenCL 3.0 ",
     "devices": [{"name": "Intel(R) Graphics", "type": "gpu", "vendor": "intel", "compute_units": 32}]},
    {"name": "Intel(R) OpenCL", "vendor": "Intel(R) Corporation", "version": "OpenCL 2.1 WINDOWS",
     "devices": [{"name": "Intel(R) Core(TM) Ultra 9 386H", "type": "cpu", "vendor": "intel", "compute_units": 16}]}]}


def test_the_opencl_features(opencl_tool):
    f = opencl_tool["summarize"](LAPTOP)
    assert [p["name"] for p in f["platforms"]] == ["NVIDIA CUDA", "Intel(R) OpenCL Graphics", "Intel(R) OpenCL"]
    assert "devices" not in f["platforms"][0]
    assert [d["name"] for d in f["gpus"]] == ["NVIDIA RTX PRO 1000 Blackwell Generation Laptop GPU", "Intel(R) Graphics"]
    assert f["devices"][2]["platform"] == "Intel(R) OpenCL" and f["devices"][2]["type"] == "cpu"
    assert f["vendors"] == ["intel", "nvidia"]
    assert f["version"] == "3.0"
    assert opencl_tool["summarize"]({"library": "x", "platforms": []})["gpus"] == []


def test_opencl_gpu_nodes(opencl_tool, tmp_path):
    assert opencl_tool["gpu_nodes"](str(tmp_path)) == []
    (tmp_path / "nvidia0").write_text("")
    assert opencl_tool["gpu_nodes"](str(tmp_path)) == [str(tmp_path / "nvidia0")]


def test_an_intel_gpu_on_the_pci_bus(opencl_target, tmp_path):
    def device(name, vendor, cls):
        d = tmp_path / name
        d.mkdir()
        (d / "vendor").write_text(vendor + "\n")
        (d / "class").write_text(cls + "\n")

    device("0000-01-00.0", "0x10de", "0x030200")      # an NVIDIA GPU
    device("0000-00-14.0", "0x8086", "0x0c0330")      # an Intel USB controller
    assert not opencl_target["intel_gpu_on_pci"](str(tmp_path))
    device("0000-00-02.0", "0x8086", "0x030000")      # the Intel iGPU
    assert opencl_target["intel_gpu_on_pci"](str(tmp_path))


class FakeCM:
    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)


def test_the_opencl_target_needs_a_gpu(opencl_target, opencl_tool):
    t = opencl_target["CTask"].__new__(opencl_target["CTask"])
    t.cm = FakeCM()

    def ctx(features):
        return {"control": {"con": False}, "tasks": {"nested_call": 0, "global": {"opencl": {"features": features}}}}

    gpus = opencl_tool["summarize"](LAPTOP)
    assert t.run(ctx(gpus))["features"]["gpus"] == gpus["gpus"]

    cpu_only = opencl_tool["summarize"]({"library": "libOpenCL.so.1", "platforms": [LAPTOP["platforms"][2]]})
    r = t.run(ctx(cpu_only))
    assert r["return"] == 1 and "no GPU" in r["error"] and "allow_cpu" in r["error"]
    assert t.run(ctx(cpu_only), allow_cpu = True)["return"] == 0

    r = t.run(ctx({"devices": [], "gpus": [], "error": "the OpenCL library lists no platform (-1001)"}))
    assert r["return"] == 1 and "-1001" in r["error"]

    # a cached target is checked again against this machine
    r = t.finish_dynamic_result(ctx(cpu_only), {"features": gpus}, {})
    assert r["return"] == 1


# 'cmd gpu vkjson' on the Galaxy Tab S10+ (the numbers as Android prints them, floats)
VKJSON = json.dumps({"apiVersion": 4206839.0, "devices": [{"properties": {
    "deviceName": "Mali-G720-Immortalis MC12", "apiVersion": 4206839.0, "driverVersion": 184553472.0,
    "vendorID": 5045.0, "deviceID": 3362783232.0, "deviceType": 1.0}}]})


def test_the_android_gpu(android_gpu):
    devices = android_gpu["parse_vkjson"](VKJSON)
    assert devices == [{"name": "Mali-G720-Immortalis MC12", "type": "integrated-gpu", "vendor": "arm", "vendor_id": 5045,
                        "api_version": "1.3.247", "driver_version": 184553472, "device_id": 3362783232}]
    assert android_gpu["parse_vkjson"]("not json") == []

    gles = android_gpu["parse_gles"]("GLES: ARM, Mali-G720-Immortalis MC12, OpenGL ES 3.2 v1.r44p1-01eac0.97cfdb5d")
    assert gles == {"vendor": "ARM", "renderer": "Mali-G720-Immortalis MC12", "version": "OpenGL ES 3.2 v1.r44p1-01eac0.97cfdb5d"}
    assert android_gpu["parse_gles"]("") == {}


# 'service list' and lshal lines of three devices
SERVICES_MTK = """52	android.hardware.neuralnetworks.IDevice/mtk-dsp_shim: [android.hardware.neuralnetworks.IDevice]
53	android.hardware.neuralnetworks.IDevice/mtk-mdla_shim: [android.hardware.neuralnetworks.IDevice]
54	android.hardware.neuralnetworks.IDevice/mtk-neuron_shim: [android.hardware.neuralnetworks.IDevice]
343	vendor.mediatek.hardware.apuware.apusys.INeuronApusys/default: [vendor.mediatek.hardware.apuware.apusys.INeuronApusys]
"""
SERVICES_EXYNOS = "61	vendor.samsung_slsi.hardware.enn_aidl.IEnnInterfaceAidl/default: [vendor.samsung_slsi.hardware.enn_aidl.IEnnInterfaceAidl]\n"
LSHAL_PIXEL = "FM    Y android.hardware.neuralnetworks@1.3::IDevice/google-edgetpu  0/1  1234  2345\n"


def test_the_android_npu(android_npu):
    nnapi, stacks = android_npu["nnapi_devices"], android_npu["vendor_stacks"]
    assert nnapi(SERVICES_MTK) == ["mtk-dsp_shim", "mtk-mdla_shim", "mtk-neuron_shim"]
    assert [s["name"] for s in stacks(SERVICES_MTK)] == ["mediatek-apu"]

    # the Exynos tablet: ENN, no NNAPI driver
    assert nnapi(SERVICES_EXYNOS) == []
    assert "only from an app" in stacks(SERVICES_EXYNOS)[0]["note"]

    # an older NNAPI driver (HIDL), listed by lshal
    assert nnapi("", LSHAL_PIXEL) == ["google-edgetpu"]
    assert [s["name"] for s in stacks("libedgetpu_litert.so\n")] == ["google-edgetpu"]
    assert [s["name"] for s in stacks("libcdsprpc.so\n")] == ["qualcomm-hexagon"]
