"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Engine wiring: cMeta imports, and this repo is registered and resolvable.
"""


def test_cmeta_importable_and_versioned():
    import cmeta

    assert getattr(cmeta, "__version__", None), "cmeta.__version__ is missing/empty"


def test_repo_is_plugged(cm):
    """The `repo plug` in the fixture must make this repo discoverable by the engine."""
    r = cm.access({"category": "repo", "command": "find"})
    assert r["return"] == 0, r.get("error")

    repo_uids = {a["cmeta_ref_parts"].get("artifact_uid") for a in r.get("artifacts", [])}
    # _cmr.yaml -> ctuninglabs@cmeta-aops,3cb4ee4f444048f6
    assert "3cb4ee4f444048f6" in repo_uids, f"this repo not found among plugged repos: {repo_uids}"


def test_uniform_access_reports_errors_not_raises(cm):
    """Unknown artifacts return a nonzero code + error string (the return contract),
    rather than raising."""
    r = cm.access(
        {"category": "task", "command": "find", "arg1": "this-artifact-does-not-exist-xyz"}
    )
    # find of a missing alias yields no artifacts (return 0/empty) or a >0 code with error;
    # either way it must be a well-formed dict with an int 'return' and no crash.
    assert isinstance(r, dict) and isinstance(r.get("return"), int)
    if r["return"] != 0:
        assert r.get("error")
