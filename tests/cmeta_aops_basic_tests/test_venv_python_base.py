"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The venv task's --python=<interpreter>: the venv is made on the interpreter the user named (a conda env's
python, a system python) instead of a uv-managed one, recorded as python_base; a version at the same time is
refused. Offline: uv is a fake that runs nothing, the venv files are planted.
"""

import os

import pytest


@pytest.fixture(scope="module")
def venv(task_namespace):
    return task_namespace("venv")


class CM:
    debug = False

    def __init__(self):
        self.cmds = []

        class Files:
            quote_path = staticmethod(lambda p: f'"{p}"' if ' ' in p else p)

        class Utils:
            files = Files()

        self.utils = Utils()

    def access(self, d):
        self.cmds.append(d.get("cmd"))
        return {"return": 0, "returncode": 0, "stdout": ""}

    def catch_error(self, r):
        return r.get("return", 0) > 0

    def check_params(self, params, allowed, name):
        return {"return": 0}

    def error(self, msg, code = 1):
        return {"return": code, "error": msg}


def task_of(ns):
    t = ns["CTask"].__new__(ns["CTask"])
    t.cm = CM()
    return t


def ctx():
    return {"control": {}, "tasks": {"nested_call": 0, "run_control": {}, "global": {"uv": {"qpath": "uv"}}}}


def test_check_params_takes_an_existing_interpreter_and_refuses_a_version_with_it(venv, tmp_path):
    base = tmp_path / "conda" / ("python.exe" if os.name == "nt" else "python")
    base.parent.mkdir()
    base.write_text("")
    t = task_of(venv)
    params = {"python": str(base)}
    assert t.check_params(ctx(), params)["return"] == 0 and params["python"] == os.path.abspath(str(base))
    r = t.check_params(ctx(), {"python": str(base), "version": "3.13"})
    assert r["return"] == 1 and "cannot both be given" in r["error"]
    r = t.check_params(ctx(), {"python": str(tmp_path / "missing" / "python")})
    assert r["return"] == 1 and "was not found" in r["error"]


def test_run_makes_the_venv_on_the_interpreter_and_records_it(venv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scripts = tmp_path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    scripts.mkdir(parents = True)
    for name in (("activate.bat", "python.exe") if os.name == "nt" else ("activate", "python")):
        (scripts / name).write_text("")
    base = str(tmp_path / "my env" / "python")      # a space: the path is quoted on the command line

    t = task_of(venv)
    r = t.run(ctx(), python = base, version = None, env = {}, timeout = None)
    assert r["return"] == 0
    assert t.cm.cmds == [f'uv venv --seed --python "{base}"']
    assert r["python_base"] == base and r["_update_params"] == {"version": None, "python": base}
    assert os.path.normcase(r["path_to_python"]) == os.path.normcase(str(scripts / ("python.exe" if os.name == "nt" else "python")))

    # without --python: the version, as before, and nothing recorded as the base
    t = task_of(venv)
    r = t.run(ctx(), python = None, version = "3.12", env = {}, timeout = None)
    assert t.cm.cmds == ["uv venv --seed --python 3.12"] and "python_base" not in r and r["_update_params"] == {"version": "3.12"}
