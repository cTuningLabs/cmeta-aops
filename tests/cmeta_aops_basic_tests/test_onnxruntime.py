"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of ONNX Runtime per target:

* tool/pip-onnxruntime - the package for the targets, and the openvino release that
  onnxruntime-openvino needs on Windows;
* program/test-onnxruntime - the execution provider of each target.
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
def tool():
    return load_head("tool/pip-onnxruntime/api_v1.py", "\nclass CTool",
                     ["from tool_c393ba5c6fa14f66.api.ctool import InitCTool"])


@pytest.fixture(scope = "module")
def program():
    return load_head("program/test-onnxruntime/src/program.py", None, [])


def test_package_for_the_targets(tool):
    pkg = tool["ort_package"]
    assert pkg(["cpu"]) == ("onnxruntime", [])
    assert pkg(["metal"]) == ("onnxruntime", [])
    assert pkg(["cuda"]) == ("onnxruntime-gpu", ["cuda", "cudnn"])
    assert pkg(["cpu", "cuda"]) == ("onnxruntime-gpu", ["cuda", "cudnn"])
    assert pkg(["npu-intel"]) == ("onnxruntime-openvino", [])
    assert pkg(["xpu"]) == ("onnxruntime-openvino", [])
    assert pkg(["rocm"]) == ("onnxruntime-migraphx", [])
    assert pkg(["cuda"], override = "onnxruntime-directml") == ("onnxruntime-directml", [])


def test_openvino_runtime_for_onnxruntime_openvino(tool):
    assert tool["openvino_runtime"]("1.24.1") == "2025.4.1"
    assert tool["openvino_runtime"](None) == tool["openvino_runtime"](tool["ORT_OPENVINO_DEFAULT"])
    assert tool["openvino_runtime"]("0.1.0") is None


def test_providers_of_the_targets(program):
    runs = program["providers_for"]
    assert runs(["cpu"]) == [("CPUExecutionProvider", {})]
    assert runs(["cpu", "cuda"]) == [("CPUExecutionProvider", {}), ("CUDAExecutionProvider", {})]
    assert runs(["npu-intel"]) == [("OpenVINOExecutionProvider", {"device_type": "NPU"})]
    # openvino next to a device target names the stack, alone it is the OpenVINO CPU device
    assert runs(["npu-intel", "openvino"]) == [("OpenVINOExecutionProvider", {"device_type": "NPU"})]
    assert runs(["openvino"]) == [("OpenVINOExecutionProvider", {"device_type": "CPU"})]
    assert runs(["xpu"]) == [("OpenVINOExecutionProvider", {"device_type": "GPU"})]
    assert runs(["metal"]) == [("CoreMLExecutionProvider", {})]


class FakeCore:
    """OpenVINO's Core with GPUs of given names."""
    def __init__(self, names):
        self.names = names

    def get_property(self, device, prop):
        return self.names[device]


def test_xpu_is_the_intel_gpu(program):
    # No Intel GPU runtime: the NVIDIA GPU is OpenVINO's only GPU, and xpu must not take it
    nvidia_only = FakeCore({"GPU": "NVIDIA RTX A500 Laptop GPU (dGPU)"})
    assert program["intel_gpu"](nvidia_only, ["CPU", "GPU"]) is None
    both = FakeCore({"GPU.0": "NVIDIA RTX PRO 1000 (dGPU)", "GPU.1": "Intel(R) Graphics (iGPU)"})
    assert program["intel_gpu"](both, ["CPU", "GPU.0", "GPU.1", "NPU"]) == "GPU.1"


def test_openvino_xpu_is_the_intel_gpu(repo_root):
    path = repo_root / "program" / "test-openvino" / "src" / "program.py"
    ns = {"__name__": "helpers"}
    exec(compile(path.read_text(encoding = "utf-8"), str(path), "exec"), ns)
    assert ns["intel_gpu"](FakeCore({"GPU": "NVIDIA GeForce 940MX (dGPU)"}), ["CPU", "GPU"]) is None
    assert ns["intel_gpu"](FakeCore({"GPU.0": "Intel(R) Graphics (iGPU)"}), ["GPU.0"]) == "GPU.0"


def test_timed_run(program):
    times, per_second, elapsed = program["timed_run"](lambda: None, 7, 0, 1e9, "X")
    assert len(times) == 7 and per_second == []
