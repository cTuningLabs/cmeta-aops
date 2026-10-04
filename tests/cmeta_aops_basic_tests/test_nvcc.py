"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/nvcc: the CUDA toolkit from NVIDIA's redistributable archives
(redist.py: the release for the driver and the GPU, the components, unpacking them into one
toolkit, an install from a fake NVIDIA server with libraries added on demand), the host
compilers a toolkit supports (host.py, from its host_config.h) and the nvcc hooks that use
them; also the Visual Studio release that tool/microsoft.visual-studio installs for a version.
"""

import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import tarfile
import zipfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The CUDA releases of NVIDIA's index (a part), with the nvcc version of each
NVCC = {"11.4.4": "11.4.152", "12.2.2": "12.2.140", "12.4.1": "12.4.131", "12.5.1": "12.5.82",
        "12.9.0": "12.9.41", "12.9.1": "12.9.86", "12.9.2": "12.9.86", "13.0.2": "13.0.88",
        "13.3.1": "13.3.73", "13.4.2": "13.4.92"}
RELEASES = sorted(NVCC, key = lambda v: tuple(int(x) for x in v.split(".")))


@pytest.fixture(scope = "module")
def redist():
    spec = importlib.util.spec_from_file_location("nvcc_redist", REPO_ROOT / "tool" / "nvcc" / "redist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def matches(spec, version):
    """cm.packages.match_version in short: a plain version is a prefix; >=, <, == and commas."""
    def key(v):
        return tuple(int(x) for x in re.findall(r"\d+", v))
    if not any(op in spec for op in "<>=!"):
        return version == spec or version.startswith(spec + ".")
    for part in spec.split(","):
        op, v = re.match(r"\s*(==|>=|<=|>|<)\s*(\S+)", part).groups()
        k, kv = key(version), key(v)
        if not {"==": k == kv, ">=": k >= kv, "<=": k <= kv, ">": k > kv, "<": k < kv}[op]:
            return False
    return True


def test_releases_from_the_index(redist):
    html = ('<a href="redistrib_12.9.1.json">x</a> <a href="redistrib_11.0.3.json">'
            '<a href="redistrib_13.4.2.json"> <a href="redistrib_12.9.1.json"> <a href="cuda_nvcc/">')
    assert redist.releases(html) == ["11.0.3", "12.9.1", "13.4.2"]


def test_choose_a_release_for_the_driver_and_the_gpu(redist):
    def choose(wanted, driver, arch):
        return redist.choose(RELEASES, wanted, matches, driver, arch, NVCC.get)

    # GeForce 940MX (sm_50), driver for CUDA 13.0: CUDA 13 dropped Maxwell -> the newest 12.x
    assert choose(None, "13.0", 50) == ("12.9.2", None)
    assert choose("12", "13.0", 50) == ("12.9.2", None)
    release, why = choose("13.0", "13.0", 50)
    assert release is None and "sm_75" in why and "sm_50" in why

    # Blackwell (sm_120), driver for CUDA 13.3: the newest release the driver fully runs
    assert choose(None, "13.3", 120) == ("13.3.1", None)
    assert choose("12.9", "13.3", 120) == ("12.9.2", None)
    assert choose(">=12.4,<12.6", "13.3", 120) == ("12.5.1", None)

    # an exact nvcc version, and a release label instead of one
    assert choose("12.9.86", "13.3", 120) == ("12.9.2", None)
    assert choose("==12.9.41", "13.3", 120) == ("12.9.0", None)
    release, why = choose("12.9.1", "13.3", 120)
    assert release is None and "--version=12.9.86" in why and "--version=12.9" in why
    release, why = choose("12.9.99", "13.3", 120)
    assert release is None and "12.9.99" in why

    # a newer minor version than the driver's when asked for, with a warning; a newer major never
    release, warning = choose("13.4", "13.3", 120)
    assert release == "13.4.2" and "minor version compatibility" in warning
    release, why = choose("13", "12.2", 86)
    assert release is None and "update the NVIDIA driver" in why
    assert choose(None, "12.2", 86) == ("12.2.2", None)

    # Kepler (sm_35): CUDA 11 only
    assert choose(None, "11.4", 35) == ("11.4.4", None)
    release, why = choose(None, "11.4", 30)
    assert release is None and "sm_35" in why

    # nothing known about the machine: the newest
    assert choose(None, None, None) == ("13.4.2", None)
    release, why = choose("10.2", None, None)
    assert release is None and "no CUDA release matches 10.2" in why


def test_library_names(redist):
    assert redist.lib_components(["$cublas", "$cudart"]) == ["libcublas"]
    assert redist.lib_components(["cublasLt", "libcufft", "cusolver"]) == \
        ["libcublas", "libcufft", "libnvjitlink", "libcusolver", "libcusparse"]
    assert redist.lib_components(["unknown", "", "nvrtc"]) == ["cuda_nvrtc"]
    assert redist.lib_components(None) == []


def test_components_of_a_release(redist):
    def entry(version, *platforms):
        return {"name": "x", "version": version,
                **{p: {"relative_path": f"x/{p}/x-{version}.tar.xz", "sha256": "0" * 64, "size": "2097152"}
                   for p in platforms}}

    # CUDA 13 splits cccl, crt and nvvm out of nvcc; 12.x has cuda_cccl
    m13 = {"release_label": "13.4.2", "cuda_nvcc": entry("13.4.92", "linux-x86_64", "windows-x86_64"),
           "cuda_cudart": entry("13.4.80", "linux-x86_64"), "cccl": entry("13.4.1", "linux-x86_64"),
           "cuda_crt": entry("13.4.92", "linux-x86_64"), "libnvvm": entry("13.4.92", "linux-x86_64"),
           "libcublas": entry("13.4.1.4", "linux-x86_64"), "nsight_compute": entry("2026.3", "linux-x86_64")}
    names = [c[0] for c in redist.components(m13, "linux-x86_64")]
    assert names == ["cuda_nvcc", "cuda_cudart", "cccl", "cuda_crt", "libnvvm"]
    assert [c[0] for c in redist.components(m13, "windows-x86_64")] == ["cuda_nvcc"]
    assert [c[0] for c in redist.components(m13, "linux-sbsa")] == []
    libs = redist.components(m13, "linux-x86_64", redist.lib_components(["cublas"]))
    assert libs == [("libcublas", "x/linux-x86_64/x-13.4.1.4.tar.xz", "0" * 64, 2097152)]
    assert redist.nvcc_version(m13) == "13.4.92"


def test_incompatible(redist):
    assert redist.incompatible("12.9.2", "13.0", 50) is None
    assert "sm_75" in redist.incompatible("13.0.2", "13.0", 61)
    assert "driver" in redist.incompatible("13.0.2", "12.9", 86)
    assert redist.incompatible("12.9.2", "12.2", 86) is None    # a minor version: choose() decides


def can_symlink(tmp_path):
    try:
        os.symlink("x", tmp_path / "link-check")
        return True
    except (OSError, NotImplementedError):
        return False


def add_file(archive, name, data, link = None):
    if isinstance(archive, zipfile.ZipFile):
        archive.writestr(name, data)
        return
    info = tarfile.TarInfo(name)
    if link:
        info.type, info.linkname = tarfile.SYMTYPE, link
        archive.addfile(info)
    else:
        info.size, info.mode = len(data), 0o755 if "/bin/" in name else 0o644
        archive.addfile(info, io.BytesIO(data))


def make_archive(path, top, files, links = {}):
    """An archive as NVIDIA's: everything inside <component>-<platform>-<version>-archive/."""
    if str(path).endswith(".zip"):
        with zipfile.ZipFile(path, "w") as z:
            for name, data in files.items():
                add_file(z, f"{top}/{name}", data)
    else:
        with tarfile.open(path, "w:xz") as t:
            for name, data in files.items():
                add_file(t, f"{top}/{name}", data)
            for name, target in links.items():
                add_file(t, f"{top}/{name}", b"", link = target)


def test_unpack_archives_into_one_toolkit(redist, tmp_path):
    a = tmp_path / "cuda_nvcc-windows-x86_64-12.9.86-archive.zip"
    make_archive(a, "cuda_nvcc-windows-x86_64-12.9.86-archive",
                 {"bin/nvcc.exe": b"nvcc", "bin/nvcc.profile": b"TOP = $(_HERE_)/..", "include/crt/host_config.h": b"//"})
    b = tmp_path / "cuda_cudart-windows-x86_64-12.9.79-archive.zip"
    make_archive(b, "cuda_cudart-windows-x86_64-12.9.79-archive",
                 {"bin/cudart64_12.dll": b"dll", "include/cuda_runtime.h": b"//", "lib/x64/cudart.lib": b"lib"})
    root = tmp_path / "content" / "12.9.2"
    redist.unpack_into(str(a), str(root))
    redist.unpack_into(str(b), str(root))
    assert (root / "bin" / "nvcc.exe").read_bytes() == b"nvcc"
    assert (root / "bin" / "cudart64_12.dll").is_file()
    assert (root / "include" / "crt" / "host_config.h").is_file() and (root / "include" / "cuda_runtime.h").is_file()
    assert (root / "lib" / "x64" / "cudart.lib").is_file()
    assert not (tmp_path / "content" / "12.9.2.unpacking").exists()

    # the same archive again (an update) replaces its files
    redist.unpack_into(str(a), str(root))
    assert (root / "bin" / "nvcc.exe").read_bytes() == b"nvcc"

    bad = tmp_path / "bad.tar.xz"
    bad.write_bytes(b"not an archive")
    with pytest.raises(ValueError):
        redist.unpack_into(str(bad), str(root))


def test_unpack_keeps_links_and_links_the_targets_folder(redist, tmp_path):
    if not can_symlink(tmp_path):
        pytest.skip("symbolic links need privileges here")
    a = tmp_path / "cuda_cudart-linux-x86_64-12.9.79-archive.tar.xz"
    make_archive(a, "cuda_cudart-linux-x86_64-12.9.79-archive",
                 {"lib/libcudart.so.12.9.79": b"\x7fELF", "include/cuda_runtime.h": b"//"},
                 {"lib/libcudart.so.12": "libcudart.so.12.9.79", "lib/libcudart.so": "libcudart.so.12"})
    root = tmp_path / "content" / "12.9.2"
    redist.unpack_into(str(a), str(root))
    assert os.readlink(root / "lib" / "libcudart.so") == "libcudart.so.12"
    assert (root / "lib" / "libcudart.so").read_bytes() == b"\x7fELF"

    d = redist.link_targets(str(root), "linux-x86_64")
    assert d == str(root / "targets" / "x86_64-linux")
    assert (root / "targets" / "x86_64-linux" / "include" / "cuda_runtime.h").is_file()
    assert (root / "targets" / "x86_64-linux" / "lib" / "libcudart.so.12").is_file()
    assert redist.link_targets(str(root), "linux-x86_64") == d     # again: nothing changes
    assert redist.link_targets(str(root), "windows-x86_64") is None


def test_version_json(redist):
    m = {"cuda_nvcc": {"name": "CUDA NVCC", "version": "12.9.86"}, "cuda_cudart": {"name": "CUDA Runtime (cudart)", "version": "12.9.79"}}
    data = redist.version_json(m, "12.9.2", ["cuda_nvcc", "cuda_cudart"])
    assert data["cuda"] == {"name": "CUDA SDK", "version": "12.9.2"}
    assert data["cuda_nvcc"] == {"name": "CUDA NVCC", "version": "12.9.86"}


###############################################################################################
# The nvcc hooks, with a stand-in for the engine and a fake NVIDIA server

class FakePackages:
    def match_version(self, spec, version):
        return {"return": 0, "matched": matches(spec, version)}


class FakeCM:
    """What the nvcc hooks use of cMeta: errors, version matching, download-file and cmd."""

    debug = False

    def __init__(self, server, list_gpu_arch = "", host_cc = None):
        self.server = server              # url -> local archive
        self.list_gpu_arch = list_gpu_arch
        self.downloads = []
        self.packages = FakePackages()
        # what task compiler (lang cpp) sets up as the host compiler
        self.host_cc = host_cc or {"tool": {"name": "gcc-cpp"}, "version": "13.3.0", "qpath": '"/usr/bin/g++"'}
        self.compiler_calls = []

    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def q(self, path):
        return f'"{path}"'

    def access(self, ii):
        if ii.get("arg1", "").startswith("download-file"):
            src = self.server.get(ii["url"])
            if not src:
                return {"return": 1, "error": f"404 {ii['url']}"}
            d = os.path.join(ii.get("chdir") or os.getcwd(), ii["directory"])
            os.makedirs(d, exist_ok = True)
            shutil.copy(src, os.path.join(d, ii["filename"]))
            self.downloads.append(ii["url"].rsplit("/", 1)[-1])
            return {"return": 0}
        if ii.get("arg1", "").startswith("cmd"):
            return {"return": 0, "returncode": 0, "stdout": self.list_gpu_arch}
        if ii.get("arg1", "").startswith("compiler"):
            # the versions asked for through ctx use, as the engine merges them into the setups
            self.compiler_calls.append({k: dict(v) for k, v in ii["ctx"]["tasks"].get("use", {}).items()})
            ii["ctx"]["tasks"]["global"]["compiler-cpp"] = dict(self.host_cc)
            return {"return": 0}
        raise AssertionError(f"unexpected access: {ii}")


@pytest.fixture(scope = "module")
def host():
    spec = importlib.util.spec_from_file_location("nvcc_host", REPO_ROOT / "tool" / "nvcc" / "host.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def nvcc_api(redist, host):
    """tool/nvcc/api_v1.py with a stand-in for its base class (the real one needs cMeta)."""
    path = REPO_ROOT / "tool" / "nvcc" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "class InitCTool:\n    pass")
    src = src.replace("from . import redist", "").replace("from . import host", "")
    ns = {"__name__": "nvcc_api", "__file__": str(path), "redist": redist, "host": host}
    exec(compile(src, str(path), "exec"), ns)
    return ns["CTool"]


def tool(nvcc_api, cm):
    t = nvcc_api.__new__(nvcc_api)
    t.cm = cm
    return t


def context(uname = "linux", uarch = "amd64", arch = 50, driver = "13.0"):
    return {"control": {"con": False, "quiet": True, "verbose": False},
            "tasks": {"nested_call": 0,
                      "global": {"host": {"os": {"uname": uname, "uarch": uarch}},
                                 "cuda": {"features": {"compute_cap_int_min": arch,
                                                       "versions": {"cuda version": driver}}}}}}


@pytest.fixture
def server(redist, tmp_path, monkeypatch):
    """Fake releases 12.9.2 and 13.0.2 for linux-x86_64 and windows-x86_64."""
    store = tmp_path / "nvidia"
    store.mkdir()
    urls, manifests = {}, {}
    for release, nvcc in (("12.9.2", "12.9.86"), ("13.0.2", "13.0.88")):
        m = {"release_label": release}
        for platform, ext in (("linux-x86_64", "tar.xz"), ("windows-x86_64", "zip")):
            exe = ".exe" if platform.startswith("windows") else ""
            content = {
                "cuda_nvcc": {f"bin/nvcc{exe}": b"nvcc " + nvcc.encode(), "bin/nvcc.profile": b"TOP = $(_HERE_)/..",
                              "nvvm/bin/cicc" + exe: b"cicc"},
                "cuda_cudart": {"include/cuda_runtime.h": b"//", "lib/libcudart.so.12": b"\x7fELF"},
                "cuda_cccl": {"include/thrust/version.h": b"//"},
                "cuda_profiler_api": {"include/cuda_profiler_api.h": b"//"},
                "libcublas": {"lib/libcublas.so.12": b"\x7fELF", "include/cublas_v2.h": b"//"},
            }
            for name, files in content.items():
                version = nvcc if name == "cuda_nvcc" else "1.0"
                top = f"{name}-{platform}-{version}-archive"
                relative_path = f"{name}/{platform}/{top}.{ext}"
                archive = store / f"{top}.{ext}"
                make_archive(archive, top, files)
                data = archive.read_bytes()
                m.setdefault(name, {"name": name, "version": version})[platform] = {
                    "relative_path": relative_path, "sha256": hashlib.sha256(data).hexdigest(), "size": str(len(data))}
                urls[f"{redist.BASE}/{relative_path}"] = str(archive)
        manifests[release] = m
    monkeypatch.setattr(redist, "releases", lambda index_html = None: ["12.9.2", "13.0.2"])
    monkeypatch.setattr(redist, "manifest", lambda release: json.loads(json.dumps(manifests[release])))
    return urls


@pytest.mark.parametrize("uname", ["windows", "linux"])
def test_install_the_newest_toolkit_for_the_gpu(nvcc_api, server, tmp_path, monkeypatch, uname):
    if uname == "linux" and not can_symlink(tmp_path):
        pytest.skip("the Linux layout links targets/x86_64-linux, which needs privileges here")
    entry = tmp_path / "cache-entry"
    entry.mkdir()
    monkeypatch.chdir(entry)
    cm = FakeCM(server)
    t = tool(nvcc_api, cm)

    # sm_50 with a driver for CUDA 13.0: 13.0 cannot build for it -> 12.9.2
    r = t.install(context(uname, arch = 50, driver = "13.0"), {"with": {}})
    assert r["return"] == 0, r
    root = entry / "content" / "12.9.2"
    exe = ".exe" if uname == "windows" else ""
    assert r["found_path"] == str(root / "bin" / f"nvcc{exe}")
    assert (root / "bin" / f"nvcc{exe}").read_bytes() == b"nvcc 12.9.86"
    assert (root / "include" / "thrust" / "version.h").is_file()
    assert not (entry / "downloads").exists()
    assert sorted(cm.downloads) == sorted(f"{n}-{'windows' if exe else 'linux'}-x86_64-{v}-archive.{'zip' if exe else 'tar.xz'}"
                                          for n, v in (("cuda_nvcc", "12.9.86"), ("cuda_cudart", "1.0"),
                                                       ("cuda_cccl", "1.0"), ("cuda_profiler_api", "1.0")))
    version = json.loads((root / "version.json").read_text())
    assert version["cuda"]["version"] == "12.9.2" and version["cuda_nvcc"]["version"] == "12.9.86"
    marker = json.loads((root / "cmeta-cuda-redist.json").read_text())
    assert marker["release"] == "12.9.2" and marker["nvcc"] == "12.9.86" and "libcublas" not in marker["components"]
    if uname == "linux":
        assert (root / "targets" / "x86_64-linux" / "include" / "cuda_runtime.h").is_file()

    # a library asked for later (lib-cuda's lib_names) is added once
    ctx = context(uname, arch = 50, driver = "13.0")
    assert t._add_libraries(ctx, str(root), ["$cublas", "$cudart", "cufile"], {})["return"] == 0
    assert (root / "lib" / "libcublas.so.12").is_file()
    marker = json.loads((root / "cmeta-cuda-redist.json").read_text())
    assert "libcublas" in marker["components"] and marker["components"]["libcufile"] is None
    assert "libcublas" in json.loads((root / "version.json").read_text())
    n = len(cm.downloads)
    assert t._add_libraries(ctx, str(root), ["cublas", "cufile"], {})["return"] == 0
    assert len(cm.downloads) == n


def test_install_follows_the_request(nvcc_api, server, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = tool(nvcc_api, FakeCM(server))

    r = t.install(context("windows", arch = 50, driver = "13.0"), {"version": "13.0", "with": {}})
    assert r["return"] == 1 and "sm_75" in r["error"]

    # --with.any_arch: to build for other GPUs
    r = t.install(context("windows", arch = 50, driver = "13.0"), {"version": "13.0", "with": {"any_arch": True}})
    assert r["return"] == 0 and r["found_path"].endswith(os.path.join("13.0.2", "bin", "nvcc.exe"))

    r = t.install(context("windows", arch = 120, driver = "12.9"), {"version": "13", "with": {}})
    assert r["return"] == 1 and "update the NVIDIA driver" in r["error"]

    r = t.install(context("windows", arch = 120, driver = "13.0"), {"version": "12.9.86", "with": {"cuda_libs": "cublas"}})
    assert r["return"] == 0
    assert (tmp_path / "content" / "12.9.2" / "lib" / "libcublas.so.12").is_file()

    r = t.install(context("darwin", "arm64"), {"with": {}})
    assert r["return"] == 1 and "darwin/arm64" in r["error"]


def test_a_toolkit_from_the_installer_is_left_alone(nvcc_api, server, tmp_path):
    cm = FakeCM(server)
    t = tool(nvcc_api, cm)
    (tmp_path / "lib").mkdir()
    assert t._add_libraries(context(), str(tmp_path), ["cublas"], {})["return"] == 0
    assert t._add_libraries(context(), None, ["cublas"], {})["return"] == 0
    assert cm.downloads == []


LIST_GPU_ARCH_13 = "\n".join(f"arch=compute_{a},code=sm_{a}" for a in (75, 80, 86, 89, 90, 100, 120)) + "\n"
LIST_GPU_ARCH_12 = "\n".join(f"arch=compute_{a},code=sm_{a}" for a in (50, 52, 60, 70, 75, 80, 86, 90, 120)) + "\n"


def test_detection_skips_toolkits_that_cannot_build_for_the_gpu(nvcc_api, tmp_path):
    def found(version):
        bin_dir = tmp_path / version / "bin"
        bin_dir.mkdir(parents = True)
        (bin_dir / "nvcc").write_text("")
        return {"path": str(bin_dir / "nvcc"), "detected_version": version}

    t = tool(nvcc_api, FakeCM({}, LIST_GPU_ARCH_13))
    r = t.check_features(context(arch = 50, driver = "13.0"), [found("13.0.88")], {"with": {}})
    assert r == {"return": 0, "paths": []}

    r = t.check_features(context(arch = 50, driver = "13.0"), [found("13.3.73")], {"with": {"any_arch": True}})
    assert [p["features"]["supported_arch_min"] for p in r["paths"]] == [75]

    # a toolkit for CUDA 13 with a driver for CUDA 12
    r = t.check_features(context(arch = 86, driver = "12.9"), [found("13.4.92")], {"with": {}})
    assert r["paths"] == []

    t = tool(nvcc_api, FakeCM({}, LIST_GPU_ARCH_12))
    r = t.check_features(context(arch = 50, driver = "13.0"), [found("12.9.86")], {"with": {}})
    assert [p["features"]["supported_arch_min"] for p in r["paths"]] == [50]


def test_one_cache_entry_per_gpu_architecture(nvcc_api):
    t = tool(nvcc_api, FakeCM({}))
    cache_params = {"name": "nvcc"}
    assert t.customize_tool_cache_artifact(context(arch = 61), {}, {"with": {}}, [], cache_params, {}, {})["return"] == 0
    assert cache_params == {"name": "nvcc", "gpu_arch_min": 61}

    cache_params = {"name": "nvcc"}
    t.customize_tool_cache_artifact(context(arch = 61), {}, {"with": {"any_arch": True}}, [], cache_params, {}, {})
    assert cache_params == {"name": "nvcc"}


def test_arch_flags_fail_for_an_older_gpu(nvcc_api):
    t = tool(nvcc_api, FakeCM({}))

    def result(arch_min, arch_max):
        return {"version": "13.0.88", "features": {"supported_arch_min": arch_min, "supported_arch_max": arch_max,
                                                    "version_major": 13, "paths": {"home": None},
                                                    "flags": {"dynamic_build": "-cudart={cudart_shared}"}}}

    r = t.finish_dynamic_result(context(arch = 50), result(75, 120), {"with": {"arch_flags": True}})
    assert r["return"] == 1 and "sm_50" in r["error"] and "older CUDA toolkit" in r["error"]

    r = t.finish_dynamic_result(context(arch = 86), result(75, 120), {"with": {"arch_flags": True}})
    assert r["return"] == 0
    assert r["result"]["features"]["target_arch"]["flags"] == "-gencode arch=compute_86,code=sm_86"

    # reused in the same run: the flag is not added twice
    again = t.finish_dynamic_result(context(arch = 86), r["result"], {"with": {"arch_flags": True}})
    assert again["result"]["features"]["target_arch"]["flags"] == "-gencode arch=compute_86,code=sm_86"


def test_arch_flags_for_a_gpu_newer_than_the_toolkit(nvcc_api):
    t = tool(nvcc_api, FakeCM({}))
    # CUDA 11.8 knows up to sm_90; on a Blackwell GPU (sm_120) the driver compiles compute_90 PTX
    features = {"supported_arch": [35, 50, 60, 70, 75, 80, 86, 87, 89, 90], "supported_arch_min": 35,
                "supported_arch_max": 90, "version_major": 11, "paths": {"home": None},
                "flags": {"dynamic_build": "-cudart={cudart_shared}"}}
    r = t.finish_dynamic_result(context(arch = 120), {"version": "11.8.89", "features": features},
                                {"with": {"arch_flags": True}})
    assert r["result"]["features"]["target_arch"] == {"compute_cap": 90, "flags": "-gencode arch=compute_90,code=compute_90"}

    # a GPU between two architectures the toolkit lists (sm_88): the PTX of the one before
    features = dict(features, target_arch = {})
    r = t.finish_dynamic_result(context(arch = 88), {"version": "11.8.89", "features": features},
                                {"with": {"arch_flags": True}})
    assert r["result"]["features"]["target_arch"]["flags"] == "-gencode arch=compute_87,code=compute_87"


###############################################################################################
# The host compilers a toolkit supports (tool/nvcc/host.py)

# The checks of include/crt/host_config.h, as CUDA 11.8, 12.8 and 13.3 have them
HOST_CONFIG = {
    "11.8": """
#if __GNUC__ > 11
#error -- unsupported GNU version! gcc versions later than 11 are not supported!
#if (__clang_major__ >= 15) || (__clang_major__ < 3) || ((__clang_major__ == 3) &&  (__clang_minor__ < 3))
#error -- unsupported clang version! clang version must be less than 15 and greater than 3.2 .
#if _MSC_VER < 1910 || _MSC_VER >= 1940
#error -- unsupported Microsoft Visual Studio version! Only the versions between 2017 and 2022 (inclusive) are supported!
""",
    "12.8": """
#if (__GRCO_CLANG_COMPILER__ == 1) && ((__clang_major__ < 16) || (__clang_major__ > 19))
#if __GNUC__ > 14
#if (__clang_major__ >= 20) || (__clang_major__ < 3) || ((__clang_major__ == 3) &&  (__clang_minor__ < 3))
#error -- unsupported HOS clang version! The version must be must be less than 20 and greater than 3.2 .
#if _MSC_VER < 1910 || _MSC_VER >= 1950
""",
    "13.3": """
#if __GNUC__ > 15
#if (__clang_major__ >= 22) || (__clang_major__ < 3) || ((__clang_major__ == 3) &&  (__clang_minor__ < 3))
#if _MSC_VER < 1920 || _MSC_VER >= 1960
""",
}


def test_host_compiler_limits_of_a_toolkit(host, tmp_path):
    assert host.limits(HOST_CONFIG["11.8"]) == {"msvc": (1910, 1940), "gcc": 11, "clang": 15}
    assert host.limits(HOST_CONFIG["12.8"]) == {"msvc": (1910, 1950), "gcc": 14, "clang": 20}
    assert host.limits(HOST_CONFIG["13.3"]) == {"msvc": (1920, 1960), "gcc": 15, "clang": 22}
    assert host.limits("") == {}

    crt = tmp_path / "include" / "crt"
    crt.mkdir(parents = True)
    (crt / "host_config.h").write_text(HOST_CONFIG["12.8"])
    assert host.read_limits(str(tmp_path))["gcc"] == 14
    assert host.read_limits(str(tmp_path / "none")) == {} and host.read_limits(None) == {}


def test_host_compiler_version_ranges(host):
    ranges = host.version_ranges(host.limits(HOST_CONFIG["12.8"]))
    assert ranges == {"microsoft-visual-studio": ">=19.10,<19.50", "msvc": ">=19.10,<19.50",
                      "gcc-cpp": "<15", "clang-cpp": "<20"}
    assert host.version_ranges({}) == {}
    # the ranges select what they should
    assert matches(ranges["msvc"], "19.44.35217") and not matches(ranges["msvc"], "19.50.35717")
    assert matches(ranges["gcc-cpp"], "14.2.0") and not matches(ranges["gcc-cpp"], "15.2.0")


def test_unsupported_host_compilers(host):
    lim = host.limits(HOST_CONFIG["12.8"])
    assert "19.50" in host.unsupported("msvc", "19.50.35717", lim)
    assert host.unsupported("msvc", "19.44.35217", lim) is None
    assert "GCC 14" in host.unsupported("gcc-cpp", "15.2.0", lim)
    assert host.unsupported("gcc-cpp", "13.3.0", lim) is None
    assert "clang 19" in host.unsupported("clang-cpp", "20.1.0", lim)
    assert host.unsupported("clang-cpp", "18.1.3", lim) is None
    assert host.unsupported("msvc", "19.50.35717", host.limits(HOST_CONFIG["13.3"])) is None
    assert host.unsupported("icx", "2025.1", lim) is None and host.unsupported("msvc", None, lim) is None


def toolkit_home(tmp_path, cuda):
    crt = tmp_path / f"cuda-{cuda}" / "include" / "crt"
    crt.mkdir(parents = True, exist_ok = True)
    (crt / "host_config.h").write_text(HOST_CONFIG[cuda])
    return str(tmp_path / f"cuda-{cuda}")


def nvcc_result(home, version = "12.8.93"):
    return {"version": version, "features": {"paths": {"home": home}, "version_major": int(version.split(".")[0]),
                                             "flags": {"dynamic_build": "-cudart={cudart_shared}"}}}


def test_the_host_compiler_follows_the_toolkit(nvcc_api, tmp_path):
    # Windows, CUDA 12.8: the Visual Studio and MSVC with cl.exe below 19.50 (not VS 2026)
    cl = r'"C:\VS\2022\cl.exe"'
    cm = FakeCM({}, host_cc = {"tool": {"name": "msvc"}, "version": "19.44.35217", "qpath": cl})
    t = tool(nvcc_api, cm)
    ctx = context("windows", arch = 120, driver = "13.3")
    r = t.finish_dynamic_result(ctx, nvcc_result(toolkit_home(tmp_path, "12.8")), {"with": {}})
    assert r["return"] == 0, r
    assert cm.compiler_calls[0]["msvc"] == {"version": ">=19.10,<19.50"}
    # the Visual Studio installation follows the version of msvc (tool/msvc passes it on): no range of its own
    assert "microsoft-visual-studio" not in cm.compiler_calls[0]
    assert r["result"]["features"]["flags"]["host_compiler"] == "-ccbin " + cl

    # reused in the same run: the compiler is not set up again
    r = t.finish_dynamic_result(ctx, r["result"], {"with": {}})
    assert r["return"] == 0 and len(cm.compiler_calls) == 1


def test_a_version_given_with_use_stays(nvcc_api, tmp_path):
    cm = FakeCM({})
    t = tool(nvcc_api, cm)
    ctx = context("linux", arch = 86, driver = "13.0")
    ctx["tasks"]["use"] = {"gcc-cpp": {"version": "13"}}
    assert t.finish_dynamic_result(ctx, nvcc_result(toolkit_home(tmp_path, "12.8")), {"with": {}})["return"] == 0
    assert cm.compiler_calls[0]["gcc-cpp"] == {"version": "13"}
    assert cm.compiler_calls[0]["clang-cpp"] == {"version": "<20"}


def test_a_compiler_version_asked_for_is_not_steered_into_the_limits(nvcc_api, tmp_path):
    """--use.compiler-cpp.version=19.50 with CUDA 12.8: no limits are set for the compiler tools, the toolkit's check stops the run."""
    cm = FakeCM({}, host_cc = {"tool": {"name": "msvc"}, "version": "19.50.35717", "qpath": '"cl.exe"'})
    t = tool(nvcc_api, cm)
    ctx = context("windows", arch = 120, driver = "13.3")
    ctx["tasks"]["use"] = {"compiler-cpp": {"version": "19.50"}}
    r = t.finish_dynamic_result(ctx, nvcc_result(toolkit_home(tmp_path, "12.8")), {"with": {}})
    assert "msvc" not in cm.compiler_calls[0] and "microsoft-visual-studio" not in cm.compiler_calls[0]
    assert r["return"] == 1 and "19.50" in r["error"] and "any_host_compiler" in r["error"]

    # a version the toolkit accepts goes through as it is
    cm = FakeCM({}, host_cc = {"tool": {"name": "msvc"}, "version": "19.44.35217", "qpath": '"cl.exe"'})
    t = tool(nvcc_api, cm)
    ctx = context("windows", arch = 120, driver = "13.3")
    ctx["tasks"]["use"] = {"compiler-cpp": {"version": "19.44"}}
    r = t.finish_dynamic_result(ctx, nvcc_result(toolkit_home(tmp_path, "12.8")), {"with": {}})
    assert r["return"] == 0 and "msvc" not in cm.compiler_calls[0]


def test_an_unsupported_compiler_set_up_earlier_stops_the_run(nvcc_api, tmp_path):
    t = tool(nvcc_api, FakeCM({}))
    ctx = context("windows", arch = 120, driver = "13.3")
    ctx["tasks"]["global"]["compiler-cpp"] = {"tool": {"name": "msvc"}, "version": "19.50.35717", "qpath": '"cl.exe"'}
    r = t.finish_dynamic_result(ctx, nvcc_result(toolkit_home(tmp_path, "12.8")), {"with": {}})
    assert r["return"] == 1
    assert "--use.msvc.version='>=19.10,<19.50'" in r["error"] and "any_host_compiler" in r["error"]

    # --with.any_host_compiler: nvcc is told to try anyway
    r = t.finish_dynamic_result(ctx, nvcc_result(toolkit_home(tmp_path, "12.8")), {"with": {"any_host_compiler": True}})
    assert r["return"] == 0
    assert r["result"]["features"]["flags"]["host_compiler"] == '-ccbin "cl.exe" -allow-unsupported-compiler'

    # CUDA 13.3 supports this MSVC
    r = t.finish_dynamic_result(ctx, nvcc_result(toolkit_home(tmp_path, "13.3"), "13.3.73"), {"with": {}})
    assert r["return"] == 0


def test_adding_a_library_asks_first_without_q(nvcc_api, server, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cm = FakeCM(server)
    t = tool(nvcc_api, cm)
    r = t.install(context("windows", arch = 120, driver = "13.0"), {"with": {}})
    root = os.path.dirname(os.path.dirname(r["found_path"]))
    n = len(cm.downloads)

    ctx = context("windows", arch = 120, driver = "13.0")
    ctx["control"].update({"con": True, "quiet": False})
    answers = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt = "": next(answers))
    r = t._add_libraries(ctx, root, ["cublas"], {})
    assert r["return"] == 1 and "libcublas not added" in r["error"] and len(cm.downloads) == n
    assert t._add_libraries(ctx, root, ["cublas"], {})["return"] == 0 and len(cm.downloads) == n + 1


###############################################################################################
# tool/microsoft.visual-studio: the Build Tools release for a version

@pytest.fixture(scope = "module")
def vs():
    path = REPO_ROOT / "tool" / "microsoft.visual-studio" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    head = src[:src.index("\nclass CTool")].replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "")
    ns = {"__name__": "vs_helpers", "__file__": str(path)}
    exec(compile(head, str(path), "exec"), ns)
    return ns


def test_the_build_tools_release_for_a_version(vs):
    year_for = vs["year_for"]
    assert year_for(">=19.10,<19.50", matches) == "2022"      # what nvcc 12.x asks for
    assert year_for(">=19.20,<19.60", matches) == "2026"
    assert year_for("19.44.35217", matches) == "2022"
    assert year_for("19.50", matches) == "2026"
    assert year_for("19.29", matches) == "2019"
    assert year_for("17", matches) is None                    # not a cl.exe version
    assert year_for("<19.10", matches) is None
