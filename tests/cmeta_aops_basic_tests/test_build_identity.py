"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The build entries of a program (category/task/api/build_identity.py): the identity of a request, its
digest, the entry found by it or made for it (the plain request adopts the entry made before the entries
per request), the resolved toolchain written back. The entries are made in the suite's throwaway
CMETA_HOME through the cache category, as the driver does.
"""

import importlib.util
import json
import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def bi():
    path = REPO_ROOT / "category" / "task" / "api" / "build_identity.py"
    spec = importlib.util.spec_from_file_location("build_identity_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_reused_build_completes_its_tools_features_from_the_current_entries(bi, tmp_path):
    # the entry of lib-litert-android was re-detected after the build: it now carries model_int8
    entry = tmp_path / "task--setup--lib-litert-android--0123456789abcdef"
    entry.mkdir()
    (entry / "cmeta-task-cached-result.json").write_text(json.dumps({
        "version": "2.2.0", "features": {"model": "/m/float.tflite", "model_int8": "/m/quant.tflite", "root": "/x"}}), encoding = "utf-8")
    gone = tmp_path / "task--setup--gone--fedcba9876543210"        # an entry that no longer exists
    g = {"host": {"os": {"uname": "linux"}},
         "lib-litert-android": {"version": "2.2.0", "path_cmeta_cache": str(entry), "features": {"model": "/m/old-float.tflite"}},
         "compiler-c": {"version": "21.0.0", "path_cmeta_cache": str(gone), "features": {"flags": {}}},
         "python": {"version": "3.14.7", "path": "/v/bin/python"},                   # no entry at all
         "target": {"compute": ["android-cpu"]}}
    added = bi.complete_restored_tools(g)
    assert added == {"lib-litert-android": ["model_int8", "root"]}
    f = g["lib-litert-android"]["features"]
    assert f["model_int8"] == "/m/quant.tflite" and f["root"] == "/x"
    assert f["model"] == "/m/old-float.tflite"                      # what the snapshot had stays: the build's record
    assert g["compiler-c"]["features"] == {"flags": {}} and "features" not in g["python"]
    # a second pass adds nothing; a snapshot entry without features gets them all
    assert bi.complete_restored_tools(g) == {}
    g["lib-litert-android"].pop("features")
    assert bi.complete_restored_tools(g) == {"lib-litert-android": ["model", "model_int8", "root"]}
    # a broken result file is skipped
    (entry / "cmeta-task-cached-result.json").write_text("{not json", encoding = "utf-8")
    g["lib-litert-android"]["features"] = {}
    assert bi.complete_restored_tools(g) == {}


def test_request_identity_is_the_explicit_choices_and_the_resolved_targets(bi):
    plain = bi.request_identity({"name": "prog", "target_tmp": "tmp-x", "recompile": True}, {}, [])
    assert plain == {"compute": ["cpu"]} == bi.PLAIN
    assert bi.request_identity({"name": "prog"}, {}, ["cpu"]) == plain                         # the resolved target, not the request
    full = bi.request_identity({"name": "prog", "compile": {"static": "True", "flags": ""}, "with": {"openmp": True}, "params": {"n": 1024}},
                               {"nvcc": {"version": 12.9, "update": True}, "compiler-cpp": {"name": "gcc-cpp"}}, ["cuda", "cpu"])
    assert full == {"use": {"compiler-cpp": {"name": "gcc-cpp"}, "nvcc": {"version": "12.9"}},
                    "compile": {"static": True}, "with": {"openmp": True}, "compute": ["cpu", "cuda"]}
    # the program's run parameters, the control switches of --use and the empty members are not identity
    assert "params" not in full and "update" not in full["use"]["nvcc"] and "flags" not in full["compile"]
    # the same request in another spelling has the same digest; a different one another
    again = bi.request_identity({"compile": {"static": True}, "with": {"openmp": "yes"}}, {"compiler-cpp": {"name": "gcc-cpp"}, "nvcc": {"version": "12.9"}}, ["cpu", "cuda"])
    assert bi.digest(again) == bi.digest(full) and len(bi.digest(full)) == 16
    assert bi.digest(bi.request_identity({}, {"nvcc": {"version": "13.3"}}, ["cuda"])) != bi.digest(full)
    assert bi.digest(plain) == bi.digest({"compute": ["cpu"]})


def test_describe_and_entry_params(bi):
    assert bi.describe(bi.PLAIN) == "plain (cpu, no explicit choice)"
    identity = {"use": {"compiler-c": {"name": "clang"}, "nvcc": {"version": "12.9"}}, "compile": {"static": True, "flags": "-O3"}, "compute": ["cuda"]}
    assert bi.describe(identity) == "compiler-c clang, nvcc 12.9, static, flags=-O3, cuda"
    params = bi.entry_params("prog", "0123456789abcdef", identity)
    assert params == {"program": "prog", "program_uid": "0123456789abcdef", "request": identity, "request_digest": bi.digest(identity)}
    assert bi.plain_name("prog") == "task--program--prog"
    resolved = bi.resolved_of({"nvcc": {"name": "nvcc", "version": "12.9.86", "path": "/usr/local/cuda-12.9/bin/nvcc", "entry": "x", "features": {}},
                               "host": "not a dict", "lib-openssl": {"version": "3.0.13"}})
    assert resolved == {"nvcc": {"name": "nvcc", "version": "12.9.86", "path": "/usr/local/cuda-12.9/bin/nvcc"}, "lib-openssl": {"version": "3.0.13"}}


def read_meta(path):
    for name in ("_cmeta.json", "_cmeta.yaml"):
        p = os.path.join(path, name)
        if os.path.isfile(p):
            if name.endswith(".json"):
                with open(p, encoding = "utf-8") as f:
                    return json.load(f)
            import yaml
            with open(p, encoding = "utf-8") as f:
                return yaml.safe_load(f)
    raise AssertionError(f"no meta in {path}")


def test_entries_per_request_with_the_cache_category(bi, cm):
    cache = "cache,1ebdcc1cc30c4022"
    alias, uid = "test-build-entries", "fedcba9876543210"

    # nothing yet: no entry, and no entry is made by looking
    r = bi.find_entries(cm, cache, alias, uid)
    assert r["return"] == 0 and r["entries"] == []

    # the plain request makes the plain entry (the name every program had before)
    plain = bi.request_identity({}, {}, ["cpu"])
    r = bi.find_or_create_entry(cm, cache, alias, uid, plain)
    assert r["return"] == 0 and r["created"] and not r["adopted"] and r["alias"] == "task--program--test-build-entries"
    plain_path = r["path"]
    meta = read_meta(plain_path)
    assert meta["params"]["program"] == alias and meta["params"]["request"] == plain and meta["params"]["request_digest"] == bi.digest(plain)
    assert set(meta["tags"]) >= set(bi.TAGS)

    # the same request finds it; another request gets its own entry, named with a UID
    r = bi.find_or_create_entry(cm, cache, alias, uid, plain)
    assert r["return"] == 0 and not r["created"] and r["path"] == plain_path
    cuda = bi.request_identity({"compile": {"static": True}}, {"nvcc": {"version": "13.3"}}, ["cuda"])
    r = bi.find_or_create_entry(cm, cache, alias, uid, cuda)
    assert r["return"] == 0 and r["created"] and r["alias"].startswith("task--program--test-build-entries--") and r["uid"]
    cuda_path = r["path"]
    assert cuda_path != plain_path and read_meta(cuda_path)["params"]["request"] == cuda
    assert bi.find_or_create_entry(cm, cache, alias, uid, cuda)["path"] == cuda_path
    assert bi.find_or_create_entry(cm, cache, alias, uid, dict(cuda, compute = ["cpu", "cuda"]))["created"]   # other targets: another entry

    # every entry of the program, by its params; one request only
    r = bi.find_entries(cm, cache, alias, uid)
    assert r["return"] == 0 and len(r["entries"]) == 3 and {e["path"] for e in r["entries"]} >= {plain_path, cuda_path}
    assert all(e["params"]["program"] == alias for e in r["entries"])
    r = bi.find_entries(cm, cache, alias, uid, cuda)
    assert [e["path"] for e in r["entries"]] == [cuda_path]

    # the resolved toolchain of a run goes into the entry's params, the request stays
    r = bi.update_entry(cm, cache, {"alias": "task--program--test-build-entries", "uid": read_meta(plain_path)["artifact"]},
                        {"compiler-c": {"name": "gcc", "version": "14.2.0", "path": "/usr/bin/gcc", "entry": "abcd"}})
    assert r["return"] == 0
    meta = read_meta(plain_path)
    assert meta["params"]["resolved"] == {"compiler-c": {"name": "gcc", "version": "14.2.0", "path": "/usr/bin/gcc"}}
    assert meta["params"]["request_digest"] == bi.digest(plain)


def test_the_entry_made_before_is_adopted_by_the_plain_request(bi, cm):
    cache = "cache,1ebdcc1cc30c4022"
    alias, uid = "test-legacy-entry", "0f0f0f0f0f0f0f0f"
    # an entry as every program had it before: the plain name, the four tags, no params
    r = cm.access({"category": cache, "command": "get", "arg1": f"task--program--{alias}", "tags": bi.TAGS})
    assert r["return"] == 0, r.get("error")
    legacy_path = r["artifact"]["path"]
    assert "params" not in read_meta(legacy_path) or not read_meta(legacy_path)["params"]

    r = bi.find_entries(cm, cache, alias, uid)
    assert r["return"] == 0 and [(e["path"], e["params"]) for e in r["entries"]] == [(legacy_path, None)]

    # another request does not take it: a new entry with a UID
    cuda = bi.request_identity({}, {"nvcc": {"version": "12.9"}}, ["cuda"])
    r = bi.find_or_create_entry(cm, cache, alias, uid, cuda)
    assert r["return"] == 0 and r["created"] and r["path"] != legacy_path
    assert [e["params"] is None for e in bi.find_entries(cm, cache, alias, uid)["entries"]] == [False, True]   # the one without params last

    # the plain request adopts it and writes the params; the builds in it stay where they are
    plain = bi.request_identity({}, {}, ["cpu"])
    r = bi.find_or_create_entry(cm, cache, alias, uid, plain)
    assert r["return"] == 0 and r["adopted"] and not r["created"] and r["path"] == legacy_path
    meta = read_meta(legacy_path)
    assert meta["params"]["request"] == plain and meta["params"]["request_digest"] == bi.digest(plain) and meta["params"]["program"] == alias
    r = bi.find_or_create_entry(cm, cache, alias, uid, plain)
    assert r["return"] == 0 and not r["adopted"] and not r["created"] and r["path"] == legacy_path
    assert all(e["params"] is not None for e in bi.find_entries(cm, cache, alias, uid)["entries"])


def test_driver_chooses_the_entry_from_the_request_before_the_pipeline():
    src = (REPO_ROOT / "task" / "compile-and-run-program" / "api_v1.py").read_text(encoding = "utf-8")
    i_snap = src.index("request_params = copy.deepcopy(params)")
    i_targets = src.index("selected_compute = _global.get('target',{}).get('compute', [])")
    i_identity = src.index("identity = build_identity.request_identity(request_params, request_use, selected_compute)")
    i_entry = src.index("r = build_identity.find_or_create_entry(self.cm, self.cmeta['uses_categories']['cache'],")
    i_all = src.index("all_uses = all_desc.get('uses', {})")
    assert i_snap < i_targets < i_identity < i_entry < i_all          # the request and the resolved targets name the entry, before any tool is set up
    assert "ctx_tasks['local']['build_entry'] = {'path': r['path'], 'alias': r['alias'], 'uid': r['uid']," in src
    assert "build_identity.update_entry(self.cm, self.cmeta['uses_categories']['cache'], entry, record.get('resolved'))" in src
