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
import re
import atexit
import shutil
import pathlib
import tempfile
import importlib.util

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
    sys.modules, so the tests that run tasks through the engine are not disturbed. The other names a task
    imports from the task category API (prompt_via_file, ...) are the real ones, loaded from the repo.

        ns = task_namespace("run-ai");  CTask = ns["CTask"];  task = CTask.__new__(CTask)
    """
    loaded = {}
    ctask = []

    def ctask_names(*names):
        """The real helpers of category/task/api/ctask.py (it needs no cMeta to load), by name."""
        if not ctask:
            spec = importlib.util.spec_from_file_location("ctask_under_test", str(REPO_ROOT / "category" / "task" / "api" / "ctask.py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            ctask.append(module)
        return tuple(getattr(ctask[0], n) for n in names)

    def load(task: str) -> dict:
        if task not in loaded:
            path = REPO_ROOT / "task" / task / "api_v1.py"
            source = path.read_text(encoding="utf-8")
            # the one import line of the task category API becomes one line again (the line numbers of the file
            # are kept for tracebacks): the base class a stand-in, the helpers the real ones
            m = re.search(r"^from task_c36be4b9314a45e0\.api\.ctask import ([^\n]+)$", source, re.M)
            if m:
                names = [n.strip() for n in m.group(1).split(",") if n.strip() and n.strip() != "InitCTask"]
                stand_in = "InitCTask = object"
                if names:
                    stand_in += "; %s, = _ctask_names(%s)" % (", ".join(names), ", ".join(repr(n) for n in names))
                source = source[:m.start()] + stand_in + source[m.end():]
            namespace = {"__file__": str(path), "__name__": "task_" + task.replace("-", "_") + "_under_test",
                         "_ctask_names": ctask_names}
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
