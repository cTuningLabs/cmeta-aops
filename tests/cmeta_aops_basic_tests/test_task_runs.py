"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

End-to-end smoke tests of the task workflow engine using OFFLINE tasks only
(no network, no toolchain installs). These exercise: `params_map`, the `init`
hook, a real `run()` body, `uses` sub-task pipelines, and the `--info` help path.
"""


def test_info_does_not_execute(cm):
    """`info=True` returns help text and must NOT run the task."""
    r = cm.access(
        {
            "category": "task",
            "command": "run",
            "arg1": "clone-git-to-cache",
            "info": True,
            "con": False,
            "quiet": True,
        }
    )
    assert r["return"] == 0, r.get("error")
    assert r.get("help"), "expected help text from the --info path"


def test_run_generate_temp_file(cm):
    """A task whose api_v1.py `run()` returns a value; fully offline."""
    r = cm.access(
        {
            "category": "task",
            "command": "run",
            "arg1": "generate-temp-file",
            "con": False,
            "quiet": True,
        }
    )
    assert r["return"] == 0, r.get("error")
    assert r.get("temp_file"), "generate-temp-file should return a 'temp_file' path"


def test_run_print_text_exercises_init_and_params_map(cm):
    """`print-text` maps arg2->text and runs its `init` hook. quiet+skip_enter avoid
    the interactive prompt."""
    r = cm.access(
        {
            "category": "task",
            "command": "run",
            "arg1": "print-text",
            "arg2": "hello-from-tests",  # exercises params_map (arg2 -> text)
            "con": False,
            "quiet": True,
            "skip_enter": True,
        }
    )
    assert r["return"] == 0, r.get("error")


def test_run_host_pipeline(cm):
    """`host` runs a `uses` sub-task pipeline (init, ...) and detects the host
    offline. Validates nested task dispatch through the engine."""
    r = cm.access(
        {
            "category": "task",
            "command": "run",
            "arg1": "host",
            "con": False,
            "quiet": True,
        }
    )
    assert r["return"] == 0, r.get("error")
