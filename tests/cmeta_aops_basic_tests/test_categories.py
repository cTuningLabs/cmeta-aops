"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The main categories this repo ships exist and resolve their artifacts.
"""

import pytest

# Categories that must exist AND contain at least one artifact.
POPULATED_CATEGORIES = ["task", "tool", "program"]

# Auxiliary categories that must exist as category definitions (may be stubs /
# may or may not currently hold artifacts).
ALL_CATEGORIES = POPULATED_CATEGORIES + ["model", "dataset", "docker"]


@pytest.mark.parametrize("category", ALL_CATEGORIES)
def test_category_definition_exists(cm, category):
    """Each category is registered (its `category/<name>/_cmeta.yaml` is indexed)."""
    r = cm.access({"category": "category", "command": "find", "arg1": category})
    assert r["return"] == 0, r.get("error")
    aliases = {a["cmeta_ref_parts"].get("artifact_alias") for a in r.get("artifacts", [])}
    assert category in aliases, f"category '{category}' not found among {sorted(aliases)}"


@pytest.mark.parametrize("category", POPULATED_CATEGORIES)
def test_category_has_artifacts(cm, category):
    r = cm.access({"category": category, "command": "find"})
    assert r["return"] == 0, r.get("error")
    assert len(r.get("artifacts", [])) > 0, f"no artifacts indexed for category '{category}'"


@pytest.mark.parametrize("category", POPULATED_CATEGORIES)
def test_found_artifacts_belong_to_category(cm, category):
    """Every artifact returned for a category actually carries that category ref."""
    r = cm.access({"category": category, "command": "find"})
    assert r["return"] == 0, r.get("error")
    for a in r["artifacts"]:
        assert a["cmeta_ref_parts"].get("category_alias") == category
