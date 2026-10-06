"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

prompt_via_file() of the task category API: a prompt that is too long for a command line argument goes to a file,
and the agent tasks get a one-line request to read it first. Offline: no agent runs.
"""

import os
import subprocess

import pytest


@pytest.fixture(scope="module")
def api(task_namespace):
    # run-codex imports the helpers from the task category API: the loader binds the real ones; the limit is
    # the API's constant (run-codex itself does not import it)
    ns = task_namespace("run-codex")
    return ns["prompt_via_file"], ns["prompt_via_file_done"], ns["_ctask_names"]("MAX_PROMPT_ARG_CHARS")[0]


LONG = ("x" * 99 + "\n") * 600      # 60,000 characters


def test_a_short_prompt_stays_on_the_command_line(api):
    prompt_via_file, done, limit = api
    r = prompt_via_file("hello\nworld", "codex")
    assert r["return"] == 0 and r["text"] == "hello\nworld" and r["file"] == "" and not r["temporary"]
    assert prompt_via_file("z" * limit, "codex")["file"] == ""           # exactly at the limit: still an argument
    assert prompt_via_file("", "codex")["text"] == ""
    assert prompt_via_file(LONG, "codex", when=False)["file"] == ""      # it goes another way (stdin)


def test_a_long_prompt_goes_to_the_named_file(api, tmp_path):
    prompt_via_file, done, limit = api
    path = tmp_path / "log" / "20261006-000000.codex.prompt.md"
    r = prompt_via_file(LONG, "codex", path=str(path))
    assert r["return"] == 0 and r["file"] == str(path) and not r["temporary"]
    assert path.read_text(encoding="utf-8") == LONG
    assert str(path).replace("\\", "/") in r["text"] and str(len(LONG)) in r["text"] and len(r["text"]) < 400
    assert r["reason"].startswith("too long")
    # the whole command line is short now (Windows caps it at 32767 characters)
    assert len(subprocess.list2cmdline(["codex.exe", "-m", "gpt-5.6-sol", r["text"]])) < 1000
    done(r)
    assert path.is_file()                                                # a file named by the caller is kept


def test_a_long_prompt_goes_next_to_the_prompt_file(api, tmp_path):
    prompt_via_file, done, limit = api
    prompt_file = tmp_path / "review.txt"
    prompt_file.write_text("x")
    r = prompt_via_file(LONG, "claude", prompt_file=str(prompt_file))
    assert r["file"] == str(tmp_path / "review-prompt.md") and os.path.isfile(r["file"]) and not r["temporary"]
    done(r)
    assert os.path.isfile(r["file"])


def test_a_long_prompt_with_no_name_goes_to_a_temporary_file(api):
    prompt_via_file, done, limit = api
    r = prompt_via_file(LONG, "opencode")
    assert r["temporary"] and os.path.isfile(r["file"]) and "run-opencode-prompt-" in os.path.basename(r["file"])
    done(r)
    assert not os.path.exists(r["file"])
    assert done(r)["return"] == 0                                        # twice is harmless


def test_force_and_a_lower_limit(api):
    prompt_via_file, done, limit = api
    # a launcher script would mangle the argument: the file whatever the length, with the reason given
    r = prompt_via_file("short", "gemini", force=True, why="the launcher would mangle it", limit=7000)
    assert r["file"] != "" and r["reason"] == "the launcher would mangle it"
    done(r)
    r = prompt_via_file("y" * 8000, "gemini", limit=7000)
    assert r["file"] != "" and r["reason"].startswith("too long")
    done(r)


def test_every_agent_task_uses_the_helper(repo_root):
    for task in ("run-claude", "run-codex", "run-opencode", "run-openclaw", "run-agy", "run-gemini"):
        source = (repo_root / "task" / task / "api_v1.py").read_text(encoding="utf-8")
        assert "prompt_via_file(" in source and "prompt_via_file_done(" in source, task
        assert "long_prompt_file" in source, task
