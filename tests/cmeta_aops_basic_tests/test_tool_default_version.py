"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The version a tool installs when none is asked for is declared in its _desc.yaml (default_version), not in
the SPEC of its api_v1.py: every tool on a shared installer (common_release, common_pyvenv,
common_static_lib) declares it there, no SPEC carries a copy, and the installers read it from the
description (a SPEC key is only a fallback for tools written before 0.46.1). Offline.
"""

import os
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALLERS = ('install_release(', 'install_pyvenv(', 'install_static_lib(')
SPEC_KEY = re.compile(r"""['"]default_version['"]\s*:\s*['"]""")       # a literal value: a copy of the description


def load(rel_path, stubs = ()):
    """The module's namespace, with its cMeta imports replaced."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in stubs:
        assert line in src, line
        src = src.replace(line, replacement)
    ns = {"__name__": path.stem, "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def tools_on_shared_installers():
    found = []
    for api in sorted((REPO_ROOT / "tool").glob("*/api_v1.py")):
        code = api.read_text(encoding = "utf-8")
        if any(word in code for word in INSTALLERS):
            found.append(api.parent.name)
    return found


TOOLS = tools_on_shared_installers()


def test_tools_were_found():
    assert len(TOOLS) >= 20, TOOLS


@pytest.mark.parametrize("name", TOOLS)
def test_default_version_is_declared_in_desc_not_in_code(name):
    folder = REPO_ROOT / "tool" / name
    desc = yaml.safe_load((folder / "_desc.yaml").read_text(encoding = "utf-8-sig")) or {}

    # One version, or one per implementation (mpi: --with.mpi), as non-empty strings
    versions = desc.get("default_versions") or {"": desc.get("default_version")}
    assert versions, f"tool/{name}/_desc.yaml declares no default_version"
    for key, version in versions.items():
        assert isinstance(version, str) and version.strip(), f"tool/{name}/_desc.yaml: default_version{key and ' ' + key} must be a quoted string"

    # The code holds no copy: a bump is one edit, and "cx tool show" answers the question
    code = (folder / "api_v1.py").read_text(encoding = "utf-8")
    spec_copies = [line for line in code.splitlines() if SPEC_KEY.search(line)]
    assert not spec_copies, f"tool/{name}/api_v1.py still pins a version in its code: {spec_copies}"


###################################################################################################
# The helper and the installers

@pytest.fixture(scope = "module")
def release():
    return load("category/tool/api/common_release.py")


@pytest.fixture(scope = "module")
def pyvenv(release):
    ns = load("category/tool/api/common_pyvenv.py",
              [("from tool_c393ba5c6fa14f66.api.common_release import default_version", "")])
    ns["default_version"] = release["default_version"]
    return ns


class FakeCM:
    """Records the download URL and the commands run; downloads nothing."""

    def __init__(self):
        self.urls = []
        self.commands = []
        me = self

        class Sys:
            @staticmethod
            def run(command, **kw):
                me.commands.append(command)
                return {"return": 0, "returncode": 0}

        class Utils:
            sys = Sys

        self.utils = Utils

    def access(self, ii):
        if "url" in ii:
            self.urls.append(ii["url"])
            return {"return": 1, "error": "offline test"}
        return {"return": 0, "tool_path": "uv"}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def error(self, text, *a, **kw):
        return {"return": 1, "error": text}


def tool_with(desc):
    tool = type("T", (), {})()
    tool.cm = FakeCM()
    if desc is not None:
        tool.cdesc = desc
    return tool


def test_default_version_prefers_the_description(release):
    f = release["default_version"]
    assert f(tool_with({"default_version": "1.2.3"}), {"default_version": "9.9.9"}) == "1.2.3"
    assert f(tool_with({}), {"default_version": "9.9.9"}) == "9.9.9"        # an older tool: the SPEC key
    assert f(tool_with(None), {"default_version": "9.9.9"}) == "9.9.9"      # no description at all (a stub)
    assert f(tool_with({}), {}) is None
    assert f(tool_with({"default_version": 1.3}), {}) == "1.3"              # an unquoted YAML number


def test_install_release_takes_the_version_of_the_description(release, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool = tool_with({"default_version": "7.7.7"})
    ctx = {"tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "linux", "uarch": "amd64"}, "vars": {"file_ext_exe": ""}}}}}
    spec = {"name": "x", "url": "https://example.invalid/x-{version}-{os}-{arch}"}
    r = release["install_release"](tool, ctx, {"control": {}}, None, spec)
    assert r["return"] == 1 and tool.cm.urls == ["https://example.invalid/x-7.7.7-linux-amd64"]

    # No version anywhere: a clear error, not a KeyError
    r = release["install_release"](tool_with({}), ctx, {"control": {}}, None, spec)
    assert r["return"] == 1 and "default_version" in r["error"]

    # An explicit version still wins
    tool = tool_with({"default_version": "7.7.7"})
    r = release["install_release"](tool, ctx, {"control": {}, "version": "8.0.0", "version_simple": "8.0.0"}, None, spec)
    assert tool.cm.urls == ["https://example.invalid/x-8.0.0-linux-amd64"]


def test_install_pyvenv_takes_the_version_of_the_description(pyvenv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents = True)
    (scripts / "python.exe").write_text("")
    (scripts / "lint.exe").write_text("")
    tool = tool_with({"default_version": "5.5.5"})
    ctx = {"tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "windows"}, "vars": {"file_ext_exe": ".exe"}},
                                                  "uv": {"qpath": "uv"}}}}
    r = pyvenv["install_pyvenv"](tool, ctx, {"control": {}}, None, {"name": "lint", "package": "the-lint", "python": "3.12"})
    assert r["return"] == 0 and r["found_path"] == os.path.join(str(tmp_path), "venv", "Scripts", "lint.exe")
    assert any('"the-lint==5.5.5"' in c for c in tool.cm.commands)

    r = pyvenv["install_pyvenv"](tool_with({}), ctx, {"control": {}}, None, {"name": "lint", "python": "3.12"})
    assert r["return"] == 1 and "default_version" in r["error"]
