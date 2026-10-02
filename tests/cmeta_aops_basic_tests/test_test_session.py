"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The test-session task: a dated sandbox under <root>/tmp and a log under <root>/log that stays,
with the agent, the results and the costs. Offline; every test uses its own root.
"""

import datetime
import json
import os
import re

import pytest

GENERATOR = {"method": "agent", "agent": "Claude Code 2.1.286", "model": "claude-opus-5-5", "effort": "max"}


@pytest.fixture
def session(cm, tmp_path, monkeypatch):
    """Run test-session with a throwaway root and a known agent."""
    monkeypatch.setenv("CMETA_GENERATOR", json.dumps(GENERATOR))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "0000-test-session")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))  # no transcripts unless a test writes them
    monkeypatch.delenv("CMETA_TESTS_ROOT", raising=False)

    def run(**params):
        request = {"category": "task", "command": "run", "arg1": "test-session",
                   "root": str(tmp_path), "con": False, "quiet": True}
        request.update(params)
        return cm.access(request)

    run.root = tmp_path
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
    assert re.fullmatch(r"\d{8}/\d{4}\.self-test", r["id"])
    date, name = r["id"].split("/")
    assert r["sandbox"] == os.path.join(str(session.root), "tmp", "cmeta-tests-" + date, name)
    assert os.path.isdir(r["sandbox"])
    assert os.path.isfile(r["log"]) and r["log"].endswith(name + ".md")

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
    kept = os.path.join(os.path.dirname(r["log"]), sid.split("/")[1], "bench.txt")
    assert os.path.isfile(kept)
    assert rec["attachments"][0]["name"] == "bench.txt"

    md = open(r["log"], encoding="utf-8").read()
    assert "| cuda_tps | 157.3 |" in md
    assert "Agent tokens (reported): 1,200" in md and "Agent cost (reported): $0.5" in md
    assert "gpu_minutes: 2" in md
    assert "bench.txt" in md


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
    kept = session(start=True, type="keepme")
    small = session(start=True, type="small")
    running = session(start=True, type="running")
    assert session(finish=True, id=kept["id"], keep=True, max_keep_mib="0")["return"] == 0
    assert session(finish=True, id=small["id"])["return"] == 0
    assert os.path.isdir(small["sandbox"]), "a small sandbox stays after finish"

    listed = session(list=True)
    assert listed["return"] == 0
    ids = [s["id"] for s in listed["sessions"]]
    assert {kept["id"], small["id"], running["id"]} <= set(ids)
    only = session(list=True, type="small")["sessions"]
    assert [s["id"] for s in only] == [small["id"]]
    assert session()["sessions"], "listing is the default action"

    r = session(prune=True)
    assert r["return"] == 0
    assert r["pruned"] == [small["id"]]
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

