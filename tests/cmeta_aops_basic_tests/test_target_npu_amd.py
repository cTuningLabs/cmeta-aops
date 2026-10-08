"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of task/target--npu-amd (the AMD Ryzen AI NPU found without an SDK) and of the FastFlowLM
tool's release table: the probe lines of Linux and Windows, the PCI IDs and revisions of the NPU
generations, a fake PCI bus.
"""

import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def npu():
    path = REPO_ROOT / "task" / "target--npu-amd" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask:\n    pass")
    ns = {"__name__": "target_npu_amd", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def flm():
    path = REPO_ROOT / "tool" / "flm" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "class InitCTool:\n    pass")
    src = src.replace("from tool_c393ba5c6fa14f66.api.common_deb import sha256_of", "sha256_of = None")
    ns = {"__name__": "flm", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def test_the_linux_probe_line_of_the_acer(npu):
    d = npu["parse_npus"]("accel0 amdxdna 0x1022 0x17f0 0x20 1.1.2.64 RyzenAI-npu6\n", "linux")
    assert d == [{'pci_id': '1022:17f0', 'revision': '20', 'npu_generation': 'npu6', 'platform': 'Krackan Point',
                  'architecture': 'xdna2', 'node': '/dev/accel/accel0', 'driver': 'amdxdna', 'firmware': '1.1.2.64', 'name': 'RyzenAI-npu6'}]


@pytest.mark.parametrize("device, rev, generation, platform", [
    ("0x1502", "0x00", "npu1", "Phoenix / Hawk Point"),
    ("0x17f0", "0x10", "npu4", "Strix Point"),
    ("0x17f0", "0x11", "npu5", "Strix Halo"),
    ("0x17f0", "0x20", "npu6", "Krackan Point"),
    ("0x17f2", "0x10", "npu3", "data centre (PF)"),
])
def test_the_generations(npu, device, rev, generation, platform):
    d = npu["describe"]("0x1022", device, rev)
    assert d['npu_generation'] == generation and d['platform'] == platform


def test_an_unknown_revision_keeps_the_pci_id(npu):
    d = npu["describe"]("0x1022", "0x17f0", "0x30")
    assert d == {'pci_id': '1022:17f0', 'revision': '30'}


def test_other_accel_devices_are_not_taken(npu):
    assert npu["parse_npus"]("accel0 intel_vpu 0x8086 0xb03e\n", "linux") == []
    assert npu["parse_npus"]("", "linux") == []


def test_the_windows_probe(npu):
    text = ("Name: AMD IPU Device\nDeviceID: PCI\\VEN_1022&DEV_17F0&SUBSYS_19061025&REV_20\\4&2b3a1c2&0&0049\n"
            "Status: OK\nDriverVersion: 32.0.203.311\n\n"
            "Name: Intel(R) AI Boost\nDeviceID: PCI\\VEN_8086&DEV_7D1D&SUBSYS_00000000&REV_04\\3&11583659&0&58\nStatus: OK\n\n")
    d = npu["parse_npus"](text, "windows")
    assert len(d) == 1
    assert d[0]['npu_generation'] == 'npu6' and d[0]['name'] == 'AMD IPU Device' and d[0]['driver_version'] == '32.0.203.311'


def test_the_npus_on_a_fake_pci_bus(npu, tmp_path):
    if os.name == 'nt':
        pytest.skip('PCI addresses have colons, which a Windows file name cannot have')
    for name, vendor, device, rev in (('0000:c3:00.1', '0x1022', '0x17f0', '0x20'), ('0000:c2:00.0', '0x1002', '0x1114', '0xc2')):
        d = tmp_path / name
        d.mkdir()
        (d / 'vendor').write_text(vendor + '\n'); (d / 'device').write_text(device + '\n'); (d / 'revision').write_text(rev + '\n')
    found = npu["amd_npus_on_pci"](str(tmp_path))
    assert [f['pci_id'] for f in found] == ['1022:17f0'] and found[0]['platform'] == 'Krackan Point'


def test_the_flm_release_table(flm):
    asset, sha = flm["asset_for"]("1.0.7", "linux", "amd64")
    assert asset == "fastflowlm_1.0.7_linux.tar.gz" and len(sha) == 64
    asset, sha = flm["asset_for"]("1.0.7", "windows", "amd64")
    assert asset.endswith(".zip")
    assert flm["asset_for"]("1.0.7", "darwin", "arm64") == (None, None)
    assert flm["asset_for"]("9.9.9", "linux", "amd64") == (None, None)
