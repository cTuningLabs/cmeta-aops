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
    # The module-level code only: install.py imports its package sibling upgrade.py
    return load_head("task/setup/install.py", "\ndef install_tool", ["from . import upgrade"]).SUDO_PREFIX


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


# --------------------------------------------------------------------------------------------
# tool/microsoft.visual-studio

@pytest.fixture(scope = "module")
def vs():
    return load_head("tool/microsoft.visual-studio/api_v1.py", "\nclass CTool",
                     ["from tool_c393ba5c6fa14f66.api.ctool import InitCTool"])


def test_build_tools_winget_ids(vs):
    assert vs.BUILD_TOOLS_WINGET_IDS["2026"] == "Microsoft.VisualStudio.BuildTools"
    assert vs.BUILD_TOOLS_WINGET_IDS["2022"] == "Microsoft.VisualStudio.2022.BuildTools"


def test_build_tools_install_cmd():
    import yaml
    desc = yaml.safe_load((REPO_ROOT / "tool" / "microsoft.visual-studio" / "_desc.yaml").read_text(encoding = "utf-8"))
    cmd = desc["install_cmd"]["windows"]
    assert "--id=@VS_BUILD_TOOLS@" in cmd                      # replaced by customize_install_cmd()
    assert "Microsoft.VisualStudio.Workload.VCTools" in cmd and "--includeRecommended" in cmd


@pytest.mark.skipif(sys.platform != "win32", reason = "Visual Studio is Windows-only")
def test_vswhere_installations_are_folders(vs):
    for path in vs.vswhere_installations():
        assert pathlib.Path(path).is_dir()


# --------------------------------------------------------------------------------------------
# Programs: run_time_env is expanded by task/setup-run, whose own params are not the program's

def test_run_time_env_reads_the_program_params():
    """
    '{{params.X|default}}' in local_vars.run_time_env always gave the default: setup-run expands
    run_time_env with its own params. compile-and-run-program keeps the program's params in
    local.params, so '{{local.params.X|default}}' is the form that sees --X on the command line.
    """
    import yaml
    offenders = []
    for desc in sorted((REPO_ROOT / "program").glob("*/_desc.yaml")):
        data = yaml.safe_load(desc.read_text(encoding = "utf-8")) or {}
        env = (data.get("local_vars") or {}).get("run_time_env") or {}
        for key, value in env.items():
            if isinstance(value, str) and "{{params." in value:
                offenders.append(f"{desc.parent.name}: {key}: {value}")
    assert offenders == []


# --------------------------------------------------------------------------------------------
# tool/vulkan-sdk sdk_layout

@pytest.fixture(scope = "module")
def vksdk():
    return load_head("tool/vulkan-sdk/api_v1.py", "\nclass CTool",
                     ["from tool_c393ba5c6fa14f66.api.ctool import InitCTool"])


def make_sdk(root, bin_dir, inc_dir, exe):
    (root / bin_dir).mkdir(parents = True)
    (root / bin_dir / ("glslc" + exe)).write_text("")
    (root / inc_dir / "vulkan").mkdir(parents = True)
    (root / inc_dir / "vulkan" / "vulkan_core.h").write_text("")


def test_sdk_layout_lower_case_outside_windows(vksdk, tmp_path):
    make_sdk(tmp_path, "bin", "include", "")
    layout = vksdk.sdk_layout(str(tmp_path), "darwin")
    assert pathlib.Path(layout["glslc"]).parent.name == "bin"       # not "Bin" on a case-insensitive disk
    assert pathlib.Path(layout["lib"]).name == "lib"


def test_sdk_layout_lunarg_windows(vksdk, tmp_path):
    make_sdk(tmp_path, "Bin", "Include", ".exe")
    layout = vksdk.sdk_layout(str(tmp_path), "windows")
    assert pathlib.Path(layout["glslc"]).name == "glslc.exe"
    assert pathlib.Path(layout["include"]).name == "Include"


def test_sdk_layout_not_an_sdk(vksdk, tmp_path):
    assert vksdk.sdk_layout(str(tmp_path), "linux") is None


# --------------------------------------------------------------------------------------------
# common_llama_cpp.parse_llama_log with -v (llama.cpp b11324 prints devices only when verbose)

VERBOSE_LOG = """0.00.002.021 I llama_completion: llama backend init
0.00.153.092 I llama_prepare_model_devices: using device Vulkan0 (Apple M4) (unknown id) - 12123 MiB free
0.00.201.462 I load_tensors: offloaded 25/25 layers to GPU
0.01.807.491 I system_info: n_threads = 4 (n_threads_batch = 4) / 10 | CPU : NEON = 1 | ARM_FMA = 1 |
0.02.841.114 I common_perf_print:    sampling time =       4.24 ms
0.02.841.120 I common_perf_print: prompt eval time =      36.04 ms /    18 tokens (    2.00 ms per token,   499.42 tokens per second)
0.02.841.125 I common_perf_print:        eval time =     490.00 ms /    63 runs   (    7.78 ms per token,   128.57 tokens per second)
"""


def test_parse_llama_log_devices_and_offload():
    m = load_module("category/program/api/common_llama_cpp.py", "common_llama_cpp")
    r = m.parse_llama_log(VERBOSE_LOG)
    assert r["devices"] == [{"name": "Vulkan0", "description": "Apple M4"}]
    assert r["gpu_layers"] == {"offloaded": 25, "total": 25}
    assert r["prompt_tokens_per_second"] == 499.42 and r["generation_tokens_per_second"] == 128.57
    assert r["threads"] == 4


# --------------------------------------------------------------------------------------------
# common_llama_cpp.run_flags: targets and offload parameters -> llama.cpp flags

@pytest.mark.parametrize("compute, params, flags, settings", [
    (["cpu"], {}, "-ngl 0 --device none", {}),
    (["cuda"], {}, "", {}),
    (["cpu", "cuda"], {"ngl": "12"}, "-ngl 12", {"ngl": "12"}),
    (["cuda", "vulkan"], {"devices": "CUDA0,Vulkan0", "split_mode": "layer", "tensor_split": "3,1"},
     "--device CUDA0,Vulkan0 -sm layer -ts 3,1", {"devices": "CUDA0,Vulkan0", "split_mode": "layer", "tensor_split": "3,1"}),
    (["cpu"], {"ngl": "4", "threads": "8"}, "-ngl 4 -t 8 --device none", {"ngl": "4", "threads": "8"}),
    (["cpu"], {"devices": "MTL0"}, "-ngl 0 --device MTL0", {"devices": "MTL0"}),
    (["metal"], {"main_gpu": "0", "ngl": ""}, "-mg 0", {"main_gpu": "0"}),
])
def test_llama_cpp_run_flags(compute, params, flags, settings):
    m = load_module("category/program/api/common_llama_cpp.py", "common_llama_cpp_flags")
    assert m.run_flags(compute, params) == (flags, settings)


def test_llama_cpp_release_gpu_targets():
    ll = load_head("tool/llama-cpp/api_v1.py", "\nclass CTool",
                   ["from tool_c393ba5c6fa14f66.api.ctool import InitCTool"])
    assert set(ll.GPU_TARGETS) >= {"cuda", "vulkan", "metal"}
    assert ll.backend_from_compute(["cpu", "cuda"], "linux") == "cuda"
    assert ll.backend_from_compute(["cpu"], "darwin") == "metal"


def test_build_llama_cpp_default_checkout_is_the_release_build():
    """A release and a source build of llama.cpp compare out of the box: the same default build."""
    import yaml
    tool = yaml.safe_load((REPO_ROOT / "tool" / "llama-cpp" / "_desc.yaml").read_text(encoding = "utf-8"))
    desc = (REPO_ROOT / "program" / "build-llama-cpp" / "_desc.yaml").read_text(encoding = "utf-8")
    assert "checkout: '{{params.checkout|b%s}}'" % tool["default_version"] in desc
