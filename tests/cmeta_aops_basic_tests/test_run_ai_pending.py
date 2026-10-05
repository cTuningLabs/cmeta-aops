"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The run-ai task, pending.py: the proposals a run stages for the artifacts its project uses, and the guard that keeps
those artifacts read-only for a run. Offline: plain folders in a temporary directory - no cMeta, no harness.
"""

import importlib.util
import json
import os
import pathlib
import time

import pytest

# tests/cmeta_aops_basic_tests/<this file> -> the repository root is two levels up; the module is plain Python
# (standard library only), loaded by its path and not registered in sys.modules
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("run_ai_pending_under_test", str(REPO_ROOT / "task" / "run-ai" / "pending.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

LABEL = "project,1d3c5e7f9a2b4c6d::shared-rules,0a1b2c3d4e5f6a7b"


def put(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return path


@pytest.fixture
def world(tmp_path):
    """A project and one used artifact, each with an !AI folder."""
    ai = tmp_path / "used" / "!AI"
    put(ai / "memory" / "MEMORY.md", "- [One](one.md) - first\n- [Two](two.md) - second\n")
    put(ai / "memory" / "one.md", "one\n")
    put(ai / "memory" / "two.md", "two\n")
    put(ai / "skills" / "s1" / "SKILL.md", "skill\n")
    put(ai / "log" / "x.run.md", "a log\n")
    pending = tmp_path / "project" / "!AI" / "pending"
    key = P.stage_key(LABEL)
    return {"ai": str(ai), "pending": str(pending), "key": key, "dir": pending / key,
            "sources": [{"label": LABEL, "key": key, "ai": str(ai)}]}


def read(path):
    return pathlib.Path(path).read_bytes().decode("utf-8")


# ---------------------------------------------------------------------------------------------- names
def test_stage_key_is_the_alias_and_the_uid():
    assert P.stage_key(LABEL) == "shared-rules--0a1b2c3d4e5f6a7b"
    assert P.stage_key("task,1234::_Check pages: now and then, again,abcd") == "_Check-pages-now-and-then-again--abcd"
    assert P.stage_key("tool::plain") == "plain"                              # no UID known
    assert P.stage_key("", os.path.join("x", "My Folder")) == "My-Folder"   # no cRef at all: the folder name
    assert P.stage_key("c,1::...,77") == "artifact--77"                       # nothing usable in the alias


# ---------------------------------------------------------------------------------------------- the guard
def test_snapshot_sees_memory_and_skills_only(world):
    snap = P.snapshot(world["ai"])
    assert sorted(snap) == ["memory/MEMORY.md", "memory/one.md", "memory/two.md", "skills/s1/SKILL.md"]
    put(pathlib.Path(world["ai"]) / "log" / "y.run.md", "another log\n")
    assert P.changes(snap, world["ai"]) == []


def test_changes_are_found(world):
    ai = pathlib.Path(world["ai"])
    snap = P.snapshot(world["ai"])
    put(ai / "memory" / "one.md", "one, edited\n")
    put(ai / "memory" / "three.md", "three\n")
    (ai / "memory" / "two.md").unlink()
    assert [(rel, what) for rel, what, sha in P.changes(snap, world["ai"])] == [
        ("memory/one.md", "changed"), ("memory/three.md", "added"), ("memory/two.md", "deleted")]


def test_guard_restore_puts_back_and_keeps_proposals(world):
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: P.snapshot(world["ai"])}
    t0 = time.time()
    put(ai / "memory" / "one.md", "one, edited\n")
    put(ai / "memory" / "three.md", "three\n")
    put(ai / "skills" / "s2" / "SKILL.md", "new skill\n")
    (ai / "memory" / "two.md").unlink()
    notes, records = P.guard(world["sources"], snap, t0, time.time(), "restore", world["pending"], "S1")

    # the artifact is as it was
    assert read(ai / "memory" / "one.md") == "one\n" and read(ai / "memory" / "two.md") == "two\n"
    assert not (ai / "memory" / "three.md").exists() and not (ai / "skills" / "s2").exists()
    assert P.changes(snap[world["ai"]], world["ai"]) == []
    # and nothing that was written is lost: it waits as proposals
    d = world["dir"]
    assert read(d / "memory" / "one.md") == "one, edited\n" and read(d / "memory" / "three.md") == "three\n"
    assert read(d / "skills" / "s2" / "SKILL.md") == "new skill\n" and (d / "memory" / "two.md.delete").exists()
    assert len(records) == 4 and all(r["staged"] for r in records) and notes

    # applying the proposals afterwards gives exactly what the session had written
    targets, unknown = P.staged(world["pending"], world["sources"])
    assert sorted((i["rel"], i["action"]) for i in targets[0]["items"]) == [
        ("memory/one.md", "change"), ("memory/three.md", "new"), ("memory/two.md", "delete"), ("skills/s2/SKILL.md", "new")]
    for i in targets[0]["items"]:
        assert P.apply(i)
    assert read(ai / "memory" / "one.md") == "one, edited\n" and not (ai / "memory" / "two.md").exists()
    assert read(ai / "skills" / "s2" / "SKILL.md") == "new skill\n"


def test_guard_report_touches_nothing(world):
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: P.snapshot(world["ai"])}
    put(ai / "memory" / "one.md", "one, edited\n")
    notes, records = P.guard(world["sources"], snap, time.time() - 1, time.time(), "report", world["pending"], "S1")
    assert read(ai / "memory" / "one.md") == "one, edited\n" and not os.path.exists(world["pending"])
    assert [r["outcome"] for r in records] == ["reported"] and "reported only" in notes[0]


def test_guard_ask_keeps_on_the_users_word_and_records_it(world):
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: P.snapshot(world["ai"])}
    put(ai / "memory" / "one.md", "one, pulled from the remote\n")
    (ai / "memory" / "two.md").unlink()
    asked = []

    def ask(source, ch):
        asked.append((source["label"], [(rel, what) for rel, what, sha in ch]))
        return True
    notes, records = P.guard(world["sources"], snap, time.time() - 1, time.time(), "ask", world["pending"], "S6", ask, "the::project")
    assert asked == [(LABEL, [("memory/one.md", "changed"), ("memory/two.md", "deleted")])]
    assert read(ai / "memory" / "one.md") == "one, pulled from the remote\n" and not (ai / "memory" / "two.md").exists()
    assert not os.path.exists(world["pending"]) and all("kept" in r["outcome"] for r in records)
    rec = json.loads(read(ai / "log" / "S6.applied.json"))
    assert rec["from_project"] == "the::project" and "context guard" in rec["by"] and len(rec["applied"]) == 2
    # a second decision under the same stamp gets its own record
    assert P.record_applied(world["ai"], "S6", "p", []).endswith("S6-2.applied.json")


def test_guard_ask_says_no_or_has_nobody_to_ask(world):
    ai = pathlib.Path(world["ai"])
    for ask in (lambda source, ch: False, None):
        snap = {world["ai"]: P.snapshot(world["ai"])}
        put(ai / "memory" / "one.md", "one, edited\n")
        notes, records = P.guard(world["sources"], snap, time.time() - 1, time.time(), "ask", world["pending"], "S7", ask)
        assert read(ai / "memory" / "one.md") == "one\n" and read(world["dir"] / "memory" / "one.md") == "one, edited\n"
        assert "put back" in records[0]["outcome"]
        (world["dir"] / "memory" / "one.md").unlink()


def test_guard_no_change_no_notes(world):
    snap = {world["ai"]: P.snapshot(world["ai"])}
    assert P.guard(world["sources"], snap, time.time() - 1, time.time(), "restore", world["pending"], "S1") == ([], [])
    assert not os.path.exists(world["pending"])


def test_guard_keeps_a_staged_proposal_and_sets_the_direct_change_aside(world):
    ai = pathlib.Path(world["ai"])
    put(world["dir"] / "memory" / "one.md", "one, as proposed earlier\n")
    snap = {world["ai"]: P.snapshot(world["ai"])}
    put(ai / "memory" / "one.md", "one, edited directly\n")
    notes, records = P.guard(world["sources"], snap, time.time() - 1, time.time(), "restore", world["pending"], "S9")
    assert read(ai / "memory" / "one.md") == "one\n"
    assert read(world["dir"] / "memory" / "one.md") == "one, as proposed earlier\n"
    assert read(world["dir"] / "_direct-S9" / "memory" / "one.md") == "one, edited directly\n"
    # what is set aside is not a proposal: only the earlier one is listed
    targets, unknown = P.staged(world["pending"], world["sources"])
    assert [(i["rel"], i["action"]) for i in targets[0]["items"]] == [("memory/one.md", "change")]


def test_what_apply_pending_wrote_meanwhile_is_no_direct_change(world):
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: P.snapshot(world["ai"])}
    t0 = time.time()
    put(world["dir"] / "memory" / "one.md", "one, approved\n")
    put(world["dir"] / "memory" / "two.md.delete", "")
    targets, unknown = P.staged(world["pending"], world["sources"])
    records = [P.apply(i) for i in targets[0]["items"]]
    P.record_applied(world["ai"], "S2", "some::project", records)
    notes, recs = P.guard(world["sources"], snap, t0, time.time(), "restore", world["pending"], "S3")
    assert (notes, recs) == ([], [])
    assert read(ai / "memory" / "one.md") == "one, approved\n" and not (ai / "memory" / "two.md").exists()


def test_an_artifact_that_ran_its_own_session_is_left_alone(world):
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: P.snapshot(world["ai"])}
    t0 = time.time()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    put(ai / "log" / "c1.conversation.json", json.dumps({"id": "c1", "runs": [{"started": now}]}))     # still running
    put(ai / "memory" / "one.md", "one, written by its own session\n")
    notes, records = P.guard(world["sources"], snap, t0, time.time() + 1, "restore", world["pending"], "S4")
    assert read(ai / "memory" / "one.md") == "one, written by its own session\n" and not os.path.exists(world["pending"])
    assert "left" in records[0]["outcome"]


def test_an_old_run_of_the_artifact_does_not_switch_the_guard_off(world):
    ai = pathlib.Path(world["ai"])
    put(ai / "log" / "c0.conversation.json", json.dumps({"id": "c0", "runs": [
        {"started": "2026-01-01T10:00:00", "finished": "2026-01-01T11:00:00"}, {"started": "2026-01-02T10:00:00"}]}))
    assert not P.own_session_ran(world["ai"], time.time() - 60, time.time())
    snap = {world["ai"]: P.snapshot(world["ai"])}
    put(ai / "memory" / "one.md", "edited\n")
    P.guard(world["sources"], snap, time.time() - 1, time.time(), "restore", world["pending"], "S5")
    assert read(ai / "memory" / "one.md") == "one\n"


# ---------------------------------------------------------------------------------------------- the proposals
def test_staged_names_the_action_of_every_proposal(world):
    d = world["dir"]
    put(d / "_note.md", "why\nsecond line\n")
    put(d / "memory" / "one.md", "one\n")                          # the artifact has it already
    put(d / "memory" / "two.md", "two, better\n")
    put(d / "memory" / "four.md", "four\n")
    put(d / "memory" / "MEMORY.md.append", "- [Two](two.md) - second\n- [Four](four.md) - fourth\n\n")
    put(d / "memory" / "gone.md.delete", "")                        # nothing to remove
    put(d / "skills" / "s1" / "SKILL.md.delete", "")
    put(d / "log" / "x.md", "not allowed\n")
    put(d / "top.md", "not allowed either\n")
    put(d / "_direct-S1" / "memory" / "one.md", "set aside\n")
    put(pathlib.Path(world["pending"]) / "stranger--00" / "memory" / "a.md", "whose?\n")
    targets, unknown = P.staged(world["pending"], world["sources"])
    assert unknown == ["stranger--00"] and len(targets) == 1 and targets[0]["note"] == "why\nsecond line"
    got = {i["rel"]: (i["action"], bool(i["problem"])) for i in targets[0]["items"]}
    assert got == {"memory/one.md": ("same", False), "memory/two.md": ("change", False), "memory/four.md": ("new", False),
                   "memory/MEMORY.md": ("append", False), "memory/gone.md": ("same", False),
                   "skills/s1/SKILL.md": ("delete", False), "log/x.md": ("", True), "top.md": ("", True)}
    append = [i for i in targets[0]["items"] if i["action"] == "append"][0]
    assert append["lines"] == ["- [Four](four.md) - fourth"]       # the line the index has is skipped
    assert P.count(world["pending"], world["sources"]) == 4


def test_apply_whole_file_append_and_delete(world):
    ai = pathlib.Path(world["ai"])
    put(ai / "memory" / "MEMORY.md", b"- [One](one.md) - first\r\n- [Two](two.md) - second")       # CRLF, no last line end
    d = world["dir"]
    put(d / "_note.md", "why\n")
    put(d / "memory" / "four.md", "four\n")
    put(d / "memory" / "MEMORY.md.append", "- [Four](four.md) - fourth\n")
    put(d / "skills" / "s1" / "SKILL.md.delete", "")
    targets, unknown = P.staged(world["pending"], world["sources"])
    t = targets[0]
    records = []
    for i in t["items"]:
        r = P.apply(i)
        assert r and r["rel"] == i["rel"]
        records.append(r)
        P.clear(i, t["dir"])
    assert read(ai / "memory" / "four.md") == "four\n"
    assert (ai / "memory" / "MEMORY.md").read_bytes() == b"- [One](one.md) - first\r\n- [Two](two.md) - second\r\n- [Four](four.md) - fourth\r\n"
    assert not (ai / "skills" / "s1").exists()                     # the emptied skill folder goes with its file
    fp = P.record_applied(world["ai"], "S7", LABEL, records)
    rec = json.loads(read(fp))
    assert [(e["rel"], e["action"]) for e in rec["applied"]] == [("memory/MEMORY.md", "append"), ("memory/four.md", "new"), ("skills/s1/SKILL.md", "delete")]
    P.finish_target(t["dir"], world["pending"])
    assert not os.path.exists(world["pending"])                    # nothing left: the staging folders are gone
    # a second look finds nothing to do
    assert P.staged(world["pending"], world["sources"]) == ([], [])


def test_append_to_a_file_that_does_not_exist_creates_it(world):
    put(world["dir"] / "memory" / "notes.md.append", "first line\n")
    targets, unknown = P.staged(world["pending"], world["sources"])
    item = targets[0]["items"][0]
    assert item["action"] == "new" and P.diff(item) == ["    + first line"]
    P.apply(item)
    assert read(pathlib.Path(world["ai"]) / "memory" / "notes.md") == "first line\n"


def test_same_and_refused_proposals_are_not_applied(world):
    put(world["dir"] / "memory" / "one.md", "one\n")
    put(world["dir"] / "log" / "x.md", "no\n")
    targets, unknown = P.staged(world["pending"], world["sources"])
    assert [P.apply(i) for i in targets[0]["items"]] == [None, None]
    assert not (pathlib.Path(world["ai"]) / "log" / "x.md").exists()


def test_diff_lines(world):
    put(world["dir"] / "memory" / "one.md", "one\nand more\n")
    put(world["dir"] / "memory" / "bin.md", b"\x00\x01\x02")
    put(world["dir"] / "memory" / "two.md.delete", "")
    targets, unknown = P.staged(world["pending"], world["sources"])
    by = {i["rel"]: P.diff(i) for i in targets[0]["items"]}
    assert any(x.strip() == "+and more" for x in by["memory/one.md"])
    assert by["memory/bin.md"][0].strip().startswith("binary file")
    assert "removed" in by["memory/two.md"][0]


def test_a_file_too_large_to_keep_is_reported_not_restored(world, monkeypatch):
    monkeypatch.setattr(P, "MAX_KEEP", 2)
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: P.snapshot(world["ai"])}
    put(ai / "memory" / "one.md", "one, edited\n")
    notes, records = P.guard(world["sources"], snap, time.time() - 1, time.time(), "restore", world["pending"], "S8")
    assert "NOT put back" in records[0]["outcome"] and read(ai / "memory" / "one.md") == "one, edited\n"
    assert read(world["dir"] / "memory" / "one.md") == "one, edited\n"
