"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/intel-npu-runtime (Intel's Linux NPU user-space driver without root): the
build for a distribution release, the pinned archives, the firmware and device checks, and an
install from a fake GitHub and Ubuntu archive (Intel's tarball with its .deb packages).
"""

import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import tarfile
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def npu():
    """tool/intel-npu-runtime/api_v1.py with stand-ins for cMeta (its base class) and the shared
    .deb helpers loaded from category/tool/api/common_deb.py."""
    deb_path = REPO_ROOT / "category" / "tool" / "api" / "common_deb.py"
    deb = {"__name__": "common_deb", "__file__": str(deb_path)}
    exec(compile(deb_path.read_text(encoding = "utf-8"), str(deb_path), "exec"), deb)

    path = REPO_ROOT / "tool" / "intel-npu-runtime" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "class InitCTool:\n    pass")
    src = src.replace("from tool_c393ba5c6fa14f66.api.common_deb import extract_deb, sha256_of", "")
    ns = {"__name__": "npu_runtime", "__file__": str(path), "extract_deb": deb["extract_deb"], "sha256_of": deb["sha256_of"]}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def test_the_build_for_a_release(npu):
    release_for = npu["release_for"]
    assert release_for("24.04") == "24.04"
    assert release_for("26.04") == "26.04"
    assert release_for("26.10") == "26.04"
    assert release_for("25.10") == "24.04"      # between the two: the 24.04 build (glibc 2.38+)
    assert release_for("13") == "24.04"         # Debian 13
    assert release_for(None) == "24.04"


def test_the_archives_are_pinned(npu):
    for path, sha in list(npu["TARBALLS"].values()) + [npu["LEVEL_ZERO"]] + list(npu["TBB"].values()):
        assert re.fullmatch(r"[0-9a-f]{64}", sha), path
    assert set(npu["TARBALLS"]) == set(npu["TBB"]) == set(npu["TARBALL_MB"]) == {"24.04", "26.04"}
    assert all(npu["VERSION"] in p for p, _ in npu["TARBALLS"].values())
    assert "intel-fw-npu" not in npu["PACKAGES"]


def test_firmware_and_device_checks(npu, tmp_path):
    fw = tmp_path / "vpu"
    fw.mkdir()
    for name in ("vpu_37xx_v1.bin.zst", "vpu_40xx_v1.bin.zst"):
        (fw / name).write_bytes(b"x")
    files = npu["firmware_files"]((str(fw), str(tmp_path / "missing")))
    assert [os.path.basename(f) for f in files] == ["vpu_37xx_v1.bin.zst", "vpu_40xx_v1.bin.zst"]
    assert npu["firmware_files"]((str(tmp_path / "missing"),)) == []

    accel = tmp_path / "accel"
    accel.mkdir()
    assert npu["npu_access"](str(accel)) == {}
    (accel / "accel0").write_text("")
    assert list(npu["npu_access"](str(accel))) == [str(accel / "accel0")]


def test_root_of_needs_the_marker(npu, tmp_path):
    lib = tmp_path / "content" / "1.38.0" / npu["DRIVER_LIB"]
    lib.parent.mkdir(parents = True)
    lib.write_bytes(b"x")
    assert npu["root_of"](str(lib)) is None
    (tmp_path / "content" / "1.38.0" / npu["MARKER"]).write_text("{}")
    assert npu["root_of"](str(lib)) == str(tmp_path / "content" / "1.38.0")


def ar_entry(name, data):
    header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode()
    return header + data + (b"\n" if len(data) % 2 else b"")


def make_deb(path, files):
    """A .deb with a gzip data.tar of {path: bytes}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj = buf, mode = "w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo("./" + name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    path.write_bytes(b"!<arch>\n" + ar_entry("debian-binary", b"2.0\n") + ar_entry("data.tar.gz", buf.getvalue()))


class FakeCM:
    def __init__(self, server):
        self.server = server
        self.downloads = []

    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def access(self, ii):
        assert ii["arg1"].startswith("download-file")
        src = self.server[ii["url"]]
        d = os.path.join(os.getcwd(), ii["directory"])
        os.makedirs(d, exist_ok = True)
        shutil.copy(src, os.path.join(d, ii["filename"]))
        self.downloads.append(ii["filename"])
        return {"return": 0}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def server(npu, tmp_path, monkeypatch):
    """Intel's 24.04 tarball (its three packages), libze1 and libtbb12 on a fake server."""
    store = tmp_path / "server"
    store.mkdir()
    lib = "usr/lib/x86_64-linux-gnu"
    debs = store / "debs"
    debs.mkdir()
    make_deb(debs / "intel-level-zero-npu_1.38.0~ubuntu24.04_amd64.deb", {f"{lib}/libze_intel_npu.so.1": b"\x7fELF npu"})
    make_deb(debs / "intel-driver-compiler-npu_1.38.0~ubuntu24.04_amd64.deb",
             {f"{lib}/libopenvino_intel_npu_compiler.so": b"\x7fELF compiler"})
    make_deb(debs / "intel-fw-npu_1.38.0~ubuntu24.04_amd64.deb", {"lib/firmware/updates/intel/vpu/vpu_50xx_v1.bin": b"fw"})
    tarball = store / "linux-npu-driver-ubuntu2404.tar.gz"
    with tarfile.open(tarball, "w:gz") as t:
        for deb in sorted(debs.iterdir()):
            t.add(deb, arcname = "./" + deb.name)
    make_deb(store / "libze1_1.34.0+u24.04_amd64.deb", {f"{lib}/libze_loader.so.1": b"\x7fELF loader"})
    make_deb(store / "libtbb12_2021.11.0-2ubuntu2_amd64.deb", {f"{lib}/libtbb.so.12": b"\x7fELF tbb"})

    monkeypatch.setitem(npu["TARBALLS"], "24.04", ("intel/npu/ubuntu2404.tar.gz", sha(tarball)))
    monkeypatch.setitem(npu, "LEVEL_ZERO", ("oneapi/libze1_1.34.0+u24.04_amd64.deb", sha(store / "libze1_1.34.0+u24.04_amd64.deb")))
    monkeypatch.setitem(npu["TBB"], "24.04", ("pool/libtbb12_2021.11.0-2ubuntu2_amd64.deb",
                                              sha(store / "libtbb12_2021.11.0-2ubuntu2_amd64.deb")))
    monkeypatch.setitem(npu, "system_lib", lambda name, dirs = None: None)    # the system has no oneTBB
    return {f"{npu['GITHUB']}/intel/npu/ubuntu2404.tar.gz": str(tarball),
            f"{npu['GITHUB']}/oneapi/libze1_1.34.0+u24.04_amd64.deb": str(store / "libze1_1.34.0+u24.04_amd64.deb"),
            f"{npu['UBUNTU']}/pool/libtbb12_2021.11.0-2ubuntu2_amd64.deb": str(store / "libtbb12_2021.11.0-2ubuntu2_amd64.deb")}


def context(uname = "linux", version_id = "24.04"):
    return {"control": {"con": False, "quiet": True, "verbose": False},
            "tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": uname, "uarch": "amd64"},
                                                             "os_extra": {"version_id": version_id}}}}}


def test_install_unpacks_the_driver_without_root(npu, server, tmp_path, monkeypatch):
    entry = tmp_path / "cache-entry"
    entry.mkdir()
    monkeypatch.chdir(entry)
    t = npu["CTool"].__new__(npu["CTool"])
    t.cm = FakeCM(server)

    r = t.install(context(), {})
    assert r["return"] == 0, r
    root = entry / "content" / "1.38.0"
    lib = root / "usr" / "lib" / "x86_64-linux-gnu"
    assert os.path.normpath(r["found_path"]) == str(root / npu["DRIVER_LIB"])
    assert (lib / "libze_intel_npu.so.1").read_bytes() == b"\x7fELF npu"
    assert (lib / "libopenvino_intel_npu_compiler.so").is_file()
    assert (lib / "libze_loader.so.1").is_file() and (lib / "libtbb.so.12").is_file()
    assert not (root / "lib" / "firmware").exists()           # the firmware needs root: left out
    assert not (entry / "downloads").exists()
    marker = json.loads((root / npu["MARKER"]).read_text())
    assert marker["version"] == "1.38.0" and marker["release"] == "24.04" and marker["tbb"] is True
    assert len(marker["sha256"]) == 5                          # the tarball, its 2 packages, libze1, libtbb12

    # what detect() and finish_dynamic_result() make of it
    e = t._entry(r["found_path"])
    assert e["features"]["kind"] == "cmeta" and [os.path.normpath(d) for d in e["features"]["lib_dirs"]] == [str(lib)]
    out = t.finish_dynamic_result(context(), dict(e), {})
    assert [os.path.normpath(d) for d in out["result"]["_aggregate"]["env"]["+LD_LIBRARY_PATH"]] == [str(lib)]


def test_install_checks_the_sha256(npu, server, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(npu["TARBALLS"], "24.04", (npu["TARBALLS"]["24.04"][0], "0" * 64))
    t = npu["CTool"].__new__(npu["CTool"])
    t.cm = FakeCM(server)
    r = t.install(context(), {})
    assert r["return"] == 1 and "sha256" in r["error"]


def test_install_elsewhere(npu, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = npu["CTool"].__new__(npu["CTool"])
    t.cm = FakeCM({})
    r = t.install(context("windows"), {})
    assert r["return"] == 1 and "Windows Update" in r["error"]


@pytest.fixture(scope = "module")
def target():
    """task/target--npu-intel/api_v1.py with a stand-in for its cMeta base class."""
    path = REPO_ROOT / "task" / "target--npu-intel" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask:\n    pass")
    ns = {"__name__": "target_npu_intel", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


class SetupCM:
    """Records the setup calls and answers like task/setup: the tool's result in global."""
    def __init__(self):
        self.calls = []

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def access(self, ii):
        self.calls.append(ii["name"])
        ii["ctx"]["tasks"]["global"]["intel-npu-runtime"] = {
            "path": "/cache/content/1.38.0/libze_intel_npu.so.1", "version": "1.38.0", "features": {"kind": "cmeta"}}
        return {"return": 0}


LUNAR_LAKE = {"pci_id": "8086:643e", "platform": "Lunar Lake", "npu_generation": "40xx", "node": "accel0", "driver": "intel_vpu"}


def target_ctx(uname = "linux", uarch = "amd64"):
    return {"control": {"con": False, "quiet": True, "verbose": False},
            "tasks": {"local": {}, "global": {"host": {"os": {"uname": uname, "uarch": uarch}}}}}


def test_the_target_sets_up_the_npu_runtime(target):
    t = target["CTask"].__new__(target["CTask"])
    t.cm = SetupCM()
    r = t.finish_dynamic_result(target_ctx(), {"features": {"devices": [LUNAR_LAKE]}}, {})
    assert r["return"] == 0
    assert t.cm.calls == [target["INTEL_NPU_RUNTIME"]]
    assert r["result"]["features"]["runtime"] == {
        "path": "/cache/content/1.38.0/libze_intel_npu.so.1", "version": "1.38.0", "kind": "cmeta"}


@pytest.mark.parametrize("ctx, features, params", [
    (target_ctx("windows"), {"devices": [LUNAR_LAKE]}, {}),            # Windows Update brings the driver
    (target_ctx(uarch = "arm64"), {"devices": [LUNAR_LAKE]}, {}),      # Intel builds it for x86_64 only
    (target_ctx(), {"devices": [LUNAR_LAKE]}, {"skip_runtime": True}),
    (target_ctx(), {}, {}),                                             # no NPU found
])
def test_the_target_leaves_the_runtime(target, ctx, features, params):
    t = target["CTask"].__new__(target["CTask"])
    t.cm = SetupCM()
    r = t.finish_dynamic_result(ctx, {"features": dict(features)}, params)
    assert r["return"] == 0 and t.cm.calls == [] and "runtime" not in r["result"]["features"]


def test_the_npu_on_the_pci_bus(target, tmp_path):
    for slot, vendor, device in (("0000:00:0b.0", "0x8086", "0x643e"),      # the NPU
                                 ("0000:00:02.0", "0x8086", "0x64a0"),      # the Intel GPU
                                 ("0000:01:00.0", "0x10de", "0x2860")):     # an NVIDIA GPU
        d = tmp_path / slot.replace(":", "-")                               # (no ":" in Windows names)
        d.mkdir()
        (d / "vendor").write_text(vendor + "\n")
        (d / "device").write_text(device + "\n")
    assert target["intel_npus_on_pci"](str(tmp_path)) == [
        {"pci_id": "8086:643e", "platform": "Lunar Lake", "npu_generation": "40xx"}]
    assert target["intel_npus_on_pci"](str(tmp_path / "missing")) == []


class ProbeCM:
    """The probe's temp file through cm.utils.files, and errors."""
    def __init__(self):
        def read_file(path, encoding = None, remove_after_read = False):
            with open(path, encoding = encoding) as f:
                return {"return": 0, "data": f.read()}
        self.utils = types.SimpleNamespace(files = types.SimpleNamespace(read_file = read_file))

    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)


@pytest.mark.parametrize("on_pci", [[], [{"pci_id": "8086:b03e", "platform": "Panther Lake", "npu_generation": "50xx"}]])
def test_no_accel_device(target, tmp_path, monkeypatch, on_pci):
    probe = tmp_path / "probe.txt"
    probe.write_text("")
    monkeypatch.setitem(target, "intel_npus_on_pci", lambda: on_pci)
    t = target["CTask"].__new__(target["CTask"])
    t.cm = ProbeCM()
    ctx = target_ctx()
    ctx["tasks"]["local"]["generate-temp-file-target-npu-intel"] = {"temp_file": str(probe)}
    r = t._detect(ctx)
    assert r["return"] == 1 and "no accel device of the intel_vpu driver" in r["error"]
    if on_pci:     # the NPU without a driver: the kernel or its firmware
        assert "Panther Lake NPU (8086:b03e) is on the PCI bus" in r["error"] and "vpu_50xx_v1.bin" in r["error"]
    else:
        assert "PCI" not in r["error"]


def test_glibc(npu):
    assert npu["glibc_of"](("glibc", "2.39")) == (2, 39)
    assert npu["glibc_of"](("glibc", "2.35")) < npu["GLIBC_MIN"]
    assert npu["glibc_of"](("", "")) is None            # musl, or not found


def test_install_needs_glibc_2_38(npu, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(npu["platform"], "libc_ver", lambda *a, **k: ("glibc", "2.35"))     # Ubuntu 22.04
    t = npu["CTool"].__new__(npu["CTool"])
    t.cm = FakeCM({})
    r = t.install(context(version_id = "22.04"), {})
    assert r["return"] == 1 and "glibc 2.38 or newer" in r["error"] and "2.35" in r["error"]
    assert not list(tmp_path.iterdir())                  # nothing downloaded
