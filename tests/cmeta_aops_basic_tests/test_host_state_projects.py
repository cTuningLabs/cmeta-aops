"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A probe of a host keeps the saved state of each project the host declares, and drops the state of a project
taken out of the host's _desc.yaml (before 2026-10-16 a retired project stayed in state.yaml for ever, and
cx host show kept reporting its repositories).
"""

import importlib.util
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def host_category():
    path = REPO_ROOT / "category" / "host" / "api" / "v1.py"
    spec = importlib.util.spec_from_file_location("category_host_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_retired_project_leaves_the_state():
    saved = {"projects": {"server": {"probed_at": "2026-10-15"}, "old-prototype": {"probed_at": "2026-10-12"}}}
    desc = {"projects": {"server": {"path": "/srv"}}}
    assert host_category().declared_project_states(saved, desc) == {"server": {"probed_at": "2026-10-15"}}


def test_no_declared_projects_keeps_none():
    saved = {"projects": {"old-prototype": {"probed_at": "2026-10-12"}}}
    module = host_category()
    assert module.declared_project_states(saved, {}) == {}
    assert module.declared_project_states(saved, None) == {}
    assert module.declared_project_states({}, {"projects": {"server": {}}}) == {}
