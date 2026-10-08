"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/rocm: the ROCm found through rocm-sdk (AMD's Python distribution inside a python,
as in the rocm/vllm and rocm/pytorch images) next to the one found through rocm-smi - the names and the
version command of the description, amd-smi's JSON turned into rocm-smi's for the device list, one
candidate per installation - and of program/test-onnxruntime's reading of a provider's failure.
"""

import json
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


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


@pytest.fixture(scope = "module")
def rocm():
    return load("tool/rocm/api_v1.py",
                {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass"})


@pytest.fixture(scope = "module")
def desc():
    return yaml.safe_load((REPO_ROOT / "tool" / "rocm" / "_desc.yaml").read_text(encoding = "utf-8"))


# amd-smi static --asic --vram --driver --bus --json on an MI300X (ROCm 10.1), shortened
AMD_SMI = {"gpu_data": [{"gpu": 0,
                         "asic": {"market_name": "AMD Instinct MI300X", "vendor_id": "0x1002", "vendor_name": "Advanced Micro Devices Inc. [AMD/ATI]",
                                  "device_id": "0x74a1", "asic_serial": "0x6F1F0A2B3C4D5E6F", "target_graphics_version": "gfx942"},
                         "bus": {"bdf": "0000:83:00.0"},
                         "vram": {"type": "HBM3", "size": {"value": 196592, "unit": "MB"}},
                         "driver": {"name": "amdgpu", "version": "6.19.14"}}]}


def test_the_description_detects_rocm_sdk_too(desc):
    names = [n for n in desc["names"]]
    assert any(n.startswith("rocm-smi") for n in names)
    assert "rocm-sdk" in names
    # rocm-sdk has no --version: the command falls back to "version"
    assert "|| {{tool_path}} version" in desc["cmd_get_version"]
    regexes = [m["regex"] for m in desc["match_version"]]
    assert re.search(regexes[0], "ROCM-SMI version: 3.0.0+unknown\nROCM-SMI-LIB version: 7.5.0\n").group(1) == "3.0.0+unknown"
    assert not re.search(regexes[0], "10.1.0\n")
    assert re.search(regexes[1], "10.1.0\n").group(1) == "10.1.0"
    assert re.search(regexes[1], "10.1.0rc1\n").group(1) == "10.1.0rc1"


def test_is_rocm_sdk(rocm):
    assert rocm["is_rocm_sdk"]("/opt/python/bin/rocm-sdk")
    assert not rocm["is_rocm_sdk"]("/usr/bin/rocm-smi")
    assert not rocm["is_rocm_sdk"](None)


def test_amd_smi_json_becomes_rocm_smi_json(rocm):
    cards = rocm["cards_from_amd_smi"](AMD_SMI)
    assert list(cards) == ["card0"]
    card = cards["card0"]
    assert card["Card Series"] == "AMD Instinct MI300X"
    assert card["GFX Version"] == "gfx942"
    assert card["PCI Bus"] == "0000:83:00.0"
    assert card["Driver version"] == "6.19.14"
    assert card["VRAM Total Memory (B)"] == str(196592 * 1024 * 1024)
    # ... and the device parser of rocm-smi's JSON reads it
    devices = rocm["parse_rocm_smi_devices"](cards)
    assert devices[0]["name"] == "AMD Instinct MI300X"
    assert devices[0]["pci.bus_id"] == "0000:83:00.0"
    assert devices[0]["memory.total"] == 196592 * 1024 * 1024
    assert devices[0]["compute_cap"] == "gfx942"
    # a list, N/A values, no gpu index
    cards = rocm["cards_from_amd_smi"]([{"asic": {"market_name": "N/A", "device_id": "0x1234"}}])
    assert cards == {"card0": {"Card Model": "0x1234"}}
    assert rocm["cards_from_amd_smi"]({}) == {}


def test_one_candidate_per_installation(rocm, tmp_path):
    own = tmp_path / "venv" / "bin"
    own.mkdir(parents = True)
    (own / "rocm-smi").write_text("#!/bin/sh\n")
    (own / "rocm-sdk").write_text("#!/bin/sh\n")
    image = tmp_path / "opt" / "python" / "bin"
    image.mkdir(parents = True)
    (image / "rocm-sdk").write_text("#!/bin/sh\n")
    paths = [{"path": str(own / "rocm-smi")}, {"path": str(own / "rocm-sdk")}, {"path": str(image / "rocm-sdk")}, {"path": "/usr/bin/rocm-smi"}]
    kept = [p["path"] for p in rocm["prefer_rocm_smi"](paths)]
    # the rocm-sdk next to our own rocm-smi is dropped, the image's (alone) is kept
    assert kept == [str(own / "rocm-smi"), str(image / "rocm-sdk"), "/usr/bin/rocm-smi"]


@pytest.fixture(scope = "module")
def ort():
    return load("program/test-onnxruntime/src/program.py")


def test_the_provider_error_is_the_cause_ort_printed(ort):
    printed = ("*************** EP Error ***************\n"
               "EP Error /root/Codes/onnxruntime/core/session/provider_bridge_ort.cc:1988 onnxruntime::Provider& "
               "onnxruntime::ProviderLibrary::Get() [ONNXRuntimeError] : 1 : FAIL : Failed to load library "
               "/venv/lib/python3.14/site-packages/onnxruntime/capi/libonnxruntime_providers_migraphx.so with error: "
               "libmigraphx_c.so.3: cannot open shared object file: No such file or directory\n"
               " when using [('MIGraphXExecutionProvider', {})]\n"
               "Falling back to ['CPUExecutionProvider'] and retrying.\n")
    error = ort["provider_error"]("Conflicting session configuration: explicitly added the CPU EP ...", printed)
    assert error.startswith("/root/Codes/onnxruntime/core/session/provider_bridge_ort.cc")
    assert "libmigraphx_c.so.3: cannot open shared object file" in error
    assert "-> MIGraphX is not installed" in error
    # nothing printed: the exception's text
    assert ort["provider_error"]("boom", "") == "boom"
    assert ort["provider_error"]("boom", None) == "boom"
    # a cause without a known library: no hint
    assert ort["provider_error"]("x", "EP Error something odd happened when using [('X', {})]") == "something odd happened"
