"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the tool fixes of 2026-11-24 (cmeta-aops 0.81.1): common_pyvenv's c_libraries - the include and
library folders of the libraries a C extension compiles against, given to its build (certbot's python-augeas with
Homebrew's augeas on macOS) -, lib-augeas's library folder, flm's pinned 1.0.13 and the exit codes it names when it
cannot start, and the pins of lib-zlib 1.4 and of cloudflared's default version.
"""

import os
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SHA256 = re.compile(r"[0-9a-f]{64}")


def load(rel_path, stubs = ()):
    """A hook file of the repository with its cMeta imports replaced: stubs are (line, replacement) pairs."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool:\n    pass")
    for line, new in stubs:
        src = src.replace(line, new)
    ns = {"__name__": "under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


@pytest.fixture(scope = "module")
def pyvenv():
    ns = load("category/tool/api/common_pyvenv.py",
              [("from tool_c393ba5c6fa14f66.api.common_release import default_version", "")])
    ns["default_version"] = lambda tool, spec = None: (getattr(tool, "cdesc", None) or {}).get("default_version")
    return ns


# --------------------------------------------------------------------------------------------
# common_pyvenv: c_libraries

def test_the_folders_the_compiler_does_not_search_are_named(pyvenv):
    brew = {"include": "/opt/homebrew/include", "includes": ["/opt/homebrew/include"],
            "lib": "/opt/homebrew/lib", "libs": ["/opt/homebrew/lib"]}
    g = {"lib-augeas": {"features": {"paths": brew}},
         "lib-system": {"features": {"paths": {"include": "/usr/include", "lib": "/usr/lib/x86_64-linux-gnu"}}},
         "lib-space": {"features": {"paths": {"include": "/opt/my libs/include"}}}}
    flags = pyvenv["library_flags"]

    assert flags(g, ["lib-augeas"]) == (["-I/opt/homebrew/include"], ["-L/opt/homebrew/lib"])

    # the compiler's own folders stay unnamed: an -I/usr/include can reorder the system's headers
    assert flags(g, ["lib-system"]) == ([], [])

    # a library that was not set up, a folder with a space, the same library twice
    assert flags(g, ["lib-missing"]) == ([], [])
    assert flags(g, ["lib-space"]) == (['-I"/opt/my libs/include"'], [])
    assert flags(g, ["lib-augeas", "lib-augeas"]) == (["-I/opt/homebrew/include"], ["-L/opt/homebrew/lib"])

    searched = pyvenv["searched_anyway"]
    assert all(searched(f) for f in ("/usr/include", "/usr/lib", "/usr/lib64", "/usr/lib/aarch64-linux-gnu/"))
    assert not any(searched(f) for f in ("/opt/homebrew/include", "/usr/local/include", "/home/linuxbrew/.linuxbrew/lib"))


class FakeCM:
    """Records the commands run and the environment each got; runs nothing."""

    def __init__(self):
        self.runs = []
        me = self

        class Sys:
            @staticmethod
            def run(command, **kw):
                me.runs.append((command, dict(kw.get("env") or {})))
                return {"return": 0, "returncode": 0}

        class Utils:
            sys = Sys

        self.utils = Utils

    def access(self, ii):
        return {"return": 0, "tool_path": "uv"}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def error(self, text, *a, **kw):
        return {"return": 1, "error": text}


def test_the_build_of_a_c_extension_gets_the_folders_of_its_libraries(pyvenv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CFLAGS", "-O2")
    monkeypatch.delenv("LDFLAGS", raising = False)

    # an environment made already, with the command in it
    bindir = tmp_path / "venv" / "bin"
    bindir.mkdir(parents = True)
    (bindir / "python").write_text("")
    (bindir / "certbot").write_text("")

    tool = type("T", (), {})()
    tool.cm, tool.cdesc = FakeCM(), {"default_version": "5.10.0"}
    paths = {"include": "/opt/homebrew/include", "lib": "/opt/homebrew/lib"}
    ctx = {"tasks": {"nested_call": 0,
                     "global": {"host": {"os": {"uname": "darwin"}, "vars": {"file_ext_exe": ""}}, "uv": {"qpath": "uv"},
                                "compiler-c": {"path": "/usr/bin/clang"}, "lib-augeas": {"features": {"paths": paths}}}}}
    spec = {"name": "certbot", "python": "3.12", "c_compiler": True, "c_libraries": ["lib-augeas"]}

    r = pyvenv["install_pyvenv"](tool, ctx, {"control": {}}, None, spec)
    assert r["return"] == 0
    envs = [env for command, env in tool.cm.runs if " pip install " in command]
    assert envs == [{"CC": "/usr/bin/clang", "CFLAGS": "-O2 -I/opt/homebrew/include", "LDFLAGS": "-L/opt/homebrew/lib"}]

    # without c_libraries: the compiler alone, as before
    tool.cm = FakeCM()
    r = pyvenv["install_pyvenv"](tool, ctx, {"control": {}}, None, dict(spec, c_libraries = []))
    assert [env for command, env in tool.cm.runs if " pip install " in command] == [{"CC": "/usr/bin/clang"}]


def test_certbot_builds_against_the_augeas_of_lib_augeas():
    src = (REPO_ROOT / "tool" / "certbot" / "api_v1.py").read_text(encoding = "utf-8")
    assert "'c_libraries': ['lib-augeas']" in src
    desc = yaml.safe_load((REPO_ROOT / "tool" / "certbot" / "_desc.yaml").read_text(encoding = "utf-8"))
    assert all(any(u["name"].startswith("lib-augeas,") for u in desc["install_uses"][o]) for o in ("linux", "darwin"))


# --------------------------------------------------------------------------------------------
# lib-augeas: the library folder beside its pkgconfig folder

def test_lib_augeas_names_its_library_folder():
    ns = load("tool/lib-augeas/api_v1.py")
    folder = ns["library_folder"]
    assert folder("/opt/homebrew/lib/pkgconfig") == "/opt/homebrew/lib"
    assert folder("/usr/lib64/pkgconfig") == "/usr/lib64"
    assert folder("/usr/lib/x86_64-linux-gnu/pkgconfig") == "/usr/lib/x86_64-linux-gnu"
    assert folder("/usr/share/pkgconfig") == os.path.join("/usr", "lib")


# --------------------------------------------------------------------------------------------
# flm: 1.0.13 pinned, the codes of a start that cannot be

def test_flm_pins_1_0_13_and_knows_why_it_cannot_start():
    ns = load("tool/flm/api_v1.py", [("from tool_c393ba5c6fa14f66.api.common_deb import sha256_of", "")])
    for uname in ("linux", "windows"):
        asset, sha = ns["asset_for"]("1.0.13", uname, "amd64")
        assert asset.startswith("fastflowlm_1.0.13_") and SHA256.fullmatch(sha)

    # Windows' STATUS_DLL_NOT_FOUND unsigned and signed; an illegal instruction as Python (-4) and a shell (132) see
    # the signal on Linux, and Windows' STATUS_ILLEGAL_INSTRUCTION both ways
    assert set(ns["DLL_NOT_FOUND"]) == {0xC0000135, -1073741515}
    assert set(ns["ILLEGAL_INSTRUCTION"]) == {-4, 132, 0xC000001D, -1073741795}


# --------------------------------------------------------------------------------------------
# pins: lib-zlib 1.4, cloudflared's default version

def test_lib_zlib_pins_1_4():
    ns = load("tool/lib-zlib/api_v1.py",
              [("from tool_c393ba5c6fa14f66.api.common_static_lib import install_static_lib, detect_static_lib", "")])
    assert SHA256.fullmatch(ns["SPEC"]["sha256"]["1.4"])


def test_cloudflared_pins_the_digests_of_its_default_version():
    """Its docstring's rule: the digests of a new default version are added with it."""
    desc = yaml.safe_load((REPO_ROOT / "tool" / "cloudflared" / "_desc.yaml").read_text(encoding = "utf-8"))
    ns = load("tool/cloudflared/api_v1.py",
              [("from tool_c393ba5c6fa14f66.api.common_release import install_release", "")])
    sums = ns["SPEC"]["checksum"]["sha256"][str(desc["default_version"])]
    assert set(sums) == {"cloudflared-linux-amd64", "cloudflared-linux-arm64", "cloudflared-darwin-amd64.tgz",
                         "cloudflared-darwin-arm64.tgz", "cloudflared-windows-amd64.exe"}
    assert all(SHA256.fullmatch(v) for v in sums.values())
