"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The provenance record of a program run (category/task/api/provenance.py): the modes, what the record
holds, the loader-log parsers, and every check with its positive and negative case; then the hook in
task/compile-and-run-program (the snapshot of the request, the record after the run, the warning
path, strict mode). Offline: a fake context and a stand-in for the binary inspector.
"""

import copy
import importlib.util
import json
import os
import pathlib
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def prov():
    path = REPO_ROOT / "category" / "task" / "api" / "provenance.py"
    spec = importlib.util.spec_from_file_location("provenance_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_inspector(deps = None, static = False, fmt = "elf", raise_ = None):
    """A stand-in for binary_deps: resolve() answers with the given dependencies."""
    def resolve(path, env = None, cwd = None, uname = None, **kw):
        if raise_:
            raise raise_
        return {"path": path, "format": fmt, "arch": "x86_64", "bits": 64, "static": static, "interpreter": None,
                "needed": [d["name"] for d in deps or []], "delay_needed": [], "rpath": [], "runpath": [], "kind": "executable",
                "deps": copy.deepcopy(deps or []), "missing": [d["name"] for d in deps or [] if d.get("path") is None], "error": None}

    def is_system_library(name, uname = None):
        base = os.path.basename(str(name)).lower()
        return base.startswith(("libc.so", "libm.so", "libdl.so", "libpthread.so", "ld-linux", "linux-vdso", "kernel32",
                                "api-ms-win-", "vcruntime", "libsystem", "/usr/lib/libsystem")) or str(name).startswith("/usr/lib/libSystem")

    return types.SimpleNamespace(resolve = resolve, is_system_library = is_system_library,
                                 inspect = lambda p: resolve(p), describe = lambda info: "fake")


def ctx_global(uname = "linux", cuda = False, python = False):
    g = {"host": {"os": {"uname": uname, "uarch": "amd64"}, "os_extra": {"id": "ubuntu"},
                  "hostname": {"hostname": "box", "ipv4": ["10.0.0.2"]}},
         "init": {}, "runner": {}, "target": {"compute": ["cuda"] if cuda else ["cpu"]},
         "compiler-c": {"tool": {"name": "gcc"}, "version": "14.2.0", "path": "/usr/bin/gcc", "path_bin": "/usr/bin",
                        "path_cmeta_cache": "/home/u/CMETA/repos/local/cache/task--setup--gcc--0123456789abcdef",
                        "features": {"flags": {}}},
         "lib-openssl": {"version": "3.0.13", "path": "/usr/include/openssl/opensslv.h", "path_bin": "/usr/include/openssl",
                         "path_cmeta_cache": "/home/u/CMETA/repos/local/cache/task--setup--lib-openssl--fedcba9876543210",
                         "features": {"lib_names": ["ssl", "crypto"],
                                      "paths": {"dynamic_lib": "/usr/lib/x86_64-linux-gnu", "lib": "/usr/lib/x86_64-linux-gnu"}}},
         "lib-xopenme": {"version": "default", "path": "/home/u/CMETA/repos/local/cache/task--setup--lib-xopenme--1111222233334444/build/lib/dynamic/libxopenme.so",
                         "path_cmeta_cache": "/home/u/CMETA/repos/local/cache/task--setup--lib-xopenme--1111222233334444",
                         "features": {"lib_names": ["xopenme"], "lib_names_static": ["xopenme"],
                                      "paths": {"dynamic_lib": "/home/u/CMETA/repos/local/cache/task--setup--lib-xopenme--1111222233334444/build/lib/dynamic"}}}}
    if cuda:
        g["nvcc"] = {"version": "13.3.73", "path": "/usr/local/cuda-13.3/bin/nvcc", "path_bin": "/usr/local/cuda-13.3/bin",
                     "path_cmeta_cache": "/home/u/CMETA/repos/local/cache/task--setup--nvcc--aaaa0000bbbb1111",
                     "features": {"paths": {"bin": "/usr/local/cuda-13.3/bin", "bins": ["/usr/local/cuda-13.3/bin"], "lib": "/usr/local/cuda-13.3/lib64"}}}
        g["lib-cudnn"] = {"version": "9.27.0", "path": "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--cccc0000dddd1111/content/lib/libcudnn.so.9",
                          "path_bin": "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--cccc0000dddd1111/content/lib",
                          "path_cmeta_cache": "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--cccc0000dddd1111",
                          "features": {"lib_names": ["cudnn"], "paths": {"dynamic_lib": "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--cccc0000dddd1111/content/lib"}}}
        g["cuda"] = {"version": "13.3", "path": "/usr/bin/nvidia-smi",
                     "features": {"versions": {"driver version": "610.43", "cuda version": "13.3"}, "compute_cap_int_min": 86,
                                  "devices": ["NVIDIA RTX A500"]}}
    if python:
        g["python"] = {"version": "3.12.3", "path": "/home/u/CMETA/repos/local/cache/task--setup--python--9999888877776666/venv/bin/python",
                       "path_cmeta_cache": "/home/u/CMETA/repos/local/cache/task--setup--python--9999888877776666"}
    return g


def dep(name, path, system = False, source = "env"):
    return {"name": name, "path": path, "source": source, "system": system}


SYSTEM_DEPS = [dep("libc.so.6", "/lib/x86_64-linux-gnu/libc.so.6", True, "system"),
               dep("libm.so.6", "/lib/x86_64-linux-gnu/libm.so.6", True, "system")]


def record(prov, inspector, uname = "linux", cuda = False, python = False, compile_static = False, requested_static = None,
           use = None, mode = "on", result_data = None, local = None, target = None, **kw):
    prov.binary_deps = inspector
    g = ctx_global(uname, cuda, python)
    target = str(target) if target else "/tmp/build"
    local = dict(local or {})
    local.setdefault("target_path_exe", os.path.join(target, "program"))
    request_params = {"name": "prog", "compute": "cuda" if cuda else None}
    if requested_static is not None:
        request_params["compile"] = {"static": requested_static}
    return prov.build_record(mode, {"alias": "prog", "uid": "0" * 16}, "tmp", target, g["target"]["compute"], g, local,
                             {k: v for k, v in request_params.items() if v is not None}, use or {}, compile_static,
                             result_data = result_data, **kw)


# ---------------------------------------------------------------------------------------------- modes

def test_modes(prov):
    assert prov.mode_of(None) == "on" and prov.mode_of(True) == "on" and prov.mode_of("ON") == "on" and prov.mode_of("yes") == "on"
    assert prov.mode_of(False) == "off" and prov.mode_of("off") == "off" and prov.mode_of("no") == "off"
    assert prov.mode_of("loaded") == "loaded" and prov.mode_of(" Strict ") == "strict"
    with pytest.raises(ValueError) as e:
        prov.mode_of("bogus")
    assert "on, off, loaded or strict" in str(e.value)


def test_loader_env_per_os(prov, tmp_path):
    linux = prov.loader_env("linux", str(tmp_path))
    assert linux["LD_DEBUG"] == "libs" and linux["LD_DEBUG_OUTPUT"].startswith(str(tmp_path))
    mac = prov.loader_env("darwin", str(tmp_path))
    assert mac["DYLD_PRINT_LIBRARIES"] == "1" and mac["DYLD_PRINT_TO_FILE"].endswith("tmp-cmeta-dyld.log")
    assert prov.loader_env("windows", str(tmp_path)) == {}


def test_run_environment_prepends_lists(prov):
    env = prov.run_environment({"+PATH": ["/opt/x/bin", "/opt/y/bin"], "+LD_LIBRARY_PATH": ["/opt/x/lib"], "CMETA_TARGETS": "cpu"},
                               base = {"PATH": "/usr/bin", "HOME": "/home/u"})
    assert env["PATH"] == os.pathsep.join(["/opt/x/bin", "/opt/y/bin", "/usr/bin"])
    assert env["LD_LIBRARY_PATH"] == "/opt/x/lib" and env["CMETA_TARGETS"] == "cpu" and env["HOME"] == "/home/u"


# ---------------------------------------------------------------------------------------------- parsers

LD_DEBUG_TEXT = """     12345:\tfind library=libc.so.6 [0]; searching
     12345:\t search cache=/etc/ld.so.cache
     12345:\t  trying file=/lib/x86_64-linux-gnu/libc.so.6
     12345:\t
     12345:\tcalling init: /lib/x86_64-linux-gnu/libc.so.6
     12345:\t
     12345:\tcalling init: /usr/local/cuda-13.3/lib64/libcudart.so.13
     12345:\tcalling init: /lib/x86_64-linux-gnu/libc.so.6
     12345:\tinitialize program: ./program
     12345:\ttransferring control: ./program
"""

DYLD_TEXT = """dyld[4242]: <09E862B1-67E8-3B07-9E46-81494986DF74> /usr/lib/libSystem.B.dylib
dyld[4242]: /opt/homebrew/opt/libomp/lib/libomp.dylib
dyld[4242]: <1B8AB7A7-AD95-3B41-85F2-FB21B66B6423> /usr/lib/libSystem.B.dylib
something else
"""


def test_parse_ld_debug(prov):
    assert prov.parse_ld_debug(LD_DEBUG_TEXT) == ["/lib/x86_64-linux-gnu/libc.so.6", "/usr/local/cuda-13.3/lib64/libcudart.so.13"]


def test_parse_dyld_log(prov):
    assert prov.parse_dyld_log(DYLD_TEXT) == ["/usr/lib/libSystem.B.dylib", "/opt/homebrew/opt/libomp/lib/libomp.dylib"]


def test_loader_logs_are_read_per_process_and_cleared(prov, tmp_path):
    (tmp_path / "tmp-cmeta-ld-debug.101").write_text(LD_DEBUG_TEXT)
    (tmp_path / "tmp-cmeta-ld-debug.102").write_text("     102:\tcalling init: /lib/x86_64-linux-gnu/libtinfo.so.6\n")
    paths, processes = prov.loader_log_libraries(str(tmp_path), "linux")
    assert processes == 2 and "/lib/x86_64-linux-gnu/libtinfo.so.6" in paths and "/usr/local/cuda-13.3/lib64/libcudart.so.13" in paths
    prov.clear_loader_logs(str(tmp_path))
    assert prov.loader_log_libraries(str(tmp_path), "linux") == (None, 0)


def test_library_key(prov):
    assert prov.library_key("libcublasLt.so.13") == "cublaslt"
    assert prov.library_key("cudart64_13.dll") == "cudart"
    assert prov.library_key("libcrypto-4-x64.dll") == "crypto"
    assert prov.library_key("/usr/lib/x86_64-linux-gnu/libstdc++.so.6") == "stdc++"
    assert prov.library_key("ssl_static") == "ssl" and prov.library_key("$ws2_32") == "ws2_32"
    assert prov.library_key("libcudnn_ops.so.9") == "cudnn_ops" and prov.library_key("VCOMP140.DLL") == "vcomp140"
    assert prov.library_key("libgomp.so.1") == "gomp" and prov.library_key("libz.so.1") == "z"
    assert prov.library_key("/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib") == "crypto"      # Mach-O: the version before .dylib
    assert prov.library_key("libssl.3.dylib") == "ssl" and prov.library_key("/opt/homebrew/opt/libomp/lib/libomp.dylib") == "omp"


# ---------------------------------------------------------------------------------------------- the record

def test_record_shape_and_passive_resolution(prov, tmp_path):
    deps = SYSTEM_DEPS + [dep("libcrypto.so.3", "/usr/lib/x86_64-linux-gnu/libcrypto.so.3"),
                          dep("libxopenme.so", "/home/u/CMETA/repos/local/cache/task--setup--lib-xopenme--1111222233334444/build/lib/dynamic/libxopenme.so")]
    r = record(prov, fake_inspector(deps), target = tmp_path, local = {"run_time_env": {"+LD_LIBRARY_PATH": ["/opt/x/lib"]}})
    assert r["format"] == 1 and r["mode"] == "on" and r["program"]["alias"] == "prog" and r["compute"] == ["cpu"]
    assert r["host"] == {"uname": "linux", "uarch": "amd64", "os_id": "ubuntu", "hostname": "box"}
    assert r["requested"] == {"use": {}}                                  # nothing was explicit
    assert r["resolved"]["compiler-c"]["name"] == "gcc" and r["resolved"]["compiler-c"]["entry"] == "0123456789abcdef"
    assert r["resolved"]["lib-openssl"]["features"]["lib_names"] == ["ssl", "crypto"]
    assert "host" not in r["resolved"] and "target" not in r["resolved"]
    assert r["build"]["binary"]["format"] == "elf" and r["build"]["binary"]["kind_of_file"] == "program"
    assert r["loaded"]["method"] == "resolved"
    by_name = {l["name"]: l for l in r["loaded"]["libraries"]}
    assert by_name["libc.so.6"]["system"] is True and by_name["libcrypto.so.3"]["tool"] == "lib-openssl"
    assert by_name["libxopenme.so"]["tool"] == "lib-xopenme"
    assert r["ok"] is True and not any(c["rule"] == "static" for c in r["checks"])
    assert any(c["rule"] == "origin" and c.get("tool") == "lib-openssl" and c["ok"] for c in r["checks"])
    json.dumps(r)                                                          # serializable as written


def test_requested_keeps_only_what_was_explicit(prov):
    req = prov.requested_from({"name": "p", "compute": "cuda,cpu", "compile": {"static": True}, "with": {"x": 1}, "target_tmp": "t",
                               "provenance": "strict", "size": 1000, "env": {}}, {"nvcc": {"version": "12.9"}})
    assert req == {"use": {"nvcc": {"version": "12.9"}}, "compile": {"static": True}, "with": {"x": 1}, "compute": ["cuda", "cpu"],
                   "params": {"size": 1000}}


def test_record_written_and_summarized(prov, tmp_path):
    r = record(prov, fake_inspector(SYSTEM_DEPS), target = tmp_path)
    assert prov.write_record(str(tmp_path), r) is None
    data = json.loads((tmp_path / "provenance.json").read_text(encoding = "utf-8"))
    assert data["format"] == 1 and data["ok"] is True
    assert prov.summary(r) == {"ok": True, "errors": 0, "warnings": 0} and prov.failed_lines(r) == []


def test_inspector_failure_is_a_note_not_an_error(prov, tmp_path):
    r = record(prov, fake_inspector(raise_ = NotImplementedError("later")), target = tmp_path, compile_static = True, requested_static = True)
    assert r["build"]["binary"]["format"] is None and "unavailable" in r["build"]["binary"]["error"]
    assert r["loaded"]["method"] == "resolved" and r["loaded"]["libraries"] == []
    static = [c for c in r["checks"] if c["rule"] == "static"]
    assert static and static[0]["level"] == "info" and static[0]["ok"] is None
    assert r["ok"] is True


def test_python_program_inspects_the_interpreter(prov, tmp_path):
    python = tmp_path / "venv" / "bin"
    python.mkdir(parents = True)
    (python / "python").write_bytes(b"\x7fELF")
    inspector = fake_inspector(SYSTEM_DEPS)
    prov.binary_deps = inspector
    g = ctx_global(python = True)
    g["python"]["path"] = str(python / "python")
    r = prov.build_record("on", {"alias": "pyprog", "uid": "1" * 16}, "tmp", str(tmp_path), ["cpu"], g, {}, {"name": "pyprog"}, {}, False)
    assert r["build"]["binary"]["kind_of_file"] == "interpreter" and r["build"]["binary"]["path"] == str(python / "python")
    assert r["runtime"]["python"]["version"] == "3.12.3"


# ---------------------------------------------------------------------------------------------- the checks

def check(r, rule):
    return [c for c in r["checks"] if c["rule"] == rule]


def test_static_cpu_fully_static_passes(prov, tmp_path):
    r = record(prov, fake_inspector([], static = True), target = tmp_path, compile_static = True, requested_static = True)
    s = check(r, "static")
    assert s and s[0]["ok"] is True and s[0]["level"] == "error" and r["ok"] is True


def test_static_cpu_with_shared_libcrypto_is_an_error_when_requested(prov, tmp_path):
    deps = SYSTEM_DEPS + [dep("libcrypto.so.3", "/usr/lib/x86_64-linux-gnu/libcrypto.so.3")]
    r = record(prov, fake_inspector(deps, static = False), target = tmp_path, compile_static = True, requested_static = True)
    s = check(r, "static")[0]
    assert s["ok"] is False and s["level"] == "error" and "not fully static" in s["detail"] and r["ok"] is False
    assert prov.summary(r)["errors"] == 1 and prov.failed_lines(r) == [("error", s["detail"])]


def test_static_from_a_default_is_a_warning(prov, tmp_path):
    deps = SYSTEM_DEPS + [dep("libcrypto.so.3", "/usr/lib/x86_64-linux-gnu/libcrypto.so.3")]
    r = record(prov, fake_inspector(deps, static = False), target = tmp_path, compile_static = True, requested_static = None)
    s = check(r, "static")[0]
    assert s["ok"] is False and s["level"] == "warning" and r["ok"] is True and prov.summary(r)["warnings"] == 1


def test_static_cuda_allows_nvidia_and_cxx_runtime_but_not_cudart(prov, tmp_path):
    allowed = SYSTEM_DEPS + [dep("libstdc++.so.6", "/usr/lib/x86_64-linux-gnu/libstdc++.so.6"),
                             dep("libgcc_s.so.1", "/lib/x86_64-linux-gnu/libgcc_s.so.1"),
                             dep("libcuda.so.1", "/usr/lib/x86_64-linux-gnu/libcuda.so.1"),
                             dep("libcudnn.so.9", "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--cccc0000dddd1111/content/lib/libcudnn.so.9"),
                             dep("libcublas.so.13", "/usr/local/cuda-13.3/lib64/libcublas.so.13")]
    r = record(prov, fake_inspector(allowed), target = tmp_path, cuda = True, compile_static = True, requested_static = True)
    assert check(r, "static")[0]["ok"] is True and r["ok"] is True
    bad = allowed + [dep("libcudart.so.13", "/usr/local/cuda-13.3/lib64/libcudart.so.13"),
                     dep("libgomp.so.1", "/lib/x86_64-linux-gnu/libgomp.so.1")]
    r = record(prov, fake_inspector(bad), target = tmp_path, cuda = True, compile_static = True, requested_static = True)
    s = check(r, "static")[0]
    assert s["ok"] is False and "libcudart.so.13" in s["detail"] and "libgomp.so.1" in s["detail"] and "libcublas" not in s["detail"]


def test_static_windows_allows_the_openmp_dll(prov, tmp_path):
    deps = [dep("KERNEL32.dll", "C:/Windows/System32/KERNEL32.dll", True, "system"),
            dep("VCOMP140.DLL", "C:/Windows/System32/VCOMP140.DLL"), dep("api-ms-win-crt-math-l1-1-0.dll", "C:/Windows/System32/x.dll", True, "api")]
    r = record(prov, fake_inspector(deps, fmt = "pe"), uname = "windows", target = tmp_path, compile_static = True, requested_static = True)
    assert check(r, "static")[0]["ok"] is True
    r = record(prov, fake_inspector(deps + [dep("libcrypto-3-x64.dll", "C:/OpenSSL/bin/libcrypto-3-x64.dll")], fmt = "pe"),
               uname = "windows", target = tmp_path, compile_static = True, requested_static = True)
    s = check(r, "static")[0]
    assert s["ok"] is False and "libcrypto-3-x64.dll" in s["detail"]


def test_origin_a_library_from_another_folder(prov, tmp_path):
    deps = SYSTEM_DEPS + [dep("libcudart.so.12", "/usr/local/cuda-12.9/lib64/libcudart.so.12"),
                          dep("libcudnn.so.9", "/opt/other/libcudnn.so.9")]
    r = record(prov, fake_inspector(deps), target = tmp_path, cuda = True, use = {"nvcc": {"version": "13.3"}})
    origin = {c["tool"]: c for c in check(r, "origin") if c["ok"] is False}
    assert "nvcc" in origin and origin["nvcc"]["level"] == "error"            # nvcc was requested with --use
    assert "cuda-12.9" in origin["nvcc"]["detail"]
    assert "lib-cudnn" in origin and origin["lib-cudnn"]["level"] == "warning"  # a default
    assert r["ok"] is False


def test_origin_passes_when_the_library_is_the_tools_own(prov, tmp_path):
    deps = SYSTEM_DEPS + [dep("libcudart.so.13", "/usr/local/cuda-13.3/lib64/libcudart.so.13"),
                          dep("libcudnn.so.9", "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--cccc0000dddd1111/content/lib/libcudnn.so.9")]
    r = record(prov, fake_inspector(deps), target = tmp_path, cuda = True)
    assert all(c["ok"] for c in check(r, "origin")) and r["ok"] is True
    assert {c["tool"] for c in check(r, "origin")} == {"nvcc", "lib-cudnn"}


def test_version_check_uses_the_matcher(prov, tmp_path):
    calls = []

    def matcher(spec, version):
        calls.append((spec, version))
        return spec == "13.3"

    r = record(prov, fake_inspector(SYSTEM_DEPS), target = tmp_path, cuda = True, match_version = matcher,
               use = {"nvcc": {"version": "13.3"}, "lib-cudnn": {"version": "9.10"}, "python": {"version": "3.12"}})
    v = {c["tool"]: c for c in check(r, "version")}
    assert v["nvcc"]["ok"] is True and v["lib-cudnn"]["ok"] is False and v["lib-cudnn"]["level"] == "error"
    assert v["python"]["ok"] is None and v["python"]["level"] == "info"      # not part of this run
    assert ("13.3", "13.3.73") in calls and r["ok"] is False


def test_accelerator_required_but_unavailable(prov, tmp_path):
    data = {"stats": {"results": [{"accelerator": "cpu", "available": True, "required": True},
                                  {"accelerator": "gpu", "available": False, "required": False},
                                  {"accelerator": "npu", "available": False, "required": True}]}}
    r = record(prov, fake_inspector(SYSTEM_DEPS), target = tmp_path, result_data = data)
    acc = {c["detail"].split()[1]: c for c in check(r, "accelerator")}
    assert acc["npu"]["ok"] is False and acc["npu"]["level"] == "error"
    assert acc["gpu"]["ok"] is True and acc["gpu"]["level"] == "info" and "optional" in acc["gpu"]["detail"]
    assert acc["cpu"]["ok"] is True and r["ok"] is False and r["result"] == data


def test_loaded_mode_reads_the_logs_and_attributes(prov, tmp_path):
    (tmp_path / "tmp-cmeta-ld-debug.7").write_text(
        "     7:\tcalling init: /lib/x86_64-linux-gnu/libc.so.6\n"
        "     7:\tcalling init: /usr/local/cuda-13.3/lib64/libcudart.so.13\n"
        "     7:\tcalling init: /home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--cccc0000dddd1111/content/lib/libcudnn.so.9\n"
        "     7:\tcalling init: " + os.path.join(str(tmp_path), "program") + "\n")
    r = record(prov, fake_inspector(SYSTEM_DEPS), target = tmp_path, cuda = True, mode = "loaded")
    assert r["loaded"]["method"] == "loader-log" and r["loaded"]["processes"] == 1
    names = {l["name"]: l for l in r["loaded"]["libraries"]}
    assert "program" not in names and names["libcudart.so.13"]["tool"] == "nvcc" and names["libcudnn.so.9"]["tool"] == "lib-cudnn"
    assert names["libc.so.6"]["system"] is True


def test_loaded_mode_without_logs_falls_back_to_resolution(prov, tmp_path):
    r = record(prov, fake_inspector(SYSTEM_DEPS, fmt = "pe"), uname = "windows", target = tmp_path, mode = "loaded")
    assert r["loaded"]["method"] == "resolved" and "resolution stands in" in r["loaded"]["note"]
    r = record(prov, fake_inspector(SYSTEM_DEPS), target = tmp_path, mode = "loaded", run_skipped = True)
    assert r["loaded"]["method"] == "resolved" and "skipped" in r["loaded"]["note"]


# ---------------------------------------------------------------------------------------------- the driver hook

def driver_source():
    return (REPO_ROOT / "task" / "compile-and-run-program" / "api_v1.py").read_text(encoding = "utf-8")


def test_driver_snapshots_the_request_before_the_defaults_and_hooks_after_the_run():
    src = driver_source()
    i_copy = src.index("params = copy.deepcopy(params)\n")
    i_snap = src.index("request_params = copy.deepcopy(params)")
    i_use = src.index("request_use = copy.deepcopy(ctx['tasks'].get('use') or {})")
    i_merge = src.index("params_desc = copy.deepcopy(desc['params'])")
    i_desc_use = src.index("_use = desc.get('use')")
    assert i_copy < i_snap < i_use < i_merge < i_desc_use           # the snapshot precedes both merges
    i_mode = src.index("provenance_mode = provenance.mode_of(params.get('provenance'))")
    i_env = src.index("provenance.loader_env(uname, target_path)")
    i_run_uses = src.index("run_uses = run_desc.get('uses')")
    i_hook = src.index("r = self.write_provenance(ctx, params, provenance_mode, request_params, request_use,")
    i_impact = src.index("result['_impact'] = {'self_time_compile_with_cmeta': self_time_compile,")
    assert i_mode < i_env < i_run_uses < i_hook < i_impact            # env before the run, the record after it
    assert "if provenance_mode == 'loaded' and uname in ('linux', 'darwin')" in src
    assert "if provenance_mode != 'off':" in src


class FakeCM:
    debug = False

    def __init__(self):
        self.packages = types.SimpleNamespace(match_version = lambda spec, v: {"return": 0, "matched": spec.split("=")[-1] in v})

    def error(self, text, code = 1):
        return {"return": code, "error": text}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0


@pytest.fixture
def driver(prov):
    """The driver's CTask with the engine base class stubbed, and the provenance module under test."""
    src = driver_source().replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask: pass")
    src = src.replace("from task_c36be4b9314a45e0.api import deadlines", "").replace("from task_c36be4b9314a45e0.api import build_stamp", "")
    src = src.replace("from task_c36be4b9314a45e0.api import provenance", "").replace("from task_c36be4b9314a45e0.api import build_identity", "")
    spec = importlib.util.spec_from_file_location("build_identity_for_the_driver", REPO_ROOT / "category" / "task" / "api" / "build_identity.py")
    build_identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_identity)
    ns = {"__name__": "driver_under_test", "__file__": str(REPO_ROOT / "task" / "compile-and-run-program" / "api_v1.py"),
          "provenance": prov, "deadlines": None, "build_stamp": None, "build_identity": build_identity}
    exec(compile(src, ns["__file__"], "exec"), ns)
    task = object.__new__(ns["CTask"])
    task.cm = FakeCM()
    return task


def hook_ctx(tmp_path, cuda = False, con = True):
    g = ctx_global(cuda = cuda)
    return {"control": {"con": con, "verbose": False, "quiet": True},
            "tasks": {"nested_call": 0, "global": g, "local": {"target_path_exe": os.path.join(str(tmp_path), "program"),
                                                              "result_files_data": {"stats": {"aggregated_value": 1.0}}}, "use": {}}}


def test_hook_writes_the_record_and_reports(driver, prov, tmp_path, capsys):
    prov.binary_deps = fake_inspector(SYSTEM_DEPS + [dep("libcrypto.so.3", "/usr/lib/x86_64-linux-gnu/libcrypto.so.3")])
    ctx = hook_ctx(tmp_path)
    r = driver.write_provenance(ctx, {"compile": {"static": False}}, "on", {"name": "prog"}, {}, str(tmp_path), "tmp", "prog", "0" * 16, ["cpu"])
    assert r["return"] == 0 and r["provenance"]["ok"] is True and r["provenance"]["errors"] == 0
    assert r["provenance"]["path"] == os.path.join(str(tmp_path), "provenance.json") and (tmp_path / "provenance.json").is_file()
    assert "PROVENANCE" not in capsys.readouterr().out                    # nothing printed when all pass


def test_hook_strict_fails_after_writing_the_record(driver, prov, tmp_path, capsys):
    prov.binary_deps = fake_inspector(SYSTEM_DEPS + [dep("libcrypto.so.3", "/usr/lib/x86_64-linux-gnu/libcrypto.so.3")], static = False)
    ctx = hook_ctx(tmp_path)
    r = driver.write_provenance(ctx, {"compile": {"static": True}}, "on", {"name": "prog", "compile": {"static": True}}, {},
                                str(tmp_path), "tmp", "prog", "0" * 16, ["cpu"])
    assert r["return"] == 0 and r["provenance"]["ok"] is False and r["provenance"]["errors"] == 1
    out = capsys.readouterr().out
    assert "PROVENANCE: static build" in out and "(warning)" not in out
    r = driver.write_provenance(ctx, {"compile": {"static": True}}, "strict", {"name": "prog", "compile": {"static": True}}, {},
                                str(tmp_path), "tmp", "prog", "0" * 16, ["cpu"])
    assert r["return"] == 99 and r["error"].startswith("PROVENANCE: 1 check(s) failed:")
    assert json.loads((tmp_path / "provenance.json").read_text(encoding = "utf-8"))["ok"] is False


def test_hook_warns_and_goes_on_when_the_record_cannot_be_written(driver, prov, tmp_path, capsys):
    prov.binary_deps = fake_inspector(SYSTEM_DEPS)
    ctx = hook_ctx(tmp_path)
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("x")                                                  # a file where the folder should be
    r = driver.write_provenance(ctx, {}, "strict", {"name": "prog"}, {}, str(blocked), "tmp", "prog", "0" * 16, ["cpu"])
    assert r["return"] == 0 and r["provenance"]["path"] is None and r["provenance"]["error"]
    assert "WARNING: provenance record not written" in capsys.readouterr().out


def test_hook_warning_level_is_printed_as_such(driver, prov, tmp_path, capsys):
    prov.binary_deps = fake_inspector(SYSTEM_DEPS + [dep("libcrypto.so.3", "/usr/lib/x86_64-linux-gnu/libcrypto.so.3")], static = False)
    ctx = hook_ctx(tmp_path)
    r = driver.write_provenance(ctx, {"compile": {"static": True}}, "strict", {"name": "prog"}, {}, str(tmp_path), "tmp", "prog", "0" * 16, ["cpu"])
    assert r["return"] == 0 and r["provenance"]["warnings"] == 1            # static came from a default: a warning, strict passes
    assert "PROVENANCE (warning): static build" in capsys.readouterr().out


def test_origin_follows_symbolic_links(prov, tmp_path, monkeypatch):
    """Debian's /lib is a link to /usr/lib: a library the loader names under /lib belongs to a tool whose folder is /usr/lib."""
    real = os.path.realpath

    def linked(path):
        p = str(path).replace("\\", "/")
        return "/usr/lib/" + p[len("/lib/"):] if p.startswith("/lib/") else real(path)

    monkeypatch.setattr(prov.os.path, "realpath", linked)
    assert prov.under("/lib/x86_64-linux-gnu/libcrypto.so.3", [os.path.normcase(os.path.normpath("/usr/lib/x86_64-linux-gnu"))])
    assert not prov.under("/opt/other/libcrypto.so.3", [os.path.normcase(os.path.normpath("/usr/lib/x86_64-linux-gnu"))])
    deps = SYSTEM_DEPS + [dep("libcrypto.so.3", "/lib/x86_64-linux-gnu/libcrypto.so.3")]
    r = record(prov, fake_inspector(deps), target = tmp_path)
    assert all(c["ok"] for c in check(r, "origin")) and r["ok"] is True


def test_attribution_by_name_then_by_cache_entry(prov):
    g = ctx_global(cuda = True)
    # the distribution's OpenSSL shares /usr/lib with everything: libcrypto is its own, libgomp is nobody's
    assert prov.attribute("/usr/lib/x86_64-linux-gnu/libcrypto.so.3", g) == "lib-openssl"
    assert prov.attribute("/usr/lib/x86_64-linux-gnu/libgomp.so.1", g) is None
    # a library inside a tool's cache entry belongs to that tool, whatever its name
    assert prov.attribute("/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--cccc0000dddd1111/content/lib/libcudnn_graph.so.9", g) == "lib-cudnn"
    assert prov.attribute("/opt/other/libcudnn.so.9", g) is None


def test_loader_prefix_for_macos(prov):
    folder = "/Users/u/CMETA/repos/local/cache/task--program--p/tmp"
    prefix = prov.loader_prefix("darwin", folder)
    assert prefix == "DYLD_PRINT_LIBRARIES=1 DYLD_PRINT_TO_FILE=" + os.path.join(folder, "tmp-cmeta-dyld.log") + " "
    spaced = "/Users/u/My Dir/tmp"
    assert prov.loader_prefix("darwin", spaced) == 'DYLD_PRINT_LIBRARIES=1 DYLD_PRINT_TO_FILE="' + os.path.join(spaced, "tmp-cmeta-dyld.log") + '" '
    assert prov.loader_prefix("windows", "/x") == ""
    src = driver_source()
    assert "ctx_tasks.setdefault('use', {}).setdefault('setup-run', {})['prefix_cmd']" in src   # macOS: the command line
    assert "ctx_tasks['local'].setdefault('run_time_env', {}).update(provenance.loader_env(uname, target_path))" in src  # Linux: the environment


def test_macos_names_and_system_folders(prov, tmp_path):
    deps = [dep("/usr/lib/libSystem.B.dylib", "/usr/lib/libSystem.B.dylib", True, "system"),
            dep("/usr/lib/libRosetta.dylib", "/usr/lib/libRosetta.dylib", False, "system"),
            dep("/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib", "/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib", False, "absolute")]
    r = record(prov, fake_inspector(deps, fmt = "macho"), uname = "darwin", target = tmp_path)
    by_name = {l["name"]: l for l in r["loaded"]["libraries"]}
    assert set(by_name) == {"libSystem.B.dylib", "libRosetta.dylib", "libcrypto.3.dylib"}   # basenames, not install paths
    assert by_name["libRosetta.dylib"]["system"] is True                                    # /usr/lib is Apple's
    assert by_name["libcrypto.3.dylib"]["system"] is False


# ---------------------------------------------------------------------- a compiler's runtime belongs to the compiler

def probe_table(table):
    """A stand-in for -print-file-name: (compiler path, file name) -> the compiler's answer; the questions are recorded."""
    calls = []

    def probe(compiler, filename):
        calls.append((compiler, filename))
        return table.get((compiler, filename))

    probe.calls = calls
    return probe


def lib(name, path, system = False, tool = None):
    return {"name": name, "path": path, "system": system, "tool": tool}


def test_runtime_library_names_per_family(prov):
    families = {n: [f for f, rx in prov.RUNTIME_LIBRARIES.items() if rx.match(prov.library_key(n))] for n in (
        "libgomp.so.1", "libgomp-1.dll", "libgomp.1.dylib", "libgcc_s_seh-1.dll", "libstdc++-6.dll", "libasan.so.8",
        "libomp.so.5", "libomp.dylib", "libc++_shared.so", "libclang_rt.asan-x86_64.so", "libiomp5.so", "libsycl.so.8",
        "VCOMP140.DLL", "msvcp140_atomic_wait.dll", "libcrypto.so.3", "libunwind.so.8", "libatlas.so.3", "libz.so.1")}
    assert families["libgomp.so.1"] == families["libgomp-1.dll"] == families["libgomp.1.dylib"] == ["gnu"]
    assert families["libgcc_s_seh-1.dll"] == families["libstdc++-6.dll"] == families["libasan.so.8"] == ["gnu"]
    assert families["libomp.so.5"] == families["libomp.dylib"] == families["libc++_shared.so"] == families["libclang_rt.asan-x86_64.so"] == ["llvm"]
    assert families["libiomp5.so"] == families["libsycl.so.8"] == ["intel"]
    assert families["VCOMP140.DLL"] == families["msvcp140_atomic_wait.dll"] == ["msvc"]
    assert families["libcrypto.so.3"] == families["libunwind.so.8"] == families["libatlas.so.3"] == families["libz.so.1"] == []


def test_compiler_family_and_root(prov):
    assert prov.compiler_family({"tool": {"name": "gcc"}, "path": "/usr/bin/gcc"}, "compiler-c") == "gnu"
    assert prov.compiler_family({"path": "/usr/bin/x86_64-linux-gnu-gcc-15"}) == "gnu"
    assert prov.compiler_family({"path": "/home/u/.local/share/swiftly/bin/clang"}) == "llvm"
    assert prov.compiler_family({"path": "/opt/android-ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang++"}) == "llvm"
    assert prov.compiler_family({"tool": {"name": "msvc"}, "path": r"D:\VS\VC\Tools\MSVC\14.50\bin\HostX64\x64\cl.exe"}) == "msvc"
    assert prov.compiler_family({"path": "/opt/intel/oneapi/compiler/latest/bin/icx"}) == "intel"
    assert prov.compiler_family({"path": "/usr/local/cuda/bin/nvcc"}, "nvcc") is None               # its host compiler is a tool of its own
    assert prov.compiler_family({"path": "/usr/bin/python3"}, "python") is None
    assert prov.compiler_family({"path": "/usr"}, "lib-openssl") is None
    assert prov.compiler_root({"path": "/usr/bin/gcc"}, "gnu") == "/usr"
    assert prov.compiler_root({"path": "/opt/llvm-21/bin/clang"}, "llvm") == "/opt/llvm-21"
    vs = r"D:\Program Files\Microsoft Visual Studio\18\Community"
    assert prov.compiler_root({"path": vs + r"\VC\Tools\MSVC\14.50.35717\bin\HostX64\x64\cl.exe"}, "msvc").lower() == vs.lower()
    assert prov.compiler_root({"path": vs + r"\VC\Auxiliary\Build\vcvars64.bat"}, "msvc").lower() == vs.lower()
    assert prov.compiler_root({"path": r"C:\Program Files\LLVM\bin\clang.exe"}, "llvm").lower() == r"c:\program files\llvm"
    # a folder of the compiler's own, as against the system folders every package shares
    assert prov.dedicated_root("/opt/llvm-21", "linux") and prov.dedicated_root("/usr/lib/llvm-21", "linux")
    assert prov.dedicated_root("/opt/homebrew/Cellar/gcc/15.2.0", "darwin") and not prov.dedicated_root("/opt/homebrew", "darwin")
    assert not prov.dedicated_root("/usr", "linux") and not prov.dedicated_root("/usr/local", "linux") and not prov.dedicated_root("/", "linux")
    assert prov.dedicated_root(r"C:\Program Files\LLVM", "windows") and prov.dedicated_root(vs, "windows")
    assert not prov.dedicated_root(r"C:\Program Files", "windows") and not prov.dedicated_root(r"C:\Windows\System32", "windows")


def test_runtime_library_is_attributed_by_the_compilers_answer(prov):
    g = ctx_global()
    g["gcc"] = dict(g["compiler-c"])                            # task/compiler keeps the compiler under its own name too
    libs = [lib("libgomp.so.1", "/usr/lib/x86_64-linux-gnu/libgomp.so.1"),
            lib("libcrypto.so.3", "/usr/lib/x86_64-linux-gnu/libcrypto.so.3", tool = "lib-openssl"),
            lib("libc.so.6", "/lib/x86_64-linux-gnu/libc.so.6", system = True)]
    probe = probe_table({("/usr/bin/gcc", "libgomp.so.1"): "/usr/lib/gcc/x86_64-linux-gnu/14/../../../x86_64-linux-gnu/libgomp.so.1"})
    assert prov.attribute_runtime(libs, g, "linux", probe = probe) == 1
    assert libs[0]["tool"] == "gcc" and libs[0]["role"] == "runtime"         # the compiler tool, not the role key compiler-c
    assert "role" not in libs[1] and libs[2]["tool"] is None                  # claimed by a tool, or the OS's: never asked
    assert probe.calls == [("/usr/bin/gcc", "libgomp.so.1")]                  # one question, for the one candidate


def test_runtime_names_are_per_family_and_another_answer_is_no_claim(prov):
    g = ctx_global()                                                            # gcc only
    libs = [lib("libomp.so.5", "/usr/lib/x86_64-linux-gnu/libomp.so.5"),       # LLVM's runtime, not GCC's
            lib("libgomp.so.1", "/opt/other/lib/libgomp.so.1"),                 # a libgomp from somewhere else
            lib("libstdc++.so.6", "/usr/lib/x86_64-linux-gnu/libstdc++.so.6")]  # the compiler has no answer
    probe = probe_table({("/usr/bin/gcc", "libgomp.so.1"): "/usr/lib/x86_64-linux-gnu/libgomp.so.1"})
    assert prov.attribute_runtime(libs, g, "linux", probe = probe) == 0
    assert all(l["tool"] is None and "role" not in l for l in libs)
    assert ("/usr/bin/gcc", "libomp.so.5") not in probe.calls                  # not GCC's family: never asked
    assert ("/usr/bin/gcc", "libgomp.so.1") in probe.calls and ("/usr/bin/gcc", "libstdc++.so.6") in probe.calls


def test_runtime_library_in_the_compilers_own_folder(prov):
    # a compiler installed in a folder of its own owns the runtime-named libraries under it, without an answer
    g = ctx_global()
    g["compiler-c"] = {"tool": {"name": "clang"}, "version": "21.1.0", "path": "/opt/llvm-21/bin/clang", "features": {}}
    libs = [lib("libomp.so.5", "/opt/llvm-21/lib/libomp.so.5"), lib("libz.so.1", "/opt/llvm-21/lib/libz.so.1")]
    assert prov.attribute_runtime(libs, g, "linux", probe = probe_table({})) == 1
    assert libs[0]["tool"] == "compiler-c" and libs[0]["role"] == "runtime"
    assert libs[1]["tool"] is None                                              # not a runtime name
    # a compiler in a shared system folder owns nothing by place: /usr is everybody's
    libs2 = [lib("libgomp.so.1", "/usr/lib/x86_64-linux-gnu/libgomp.so.1")]
    assert prov.attribute_runtime(libs2, ctx_global(), "linux", probe = probe_table({})) == 0 and libs2[0]["tool"] is None


def test_msvc_runtime_by_name_and_place(prov, monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\WINDOWS")
    g = ctx_global(uname = "windows")
    vs = r"D:\VS\18\Community"
    g["compiler-c"] = {"tool": {"name": "msvc"}, "version": "19.50.35726", "path": vs + r"\VC\Tools\MSVC\14.50.35717\bin\HostX64\x64\cl.exe", "features": {}}
    g["msvc"] = dict(g["compiler-c"])
    g["microsoft-visual-studio"] = {"tool": {"name": "microsoft-visual-studio"}, "version": "19.50.35726",
                                    "path": vs + r"\VC\Auxiliary\Build\vcvars64.bat", "features": {}}
    libs = [lib("VCOMP140.DLL", r"C:\WINDOWS\System32\VCOMP140.DLL"),
            lib("vcomp140.dll", vs + r"\VC\Redist\MSVC\14.50.35710\x64\Microsoft.VC143.OpenMP\vcomp140.dll"),
            lib("vcomp140.dll", r"C:\other\vcomp140.dll"),
            lib("KERNEL32.dll", r"C:\WINDOWS\System32\KERNEL32.dll", system = True)]
    probe = probe_table({})
    assert prov.attribute_runtime(libs, g, "windows", probe = probe) == 2
    assert libs[0]["tool"] == "msvc" and libs[0]["role"] == "runtime"           # the redistributable copy in System32
    assert libs[1]["tool"] == "msvc"                                            # the copy in the installation
    assert libs[2]["tool"] is None and libs[3]["tool"] is None
    assert probe.calls == []                                                    # MSVC is never asked
    assert [c[0] for c in prov.compiler_tools(g)] == ["msvc", "microsoft-visual-studio"]   # one per binary, the compiler first


def test_record_attributes_the_runtime_and_the_static_check_still_sees_it(prov, tmp_path, monkeypatch):
    monkeypatch.setattr(prov, "print_file_name",
                        lambda compiler, filename, timeout = 15: "/usr/lib/x86_64-linux-gnu/libgomp.so.1" if filename == "libgomp.so.1" else None)
    deps = SYSTEM_DEPS + [dep("libgomp.so.1", "/usr/lib/x86_64-linux-gnu/libgomp.so.1")]
    r = record(prov, fake_inspector(deps), target = tmp_path)
    gomp = next(l for l in r["loaded"]["libraries"] if l["name"] == "libgomp.so.1")
    assert gomp["tool"] == "compiler-c" and gomp["role"] == "runtime" and r["ok"] is True
    # requested static: the runtime library is the compiler's and still a violation
    r = record(prov, fake_inspector(deps), compile_static = True, requested_static = True, target = tmp_path)
    static = check(r, "static")
    assert static and static[0]["ok"] is False and "libgomp.so.1" in static[0]["detail"] and r["ok"] is False
    # the loader log's libraries get the same treatment
    folder = tmp_path / "logged"
    folder.mkdir()
    (folder / (prov.LD_DEBUG_FILE + ".4242")).write_text("      4242:     calling init: /usr/lib/x86_64-linux-gnu/libgomp.so.1\n"
                                                         "      4242:     calling init: /lib/x86_64-linux-gnu/libc.so.6\n", encoding = "utf-8")
    r = record(prov, fake_inspector(SYSTEM_DEPS), mode = "loaded", target = folder)
    gomp = next(l for l in r["loaded"]["libraries"] if l["name"] == "libgomp.so.1")
    assert r["loaded"]["method"] == "loader-log" and gomp["tool"] == "compiler-c" and gomp["role"] == "runtime"


def test_a_tool_resolved_to_a_library_file_names_it(prov):
    assert prov.tool_library_keys({"path": "/x/content/lib/libomp.so", "features": {}}, "lib-openmp") == ["omp"]
    assert prov.tool_library_keys({"path": "/opt/homebrew/opt/libomp/lib/libomp.dylib", "features": {}}, "lib-openmp") == ["omp"]
    assert prov.tool_library_keys({"path": "/usr/include/openssl/opensslv.h", "features": {"lib_names": ["ssl", "crypto"]}}, "lib-openssl") == ["ssl", "crypto"]
    assert prov.tool_library_keys({"path": "/usr/bin/gcc", "features": {}}, "gcc") == []
    assert prov._is_library_file("libomp.so.5") and prov._is_library_file("omp.lib") and prov._is_library_file("libgomp.a")
    assert not prov._is_library_file("gcc") and not prov._is_library_file("cl.exe") and not prov._is_library_file(".so")


# ---------------------------------------------------------------------------------------------- wheels

def make_site_packages(root, posix = True):
    """A program venv with the distributions of an ONNX Runtime CUDA install: files from RECORD, requirements from METADATA."""
    venv = root / "venv-cuda" / ".venv"
    sp = venv / ("lib/python3.14/site-packages" if posix else "Lib/site-packages")
    dists = {
        "onnxruntime_gpu-1.30.0": ("onnxruntime-gpu",
                                   ["numpy>=1.21.6", "packaging", 'nvidia-cuda-runtime~=13.0; extra == "cuda"', 'nvidia-cudnn-cu13; extra == "cudnn"'],
                                   ["onnxruntime/capi/libonnxruntime_providers_cuda.so", "onnxruntime/capi/libonnxruntime.so.1.30.0"]),
        "nvidia_cudnn_cu13-9.27.0.42": ("nvidia-cudnn-cu13", ["nvidia-cublas"], ["nvidia/cudnn/lib/libcudnn.so.9"]),
        "nvidia_cublas-13.8.1.7": ("nvidia-cublas", ["nvidia-cuda-nvrtc"], ["nvidia/cu13/lib/libcublas.so.13"]),
        "nvidia_cuda_nvrtc-13.4.92": ("nvidia-cuda-nvrtc", [], ["nvidia/cu13/lib/libnvrtc.so.13"]),
        "nvidia_cuda_runtime-13.4.92": ("nvidia-cuda-runtime", [], ["nvidia/cu13/lib/libcudart.so.13"]),
        "numpy-2.5.3": ("numpy", [], ["numpy/_core/_multiarray_umath.cpython-314-x86_64-linux-gnu.so", "numpy.libs/libscipy_openblas64_-f48b354e.so"]),
        "packaging-26.3": ("packaging", [], ["packaging/__init__.py"]),
        "lonely-1.0": ("lonely", [], ["lonely/liblonely.so"]),
    }
    for folder, (name, reqs, files) in dists.items():
        d = sp / (folder + ".dist-info")
        d.mkdir(parents = True)
        version = folder.rsplit("-", 1)[1]
        (d / "METADATA").write_text("Metadata-Version: 2.1\nName: %s\nVersion: %s\n%s\nSummary: x\n\nthe long description\nRequires-Dist: not-a-header\n"
                                    % (name, version, "\n".join("Requires-Dist: " + r for r in reqs)), encoding = "utf-8")
        (d / "RECORD").write_text("".join("%s,sha256=abc,123\n" % f for f in files) + "%s/RECORD,,\n" % d.name, encoding = "utf-8")
        for f in files:
            p = sp / f
            p.parent.mkdir(parents = True, exist_ok = True)
            p.write_bytes(b"\x7fELF")
    return venv, sp


def test_wheel_library_is_attributed_to_the_pip_tool_that_pulled_its_distribution(prov, tmp_path):
    venv, sp = make_site_packages(tmp_path)
    py = str(venv / "bin" / "python")
    g = ctx_global(cuda = True)
    g["python"] = {"version": "3.14.7", "path": py}
    g["pip-onnxruntime"] = {"version": "1.30.0", "path": py,
                            "_params": {"name": "pip", "with": {"package": "onnxruntime-gpu", "extras": ["cuda", "cudnn"]}}}
    g["pip-numpy"] = {"version": "2.5.3", "path": py, "_params": {"name": "pip", "with": {"package": "numpy"}}}
    s = str(sp)
    # the package's own file; a dependency one step away (through an extra), two and three steps away
    assert prov.attribute(s + "/onnxruntime/capi/libonnxruntime_providers_cuda.so", g) == "pip-onnxruntime"
    assert prov.attribute(s + "/nvidia/cu13/lib/libcudart.so.13", g) == "pip-onnxruntime"
    assert prov.attribute(s + "/nvidia/cudnn/lib/libcudnn.so.9", g) == "pip-onnxruntime"
    assert prov.attribute(s + "/nvidia/cu13/lib/libcublas.so.13", g) == "pip-onnxruntime"
    assert prov.attribute(s + "/nvidia/cu13/lib/libnvrtc.so.13", g) == "pip-onnxruntime"
    # numpy is required by onnxruntime-gpu too, but pip-numpy installed it: the nearest tool wins
    assert prov.attribute(s + "/numpy/_core/_multiarray_umath.cpython-314-x86_64-linux-gnu.so", g) == "pip-numpy"
    # the loader reports a path with .. in it (numpy/_core/../../numpy.libs/...): still numpy's
    assert prov.attribute(s + "/numpy/_core/../../numpy.libs/libscipy_openblas64_-f48b354e.so", g) == "pip-numpy"
    # a distribution no tool of the run pulled stays unattributed, and so does a file no RECORD lists
    assert prov.attribute(s + "/lonely/liblonely.so", g) is None
    assert prov.attribute(s + "/nvidia/cudnn/lib/libcudnn_extra.so.9", g) is None
    # the record names the distribution; a library outside any site-packages has none
    entries = prov.library_entries([s + "/nvidia/cudnn/lib/libcudnn.so.9", "/lib/x86_64-linux-gnu/libc.so.6"], g, "linux")
    assert entries[0]["tool"] == "pip-onnxruntime" and entries[0]["dist"] == "nvidia-cudnn-cu13"
    assert entries[1]["tool"] is None and "dist" not in entries[1]


def test_nvidia_driver_libraries_belong_to_the_cuda_entry_of_the_run(prov):
    g = ctx_global(cuda = True)         # has the "cuda" entry: the driver and the GPU of the target
    for p in ("/usr/lib/x86_64-linux-gnu/libcuda.so.1", "/usr/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.1",
              "/usr/lib/x86_64-linux-gnu/libnvidia-nvvm70.so.4", "C:\\Windows\\System32\\nvcuda.dll"):
        assert prov.attribute(p, g) == "cuda", p
    assert prov.attribute("/usr/lib/x86_64-linux-gnu/libcudart.so.13", g) is None       # the toolkit's, not the driver's
    entries = prov.library_entries(["/usr/lib/x86_64-linux-gnu/libcuda.so.1"], g, "linux")
    assert entries[0]["tool"] == "cuda" and entries[0]["role"] == "driver"
    g_cpu = ctx_global()                # no cuda entry: nothing to attribute the driver to
    assert prov.attribute("/usr/lib/x86_64-linux-gnu/libcuda.so.1", g_cpu) is None


def test_wheel_rule_keeps_to_the_tools_own_venv_and_falls_back_to_the_key(prov, tmp_path):
    venv, sp = make_site_packages(tmp_path)
    other_venv, other_sp = make_site_packages(tmp_path / "other")
    g = ctx_global()
    # a pip tool that installed into ANOTHER venv does not claim this venv's files
    g["pip-onnxruntime"] = {"version": "1.30.0", "path": str(other_venv / "bin" / "python"), "_params": {"with": {"package": "onnxruntime-gpu"}}}
    assert prov.attribute(str(sp / "onnxruntime" / "capi" / "libonnxruntime.so.1.30.0"), g) is None
    assert prov.attribute(str(other_sp / "onnxruntime" / "capi" / "libonnxruntime.so.1.30.0"), g) == "pip-onnxruntime"
    # an older entry without _params: the key names the package (pip-numpy -> numpy); the Windows venv layout too
    venv_w, sp_w = make_site_packages(tmp_path / "win", posix = False)
    g = ctx_global("windows")
    g["pip-numpy"] = {"version": "2.5.3", "path": str(venv_w / "Scripts" / "python.exe")}
    assert prov.attribute(str(sp_w / "numpy.libs" / "libscipy_openblas64_-f48b354e.so"), g) == "pip-numpy"
    assert prov.site_packages_of(str(sp_w / "numpy" / "x.pyd")) == str(sp_w)
    assert prov.site_packages_of("/usr/lib/x86_64-linux-gnu/libz.so.1") is None
    assert prov.norm_dist("Nvidia_CUDNN.cu13") == "nvidia-cudnn-cu13"
    # the header block of METADATA ends at the first empty line: the Requires-Dist in the description is not read
    idx = prov.dist_index(str(sp_w))
    assert "not-a-header" not in idx["requires"]["onnxruntime-gpu"] and idx["versions"]["numpy"] == "2.5.3"


def test_framework_versions_from_the_venv(prov, tmp_path):
    venv, sp = make_site_packages(tmp_path)
    # a torch wheel built for CUDA 13.0, installed but nothing of it loaded in this run
    d = sp / "torch-2.14.1+cu130.dist-info"
    d.mkdir()
    (d / "METADATA").write_text("Name: torch\nVersion: 2.14.1+cu130\nRequires-Dist: nvidia-cuda-runtime\n\n", encoding = "utf-8")
    (d / "RECORD").write_text("torch/lib/libtorch_cuda.so,,\n", encoding = "utf-8")
    py = str(venv / "bin" / "python")
    g = ctx_global(cuda = True)
    g["pip-onnxruntime"] = {"version": "1.30.0", "path": py, "_params": {"with": {"package": "onnxruntime-gpu"}}}
    g["pip-torch"] = {"version": "2.14.1+cu130", "path": py, "_params": {"with": {"package": "torch"}}}
    libs = prov.library_entries([str(sp / "nvidia/cu13/lib/libcudart.so.13"), str(sp / "nvidia/cudnn/lib/libcudnn.so.9"),
                                 "/lib/x86_64-linux-gnu/libc.so.6"], g, "linux")
    fw = prov.framework_versions(libs, g)
    assert fw["nvidia-cuda-runtime"] == {"version": "13.4.92", "loaded": True, "tool": "pip-onnxruntime"}
    assert fw["nvidia-cudnn-cu13"]["version"] == "9.27.0.42" and fw["nvidia-cudnn-cu13"]["loaded"]
    assert fw["onnxruntime-gpu"] == {"version": "1.30.0", "loaded": False, "tool": "pip-onnxruntime"}
    assert fw["torch"]["version"] == "2.14.1+cu130" and fw["torch"]["cuda_build"] == "13.0" and not fw["torch"]["loaded"]
    assert prov.cuda_build_of("2.9.0+cu128") == "12.8" and prov.cuda_build_of("1.30.0") is None
    # a requested CUDA version cannot apply to the wheel's runtime: an error naming the wheel and the tool
    rec = {"requested": {"use": {"nvcc": {"version": "12.9"}}}, "compute": ["cuda"], "host": {"uname": "linux"},
           "loaded": {"method": "loader-log", "libraries": libs}, "build": {"binary": {"format": "elf"}},
           "runtime": {"frameworks": fw}, "resolved": {}}
    prov.run_checks(rec, g, False)
    wheel = [c for c in rec["checks"] if c["rule"] == "wheel"]
    assert len(wheel) == 1 and wheel[0]["level"] == "error" and wheel[0]["ok"] is False
    assert "nvidia-cuda-runtime 13.4.92" in wheel[0]["detail"] and "pip-onnxruntime" in wheel[0]["detail"] and rec["ok"] is False
    info = [c["detail"] for c in rec["checks"] if c["rule"] == "info" and c["detail"].startswith("frameworks:")][0]
    assert "torch 2.14.1+cu130 (built for CUDA 13.0) (installed, nothing of it loaded)" in info
    # without an explicit CUDA request there is nothing to flag
    rec["requested"] = {"use": {}}
    prov.run_checks(rec, g, False)
    assert not [c for c in rec["checks"] if c["rule"] == "wheel"] and rec["ok"] is True


def go_binary(path, version = b"go1.26.2", inline = True):
    """A file that carries a Go buildinfo header: magic, pointer size, flags (2 = the version inline), then the varint-prefixed version."""
    head = prov_magic = b"\xff Go buildinf:" + bytes([8, 2 if inline else 0]) + b"\x00" * 16
    body = bytes([len(version)]) + version if inline else b"\x00" * 40 + version
    path.write_bytes(b"MZ" + b"\x00" * 100 + head + body + b"\x00" * 50)
    return str(path)


def test_go_and_rust_toolchains_are_read_from_the_binary(prov, tmp_path):
    exe = go_binary(tmp_path / "program")
    assert prov.go_version_in_binary(exe) == "1.26.2"
    assert prov.go_version_in_binary(go_binary(tmp_path / "old", b"go1.17.3", inline = False)) == "1.17.3"
    (tmp_path / "plain").write_bytes(b"\x7fELF" + b"\x00" * 64)
    assert prov.go_version_in_binary(str(tmp_path / "plain")) is None
    rust = tmp_path / "rust-elf"
    rust.write_bytes(b"\x7fELF\x00rustc version 1.90.0 (1159e78c4 2025-09-14)\x00/rustc/1159e78c47b8b3a2e5c6d7e8f9a0b1c2d3e4f5a6/library/std/src/panic.rs\x00")
    assert prov.rust_version_in_binary(str(rust)) == ("1.90.0", "1159e78c4")
    rust_pe = tmp_path / "rust-pe"
    rust_pe.write_bytes(b"MZ\x00/rustc/1159e78c47b8b3a2e5c6d7e8f9a0b1c2d3e4f5a6/library/std/src/panic.rs\x00")
    assert prov.rust_version_in_binary(str(rust_pe)) == (None, "1159e78c47b8b3a2e5c6d7e8f9a0b1c2d3e4f5a6")

    g = ctx_global()
    # an Android build: the NDK's clang is not Go, however its name starts
    g["compiler-c"] = {"tool": {"name": "google.android-ndk.clang"}, "version": "21.0.0", "path": "/ndk/clang"}
    assert prov.toolchain_in_binary(exe, g) == {}
    g["compiler-go"] = {"tool": {"name": "go"}, "version": "1.26.2", "path": "/opt/go/bin/go"}
    tc = prov.toolchain_in_binary(exe, g)
    assert tc == {"go": {"tool": "compiler-go", "resolved": "1.26.2", "binary": "1.26.2", "source": "go buildinfo"}}
    g["compiler-go"] = {"tool": {"name": "go-android"}, "version": "1.26.2", "path": "/opt/go/bin/go"}
    assert prov.toolchain_in_binary(exe, g)["go"]["binary"] == "1.26.2"
    g["compiler-rust"] = {"tool": {"name": "rustc"}, "version": "1.90.0", "path": "/opt/rust/bin/rustc"}
    tc = prov.toolchain_in_binary(str(rust_pe), g, rustc_probe = lambda p: "1159e78c47b8b3a2e5c6d7e8f9a0b1c2d3e4f5a6")
    assert tc["rust"]["binary_commit"].startswith("1159e78c4") and tc["rust"]["resolved_commit"].startswith("1159e78c4")

    # the checks: the same toolchain is info; another one a warning, or an error when its version was requested
    def checks_for(toolchain, use = None):
        rec = {"requested": {"use": use or {}}, "compute": ["cpu"], "host": {"uname": "linux"}, "loaded": {"method": "resolved", "libraries": []},
               "build": {"binary": {"format": "elf"}, "toolchain": toolchain}, "runtime": {}, "resolved": {}}
        prov.run_checks(rec, g, False)
        return [c for c in rec["checks"] if c["rule"] == "toolchain"], rec["ok"]
    cs, ok = checks_for({"go": {"tool": "compiler-go", "resolved": "1.26.2", "binary": "1.26.2"}})
    assert cs[0]["level"] == "info" and cs[0]["ok"] is True and ok
    cs, ok = checks_for({"go": {"tool": "compiler-go", "resolved": "1.26.2", "binary": "1.27.0"}})
    assert cs[0]["level"] == "warning" and cs[0]["ok"] is False and ok and "another toolchain built it" in cs[0]["detail"]
    cs, ok = checks_for({"go": {"tool": "compiler-go", "resolved": "1.26.2", "binary": "1.27.0"}}, use = {"go": {"version": "1.26"}})
    assert cs[0]["level"] == "error" and not ok
    cs, ok = checks_for({"rust": {"tool": "compiler-rust", "resolved": "1.90.0", "binary": None, "binary_commit": "abc1234567890abcdef", "resolved_commit": "abc1234567890abcdef"}})
    assert cs[0]["level"] == "info" and cs[0]["ok"] is True
    cs, ok = checks_for({"rust": {"tool": "compiler-rust", "resolved": "1.90.0", "binary": None, "binary_commit": "abc1234567890abcdef", "resolved_commit": "fff1234567890abcdef"}})
    assert cs[0]["level"] == "warning" and cs[0]["ok"] is False
    cs, ok = checks_for({"rust": {"tool": "compiler-rust", "resolved": "1.90.0", "binary": None, "binary_commit": None}})
    assert cs[0]["level"] == "info" and cs[0]["ok"] is None and "does not say" in cs[0]["detail"]
    # the record of a Go run carries build.toolchain
    local = {"target_path_exe": exe}
    r = record(prov, fake_inspector(SYSTEM_DEPS), local = local, target = str(tmp_path))
    assert r["build"]["toolchain"]["go"]["binary"] == "1.26.2" if "compiler-go" in ctx_global() else True


def test_python_environment_kinds(prov, tmp_path):
    # a uv-managed interpreter, and a venv uv made on it
    uvpy = tmp_path / "share" / "uv" / "python" / "cpython-3.14.7-linux-x86_64-gnu"
    (uvpy / "bin").mkdir(parents = True)
    (uvpy / "bin" / "python3").write_bytes(b"")
    venv = tmp_path / "proj" / ".venv"
    (venv / "bin").mkdir(parents = True)
    (venv / "bin" / "python").write_bytes(b"")
    (venv / "pyvenv.cfg").write_text(f"home = {uvpy / 'bin'}\nimplementation = CPython\nuv = 0.12.21\nversion_info = 3.14.7\n", encoding = "utf-8")
    e = prov.python_environment(str(venv / "bin" / "python"))
    assert e["kind"] == "venv" and e["made_by"] == "uv 0.12.21" and e["base"]["kind"] == "uv-managed"
    assert prov.python_environment_text(e) == "venv made by uv 0.12.21 on a uv-managed Python"
    assert prov.python_environment(str(uvpy / "bin" / "python3"))["kind"] == "uv-managed"
    # a conda base (conda-meta/ with condabin/, pkgs/ or envs/ next to it) and a conda environment, POSIX and
    # Windows layouts; an environment made anywhere with "conda create -p" (no such folders) is an environment
    conda = tmp_path / "miniconda3"
    (conda / "conda-meta").mkdir(parents = True)
    (conda / "condabin").mkdir()
    (conda / "bin").mkdir()
    made = tmp_path / "entry" / ".conda-env"
    (made / "conda-meta").mkdir(parents = True)
    (made / "bin").mkdir()
    (made / "bin" / "python").write_bytes(b"")
    assert prov.python_environment(str(made / "bin" / "python"))["kind"] == "conda-env"
    (conda / "bin" / "python").write_bytes(b"")
    e = prov.python_environment(str(conda / "bin" / "python"))
    assert e["kind"] == "conda" and "name" not in e and prov.python_environment_text(e) == "a conda base environment"
    env = conda / "envs" / "myenv"
    (env / "conda-meta").mkdir(parents = True)
    (env / "python.exe").write_bytes(b"")
    e = prov.python_environment(str(env / "python.exe"))
    assert e["kind"] == "conda-env" and e["name"] == "myenv" and "myenv" in prov.python_environment_text(e)
    # a venv made on a conda environment: the base is named
    v2 = tmp_path / "v2"
    (v2 / "Scripts").mkdir(parents = True)
    (v2 / "Scripts" / "python.exe").write_bytes(b"")
    (v2 / "pyvenv.cfg").write_text(f"home = {env}\nversion = 3.13.9\n", encoding = "utf-8")
    e = prov.python_environment(str(v2 / "Scripts" / "python.exe"))
    assert e["kind"] == "venv" and e["base"] == {"kind": "conda-env", "prefix": str(env), "name": "myenv"} and "made_by" not in e
    assert prov.python_environment_text(e) == "venv on the conda environment myenv"
    # the system's
    usr = tmp_path / "usr" / "bin"
    usr.mkdir(parents = True)
    (usr / "python3").write_bytes(b"")
    assert prov.python_environment(str(usr / "python3"))["kind"] == "system"
    assert prov.python_environment("") == {}
    # the record carries it, and the checks say it in one line
    g = ctx_global(python = True)
    g["python"]["path"] = str(venv / "bin" / "python")
    r = prov.build_record("on", {"alias": "p", "uid": "0" * 16}, "tmp", str(tmp_path), ["cpu"], g, {"target_path_exe": str(tmp_path / "x")}, {}, {}, False)
    assert r["runtime"]["python"]["environment"]["kind"] == "venv"
    assert any(c["detail"] == "python 3.12.3: venv made by uv 0.12.21 on a uv-managed Python" for c in r["checks"])
    # an interpreter requested with --use.python.tool_path: the run used it, a venv made on it, or something else (error)
    def py_check(use_path, g_path):
        g["python"]["path"] = g_path
        rr = prov.build_record("on", {"alias": "p", "uid": "0" * 16}, "tmp", str(tmp_path), ["cpu"], g, {"target_path_exe": str(tmp_path / "x")},
                               {}, {"python": {"tool_path": use_path}}, False)
        return [c for c in rr["checks"] if c["rule"] == "python"][0], rr["ok"]
    c, ok = py_check(str(conda / "bin" / "python"), str(conda / "bin" / "python"))
    assert c["ok"] is True and ok and "the run used it" in c["detail"]
    c, ok = py_check(str(env / "python.exe"), str(v2 / "Scripts" / "python.exe"))              # a venv made on the requested conda env
    assert c["ok"] is True and ok and "through a venv made on it" in c["detail"]
    c, ok = py_check(str(conda / "bin" / "python"), str(venv / "bin" / "python"))              # a venv on another base: not honoured
    assert c["ok"] is False and not ok and "instead" in c["detail"] and "uv-managed" in c["detail"]


def test_runtime_rule_yields_to_the_tool_that_names_the_library(prov, tmp_path):
    # the build linked lib-openmp's libomp.so, the process loaded the system's libomp.so.5 (another soname): not
    # the compiler's runtime - the tool's library came from elsewhere, which the origin check reports
    g = ctx_global()
    g["compiler-c"] = {"tool": {"name": "clang"}, "version": "22.1.7", "path": "/opt/llvm/bin/clang", "features": {}}
    g["lib-openmp"] = {"version": "default", "path": "/opt/llvm/lib/libomp.so", "path_cmeta_cache": "/opt/llvm",
                       "features": {"paths": {"dynamic_lib": "/opt/llvm/lib"}}}
    libs = [lib("libomp.so.5", "/usr/lib/x86_64-linux-gnu/libomp.so.5")]
    probe = probe_table({("/opt/llvm/bin/clang", "libomp.so.5"): "/usr/lib/x86_64-linux-gnu/libomp.so.5"})   # clang would say yes
    assert prov.attribute_runtime(libs, g, "linux", probe = probe) == 0 and libs[0]["tool"] is None and probe.calls == []
    prov.binary_deps = fake_inspector(SYSTEM_DEPS + [dep("libomp.so.5", "/usr/lib/x86_64-linux-gnu/libomp.so.5")])
    r = prov.build_record("on", {"alias": "prog", "uid": "0" * 16}, "tmp", str(tmp_path), ["cpu"], g,
                          {"target_path_exe": str(tmp_path / "program")}, {"name": "prog"}, {}, False)
    origin = [c for c in r["checks"] if c["rule"] == "origin" and c.get("tool") == "lib-openmp"]
    assert origin and origin[0]["ok"] is False and origin[0]["level"] == "warning"
    assert "libomp.so.5 comes from /usr/lib/x86_64-linux-gnu/libomp.so.5, not from the resolved lib-openmp" in origin[0]["detail"]
    omp = next(l for l in r["loaded"]["libraries"] if l["name"] == "libomp.so.5")
    assert omp["tool"] is None and "role" not in omp
    # the same library loaded from the tool's own folder is the tool's
    prov.binary_deps = fake_inspector(SYSTEM_DEPS + [dep("libomp.so", "/opt/llvm/lib/libomp.so")])
    r = prov.build_record("on", {"alias": "prog", "uid": "0" * 16}, "tmp", str(tmp_path), ["cpu"], g,
                          {"target_path_exe": str(tmp_path / "program")}, {"name": "prog"}, {}, False)
    omp = next(l for l in r["loaded"]["libraries"] if l["name"] == "libomp.so")
    assert omp["tool"] == "lib-openmp" and all(c["ok"] for c in r["checks"] if c["rule"] == "origin")


def test_runtime_attribution_problem_is_a_note(prov, tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("no compilers today")

    monkeypatch.setattr(prov, "attribute_runtime", broken)
    r = record(prov, fake_inspector(SYSTEM_DEPS + [dep("libgomp.so.1", "/usr/lib/x86_64-linux-gnu/libgomp.so.1")]), target = tmp_path)
    assert "runtime attribution failed: RuntimeError: no compilers today" in r["loaded"]["note"] and r["ok"] is True


def test_mode_from_the_environment(prov):
    assert prov.mode_of(None, env = {}) == "on"
    assert prov.mode_of(None, env = {"CMETA_PROVENANCE": "strict"}) == "strict"
    assert prov.mode_of(None, env = {"CMETA_PROVENANCE": "loaded"}) == "loaded"
    assert prov.mode_of(None, env = {"CMETA_PROVENANCE": ""}) == "on"
    assert prov.mode_of("off", env = {"CMETA_PROVENANCE": "strict"}) == "off"     # the run's own choice wins
    with pytest.raises(ValueError, match = "CMETA_PROVENANCE=sometimes"):
        prov.mode_of(None, env = {"CMETA_PROVENANCE": "sometimes"})
    # inside a test session the default is strict; CMETA_PROVENANCE and the run's own choice still win
    assert prov.mode_of(None, env = {"CMETA_TEST_SESSION": "20261005/0952.prov-runtime"}) == "strict"
    assert prov.mode_of(None, env = {"CMETA_TEST_SESSION": "20261005/0952.prov-runtime", "CMETA_PROVENANCE": "on"}) == "on"
    assert prov.mode_of("loaded", env = {"CMETA_TEST_SESSION": "20261005/0952.prov-runtime"}) == "loaded"
    assert prov.mode_of(None, env = {"CMETA_TEST_SESSION": " "}) == "on"
    assert "provenance.mode_of(params.get('provenance'))" in driver_source()     # the driver passes None when the run names no mode


def test_session_attachment_name_and_note(prov):
    record = {"created": "2026-10-05T07:54:12Z", "program": {"alias": "test-nmm-c-cpu", "target_tmp": "tmp-prov-clang"},
              "compute": ["cpu"], "ok": False,
              "checks": [{"rule": "origin", "level": "warning", "ok": False, "detail": "x"},
                         {"rule": "version", "level": "error", "ok": False, "detail": "y"},
                         {"rule": "info", "level": "info", "ok": True, "detail": "z"}]}
    assert prov.session_attachment_name(record) == "provenance--test-nmm-c-cpu--tmp-prov-clang--075412.json"
    assert prov.session_note(record) == "provenance: test-nmm-c-cpu (tmp-prov-clang) FAILED, 1 failed, 1 warnings; compute cpu"
    bare = prov.session_attachment_name({"program": {"uid": "0123456789abcdef"}})
    assert bare.startswith("provenance--0123456789abcdef--tmp--") and bare.endswith(".json") and len(bare) == len("provenance--0123456789abcdef--tmp--HHMMSS.json")
    assert prov.session_note({"program": {"alias": "p"}, "checks": []}) == "provenance: p (tmp) ok, 0 failed, 0 warnings; compute ?"


def test_hook_attaches_the_record_to_the_test_session(driver, prov, tmp_path, monkeypatch, capsys):
    calls = []

    def access(p):
        calls.append(p)
        return {"return": 0}

    driver.cm.access = access
    monkeypatch.setenv("CMETA_TEST_SESSION", "20261005/0952.prov-runtime")
    prov.binary_deps = fake_inspector(SYSTEM_DEPS)
    ctx = hook_ctx(tmp_path)
    r = driver.write_provenance(ctx, {}, "on", {"name": "prog"}, {}, str(tmp_path), "tmp", "prog", "0" * 16, ["cpu"])
    assert r["return"] == 0 and r["provenance"]["session"] == "20261005/0952.prov-runtime"
    assert len(calls) == 1
    p = calls[0]
    assert p["category"] == "task,c36be4b9314a45e0" and p["arg1"] == "test-session,33b25e8340de4d8e" and p["command"] == "run"
    assert p["id"] == "20261005/0952.prov-runtime" and p["attach"] == os.path.join(str(tmp_path), "provenance.json")
    assert p["attach_as"].startswith("provenance--prog--tmp--") and p["note"].startswith("provenance: prog (tmp) ok, 0 failed")
    assert p["con"] is False
    # the session cannot be reached: a warning, the run's result stands
    driver.cm.access = lambda p: {"return": 1, "error": "no session"}
    r = driver.write_provenance(ctx, {}, "on", {"name": "prog"}, {}, str(tmp_path), "tmp", "prog", "0" * 16, ["cpu"])
    assert r["return"] == 0 and "session" not in r["provenance"]
    assert "WARNING: provenance record not attached to test session 20261005/0952.prov-runtime: no session" in capsys.readouterr().out
    # no session: nothing is called
    monkeypatch.delenv("CMETA_TEST_SESSION")
    calls.clear()
    driver.cm.access = access
    r = driver.write_provenance(ctx, {}, "on", {"name": "prog"}, {}, str(tmp_path), "tmp", "prog", "0" * 16, ["cpu"])
    assert r["return"] == 0 and calls == []
