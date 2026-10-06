"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The run-ai task, conversations.py: the conversation files of a project, the adapters of the harnesses (how a session
is started, resumed, found and exported) and the transcript. Offline: the session stores are small files written
here in the layout each harness uses - no harness runs.
"""

import importlib.util
import json
import os
import pathlib

import pytest

# the module is plain Python (standard library only), loaded by its path and not registered in sys.modules
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("run_ai_conversations_under_test", str(REPO_ROOT / "task" / "run-ai" / "conversations.py"))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

SID = "5ab0c0de-1234-4abc-8def-0123456789ab"


def put(path, lines):
    path = pathlib.Path(path)
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text("".join(json.dumps(x) + "\n" if not isinstance(x, str) else x for x in lines), encoding = "utf-8")
    return path


# ---------------------------------------------------------------------------------------------- the conversation files
def conversation(log_dir, cid, title = "a title", updated = None):
    conv = C.new_conversation(str(log_dir), cid, str(log_dir.parent), "project::p", title)
    C.save_conversation(conv)
    if updated:      # save_conversation stamps "now": write the wanted time straight into the file
        data = json.loads(pathlib.Path(conv["_path"]).read_text(encoding = "utf-8"))
        data["updated"] = updated
        pathlib.Path(conv["_path"]).write_text(json.dumps(data), encoding = "utf-8")
    return conv


def test_conversations_are_listed_newest_activity_first_and_found_by_prefix(tmp_path):
    log = tmp_path / "!AI" / "log"
    conversation(log, "20261004-181659", updated = "2026-10-06T08:00:00")      # the oldest one, continued last
    conversation(log, "20261005-090000", updated = "2026-10-05T09:10:00")
    conversation(log, "20261005-120000", updated = "2026-10-05T12:30:00")
    assert [c["id"] for c in C.list_conversations(str(log))] == ["20261004-181659", "20261005-120000", "20261005-090000"]

    assert C.find_conversation(str(log), "20261004-181659")[0]["id"] == "20261004-181659"
    assert C.find_conversation(str(log), "20261004")[0]["id"] == "20261004-181659"         # a prefix that matches one
    conv, error = C.find_conversation(str(log), "20261005")                                 # ... and one that matches two
    assert conv is None and "matches 2 conversations" in error
    conv, error = C.find_conversation(str(log), "2027")
    assert conv is None and "no conversation" in error and str(log) in error
    assert C.list_conversations(str(tmp_path / "nothing-here")) == []


def test_the_file_keeps_no_private_keys_and_the_title_comes_from_the_prompt(tmp_path):
    conv = conversation(tmp_path / "log", "20261005-090000")
    data = json.loads(pathlib.Path(conv["_path"]).read_text(encoding = "utf-8"))
    assert "_path" not in data and data["id"] == "20261005-090000" and data["runs"] == [] and data["sessions"] == {}
    assert C.transcript_path(conv).endswith("20261005-090000.transcript.md")
    assert C.title_from_prompt("  fix   the\ntests ", False, "s") == "fix the tests"
    assert C.title_from_prompt("x" * 200, False, "s") == "x" * 90 + "..."
    assert C.title_from_prompt("", True, "20261005-090000") == "interactive session 20261005-090000"
    assert C.title_from_prompt("", False, "20261005-090000") == "run 20261005-090000"


# ---------------------------------------------------------------------------------------------- the adapters
def test_how_each_harness_starts_and_resumes_a_session():
    assert C.harness_key("antigravity") == "agy" and C.harness_key("claude") == "claude"
    # run-ai chooses the session id for these, and learns it after the run for the others
    assert [h for h in ("claude", "codex", "opencode", "openclaw", "antigravity", "agy", "gemini") if C.chooses_id(h)] == ["claude", "openclaw", "gemini"]
    assert C.new_session_flags("claude", "ID", "20261005-090000", "my-app") == ["--session-id", "ID", "--name", "run-ai 20261005-090000 my-app"]
    assert C.new_session_flags("gemini", "ID", "c", "a") == ["--session-id", "ID"]
    assert C.new_session_flags("codex", "ID", "c", "a") == []
    assert C.resume_flags("claude", "ID") == ["--resume", "ID"]
    assert C.resume_flags("antigravity", "ID") == ["--conversation", "ID"]
    assert C.resume_flags("opencode", "ID") == ["--session", "ID"]
    assert C.resume_flags("openclaw", "ID") == ["--session-id", "ID"]
    assert C.resume_flags("gemini", "ID") == ["--resume", "ID"]
    assert C.resume_flags("codex", "ID") == []           # a sub-command of codex: run-codex --resume=<id>
    # OpenClaw's terminal UI takes the key of the session, not its id
    assert C.new_session_flags("openclaw", "ID", "c", "a", interactive = True) == ["--session", "agent:main:explicit:ID"]
    assert C.resume_flags("openclaw", "ID", interactive = True) == ["--session", "agent:main:explicit:ID"]
    assert C.resume_flags("claude", "ID", interactive = True) == ["--resume", "ID"]
    for h in ("claude", "codex", "agy", "opencode", "openclaw", "gemini"):
        assert C.native_store_hint(h)
    assert C.session_exists("some-new-harness", "ID", ".") is True      # unknown harness: let it try
    assert C.discover_session("some-new-harness", ".", 0, {"stats": {"session_id": "S"}}) == "S"
    assert len(C.new_id()) == 36


def test_claude_sessions_are_found_and_exported(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    project = tmp_path / "my project, with a comma"
    project.mkdir()
    folder = pathlib.Path(C.claude_project_dirs(str(project))[0])
    assert folder.parent == tmp_path / "claude" / "projects" and "," not in folder.name and " " not in folder.name
    put(folder / "sess-1.jsonl", [
        {"type": "user", "timestamp": "2026-10-05T07:00:00.000Z", "message": {"content": "what is in this folder?"}},
        {"type": "user", "isMeta": True, "message": {"content": "a caveat the user never typed"}},
        {"type": "user", "message": {"content": "<command-name>/model</command-name>"}},
        {"type": "assistant", "timestamp": "2026-10-05T07:00:05.000Z", "message": {"content": [
            {"type": "text", "text": "Let me look."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls   -la"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "a.txt"}]}},
        {"type": "assistant", "isSidechain": True, "message": {"content": "a subagent's turn"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "One file: a.txt."}]}},
        "not json at all\n",
    ])
    assert C.session_exists("claude", "sess-1", str(project)) and not C.session_exists("claude", "other", str(project))
    messages = C.export_session("claude", "sess-1", str(project))
    assert [(role, blocks) for role, ts, blocks in messages] == [
        ("user", [("text", "what is in this folder?")]),
        ("assistant", [("text", "Let me look."), ("tool", "Bash ls -la")]),
        ("assistant", [("text", "One file: a.txt.")])]
    assert messages[0][1]            # the UTC stamp, as local time
    assert C.export_session("claude", "other", str(project)) is None


def test_a_long_project_path_finds_the_folder_claude_code_shortened(tmp_path, monkeypatch):
    # Claude Code cuts a slug longer than 200 characters to 200 and appends "-<hash of the path>"; the hash depends on
    # its runtime, so run-ai takes the folders with the prefix - not one whose sessions ran in another folder
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    deep = tmp_path / ("d" * 120) / ("e" * 90)
    other = tmp_path / ("d" * 120) / ("e" * 90 + "-other")
    projects = tmp_path / "claude" / "projects"
    slug = C.re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(str(deep)))
    assert len(slug) > C.CLAUDE_SLUG_MAX
    assert C.claude_project_dirs(str(deep)) == []                       # nothing yet: no folder made up
    mine = projects / (slug[:C.CLAUDE_SLUG_MAX] + "-a1b2c3")
    theirs = projects / (slug[:C.CLAUDE_SLUG_MAX] + "-x0abcd")
    try:
        put(mine / "sess-1.jsonl", [{"type": "user", "cwd": str(deep), "message": {"content": "hello from deep"}}])
    except OSError:
        pytest.skip("this file system does not take paths this long (Windows without LongPathsEnabled)")
    put(theirs / "sess-2.jsonl", [{"type": "user", "cwd": str(other), "message": {"content": "hello from other"}}])
    (projects / slug[:C.CLAUDE_SLUG_MAX]).mkdir()                       # the bare prefix is no shortened slug
    found = [pathlib.Path(d) for d in C.claude_project_dirs(str(deep))]
    assert found == [mine]
    assert C.claude_session_file(str(deep), "sess-1") == str(mine / "sess-1.jsonl")
    assert C.claude_session_file(str(deep), "sess-2") == ""
    assert [b for role, ts, b in C.export_session("claude", "sess-1", str(deep))] == [[("text", "hello from deep")]]
    # a folder whose sessions say nothing about their directory (only a memory) is taken
    (mine / "sess-1.jsonl").unlink()
    (mine / "memory").mkdir()
    assert [pathlib.Path(d) for d in C.claude_project_dirs(str(deep))] == [mine]
    # a short path keeps its plain slug
    short = tmp_path / "short"
    assert C.claude_project_dirs(str(short))[0].endswith(C.re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(str(short))))


def test_openclaw_sessions_are_found_through_its_index_and_exported(tmp_path, monkeypatch):
    # OpenClaw 2026.6: <state>/agents/<agent>/sessions/<file>.jsonl and the index sessions.json (key -> session id);
    # a headless turn names the file after the id run-ai chose, its terminal UI after an id of its own
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path / "oc"))
    sessions = tmp_path / "oc" / "agents" / "main" / "sessions"
    headless, tui_key, tui_real = SID, "11111111-2222-4333-8444-555555555555", "99999999-8888-4777-8666-555555555555"
    put(sessions / (headless + ".jsonl"), [
        {"type": "session", "version": 3, "id": headless, "timestamp": "2026-10-05T21:17:24.445Z", "cwd": "C:\\ws"},
        {"type": "message", "timestamp": "2026-10-05T21:17:24.445Z", "message": {"role": "user", "content": "<!-- the context -->\n" + C.REQUEST_MARK + "\nRead notes.txt"}},
        {"type": "message", "timestamp": "2026-10-05T21:17:30.000Z", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Let me read it."}, {"type": "toolCall", "name": "read", "arguments": {"path": "D:/p/notes.txt"}}]}},
        {"type": "message", "message": {"role": "toolResult", "content": [{"type": "text", "text": "The mascot is a heron."}]}},
        {"type": "message", "timestamp": "2026-10-05T21:17:35.000Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "Heron."}]}},
        "not json\n"])
    put(sessions / (headless + ".trajectory.jsonl"), [{"traceSchema": "openclaw-trajectory", "type": "model.fallback_step"}])
    put(sessions / (tui_real + ".jsonl"), [{"type": "message", "message": {"role": "user", "content": "hello from the UI"}}])
    (sessions / "sessions.json").write_text(json.dumps({
        "agent:main:explicit:" + headless: {"sessionId": headless, "sessionFile": str(sessions / (headless + ".jsonl"))},
        "agent:main:explicit:" + tui_key: {"sessionId": tui_real}}), encoding = "utf-8")

    assert C.session_exists("openclaw", headless, ".") and not C.session_exists("openclaw", "nope", ".")
    messages = C.export_session("openclaw", headless, ".")
    assert [(role, blocks) for role, ts, blocks in messages] == [
        ("user", [("text", "<!-- the context -->\n" + C.REQUEST_MARK + "\nRead notes.txt")]),
        ("assistant", [("text", "Let me read it."), ("tool", "read D:/p/notes.txt")]),
        ("assistant", [("text", "Heron.")])]
    assert messages[0][1] and not messages[0][1].endswith("Z")         # local time
    # the key run-ai gave the terminal UI leads to the session it filed under its own id
    assert C.openclaw_session_id(tui_key) == tui_real
    assert C.openclaw_session_file(tui_key).endswith(tui_real + ".jsonl")
    assert C.export_session("openclaw", tui_key, ".")[0][2] == [("text", "hello from the UI")]
    assert C.openclaw_session_id("nope") == "" and C.export_session("openclaw", "nope", ".") is None


def test_the_transcript_keeps_the_request_not_what_run_ai_put_before_it():
    lines = C._render_messages([("user", "2026-10-05 23:00:00", [("text", "the hand-over\n# the orientation\n" + C.REQUEST_MARK + "\nwhich word?")]),
                                ("assistant", "", [("text", "Heron. " + C.REQUEST_MARK)])], {"user": "User", "assistant": "OpenClaw"})
    text = "\n".join(lines)
    assert "which word?" in text and "the hand-over" not in text and "# the orientation" not in text
    assert C.PREPENDED_NOTE in text
    assert "Heron. " + C.REQUEST_MARK in text           # an answer is kept as it is


def gemini_session(home, sid = SID, project = "my-app"):
    """A session file as Gemini CLI 0.62 writes it: a header line, the list of messages as a "$set", then single
    messages added to it - a streamed answer written again under its id as it grows."""
    context = {"id": "ctx", "timestamp": "2026-10-05T18:38:50.073Z", "type": "user",
               "content": [{"text": "<session_context>\nThis is the Gemini CLI. ..."}]}
    return put(pathlib.Path(home) / ".gemini" / "tmp" / project / "chats" / ("session-2026-10-05T18-38-%s.jsonl" % sid[:8]), [
        {"sessionId": sid, "projectHash": "e68f", "startTime": "2026-10-05T18:38:50.072Z", "kind": "main"},
        {"$set": {"messages": [context]}},
        {"id": "u1", "timestamp": "2026-10-05T18:38:50.156Z", "type": "user", "content": [{"text": "Which file is the largest?"}]},
        {"$set": {"lastUpdated": "2026-10-05T18:38:50.156Z"}},
        {"id": "g1", "timestamp": "2026-10-05T18:38:52.000Z", "type": "gemini", "content": "Let me",
         "toolCalls": [{"name": "run_shell_command", "args": {"command": "du -a   ."}}]},
        {"id": "g1", "timestamp": "2026-10-05T18:38:53.000Z", "type": "gemini", "content": "Let me check.",
         "toolCalls": [{"name": "run_shell_command", "args": {"command": "du -a   ."}}], "model": "gemini-3.1-pro-preview"},
        {"id": "i1", "type": "info", "content": "an update is available"},
        {"id": "g2", "timestamp": "2026-10-05T18:38:55.000Z", "type": "gemini", "content": "It is data.bin."},
        "a broken line\n",
    ])


def test_gemini_sessions_are_found_by_id_and_exported_once_per_message(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "home"))
    path = gemini_session(tmp_path / "home")
    gemini_session(tmp_path / "home", sid = "5ab0c0de-0000-0000-0000-000000000000", project = "another")   # the same first 8 characters
    assert C.gemini_home() == os.path.join(str(tmp_path / "home"), ".gemini")
    assert C.gemini_chat_file(SID) == str(path)
    assert C.session_exists("gemini", SID, ".") and not C.session_exists("gemini", "ffffffff-1234-4abc-8def-0123456789ab", ".")

    assert [m.get("id") for m in C.gemini_messages(str(path))] == ["ctx", "u1", "g1", "i1", "g2"]
    messages = C.export_session("gemini", SID, ".")
    assert [(role, blocks) for role, ts, blocks in messages] == [
        ("user", [("text", "Which file is the largest?")]),
        ("assistant", [("text", "Let me check."), ("tool", "run_shell_command du -a .")]),      # the last version of g1
        ("assistant", [("text", "It is data.bin.")])]
    assert messages[0][1] == C.local_ts("2026-10-05T18:38:50.156Z")        # the UTC stamp, as local time
    assert C.export_session("gemini", "ffffffff-1234-4abc-8def-0123456789ab", ".") is None


def test_gemini_message_list_replaced_by_a_later_set(tmp_path):
    path = put(tmp_path / "session.jsonl", [
        {"sessionId": "x"},
        {"$set": {"messages": [{"id": "a", "type": "user", "content": [{"text": "one"}]}]}},
        {"id": "b", "type": "gemini", "content": "two"},
        {"$set": {"messages": [{"id": "a", "type": "user", "content": [{"text": "one"}]},
                               {"id": "b", "type": "gemini", "content": "two, compressed"}]}},
    ])
    assert [(m["id"], m["content"] if isinstance(m["content"], str) else m["content"][0]["text"]) for m in C.gemini_messages(str(path))] == [
        ("a", "one"), ("b", "two, compressed")]


# ---------------------------------------------------------------------------------------------- the transcript
def test_transcript_has_a_segment_per_session_and_keeps_one_whose_store_is_gone(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "home"))
    project = tmp_path / "proj"
    log = project / "!AI" / "log"
    conv = C.new_conversation(str(log), "20261005-090000", str(project), "project,1::proj,2", "Which file is the largest?")
    put(pathlib.Path(C.claude_project_dirs(str(project))[0]) / "sess-1.jsonl", [
        {"type": "user", "message": {"content": "Which file is the largest?"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "data.bin, by far."}]}}])
    gemini_session(tmp_path / "home")
    conv["runs"] = [{"stamp": "20261005-090000", "harness": "claude", "mode": "prompt", "session": "sess-1", "started": "2026-10-05T09:00:00", "finished": "2026-10-05T09:00:09"},
                    {"stamp": "20261005-091500", "harness": "gemini", "mode": "prompt", "session": SID, "started": "2026-10-05T09:15:00", "finished": "2026-10-05T09:15:20"}]
    conv["sessions"] = {"claude": {"id": "sess-1", "started": "2026-10-05T09:00:00", "runs": 1},
                        "gemini": {"id": SID, "started": "2026-10-05T09:15:00", "runs": 1}}
    path, notes = C.write_transcript(conv, str(log))
    text = pathlib.Path(path).read_text(encoding = "utf-8")
    assert notes == [] and path == C.transcript_path(conv)
    assert text.index("## claude - session `sess-1`") < text.index("## gemini - session `%s`" % SID)     # in the order they started
    assert "### User" in text and "### Claude" in text and "data.bin, by far." in text
    assert "### Gemini" in text and "`-> run_shell_command du -a .`" in text and "It is data.bin." in text
    assert "<session_context>" not in text
    assert conv["sessions"]["claude"]["exported"] == 2 and conv["sessions"]["gemini"]["exported"] == 3

    # the claude store goes away (another machine, a cleaned home): its segment stays as it was written
    for f in pathlib.Path(C.claude_project_dirs(str(project))[0]).glob("*.jsonl"):
        f.unlink()
    path, notes = C.write_transcript(conv, str(log))
    text = pathlib.Path(path).read_text(encoding = "utf-8")
    assert "data.bin, by far." in text and "It is data.bin." in text
    assert len(notes) == 1 and "claude" in notes[0] and "kept" in notes[0]


def test_a_replaced_session_keeps_its_segment_and_headings_in_answers_do_not_cut_it(tmp_path, monkeypatch):
    """When a harness's session is gone from its store, run-ai starts another and keeps the old one under "previous":
    the transcript still shows both, the old one from the previous export, whole - also when an answer has headings."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    project = tmp_path / "proj"
    log = project / "!AI" / "log"
    folder = pathlib.Path(C.claude_project_dirs(str(project))[0])
    answer = "Plan:\n\n## Step 1\n\nRead the notes.\n\n## Step 2\n\nAnswer."
    put(folder / "sess-a.jsonl", [{"type": "user", "message": {"content": "make a plan"}},
                                  {"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}}])
    conv = C.new_conversation(str(log), "20260101-090000", str(project), "", "make a plan")
    conv["runs"] = [{"harness": "claude", "session": "sess-a"}]
    conv["sessions"] = {"claude": {"id": "sess-a", "started": "2026-01-01T09:00:00", "runs": 1}}
    path, notes = C.write_transcript(conv, str(log))
    assert "## Step 2" in read(path) and notes == []

    # the store forgets sess-a; a new claude session sess-b replaces it
    (folder / "sess-a.jsonl").unlink()
    put(folder / "sess-b.jsonl", [{"type": "user", "message": {"content": "go on"}},
                                  {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}}])
    conv["sessions"]["claude"] = {"id": "sess-b", "started": "2026-01-01T10:00:00", "runs": 1,
                                  "previous": [{"id": "sess-a", "started": "2026-01-01T09:00:00", "runs": 1}]}
    path, notes = C.write_transcript(conv, str(log))
    text = read(path)
    assert text.index("## claude - session `sess-a`") < text.index("## claude - session `sess-b`")
    assert "Read the notes." in text and "## Step 2" in text and "Answer." in text and "Done." in text
    assert len(notes) == 1 and "kept" in notes[0]
    # and again: the kept text survives a second export unchanged
    assert C.write_transcript(conv, str(log))[0] and read(path).count("Read the notes.") == 1 and "Answer." in read(path)

    # an older conversation file lists previous sessions by their ids only
    conv["sessions"]["claude"]["previous"] = ["sess-a"]
    text = read(C.write_transcript(conv, str(log))[0])
    assert "## claude - session `sess-a`" in text and "Answer." in text


def read(path):
    return pathlib.Path(path).read_text(encoding = "utf-8")


def test_hand_over_names_the_transcript_and_the_reason(tmp_path):
    conv = C.new_conversation(str(tmp_path / "log"), "20261005-090000", str(tmp_path), "", "Which file is the largest?")
    conv["runs"] = [{"harness": "claude", "finished": "2026-10-05T09:00:09"}, {"harness": "claude"}, {"harness": "codex", "started": "2026-10-05T09:30:00"}]
    text = C.handover_text(conv, "gemini", str(tmp_path / "log"), "no gemini session in it yet")
    assert "20261005-090000.transcript.md" in text and "\\" not in text
    assert text.startswith("You continue conversation 20261005-090000 of this project (no gemini session in it yet)")
    assert "3 run(s) so far with claude, codex" in text and "2026-10-05T09:30" in text
    assert "Before anything else, read its transcript" in text and "answer the request at the end of this message" in text
    # the title is the first words of the first request: quoted in front of a prompt it would read as an instruction
    assert "Which file is the largest?" not in text
