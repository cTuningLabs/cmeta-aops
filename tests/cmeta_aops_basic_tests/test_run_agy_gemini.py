"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The run-agy and run-gemini tasks: how the JSON event stream of each CLI ("--output-format stream-json") is turned
back into text and into token statistics, and what a failed run is told. Offline: the lines below have the shapes
the CLIs print (Antigravity CLI 1.2, Gemini CLI 0.62) - no CLI runs.
"""

import json

import pytest


@pytest.fixture(scope="module")
def gemini(task_namespace):
    return task_namespace("run-gemini")


@pytest.fixture(scope="module")
def agy(task_namespace):
    return task_namespace("run-agy")


def parse(namespace, lines, *state):
    task = namespace["CTask"].__new__(namespace["CTask"])
    stats, text = {}, []
    for line in lines:
        text += task._parse_stream_line(line if isinstance(line, str) else json.dumps(line), stats, *state)
    return "".join(text), stats, task


# ---------------------------------------------------------------------------------------------- gemini
# What the API answers to a key it does not accept, as the CLI passes it on: JSON inside JSON inside a string
API_ERROR = "[API Error: " + json.dumps({"error": {"message": json.dumps(
    {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}, indent=2) + "\n",
    "code": 400, "status": "Bad Request"}}) + "]"


def test_gemini_stream_of_a_run_that_worked(gemini):
    text, stats, task = parse(gemini, [
        {"type": "init", "timestamp": "2026-10-05T18:38:50.081Z", "session_id": "5ab0c0de-1234-4abc-8def-0123456789ab", "model": "auto"},
        {"type": "message", "role": "user", "content": "Which file is the largest?"},
        {"type": "message", "role": "assistant", "content": "Let me ", "delta": True},
        {"type": "message", "role": "assistant", "content": "check.\n", "delta": True},
        {"type": "tool_use", "tool_name": "run_shell_command", "parameters": {"command": "du -a ."}},
        {"type": "tool_result", "status": "success", "output": "12 ./data.bin"},
        {"type": "message", "role": "assistant", "content": "It is data.bin."},
        {"type": "result", "status": "success", "stats": {
            "total_tokens": 1560, "input_tokens": 1500, "output_tokens": 60, "cached": 1000, "input": 500, "duration_ms": 2400, "tool_calls": 1,
            "models": {"gemini-3.5-flash-lite": {"total_tokens": 260, "input_tokens": 250, "output_tokens": 10, "cached": 0, "input": 250},
                       "gemini-3.1-pro-preview": {"total_tokens": 1300, "input_tokens": 1250, "output_tokens": 50, "cached": 1000, "input": 250}}}},
        "a log line of the CLI, not an event",
    ])
    assert text == "Let me check.\n[tool: run_shell_command] du -a .\nIt is data.bin.\na log line of the CLI, not an event\n"
    assert stats["session_id"] == "5ab0c0de-1234-4abc-8def-0123456789ab" and stats["status"] == "success"
    # the default model routes between two: the name it was started with, and the ones that worked
    assert stats["model"] == "auto" and stats["models"] == ["gemini-3.1-pro-preview", "gemini-3.5-flash-lite"]
    # the totals of the run are at the top level; the per-model split repeats them and is not added again
    tokens = task._get_tokens(stats)
    assert (tokens["input"], tokens["output"], tokens["cache_read"]) == (1500, 60, 1000)
    assert tokens["sent"] == 1500 and tokens["total"] == 1560 and tokens["cost_usd"] == 0
    assert stats["duration_ms"] == 2400 and stats["tool_calls"] == 1
    lines = task._format_stats(stats)
    assert "  Tokens sent:     1500 (of which cached: 1000)" in lines
    assert "  Model:           auto (gemini-3.1-pro-preview, gemini-3.5-flash-lite)" in lines


def test_gemini_statistics_nested_per_model(gemini):
    """The shape of the "-o json" report: no totals, the counters under each model's "tokens"."""
    text, stats, task = parse(gemini, [{"type": "result", "status": "success", "stats": {"models": {
        "gemini-3.1-pro-preview": {"tokens": {"prompt": 900, "candidates": 40, "cached": 300, "thoughts": 25, "tool": 5, "total": 970}},
        "gemini-3.5-flash-lite": {"tokens": {"prompt": 100, "candidates": 10, "cached": 0, "thoughts": 0, "tool": 0, "total": 110}}}}}])
    tokens = task._get_tokens(stats)
    assert (tokens["input"], tokens["output"], tokens["cache_read"], tokens["reasoning"], tokens["tool"]) == (1000, 50, 300, 25, 5)
    assert tokens["total"] == 1080 and stats["model"] == "gemini-3.1-pro-preview"


def test_gemini_error_of_the_api_is_read_out_of_its_wrapping(gemini):
    assert gemini["_error_text"]({"type": "unknown", "message": API_ERROR}) == "API key not valid. Please pass a valid API key."
    assert gemini["_error_text"]("plain   text\nover two lines") == "plain text over two lines"
    assert gemini["_error_text"]({"code": 7}) == "{'code': 7}"
    text, stats, task = parse(gemini, [
        {"type": "init", "session_id": "s-1", "model": "auto"},
        {"type": "result", "status": "error", "error": {"type": "unknown", "message": API_ERROR},
         "stats": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "cached": 0, "input": 0, "duration_ms": 0, "tool_calls": 0}}])
    assert text == "[error] API key not valid. Please pass a valid API key.\n"
    assert stats["status"] == "error" and stats["error"] == "API key not valid. Please pass a valid API key."
    assert gemini["_failure_hint"](text) == "the GEMINI_API_KEY of this environment is not valid"


def test_gemini_failures_are_told_what_to_do(gemini):
    hint = gemini["_failure_hint"]
    refused = ("Error authenticating: IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals. "
               "To continue using Gemini, please migrate to the Antigravity suite of products: https://antigravity.google")
    assert "personal Google accounts" in hint(refused) and "run-agy" in hint(refused)        # not the plain sign-in hint
    assert "not signed in" in hint("Please set an Auth method in your /home/u/.gemini/settings.json or specify one of the following "
                                   "environment variables before running: GEMINI_API_KEY, GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_GENAI_USE_GCA")
    assert "quota" in hint('{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}')
    assert "--skip-trust" in hint("Gemini CLI is not running in a trusted directory.")
    assert "sign in" in hint("Error authenticating: something else")
    assert hint("some other failure") == ""


def test_gemini_headless_runs_never_open_a_browser(gemini):
    assert gemini["NO_BROWSER_ENV"] == "NO_BROWSER"
    assert gemini["YES_FLAGS"] == ["--yolo"] and gemini["TRUST_FLAGS"] == ["--skip-trust"]
    assert gemini["_flag_value"](["--yolo", "--model", "gemini-3.1-pro-preview"], gemini["MODEL_FLAGS"]) == "gemini-3.1-pro-preview"
    assert gemini["_flag_value"](["-m=flash"], gemini["MODEL_FLAGS"]) == "flash"


# ---------------------------------------------------------------------------------------------- antigravity (agy)
def test_agy_stream_nests_each_payload_under_the_name_of_its_event(agy):
    state = {"streamed": 0, "unknown": 0}
    text, stats, task = parse(agy, [
        {"event": "init", "conversation_id": "conv-1", "init": {"cwd": "/work/app", "tools": ["shell"]}},
        {"event": "step_update", "step_update": {"conversation_id": "conv-1", "step_index": 0, "state": "DONE", "step_type": "user_input"}},
        {"event": "step_update", "step_update": {"step_index": 1, "state": "ACTIVE", "step_type": "agent_response", "text_delta": "It is "}},
        {"event": "step_update", "step_update": {"step_index": 1, "state": "ACTIVE", "step_type": "agent_response", "text_delta": "data.bin."}},
        {"event": "result", "result": {"conversation_id": "conv-1", "status": "SUCCESS", "response": "It is data.bin.", "duration_seconds": 3.5,
                                       "num_turns": 1, "usage": {"input_tokens": 42000, "output_tokens": 12, "thinking_tokens": 30,
                                                                 "cache_read_tokens": 40000, "total_tokens": 42042}}},
    ], state)
    assert text == "It is data.bin.\n"                  # the streamed text, not the response repeated
    assert stats["session_id"] == "conv-1" and stats["status"] == "SUCCESS" and stats["turns"] == 1 and stats["duration_s"] == 3.5
    tokens = task._get_tokens(stats)
    assert (tokens["input"], tokens["output"], tokens["reasoning"], tokens["cache_read"]) == (42000, 12, 30, 40000)
    assert "response" not in stats["raw"]


def test_agy_answer_that_was_not_streamed_and_a_failed_result(agy):
    state = {"streamed": 0, "unknown": 0}
    text, stats, task = parse(agy, [{"event": "result", "result": {"conversation_id": "c", "status": "SUCCESS", "response": "OK", "usage": {}}}], state)
    assert text == "OK\n"
    state = {"streamed": 0, "unknown": 0}
    text, stats, task = parse(agy, [{"event": "result", "result": {"status": "ERROR", "error": "authentication failed or timed out"}},
                                    "Open this URL to sign in: https://example.invalid/login"], state)
    assert "[error] authentication failed or timed out" in text and "Open this URL" in text
    assert stats["status"] == "ERROR"
