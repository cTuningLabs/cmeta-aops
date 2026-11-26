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


COMMON_DEB_IMPORT = "from tool_c393ba5c6fa14f66.api.common_deb import ar_members, extract_deb, sha256_of, zstd_decompress"


def common_deb():
    """category/tool/api/common_deb.py, which the tools import as tool_c393ba5c6fa14f66.api.common_deb."""
    path = REPO_ROOT / "category" / "tool" / "api" / "common_deb.py"
    ns = {"__name__": "common_deb", "__file__": str(path)}
    exec(compile(path.read_text(encoding = "utf-8"), str(path), "exec"), ns)
    return ns


def load_head(rel_path, class_line, imports):
    """The module-level code of a hook file, up to its class (which needs cMeta), with the shared
    .deb helpers it imports."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    head = src[:src.index(class_line)]
    ns = {"__name__": "helpers", "__file__": str(path)}
    if COMMON_DEB_IMPORT in head:
        deb = common_deb()
        ns.update({k: deb[k] for k in ("ar_members", "extract_deb", "sha256_of", "zstd_decompress")})
    for line in imports + [COMMON_DEB_IMPORT]:
        head = head.replace(line, "")
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


def test_the_lines_are_the_data_of_the_description(tool):
    # releases: of _desc.yaml, in their order: a new release of the runtime is an entry there, not code
    import yaml
    desc = yaml.safe_load((REPO_ROOT / "tool" / "intel-gpu-runtime" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert list(tool["LINES"]) == [str(v) for v in desc["releases"]] == [tool["MODERN"], tool["LEGACY"]]
    assert tool["LINES"][tool["MODERN"]]["default"] is True and tool["LINES"][tool["LEGACY"]]["device_id_prefixes"]
    assert all(line["for"] for line in tool["LINES"].values())

    # a line the data adds is chosen by its device ids, the default line keeps the rest
    lines = dict(tool["LINES"], **{"99.1": {"device_id_prefixes": ["e2"], "packages": []}})
    assert tool["line_for"](["e20b"], lines) == "99.1"
    assert tool["line_for"](["e20b", "a7a0"], lines) == tool["MODERN"]
    assert tool["line_for"](["591b"], lines) == tool["LEGACY"]


def test_the_line_of_gen12_and_later_provides_the_offline_compiler_and_the_level_zero_headers(tool):
    # PyTorch's XPU build compiles its SYCL kernels ahead of time (icx -fsycl-targets=spir64_gen: ocloc of the same
    # compute-runtime release, on PATH) and includes level_zero/ze_api.h (ATen's LazyLevelZero: libze-dev of the
    # loader's release, on CPATH); the legacy1 line is no target of it and keeps its packages
    names = [p.rsplit("/", 1)[-1] for p, _ in tool["RELEASES"][tool["MODERN"]]]
    assert "intel-ocloc_" + tool["MODERN"] + "-0_amd64.deb" in names
    loader = next(n for n in names if n.startswith("libze1_"))
    assert loader.replace("libze1_", "libze-dev_") in names
    # ... and the loader as a linker names it (-lze_loader: Triton's Intel backend links its launcher against it),
    # on LIBRARY_PATH - a package may provide several things
    assert tool["provided"](tool["MODERN"]) == [{"file": "usr/bin/ocloc", "env": "PATH"},
                                                {"file": "usr/include/level_zero/ze_api.h", "env": "CPATH", "dir": "usr/include"},
                                                {"file": "usr/lib/x86_64-linux-gnu/libze_loader.so", "env": "LIBRARY_PATH"}]
    assert tool["provided"](tool["LEGACY"]) == []
    assert not any("ocloc" in p for p, _ in tool["RELEASES"][tool["LEGACY"]])


def test_what_a_line_provides_is_linked_and_exported(tool, tmp_path):
    modern = tool["MODERN"]
    root = tmp_path / "content" / modern
    assert tool["provide"](str(root), modern) == ["usr/bin/ocloc", "usr/include/level_zero/ze_api.h",
                                                  "usr/lib/x86_64-linux-gnu/libze_loader.so"]
    assert tool["exports"](str(root), modern) == {}

    # the package names its command ocloc-<version> (update-alternatives makes "ocloc", which an unpacking without
    # root does not run): a link of that name beside it, to the newest; an "ocloc" that is there is kept
    bin_dir = root / "usr" / "bin"
    bin_dir.mkdir(parents = True)
    for name in ("ocloc-9.1.2", "ocloc-26.35.1"):
        (bin_dir / name).write_text("#!/bin/sh")
    headers = root / "usr" / "include" / "level_zero"
    headers.mkdir(parents = True)
    (headers / "ze_api.h").write_text("")
    libs = root / "usr" / "lib" / "x86_64-linux-gnu"
    libs.mkdir(parents = True)
    (libs / "libze_loader.so").write_text("")
    if os.name == "nt":
        pytest.skip("symbolic links need privileges on Windows (the runtime is for Linux)")
    assert tool["provide"](str(root), modern) == []
    assert os.path.realpath(bin_dir / "ocloc") == os.path.realpath(bin_dir / "ocloc-26.35.1")
    assert tool["command_link"](str(root), "usr/bin/ocloc") == str(bin_dir / "ocloc")
    assert tool["exports"](str(root), modern) == {"PATH": [str(bin_dir)], "CPATH": [str(root / "usr" / "include")],
                                                  "LIBRARY_PATH": [str(libs)]}


def test_a_runtime_unpacked_before_a_package_was_added_gets_it_on_its_next_use(tool):
    modern = tool["MODERN"]
    listed = [p for p, _ in tool["RELEASES"][modern]]
    assert tool["missing_packages"]({"version": modern, "packages": listed}) == []

    # an entry of the night of 2026-11-24 (with ocloc, before the headers)
    before = [p for p in listed if "/libze-dev_" not in p]
    assert [p.rsplit("/", 1)[-1] for p in tool["missing_packages"]({"version": modern, "packages": before})] == \
           [p.rsplit("/", 1)[-1] for p in listed if "/libze-dev_" in p]

    # a line no longer known has nothing to compare with
    assert tool["missing_packages"]({"version": "1.2.3", "packages": []}) == []


def runtime_class():
    """tool/intel-gpu-runtime's CTool, its base class a stand-in (no cMeta)."""
    path = REPO_ROOT / "tool" / "intel-gpu-runtime" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "class InitCTool: pass")
    deb = common_deb()
    ns = {"__name__": "intel_gpu_runtime_under_test", "__file__": str(path)}
    ns.update({k: deb[k] for k in ("ar_members", "extract_deb", "sha256_of", "zstd_decompress")})
    exec(compile(src.replace(COMMON_DEB_IMPORT, ""), str(path), "exec"), ns)
    return ns["CTool"]


def test_complete_unpacks_only_what_the_line_gained_and_records_it(tool, tmp_path):
    import json
    modern = tool["MODERN"]
    listed = [p for p, _ in tool["RELEASES"][modern]]
    root = tmp_path / "task--setup--intel-gpu-runtime--x" / "content" / modern
    root.mkdir(parents = True)
    (root / tool["MARKER"]).write_text(json.dumps({"version": modern, "packages": [p for p in listed if "/libze-dev_" not in p],
                                                   "sha256": {}}))
    (root / "usr" / "bin").mkdir(parents = True)
    (root / "usr" / "bin" / "ocloc").write_text("#!/bin/sh")

    runtime = object.__new__(runtime_class())
    unpacked = []

    def unpack(ctx, params, entry, into, packages):
        unpacked.append((entry, into, [p for p, _ in packages]))
        (root / "usr" / "include" / "level_zero").mkdir(parents = True)
        (root / "usr" / "include" / "level_zero" / "ze_api.h").write_text("")
        (root / "usr" / "lib" / "x86_64-linux-gnu").mkdir(parents = True)
        (root / "usr" / "lib" / "x86_64-linux-gnu" / "libze_loader.so").write_text("")
        return {"return": 0, "sha256": {p.rsplit("/", 1)[-1]: "f" * 64 for p, _ in packages}}

    runtime._unpack = unpack
    r = runtime.complete({"control": {}}, {}, str(root))
    assert r == {"return": 0, "version": modern}
    assert unpacked == [(str(tmp_path / "task--setup--intel-gpu-runtime--x"), str(root), [p for p in listed if "/libze-dev_" in p])]
    marker = json.loads((root / tool["MARKER"]).read_text())
    assert sorted(marker["packages"]) == sorted(listed) and list(marker["sha256"]) == ["libze-dev_1.34.0+u24.04_amd64.deb"]

    # the next use has nothing to unpack
    assert runtime.complete({"control": {}}, {}, str(root)) == {"return": 0, "version": modern} and len(unpacked) == 1


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
