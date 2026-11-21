"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The newest version of a tool installed from the files of its GitHub releases (latest_needs_assets: true in its
_desc.yaml - llama.cpp) is the newest tag whose release has those files: a build's tag comes minutes before them
(2026-11-21: cx tool check-updates named b12591 while its binaries were not published). A tool that does not say so
keeps the newest tag, as before. No network: the pages are stand-ins.
"""

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CTX = {"tasks": {"global": {"host": {"os": {"uname": "linux"}, "os_extra": {}}}}}
CHANNELS = {"declared": None, "package": None}
TAGS = {"12604": "b12604", "12606": "b12606", "12608": "b12608", "12609": "b12609"}


@pytest.fixture()
def up(monkeypatch):
    spec = importlib.util.spec_from_file_location("setup_upgrade_released_files", REPO_ROOT / "task" / "setup" / "upgrade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # GitHub marks another kind of release as latest (llama.cpp: not a b-build): the tags decide
    monkeypatch.setattr(module, "github_latest_release_tag", lambda repo, timeout=15: "v0.5.0")
    return module


class _Self:
    def list_versions(self, ctx, desc, params, never_install=False):
        return {"return": 0, "versions": list(TAGS), "tags": dict(TAGS)}


DESC = {"cmd_get_versions": "git ls-remote --tags https://github.com/ggml-org/llama.cpp",
        "cmd_get_versions_regex": r"\brefs/tags/b(\d+)\b"}


def test_a_page_with_files_and_one_without(up):
    assert up.release_has_files('<a href="/ggml-org/llama.cpp/releases/download/b12606/llama-b12606-bin-win.zip">', "b12606")
    assert not up.release_has_files('<a href="/ggml-org/llama.cpp/archive/refs/tags/b12608.zip">Source code</a>', "b12608")
    assert not up.release_has_files(None, "b12608")


def test_the_newest_tag_whose_release_has_its_files(up, monkeypatch):
    released = {"b12604": True, "b12606": True, "b12608": False, "b12609": False}
    monkeypatch.setattr(up, "github_release_has_files", lambda repo, tag, timeout=20: released[tag])
    r = up.find_latest(_Self(), CTX, dict(DESC, latest_needs_assets=True), {}, {}, CHANNELS)
    assert r["upstream_version"] == "12606", r
    assert any("b12609 has no files released yet" in n for n in r["notes"]) and any("b12608" in n for n in r["notes"])


def test_a_page_that_cannot_be_read_takes_the_newest_tag(up, monkeypatch):
    monkeypatch.setattr(up, "github_release_has_files", lambda repo, tag, timeout=20: None)
    r = up.find_latest(_Self(), CTX, dict(DESC, latest_needs_assets=True), {}, {}, CHANNELS)
    assert r["upstream_version"] == "12609" and any("could not be read" in n for n in r["notes"]), r


def test_a_tool_that_does_not_say_so_keeps_the_newest_tag(up, monkeypatch):
    monkeypatch.setattr(up, "github_release_has_files", lambda repo, tag, timeout=20: pytest.fail("not asked"))
    r = up.find_latest(_Self(), CTX, dict(DESC), {}, {}, CHANNELS)
    assert r["upstream_version"] == "12609", r
