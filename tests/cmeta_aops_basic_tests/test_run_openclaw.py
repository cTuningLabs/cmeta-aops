"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The run-openclaw task: how the result of "openclaw agent --json" is turned back into the reply and into token
statistics. Offline: the output below has the shape OpenClaw 2026.6 prints (its log lines, then one JSON object), and
the Claude Code session of a claude-cli turn is a small file written here - no CLI runs.
"""

import json
import pathlib
import time

import pytest


@pytest.fixture(scope="module")
def openclaw(task_namespace):
    return task_namespace("run-openclaw")


def task_of(namespace):
    return namespace["CTask"].__new__(namespace["CTask"])


def result(reply = "Heron.", provider = "claude-cli", binding = "c1a0de00-0000-4000-8000-000000000001", cost = 0, first = None):
    usage = {"input": 1, "output": 1, "cacheRead": 30000, "cacheWrite": 200, "totalTokens": 2,
             "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": cost}}
    agent_meta = {"sessionId": binding, "provider": provider, "model": "m", "usage": usage, "lastCallUsage": dict(usage)}
    if binding:
        agent_meta["cliSessionBinding"] = {"sessionId": binding, "cwdHash": "x"}
    data = {"payloads": ([{"text": first}] if first else []) + [{"text": reply, "mediaUrl": None}],
            "meta": {"durationMs": 1, "finalAssistantVisibleText": reply, "agentMeta": agent_meta,
                     "systemPromptReport": {"tools": {"entries": [{"usage": {"input": 999}}]}}}}
    # what OpenClaw prints before its JSON: log lines of its runtime (one of them with braces in it)
    return ("[agent/cli-backend] cli exec: provider=claude-cli model=m trigger=user {not json}\n"
            "[agent/cli-backend] claude live session close: reason=restart\n" + json.dumps(data, indent=2) + "\n")


def test_the_reply_is_the_payload_text_not_the_whole_json(openclaw):
    reply, tokens = task_of(openclaw)._from_json(result(reply = "Heron, KESTREL.", provider = "openai", binding = ""))
    assert reply == "Heron, KESTREL."
    # the turn's usage, not every "usage" in the result (the report of the system prompt has one of its own)
    assert tokens["input"] == 1 and tokens["output"] == 1 and tokens["cache_read"] == 30000 and tokens["cache_write"] == 200
    assert tokens["sent"] == 1 + 30000 + 200 and tokens["total"] == tokens["sent"] + 1 and "cost_usd" not in tokens
    reply, tokens = task_of(openclaw)._from_json(result(provider = "openai", binding = "", cost = 0.0123))
    assert tokens["cost_usd"] == 0.0123
    # two payloads are one reply; output that is no JSON leaves the raw output in place
    assert task_of(openclaw)._from_json(result(first = "First.", binding = ""))[0] == "First.\n\nHeron."
    assert task_of(openclaw)._from_json("openclaw: something went wrong\n") == (None, {})


def test_a_claude_cli_turn_is_counted_from_claude_codes_own_session(openclaw, tmp_path, monkeypatch):
    # the claude-cli provider runs Claude Code: its session file has every model call of the turn (one line per
    # content block, all with the message's usage), while OpenClaw reports the last call with 1 output token
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    sid = "c1a0de00-0000-4000-8000-000000000001"
    start = time.time()
    stamp = lambda delta: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(start + delta))
    call = lambda mid, delta, i, w, r, o: {"type": "assistant", "timestamp": stamp(delta), "message": {"id": mid, "usage": {
        "input_tokens": i, "cache_creation_input_tokens": w, "cache_read_input_tokens": r, "output_tokens": o}}}
    lines = [call("msg_old", -3600, 9, 9, 9, 9),                 # an earlier turn of the same Claude session
             call("msg_1", 2, 3, 30000, 0, 120), call("msg_1", 2, 3, 30000, 0, 120),     # one call, two blocks
             call("msg_2", 5, 1, 200, 30000, 40),
             {"type": "user", "timestamp": stamp(3), "message": {"content": "a tool result"}}]
    folder = tmp_path / "claude" / "projects" / "C--Users-someone--openclaw-workspace"
    folder.mkdir(parents = True)
    (folder / (sid + ".jsonl")).write_text("".join(json.dumps(x) + "\n" for x in lines), encoding = "utf-8")

    reply, tokens = task_of(openclaw)._from_json(result(binding = sid), start)
    assert reply == "Heron."
    assert (tokens["input"], tokens["cache_write"], tokens["cache_read"], tokens["output"]) == (4, 30200, 30000, 160)
    assert tokens["model_calls"] == 2 and tokens["total"] == 4 + 30200 + 30000 + 160 and sid in tokens["from"]
    lines_out = task_of(openclaw)._format_stats(tokens)
    assert any("cache read: 30000" in x for x in lines_out) and any("Counted from" in x for x in lines_out)

    # no Claude session to read: OpenClaw's own numbers
    reply, tokens = task_of(openclaw)._from_json(result(binding = "c1a0de00-0000-4000-8000-00000000ffff"), start)
    assert tokens["output"] == 1 and "from" not in tokens
