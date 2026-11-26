"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of "unpinned" (2026-11-26): a tool that has no default_version on purpose says why in its _desc.yaml
(unpinned: '<reason>'). "cx tool check-updates" shows the reason beside "no pin", and the promotion of explored
versions proposes no first pin for it - a note with the reason instead. A tool has a pin or a reason for having
none, never both; apache2 (no install command of it ever took a version) and python say theirs.
"""

import importlib.util
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def up():
    """task/setup/upgrade.py loaded on its own: its helpers need no cMeta."""
    spec = importlib.util.spec_from_file_location("setup_upgrade_unpinned", REPO_ROOT / "task" / "setup" / "upgrade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope = "module")
def ev():
    """task/explore-tool-versions/api_v1.py without the task engine: its helpers."""
    path = REPO_ROOT / "task" / "explore-tool-versions" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from task_c36be4b9314a45e0.api.ctask import InitCTask",
                                                     "class InitCTask:\n    pass")
    ns = {"__name__": "task_explore_tool_versions_unpinned", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def verdict(tool, version, works, uname, error_class = None, error = None):
    return {"schema": 1, "tool": tool, "version": version, "obtained": version if works else None,
            "works": works, "error_class": error_class, "error": error, "host": {"uname": uname}}


def test_the_reason_of_a_tool_without_a_pin(up):
    reason = up.unpinned_reason
    assert reason({"unpinned": " the system's package decides "}) == "the system's package decides"
    assert reason({}) is None and reason(None) is None and reason({"unpinned": ""}) is None

    # a word that is no reason is none (the key is a sentence, not a switch)
    assert reason({"unpinned": True}) is None

    # a pin is what is installed: a reason for having none beside it does not count
    assert reason({"default_version": "1.2.3", "unpinned": "why"}) is None


def test_no_first_pin_is_proposed_for_a_tool_without_one_on_purpose(ev):
    records = [verdict("python", "3.14.8", True, "windows"), verdict("python", "3.14.8", True, "linux"),
               verdict("other", "2.0.0", True, "windows"), verdict("other", "2.0.0", True, "linux")]
    descs = {"python": {"unpinned": "the machine's own Python"}, "other": {}}

    proposals = ev["proposals_of"](records, descs, min_os = 2, today = "2026-11-26")
    assert {"tool": "python", "change": "unpinned", "version": "3.14.8", "reason": "the machine's own Python",
            "works_on": ["linux", "windows"], "evidence": 2} in proposals

    # a tool that says nothing still gets its first pin proposed, as before
    assert {"tool": "other", "change": "default_version", "from": None, "to": "2.0.0", "works_on": ["linux", "windows"],
            "evidence": 2, "first": True} in proposals
    assert len(proposals) == 2

    # with a pin the reason does not count: the next pin is proposed
    pinned = ev["proposals_of"](records[:2], {"python": {"default_version": "3.13.0", "unpinned": "ignored"}}, min_os = 2)
    assert [p["change"] for p in pinned] == ["default_version"] and pinned[0]["first"] is False


def test_every_kind_of_proposal_has_its_line(ev):
    """The promotion prints a line for each kind it makes (a "not supported here" note had none and reached the lines
    of a limit, which it has no words for)."""
    src = (REPO_ROOT / "task" / "explore-tool-versions" / "api_v1.py").read_text(encoding = "utf-8")
    for kind in ("default_version", "unpinned", "not available", "not supported here"):
        assert f"p['change'] == '{kind}'" in src


def test_a_tool_has_a_pin_or_a_reason_for_none():
    both, said = [], {}
    for path in sorted((REPO_ROOT / "tool").glob("*/_desc.yaml")):
        desc = yaml.safe_load(path.read_text(encoding = "utf-8")) or {}
        if "unpinned" in desc:
            said[path.parent.name] = desc["unpinned"]
            if desc.get("default_version"):
                both.append(path.parent.name)
    assert both == []
    assert all(isinstance(v, str) and len(v.strip()) > 20 for v in said.values())

    # apache2: every install command of it is the system's package manager, none takes a version; python: by design
    assert {"apache2", "python"} <= set(said)
    apache2 = yaml.safe_load((REPO_ROOT / "tool" / "apache2" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert "install_cmd_version" not in apache2 and not (REPO_ROOT / "tool" / "apache2" / "api_v1.py").read_text(
        encoding = "utf-8").count("def install(")


def test_the_report_shows_the_reason():
    category = (REPO_ROOT / "category" / "tool" / "api" / "v1.py").read_text(encoding = "utf-8")
    assert "no pin on purpose - {row[\"unpinned\"]}" in category and "'unpinned'," in category
    setup = (REPO_ROOT / "task" / "setup" / "api_v1.py").read_text(encoding = "utf-8")
    assert "unpinned = upgrade.unpinned_reason(desc)" in setup and "'unpinned': unpinned" in setup
