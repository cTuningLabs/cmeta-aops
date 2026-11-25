"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The harness "pi" of run-ai (2026-11-24): Pi (https://pi.dev), run by the task run-pi with the tool pi, which a plugged
repository provides. What cmeta-aops holds of it is tested here, offline: run-ai's tables (the gateway, --yes, the
read-only tools, the long prompt, the main screen - and no entry among the harnesses whose task is in this repository), the session adapter of conversations.py (how a
session is named, resumed, found in Pi's own folder and exported - a session file written here in Pi's layout, no Pi
runs), and what the gateway category gives the harness (both wires, the request headers its task builds providers
from; no network).
"""

import importlib.util
import json
import os
import pathlib
import uuid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("run_ai_conversations_pi_under_test", str(REPO_ROOT / "task" / "run-ai" / "conversations.py"))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

SID = "5ab0c0de-1234-4abc-8def-0123456789ab"


def pi_session(agent_dir, project, sid = SID, store = None):
    """A session file as Pi 1.6.0 writes it: the header, the model and thinking entries, then the messages - the system
    prompt, the request, an answer with a tool call, the tool's result, the last answer."""
    project = str(project)
    folder = "--" + project.lstrip("/\\").replace("/", "-").replace("\\", "-").replace(":", "-") + "--"
    path = pathlib.Path(store or pathlib.Path(agent_dir) / "sessions") / folder / ("2026-11-24T12-36-22-833Z_%s.jsonl" % sid)
    path.parent.mkdir(parents = True, exist_ok = True)
    usage = {"input": 30, "output": 9, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 39}
    entries = [
        {"type": "session", "version": 3, "id": sid, "timestamp": "2026-11-24T12:36:22.833Z", "cwd": project},
        {"type": "model_change", "id": "e1", "parentId": None, "timestamp": "2026-11-24T12:36:22.948Z", "provider": "gw", "modelId": "m"},
        {"type": "thinking_level_change", "id": "e2", "parentId": "e1", "timestamp": "2026-11-24T12:36:22.948Z", "thinkingLevel": "off"},
        {"type": "message", "id": "e3", "parentId": "e2", "timestamp": "2026-11-24T12:36:22.958Z",
         "message": {"role": "system", "content": "", "sections": {"preamble": "You are a coding assistant."}}},
        {"type": "message", "id": "e4", "parentId": "e3", "timestamp": "2026-11-24T12:36:22.959Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "Run the command and say what it printed."}]}},
        {"type": "message", "id": "e5", "parentId": "e4", "timestamp": "2026-11-24T12:36:23.038Z",
         "message": {"role": "assistant", "provider": "gw", "model": "m", "stopReason": "toolUse", "usage": usage,
                     "content": [{"type": "thinking", "thinking": "a command it is"}, {"type": "text", "text": "I run a command."},
                                 {"type": "toolCall", "id": "call_1", "name": "bash", "arguments": {"command": "echo  it-works"}}]}},
        {"type": "message", "id": "e6", "parentId": "e5", "timestamp": "2026-11-24T12:36:23.092Z",
         "message": {"role": "toolResult", "toolCallId": "call_1", "toolName": "bash", "content": [{"type": "text", "text": "it-works\n"}]}},
        {"type": "message", "id": "e7", "parentId": "e6", "timestamp": "2026-11-24T12:36:23.098Z",
         "message": {"role": "assistant", "provider": "gw", "model": "m", "stopReason": "stop", "usage": usage,
                     "content": "The command printed its words."}},
    ]
    path.write_text("".join(json.dumps(e) + "\n" for e in entries) + "not a record\n", encoding = "utf-8")
    return path


# ---------------------------------------------------------------------------------------------- run-ai's tables
def test_the_tables_of_run_ai_know_pi(task_namespace):
    ns = task_namespace("run-ai")

    # the task and the tool of pi are not part of this repository, so it has no entry in the table of harnesses (every
    # harness there has both here): run-ai finds them by its rule for any other harness, wherever they are plugged
    assert "pi" not in ns["HARNESSES"]
    cls = ns["CTask"]
    task = cls.__new__(cls)
    task._harness_cache = ns["harness_declarations"]([])                     # no task declares it here
    assert task._harness_refs("pi") == ("run-pi", "pi")

    # declared by its task (the tag ai-harness, its "harness" block), wherever it is plugged: that task and its tool
    task._harness_cache = ns["harness_declarations"]([("run-pi,e09024944b584215", {"name": "pi", "tool": "pi,b9da93b6b4094df3"})])
    assert task._harness_refs("pi") == ("run-pi,e09024944b584215", "pi,b9da93b6b4094df3")

    for table in ("GATEWAY_HARNESSES", "YES_HARNESSES", "LONG_PROMPT_HARNESSES", "MAIN_SCREEN_HARNESSES"):
        assert "pi" in ns[table], table

    # the harnesses that were there are all still there, in their order
    assert ns["GATEWAY_HARNESSES"][:3] == ("claude", "codex", "opencode")
    assert ns["MAIN_SCREEN_HARNESSES"][:3] == ("claude", "codex", "hermes")

    # read-only: the tools that only read - Pi has no plan mode
    assert ns["READ_ONLY_FLAGS"]["pi"] == ["--tools", "read,grep,find,ls"]

    # the error of a harness without gateway support names those that have it, whatever the table holds
    said = ns["NO_GATEWAY_SUPPORT"] % "vibe"
    assert said.startswith('the harness "vibe" has no gateway support (') and "claude, codex, opencode, pi have" in said


# ---------------------------------------------------------------------------------------------- the session adapter
def test_a_session_is_named_by_run_ai_and_resumed_by_its_id():
    assert C.chooses_id("pi")
    assert C.new_session_flags("pi", SID, "20261124-120000", "proj") == ["--session-id", SID]
    assert C.new_session_flags("pi", SID, "20261124-120000", "proj", interactive = True) == ["--session-id", SID]
    assert C.resume_flags("pi", SID) == ["--session", SID] == C.resume_flags("pi", SID, interactive = True)
    assert "sessions" in C.native_store_hint("pi") and "PI_CODING_AGENT_DIR" in C.native_store_hint("pi")


def test_a_session_is_found_in_pis_own_folder_by_its_id_and_its_folder(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    project = tmp_path / "work" / "my project"
    other = tmp_path / "work" / "another"
    project.mkdir(parents = True)
    other.mkdir(parents = True)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    monkeypatch.delenv("PI_CODING_AGENT_SESSION_DIR", raising = False)
    assert C.pi_sessions_dir() == str(agent / "sessions")
    assert not C.session_exists("pi", SID, str(project))                   # no store at all yet

    fp = pi_session(agent, project)
    assert C.pi_session_file(SID, str(project)) == str(fp) and C.session_exists("pi", SID, str(project))

    # a session of another folder is not this project's: Pi opens a session by its id in the folder it was made in
    assert not C.session_exists("pi", SID, str(other)) and C.pi_exists(SID)
    assert not C.session_exists("pi", "0" * 8 + SID[8:], str(project))

    # a file with the id in its name and another id inside is not the session
    liar = fp.with_name("2026-11-24T13-00-00-000Z_%s.jsonl" % ("f" * 8 + SID[8:]))
    liar.write_text(json.dumps({"type": "session", "id": SID, "cwd": str(project)}) + "\n", encoding = "utf-8")
    assert not C.pi_exists("f" * 8 + SID[8:], str(project))


def test_the_sessions_follow_the_variable_that_moves_them(tmp_path, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(tmp_path / "elsewhere"))
    assert C.pi_sessions_dir() == str(tmp_path / "elsewhere")
    pi_session(tmp_path / "agent", project)                                 # in the folder that is not looked at
    assert not C.pi_exists(SID, str(project))
    pi_session(None, project, store = tmp_path / "elsewhere")
    assert C.pi_exists(SID, str(project))


def test_the_transcript_of_a_session(tmp_path, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    monkeypatch.delenv("PI_CODING_AGENT_SESSION_DIR", raising = False)
    assert C.export_session("pi", SID, str(project)) is None               # no session: nothing to export
    pi_session(tmp_path / "agent", project)
    messages = C.export_session("pi", SID, str(project))

    # the request and the two answers: no system prompt, no thinking, no tool result; the tool call as one line
    assert [(role, blocks) for role, _, blocks in messages] == [
        ("user", [("text", "Run the command and say what it printed.")]),
        ("assistant", [("text", "I run a command."), ("tool", "bash echo it-works")]),
        ("assistant", [("text", "The command printed its words.")])]
    assert all(len(ts) == 19 and ts.startswith("2026-11-24 ") for _, ts, _ in messages)      # local time, to the second


# ---------------------------------------------------------------------------------------------- the gateway category
def gateway(cm, name, desc):
    """A gateway artifact in the test home's local repository, with a token secret beside it."""
    r = cm.access({"category": "secret", "command": "get", "arg1": "local:" + name + "-key"})
    assert r["return"] == 0, r
    files = os.path.join(r["artifact"]["path"], "files")
    os.makedirs(files, exist_ok = True)
    with open(os.path.join(files, "token"), "w") as f:
        f.write("sk-test-" + name + "\n")
    cm.utils.files.safe_write_file(os.path.join(r["artifact"]["path"], "_desc.yaml"), {"kind": "token", "token": {"file": "files/token"}})
    r = cm.access({"category": "ai.gateway", "command": "get", "arg1": "local:" + name})
    assert r["return"] == 0, r
    cm.utils.files.safe_write_file(os.path.join(r["artifact"]["path"], "_desc.yaml"), desc)
    return name


def test_connect_gives_pi_both_wires_and_the_request_headers(cm):
    name = "gw-pi-" + uuid.uuid4().hex[:8]
    gateway(cm, name, {"base_url": "http://127.0.0.1:9", "wires": {"anthropic": "/anthropic", "openai": "/openai/v1"},
                       "auth": {"header": "x-api-key", "secret": name + "-key"},
                       "models": {"pi": {"default": "claude-haiku-x"}, "codex": {"default": "gpt-x"}}})
    r = cm.access({"category": "ai.gateway", "command": "connect", "arg1": name, "harness": "pi", "con": False})
    assert r["return"] == 0, r

    # nothing of another harness's recipe: no variables, no words - the task run-pi registers its providers from these
    assert r["env"] == {} and r["args"] == [] and "opencode_config" not in r and "claude_settings" not in r
    assert r["wires"] == {"anthropic": "/anthropic", "openai": "/openai/v1"} and r["base_url"] == "http://127.0.0.1:9"
    assert r["request_headers"] == {"x-api-key": "sk-test-" + name} and r["model"] == "claude-haiku-x"

    # a model named for the run goes before the declared default
    r = cm.access({"category": "ai.gateway", "command": "connect", "arg1": name, "harness": "pi", "model": "gpt-y", "con": False})
    assert r["return"] == 0 and r["model"] == "gpt-y"

    # a bearer gateway with one wire: the key as an Authorization header
    name2 = "gw-pi-" + uuid.uuid4().hex[:8]
    gateway(cm, name2, {"base_url": "http://127.0.0.1:9", "wires": {"openai": "/v1"}, "auth": {"header": "bearer", "secret": name2 + "-key"}})
    r = cm.access({"category": "ai.gateway", "command": "connect", "arg1": name2, "harness": "pi", "con": False})
    assert r["return"] == 0 and r["request_headers"] == {"Authorization": "Bearer sk-test-" + name2} and r["wire"] == "openai" and r["model"] == ""

    # a gateway that passes a harness's own login on has no recipe for pi: said, never a run on another account
    name3 = "gw-pi-" + uuid.uuid4().hex[:8]
    gateway(cm, name3, {"base_url": "http://127.0.0.1:9", "wires": {"anthropic": ""}, "auth": {"header": "login"}})
    r = cm.access({"category": "ai.gateway", "command": "connect", "arg1": name3, "harness": "pi", "con": False})
    assert r["return"] > 0 and "pi has none" in r["error"]

    # the catalog of a gateway for pi: both wires asked (nothing listens here: each says why), the declared default
    r = cm.access({"category": "ai.gateway", "command": "models", "arg1": name, "harness": "pi", "con": False})
    assert r["return"] == 0 and set(r["errors"]) | set(r["models"]) == {"anthropic", "openai"} and r["defaults"] == {"default": "claude-haiku-x"}


def test_the_choice_for_pi_follows_its_own_config_key(cm, task_namespace):
    cls = task_namespace("set-ai-gateway")["CTask"]
    task = cls.__new__(cls)
    task.cm = cm
    cfg = {}
    task._config = lambda: cfg
    assert task.choose("pi") == ("login", "the default", "")
    cfg.update(run_ai_gateway_pi = "my-gateway")
    assert task.choose("pi")[:2] == ("my-gateway", "config run_ai_gateway_pi") and task.choose("codex")[0] == "login"
    assert task.choose("pi", ln = True)[0] == "login"
