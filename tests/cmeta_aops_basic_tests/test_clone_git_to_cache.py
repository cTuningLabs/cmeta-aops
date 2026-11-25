"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline test of task/clone-git-to-cache: every git parameter of its cache identity (branch,
new_branch, update_submodules, checkout, fetch, depth, filter) and the clone options reach task/clone-git.
"""

import pytest


@pytest.fixture(scope = "module")
def task(task_namespace):
    # the hook file with a stand-in for the engine's base class and the real helpers of the task API
    return task_namespace("clone-git-to-cache")


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


def test_a_shallow_or_partial_clone_is_a_clone_of_its_own(task, tmp_path):
    """depth and filter are part of the cache identity (_desc.yaml) and of the folder of the file cache: a full clone is
    never taken for a shallow one, nor a shallow one for a full one; a clone without them keeps its folder of before."""
    import os
    import pathlib
    import yaml
    desc = pathlib.Path(__file__).resolve().parents[2] / "task" / "clone-git-to-cache" / "_desc.yaml"
    assert {"depth", "filter"} <= set(yaml.safe_load(desc.read_text(encoding = "utf-8"))["cache_params"])
    folders = {}
    for kind, words in (("full", {}), ("shallow", {"depth": 1}), ("partial", {"filter": "blob:none"})):
        t = task["CTask"].__new__(task["CTask"])
        t.cm = FakeCM()
        t.category_alias, t.category_uid = "task", "c36be4b9314a45e0"
        ctx = {"control": {"con": False, "quiet": True, "verbose": False},
               "tasks": {"nested_call": 0, "global": {"init": {"file_cache": str(tmp_path / "fc")}}, "cparams": {},
                         "run_control": {"cur_dir": str(tmp_path), "work_dir": str(tmp_path)}}}
        assert t.run(ctx, name = "src-x", url = "https://github.com/org/x", checkout = "v1.0", **words)["return"] == 0
        folders[kind] = os.path.relpath(t.cm.calls[0]["path"], str(tmp_path / "fc")).replace(os.sep, "/")
    assert folders == {"full": "git-src-x/v1.0", "shallow": "git-src-x/v1.0-depth1", "partial": "git-src-x/v1.0-filter-blob-none"}
