"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The test-session task: a dated sandbox and a record that stays, with the agent, the results and
the costs, as subfolders of two artifacts of the local repository (tmp:: and
log::cmeta-aops-test-sessions, <YYYYMMDD>/<HHMM>.<type>). Offline; the tests share the suite's throwaway CMETA_HOME, so
each uses its own session types.
"""

import datetime
import json
import os
import re
import uuid

import pytest

GENERATOR = {"method": "agent", "agent": "Claude Code 2.1.286", "model": "claude-opus-5-5", "effort": "max"}


@pytest.fixture
def session(cm, tmp_path, monkeypatch):
    """Run test-session with a throwaway root and a known agent."""
    monkeypatch.setenv("CMETA_GENERATOR", json.dumps(GENERATOR))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "0000-test-session")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))  # no transcripts unless a test writes them

    def run(**params):
        request = {"category": "task", "command": "run", "arg1": "test-session", "con": False, "quiet": True}
        request.update(params)
        return cm.access(request)

    run.home = str(cm.home_path)
    run.local = os.path.join(str(cm.home_path), "repos", "local")
    run.unique = uuid.uuid4().hex[:6]   # session types of this test only
    return run


@pytest.fixture(scope="module")
def helpers(repo_root):
    """The module-level helpers of the hook file (its class needs cMeta)."""
    path = repo_root / "task" / "test-session" / "api_v1.py"
    src = path.read_text(encoding="utf-8")
    head = src[:src.index("class CTask")].replace(
        "from task_c36be4b9314a45e0.api.ctask import InitCTask", "")
    ns = {"__file__": str(path)}
    exec(compile(head, str(path), "exec"), ns)
    return ns


def test_start_creates_sandbox_and_log(session, repo_root):
    r = session(start=True, type="Self Test", title="session test", cmd="cx task run x")
    assert r["return"] == 0, r.get("error")
    assert re.fullmatch(r"\d{8}/\d{4}\.self-test(-\d+)?", r["id"])
    date, name = r["id"].split("/")
    assert r["sandbox"] == os.path.join(session.local, "tmp", "cmeta-aops-test-sessions", date, name)
    assert os.path.isdir(r["sandbox"])
    assert r["log"] == os.path.join(session.local, "log", "cmeta-aops-test-sessions", date, name, "session.md")
    assert os.path.isfile(r["log"])

    rec = r["record"]
    assert rec["status"] == "running"
    assert rec["agent"]["model"] == "claude-opus-5-5"
    assert rec["agent"]["effort"] == "max"
    assert rec["agent"]["session"] == "0000-test-session"
    assert "method" not in rec["agent"]
    assert rec["repositories"][0]["path"] == str(repo_root)
    assert rec["host"]["cpus"] == os.cpu_count()
    with open(r["log"], encoding="utf-8") as f:
        md = f.read()
    assert "session test" in md and "claude-opus-5-5" in md and "`cx task run x`" in md


def test_same_minute_gets_a_suffix(session):
    a = session(start=True, type="dup")
    b = session(start=True, type="dup")
    assert a["return"] == 0 and b["return"] == 0
    if a["id"].split(".")[0] == b["id"].split(".")[0]:
        assert b["id"] == a["id"] + "-2"


def test_notes_results_costs_and_attachments(session, tmp_path):
    sid = session(start=True, type="bench")["id"]
    out = tmp_path / "bench.txt"
    out.write_text("gen 157.3 t/s\n", encoding="utf-8")
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"model": "qwen2.5-0.5b-q4_k_m"}), encoding="utf-8")

    r = session(id=sid, note="CUDA run", results={"cuda_tps": "157.3", "runs": "3"},
                results_file=str(results), attach=str(out), costs={"gpu_minutes": "2"},
                tokens="1200", cost_usd="0.5")
    assert r["return"] == 0, r.get("error")
    rec = r["record"]
    assert rec["notes"][-1]["text"] == "CUDA run"
    assert rec["results"] == {"model": "qwen2.5-0.5b-q4_k_m", "cuda_tps": 157.3, "runs": 3}
    assert rec["costs"] == {"gpu_minutes": 2, "agent_tokens": 1200, "agent_cost_usd": 0.5}
    kept = os.path.join(os.path.dirname(r["log"]), "attachments", "bench.txt")
    assert os.path.isfile(kept)
    assert rec["attachments"][0]["name"] == "bench.txt"

    md = open(r["log"], encoding="utf-8").read()
    assert "| cuda_tps | 157.3 |" in md
    assert "Agent tokens (reported): 1,200" in md and "Agent cost (reported): $0.5" in md
    assert "gpu_minutes: 2" in md
    assert "(attachments/bench.txt)" in md


def test_two_artifacts_hold_every_session_and_list_filters(session, cm):
    u = session.unique
    a = session(start=True, type="filter-a-" + u, title="first")
    b = session(start=True, type="filter-b-" + u, title="second")
    assert a["return"] == 0 and b["return"] == 0
    assert session(finish=True, id=a["id"], status="failed")["return"] == 0

    # no index entry per session: one log and one tmp artifact hold them all
    for category in ("log", "tmp"):
        r = cm.access({"category": category, "command": "find", "arg1": "local:cmeta-aops-test-sessions"})
        assert r["return"] == 0 and len(r["artifacts"]) == 1, category
    assert os.path.dirname(os.path.dirname(a["log"])) == os.path.dirname(os.path.dirname(b["log"]))  # the day

    failed = [x["id"] for x in session(list=True, status="failed")["sessions"]]
    assert a["id"] in failed and b["id"] not in failed
    host = a["record"]["host"]["name"]
    mine = [x["id"] for x in session(list=True, host=host.upper(), type="filter-b-" + u)["sessions"]]
    assert mine == [b["id"]]
    assert session(list=True, date=a["id"][:8], type="filter-a-" + u)["sessions"][0]["title"] == "first"
    # the other id forms work too
    old = a["id"].replace("/", "-", 1)
    assert session(id=old, note="by the old id")["record"]["notes"][-1]["text"] == "by the old id"


def test_finish_removes_a_large_sandbox_and_keeps_the_log(session):
    r = session(start=True, type="build")
    sid, sandbox = r["id"], r["sandbox"]
    with open(os.path.join(sandbox, "blob.bin"), "wb") as f:
        f.write(b"x" * 300000)

    r = session(finish=True, id=sid, status="failed", summary="compiler crashed", max_keep_mib="0.1")
    assert r["return"] == 0, r.get("error")
    rec = r["record"]
    assert rec["status"] == "failed" and rec["summary"] == "compiler crashed"
    assert rec["sandbox_removed"] is True and not os.path.exists(sandbox)
    assert rec["costs"]["sandbox_mib"] == 0.3
    assert rec["costs"]["wall_time_s"] >= 0
    md = open(r["log"], encoding="utf-8").read()
    assert "## Summary" in md and "compiler crashed" in md and "(removed, 0.3 MiB)" in md


def test_keep_list_and_prune(session):
    u = session.unique
    kept = session(start=True, type="keepme-" + u)
    small = session(start=True, type="small-" + u)
    running = session(start=True, type="running-" + u)
    assert session(finish=True, id=kept["id"], keep=True, max_keep_mib="0")["return"] == 0
    assert session(finish=True, id=small["id"])["return"] == 0
    assert os.path.isdir(small["sandbox"]), "a small sandbox stays after finish"

    listed = session(list=True)
    assert listed["return"] == 0
    ids = [s["id"] for s in listed["sessions"]]
    assert {kept["id"], small["id"], running["id"]} <= set(ids)
    only = session(list=True, type="small-" + u)["sessions"]
    assert [s["id"] for s in only] == [small["id"]]
    assert session()["sessions"], "listing is the default action"

    r = session(prune=True)
    assert r["return"] == 0
    assert small["id"] in r["pruned"] and kept["id"] not in r["pruned"] and running["id"] not in r["pruned"]
    assert not os.path.exists(small["sandbox"])
    assert os.path.isdir(kept["sandbox"]), "--keep survives a plain prune"
    assert os.path.isdir(running["sandbox"]), "a running session is never pruned"

    r = session(prune=True, all=True, id=kept["id"])
    assert r["pruned"] == [kept["id"]] and not os.path.exists(kept["sandbox"])


def test_errors(session, tmp_path):
    assert session(id="not-an-id", note="x")["return"] > 0
    assert session(id="20261002/0000.missing", note="x")["return"] > 0
    assert session(start=True, type="x", repos=str(tmp_path / "no-such-repo"))["return"] > 0
    sid = session(start=True, type="attach")["id"]
    assert session(id=sid, attach=str(tmp_path / "missing.txt"))["return"] > 0


def test_helpers(helpers):
    assert helpers["duration_text"](42) == "42 s"
    assert helpers["duration_text"](125) == "2 min 5 s"
    assert helpers["duration_text"](3725) == "1 h 2 min"
    assert helpers["value"]("3") == 3 and helpers["value"]("0.5") == 0.5 and helpers["value"]("a") == "a"
    assert helpers["bytes_text"](13) == "13 B" and helpers["bytes_text"](2048) == "2.0 KiB"
    assert helpers["size_text"](2048) == "2.0 GiB" and helpers["size_text"](12.5) == "12.5 MiB"
    assert helpers["changed_text"](1) == ", 1 changed file" and helpers["changed_text"](0) == ""
    t = datetime.datetime(2026, 10, 2, 9, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    assert helpers["stamp"](t) == "2026-10-02 09:15:00 UTC+02:00"
    assert helpers["name_of"]("20261002/1338.ubuntu-npu-xpu") == "20261002/1338.ubuntu-npu-xpu"
    assert helpers["name_of"]("20261002-1338.ubuntu-npu-xpu") == "20261002/1338.ubuntu-npu-xpu"
    assert helpers["name_of"]("test-session.20261002-1338.x-2") == "20261002/1338.x-2"
    assert helpers["name_of"]("not-an-id") is None and helpers["name_of"]("2026/1338.x") is None
    assert helpers["tag_of"]("FGG-LENOVO-P14S") == "fgg-lenovo-p14s" and helpers["tag_of"]("Self Test") == "self-test"


def test_migrate_the_old_folders(session, cm, tmp_path):
    """The folders kept before 0.42.0 move into the two artifacts, and --remove_old removes them."""
    kind = "old-" + session.unique
    day, name = "20261001", f"1200.{kind}"
    old_log = tmp_path / "log" / ("cmeta-tests-" + day)
    old_tmp = tmp_path / "tmp" / ("cmeta-tests-" + day) / name
    (old_log / name).mkdir(parents=True)
    old_tmp.mkdir(parents=True)
    (old_tmp / "build.log").write_text("built\n", encoding="utf-8")
    (old_log / name / "result.json").write_text("{}", encoding="utf-8")
    rec = {"id": f"{day}/{name}", "type": kind, "title": "old one", "status": "passed",
           "started": "2026-10-01T12:00:00+02:00", "finished": "2026-10-01T12:05:00+02:00",
           "host": {"name": "host-a"}, "sandbox": str(old_tmp), "notes": [], "results": {"x": 1},
           "costs": {"wall_time_s": 300}, "attachments": [{"name": "result.json", "bytes": 2}]}
    (old_log / (name + ".json")).write_text(json.dumps(rec), encoding="utf-8")
    (old_log / (name + ".md")).write_text("# old\n", encoding="utf-8")

    r = session(migrate=True, remove_old=True, **{"from": str(tmp_path)})
    assert r["return"] == 0, r.get("error")
    new_id = f"{day}/{name}"
    assert r["migrated"] == [new_id]
    log = os.path.join(session.local, "log", "cmeta-aops-test-sessions", day, name)
    assert os.path.isfile(os.path.join(log, "session.md"))
    assert os.path.isfile(os.path.join(log, "attachments", "result.json"))
    with open(os.path.join(log, "session.json"), encoding="utf-8") as f:
        new = json.load(f)
    assert new["id"] == new_id and new["results"] == {"x": 1} and new["migrated_from"]["sandbox"] == str(old_tmp)
    assert new["sandbox"] == os.path.join(session.local, "tmp", "cmeta-aops-test-sessions", day, name)
    assert os.path.isfile(os.path.join(new["sandbox"], "build.log"))
    assert [x["id"] for x in session(list=True, type=kind)["sessions"]] == [new_id]
    assert not (tmp_path / "log").exists() and not (tmp_path / "tmp").exists()

    again = session(migrate=True, **{"from": str(tmp_path)})
    assert again["return"] == 0 and again["migrated"] == []


def transcript_line(t, request, model="claude-opus-5-5", output=100, cache_read=1000):
    return json.dumps({"type": "assistant", "timestamp": t, "requestId": request,
                       "message": {"model": model, "usage": {"input_tokens": 2, "output_tokens": output,
                                   "cache_creation_input_tokens": 10, "cache_read_input_tokens": cache_read}}})


def write_transcripts(root, session_id, start, minutes_before, minutes_inside):
    """A main transcript and a subagent's, with requests before and inside the session."""
    project = root / "claude" / "projects" / "D---proj"
    (project / session_id / "subagents").mkdir(parents=True)
    def utc(minutes):
        t = (start + datetime.timedelta(minutes=minutes)).astimezone(datetime.timezone.utc)
        return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    main = [transcript_line(utc(-minutes_before), "req-before")]
    # One request logged twice (one line per content block): counted once
    main += [transcript_line(utc(minutes_inside), "req-1"), transcript_line(utc(minutes_inside), "req-1"),
             json.dumps({"type": "user", "timestamp": utc(minutes_inside), "message": {"content": "hi"}})]
    (project / (session_id + ".jsonl")).write_text("\n".join(main) + "\n", encoding="utf-8")
    (project / session_id / "subagents" / "agent-x.jsonl").write_text(
        transcript_line(utc(minutes_inside), "req-2", model="claude-haiku-4-5-20251001", output=50) + "\n",
        encoding="utf-8")
    return project.parent


def test_claude_usage_counts_requests_once_in_the_window(helpers, tmp_path):
    start = datetime.datetime.now().astimezone()
    projects = write_transcripts(tmp_path, "sess-1", start, minutes_before=5, minutes_inside=0)
    usage = helpers["claude_usage"]("sess-1", start - datetime.timedelta(minutes=1),
                                    start + datetime.timedelta(minutes=1), str(projects))
    assert usage["requests"] == 2
    assert usage["output_tokens"] == 150 and usage["input_tokens"] == 4
    assert usage["cache_read_input_tokens"] == 2000 and usage["cache_creation_input_tokens"] == 20
    assert set(usage["by_model"]) == {"claude-opus-5-5", "claude-haiku-4-5-20251001"}
    assert helpers["claude_usage"]("other", start, start, str(projects)) is None

    prices = {"claude-opus-5-5": {"input": 1, "output": 1000, "cache_write": 0, "cache_read": 1000},
              "claude-haiku-4-5-20251001": {"output": 2000}}
    # opus: 100 out * 1000/1e6 + 1000 cache-read * 1000/1e6 + 2 in * 1/1e6; haiku: 50 out * 2000/1e6
    assert helpers["usage_cost"](usage, prices) == round(0.1 + 1.0 + 0.000002 + 0.1, 2)
    assert helpers["usage_cost"](usage, {"claude-opus-5-5": prices["claude-opus-5-5"]}) is None


def test_finish_records_the_agent_usage(session, tmp_path):
    r = session(start=True, type="usage")
    started = datetime.datetime.fromisoformat(r["record"]["started"])
    # The session's own transcripts (CLAUDE_CONFIG_DIR points at tmp_path/claude)
    write_transcripts(tmp_path, "0000-test-session", started, minutes_before=30, minutes_inside=0)
    r = session(finish=True, id=r["id"])
    assert r["return"] == 0, r.get("error")
    usage = r["record"]["costs"]["agent_usage"]
    assert usage["requests"] == 2 and usage["output_tokens"] == 150
    md = open(r["log"], encoding="utf-8").read()
    assert "Agent: 2 requests; 150 output, 4 input, 20 cache-write and 2,000 cache-read tokens" in md

