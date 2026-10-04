"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A cached tool entry carries the features of the time it was cached, so a key its tool's _desc.yaml
gained afterwards (a compiler flag such as openmp_static_archive) was missing on every reuse until
--update. task/setup now layers the tool's current declarative features block under the features of a
reused result in finish_dynamic_result: the keys the result lacks come from the desc, the keys it has
keep their value, lists are not appended, and the cache entry itself is not written.
"""

import copy
import importlib
import importlib.machinery
import importlib.util
import pathlib
import sys
import types

import pytest

from cmeta.utils.common import deep_merge

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SETUP = REPO_ROOT / "task" / "setup"


@pytest.fixture(scope = "module")
def common():
    spec = importlib.util.spec_from_file_location("setup_common_under_test", SETUP / "common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope = "module")
def setup_api():
    """task/setup/api_v1.py as a package member (its relative imports), with the engine's InitCTask stubbed."""
    stub = types.ModuleType("task_c36be4b9314a45e0.api.ctask")
    stub.InitCTask = type("InitCTask", (), {})
    pkg_names = ["task_c36be4b9314a45e0", "task_c36be4b9314a45e0.api"]
    saved = {k: sys.modules.get(k) for k in pkg_names + [stub.__name__, "setup_pkg_under_test"]}
    for name in pkg_names:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules[stub.__name__] = stub
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("setup_pkg_under_test", None, is_package = True))
    pkg.__path__ = [str(SETUP)]
    sys.modules["setup_pkg_under_test"] = pkg
    try:
        yield importlib.import_module("setup_pkg_under_test.api_v1")
    finally:
        for k in list(sys.modules):
            if k.startswith("setup_pkg_under_test"):
                del sys.modules[k]
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


DESC = {"features": {"linux": {"flags": {"openmp": "-fopenmp", "openmp_static_archive": "libgomp.a", "lib_prefix": "-l"},
                               "paths": ["a", "b"]},
                     "windows": {"flags": {"openmp": "/openmp"}},
                     "darwin": {"flags": {"openmp": "-Xpreprocessor -fopenmp"}}}}


def test_block_precedence(common):
    assert common.desc_features_block(DESC, "linux")["flags"]["openmp"] == "-fopenmp"
    assert common.desc_features_block(DESC, "windows")["flags"]["openmp"] == "/openmp"
    assert common.desc_features_block(DESC, "freebsd")["flags"]["openmp"] == "-fopenmp"        # linux is the fallback
    everywhere = {"features": {"all": {"flags": {"x": 1}}, "linux": {"flags": {"x": 2}}}}
    assert common.desc_features_block(everywhere, "linux")["flags"]["x"] == 1                 # all wins
    assert common.desc_features_block({}, "linux") is None
    assert common.desc_features_block({"features": "odd"}, "linux") is None
    assert common.desc_features_block(None, "linux") is None


def test_a_cached_result_gets_the_keys_it_lacks_and_keeps_its_own(common):
    cached = {"path": "/usr/bin/gcc", "version": "12.2.0",
              "features": {"flags": {"openmp": "-fopenmp-detected", "lib_prefix": "-l"}, "paths": ["b", "c"], "detected": True}}
    before = copy.deepcopy(cached["features"])
    added = common.layer_desc_features(DESC, cached, "linux", deep_merge)
    assert added == ["flags.openmp_static_archive"]
    f = cached["features"]
    assert f["flags"]["openmp_static_archive"] == "libgomp.a"          # from the desc
    assert f["flags"]["openmp"] == "-fopenmp-detected"                 # the cached value wins
    assert f["paths"] == ["b", "c"] and f["detected"] is True           # lists as cached, extra keys kept
    assert cached["path"] == "/usr/bin/gcc" and cached["version"] == "12.2.0"
    # a second pass changes nothing
    assert common.layer_desc_features(DESC, cached, "linux", deep_merge) == []
    assert {k: v for k, v in f.items() if k != "flags"} == {k: v for k, v in before.items() if k != "flags"}
    # the desc itself is not changed
    assert "detected" not in DESC["features"]["linux"]


def test_without_features(common):
    cached = {"path": "/usr/bin/x", "version": "1"}
    assert common.layer_desc_features({"names": ["x"]}, cached, "linux", deep_merge) == []     # the desc has none
    assert "features" not in cached
    assert common.layer_desc_features(DESC, cached, "linux", deep_merge) == ["flags", "paths"]   # the result had none
    assert cached["features"]["flags"]["openmp_static_archive"] == "libgomp.a" and cached["features"]["paths"] == ["a", "b"]
    assert common.missing_feature_keys({"a": {"b": 1, "c": 2}, "d": 3}, {"a": {"b": 0}}) == ["a.c", "d"]


def test_finish_dynamic_result_layers_the_desc(setup_api):
    """The wiring in task/setup: the reused result returned by finish_dynamic_result carries the desc keys."""
    task = object.__new__(setup_api.CTask)
    task.cm = types.SimpleNamespace(debug = False, utils = types.SimpleNamespace(common = types.SimpleNamespace(deep_merge = deep_merge)),
                                    catch_error = lambda r, fail16 = False: r.get("return", 0) > 0)
    task.read_tool = lambda **kw: {"return": 0, "desc": DESC, "tool_api_code": None}
    ctx = {"control": {"con": False}, "tasks": {"global": {"host": {"os": {"uname": "linux"}}}, "local": {}}}
    cached = {"path": "/usr/bin/gcc", "features": {"flags": {"openmp": "-fopenmp"}}}
    r = task.finish_dynamic_result(ctx, cached, {"name": "gcc"})
    assert r["return"] == 0 and r["result"] is cached
    assert cached["features"]["flags"]["openmp_static_archive"] == "libgomp.a" and cached["features"]["flags"]["openmp"] == "-fopenmp"
    # nothing to add: the result is handed back unchanged and not announced
    r = task.finish_dynamic_result(ctx, cached, {"name": "gcc"})
    assert r["return"] == 0 and "result" not in r


def test_setup_compile_relies_on_the_layering():
    """The per-use fallback of setup-compile is gone: the flag comes with the compiler entry."""
    src = (REPO_ROOT / "task" / "setup-compile" / "api_v1.py").read_text(encoding = "utf-8")
    assert "tool_desc_flags" not in src
    assert "openmp_static_archive" in src
    src = (REPO_ROOT / "task" / "setup" / "detect.py").read_text(encoding = "utf-8")
    assert "common.desc_features_block(desc, uname)" in src
