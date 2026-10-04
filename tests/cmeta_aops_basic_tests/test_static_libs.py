"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the static C libraries built from pinned source releases (common_static_lib.py with
tool/lib-zlib, tool/lib-zstd, tool/lib-jitterentropy) and of tool/lib-openssl's static links on
Linux: which libraries a static libssl.a/libcrypto.a needs (from the symbols nm reports undefined),
their order, a system archive or the tool that builds it, and the programs that pass with.static.
"""

import io
import os
import pathlib
import re
import subprocess
import tarfile

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = {'lib-zlib': 'z', 'lib-zstd': 'zstd', 'lib-jitterentropy': 'jitterentropy'}


def load(rel_path, imports):
    """The module's namespace, with its cMeta imports replaced."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in imports.items():
        assert line in src
        src = src.replace(line, replacement)
    ns = {"__name__": path.stem, "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def common():
    return load("category/tool/api/common_static_lib.py",
                {"from tool_c393ba5c6fa14f66.api.common_release import _sha256": "_sha256 = None"})


@pytest.fixture(scope = "module")
def specs():
    return {name: load(f"tool/{name}/api_v1.py",
                       {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass",
                        "from tool_c393ba5c6fa14f66.api.common_static_lib import install_static_lib, detect_static_lib": ""})["SPEC"]
            for name in TOOLS}


@pytest.fixture(scope = "module")
def openssl():
    return load("tool/lib-openssl/api_v1.py",
                {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass"})


def desc(rel_path):
    return yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding = "utf-8"))


# The tools' specs

def test_specs(specs):
    for name, lib in TOOLS.items():
        spec = specs[name]
        assert spec["lib"] == lib and spec["default_version"] in spec["sha256"]
        for digest in spec["sha256"].values():
            assert re.fullmatch(r"[0-9a-f]{64}", digest)
        urls = spec["url"] if isinstance(spec["url"], list) else [spec["url"]]
        assert all(u.startswith("https://") and "{version}" in u for u in urls)
        assert spec["version"][0] in [os.path.basename(h) for h in spec["headers"]]
        d = desc(f"tool/{name}/_desc.yaml")
        assert d["skip_detect"] is True and d["names"] == [spec["version"][0]]
    # jitterentropy must not be optimized (jitterentropy-base.c fails on __OPTIMIZE__)
    assert "-O0" in specs["lib-jitterentropy"]["cflags"]


def test_release(common, specs):
    urls, name = common["release"](specs["lib-zlib"], "1.3.2")
    assert urls == ["https://github.com/madler/zlib/releases/download/v1.3.2/zlib-1.3.2.tar.gz",
                    "https://zlib.net/fossils/zlib-1.3.2.tar.gz"] and name == "zlib-1.3.2.tar.gz"
    urls, name = common["release"](specs["lib-jitterentropy"], "3.7.0")
    assert urls == ["https://github.com/smuellerDD/jitterentropy-library/archive/refs/tags/v3.7.0.tar.gz"]
    assert name == "jitterentropy-library-3.7.0.tar.gz"


def test_header_version(common):
    v = common["header_version"]
    assert v('#define ZLIB_VERSION "1.3.2"\n#define ZLIB_VERNUM 0x1320\n', ["ZLIB_VERSION"]) == "1.3.2"
    zstd = "#define ZSTD_VERSION_MAJOR    1\n#define ZSTD_VERSION_MINOR    5\n#define ZSTD_VERSION_RELEASE  7\n"
    assert v(zstd, ["ZSTD_VERSION_MAJOR", "ZSTD_VERSION_MINOR", "ZSTD_VERSION_RELEASE"]) == "1.5.7"
    assert v("  # define JENT_MAJVERSION 3\n#define JENT_MINVERSION 7\n#define JENT_PATCHLEVEL 0\n",
             ["JENT_MAJVERSION", "JENT_MINVERSION", "JENT_PATCHLEVEL"]) == "3.7.0"
    assert v(zstd, ["ZSTD_VERSION_MAJOR", "ZSTD_VERSION_PATCH"]) is None


def test_sources_and_objects(common, tmp_path):
    for f in ["common/debug.c", "common/xxhash.c", "compress/zstd_fast.c", "zstd.h"]:
        (tmp_path / f).parent.mkdir(parents = True, exist_ok = True)
        (tmp_path / f).write_text("")
    files, error = common["source_files"](str(tmp_path), ["common/*.c", "compress/*.c"])
    assert error is None and [os.path.relpath(f, tmp_path).replace(os.sep, "/") for f in files] == \
        ["common/debug.c", "common/xxhash.c", "compress/zstd_fast.c"]
    files, error = common["source_files"](str(tmp_path), ["legacy/*.c"])
    assert files is None and "legacy/*.c" in error
    assert common["object_name"](str(tmp_path), str(tmp_path / "compress" / "zstd_fast.c"), ".o") == "compress_zstd_fast.o"


def test_compile_and_archive_args(common):
    gcc = {"compile_to_obj": "-c", "obj_file": "-o ", "include_path": "-I", "d": "-D", "static_lib1": "rcs", "static_lib2": ""}
    args = common["compile_args"]("/usr/bin/gcc", gcc, "/s/a.c", "/o/a.o", ["/s", "/s/common"], ["X=1", "Y"], ["-O2", "-fPIC"])
    assert args == ["/usr/bin/gcc", "-c", "-O2", "-fPIC", "-DX=1", "-DY", "-I/s", "-I/s/common", "/s/a.c", "-o", "/o/a.o"]
    assert common["archive_args"]("/usr/bin/ar", gcc, "/l/libz.a", ["a.o", "b.o"]) == ["/usr/bin/ar", "rcs", "/l/libz.a", "a.o", "b.o"]
    msvc = {"compile_to_obj": "/c", "obj_file": "/Fo:", "include_path": "/I ", "d": "/D", "static_lib1": "", "static_lib2": "/OUT:"}
    args = common["compile_args"]("cl.exe", msvc, "a.c", "a.obj", ["inc"], ["X"], ["/O2"])
    assert args == ["cl.exe", "/c", "/O2", "/DX", "/I", "inc", "a.c", "/Fo:a.obj"]
    assert common["archive_args"]("lib.exe", msvc, "z.lib", ["a.obj"]) == ["lib.exe", "/OUT:z.lib", "a.obj"]


def test_safe_members(common, tmp_path):
    archive = tmp_path / "src.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        for name in ["zlib-1.3.2/zlib.h", "../outside.c", "/abs.c"]:
            info = tarfile.TarInfo(name)
            info.size = 1
            t.addfile(info, io.BytesIO(b"x"))
        link = tarfile.TarInfo("zlib-1.3.2/tests/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../"
        t.addfile(link)
    with tarfile.open(archive) as t:
        assert [m.name for m in common["safe_members"](t)] == ["zlib-1.3.2/zlib.h"]


def test_detect(common, specs, tmp_path):
    include = tmp_path / "install" / "include"
    lib = tmp_path / "install" / "lib"
    include.mkdir(parents = True)
    lib.mkdir()
    (include / "zlib.h").write_text('#define ZLIB_VERSION "1.3.2"\n')

    class CM:
        @staticmethod
        def q(p):
            return f'"{p}"'

    tool = type("Tool", (), {"cm": CM})()
    r = common["detect_static_lib"](tool, {}, [str(include / "zlib.h")], {}, specs["lib-zlib"])
    assert r["found_paths_with_versions"] == {}                    # no libz.a yet
    (lib / "libz.a").write_bytes(b"!<arch>\n")
    r = common["detect_static_lib"](tool, {}, [str(include / "zlib.h")], {}, specs["lib-zlib"])
    found = r["found_paths_with_versions"][str(include / "zlib.h")]
    assert found["output"] == "1.3.2"
    f = found["features"]
    assert f["lib_names"] == ["z"]
    assert f["lib_names_static"] == [str(lib / "libz.a")] == [f["static_lib"]]        # a static build gets the archive by its path
    assert f["paths"]["includes"] == [str(include)] and f["paths"]["libs_static"] == [str(lib)]


# tool/lib-openssl: static links on Linux

UBUNTU_26_04 = {"deflate", "inflateInit_", "ZSTD_compress", "ZSTD_freeCCtx", "jent_version", "jent_read_entropy",
                "OPENSSL_cleanse", "memcpy"}


ARCHIVES = ["/usr/lib/x86_64-linux-gnu/libssl.a", "/usr/lib/x86_64-linux-gnu/libcrypto.a"]


def test_static_deps_and_names(openssl):
    """The archives by their paths, each needed library by the path of its archive with what it
    needs, then the system libraries."""
    deps = openssl["static_deps"](UBUNTU_26_04)
    assert [d["lib"] for d in deps] == ["jitterentropy", "z", "zstd"]
    with_paths = [dict(d, path = f"/a/lib{d['lib']}.a") for d in deps]
    assert openssl["static_lib_names"](ARCHIVES, with_paths) == \
        ARCHIVES + ["/a/libjitterentropy.a", "pthread", "/a/libz.a", "/a/libzstd.a", "dl", "m"]
    # Ubuntu 24.04, Debian: libcrypto.a needs none of them
    assert openssl["static_deps"]({"OPENSSL_cleanse", "memcpy", "pthread_once"}) == []
    assert openssl["static_lib_names"](ARCHIVES, []) == ARCHIVES + ["pthread", "dl", "m"]
    assert openssl["static_lib_names"](ARCHIVES, [], "darwin") == ARCHIVES + ["m"]           # libSystem has the rest
    assert [d["lib"] for d in openssl["static_deps"]({"compress2"})] == ["z"]
    for value, expected in [(None, False), ("", False), (False, False), ("False", False), ("no", False),
                            (True, True), ("True", True), ("yes", True), (1, True)]:
        assert openssl["is_true"](value) is expected


def test_no_static_archives_messages(openssl):
    message = openssl["no_static_archives"]
    linux = message("linux", "fedora", "", "/usr/lib64")
    assert linux.startswith("a static build needs OpenSSL's static archives libssl.a and libcrypto.a, and the OpenSSL found (/usr/lib64) has none:")
    assert "this system (fedora): Fedora packages no static OpenSSL" in linux and "cx tool setup lib-openssl --tool_path=" in linux
    assert "this system (rocky): RHEL-like systems package no static OpenSSL" in message("linux", "rocky", "rhel centos fedora")   # by ID_LIKE
    assert "this system (ubuntu): sudo apt-get install libssl-dev" in message("linux", "ubuntu", "debian")
    assert "this system" not in message("linux", "void", "")                                                      # unknown: the general lines
    assert "brew install openssl@3" in message("darwin") and "libssl.a" in message("darwin")
    windows = message("windows", where = "C:\\OpenSSL\\lib\\VC\\x64")
    assert "libssl_static.lib and libcrypto_static.lib" in windows and "ShiningLight.OpenSSL.Dev" in windows and "(C:\\OpenSSL\\lib\\VC\\x64)" in windows


def test_static_dep_tools(openssl):
    for d in openssl["STATIC_DEPS"]:
        name, uid = d["tool"].split(",")
        assert desc(f"tool/{name}/_cmeta.yaml")["artifact"] == uid and TOOLS[name] == d["lib"]


def test_undefined_symbols(openssl, monkeypatch):
    out = "\nlibcrypto-lib-c_zlib.o:\n                 U deflate\n                 U inflate\n0000 T BIO_f_zlib\n" \
          "libcrypto-lib-seed_src_jitter.o:\n                 U jent_version\n"
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout = out, stderr = "")

    monkeypatch.setattr(openssl["subprocess"], "run", run)
    assert openssl["undefined_symbols"]("nm", ["/l/libcrypto.a"]) == {"deflate", "inflate", "jent_version"}
    assert calls == [["nm", "-u", "/l/libcrypto.a"]]


def test_find_static_lib(openssl, tmp_path, monkeypatch):
    (tmp_path / "libz.a").write_bytes(b"!<arch>\n")
    assert openssl["find_static_lib"]("z", [str(tmp_path)]) == str(tmp_path / "libz.a")
    other = tmp_path / "gcc"
    other.mkdir()
    (other / "libzstd.a").write_bytes(b"!<arch>\n")

    def run(args, **kwargs):                                   # gcc -print-file-name=<name>
        name = args[1].split("=", 1)[1]
        found = other / name
        return subprocess.CompletedProcess(args, 0, stdout = (str(found) if found.exists() else name) + "\n")

    monkeypatch.setattr(openssl["subprocess"], "run", run)
    assert openssl["find_static_lib"]("zstd", [], compiler = "gcc") == str(other / "libzstd.a")
    assert openssl["find_static_lib"]("jitterentropy", [], compiler = "gcc") is None


class FakeCM:
    def __init__(self):
        self.setups = []

    def access(self, p):
        name = p["name"].split(",")[0]
        self.setups.append(name)
        return {"return": 0, "features": {"static_lib": f"/cache/{name}/install/lib/lib{TOOLS[name]}.a"}}

    @staticmethod
    def catch_error(r, fail16 = False):
        return r["return"] > 0

    @staticmethod
    def error(text):
        return {"return": 1, "error": text}


def archives_in(folder):
    paths = [str(folder / a) for a in ["libssl.a", "libcrypto.a"]]
    for p in paths:
        pathlib.Path(p).write_bytes(b"!<arch>\n")
    return paths


@pytest.mark.parametrize("mode, built", [(None, ["lib-jitterentropy"]),
                                         ("cmeta", ["lib-jitterentropy", "lib-zlib", "lib-zstd"])])
def test_static_link_deps(openssl, tmp_path, monkeypatch, mode, built):
    """The system has libz.a and libzstd.a, not libjitterentropy.a (Ubuntu 26.04 with zlib1g-dev and
    libzstd-dev): each needed library by the path of its archive, the system's or the tool's."""
    archives = archives_in(tmp_path)
    monkeypatch.setitem(openssl, "undefined_symbols", lambda nm, archives, darwin = False: UBUNTU_26_04)
    monkeypatch.setitem(openssl, "find_static_lib",
                        lambda lib, dirs, compiler = None: f"/usr/lib/lib{lib}.a" if lib in ("z", "zstd") else None)
    monkeypatch.setattr(openssl["shutil"], "which", lambda name: "/usr/bin/nm" if name == "nm" else None)
    tool = object.__new__(openssl["CTool"])
    tool.cm = FakeCM()
    features = {"paths": {"libs": [str(tmp_path)]}}
    ctx = {"control": {}, "tasks": {"global": {"compiler-c": {"path": "gcc"}}}}
    r = tool.static_link_deps(ctx, features, {"with": {"static": True, "static_deps": mode}}, archives, "linux")
    assert r["return"] == 0 and tool.cm.setups == built
    jitter = "/cache/lib-jitterentropy/install/lib/libjitterentropy.a"
    z, zstd = ("/cache/lib-zlib/install/lib/libz.a", "/cache/lib-zstd/install/lib/libzstd.a") if mode == "cmeta" else ("/usr/lib/libz.a", "/usr/lib/libzstd.a")
    assert features["lib_names_static"] == archives + [jitter, "pthread", z, zstd, "dl", "m"]


def test_static_libraries_without_archives_or_nm(openssl, tmp_path, monkeypatch):
    """Without the archives a request with with.static fails with what gives them on this system
    and a request without it records the reason; without nm the archives are linked with the
    system's static archives of what they may need."""
    tool = object.__new__(openssl["CTool"])
    tool.cm = FakeCM()
    ctx = {"control": {}, "tasks": {"global": {"host": {"os": {"uname": "linux"}, "os_extra": {"id": "fedora", "id_like": ""}}}}}
    features = {"paths": {"libs": [str(tmp_path)]}, "lib_names_static": ["ssl", "crypto"]}
    r = tool.static_libraries(ctx, features, {"with": {"static": True}}, True)
    assert r["return"] == 1 and r["error"].startswith("lib-openssl: a static build needs")
    assert "this system (fedora): Fedora packages no static OpenSSL" in r["error"] and f"({tmp_path})" in r["error"]
    assert tool.static_libraries(ctx, features, {}, False)["return"] == 0
    assert "libssl.a" in features["static_unavailable"] and "lib_names_static" not in features
    archives = archives_in(tmp_path)
    monkeypatch.setattr(openssl["shutil"], "which", lambda name: None)
    monkeypatch.setitem(openssl, "find_static_lib", lambda lib, dirs, compiler = None: "/usr/lib/libz.a" if lib == "z" else None)
    assert tool.static_libraries(ctx, features, {"with": {"static": True}}, True)["return"] == 0
    assert features["lib_names_static"] == archives + ["/usr/lib/libz.a", "pthread", "dl", "m"] and "static_unavailable" not in features
    assert tool.static_libraries(ctx, features, {}, False)["return"] == 0                 # a dynamic request: the same, no tool
    assert features["lib_names_static"] == archives + ["/usr/lib/libz.a", "pthread", "dl", "m"]
    assert tool.cm.setups == []
    # a tool that reports no archive
    tool.cm.access = lambda p: {"return": 0, "features": {}}
    monkeypatch.setattr(openssl["shutil"], "which", lambda name: "/usr/bin/nm" if name == "nm" else None)
    monkeypatch.setitem(openssl, "undefined_symbols", lambda nm, archives, darwin = False: {"jent_version"})
    monkeypatch.setitem(openssl, "find_static_lib", lambda lib, dirs, compiler = None: None)
    r = tool.static_libraries(ctx, features, {"with": {"static": True}}, True)
    assert r["return"] == 1 and "lib-jitterentropy reported no static archive" in r["error"]


def test_programs_pass_static_on_linux():
    for prog in ["test-nmm-c-cpu", "test-nmm-cpp-cpu"]:
        uses = [u for x in desc(f"program/{prog}/_desc.yaml")["updates"]["compile"]["uses"] for u in x.get("append", [])]
        entries = [u for u in uses if u.get("name") == "lib-openssl,903191f1fab74064"]
        assert len(entries) == 2
        plain, static = entries
        assert "with" not in plain and 'not ("{{global.host.os.uname}}" in ("linux", "darwin")' in plain["if"]
        assert static["with"] == {"static": True} and '"{{global.host.os.uname}}" in ("linux", "darwin")' in static["if"]
