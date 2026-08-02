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
def cm():
    """A CMeta engine instance with this repo plugged into an isolated CMETA_HOME."""
    from cmeta import CMeta

    cm = CMeta()

    r = cm.access({"category": "repo", "command": "plug", "arg1": str(REPO_ROOT)})
    assert r["return"] == 0, f"failed to plug repo: {r.get('error')}"

    return cm
