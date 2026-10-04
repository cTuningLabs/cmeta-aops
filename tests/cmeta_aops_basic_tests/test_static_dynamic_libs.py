"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The static and dynamic variants of the built libraries (tool/lib-xopenme, lib-polybench, lib-milepost)
keep separate cache entries: their identity (cache_meta_const) records with.static and with.debug_info
as False when a request does not give them, so a request must carry explicit values too. A program
passes '{{params.compile.static|$None}}' for a dynamic build; the None left the key out of the cache
query and matched the static and the dynamic entry alike. The tools now normalize the two keys in
check_params. Offline tests of that normalization and of the programs' lib entries.
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILT_LIBS = ["lib-xopenme", "lib-polybench", "lib-milepost"]


def load(rel_path):
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool: pass")
    ns = {"__name__": path.parent.name, "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def desc(rel_path):
    return yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding = "utf-8"))


def tool_of(name):
    ns = load(f"tool/{name}/api_v1.py")
    tool = object.__new__(ns["CTool"])
    tool.cdesc = {"name": desc(f"tool/{name}/_desc.yaml")["name"]}
    return tool


def ctx_of(uname = "linux"):
    return {"tasks": {"global": {"host": {"os": {"uname": uname}, "vars": {"file_ext_dlib": ".so"}}}, "local": {}}}


@pytest.mark.parametrize("name", BUILT_LIBS)
@pytest.mark.parametrize("given, expected", [
    ({}, False), ({"static": None}, False), ({"static": ""}, False), ({"static": False}, False),
    ({"static": True}, True), ({"static": "True"}, True), ({"static": "false"}, False), ({"static": 1}, True),
])
def test_static_normalized(name, given, expected):
    """with.static always has a value after check_params, so the cache query carries the key."""
    params = {"with": dict(given)}
    assert tool_of(name).check_params(ctx_of(), params)["return"] == 0
    assert params["with"]["static"] is expected
    assert params["with"]["debug_info"] is False


@pytest.mark.parametrize("name", BUILT_LIBS)
def test_debug_info_normalized(name):
    for given, expected in [({"debug_info": None}, False), ({"debug_info": True}, True), ({"debug_info": "yes"}, True)]:
        params = {"with": dict(given)}
        tool_of(name).check_params(ctx_of(), params)
        assert params["with"]["debug_info"] is expected


@pytest.mark.parametrize("name", BUILT_LIBS)
def test_identity_matches_normalized_values(name):
    """cache_meta_const records the same keys with the same defaults, so existing entries keep matching."""
    const = desc(f"tool/{name}/_desc.yaml")["cache_meta_const"]["params"]["with"]
    assert const["static"] == "{{params.with.static|$False}}"
    assert const["debug_info"] == "{{params.with.debug_info|$False}}"
    assert const["compute"] == "{{local.compute}}"


@pytest.mark.parametrize("name", BUILT_LIBS)
def test_compute_and_abi_as_before(name):
    params = {"with": {"compute": "android-cpu", "android_abi": "arm64-v8a"}}
    ctx = ctx_of()
    tool_of(name).check_params(ctx, params)
    assert params["with"]["compute"] == ["android-cpu"]
    assert ctx["tasks"]["local"]["compute"] == ["android-cpu"]
    assert ctx["tasks"]["local"]["target_abi"] == "arm64-v8a"
    assert ctx["tasks"]["local"]["tool_name"].endswith(".so")


def lib_entries(program, lib):
    uses = [u for x in desc(f"program/{program}/_desc.yaml")["updates"]["compile"]["uses"] for u in x.get("append", [])]
    return [u for u in uses if str(u.get("name", "")).startswith(lib + ",")]


def test_programs_pass_static_to_the_built_libs():
    """The matmul programs pass compile.static to lib-xopenme in the templated form (a dynamic build
    passes None, which the tool reads as False); programs that pass nothing get the dynamic entry."""
    for program in ["test-nmm-c-cpu", "test-nmm-cpp-cpu", "test-nmm-nvcc-cuda", "polybench-cpu-gemm", "polybench-gemm-cpu-cuda"]:
        entries = lib_entries(program, "lib-xopenme")
        assert len(entries) == 1
        assert entries[0]["with"]["static"] == "{{params.compile.static|$None}}"
    for program in ["polybench-cpu-gemm", "polybench-gemm-cpu-cuda"]:
        entries = lib_entries(program, "lib-polybench")
        assert len(entries) == 1 and entries[0]["with"]["static"] == "{{params.compile.static|$None}}"


def test_cuda_program_openssl_entries_like_the_c_programs():
    """test-nmm-nvcc-cuda has the two lib-openssl entries of the C programs: a plain one, and one with
    with.static for a static build on Linux (lib-openssl then links what the distribution's static
    OpenSSL needs)."""
    entries = lib_entries("test-nmm-nvcc-cuda", "lib-openssl")
    assert len(entries) == 2
    plain, static = entries
    assert "with" not in plain and 'not ("{{global.host.os.uname}}" in ("linux", "darwin")' in plain["if"]
    assert static["with"] == {"static": True} and '"{{params.compile.static|False}}" == "True"' in static["if"]


# tool/lib-openmp: the static archive of a static build

def openmp_tool():
    path = REPO_ROOT / "tool/lib-openmp/api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool", "class InitCTool: pass")
    src = src.replace("from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256", "_download = _sha256 = None")
    ns = {"__name__": "lib_openmp", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


class FakeCM:
    def error(self, text):
        return {"return": 1, "error": text}


def test_openmp_is_true():
    ns = openmp_tool()
    for value in (None, "", False, "False", "no", "0", 0):
        assert ns["is_true"](value) is False
    for value in (True, "True", "yes", "1", 1):
        assert ns["is_true"](value) is True


def test_openmp_source_pins():
    src = openmp_tool()["OPENMP_SRC"]
    assert src["version"] == "21.1.8"
    for name, digest in src["files"].items():
        assert "{version}" in name and name.endswith(".src.tar.xz")
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert src["url"].format(version = "21.1.8", file = "x") == \
        "https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/x"


def test_openmp_cmake_args():
    args = openmp_tool()["cmake_args"]("cmake", "ninja", "src", "build", "cc", "cxx")
    assert args[:5] == ["cmake", "-S", "src", "-B", "build"]
    assert "-DLIBOMP_ENABLE_SHARED=OFF" in args and "-DOPENMP_ENABLE_LIBOMPTARGET=OFF" in args
    assert "-DCMAKE_C_COMPILER=cc" in args and "-DCMAKE_CXX_COMPILER=cxx" in args and "-DCMAKE_MAKE_PROGRAM=ninja" in args


def test_openmp_static_library_shipped(tmp_path):
    """An archive next to the detected library is copied into the entry's static folder once."""
    ns = openmp_tool()
    tool = object.__new__(ns["CTool"])
    tool.cm = FakeCM()
    lib = tmp_path / "homebrew" / "lib"
    lib.mkdir(parents = True)
    (lib / "libomp.a").write_bytes(b"!<arch>\n")
    entry = tmp_path / "entry"
    entry.mkdir()
    result = {"return": 0, "path_cmeta_cache": str(entry), "features": {"paths": {"dynamic_lib": str(lib)}}}
    ctx = {"control": {}, "tasks": {"nested_call": 0, "global": {}}}
    r = tool.static_library(ctx, result, {})
    assert r == {"return": 0, "path": str(entry / "static")} and (entry / "static" / "libomp.a").is_file()
    (lib / "libomp.a").unlink()
    assert tool.static_library(ctx, result, {})["return"] == 0        # the copy is kept


def test_openmp_static_library_errors(tmp_path):
    ns = openmp_tool()
    tool = object.__new__(ns["CTool"])
    tool.cm = FakeCM()
    ctx = {"control": {}, "tasks": {"nested_call": 0, "global": {}}}
    r = tool.static_library(ctx, {"return": 0, "features": {"paths": {}}}, {})
    assert r["return"] == 1 and "no cache entry" in r["error"]
    entry = tmp_path / "entry"
    entry.mkdir()
    r = tool.static_library(ctx, {"return": 0, "path_cmeta_cache": str(entry), "features": {"paths": {"dynamic_lib": str(tmp_path)}}}, {})
    assert r["return"] == 1 and "libomp.a" in r["error"] and "gcc" in r["error"]       # no compilers set up: a clear message


def test_openmp_finish_static_and_dynamic(tmp_path):
    ns = openmp_tool()
    tool = object.__new__(ns["CTool"])
    tool.cm = FakeCM()
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "libomp.a").write_bytes(b"!<arch>\n")
    entry = tmp_path / "entry"
    entry.mkdir()
    ctx = {"control": {}, "tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "darwin"}}}}}
    result = {"return": 0, "path_cmeta_cache": str(entry), "features": {"paths": {"dynamic_lib": str(lib)}, "lib_names": ["omp"]}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {"static": "True"}})["return"] == 0
    assert result["features"]["paths"]["libs_static"] == [str(entry / "static")]
    assert result["features"]["lib_names_static"] == ["omp"] and "found_dynamic_lib_paths" not in result["features"]["paths"]
    result = {"return": 0, "path_cmeta_cache": str(entry), "features": {"paths": {"dynamic_lib": str(lib)}}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {"static": None}})["return"] == 0
    assert result["features"]["paths"]["found_dynamic_lib_paths"] == [str(lib)] and "libs_static" not in result["features"]["paths"]
    # Windows: a static build keeps the DLL's folder on the run-time path (no static runtime exists)
    ctx["tasks"]["global"]["host"]["os"]["uname"] = "windows"
    result = {"return": 0, "path_cmeta_cache": str(entry), "features": {"paths": {"dynamic_lib": str(lib)}}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {"static": True}})["return"] == 0
    assert result["features"]["paths"]["found_dynamic_lib_paths"] == [str(lib)] and "libs_static" not in result["features"]["paths"]


def test_programs_pass_static_to_openmp():
    for program in ["test-nmm-c-cpu", "test-nmm-cpp-cpu", "polybench-cpu-gemm", "polybench-gemm-cpu-cuda"]:
        entries = lib_entries(program, "lib-openmp")
        assert len(entries) == 1 and entries[0]["with"]["static"] == "{{params.compile.static|$None}}"
        assert "if_os" not in entries[0] and "global.llvm.path" in entries[0]["if"]       # clang on every OS


# program/test-nmm-c-cpu: the C math library on Linux

def test_c_program_links_libm_on_linux():
    path = REPO_ROOT / "program/test-nmm-c-cpu/api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from program_22788f3c30d04e6d.api.cprogram import InitCProgram",
                                                     "class InitCProgram: pass")
    ns = {"__name__": "test_nmm_c_cpu", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    program = object.__new__(ns["CProgram"])

    def ctx(uname, compute):
        return {"tasks": {"global": {"target": {"compute": compute}, "host": {"os": {"uname": uname}}},
                          "local": {"params": {"compile": {}}}}}

    c = ctx("linux", ["cpu"])
    assert program.customize2(c)["return"] == 0 and c["tasks"]["local"]["params"]["compile"]["lib_names"] == ["m"]
    program.customize2(c)
    assert c["tasks"]["local"]["params"]["compile"]["lib_names"] == ["m"]            # once
    for uname, compute in [("windows", ["cpu"]), ("darwin", ["cpu"]), ("linux", ["android-cpu"]), ("linux", ["cuda"])]:
        c = ctx(uname, compute)
        program.customize2(c)
        assert "lib_names" not in c["tasks"]["local"]["params"]["compile"]


# tool/lib-openssl: static links on macOS; task/setup-compile: the OpenMP note on Windows

def openssl_tool():
    path = REPO_ROOT / "tool/lib-openssl/api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool: pass")
    ns = {"__name__": "lib_openssl", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def test_openssl_undefined_symbols_macos_format(monkeypatch):
    """macOS nm prints bare names with the Mach-O underscore; GNU nm a U column. Both are read."""
    import subprocess
    ns = openssl_tool()
    outputs = {"mac": "\n/l/libcrypto.a(c_zlib.o):\n_compress\n_pthread_create\n\n/l/libcrypto.a(bio.o):\n__error\n",
               "gnu": "\nc_zlib.o:\n                 U deflate\n0000 T BIO_f_zlib\n"}
    current = {}

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout = outputs[current["k"]], stderr = "")

    monkeypatch.setattr(ns["subprocess"], "run", run)
    current["k"] = "mac"
    assert ns["undefined_symbols"]("nm", ["/l/libcrypto.a"], darwin = True) == {"compress", "pthread_create", "_error"}
    assert ns["undefined_symbols"]("nm", ["/l/libcrypto.a"]) == set()           # bare names count only on macOS
    current["k"] = "gnu"
    assert ns["undefined_symbols"]("nm", ["/l/libcrypto.a"]) == {"deflate"}
    assert ns["static_deps"]({"compress", "pthread_create"}) == [d for d in ns["STATIC_DEPS"] if d["lib"] == "z"]


def test_openssl_static_archive_folder(tmp_path):
    ns = openssl_tool()
    lib = tmp_path / "homebrew" / "lib"
    lib.mkdir(parents = True)
    features = {"paths": {"libs": [str(lib)]}}
    assert ns["static_archive_folder"](features, str(tmp_path / "entry")) is None          # no archives
    for a in ["libssl.a", "libcrypto.a", "libssl.dylib"]:
        (lib / a).write_bytes(b"!<arch>\n" + a.encode())
    (tmp_path / "entry").mkdir()
    folder = ns["static_archive_folder"](features, str(tmp_path / "entry"))
    assert folder == str(tmp_path / "entry" / "static")
    assert sorted(p.name for p in (tmp_path / "entry" / "static").iterdir()) == ["libcrypto.a", "libssl.a"]
    assert ns["static_archive_folder"](features, None) is None


def test_openssl_finish_static_on_macos(tmp_path, monkeypatch):
    """A static request on macOS: the archives' folder as the only lib folder, the libraries the
    archives need (zlib from its tool, macOS has no static one), ssl and crypto first."""
    ns = openssl_tool()
    tool = object.__new__(ns["CTool"])
    setups = []

    class CM:
        def access(self, p):
            setups.append(p["name"])
            return {"return": 0}

        def catch_error(self, r, fail16 = False):
            return r["return"] > 0

        def error(self, text):
            return {"return": 1, "error": text}

    tool.cm = CM()
    lib = tmp_path / "lib"
    lib.mkdir()
    for a in ["libssl.a", "libcrypto.a"]:
        (lib / a).write_bytes(b"!<arch>\n")
    entry = tmp_path / "entry"
    entry.mkdir()
    monkeypatch.setattr(ns["shutil"], "which", lambda name: "/usr/bin/nm" if name == "nm" else None)
    monkeypatch.setitem(ns, "undefined_symbols", lambda nm, archives, darwin = False: {"compress", "pthread_create"} if darwin else set())
    monkeypatch.setitem(ns, "find_static_lib", lambda lib, dirs, compiler = None: None)
    ctx = {"control": {}, "tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "darwin"}},
                                                                   "compiler-c": {"path": "/usr/bin/clang"}}}}
    result = {"return": 0, "path_cmeta_cache": str(entry), "features": {"paths": {"libs": [str(lib)], "lib": str(lib)}, "lib_names": ["ssl", "crypto"]}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {"static": True}})["return"] == 0
    assert result["features"]["paths"]["libs_static"] == [str(entry / "static")]
    assert result["features"]["lib_names_static"] == ["ssl", "crypto", "z", "m"]
    assert setups == ["lib-zlib,c46f457c9da347a7"]
    # A dynamic request is as before: no static folder, no deps
    result = {"return": 0, "path_cmeta_cache": str(entry), "features": {"paths": {"libs": [str(lib)]}, "lib_names": ["ssl", "crypto"]}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {}})["return"] == 0
    assert "libs_static" not in result["features"]["paths"] and "lib_names_static" not in result["features"]


def test_static_openmp_note():
    path = REPO_ROOT / "task/setup-compile/api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask: pass")
    ns = {"__name__": "setup_compile", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    note = ns["static_openmp_note"]
    assert "DLL" in note("windows", True, True)
    for uname, static, openmp in [("windows", False, True), ("windows", True, False), ("linux", True, True), ("darwin", True, True)]:
        assert note(uname, static, openmp) is None


def test_lib_readmes_mention_static():
    assert "## Static links on macOS" in (REPO_ROOT / "tool/lib-openssl/README.md").read_text(encoding = "utf-8")
    assert "libomp.a" in (REPO_ROOT / "tool/lib-openmp/README.md").read_text(encoding = "utf-8")
