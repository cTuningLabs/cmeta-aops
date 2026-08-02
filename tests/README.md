# Tests

Basic, hermetic pytest smoke tests for the `cmeta-aops` content repository.

## Run

```bash
uv run python -m pytest tests          # preferred (uv provides pytest + cmeta)
uv run python -m pytest tests -q       # quiet
python -m pytest tests                 # if cmeta + pytest are already importable
```

`uv` reads the root `pyproject.toml`, which pulls `cmeta` from the local framework
via the `__symlinks/cmeta` path source. Create that symlink first (Windows:
`_create_symlinks_for_ai_context_min.bat`) if it does not exist.

## What is covered (`tests/basic_tests/`)

- **`test_engine.py`** — cMeta imports/versions; this repo is plugged and
  discoverable; the uniform `access()` return contract holds for a missing artifact.
- **`test_categories.py`** — the main categories (`task`, `tool`, `program`) and the
  auxiliary ones (`model`, `dataset`, `docker`) are registered; the populated ones
  resolve their artifacts and every result carries the right category ref.
- **`test_artifacts.py`** — foundational task artifacts resolve by `alias`, by `UID`,
  and by `alias,UID`, including the rename-safe rule that the **UID is authoritative**
  when a wrong alias is paired with a correct UID.
- **`test_metadata_integrity.py`** — every canonical `_cmeta.yaml` / `_cmeta.json` /
  `_cmr.yaml` / `_desc.yaml` parses and carries its identity (`artifact` + `category`).
  One parametrized case per file (scratch/backup siblings like `_desc.yaml2` are
  skipped by design).
- **`test_task_runs.py`** — offline end-to-end runs of the task engine
  (`generate-temp-file`, `print-text`, `host`) plus the `--info` help path, exercising
  `params_map`, the `init`/`run` hooks, and `uses` sub-task pipelines.

## Design notes

- **Hermetic:** `conftest.py` points `CMETA_HOME` at a throwaway temp dir and plugs
  this repo into it, so tests never touch your global cMeta state.
- **Offline:** no network access or toolchain installs. Tests that would download or
  build tools (see the per-artifact `test*.bat` / `tests/` CLI recipes) are **not**
  part of this suite.
