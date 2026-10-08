"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/pip-torchvision: the torch / torchvision pairing by PyTorch's numbering, and the
pairing on AMD's index of its ROCm distribution (the versions a simple index page holds for a local tag,
the choice among them - the pair, its pre-release, or the newest final release that pairs with an older
torch - and the channel torch came from).
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel_path, imports = {}, inject = {}):
    """The module's namespace, with its cMeta imports replaced and names injected."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in imports.items():
        assert line in src
        src = src.replace(line, replacement)
    ns = {"__name__": path.parent.name, "__file__": str(path)}
    ns.update(inject)
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def tv():
    return load("tool/pip-torchvision/api_v1.py",
                {"from tool_c393ba5c6fa14f66.api.ctool import InitCTool": "class InitCTool: pass"})


# What AMD's stable index showed for torchvision on 2026-10-08 (torch had 2.14.0+rocm10.1.0)
INDEX_HTML = """<html><body>
<a href="torchvision-0.26.0%2Brocm10.0.0-cp312-cp312-linux_x86_64.whl">torchvision-0.26.0+rocm10.0.0-cp312-cp312-linux_x86_64.whl</a>
<a href="torchvision-0.27.0%2Brocm10.0.0-cp312-cp312-linux_x86_64.whl">...</a>
<a href="torchvision-0.27.0%2Brocm10.1.0-cp312-cp312-linux_x86_64.whl">...</a>
<a href="torchvision-0.28.0%2Brocm10.0.0-cp313-cp313-linux_x86_64.whl">...</a>
<a href="torchvision-0.28.0%2Brocm10.1.0-cp312-cp312-linux_x86_64.whl">...</a>
<a href="torchvision-0.28.0%2Brocm10.1.0-cp313-cp313-linux_x86_64.whl">...</a>
<a href="torchvision-0.29.0a0%2Brocm10.1.0-cp312-cp312-linux_x86_64.whl">...</a>
</body></html>"""


@pytest.mark.parametrize("torch, torchvision", [
    ("2.14.0", "0.29.0"), ("2.13.0", "0.28.0"), ("2.7.1", "0.22.1"), ("2.0.0", "0.15.0"),
    ("1.13.1", "0.14.1"), ("2.14.0+rocm10.1.0", "0.29.0"), ("2.13.0+rocm7.2", "0.28.0"),
    ("2.12.0a0+git0d62256", "0.27.0"), ("2.14", "0.29"), ("3.0.0", None), ("x", None),
])
def test_torchvision_for_torch(tv, torch, torchvision):
    assert tv["torchvision_for_torch"](torch) == torchvision


@pytest.mark.parametrize("torchvision, torch", [
    ("0.29.0", "2.14.0"), ("0.28.0", "2.13.0"), ("0.22.1", "2.7.1"), ("0.14.1", "1.13.1"),
    ("0.28.0+rocm10.1.0", "2.13.0"), ("0.29.0a0", "2.14.0"), ("bad", None),
])
def test_torch_for_torchvision(tv, torchvision, torch):
    assert tv["torch_for_torchvision"](torchvision) == torch


def test_versions_on_index(tv):
    f = tv["versions_on_index"]
    assert f(INDEX_HTML, "torchvision", "rocm10.1.0") == ["0.27.0", "0.28.0", "0.29.0a0"]
    assert f(INDEX_HTML, "torchvision", "rocm10.0.0") == ["0.26.0", "0.27.0", "0.28.0"]
    assert f(INDEX_HTML, "torch", "rocm10.1.0") == []
    assert f(None, "torchvision", "rocm10.1.0") == []
    assert f("", "torchvision", "rocm10.1.0") == []


def test_version_key_orders_pre_release_before_final(tv):
    key = tv["version_key"]
    assert sorted(["0.29.0", "0.28.0", "0.29.0a0", "0.29.0rc1"], key = key) == ["0.28.0", "0.29.0a0", "0.29.0rc1", "0.29.0"]


def test_choose_torchvision(tv):
    choose = tv["choose_torchvision"]
    available = ["0.27.0", "0.28.0", "0.29.0a0"]
    # The pair is there
    assert choose("0.28.0", available) == ("0.28.0", "exact")
    # The pair is pending: its pre-release
    assert choose("0.29.0", available) == ("0.29.0a0", "pre-release")
    # Neither: the newest final release, which pairs with an older torch
    assert choose("0.30.0", available) == (None, "0.28.0")
    # An empty index (not read): nothing to say
    assert choose("0.29.0", []) == (None, None)
    # Several pre-releases: the newest
    assert choose("0.29.0", ["0.29.0a0", "0.29.0rc1", "0.28.0"]) == ("0.29.0rc1", "pre-release")


def test_amd_channel_of(tv):
    f = tv["amd_channel_of"]
    assert f({"version": "2.14.0+rocm10.1.0"}, {}) == "stable"
    assert f({"version": "2.14.0+rocm10.1.0"}, {"rocm_channel": "Nightly"}) == "nightly"
    recorded = {"version": "2.14.0+rocm10.1.0",
                "params": {"with": {"post_flags": "--index-url https://nightly.repo.amd.com/rocm/whl-next/"}}}
    assert f(recorded, {}) == "nightly"
    assert f(None, None) == "stable"


def test_amd_index_url(tv):
    assert tv["AMD_INDEX"].format(channel = "stable") == "https://stable.repo.amd.com/rocm/whl-next/"
