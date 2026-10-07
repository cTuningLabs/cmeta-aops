"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The run-hermes task and run-ai's hermes adapters: how the "--format stream-json" events of Hermes Agent are turned
back into text and token statistics, how the session id is read from a quiet run, and how "hermes sessions list" and
"hermes sessions export --format jsonl" are parsed. Offline: the samples are what hermes v0.21.5 (release 2026.9.24)
printed on 2026-10-07 with a local model - no CLI runs.
"""

import json

import pytest


@pytest.fixture(scope="module")
def hermes(task_namespace):
    return task_namespace("run-hermes")


def task_of(namespace):
    return namespace["CTask"].__new__(namespace["CTask"])


STREAM = [
    '{"type": "system", "subtype": "init", "model": "qwen2.5:0.5b", "session_id": "20261007_164916_280b35", "timestamp": 1791391756501}',
    '{"type": "text", "text": "hello", "timestamp": 1791391758607}',
    '{"type": "text", "text": "-from", "timestamp": 1791391758684}',
    '{"type": "text", "text": "-tool", "timestamp": 1791391758768}',
    '{"type": "result", "session_id": "20261007_164916_280b35", "exit_code": 0, "text": "hello-from-tool", '
    '"tokens": {"input": 23, "output": 4, "total": 12211, "cache_read": 12184, "cache_write": 0}, "duration_ms": 2411, "timestamp": 1791391758912}',
]


def test_the_stream_becomes_text_and_statistics(hermes):
    t = task_of(hermes)
    run_stats, state, out = {}, {"streamed": 0, "unknown": 0}, []
    for line in STREAM:
        out += t._parse_stream_line(line + "\n", run_stats, state)
    assert "".join(out) == "hello-from-tool\n"           # the chunks, then the newline the result adds
    assert run_stats["session_id"] == "20261007_164916_280b35" and run_stats["model"] == "qwen2.5:0.5b"
    assert run_stats["exit_code"] == 0 and run_stats["duration_s"] == pytest.approx(2.411)
    tokens = t._get_tokens(run_stats)
    assert (tokens["sent"], tokens["output"], tokens["cache_read"], tokens["total"], tokens["cost_usd"]) == (23, 4, 12184, 12211, 0)
    lines = t._format_stats(run_stats)
    assert lines[0] == "Statistics for this prompt:" and any("Session:         20261007_164916_280b35" in x for x in lines)
    assert state["unknown"] == 0


def test_a_failed_result_shows_its_error_and_the_text_when_nothing_streamed(hermes):
    t = task_of(hermes)
    run_stats, state = {}, {"streamed": 0, "unknown": 0}
    out = t._parse_stream_line('{"type": "result", "session_id": "20261007_164201_45c8de", "exit_code": 1, "text": "", '
                               '"tokens": {"input": 0, "output": 0, "total": 0}, "duration_ms": 1019, "error": "credentials or agent init failed"}', run_stats, state)
    assert out == ["[error] credentials or agent init failed\n"] and run_stats["error"] == "credentials or agent init failed"
    # a line that is not JSON is a log line of the CLI and passes through
    assert t._parse_stream_line("Hermes couldn't start the model connection: ...\n", run_stats, state) == ["Hermes couldn't start the model connection: ...\n"]


def test_the_session_id_of_a_quiet_run(hermes):
    assert hermes["session_id_in_text"]("pong\n\nsession_id: 20261007_164833_d7c636\n") == "20261007_164833_d7c636"
    assert hermes["session_id_in_text"]("no session here\n") == ""
    assert hermes["SESSION_ID_RE"].search("x 20261007_164229_0fdf2d y").group(1) == "20261007_164229_0fdf2d"


def test_flag_values_and_the_generator_record(hermes):
    assert hermes["_flag_value"](["--model", "anthropic/claude-opus-4.6", "--reasoning=high"], ["--model", "-m"]) == "anthropic/claude-opus-4.6"
    assert hermes["_flag_value"](["-m", "x"], ["--model", "-m"]) == "x"
    assert hermes["_flag_value"](["--reasoning=high"], ["--reasoning"]) == "high"
    assert hermes["VERSION_RE"].search("Hermes Agent v0.21.5+8859.g0e21933 (2026.9.24) · upstream 0e219331").group(1) == "2026.9.24"


# ---------------------------------------------------------------------------------------------- run-ai's adapters
LIST = """Title                        Workspace          Last Active   ID
──────────────────────────────────────────────────────────────────────────────────────────────────────────────
Reply with exactly one wor   fursin             just now      20261007_164925_b9a55e
Run the shell command: ech   fursin             just now      20261007_164916_280b35
x                            fursin             6m ago        20261007_164229_0fdf2d
"""

EXPORT = {"id": "20261007_164916_280b35", "source": "oneshot", "model": "qwen2.5:0.5b", "cwd": "/home/fursin",
          "messages": [
              {"role": "user", "content": "Run the shell command: echo hello-from-tool.", "timestamp": "2026-10-07T16:49:16.682224Z", "tool_calls": None},
              {"role": "assistant", "content": "hello-from-tool", "timestamp": "2026-10-07T16:49:18.864388Z",
               "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "terminal", "arguments": json.dumps({"command": "echo hello-from-tool"})}}]},
              {"role": "tool", "content": "hello-from-tool", "timestamp": "2026-10-07T16:49:18.9Z", "tool_call_id": "c1"},
          ]}


def test_sessions_list_and_export_are_read_through_the_cli(monkeypatch):
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location("conv_under_test", str(pathlib.Path(__file__).resolve().parents[2] / "task" / "run-ai" / "conversations.py"))
    C = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(C)

    calls = []

    def fake_run(args, timeout=120):
        calls.append(list(args))
        if args[:2] == ["sessions", "list"]:
            return 0, LIST
        if args[:2] == ["sessions", "export"]:
            return 0, json.dumps(EXPORT) + "\n"
        return 1, ""

    monkeypatch.setattr(C, "hermes_run", fake_run)
    assert [s for s, _ in C.hermes_sessions()] == ["20261007_164925_b9a55e", "20261007_164916_280b35", "20261007_164229_0fdf2d"]
    assert C.hermes_exists("20261007_164916_280b35") and not C.hermes_exists("20261007_000000_000000")
    assert C.hermes_newest_session(0) == "20261007_164925_b9a55e"
    assert C.session_exists("hermes", "20261007_164916_280b35", ".") is True
    assert C.discover_session("hermes", ".", 0, {"stats": {"session_id": "S"}}) == "S"
    messages = C.export_session("hermes", "20261007_164916_280b35", ".")
    assert [m[0] for m in messages] == ["user", "assistant"]           # the tool result is dropped: the call is shown
    assert messages[1][2][0] == ("text", "hello-from-tool") and messages[1][2][1] == ("tool", "terminal echo hello-from-tool")
    assert messages[0][1]                                                # a timestamp came through
    assert calls[-1][:5] == ["sessions", "export", "--format", "jsonl", "--session-id"]
    assert C.native_store_hint("hermes").startswith("<HERMES_HOME>/state.db")
