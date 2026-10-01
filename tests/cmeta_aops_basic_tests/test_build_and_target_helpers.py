"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of module-level helpers that need no cMeta context:

* category/program/api/common_build.py - MAX_JOBS sized to the RAM of source builds;
* task/setup/install.py - quiet installs turn "sudo" into "sudo -n" (no password prompt);
* task/target--xpu - the GPUs in the lspci / Win32_VideoController probe output;
* task/target--cpu - when a cached CPU inventory comes from another machine;
* tool/ollama - release assets and the Python 3.14 unpacking of .tar.zst archives.
"""

import importlib.util
import io
import pathlib
import subprocess
import sys
import tarfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_module(rel_path, name):
    """A module of the repository that has no cMeta imports."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_head(rel_path, class_line, imports):
    """The module-level code of a hook file, up to its class (which needs cMeta)."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    head = src[:src.index(class_line)]
    for line in imports:
        head = head.replace(line, "")
    ns = {}
    exec(compile(head, str(path), "exec"), ns)
    return type("Helpers", (), {k: staticmethod(v) if callable(v) else v
                                for k, v in ns.items() if not k.startswith("__")})


# --------------------------------------------------------------------------------------------
# common_build.default_max_jobs

@pytest.fixture(scope = "module")
def common_build():
    return load_module("category/program/api/common_build.py", "common_build")


@pytest.mark.parametrize("cpus, ram, device, nvcc_threads, expected", [
    (16, 31.5, "cuda", 1, 7),     # the p14s laptops: 4 GiB per CUDA job
    (16, 15.0, "cuda", 1, 3),     # WSL with half the RAM
    (16, 31.5, "cuda", 2, 3),     # nvcc threads multiply the memory of a job
    (16, 31.5, "cpu", 1, 15),     # C++ only: 2 GiB per job
    (10, 64.0, "cpu", 1, 10),     # never more jobs than CPUs
    (4, 2.0, "cuda", 1, 1),       # always at least one job
    (12, None, "cuda", 1, 12),    # RAM unknown: one job per CPU, as the build systems do
])
def test_default_max_jobs(common_build, monkeypatch, cpus, ram, device, nvcc_threads, expected):
    monkeypatch.setattr(common_build.os, "cpu_count", lambda: cpus)
    monkeypatch.setattr(common_build, "total_ram_gib", lambda: ram)
    assert common_build.default_max_jobs(device, nvcc_threads) == expected


def test_total_ram_gib_on_this_machine(common_build):
    ram = common_build.total_ram_gib()
    assert ram is None or ram > 0.5


# --------------------------------------------------------------------------------------------
# install.SUDO_PREFIX

@pytest.fixture(scope = "module")
def sudo_prefix():
    return load_module("task/setup/install.py", "setup_install").SUDO_PREFIX


@pytest.mark.parametrize("cmd, expected", [
    ("sudo apt-get install -y zstd", "sudo -n apt-get install -y zstd"),
    ("sudo apt-get install -y zstd || (sudo apt-get update && sudo apt-get install -y zstd)",
     "sudo -n apt-get install -y zstd || (sudo -n apt-get update && sudo -n apt-get install -y zstd)"),
    ("echo x; sudo dnf install -y zstd", "echo x; sudo -n dnf install -y zstd"),
    ("sudo -n true", "sudo -n true"),
    ("brew install zstd", "brew install zstd"),
    ("pseudo sudoku", "pseudo sudoku"),
])
def test_quiet_installs_use_sudo_n(sudo_prefix, cmd, expected):
    assert sudo_prefix.sub(r"\1sudo -n ", cmd) == expected


# --------------------------------------------------------------------------------------------
# target--xpu parse_gpus

@pytest.fixture(scope = "module")
def xpu():
    return load_head("task/target--xpu/api_v1.py", "\nclass CTask",
                     ["from task_c36be4b9314a45e0.api.ctask import InitCTask"])


WINDOWS_OUTPUT = """

Name          : Meta Virtual Monitor
DriverVersion : 17.12.55.198

Name          : NVIDIA RTX PRO 1000 Blackwell Generation Laptop GPU
DriverVersion : 32.0.16.1088

Name          : Intel(R) Graphics
DriverVersion : 32.0.101.8517
"""

LINUX_OUTPUT = """00:02.0 VGA compatible controller: Intel Corporation Raptor Lake-P [Iris Xe Graphics] (rev 04)
03:00.0 Display controller: Intel Corporation Data Center GPU Flex 170 (rev 08)
01:00.0 3D controller: NVIDIA Corporation GA107GLM [RTX A500 Laptop GPU] (rev a1)
"""


def test_parse_gpus_windows(xpu):
    devices = xpu.parse_gpus(WINDOWS_OUTPUT, "windows")
    assert [d["name"] for d in devices] == ["Meta Virtual Monitor",
                                            "NVIDIA RTX PRO 1000 Blackwell Generation Laptop GPU",
                                            "Intel(R) Graphics"]
    assert devices[2]["driver_version"] == "32.0.101.8517"


def test_parse_gpus_linux(xpu):
    devices = xpu.parse_gpus(LINUX_OUTPUT, "linux")
    assert [d["class"] for d in devices] == ["VGA compatible controller", "Display controller", "3D controller"]
    assert devices[1]["name"] == "Intel Corporation Data Center GPU Flex 170 (rev 08)"
    assert devices[0]["pci_slot"] == "00:02.0"


def test_parse_gpus_empty(xpu):
    assert xpu.parse_gpus("", "linux") == []
    assert xpu.parse_gpus("", "windows") == []


# --------------------------------------------------------------------------------------------
# target--cpu is_stale

@pytest.fixture(scope = "module")
def cpu():
    return load_head("task/target--cpu/api_v1.py", "\nclass CTask",
                     ["from task_c36be4b9314a45e0.api.ctask import InitCTask", "from . import logic"])


FP = {"node": "fgg-ThinkPad-P14s-Gen-4", "machine": "x86_64", "cpus": 16}


@pytest.mark.parametrize("result, stale", [
    ({"host": dict(FP), "features": {"logical_cpu_count": 16}}, False),
    ({"host": dict(FP, node = "FGG-LENOVO-P14S"), "features": {"logical_cpu_count": 16}}, True),
    ({"host": dict(FP, cpus = 4), "features": {"logical_cpu_count": 4}}, True),
    ({"features": {"logical_cpu_count": 16}}, False),   # an entry from before the fingerprint
    ({"features": {"logical_cpu_count": 4}}, True),
    ({"features": {}}, False),
])
def test_cpu_inventory_is_stale(cpu, result, stale):
    assert cpu.is_stale(result, FP) == stale


def test_host_fingerprint(cpu):
    fp = cpu.host_fingerprint()
    assert set(fp) == {"node", "machine", "cpus"} and fp["cpus"] >= 1


# --------------------------------------------------------------------------------------------
# tool/ollama

@pytest.fixture(scope = "module")
def ollama():
    return load_head("tool/ollama/api_v1.py", "\nclass CTool",
                     ["from tool_c393ba5c6fa14f66.api.ctool import InitCTool"])


@pytest.mark.parametrize("uname, uarch, variant, asset", [
    ("windows", "amd64", None, "ollama-windows-amd64.zip"),
    ("windows", "arm64", None, "ollama-windows-arm64.zip"),
    ("linux", "x86_64", None, "ollama-linux-amd64.tar.zst"),
    ("linux", "amd64", "rocm", "ollama-linux-amd64-rocm.tar.zst"),
    ("darwin", "arm64", None, "ollama-darwin.tgz"),
    ("linux", "riscv64", None, None),
])
def test_ollama_release_asset(ollama, uname, uarch, variant, asset):
    assert ollama.release_asset(uname, uarch, variant) == asset


def test_unpack_with_python_314(ollama, tmp_path):
    """The script tool/ollama runs with a Python 3.14+ when cMeta's own Python lacks zstd."""
    pytest.importorskip("compression.zstd")
    archive = tmp_path / "a.tar.zst"
    with tarfile.open(archive, "w:zst") as t:
        data = b"#!/bin/sh\necho ollama\n"
        info = tarfile.TarInfo("bin/ollama")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    dest = tmp_path / "content"
    dest.mkdir()
    rc = subprocess.run([sys.executable, "-c", ollama.UNPACK_WITH_PYTHON, str(archive), str(dest)]).returncode
    assert rc == 0
    assert (dest / "bin" / "ollama").read_bytes().startswith(b"#!/bin/sh")
