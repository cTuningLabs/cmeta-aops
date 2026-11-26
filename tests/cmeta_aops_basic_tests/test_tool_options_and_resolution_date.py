"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of two small helpers (2026-11-24):
- ctask.supported_options: which options a program of any version takes, asked of its own help (task/setup-run gives
  nsys --trace-fork-before-exec only where its nsys has it);
- common_pyvenv.resolution_date and tool/pip's --with.exclude_newer: the day a package's dependencies are resolved as
  of - a day, or "release" (the day after the pinned version was uploaded), given to pip as --uploaded-prior-to where
  that pip has the option, refused where it has not.
"""

import importlib.util
import pathlib
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope = 'module')
def ctask():
    return load('ctask_options_under_test', REPO_ROOT / 'category' / 'task' / 'api' / 'ctask.py')


@pytest.fixture(scope = 'module')
def pyvenv():
    # (its one import of the tool category API is stood in for: the module needs no cMeta for these functions)
    release = types.ModuleType('tool_c393ba5c6fa14f66.api.common_release')
    release.default_version = lambda tool, spec: None
    for name in ('tool_c393ba5c6fa14f66', 'tool_c393ba5c6fa14f66.api'):
        sys.modules.setdefault(name, types.ModuleType(name))
    saved = sys.modules.get('tool_c393ba5c6fa14f66.api.common_release')
    sys.modules['tool_c393ba5c6fa14f66.api.common_release'] = release
    try:
        return load('common_pyvenv_under_test', REPO_ROOT / 'category' / 'tool' / 'api' / 'common_pyvenv.py')
    finally:
        if saved is None:
            sys.modules.pop('tool_c393ba5c6fa14f66.api.common_release', None)
        else:
            sys.modules['tool_c393ba5c6fa14f66.api.common_release'] = saved


# ---------------------------------------------------------------- the options a program takes
def program(tmp_path, help_text):
    """A program that prints this help for "profile --help"."""
    script = tmp_path / 'tool.py'
    script.write_text('import sys\nif sys.argv[1:] == ["profile", "--help"]:\n    print(%r)\n' % help_text)
    return [sys.executable, str(script)]


def test_an_option_the_help_names_is_taken_and_one_it_does_not_name_is_not(ctask, tmp_path, monkeypatch):
    real = ctask.supported_options
    with_it = program(tmp_path, 'usage: profile [options]\n\t--trace-fork-before-exec=\n\t   Possible values are true or false.\n\t--stats=')
    # (the program is "python tool.py": its first word is the program, the script goes with the help words)
    assert real(with_it[0], [with_it[1], 'profile', '--help'], ['--trace-fork-before-exec', '--no-such']) == ['--trace-fork-before-exec']
    (tmp_path / 'w').mkdir()
    without = program(tmp_path / 'w', 'usage: profile [options]\n\t--trace=\n\t--stats=')
    assert real(without[0], [without[1], 'profile', '--help'], ['--trace-fork-before-exec']) == []


def test_an_option_is_a_whole_word_of_the_help(ctask, tmp_path):
    p = program(tmp_path, '--trace-fork-before-exec-all=  --xtrace  --stats-all')
    assert ctask.supported_options(p[0], [p[1], 'profile', '--help'], ['--trace-fork-before-exec', '--trace', '--stats']) == []


def test_a_program_that_cannot_run_takes_none(ctask, tmp_path):
    assert ctask.supported_options(str(tmp_path / 'no-such-program'), ['--help'], ['--x']) == []


def test_setup_run_asks_nsys_for_the_fork_option():
    src = (REPO_ROOT / 'task' / 'setup-run' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "supported_options(_global['nsys'].get('path') or str(nsys).strip('\"')," in src
    assert "['--trace-fork-before-exec', '--force-overwrite']))" in src        # a run again replaces the report
    assert "profile --trace=cuda,nvtx{follow} --stats=true -o cuda_profile" in src
    # the summary of a run again in the same folder: the export of the run before is replaced (2026-11-25)
    assert "['stats', '--help'], ['--force-export']))" in src
    assert "stats{force} --report cuda_gpu_kern_sum cuda_profile.nsys-rep" in src


def test_a_tool_script_on_windows_runs_with_its_folder_searched():
    """An agent's shell sets NoDefaultCurrentDirectoryInExePath: Intel's oneapi-vars.bat ("pushd", "call vars.bat")
    then failed for every component (2026-11-25) - task/setup clears it for the script it calls."""
    src = (REPO_ROOT / 'task' / 'setup' / 'detect.py').read_text(encoding = 'utf-8')
    assert "cmd_call = 'set \"NoDefaultCurrentDirectoryInExePath=\" ' + host['vars']['cmd_sep'] + ' ' + cmd_call" in src


# ---------------------------------------------------------------- the resolution date
def test_a_day_is_taken_as_it_is_and_release_is_the_day_after_the_upload(pyvenv):
    d = pyvenv.resolution_date
    assert d(None, 'vllm', '0.10.2') == '' and d('', 'vllm', '0.10.2') == '' and d('no', 'vllm', '0.10.2') == ''
    assert d('2025-09-20', 'vllm', '0.10.2') == '2025-09-20'
    assert d('2025-09-20T12:00:00Z', 'vllm', None) == '2025-09-20'
    assert d('release', 'vllm', '0.10.2', lookup = lambda package, version: '2025-09-13') == '2025-09-14'
    assert d('RELEASE', 'x', '1', lookup = lambda package, version: '2025-12-31') == '2026-01-01'


@pytest.mark.parametrize('asked', ['yesterday', '2025-13-40', '20250920', '09/20/2025'])
def test_what_is_no_day_is_refused(pyvenv, asked):
    with pytest.raises(ValueError, match = 'YYYY-MM-DD'):
        pyvenv.resolution_date(asked, 'vllm', '0.10.2')


def test_release_needs_a_version_and_says_when_pypi_does_not_answer(pyvenv):
    with pytest.raises(ValueError, match = 'needs a version'):
        pyvenv.resolution_date('release', 'vllm', None)

    def no_answer(package, version):
        raise ValueError('PyPI does not say when vllm 9.9.9 was released')

    with pytest.raises(ValueError, match = 'PyPI does not say'):
        pyvenv.resolution_date('release', 'vllm', '9.9.9', lookup = no_answer)


def test_the_upload_day_is_the_first_file_of_the_version(pyvenv, monkeypatch):
    import io
    import json

    answer = {'urls': [{'upload_time_iso_8601': '2025-09-13T18:22:01.123456Z'}, {'upload_time_iso_8601': '2025-09-12T23:59:59Z'}]}
    asked = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(url, timeout = None):
        asked.append(url)
        return Resp(json.dumps(answer).encode())

    monkeypatch.setattr(pyvenv.urllib.request, 'urlopen', urlopen)
    assert pyvenv.pypi_upload_day('vllm', '0.10.2') == '2025-09-12'
    assert asked == ['https://pypi.org/pypi/vllm/0.10.2/json']
    answer['urls'] = []
    with pytest.raises(ValueError, match = 'no upload time'):
        pyvenv.pypi_upload_day('vllm', '0.10.2')


def test_uv_gets_the_day_and_pip_gets_it_only_where_it_has_the_option():
    src = (REPO_ROOT / 'category' / 'tool' / 'api' / 'common_pyvenv.py').read_text(encoding = 'utf-8')
    assert "older = f' --exclude-newer {day}' if day else ''" in src and "{uv} pip install{older} --python" in src
    pip = (REPO_ROOT / 'tool' / 'pip' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "supported_options(python, ['-m', 'pip', 'install', '--help'], ['--uploaded-prior-to'])" in pip
    assert "--uploaded-prior-to={day}T00:00:00Z" in pip and "'exclude_newer'," in pip
    assert 'has no ' in pip and 'or drop the option' in pip             # refused, never dropped silently
