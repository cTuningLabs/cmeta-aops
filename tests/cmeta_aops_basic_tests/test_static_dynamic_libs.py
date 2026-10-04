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


class OpenSSLCM:
    """A cMeta that sets up a dependency tool and reports its static archive."""

    def __init__(self):
        self.setups = []

    def access(self, p):
        self.setups.append(p["name"])
        name = p["name"].split(",")[0]
        return {"return": 0, "features": {"static_lib": f"/cache/{name}/install/lib/lib{name[4:]}.a"}}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0

    def error(self, text):
        return {"return": 1, "error": text}


def test_openssl_static_archives_and_windows_folder(tmp_path):
    ns = openssl_tool()
    lib = tmp_path / "lib"
    lib.mkdir()
    assert ns["static_archives"]([str(lib)]) == []                                        # no archives
    (lib / "libssl.a").write_bytes(b"!<arch>\n")
    assert ns["static_archives"]([str(lib)]) == []                                        # both are needed
    (lib / "libcrypto.a").write_bytes(b"!<arch>\n")
    assert ns["static_archives"]([str(tmp_path), str(lib)]) == [str(lib / "libssl.a"), str(lib / "libcrypto.a")]
    # Windows: the MT folder next to the detected MD folder, with both static libraries
    vc = tmp_path / "VC" / "x64"
    (vc / "MD").mkdir(parents = True)
    assert ns["windows_static_folder"]({"lib": str(vc / "MD")}) == (None, str(vc))
    (vc / "MT").mkdir()
    (vc / "MT" / "libssl_static.lib").write_bytes(b"x")
    assert ns["windows_static_folder"]({"lib": str(vc / "MD")}) == (None, str(vc))
    (vc / "MT" / "libcrypto_static.lib").write_bytes(b"x")
    assert ns["windows_static_folder"]({"lib": str(vc / "MD")}) == (str(vc / "MT"), str(vc))
    assert ns["windows_static_folder"]({"lib": str(vc)}) == (str(vc / "MT"), str(vc))       # no run-time folders detected
    assert ns["windows_static_folder"]({}) == (None, "")


def test_openssl_finish_static_on_macos(tmp_path, monkeypatch):
    """with.static on macOS: libssl.a and libcrypto.a by their paths, then the archive of what they
    need (zlib from its tool: macOS has no static one), then libm; no lib folder is replaced."""
    ns = openssl_tool()
    tool = object.__new__(ns["CTool"])
    tool.cm = OpenSSLCM()
    lib = tmp_path / "lib"
    lib.mkdir()
    for a in ["libssl.a", "libcrypto.a", "libssl.dylib"]:
        (lib / a).write_bytes(b"!<arch>\n")
    entry = tmp_path / "entry"
    entry.mkdir()
    monkeypatch.setattr(ns["shutil"], "which", lambda name: "/usr/bin/nm" if name == "nm" else None)
    monkeypatch.setitem(ns, "undefined_symbols", lambda nm, archives, darwin = False: {"compress", "pthread_create"} if darwin else set())
    monkeypatch.setitem(ns, "find_static_lib", lambda lib, dirs, compiler = None: None)
    ctx = {"control": {}, "tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "darwin"}},
                                                                   "compiler-c": {"path": "/usr/bin/clang"}}}}
    # an entry made before today keeps the copies of the archives in a "static" folder: no longer used
    result = {"return": 0, "path_cmeta_cache": str(entry),
              "features": {"paths": {"libs": [str(lib)], "lib": str(lib), "libs_static": [str(entry / "static")]}, "lib_names": ["ssl", "crypto"]}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {"static": True}})["return"] == 0
    assert "libs_static" not in result["features"]["paths"]
    assert result["features"]["lib_names_static"] == [str(lib / "libssl.a"), str(lib / "libcrypto.a"), "/cache/lib-zlib/install/lib/libzlib.a", "m"]
    assert tool.cm.setups == ["lib-zlib,c46f457c9da347a7"]
    # A dynamic request: no tool is set up; the archives (and the system's static archives of what
    # they may need, none here) are named for a static build that did not ask this tool for one
    result = {"return": 0, "path_cmeta_cache": str(entry), "features": {"paths": {"libs": [str(lib)]}, "lib_names": ["ssl", "crypto"]}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {}})["return"] == 0
    assert result["features"]["lib_names_static"] == [str(lib / "libssl.a"), str(lib / "libcrypto.a"), "m"]
    assert "libs_static" not in result["features"]["paths"] and len(tool.cm.setups) == 1


def test_openssl_static_build_stops_without_archives(tmp_path):
    """No static archives: a request with with.static fails with what gives them on this system; a
    request without it records the reason (features.static_unavailable) for setup-compile."""
    ns = openssl_tool()
    tool = object.__new__(ns["CTool"])
    tool.cm = OpenSSLCM()
    ctx = {"control": {}, "tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "linux"}, "os_extra": {"id": "ubuntu", "id_like": "debian"}}}}}
    result = {"return": 0, "features": {"paths": {"libs": [str(tmp_path)]}, "lib_names": ["ssl", "crypto"]}}
    r = tool.finish_dynamic_result(ctx, result, {"with": {"static": True}})
    assert r["return"] == 1 and "libssl.a and libcrypto.a" in r["error"] and "this system (ubuntu): sudo apt-get install libssl-dev" in r["error"]
    assert "--tool_path=<prefix>/include/openssl/opensslv.h" in r["error"] and "without --compile.static" in r["error"]
    result = {"return": 0, "features": {"paths": {"libs": [str(tmp_path)]}, "lib_names": ["ssl", "crypto"], "lib_names_static": ["ssl", "crypto"]}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {}})["return"] == 0
    assert "libssl.a" in result["features"]["static_unavailable"] and "lib_names_static" not in result["features"]
    assert tool.cm.setups == []
    # macOS and Windows name their packages; the strings of with.static are read
    ctx["tasks"]["global"]["host"] = {"os": {"uname": "darwin"}}
    r = tool.finish_dynamic_result(ctx, {"return": 0, "features": {"paths": {"libs": [str(tmp_path)]}}}, {"with": {"static": "True"}})
    assert r["return"] == 1 and "brew install openssl@3" in r["error"]
    ctx["tasks"]["global"]["host"] = {"os": {"uname": "windows"}}
    r = tool.finish_dynamic_result(ctx, {"return": 0, "features": {"paths": {"lib": str(tmp_path / "MD")}}}, {"with": {"static": True}})
    assert r["return"] == 1 and "ShiningLight.OpenSSL.Dev" in r["error"] and "libssl_static.lib" in r["error"]
    # Windows with the MT libraries: the static folder, nothing unavailable; a dynamic request gets the DLL folder
    mt = tmp_path / "MT"
    mt.mkdir()
    for l in ["libssl_static.lib", "libcrypto_static.lib"]:
        (mt / l).write_bytes(b"x")
    (tmp_path / "bin").mkdir()
    result = {"return": 0, "features": {"paths": {"lib": str(tmp_path / "MD"), "dynamic_lib": str(tmp_path / "bin")}, "static_unavailable": "old"}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {}})["return"] == 0
    assert result["features"]["paths"]["libs_static"] == [str(mt)] and "static_unavailable" not in result["features"]
    assert result["features"]["paths"]["found_dynamic_lib_paths"] == [str(tmp_path / "bin")]
    result = {"return": 0, "features": {"paths": {"lib": str(tmp_path / "MD"), "dynamic_lib": str(tmp_path / "bin")}}}
    assert tool.finish_dynamic_result(ctx, result, {"with": {"static": True}})["return"] == 0
    assert "found_dynamic_lib_paths" not in result["features"]["paths"]


# task/setup-compile: a library file by its path, and a library that cannot serve a static build

def setup_compile_task():
    path = REPO_ROOT / "task/setup-compile/api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask: pass")
    ns = {"__name__": "setup_compile", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    task = object.__new__(ns["CTask"])

    class CM:
        @staticmethod
        def q(p):
            return f'"{p}"'

        @staticmethod
        def error(text):
            return {"return": 1, "error": text}

    task.cm = CM()
    return ns, task


def compile_ctx(tmp_path, openssl_features):
    gcc = {"qpath": "gcc", "features": {"flags": {"static_build": "-static", "lib_path": "-L", "lib_prefix": "-l", "lib_prefix2": "",
                                                  "exe_file": "-o ", "include_path": "-I"}, "vars": {"file_ext_exe": ""}}}
    return {"control": {}, "tasks": {"global": {"host": {"os": {"uname": "linux"}}, "compiler-c": gcc,
                                                "lib-openssl": {"features": openssl_features}}, "local": {}}}


def test_setup_compile_links_library_files(tmp_path):
    ns, task = setup_compile_task()
    archive = tmp_path / "libssl.a"
    archive.write_bytes(b"!<arch>\n")
    assert ns["is_library_file"](str(archive))
    assert not ns["is_library_file"]("ssl") and not ns["is_library_file"](str(tmp_path / "missing.a")) and not ns["is_library_file"]("lib/libssl.a")
    features = {"paths": {"libs": [str(tmp_path)]}, "lib_names": ["ssl", "crypto"], "lib_names_static": [str(archive), "m"]}
    run = lambda with_: task.run(compile_ctx(tmp_path, features), lang = "c", src_path = str(tmp_path), src_file_names = ["a.c"],
                                 target_path = str(tmp_path / "build"), **{"with": with_})
    r = run({"static": True})
    cmd = r["add_to_local"]["compile_cmds"][0]
    assert r["return"] == 0 and "-static" in cmd and "-lssl" not in cmd
    assert f'"{archive}"' in cmd and cmd.index(str(archive)) < cmd.index('-l"m"')          # the archive as it is, then -lm
    r = run({})
    cmd = r["add_to_local"]["compile_cmds"][0]
    assert r["return"] == 0 and '-l"ssl" -l"crypto"' in cmd and str(archive) not in cmd


def test_setup_compile_stops_a_static_build_the_library_cannot_serve(tmp_path):
    ns, task = setup_compile_task()
    features = {"paths": {"libs": [str(tmp_path)]}, "lib_names": ["ssl", "crypto"], "static_unavailable": "a static build needs libssl.a and libcrypto.a ..."}
    run = lambda with_: task.run(compile_ctx(tmp_path, features), lang = "c", src_path = str(tmp_path), src_file_names = ["a.c"],
                                 target_path = str(tmp_path / "build"), **{"with": with_})
    r = run({"static": True})
    assert r["return"] == 1 and r["error"].startswith("lib-openssl: a static build needs libssl.a")
    assert run({})["return"] == 0                                                 # a dynamic build is not concerned


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
    assert "## Static builds" in (REPO_ROOT / "tool/lib-openssl/README.md").read_text(encoding = "utf-8")
    assert "libomp.a" in (REPO_ROOT / "tool/lib-openmp/README.md").read_text(encoding = "utf-8")


# task/setup-compile: GCC's static OpenMP runtime (libgomp.a) by its path in a static build

def test_compiler_metas_declare_the_static_openmp_runtime():
    for name in ("gcc", "gcc-cpp"):
        assert desc(f"tool/{name}/_desc.yaml")["features"]["linux"]["flags"]["openmp_static_archive"] == "libgomp.a"
    assert desc("tool/nvcc/_desc.yaml")["features"]["linux"]["flags"]["linker_option_prefix"] == "-Xlinker "
    for name in ("clang", "clang-cpp", "msvc"):                                 # clang: lib-openmp's libomp.a; Windows: none
        for flags in (v.get("flags", {}) for v in desc(f"tool/{name}/_desc.yaml")["features"].values()):
            assert "openmp_static_archive" not in flags


def gcc_entry(tmp_path, archive = "libgomp.a", path = "/usr/bin/gcc"):
    return {"path": path, "qpath": f'"{path}"',
            "features": {"flags": {"static_build": "-static", "openmp": "-fopenmp", "openmp_static_archive": archive, "lib_path": "-L",
                                   "lib_prefix": "-l", "lib_prefix2": "", "exe_file": "-o ", "include_path": "-I"},
                         "vars": {"file_ext_exe": ""}}}


def test_static_openmp_runtime_resolution(tmp_path):
    ns, task = setup_compile_task()
    archive = tmp_path / "lib" / "gcc" / "12" / "libgomp.a"
    archive.parent.mkdir(parents = True)
    archive.write_bytes(b"!<arch>\n")
    q = lambda s: f'"{s}"'
    gcc = gcc_entry(tmp_path)
    ns["print_file_name"] = lambda compiler, name: str(tmp_path / "lib" / "gcc" / "12" / ".." / "12" / name)   # as gcc prints it, with ..
    r = ns["static_openmp_runtime"](gcc, "libgomp.a", gcc["features"]["flags"], "linux", q = q)
    assert r["return"] == 0 and r["archive"] == str(archive)
    assert r["link"] == [f'"{archive}"', "-lpthread", "-ldl", "-Wl,--as-needed"]
    nvcc_flags = {"lib_prefix": "-l", "linker_option_prefix": "-Xlinker ", "host_compiler": "-ccbin g++"}
    assert ns["static_openmp_runtime"](gcc, "libgomp.a", nvcc_flags, "linux", q = q)["link"][-1] == "-Xlinker --as-needed"
    # no archive: the compiler prints the bare name - an error that names the compiler and the system's package facts
    ns["print_file_name"] = lambda compiler, name: name
    r = ns["static_openmp_runtime"](gcc, "libgomp.a", gcc["features"]["flags"], "linux", os_id = "arch", q = q)
    assert r["return"] == 1 and "/usr/bin/gcc (libgomp.a)" in r["error"] and "this system (arch): Arch Linux" in r["error"]
    r = ns["static_openmp_runtime"](gcc, "libgomp.a", gcc["features"]["flags"], "linux", os_id = "rocky", id_like = "rhel centos fedora", q = q)
    assert "this system (rocky): the archive comes with the gcc package" in r["error"] and "--compile.static" in r["error"]
    # a compiler without an archive name (clang) and Windows: not this rule
    clang = {"path": "/usr/bin/clang", "features": {"flags": {"openmp": "-fopenmp"}}}
    assert ns["static_openmp_runtime"](clang, None, clang["features"]["flags"], "linux", q = q) is None
    assert ns["static_openmp_runtime"](gcc, "libgomp.a", gcc["features"]["flags"], "windows", q = q) is None


def openmp_ctx(tmp_path, compiler_key, compiler, extra_global = {}):
    g = {"host": {"os": {"uname": "linux"}, "os_extra": {"id": "debian"}}, compiler_key: compiler}
    g.update(extra_global)
    return {"control": {}, "tasks": {"global": g, "local": {}}}


def test_setup_compile_static_openmp_with_gcc(tmp_path):
    ns, task = setup_compile_task()
    archive = tmp_path / "libgomp.a"
    archive.write_bytes(b"!<arch>\n")
    ns["print_file_name"] = lambda compiler, name: str(archive)
    gcc = gcc_entry(tmp_path)
    run = lambda with_: task.run(openmp_ctx(tmp_path, "compiler-c", gcc, {"lib-m": {"features": {"paths": {}, "lib_names": ["m"]}}}),
                                 lang = "c", src_path = str(tmp_path), src_file_names = ["a.c"], target_path = str(tmp_path / "build"), **{"with": with_})
    r = run({"static": True, "openmp": True})
    cmd = r["add_to_local"]["compile_cmds"][0]
    assert r["return"] == 0 and "-static" in cmd and "-fopenmp" in cmd and r["static_openmp_runtime"] == str(archive)
    assert cmd.index('-l"m"') < cmd.index(f'"{archive}"') < cmd.index("-lpthread -ldl -Wl,--as-needed") < cmd.index("-o ")
    for with_ in ({"openmp": True}, {"static": True}, {}):                                # dynamic, or no OpenMP: not concerned
        r = run(with_)
        cmd = r["add_to_local"]["compile_cmds"][0]
        assert r["return"] == 0 and str(archive) not in cmd and "--as-needed" not in cmd and "static_openmp_runtime" not in r


def test_setup_compile_static_openmp_with_nvcc_and_its_host_gcc(tmp_path):
    """nvcc runs the host link without -static: the runtime of the host compiler (compiler-cpp), the -Xlinker form."""
    ns, task = setup_compile_task()
    archive = tmp_path / "libgomp.a"
    archive.write_bytes(b"!<arch>\n")
    ns["print_file_name"] = lambda compiler, name: str(archive) if compiler == "/usr/bin/g++" else name
    nvcc = {"path": "/usr/local/cuda/bin/nvcc", "qpath": '"/usr/local/cuda/bin/nvcc"',
            "features": {"flags": {"static_build": "-cudart=static", "openmp": "-Xcompiler -fopenmp", "link_openmp": None, "host_compiler": "-ccbin /usr/bin/g++",
                                   "lib_path": "-L", "lib_prefix": "-l", "lib_prefix2": "", "exe_file": "-o ", "include_path": "-I", "linker_option_prefix": "-Xlinker "},
                         "vars": {"file_ext_exe": ""}}}
    gpp = gcc_entry(tmp_path, path = "/usr/bin/g++")
    r = task.run(openmp_ctx(tmp_path, "compiler-cuda", nvcc, {"compiler-cpp": gpp}), lang = "cuda", src_path = str(tmp_path),
                 src_file_names = ["a.cu"], target_path = str(tmp_path / "build"), **{"with": {"static": True, "openmp": True}})
    cmd = r["add_to_local"]["compile_cmds"][0]
    assert r["return"] == 0 and "-ccbin /usr/bin/g++" in cmd and "-cudart=static" in cmd and "-Xcompiler -fopenmp" in cmd
    assert f'"{archive}" -lpthread -ldl -Xlinker --as-needed' in cmd and cmd.index("--as-needed") < cmd.index("-o ")
    # the host compiler has no archive: the build stops before the compile with the reason
    ns["print_file_name"] = lambda compiler, name: name
    r = task.run(openmp_ctx(tmp_path, "compiler-cuda", nvcc, {"compiler-cpp": gpp}), lang = "cuda", src_path = str(tmp_path),
                 src_file_names = ["a.cu"], target_path = str(tmp_path / "build"), **{"with": {"static": True, "openmp": True}})
    assert r["return"] == 1 and r["error"].startswith("a static build with OpenMP needs the static OpenMP runtime of /usr/bin/g++ (libgomp.a)")
    assert "this system (debian): the archive comes with the compiler" in r["error"]


def test_openmp_readme_mentions_libgomp():
    assert "libgomp.a" in (REPO_ROOT / "tool/lib-openmp/README.md").read_text(encoding = "utf-8")
