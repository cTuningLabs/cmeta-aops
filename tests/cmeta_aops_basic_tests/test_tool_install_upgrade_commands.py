"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool install <tool>" and "cx tool upgrade <tool>" (the user's wish, 2026-10-30): "cx tool setup <tool> --install"
and "--upgrade" in short - the same setup task, the same parameters, the flag set. And the version check of a cached
tool runs for the tool named with --check_versions on the command line: before, no entry was ever checked (the
reader took a missing skip_cache_version_check as True) - a driver replaced under the cache (CUDA 13.3 -> 13.2 on
the laptop) stayed 13.3 even when asked.
"""

import importlib.util
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def tool_category():
    spec = importlib.util.spec_from_file_location('category_tool_under_test', str(REPO_ROOT / 'category' / 'tool' / 'api' / 'v1.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    category = module.Category.__new__(module.Category)
    seen = []
    category.setup = lambda params: seen.append(params) or {'return': 0}
    return category, seen


def test_install_and_upgrade_are_setup_with_the_flag():
    category, seen = tool_category()
    assert category.install({'arg1': 'nvcc', 'version': '13.2', 'ctx': {}}) == {'return': 0}
    assert category.upgrade({'arg1': 'git', 'ctx': {}}) == {'return': 0}
    assert seen[0] == {'arg1': 'nvcc', 'version': '13.2', 'ctx': {}, 'install': True}
    assert seen[1] == {'arg1': 'git', 'ctx': {}, 'upgrade': True}


def test_the_cached_version_check_is_for_the_tool_asked_on_the_command_line():
    """Only an explicit --check_versions of this call checks (the user, 2026-10-30): a global check_versions would run the
    version command of every nested tool at every reuse and throw away the entries of tools that update themselves.
    Proven on the laptop with a stale driver entry (check_versions_proof.sh of session 20261030/1542)."""
    src = (REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py').read_text(encoding='utf-8')
    assert "explicit_check = check_versions is True or str(check_versions).strip().lower() in ('true', 'yes', 'on', '1')" in src
    assert "cache_artifact['cmeta'].get('skip_cache_version_check', not explicit_check)" in src
    assert src.index('explicit_check = ') < src.index("get('init', {}).get('tool', {}).get('check_versions')")
