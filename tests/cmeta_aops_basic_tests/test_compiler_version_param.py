"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/compiler accepts "version" (its run() reads it, and common_static_lib passes the C++ compiler's
version when it sets up the C compiler for a static C++ build): a static C++ build that had to build a
static dependency failed with 'unknown input parameter "version"'.
"""

import pathlib
import types

from cmeta.utils.common import check_params

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_compiler_init_accepts_version():
    path = REPO_ROOT / "task" / "compiler" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from task_c36be4b9314a45e0.api.ctask import InitCTask",
                                                     "class InitCTask: pass")
    ns = {"__name__": "task_compiler", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    task = object.__new__(ns["CTask"])
    # the engine's check_params names the calling module in its message: give it a module it can find
    task.cm = types.SimpleNamespace(check_params = lambda params, allowed, name: check_params(params, allowed, "cmeta.utils.common"),
                                    catch_error = lambda r: r["return"] > 0)
    assert task.init({}, {"lang": "c", "version": "14", "compute": "cpu"})["return"] == 0
    r = task.init({}, {"lang": "c", "versionx": "14"})
    assert r["return"] > 0 and "versionx" in r["error"]
