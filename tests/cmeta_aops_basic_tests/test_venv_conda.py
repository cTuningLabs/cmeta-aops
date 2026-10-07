"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The venv task's --conda (0.43.3): a conda environment in .conda-env instead of a uv venv - the task asks
tool/conda for the conda of the machine, runs "conda create -y -p .conda-env python=<version> pip <packages>
[-c <channel> --override-channels]", marks the environment with who made it (.cmeta-conda-env.json, read by
the provenance record) and records conda in its params. Offline: the engine is a fake, nothing runs.
"""

import json
import os

import pytest


@pytest.fixture(scope = "module")
def venv(task_namespace):
    return task_namespace("venv")


class CM:
    debug = False

    def __init__(self, env_python = None):
        self.cmds = []
        self.env_python = env_python

        class Files:
            quote_path = staticmethod(lambda p: f'"{p}"' if " " in p else p)

        class Utils:
            files = Files()

        self.utils = Utils()

    def access(self, d):
        if str(d.get("arg1", "")).startswith("setup"):
            d["ctx"]["tasks"]["global"]["conda"] = {"qpath": "conda", "path": "/opt/mf/condabin/conda", "version": "26.7.2"}
            return {"return": 0}
        self.cmds.append(d.get("cmd"))
        if self.env_python is not None:
            self.env_python.parent.mkdir(parents = True, exist_ok = True)
            self.env_python.write_text("")
        return {"return": 0, "returncode": 0, "stdout": ""}

    def catch_error(self, r):
        return r.get("return", 0) > 0

    def check_params(self, params, allowed, name):
        return {"return": 0}

    def error(self, msg, code = 1):
        return {"return": code, "error": msg}


def ctx():
    return {"control": {}, "tasks": {"nested_call": 0, "run_control": {}, "global": {"uv": {"qpath": "uv"}}}}


def test_a_conda_environment_is_made_by_conda_and_recorded(venv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prefix = tmp_path / ".conda-env"
    py = prefix / ("python.exe" if os.name == "nt" else os.path.join("bin", "python"))

    t = venv["CTask"].__new__(venv["CTask"])
    t.cm = CM(env_python = py)
    r = t.run(ctx(), conda = True, version = "3.12", conda_packages = "numpy, scipy", channel = "conda-forge", env = {}, timeout = None)
    assert r["return"] == 0, r.get("error")
    assert t.cm.cmds == [f"conda create -y -p {prefix} python=3.12 pip numpy scipy -c conda-forge --override-channels"]
    assert r["env_kind"] == "conda" and r["made_by"] == "conda 26.7.2" and r["path_to_activate_script"] == ""
    assert os.path.normcase(r["path_to_python"]) == os.path.normcase(str(py))
    assert r["_update_params"] == {"version": "3.12", "conda": True, "conda_packages": ["numpy", "scipy"], "channel": "conda-forge"}
    marker = json.load(open(prefix / ".cmeta-conda-env.json", encoding = "utf-8"))
    assert marker["made_by"] == "conda 26.7.2" and marker["conda"] == "/opt/mf/condabin/conda" and "conda create" in marker["cmd"]

    # the plain form: no version, no packages
    t = venv["CTask"].__new__(venv["CTask"])
    t.cm = CM(env_python = py)
    r = t.run(ctx(), conda = "true", version = None, env = {}, timeout = None)
    assert r["return"] == 0 and t.cm.cmds == [f"conda create -y -p {prefix} python pip"]
    assert r["_update_params"] == {"version": None, "conda": True}


def test_the_python_spec_and_the_parameter_rules(venv, tmp_path):
    assert venv["conda_python_spec"](None) == "python"
    assert venv["conda_python_spec"]("3.12") == "python=3.12"
    assert venv["conda_python_spec"]("3.12.4") == "python=3.12.4"
    assert venv["conda_python_spec"](">=3.11,<3.14") == '"python>=3.11,<3.14"'

    t = venv["CTask"].__new__(venv["CTask"])
    t.cm = CM()
    params = {"conda": "true", "version": "3.12"}
    assert t.check_params(ctx(), params)["return"] == 0 and params["conda"] is True
    r = t.check_params(ctx(), {"conda": True, "python": str(tmp_path)})
    assert r["return"] == 1 and "cannot both be given" in r["error"]
    params = {"conda": "no", "version": None, "conda_packages": "", "channel": None}
    assert t.check_params(ctx(), params)["return"] == 0
    assert "conda" not in params and "conda_packages" not in params and "channel" not in params
