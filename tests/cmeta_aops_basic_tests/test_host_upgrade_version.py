"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The verdict of "cx host upgrade" for the engine (2026-11-03): with --version, a host that ends on another version
failed - a declared "cmeta: upgrade" command does not get the version, and pip's cached view of PyPI kept a WSL
distro on the old release while the round said "already". Nothing here reaches a host.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def engine_step():
    spec = importlib.util.spec_from_file_location('host_upgrade_version_test', ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = next(v for v in vars(module).values() if isinstance(v, type) and hasattr(v, '_engine_step'))
    return cls._engine_step


def test_the_asked_version_or_a_failure():
    step = engine_step()
    assert step('0.38.1', '0.38.2', 0, '0.38.2') == ('0.38.1 -> 0.38.2', 0)
    assert step('0.38.1', '0.38.2', 0, 'v0.38.2') == ('0.38.1 -> 0.38.2', 0)
    assert step('0.38.1', '0.38.1', 0, '0.38.2') == ('asked 0.38.2, has 0.38.1 (unchanged)', 1)
    assert step('0.37.9', '0.38.1', 0, '0.38.2') == ('asked 0.38.2, has 0.38.1 (was 0.37.9)', 1)


def test_without_a_version_as_before():
    step = engine_step()
    assert step('0.38.1', '0.38.1', 0) == ('already 0.38.1', 0)
    assert step('0.38.1', '0.38.2', 0) == ('0.38.1 -> 0.38.2', 0)
    assert step('0.38.1', None, 0, '0.38.2') == ('0.38.1 -> ?', 0), 'an unknown version is not judged'
    assert step('0.38.1', '0.38.1', 2, '0.38.2') == ('exit code 2 (cMeta 0.38.1)', 2)
