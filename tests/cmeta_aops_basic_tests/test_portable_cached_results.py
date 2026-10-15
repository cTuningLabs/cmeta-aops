"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the task category's portable cached results: a cached result saved in one place (the
entry's path recorded as _cmeta_entry_path by the save) and reused from another - the entry moved, or shared
through a data repository mounted elsewhere, on another OS - has every path under the entry rewritten to the
entry's current path, the quoted twins (qpath of path) quoted again, and nothing else touched; a result without
the record, or reused where it was saved, is returned as it is.
"""

import importlib.util
import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def category():
    path = REPO_ROOT / "category" / "task" / "api" / "v2.py"
    spec = importlib.util.spec_from_file_location("task_api_v2_under_test", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeCM:
        def q(self, s):
            return f'"{s}"'

    c = module.Category.__new__(module.Category)
    c.cm = FakeCM()
    return c


def relocate(category, result, here):
    return category._relocate_cached_result(result, here)


def test_without_the_record_nothing_changes(category):
    result = {"return": 0, "path": r"D:\old\cache\entry\content\x.bin"}
    assert relocate(category, dict(result), "/new/cache/entry") == result


def test_reused_where_it_was_saved_nothing_changes(category):
    here = os.path.join(os.getcwd(), "entry")
    result = {"return": 0, "_cmeta_entry_path": here, "path": os.path.join(here, "content", "x.bin")}
    assert relocate(category, dict(result), here) == result


def test_windows_entry_reused_on_posix_paths(category):
    saved = r"D:\cmeta-data\cache\task--get-hf-model--x"
    here = "/home/cmeta/data/cmeta-data/cache/task--get-hf-model--x"
    result = {"return": 0, "_cmeta_entry_path": saved,
              "path": saved + r"\content\model.gguf", "qpath": '"' + saved + r'\content\model.gguf"',
              "path_root": saved + r"\content", "qpath_root": "junk",
              "features": {"paths": {"model": saved + r"\content\model.gguf"}, "library": "gguf"},
              "files": [saved + r"\content\a", saved + "/content/b", "/elsewhere/c"],
              "elsewhere": r"D:\cmeta-data\cache\task--get-hf-model--xy\content", "n": 3}

    out = relocate(category, result, here)

    sep = os.sep
    expect = here + sep + "content" + sep + "model.gguf"
    assert out["path"] == expect
    assert out["qpath"] == '"' + expect + '"'              # quoted again for this OS, from the new path
    assert out["path_root"] == here + sep + "content"
    assert out["qpath_root"] == '"' + here + sep + "content" + '"'
    assert out["features"]["paths"]["model"] == expect
    assert out["features"]["library"] == "gguf"
    assert out["files"] == [here + sep + "a", here + sep + "content" + sep + "b", "/elsewhere/c"] or \
           out["files"][0] == here + sep + "content" + sep + "a"
    assert out["elsewhere"] == r"D:\cmeta-data\cache\task--get-hf-model--xy\content"   # another entry: not ours
    assert out["n"] == 3
    assert out["_cmeta_entry_path"] == here


def test_posix_entry_reused_on_another_posix_path(category):
    saved = "/home/fursin/CMETA/repos/local/cache/task--download-file--abc"
    here = "/mnt/data/cache/task--download-file--abc"
    result = {"return": 0, "_cmeta_entry_path": saved, "path": saved + "/content/file.tar.gz",
              "env": {"CMETA_FILE": saved + "/content/file.tar.gz"}}
    out = relocate(category, result, here)
    assert out["path"] == here + os.sep + "content" + os.sep + "file.tar.gz"
    assert out["env"]["CMETA_FILE"] == out["path"]


def test_a_prefix_that_is_only_a_longer_name_is_not_ours(category):
    saved = "/x/cache/entry"
    out = relocate(category, {"_cmeta_entry_path": saved, "path": "/x/cache/entry2/content"}, "/y/entry")
    assert out["path"] == "/x/cache/entry2/content"


def test_windows_prefix_compares_without_case(category):
    saved = r"d:\Cache\Entry"
    out = relocate(category, {"_cmeta_entry_path": saved, "path": r"D:\cache\entry\content\f"}, "/new/entry")
    assert out["path"] == "/new/entry" + os.sep + "content" + os.sep + "f"
