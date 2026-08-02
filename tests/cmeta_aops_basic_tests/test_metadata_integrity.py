"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Structural integrity of every canonical metadata file in the repo. A malformed
`_cmeta.*` / `_desc.yaml` / `_cmr.yaml` breaks indexing and workflows, so we parse
them all. Only exact canonical filenames are checked, which naturally skips the
author's numbered scratch/backup siblings (`_desc.yaml2`, `_cmeta.json2`, ...).
"""

import json
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_EXCLUDE_PARTS = {"__symlinks", ".venv", ".git", "__pycache__", "node_modules", "build"}


def _collect(*names):
    files = []
    for name in names:
        for p in REPO_ROOT.rglob(name):
            if _EXCLUDE_PARTS.intersection(p.parts):
                continue
            files.append(p)
    return sorted(files)


def _load(path: pathlib.Path):
    text = path.read_text(encoding="utf-8-sig")  # tolerate BOM (author edits on Windows)
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _rid(path: pathlib.Path):
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


CMETA_FILES = _collect("_cmeta.yaml", "_cmeta.json", "_cmr.yaml")
DESC_FILES = _collect("_desc.yaml")


def test_metadata_files_were_discovered():
    # Guard against the glob silently finding nothing (e.g. wrong root).
    assert CMETA_FILES, "no _cmeta.*/_cmr.yaml files found under the repo root"
    assert DESC_FILES, "no _desc.yaml files found under the repo root"


@pytest.mark.parametrize("path", CMETA_FILES, ids=_rid)
def test_cmeta_file_parses_and_has_identity(path):
    data = _load(path)
    assert isinstance(data, dict), f"{_rid(path)} did not parse to a mapping"
    assert data.get("artifact"), f"{_rid(path)} is missing an 'artifact' (UID)"
    assert data.get("category"), f"{_rid(path)} is missing a 'category' reference"


@pytest.mark.parametrize("path", DESC_FILES, ids=_rid)
def test_desc_file_parses(path):
    data = _load(path)
    # A _desc.yaml may legitimately be empty (comments only -> None); otherwise a mapping.
    assert data is None or isinstance(data, dict), f"{_rid(path)} must be a mapping or empty"
