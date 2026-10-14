"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the reproduction of a run ("cx ... -r", category/task/api/provenance.py write_repro and the
task category): the folder repro/<stamp>/ with the request that reruns the command with every tool pinned to
the version it used (repro.json), the tools (tools.json), the run's facts (run.json) and a README; a rerun
from repro.json gives the same versions. On a throwaway tool detected at this Python; nothing is installed.
"""

import importlib.util
import json
import os
import pathlib
import sys

import pytest
import yaml

PYTHON_VERSION = "%d.%d.%d" % sys.version_info[:3]
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = "test-repro-fake"


@pytest.fixture(scope="module")
def prov():
    """category/task/api/provenance.py loaded on its own: the repro helpers need no cMeta."""
    spec = importlib.util.spec_from_file_location("task_provenance_repro", REPO_ROOT / "category" / "task" / "api" / "provenance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repro_request_pins_every_tool_and_drops_the_run_switches(prov):
    origin = {"category": "tool", "command": "setup", "arg1": "yq", "con": True, "quiet": True, "repro": True, "r": True,
              "_cli": {"cmd": ["tool", "setup", "yq", "-r"]}, "json": True, "use": {"git": {"version": "2.50.0"}},
              "version": "latest"}
    tools = {"yq": {"name": "yq", "version": "4.53.6"}, "git": {"name": "git", "version": "2.53.0"}, "host": {"version": None}}

    request = prov.repro_request(origin, tools)

    assert request["category"] == "tool" and request["command"] == "setup" and request["arg1"] == "yq" and request["quiet"] is True
    assert "repro" not in request and "r" not in request and "_cli" not in request and "json" not in request
    assert "version" not in request                                                          # the word "latest" became the pin
    assert request["use"] == {"git": {"version": "2.53.0"}, "yq": {"version": "4.53.6"}}      # what was used, not what was asked
    assert origin["use"] == {"git": {"version": "2.50.0"}}                                       # the original is not changed
    assert prov.use_versions(request) == {"git": {"version": "2.53.0"}, "yq": {"version": "4.53.6"}}


def test_repro_request_pins_what_a_word_or_a_partial_version_became(prov):
    """--use.python.version=3.12 --use.pip-torch.version=latest: the pins are 3.12.14 and 2.14.1 (seen 2026-10-14:
    the request's own words were kept, so a rerun asked again for "the newest torch")."""
    origin = {"category": "program", "command": "run", "arg1": "model-cnn-ylecun-mnist-pytorch", "epochs": "1",
              "use": {"python": {"version": "3.12"}, "pip-torch": {"version": "latest"}, "compiler-c": {"name": "clang"}}}
    tools = {"python": {"version": "3.12.14"}, "pip-torch": {"version": "2.14.1"}, "pip-numpy": {"version": "2.5.4"}}

    request = prov.repro_request(origin, tools)

    assert request["use"] == {"python": {"version": "3.12.14"}, "pip-torch": {"version": "2.14.1"},
                              "compiler-c": {"name": "clang"}, "pip-numpy": {"version": "2.5.4"}}
    assert request["epochs"] == "1" and origin["use"]["python"] == {"version": "3.12"}


def test_repro_readme_names_the_rerun(prov):
    text = prov.repro_readme("20261014-010203", ["tool", "setup", "yq", "-r"], "/work", {"yq": "4.53.6"})
    assert "cx @repro/20261014-010203/repro.json" in text and "yq 4.53.6" in text and "tool setup yq -r" in text


@pytest.fixture(scope="module")
def fake_tool(cm):
    r = cm.access({"category": "tool", "command": "add", "arg1": f"local:{TOOL}", "con": False, "quiet": True, "yaml": True})
    assert r["return"] == 0, r.get("error")
    desc = {"names": [os.path.basename(sys.executable)],
            "match_version": [{"regex": r"Python (\d+\.\d+\.\d+)", "group": 1}],
            "cmd_get_version": "{{tool_path}} --version",
            "default_version": PYTHON_VERSION,
            "install_cmd": {"all": f'"{sys.executable}" -c "print(1)"'},
            "skip_common_install_uses": True}
    with open(os.path.join(r["path"], "_desc.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(desc, f)
    return r["path"]


def test_a_run_with_repro_writes_the_folder_and_reruns_from_it(cm, fake_tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # The request as the command line makes it: "cx task run setup --name=<tool> --tool_path=<python> -q -r"
    request = {"category": "task", "command": "run", "arg1": "setup", "name": TOOL, "tool_path": sys.executable,
               "con": False, "quiet": True, "repro": True,
               "_cli": {"cmd": ["task", "run", "setup", f"--name={TOOL}", f"--tool_path={sys.executable}", "-q", "-r"]}}
    r = cm.access(request)
    assert r["return"] == 0, r.get("error")
    assert r["version"] == PYTHON_VERSION

    folders = sorted((tmp_path / "repro").iterdir())
    assert len(folders) == 1, folders
    folder = folders[0]
    assert sorted(p.name for p in folder.iterdir()) == ["README.md", "repro.json", "run.json", "tools.json"]

    repro = json.loads((folder / "repro.json").read_text(encoding="utf-8"))
    assert repro["category"] == "task" and repro["command"] == "run" and repro["arg1"] == "setup" and repro["name"] == TOOL
    assert "repro" not in repro and "_cli" not in repro
    assert repro["use"][TOOL]["version"] == PYTHON_VERSION

    tools = json.loads((folder / "tools.json").read_text(encoding="utf-8"))
    assert tools[TOOL]["version"] == PYTHON_VERSION and tools[TOOL]["path"]
    assert tools[TOOL]["params"]["name"] == TOOL

    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    # The engine drops -r from the recorded command line (a rerun must not write another folder by itself)
    assert run["return"] == 0 and "-q" in run["command_line"] and "-r" not in run["command_line"]
    assert run["tools"] >= 1 and run["host"]["uname"] and run["cmeta_version"]
    assert run["directory"] == str(tmp_path) or os.path.normcase(run["directory"]) == os.path.normcase(str(tmp_path))

    # The rerun from the file: the same version, and no new folder (the file holds no -r)
    r2 = cm.access(dict(repro))
    assert r2["return"] == 0, r2.get("error")
    assert r2["version"] == PYTHON_VERSION
    assert len(list((tmp_path / "repro").iterdir())) == 1

    # A pin that cannot be met fails loudly (a version the request names is never replaced)
    bad = json.loads((folder / "repro.json").read_text(encoding="utf-8"))
    bad["use"][TOOL]["version"] = "0.0.1"
    bad["new"] = True
    r3 = cm.access(bad)
    assert r3["return"] > 0 and "0.0.1" in r3["error"], r3
