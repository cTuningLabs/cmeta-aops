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


# ---------------------------------------------------------------------------------------------- "in the meantime"
# What was applied, and which runs of the artifact started or ended, while a run lasted is read from the records the
# snapshot kept - never from a file time or a recorded time against this machine's clock. The files of a project can
# be stamped by another clock (a Windows drive inside WSL2, a network share, a container), in another time zone, or
# to the whole second only: the offsets below stand for those, in both directions.
HOUR = 3600
OFFSETS = [-26 * HOUR, -HOUR, -2, 0, 2, HOUR, 26 * HOUR]


def iso(seconds_from_now = 0):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + seconds_from_now))


def stamp_file(path, offset):
    """Give a file the time a drive whose clock is `offset` seconds away from this machine's would have given it."""
    t = time.time() + offset
    os.utime(str(path), (t, t))


def approve(world, stamp = "S2"):
    """The user applies two staged proposals: one.md is replaced, two.md is removed. -> the record's path."""
    put(world["dir"] / "memory" / "one.md", "one, approved\n")
    put(world["dir"] / "memory" / "two.md.delete", "")
    targets, unknown = P.staged(world["pending"], world["sources"])
    records = [P.apply(i) for i in targets[0]["items"]]
    for i in targets[0]["items"]:
        P.clear(i, targets[0]["dir"])
    P.finish_target(targets[0]["dir"], world["pending"])
    return P.record_applied(world["ai"], stamp, "some::project", records)


def test_the_snapshot_keeps_the_records_beside_the_files(world):
    ai = pathlib.Path(world["ai"])
    record = approve(world, "S0")
    put(ai / "log" / "c1.conversation.json", json.dumps({"id": "c1", "runs": [
        {"stamp": "20260101-100000", "started": "2026-01-01T10:00:00", "finished": "2026-01-01T11:00:00"},
        {"stamp": "20260102-100000", "started": "2026-01-02T10:00:00"}, "not a run"]}))
    put(ai / "log" / "c2.conversation.json", "{ not JSON")
    put(ai / "log" / "c3.conversation.json", json.dumps({"id": "c3", "runs": 5}))
    snap = P.snapshot(world["ai"])
    # still the plain mapping of the guarded files ...
    assert isinstance(snap, dict) and sorted(snap) == ["memory/MEMORY.md", "memory/one.md", "skills/s1/SKILL.md"]
    # ... and what the records said
    assert snap.applied == {"S0.applied.json": P._sha(pathlib.Path(record).read_bytes())}
    assert snap.runs == {"c1.conversation.json": {"20260101-100000 2026-01-01T10:00:00": "2026-01-01T11:00:00",
                                                  "20260102-100000 2026-01-02T10:00:00": ""},
                         "c3.conversation.json": {}}
    # an artifact without a log folder
    bare = pathlib.Path(world["ai"]).parent.parent / "bare" / "!AI"
    put(bare / "memory" / "a.md", "a\n")
    snap = P.snapshot(str(bare))
    assert sorted(snap) == ["memory/a.md"] and snap.applied == {} and snap.runs == {}


@pytest.mark.parametrize("file_offset", OFFSETS)
@pytest.mark.parametrize("clock_offset", [-HOUR, 0, HOUR])
def test_what_was_applied_meanwhile_is_known_whatever_the_file_times_say(world, file_offset, clock_offset):
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: P.snapshot(world["ai"])}
    record = approve(world)
    stamp_file(record, file_offset)
    t0 = time.time() + clock_offset
    assert P.guard(world["sources"], snap, t0, t0 + 1, "restore", world["pending"], "S3") == ([], [])
    assert read(ai / "memory" / "one.md") == "one, approved\n" and not (ai / "memory" / "two.md").exists()
    assert not os.path.exists(world["pending"])


@pytest.mark.parametrize("file_offset", OFFSETS)
@pytest.mark.parametrize("clock_offset", [-HOUR, 0, HOUR])
def test_a_record_from_before_the_run_approves_nothing_the_run_does(world, file_offset, clock_offset):
    """The user approved a change; later it was taken back by hand. A run that makes the same change again - the same
    bytes, the same removal - has made a direct change: the record it matches was there before the run."""
    ai = pathlib.Path(world["ai"])
    record = approve(world)
    put(ai / "memory" / "one.md", "one\n")
    put(ai / "memory" / "two.md", "two\n")
    stamp_file(record, file_offset)
    snap = {world["ai"]: P.snapshot(world["ai"])}
    put(ai / "memory" / "one.md", "one, approved\n")
    (ai / "memory" / "two.md").unlink()
    t0 = time.time() + clock_offset
    notes, records = P.guard(world["sources"], snap, t0, t0 + 1, "restore", world["pending"], "S3")
    assert sorted((r["rel"], r["what"]) for r in records) == [("memory/one.md", "changed"), ("memory/two.md", "deleted")]
    assert read(ai / "memory" / "one.md") == "one\n" and read(ai / "memory" / "two.md") == "two\n"
    assert read(world["dir"] / "memory" / "one.md") == "one, approved\n" and (world["dir"] / "memory" / "two.md.delete").exists()


def test_a_record_that_reads_differently_after_the_run_was_written_since(world):
    ai = pathlib.Path(world["ai"])
    record = put(ai / "log" / "S2.applied.json", json.dumps({"applied": [{"rel": "memory/two.md", "action": "change", "sha1": "0" * 40}]}))
    before = os.stat(str(record))
    snap = {world["ai"]: P.snapshot(world["ai"])}
    put(ai / "memory" / "one.md", "one, approved\n")
    put(record, json.dumps({"applied": [{"rel": "memory/one.md", "action": "change", "sha1": P._sha(b"one, approved\n")}]}))
    os.utime(str(record), ns = (before.st_atime_ns, before.st_mtime_ns))        # the same name and the same time
    assert P.guard(world["sources"], snap, time.time(), time.time(), "restore", world["pending"], "S3") == ([], [])
    assert read(ai / "memory" / "one.md") == "one, approved\n"


def test_one_of_two_changes_was_applied_meanwhile_and_the_other_is_direct(world):
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: P.snapshot(world["ai"])}
    record = approve(world)
    stamp_file(record, -HOUR)
    put(ai / "skills" / "s1" / "SKILL.md", "skill, edited by the session\n")
    notes, records = P.guard(world["sources"], snap, time.time(), time.time(), "restore", world["pending"], "S3")
    assert [(r["rel"], r["what"]) for r in records] == [("skills/s1/SKILL.md", "changed")]
    assert read(ai / "skills" / "s1" / "SKILL.md") == "skill\n" and read(ai / "memory" / "one.md") == "one, approved\n"
    assert not (ai / "memory" / "two.md").exists()


def test_a_record_caught_while_it_is_written_is_read_again(world, monkeypatch):
    ai = pathlib.Path(world["ai"])
    monkeypatch.setattr(P, "READ_PAUSE", 0)
    snap = {world["ai"]: P.snapshot(world["ai"])}
    record = approve(world)
    real, calls = P._read, []

    def half_written_first(path):
        data = real(path)
        if os.path.normcase(str(path)) == os.path.normcase(str(record)):
            calls.append(path)
            if len(calls) == 1:
                return data[:len(data) // 2]
        return data
    monkeypatch.setattr(P, "_read", half_written_first)
    assert P.guard(world["sources"], snap, time.time(), time.time(), "restore", world["pending"], "S3") == ([], [])
    assert len(calls) == 2 and read(ai / "memory" / "one.md") == "one, approved\n"

    # a record that never becomes readable approves nothing, and stops nothing
    monkeypatch.setattr(P, "_read", real)
    put(record, "{ half a rec")
    notes, records = P.guard(world["sources"], snap, time.time(), time.time(), "report", world["pending"], "S4")
    assert sorted(r["rel"] for r in records) == ["memory/one.md", "memory/two.md"]


def test_an_apply_that_lands_between_the_two_reads_of_the_snapshot(world, monkeypatch):
    """The snapshot reads the records, then the files. An apply right after it read the files - their new versions
    are not in the snapshot, the record is not among the known ones - is what the user approved meanwhile. (Reading
    the files first would know the record of files it had not seen.)"""
    ai = pathlib.Path(world["ai"])
    real, done = P._walk, []

    def walk_then_apply(ai_dir):
        for item in real(ai_dir):
            yield item
        if not done:
            done.append(approve(world))
    monkeypatch.setattr(P, "_walk", walk_then_apply)
    snap = {world["ai"]: P.snapshot(world["ai"])}
    assert done and snap[world["ai"]]["memory/one.md"][1] == b"one\n" and snap[world["ai"]].applied == {}
    assert P.guard(world["sources"], snap, time.time(), time.time(), "restore", world["pending"], "S3") == ([], [])
    assert read(ai / "memory" / "one.md") == "one, approved\n"


@pytest.mark.parametrize("clock_offset", [-26 * HOUR, -HOUR, 0, HOUR, 26 * HOUR])
def test_a_run_of_the_artifact_that_started_or_ended_meanwhile_is_told_by_its_records(world, clock_offset):
    """clock_offset: how far the clock that wrote the artifact's records is from the one of the run that checks -
    another machine on the same files, or the same files read in another time zone."""
    ai = pathlib.Path(world["ai"])
    conv = ai / "log" / "c1.conversation.json"
    old = {"stamp": "20260101-100000", "started": "2026-01-01T10:00:00", "finished": "2026-01-01T11:00:00"}

    def guard_after(change):
        put(ai / "memory" / "one.md", "one\n")
        snap = {world["ai"]: P.snapshot(world["ai"])}
        change()
        put(ai / "memory" / "one.md", "one, written meanwhile\n")
        t0 = time.time()
        notes, records = P.guard(world["sources"], snap, t0, t0 + 1, "restore", world["pending"], "S4")
        return [r["outcome"] for r in records]

    def left_alone(outcomes):
        return (len(outcomes) == 1 and "left" in outcomes[0] and read(ai / "memory" / "one.md") == "one, written meanwhile\n"
                and not os.path.exists(world["pending"]))

    # a run that started meanwhile, in a record of its own or as one more run of a conversation
    put(conv, json.dumps({"id": "c1", "runs": [old]}))
    started = {"stamp": "S-new", "started": iso(clock_offset)}
    assert left_alone(guard_after(lambda: put(ai / "log" / "c2.conversation.json", json.dumps({"id": "c2", "runs": [started]}))))
    (ai / "log" / "c2.conversation.json").unlink()
    assert left_alone(guard_after(lambda: put(conv, json.dumps({"id": "c1", "runs": [old, started]}))))

    # a run that was going on at the snapshot and ended meanwhile ...
    put(conv, json.dumps({"id": "c1", "runs": [old, started]}))
    ended = dict(started, finished = iso(clock_offset + 5))
    assert left_alone(guard_after(lambda: put(conv, json.dumps({"id": "c1", "runs": [old, ended]}))))
    # ... and one that is still going on (no end): it counts as running, wherever its start lies for this clock
    put(conv, json.dumps({"id": "c1", "runs": [old, started]}))
    assert left_alone(guard_after(lambda: None))

    # a run that had ended before the snapshot is over, whatever its times say here: the guard does its work
    put(conv, json.dumps({"id": "c1", "runs": [old, {"stamp": "S-done", "started": iso(clock_offset - 5), "finished": iso(clock_offset + 5)}]}))
    outcomes = guard_after(lambda: None)
    assert len(outcomes) == 1 and "put back" in outcomes[0] and read(ai / "memory" / "one.md") == "one\n"
    assert read(world["dir"] / "memory" / "one.md") == "one, written meanwhile\n"


def test_a_run_without_an_end_stops_counting_after_two_days(world):
    ai = pathlib.Path(world["ai"])
    for hours, counts in ((1, True), (46, True), (50, False), (24 * 30, False)):
        put(ai / "log" / "c1.conversation.json", json.dumps({"id": "c1", "runs": [{"stamp": "S", "started": iso(-hours * HOUR)}]}))
        snap = P.snapshot(world["ai"])
        assert P.own_session_ran(world["ai"], time.time(), time.time(), snap.runs) is counts, hours
    # a start that cannot be read counts for nothing
    put(ai / "log" / "c1.conversation.json", json.dumps({"id": "c1", "runs": [{"stamp": "S", "started": "some day"}]}))
    assert not P.own_session_ran(world["ai"], time.time(), time.time(), P.own_runs(world["ai"]))


def test_a_conversation_record_changed_without_a_run_is_no_session(world):
    """A summary, a new title: the record is rewritten, its runs are what they were."""
    ai = pathlib.Path(world["ai"])
    runs = [{"stamp": "20260101-100000", "started": "2026-01-01T10:00:00", "finished": "2026-01-01T11:00:00"}]
    put(ai / "log" / "c1.conversation.json", json.dumps({"id": "c1", "title": "a", "runs": runs}))
    snap = {world["ai"]: P.snapshot(world["ai"])}
    put(ai / "log" / "c1.conversation.json", json.dumps({"id": "c1", "title": "b", "summary": {"runs": 1}, "runs": runs}))
    put(ai / "memory" / "one.md", "edited\n")
    notes, records = P.guard(world["sources"], snap, time.time(), time.time(), "restore", world["pending"], "S5")
    assert "put back" in records[0]["outcome"] and read(ai / "memory" / "one.md") == "one\n"


def test_a_snapshot_without_the_records_falls_back_to_the_times(world):
    """A plain mapping of the files (a snapshot taken by other code): the file time of an "applied" record and the
    recorded times of a run are compared with the clock readings the guard is given, as before."""
    ai = pathlib.Path(world["ai"])
    snap = {world["ai"]: dict(P.snapshot(world["ai"]))}
    t0 = time.time()
    record = approve(world)
    stamp_file(record, HOUR)                        # by its time, written after the snapshot
    assert P.guard(world["sources"], snap, t0, time.time(), "restore", world["pending"], "S3") == ([], [])
    stamp_file(record, -HOUR)                       # by its time, written before it: no word for these changes
    notes, records = P.guard(world["sources"], snap, t0, time.time(), "report", world["pending"], "S3")
    assert sorted(r["rel"] for r in records) == ["memory/one.md", "memory/two.md"]
    put(ai / "log" / "c1.conversation.json", json.dumps({"id": "c1", "runs": [{"started": iso(-5)}]}))
    notes, records = P.guard(world["sources"], snap, t0, time.time(), "report", world["pending"], "S3")
    assert all("left" in r["outcome"] for r in records) and len(records) == 2
    assert P.applied_since(world["ai"], t0 + 2 * HOUR) == set() and len(P.applied_since(world["ai"], t0 - 2 * HOUR)) == 2


def test_decisions_recorded_at_once_under_one_stamp_each_keep_their_record(world):
    """Two projects started within the same second carry the same stamp; each may record in the artifact they both
    use at the same moment. The name of a record is taken by creating the file."""
    import threading
    gate, made = threading.Barrier(8), []

    def record(n):
        gate.wait()
        made.append(P.record_applied(world["ai"], "S9", "project-%d" % n, [{"rel": "memory/%d.md" % n, "action": "new", "sha1": "x"}]))

    workers = [threading.Thread(target = record, args = (n,)) for n in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    names = sorted(os.path.basename(p) for p in made)
    assert names == sorted(["S9.applied.json"] + ["S9-%d.applied.json" % n for n in range(2, 9)])
    written = sorted(json.loads(read(p))["from_project"] for p in made)
    assert written == ["project-%d" % n for n in range(8)], "no record was written over another"


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
