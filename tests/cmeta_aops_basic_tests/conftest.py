"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Shared pytest fixtures for the cmeta-aops basic test suite.

These tests are hermetic: they point CMETA_HOME at a throwaway temporary
directory and plug THIS repository into it, so they never touch the developer's
global cMeta state and never require network access.
"""

import os
import atexit
import shutil
import pathlib
import tempfile

import pytest

# tests/basic_tests/conftest.py -> repo root is two levels up
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# IMPORTANT: set an isolated CMETA_HOME *before* cmeta is imported/instantiated,
# so every CMeta() created during this session uses the throwaway home.
_CMETA_HOME = pathlib.Path(tempfile.mkdtemp(prefix="cmeta_home_aops_"))
os.environ["CMETA_HOME"] = str(_CMETA_HOME)
atexit.register(lambda: shutil.rmtree(_CMETA_HOME, ignore_errors=True))


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def task_namespace():
    """A loader for the hook file of a task (task/<name>/api_v1.py), for offline tests of its helpers and of the
    methods of its CTask class that need no engine: the source is executed in a namespace of its own with a
    stand-in for the task engine's base class (the real one needs cMeta), and nothing is registered in
    sys.modules, so the tests that run tasks through the engine are not disturbed.

        ns = task_namespace("run-ai");  CTask = ns["CTask"];  task = CTask.__new__(CTask)
    """
    loaded = {}

    def load(task: str) -> dict:
        if task not in loaded:
            path = REPO_ROOT / "task" / task / "api_v1.py"
            source = path.read_text(encoding="utf-8").replace(
                "from task_c36be4b9314a45e0.api.ctask import InitCTask", "InitCTask = object")
            namespace = {"__file__": str(path), "__name__": "task_" + task.replace("-", "_") + "_under_test"}
            exec(compile(source, str(path), "exec"), namespace)
            loaded[task] = namespace
        return loaded[task]

    return load


@pytest.fixture(scope="session")
def cm():
    """A CMeta engine instance with this repo plugged into an isolated CMETA_HOME."""
    from cmeta import CMeta

    cm = CMeta()

    r = cm.access({"category": "repo", "command": "plug", "arg1": str(REPO_ROOT)})
    assert r["return"] == 0, f"failed to plug repo: {r.get('error')}"

    return cm
