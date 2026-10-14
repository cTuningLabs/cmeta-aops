"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of task/explore-tool-versions: a tool tried at several versions (a setup per version in a fresh cache
entry, removed afterwards), a verdict per version in a JSONL file, and the proposals the verdicts support
(--promote): the next default_version, or a limit of "latest". The helpers are tested on their own; the run end
to end on a throwaway tool detected at this Python - nothing is installed, no network is touched.
"""

import json
import os
import pathlib
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON = sys.executable
PYTHON_VERSION = "%d.%d.%d" % sys.version_info[:3]
MISSING = "99.0.0"


@pytest.fixture(scope="module")
def ev():
    """task/explore-tool-versions/api_v1.py without the task engine: its helpers."""
    path = REPO_ROOT / "task" / "explore-tool-versions" / "api_v1.py"
    src = path.read_text(encoding="utf-8").replace("from task_c36be4b9314a45e0.api.ctask import InitCTask",
                                                   "class InitCTask:\n    pass")
    ns = {"__name__": "task_explore_tool_versions", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def verdict(tool, version, works, uname, error_class=None, error=None, obtained=None):
    return {"schema": 1, "tool": tool, "version": version, "obtained": obtained or (version if works else None),
            "works": works, "error_class": error_class, "error": error, "host": {"uname": uname}}


###################################################################################################
# The helpers

def test_error_class(ev):
    assert ev["error_class"]("failed downloading file from https://x (HTTP Error 404: Not Found)", "setup") == "not available"
    assert ev["error_class"]("SHA-256 mismatch for yq.exe", "setup") == "checksum"
    assert ev["error_class"]("urlopen error timed out", "setup") == "download"
    assert ev["error_class"]("cmake failed: no CMAKE_C_COMPILER", "setup") == "build"
    assert ev["error_class"]("venv: No matching Python version for '3.14.8'", "setup") == "not available"
    assert ev["error_class"]('failed to setup tool "x"', "setup") == "setup"
    assert ev["error_class"]("the program returned 1", "program") == "program"


def test_entry_uid_and_first_line(ev):
    assert ev["entry_uid"]("D:/cache/task--setup--yq--455a02e03547474a") == "455a02e03547474a"
    assert ev["entry_uid"]("/usr/bin") is None and ev["entry_uid"](None) is None
    assert ev["first_line"]("\n  first\nsecond") == "first" and ev["first_line"](None) == ""


def test_proposals(ev):
    descs = {"x": {"default_version": "1.0.0", "latest_limits": [{"exclude": "==3.0.0"}]}, "y": {}}
    records = [
        verdict("x", "1.1.0", True, "windows"), verdict("x", "1.1.0", True, "linux"),      # works on two: the next known
        verdict("x", "1.2.0", True, "windows"),                                                # one OS only: not yet
        verdict("x", "2.0.0", True, "windows"),
        verdict("x", "2.0.0", False, "linux", "build", "cmake failed"),                        # fails somewhere: a limit
        verdict("x", "3.0.0", False, "linux", "build", "cmake failed"),                        # already excluded
        verdict("x", "0.9.0", False, "linux", "not available", "404"),                         # older than known: no word
        verdict("x", "1.3.0rc1", True, "windows"), verdict("x", "1.3.0rc1", True, "darwin"),  # a pre-release: not known
        verdict("x", "1.4.0", True, "windows"),                                                # not offered by an older
        verdict("x", "1.4.0", False, "linux", "not available", "No matching version"),         # uv: a note, not a limit
        verdict("y", "5.0.0", True, "windows"), verdict("y", "5.0.0", True, "darwin"),        # no pin yet: the first one
    ]

    proposals = ev["proposals_of"](records, descs, min_os=2, today="2026-10-14")

    assert {"tool": "x", "change": "default_version", "from": "1.0.0", "to": "1.1.0", "works_on": ["linux", "windows"],
            "evidence": 2, "first": False} in proposals
    assert {"tool": "x", "change": "latest_limits", "version": "2.0.0", "exclude": "==2.0.0",
            "reason": "build on linux: cmake failed", "since": "2026-10-14", "evidence": 2} in proposals
    assert {"tool": "y", "change": "default_version", "from": None, "to": "5.0.0", "works_on": ["darwin", "windows"],
            "evidence": 2, "first": True} in proposals
    assert {"tool": "x", "change": "not available", "version": "1.4.0", "on": "linux", "error": "No matching version",
            "works_on": ["windows"], "evidence": 2} in proposals
    assert len(proposals) == 4

    # One OS is enough when asked
    one = ev["proposals_of"](records, descs, min_os=1, today="2026-10-14")
    assert any(p["change"] == "default_version" and p["to"] == "1.2.0" for p in one)


def test_chosen_versions(ev):
    """Never a range by itself: known and latest (and the newest one a limit excludes), the versions given, or the
    <last> newest released versions listed - each with why it is tried."""
    info = {"known": "1.0.0", "latest": "1.2.0", "newest": "1.2.0", "limit": None,
            "versions": ["0.9.0", "1.0.0", "1.1.0", "1.2.0", "1.3.0rc1", "not-a-version"]}
    assert ev["chosen_versions"](info) == {"1.0.0": "known", "1.2.0": "latest"}
    assert ev["chosen_versions"](dict(info, latest="1.0.0")) == {"1.0.0": "known, latest"}
    assert ev["chosen_versions"](dict(info, latest="1.1.0", limit={"exclude": ">=1.2"})) == \
        {"1.0.0": "known", "1.1.0": "latest", "1.2.0": "newest, excluded from latest"}

    assert ev["chosen_versions"](info, versions="1.1.0, latest,1.1.0") == {"1.1.0": "asked", "latest": "asked"}
    assert ev["chosen_versions"](info, last=2) == {"1.2.0": "#1 newest of 4 listed", "1.1.0": "#2 newest of 4 listed"}
    assert ev["chosen_versions"]({}) == {} and ev["chosen_versions"]({}, last=3) == {}


def test_evidence_per_version_and_machine(ev):
    records = [verdict("x", "1.1.0", True, "windows"), verdict("x", "1.1.0", True, "linux"),
               verdict("x", "1.2.0", False, "linux", "setup", "No matching version for 1.2.0"),
               verdict("x", "latest", True, "darwin", obtained="1.1.0")]
    records[1]["host"]["hostname"] = "t470p"

    table = ev["evidence_of"](records)
    assert table == {"x": {"1.1.0": {"works": ["darwin", "linux (t470p)", "windows"], "fails": []},
                           "1.2.0": {"works": [], "fails": ["linux: not available"]}}}


def test_read_verdicts_from_files_and_folders(ev, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.jsonl").write_text(json.dumps(verdict("x", "1.0.0", True, "linux")) + "\n\n", encoding="utf-8")
    (tmp_path / "a" / "notes.txt").write_text("not verdicts", encoding="utf-8")
    two = tmp_path / "two.jsonl"
    two.write_text(json.dumps(verdict("x", "1.1.0", False, "darwin")) + "\n" + json.dumps({"no": "tool"}) + "\n",
                   encoding="utf-8")

    records, files = ev["read_verdicts"](f"{tmp_path / 'a'},{two}")
    assert [r["version"] for r in records] == ["1.0.0", "1.1.0"] and len(files) == 2


###################################################################################################
# End to end, offline: a throwaway tool detected at this Python

@pytest.fixture(scope="module")
def explore_tool(cm):
    r = cm.access({"category": "tool", "command": "add", "arg1": "local:test-explore-python", "con": False,
                   "quiet": True, "yaml": True})
    assert r["return"] == 0, r.get("error")
    desc = {
        "names": [os.path.basename(PYTHON)],
        "match_version": [{"regex": r"Python (\d+\.\d+\.\d+)", "group": 1}],
        "cmd_get_version": "{{tool_path}} --version",
        "default_version": PYTHON_VERSION,
        "cmd_get_latest_version": f'"{PYTHON}" -c "print({PYTHON_VERSION!r})"',
        "cmd_get_latest_version_regex": r"(\d+\.\d+\.\d+)",
        "install_cmd": {"all": f'"{PYTHON}" -c "print(1)"'},
        "skip_common_install_uses": True,
    }
    with open(os.path.join(r["path"], "_desc.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(desc, f)
    return r["path"]


def test_explore_then_promote(cm, explore_tool, tmp_path):
    out = tmp_path / "verdicts.jsonl"
    r = cm.access({"category": "task", "command": "run", "arg1": "explore-tool-versions", "tool": "test-explore-python",
                   "versions": f"{PYTHON_VERSION},{MISSING}", "output": str(out), "con": False, "quiet": True})
    assert r["return"] == 0, r.get("error")
    assert r["works"] == [PYTHON_VERSION] and r["fails"] == [MISSING]

    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [(v["version"], v["works"]) for v in lines] == [(PYTHON_VERSION, True), (MISSING, False)]
    good, bad = lines
    assert good["obtained"] == PYTHON_VERSION and good["entry_removed"] is True and good["host"]["uname"]
    assert bad["error"] and bad["error_class"] and bad["obtained"] is None and good["aops"]

    # The throwaway entry of the working version is gone
    rf = cm.access({"category": "cache", "command": "find", "tags": "setup,test-explore-python", "con": False})
    assert not rf.get("artifacts") or all(good.get("entry") != a["cmeta_ref_parts"]["artifact_uid"] for a in rf["artifacts"])

    assert good["chosen_as"] == "asked"

    # The failure becomes a proposed limit; nothing newer works, so the pin stays
    r = cm.access({"category": "task", "command": "run", "arg1": "explore-tool-versions", "promote": True,
                   "verdicts": str(out), "con": False, "quiet": True})
    assert r["return"] == 0, r.get("error")
    assert [(p["change"], p.get("exclude")) for p in r["proposals"]] == [("latest_limits", f"=={MISSING}")]
    assert r["evidence"]["test-explore-python"][PYTHON_VERSION]["works"]


def test_explore_known_by_default_into_a_file_named_after_the_host(cm, explore_tool, tmp_path, monkeypatch):
    """No versions given: the tool's known version (it lists no others); the verdicts file carries the host name."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CMETA_TEST_SESSION", raising=False)
    r = cm.access({"category": "task", "command": "run", "arg1": "explore-tool-versions", "tool": "test-explore-python",
                   "con": False, "quiet": True})
    assert r["return"] == 0, r.get("error")
    assert r["works"] == [PYTHON_VERSION] and r["verdicts"][0]["chosen_as"].startswith("known")

    name = os.path.basename(r["output"])
    host = r["verdicts"][0]["host"]["hostname"]
    assert os.path.dirname(r["output"]) == str(tmp_path)
    assert name.startswith("explore-tool-versions-test-explore-python-") and name.endswith(".jsonl")
    assert not host or host.replace(" ", "_") in name


def test_explore_without_a_tool_or_verdicts(cm):
    r = cm.access({"category": "task", "command": "run", "arg1": "explore-tool-versions", "con": False, "quiet": True})
    assert r["return"] > 0 and "name the tool" in r["error"]
    r = cm.access({"category": "task", "command": "run", "arg1": "explore-tool-versions", "promote": True, "con": False, "quiet": True})
    assert r["return"] > 0 and "--verdicts" in r["error"]


CRASH_API = '''from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def check_params(self, ctx, params, cparams):
        raise ValueError('No matching version for ' + str(params.get('version')))
'''


def test_a_crash_is_a_verdict_and_the_exploration_goes_on(cm, explore_tool, tmp_path):
    """A sub-task that raises (task/venv did, for a Python uv could not install) is a failed verdict of class
    "crash"; the other versions are still tried and every verdict is written as it is made."""
    r = cm.access({"category": "tool", "command": "add", "arg1": "local:test-explore-crash", "con": False,
                   "quiet": True, "yaml": True})
    assert r["return"] == 0, r.get("error")
    with open(os.path.join(r["path"], "_desc.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump({"names": ["nothing-to-find"], "default_version": "1.0.0"}, f)
    with open(os.path.join(r["path"], "api_v1.py"), "w", encoding="utf-8") as f:
        f.write(CRASH_API)

    out = tmp_path / "crash.jsonl"
    r = cm.access({"category": "task", "command": "run", "arg1": "explore-tool-versions", "tool": "test-explore-crash",
                   "versions": "1.0.0,2.0.0", "output": str(out), "con": False, "quiet": True})
    assert r["return"] == 0, r.get("error")
    assert r["fails"] == ["1.0.0", "2.0.0"]

    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [(v["version"], v["error_class"]) for v in lines] == [("1.0.0", "crash"), ("2.0.0", "crash")]
    assert lines[0]["error"].startswith("ValueError: No matching version for 1.0.0")


def test_a_generic_class_is_read_again_on_promotion(ev):
    """Verdicts written before "No matching ... version" was classed "not available" (class "setup") are read
    again: a note, not a limit (the fleet round of 2026-10-14: an older uv on Linux and macOS)."""
    records = [verdict("python", "3.14.8", True, "windows"),
               verdict("python", "3.14.8", False, "linux", "setup", "venv: No matching Python version for '3.14.8'")]
    records[1]["stage"] = "setup"

    proposals = ev["proposals_of"](records, {"python": {"default_version": "3.13.15"}}, min_os=1, today="2026-10-14")
    assert [p["change"] for p in proposals] == ["not available"] and proposals[0]["on"] == "linux"
