"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the Intel NPU target and the OpenVINO test program:

* task/target--npu-intel - the NPU in the Windows (PnP) and Linux (sysfs accel) probe output;
* program/test-openvino - property values as JSON, and EXECUTION_DEVICES as a string or a list.
"""

import pathlib

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
def npu():
    return load_head("task/target--npu-intel/api_v1.py", "\nclass CTask",
                     ["from task_c36be4b9314a45e0.api.ctask import InitCTask"])


@pytest.fixture(scope = "module")
def program():
    return load_head("program/test-openvino/src/program.py", None, [])


WINDOWS_PROBE = """Name: Intel(R) NPU
DeviceID: PCI\\VEN_8086&DEV_B03E&SUBSYS_236017AA&REV_0F\\3&11583659&1&58
Status: OK
DriverVersion: 32.0.100.5540

Name: Some Other Accelerator
DeviceID: PCI\\VEN_1022&DEV_1502&SUBSYS_00000000&REV_00\\4&1
Status: OK
DriverVersion: 1.0.0.0
"""


def test_windows_probe_finds_the_intel_npu_only(npu):
    devices = npu["parse_npus"](WINDOWS_PROBE, "windows")
    assert devices == [{
        "pci_id": "8086:b03e", "platform": "Panther Lake", "npu_generation": "50xx",
        "name": "Intel(R) NPU", "driver_version": "32.0.100.5540", "status": "OK",
        "instance_id": "PCI\\VEN_8086&DEV_B03E&SUBSYS_236017AA&REV_0F\\3&11583659&1&58"}]


def test_windows_probe_keeps_an_unknown_intel_accelerator(npu):
    probe = "Name: Intel(R) AI Boost\nDeviceID: PCI\\VEN_8086&DEV_ABCD&SUBSYS_0\\1\nStatus: OK\n"
    devices = npu["parse_npus"](probe, "windows")
    assert devices[0]["pci_id"] == "8086:abcd" and "platform" not in devices[0]


def test_linux_probe(npu):
    probe = "accel0 intel_vpu 0x8086 0x643e\naccel1 amdxdna 0x1022 0x17f0\n"
    devices = npu["parse_npus"](probe, "linux")
    assert devices == [{"pci_id": "8086:643e", "platform": "Lunar Lake", "npu_generation": "40xx",
                        "node": "accel0", "driver": "intel_vpu"}]


def test_no_npu(npu):
    assert npu["parse_npus"]("", "windows") == []
    assert npu["parse_npus"]("accel0 amdxdna 0x1022 0x17f0", "linux") == []


def test_every_known_id_has_a_generation(npu):
    for device_id, (platform, generation) in npu["INTEL_NPUS"].items():
        assert len(device_id) == 4 and platform and generation.endswith("xx")


def test_execution_devices_as_list(program):
    assert program["as_list"]("NPU") == ["NPU"]
    assert program["as_list"]("GPU.0,CPU") == ["GPU.0", "CPU"]
    assert program["as_list"](["NPU"]) == ["NPU"]


def test_plain_property_values(program):
    class ElementType:
        def __init__(self, name):
            self.name = name

        def get_type_name(self):
            return self.name

    gops = {ElementType("f16"): 25190.3984375, ElementType("i8"): 50380.796875}
    assert program["plain"](gops) == {"f16": 25190.4, "i8": 50380.8}
    assert program["plain"](["FP16", "INT8"]) == ["FP16", "INT8"]
    assert program["plain"](17179869184) == 17179869184
    assert program["plain"](ElementType("f16")) == "f16"


def test_timed_run_by_iterations_and_by_seconds(program):
    calls = []
    times, per_second, elapsed = program["timed_run"](lambda: calls.append(1), 10, 0, 1e9, "X")
    assert len(times) == 10 and len(calls) == 10 and per_second == []
    # A timed run: as many calls as fit, and the GFLOPS of each full second (none in 0.3 s)
    times, per_second, elapsed = program["timed_run"](lambda: None, 10, 0.3, 1e9, "X")
    assert len(times) > 10 and elapsed >= 0.3 and per_second == []


def test_device_of_target(program):
    assert program["DEVICE_OF_TARGET"] == {"npu-intel": "NPU", "xpu": "GPU", "cpu": "CPU"}


# --------------------------------------------------------------------------------------------
# llama.cpp on the Intel NPU and GPU

@pytest.fixture(scope = "module")
def common():
    return load_head("category/program/api/common_llama_cpp.py", None, [])


@pytest.fixture(scope = "module")
def tool():
    return load_head("tool/llama-cpp/api_v1.py", "\nclass CTool",
                     ["from tool_c393ba5c6fa14f66.api.ctool import InitCTool"])


def test_openvino_device(common):
    assert common["openvino_device"](["npu-intel"]) == "NPU"
    assert common["openvino_device"](["npu-intel", "openvino"]) == "NPU"
    assert common["openvino_device"](["xpu", "openvino"]) == "GPU"
    assert common["openvino_device"](["openvino"]) is None
    assert common["openvino_device"](["cuda"]) is None


def test_device_names_with_parentheses(common):
    log = ("llama_prepare_model_devices: using device SYCL0 (Intel(R) Graphics) (unknown id) - 15018 MiB free\n"
           "using device CUDA0 (NVIDIA RTX PRO 1000 Blackwell Generation Laptop GPU) (0000:01:00.0) - 7820 MiB free\n"
           "using device Metal (Apple M4) - 11000 MiB free\n")
    perf = common["parse_llama_log"](log)
    assert [(d["name"], d["description"]) for d in perf["devices"]] == [
        ("SYCL0", "Intel(R) Graphics"),
        ("CUDA0", "NVIDIA RTX PRO 1000 Blackwell Generation Laptop GPU"),
        ("Metal", "Apple M4")]


def test_npu_selects_the_openvino_release(tool):
    assert tool["backend_from_compute"](["npu-intel"], "windows") == "openvino"
    assert tool["backend_from_compute"](["xpu"], "windows") == "sycl"
    # npu-intel,openvino is one backend; cuda,vulkan are two
    assert tool["backends_of"](["cpu", "npu-intel", "openvino"]) == ["openvino"]
    assert tool["backends_of"](["cuda", "vulkan"]) == ["cuda", "vulkan"]
    assert "npu-intel" in tool["GPU_TARGETS"]
