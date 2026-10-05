"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

`cx program provenance`: the view of a run's provenance record (provenance.json in the build folder) -
the requested / resolved / loaded table with the checks, `--all`, `--as_json`, `--diff` between two
records, `--as_flags`, and the message when a folder has no record. Offline: fixture records; the
command itself runs against a scratch cache entry in the hermetic CMETA_HOME.
"""

import copy
import importlib.util
import json
import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def view():
    path = REPO_ROOT / "category" / "program" / "api" / "provenance_view.py"
    spec = importlib.util.spec_from_file_location("provenance_view_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_ok():
    return {
        "format": 1,
        "created": "2026-10-04T20:11:03Z",
        "program": {"alias": "test-nmm-nvcc-cuda", "uid": "0123456789abcdef", "target_tmp": "tmp-static",
                    "target_path": "/home/u/CMETA/repos/local/cache/task--program--test-nmm-nvcc-cuda/tmp-static"},
        "compute": ["cuda"],
        "host": {"uname": "linux", "uarch": "x86_64", "os_id": "debian"},
        "requested": {"use": {"nvcc": {"version": "13.3"}}, "compile": {"static": True}, "with": {}, "compute": ["cuda"]},
        "resolved": {
            "nvcc": {"name": "nvcc", "version": "13.3.1", "path": "/usr/local/cuda-13.3/bin/nvcc", "entry": "aa11"},
            "compiler-cpp": {"name": "gcc-cpp", "version": "14.2.0", "path": "/usr/bin/g++"},
            "lib-cudnn": {"name": "lib-cudnn", "version": "9.27.0",
                          "path": "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--bb22/content/lib", "entry": "bb22"},
            "lib-openssl": {"name": "lib-openssl", "version": "3.0.13", "path": "/usr"},
            "host": {"os": {"uname": "linux"}},
        },
        "build": {"stamp": {"compute": ["cuda"]},
                  "binary": {"path": ".../tmp-static/program", "format": "elf", "arch": "x86_64", "static": False,
                             "deps": [{"name": "libcudnn.so.9", "path": "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--bb22/content/lib/libcudnn.so.9", "source": "env", "system": False},
                                      {"name": "libc.so.6", "path": "/lib/x86_64-linux-gnu/libc.so.6", "source": "system", "system": True}],
                             "missing": []}},
        "runtime": {"driver": {"cuda": "13.0"}, "gpu": {"name": "RTX A500", "arch": 86}, "python": {"version": "3.12.3", "path": "/usr/bin/python3"}},
        "loaded": {"method": "loader-log", "processes": 1,
                   "libraries": [
                       {"name": "libcudnn.so.9", "path": "/home/u/CMETA/repos/local/cache/task--setup--lib-cudnn--bb22/content/lib/libcudnn.so.9", "system": False, "tool": "lib-cudnn"},
                       {"name": "libc.so.6", "path": "/lib/x86_64-linux-gnu/libc.so.6", "system": True, "tool": None},
                       {"name": "libm.so.6", "path": "/lib/x86_64-linux-gnu/libm.so.6", "system": True, "tool": None},
                       {"name": "libstdc++.so.6", "path": "/lib/x86_64-linux-gnu/libstdc++.so.6", "system": False, "tool": None},
                   ]},
        "checks": [
            {"rule": "static: no shared library beyond the system set", "level": "error", "ok": True, "detail": "libstdc++ allowed on cuda"},
            {"rule": "loaded libcudnn.so.9 comes from the resolved lib-cudnn", "level": "error", "ok": True, "detail": "", "tool": "lib-cudnn"},
            {"rule": "requested nvcc 13.3 resolved", "level": "error", "ok": True, "detail": "13.3.1", "tool": "nvcc"},
        ],
        "ok": True,
    }


def record_failed():
    r = record_ok()
    r["program"]["target_tmp"] = "tmp-old"
    r["created"] = "2026-10-03T09:00:00Z"
    r["resolved"]["nvcc"] = {"name": "nvcc", "version": "12.9.86", "path": "/usr/local/cuda-12.9/bin/nvcc"}
    r["loaded"]["libraries"].append({"name": "libcrypto.so.3", "path": "/lib/x86_64-linux-gnu/libcrypto.so.3", "system": False, "tool": "lib-openssl"})
    r["checks"] = [
        {"rule": "static: no shared library beyond the system set", "level": "error", "ok": False,
         "detail": "libcrypto.so.3 loaded from /lib/x86_64-linux-gnu", "tool": "lib-openssl"},
        {"rule": "loaded libcudnn.so.9 comes from the resolved lib-cudnn", "level": "error", "ok": True, "detail": "", "tool": "lib-cudnn"},
        {"rule": "accelerator used", "level": "warning", "ok": False, "detail": "npu not available, cpu used"},
    ]
    r["ok"] = False
    return r


def record_partial():
    # an older record: no loaded section, no checks, no binary
    return {"format": 1, "created": "2026-09-30T08:00:00Z", "program": {"alias": "old-program", "target_tmp": "tmp"},
            "resolved": {"gcc": {"version": "13.3.0", "path": "/usr/bin/gcc"}}}


# The view functions

def test_render_table_and_checks(view):
    text = view.render(record_ok())
    assert "Provenance of program test-nmm-nvcc-cuda (tmp-static)" in text
    assert "compute: cuda" in text and "host: linux x86_64" in text and "binary: ELF x86_64, dynamic" in text
    assert "result: ok (3 ok, 0 failed, 0 warnings)" in text
    assert "loaded: 4 libraries by the loader log, 1 processes" in text
    lines = text.splitlines()
    nvcc = next(l for l in lines if l.strip().startswith("nvcc "))
    assert "13.3" in nvcc and "13.3.1" in nvcc and "[ok]" in nvcc
    cudnn = next(l for l in lines if l.strip().startswith("lib-cudnn "))
    assert "(auto)" in cudnn and "9.27.0" in cudnn and "libcudnn.so.9" in cudnn and "[ok]" in cudnn
    cpp = next(l for l in lines if l.strip().startswith("compiler-cpp "))
    assert "gcc-cpp 14.2.0" in cpp
    assert "  host" not in [l[:6] for l in lines]            # the host context is not a tool row
    assert "checks:" in text and "ok    static: no shared library beyond the system set" in text
    assert "other libraries: 2 system (libc.so.6, libm.so.6); libstdc++.so.6 (/lib/x86_64-linux-gnu)" in text


def test_render_marks_a_compilers_runtime_library(view):
    # the C++ runtime attributed to the compiler of the run leaves the "other libraries" line and joins the compiler's row
    r = record_ok()
    r["loaded"]["libraries"][3] = dict(r["loaded"]["libraries"][3], tool = "compiler-cpp", role = "runtime")
    text = view.render(r)
    cpp = next(l for l in text.splitlines() if l.strip().startswith("compiler-cpp "))
    assert "gcc-cpp 14.2.0" in cpp and "libstdc++.so.6 (runtime)" in cpp
    assert "other libraries: 2 system (libc.so.6, libm.so.6)" in text and "libstdc++.so.6 (/lib" not in text


def test_render_failed_record(view):
    text = view.render(record_failed())
    assert "result: FAILED (1 ok, 1 failed, 1 warnings)" in text
    openssl = next(l for l in text.splitlines() if l.strip().startswith("lib-openssl "))
    assert "libcrypto.so.3" in openssl and "[FAIL]" in openssl
    assert "FAIL  static: no shared library beyond the system set: libcrypto.so.3 loaded from /lib/x86_64-linux-gnu  (error)" in text
    assert "warn  accelerator used: npu not available, cpu used  (warning)" in text


def test_render_partial_record_does_not_crash(view):
    text = view.render(record_partial())
    assert "Provenance of program old-program (tmp)" in text
    assert "result: ? (0 ok, 0 failed, 0 warnings)" in text
    assert "gcc" in text and "13.3.0" in text and "(none)" in text


def test_summary_line(view):
    line = view.summary_line("tmp-static", record_ok())
    assert line.startswith("  tmp-static") and "2026-10-04T20:11" in line and "cuda" in line
    assert "linux/x86_64" in line and " ok " in line and "checks: 3 ok, 0 failed, 0 warnings" in line
    assert "FAILED" in view.summary_line("tmp-old", record_failed())


def test_diff_finds_the_changes(view):
    d = view.diff(record_failed(), record_ok())
    assert ("nvcc", "version", "12.9.86", "13.3.1") in d["resolved"]
    assert ("nvcc", "path", "/usr/local/cuda-12.9/bin/nvcc", "/usr/local/cuda-13.3/bin/nvcc") in d["resolved"]
    assert d["loaded"]["removed"] == ["/lib/x86_64-linux-gnu/libcrypto.so.3"] and d["loaded"]["added"] == []
    rules = {rule: (a, b) for rule, a, b in d["checks"]}
    assert rules["static: no shared library beyond the system set"] == ("FAIL", "ok")
    assert rules["accelerator used"] == ("warn", None)
    assert rules["requested nvcc 13.3 resolved"] == (None, "ok")
    assert d["requested"] == [] and d["context"] == []
    text = view.render_diff(d, "A", "B")
    assert "nvcc version: 12.9.86 -> 13.3.1" in text and "- /lib/x86_64-linux-gnu/libcrypto.so.3" in text
    assert "static: no shared library beyond the system set: FAIL -> ok" in text
    assert view.diff_is_empty(view.diff(record_ok(), record_ok()))
    assert "none" in view.render_diff(view.diff(record_ok(), record_ok()))


def test_diff_requested_and_context(view):
    a, b = record_ok(), record_ok()
    b["requested"]["compile"]["static"] = False
    b["compute"] = ["cpu"]
    b["host"]["uname"] = "windows"
    d = view.diff(a, b)
    assert ("compile.static", True, False) in d["requested"]
    keys = {k for k, _, _ in d["context"]}
    assert "compute" in keys and "host" in keys


def test_as_flags(view):
    assert view.as_flags(record_ok()) == ("--use.compiler-cpp.name=gcc-cpp --use.lib-cudnn.version=9.27.0 "
                                          "--use.lib-openssl.version=3.0.13 --use.nvcc.version=13.3.1 "
                                          "--compile.static --compute=cuda --target_tmp=tmp-static")
    r = record_ok()
    r["requested"]["with"] = {"any_gpu": True, "cuda_libs": ["cublas", "cufft"]}
    r["requested"]["compile"]["openmp"] = False
    flags = view.as_flags(r)
    assert "--compile.openmp=False" in flags and "--with.any_gpu --with.cuda_libs=cublas,cufft" in flags
    assert view.as_flags(record_partial()) == "--use.gcc.version=13.3.0 --target_tmp=tmp"


def test_find_records_and_missing_message(view, tmp_path):
    entry = tmp_path / "task--program--x"
    for name, has in (("tmp", False), ("tmp-cuda", True), ("tmp-static", True), ("notes", True)):
        (entry / name).mkdir(parents = True)
        if has:
            (entry / name / "provenance.json").write_text("{}")
    assert [n for n, _ in view.find_records(str(entry))] == ["tmp-cuda", "tmp-static"]
    assert view.find_records(str(tmp_path / "absent")) == []
    msg = view.missing_message("x", str(entry / "tmp"), "tmp")
    assert "no provenance record in the build folder" in msg and "cx program run x" in msg and "--all" in msg
    assert 'build folder "tmp-cpu" of program "x"' in view.missing_message("x", None, "tmp-cpu")


def test_load_record_errors(view, tmp_path):
    assert view.load_record(str(tmp_path / "none.json"))["return"] == 16
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]")
    assert view.load_record(str(bad))["return"] == 1
    bad.write_text("{not json")
    assert view.load_record(str(bad))["return"] == 1


def test_short_path(view):
    assert view.short_path("/usr/bin/gcc") == "/usr/bin/gcc"
    long = "/home/user/CMETA/repos/local/cache/task--setup--lib-cudnn--bb22/content/lib/libcudnn.so.9"
    short = view.short_path(long, 40)
    assert len(short) == 40 and short.startswith("/home/u...") and short.endswith("lib/libcudnn.so.9")


# The command

def provenance(cm, **extra):
    p = {"category": "program", "command": "provenance", "arg1": "test-nmm-c-cpu", "con": False}
    p.update(extra)
    return cm.access(p)


def test_command_end_to_end(cm):
    # no build folder yet: a clear message, and no cache entry is created by the view
    r = provenance(cm)
    assert r["return"] > 0 and "no provenance record" in r["error"] and "cx program run test-nmm-c-cpu" in r["error"]

    # the build folders of the program: the cache entry task compile-and-run-program creates
    r = cm.access({"category": "cache", "command": "get", "arg1": "task--program--test-nmm-c-cpu",
                   "tags": ["task", "c36be4b9314a45e0", "compile-and-run-program", "05437a1aae224270"]})
    assert r["return"] == 0, r.get("error")
    entry = r["artifact"]["path"]

    r = provenance(cm)
    assert r["return"] > 0 and "no provenance record in the build folder" in r["error"]

    ok, failed = record_ok(), record_failed()
    for rec in (ok, failed):
        rec["program"]["alias"] = "test-nmm-c-cpu"
    os.makedirs(os.path.join(entry, "tmp-static"))
    os.makedirs(os.path.join(entry, "tmp-old"))
    with open(os.path.join(entry, "tmp-static", "provenance.json"), "w") as f:
        json.dump(ok, f)
    with open(os.path.join(entry, "tmp-old", "provenance.json"), "w") as f:
        json.dump(failed, f)

    # tmp has no record: the folders that have one are listed
    r = provenance(cm)
    assert r["return"] == 0 and [x["target_tmp"] for x in r["records"]] == ["tmp-old", "tmp-static"]

    r = provenance(cm, target_tmp = "tmp-static")
    assert r["return"] == 0 and r["record"]["ok"] is True and r["path"].endswith(os.path.join("tmp-static", "provenance.json"))
    assert "Provenance of program test-nmm-c-cpu (tmp-static)" in r["text"]

    r = provenance(cm, all = True)
    assert r["return"] == 0 and sorted(x["target_tmp"] for x in r["records"]) == ["tmp-old", "tmp-static"]
    assert {x["target_tmp"]: x["ok"] for x in r["records"]} == {"tmp-old": False, "tmp-static": True}

    r = provenance(cm, target_tmp = "tmp-static", as_flags = True)
    assert r["return"] == 0 and r["flags"].startswith("--use.compiler-cpp.name=gcc-cpp") and r["flags"].endswith("--target_tmp=tmp-static")

    r = provenance(cm, target_tmp = "tmp-static", as_json = True)
    assert r["return"] == 0 and r["record"]["created"] == "2026-10-04T20:11:03Z"

    r = provenance(cm, target_tmp = "tmp-static", diff = "tmp-old")
    assert r["return"] == 0 and ("nvcc", "version", "13.3.1", "12.9.86") in [tuple(x) for x in r["diff"]["resolved"]]
    assert r["diff"]["loaded"]["added"] == ["/lib/x86_64-linux-gnu/libcrypto.so.3"]

    other = os.path.join(entry, "tmp-old", "provenance.json")
    r = provenance(cm, target_tmp = "tmp-static", diff = other)
    assert r["return"] == 0 and r["diff_path"] == other

    r = provenance(cm, target_tmp = "tmp-static", diff = "tmp-none")
    assert r["return"] > 0 and "no provenance record for --diff" in r["error"]

    r = provenance(cm, target_tmp = "tmp-none")
    assert r["return"] > 0 and "tmp-none" in r["error"]

    r = cm.access({"category": "program", "command": "provenance", "con": False})
    assert r["return"] > 0 and "name the program" in r["error"]
