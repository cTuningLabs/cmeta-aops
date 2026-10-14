"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/venv: the Python version a venv asks for is resolved among the ones uv can install ("uv python list
--all-versions"). A version this uv cannot install, or a condition it cannot read, is an error that names it - it
raised ValueError before and stopped the whole run with a traceback (the exploration of Python 3.14.8 on Linux,
2026-10-14).
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

UV_LIST = """cpython-3.14.7-linux-x86_64-gnu                 <download available>
cpython-3.13.15-linux-x86_64-gnu                <download available>
cpython-3.12.14-linux-x86_64-gnu                /usr/bin/python3.12
cpython-3.15.0rc2-linux-x86_64-gnu              <download available>
"""


@pytest.fixture(scope="module")
def venv():
    path = REPO_ROOT / "task" / "venv" / "api_v1.py"
    src = path.read_text(encoding="utf-8").replace("from task_c36be4b9314a45e0.api.ctask import InitCTask, folder_as_named",
                                                   "class InitCTask:\n    pass\n\ndef folder_as_named(path):\n    return path")
    ns = {"__name__": "task_venv", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


class FakeCM:
    """The engine as task/venv sees it: check_params, errors, and the "uv python list" command."""
    debug = False

    def check_params(self, params, allowed, where):
        return {"return": 0}

    def catch_error(self, r, fail16=False):
        return r["return"] > 0

    def error(self, text, code=1):
        return {"return": code, "error": text}

    def access(self, ii):
        assert ii["cmd"].endswith("python list --all-versions")
        return {"return": 0, "stdout": UV_LIST}


def check(venv, version):
    task = venv["CTask"].__new__(venv["CTask"])
    task.cm = FakeCM()
    ctx = {"control": {"con": False, "verbose": False}, "tasks": {"nested_call": 0, "global": {"uv": {"qpath": "uv"}}},
           "origin": {"pwd": "."}}
    params = {"version": version}
    return task.check_params(ctx, params, {}), params


def test_a_version_uv_can_install_is_resolved(venv):
    r, params = check(venv, "3.13")
    assert r["return"] == 0 and params["version"] == "3.13.15"

    r, params = check(venv, ">=3.12,<3.14")
    assert r["return"] == 0 and params["version"] == "3.13.15"


@pytest.mark.parametrize("version", ["3.14.8", "2.7", ">=4"])
def test_a_version_uv_cannot_install_is_an_error_that_names_it(venv, version):
    r, params = check(venv, version)
    assert r["return"] == 1 and version in r["error"] and "uv python list" in r["error"]
