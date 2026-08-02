"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Artifact resolution, including the rename-safe `alias,UID` contract (when both an
alias and a UID are given, the UID is authoritative).
"""

import pytest

# Foundational task artifacts referenced by other categories/pipelines.
# alias -> UID (from _cmeta / _desc references across the repo).
KNOWN_TASKS = {
    "clone-git-to-cache": "86919b3cfdd443d2",
    "setup": "a2f9b61079ce4333",
    "cmd": "c9ba0a88df394d7f",
    "compile-and-run-program": "05437a1aae224270",
    "host": "96ac7118439c4490",
}


def _find(cm, category, ref):
    r = cm.access({"category": category, "command": "find", "arg1": ref})
    assert r["return"] == 0, r.get("error")
    return r.get("artifacts", [])


def _uids(artifacts):
    return {a["cmeta_ref_parts"].get("artifact_uid") for a in artifacts}


def _aliases(artifacts):
    return {a["cmeta_ref_parts"].get("artifact_alias") for a in artifacts}


@pytest.mark.parametrize("alias,uid", sorted(KNOWN_TASKS.items()))
def test_find_by_alias(cm, alias, uid):
    assert uid in _uids(_find(cm, "task", alias))


@pytest.mark.parametrize("alias,uid", sorted(KNOWN_TASKS.items()))
def test_find_by_uid(cm, alias, uid):
    assert alias in _aliases(_find(cm, "task", uid))


@pytest.mark.parametrize("alias,uid", sorted(KNOWN_TASKS.items()))
def test_find_by_alias_uid(cm, alias, uid):
    artifacts = _find(cm, "task", f"{alias},{uid}")
    assert uid in _uids(artifacts)


@pytest.mark.parametrize("alias,uid", sorted(KNOWN_TASKS.items()))
def test_uid_is_authoritative_over_wrong_alias(cm, alias, uid):
    """`wrong-alias,UID` must still resolve to the artifact identified by UID."""
    artifacts = _find(cm, "task", f"zz-not-a-real-alias,{uid}")
    assert uid in _uids(artifacts)


def test_read_artifact_metadata(cm):
    """A task artifact can be read back with its `_cmeta` metadata."""
    r = cm.access({"category": "task", "command": "find", "arg1": "clone-git-to-cache"})
    assert r["return"] == 0, r.get("error")
    a = r["artifacts"][0]
    assert a["cmeta"].get("artifact") == "86919b3cfdd443d2"
    assert a["cmeta_ref_parts"].get("category_alias") == "task"
