"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline test of task/clone-git-to-cache: every git parameter of its cache identity (branch,
new_branch, update_submodules, checkout, fetch) and the clone options reach task/clone-git.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def task():
    path = REPO_ROOT / "task" / "clone-git-to-cache" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from task_c36be4b9314a45e0.api.ctask import InitCTask", "class InitCTask:\n    pass")
    ns = {"__name__": "clone_git_to_cache", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


class FakeCM:
    debug = False

    def __init__(self):
        self.calls = []

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def access(self, ii):
        self.calls.append(ii)
        return {"return": 0, "path_to_git_repo": "/cache/src"}


def test_git_parameters_reach_clone_git(task, tmp_path):
    t = task["CTask"].__new__(task["CTask"])
    t.cm = FakeCM()
    t.category_alias, t.category_uid = "task", "c36be4b9314a45e0"
    ctx = {"control": {"con": False, "quiet": True, "verbose": False},
           "tasks": {"nested_call": 0, "global": {}, "cparams": {},
                     "run_control": {"cur_dir": str(tmp_path), "work_dir": str(tmp_path)}}}

    r = t.run(ctx, name = "src-x", url = "https://github.com/org/x", checkout = "main", branch = "dev",
              new_branch = "pr-7", update_submodules = True, depth = 1, fetch = "origin pull/7/head:pr-7")

    assert r["return"] == 0 and r["_update_params"]["git_path"] == "/cache/src"
    call = t.cm.calls[0]
    assert call["arg1"].startswith("clone-git,")
    for k, v in {"url": "https://github.com/org/x", "checkout": "main", "branch": "dev", "new_branch": "pr-7",
                 "update_submodules": True, "depth": 1, "fetch": "origin pull/7/head:pr-7"}.items():
        assert call[k] == v, k
    assert "tag" not in call and "filter" not in call      # only what was given
