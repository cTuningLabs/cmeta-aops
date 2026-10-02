"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/intel-gpu-runtime (the Intel GPU compute runtime for Linux without root)
and of target--xpu's GPU probe: the release line of a GPU, the sysfs scan, the system's ICDs,
the pinned packages and unpacking a .deb without dpkg.
"""

import io
import os
import pathlib
import re
import tarfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_head(rel_path, class_line, imports):
    """The module-level code of a hook file, up to its class (which needs cMeta)."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    head = src[:src.index(class_line)]
    for line in imports:
        head = head.replace(line, "")
    ns = {"__name__": "helpers", "__file__": str(path)}
    exec(compile(head, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def tool():
    return load_head("tool/intel-gpu-runtime/api_v1.py", "\nclass CTool",
                     ["from tool_c393ba5c6fa14f66.api.ctool import InitCTool"])


@pytest.fixture(scope = "module")
def target():
    return load_head("task/target--xpu/api_v1.py", "\nclass CTask",
                     ["from task_c36be4b9314a45e0.api.ctask import InitCTask"])


def test_the_release_line_follows_the_gpu(tool):
    line, modern, legacy = tool["line_for"], tool["MODERN"], tool["LEGACY"]
    assert line(["591b"]) == legacy             # Kaby Lake HD Graphics 630 (Gen9.5)
    assert line(["0x3E9B"]) == legacy           # Coffee Lake UHD 630
    assert line(["8a52"]) == legacy             # Ice Lake (Gen11)
    assert line(["a7a0"]) == modern             # Raptor Lake-P Iris Xe (Gen12)
    assert line(["b080"]) == modern             # Panther Lake
    assert line(["56a0"]) == modern             # Arc A770
    assert line(["591b", "56a0"]) == modern     # an old iGPU with an Arc card: the new line
    assert line([]) == modern                   # nothing known (WSL2)


def test_intel_gpus_from_sysfs(tool, tmp_path):
    def device(address, vendor, cls, dev):
        d = tmp_path / address
        d.mkdir()
        for name, value in (("vendor", vendor), ("class", cls), ("device", dev)):
            (d / name).write_text(value + "\n")
    # (sysfs names the folders 0000:00:02.0; dashes here, as Windows refuses ':' in a name)
    device("0000-00-02.0", "0x8086", "0x030000", "0x591b")    # the Intel iGPU
    device("0000-02-00.0", "0x10de", "0x030200", "0x134d")    # an NVIDIA GPU
    device("0000-00-14.0", "0x8086", "0x0c0330", "0xa2af")    # an Intel USB controller
    assert tool["intel_gpus"](str(tmp_path)) == [("0000-00-02.0", "591b")]


def test_the_packages_are_pinned(tool):
    for version, packages in tool["RELEASES"].items():
        names = [p.rsplit("/", 1)[-1] for p, _ in packages]
        assert all(n.endswith(".deb") for n in names), version
        assert any(n.startswith("intel-opencl-icd") for n in names), version
        assert any("igc-opencl" in n for n in names), version
        for path, sha in packages:
            assert sha is None or re.fullmatch(r"[0-9a-f]{64}", sha), path
    # every package is pinned
    assert all(sha for packages in tool["RELEASES"].values() for _, sha in packages)


def ar_entry(name, data):
    header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode()
    return header + data + (b"\n" if len(data) % 2 else b"")


def make_deb(path, files, links):
    """A .deb with a gzip data.tar: files {path: bytes}, links {path: target}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj = buf, mode = "w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo("./" + name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        for name, target in links.items():
            info = tarfile.TarInfo("./" + name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            t.addfile(info)
    path.write_bytes(b"!<arch>\n" + ar_entry("debian-binary", b"2.0\n") + ar_entry("data.tar.gz", buf.getvalue()))


def test_extract_a_deb_without_dpkg(tool, tmp_path):
    deb = tmp_path / "libtest_1.0_amd64.deb"
    make_deb(deb, {"usr/lib/x86_64-linux-gnu/libtest.so.1.0": b"\x7fELF fake",
                   "usr/lib/x86_64-linux-gnu/intel-opencl/libigdrcl.so": b"\x7fELF icd"},
             {"usr/lib/x86_64-linux-gnu/libtest.so.1": "libtest.so.1.0"})
    root = tmp_path / "root"
    tool["extract_deb"](str(deb), str(root), use_dpkg = False)
    lib = root / "usr" / "lib" / "x86_64-linux-gnu"
    assert (lib / "libtest.so.1.0").read_bytes() == b"\x7fELF fake"
    assert (lib / "intel-opencl" / "libigdrcl.so").is_file()
    if os.name != "nt":   # symlinks need privileges on Windows
        assert os.readlink(lib / "libtest.so.1") == "libtest.so.1.0"
    with pytest.raises(ValueError):
        (tmp_path / "bad.deb").write_bytes(b"not an archive")
        tool["extract_deb"](str(tmp_path / "bad.deb"), str(root), use_dpkg = False)


def test_system_icds(tool, tmp_path):
    lib = tmp_path / "libigdrcl.so"
    lib.write_bytes(b"x")
    vendors = tmp_path / "vendors"
    vendors.mkdir()
    (vendors / "intel.icd").write_text(str(lib) + "\n")
    (vendors / "nvidia.icd").write_text("libnvidia-opencl.so.1\n")
    (vendors / "missing.icd").write_text(str(tmp_path / "gone" / "libigdrcl.so") + "\n")
    assert tool["system_icds"](str(vendors)) == [str(lib)]


def test_root_of_needs_the_marker(tool, tmp_path):
    lib = tmp_path / "content" / "26.35.39758.10" / tool["ICD_LIB"]
    lib.parent.mkdir(parents = True)
    lib.write_bytes(b"x")
    assert tool["root_of"](str(lib)) is None
    (tmp_path / "content" / "26.35.39758.10" / tool["MARKER"]).write_text("{}")
    assert tool["root_of"](str(lib)) == str(tmp_path / "content" / "26.35.39758.10")
    # the legacy1 ICD has another name, at the same depth
    legacy = tmp_path / "content" / "24.35.30872.36" / tool["ICD_LIBS"][1]
    legacy.parent.mkdir(parents = True)
    legacy.write_bytes(b"x")
    (tmp_path / "content" / "24.35.30872.36" / tool["MARKER"]).write_text("{}")
    assert tool["root_of"](str(legacy)) == str(tmp_path / "content" / "24.35.30872.36")


def test_target_xpu_parses_lspci_and_windows_names(target):
    lspci = ("00:02.0 VGA compatible controller: Intel Corporation HD Graphics 630 (rev 04)\n"
             "02:00.0 3D controller: NVIDIA Corporation GM108M [GeForce 940MX] (rev a2)\n")
    names = [d["name"] for d in target["parse_gpus"](lspci, "linux")]
    assert names == ["Intel Corporation HD Graphics 630 (rev 04)", "NVIDIA Corporation GM108M [GeForce 940MX] (rev a2)"]

    # WSL2: lspci sees Microsoft's virtual adapter, then the probe adds what Windows lists
    wsl = ("2bd6:00:00.0 3D controller: Microsoft Corporation Basic Render Driver\n\n"
           "Name          : Intel(R) Graphics\nDriverVersion : 32.0.101.8991\n\n"
           "Name          : NVIDIA RTX PRO 1000 Blackwell Generation Laptop GPU\nDriverVersion : 32.0.15.6109\n")
    devices = target["parse_gpus"](wsl, "linux")
    intel = [d for d in devices if "intel" in d["name"].lower()]
    assert intel == [{"name": "Intel(R) Graphics", "driver_version": "32.0.101.8991"}]

    windows = "Name          : Intel(R) Graphics\r\nDriverVersion : 32.0.101.8991\r\n"
    assert target["parse_gpus"](windows, "windows") == [{"name": "Intel(R) Graphics", "driver_version": "32.0.101.8991"}]
