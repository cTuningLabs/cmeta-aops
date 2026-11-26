"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of two small helpers (2026-11-24):
- ctask.supported_options: which options a program of any version takes, asked of its own help (task/setup-run gives
  nsys --trace-fork-before-exec only where its nsys has it);
- common_pyvenv.resolution_date and tool/pip's --with.exclude_newer: the day a package's dependencies are resolved as
  of - a day, or "release" (the day after the pinned version was uploaded), given to pip as --uploaded-prior-to where
  that pip has the option, refused where it has not.
- common_pyvenv's SPEC key "index" (2026-11-26): a vendor's own package index instead of PyPI for a tool's environment.
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

    # the stand-ins are there for the load only: one left behind would be found, in place of the real package, by a
    # test that runs the tool category after this one (the tests of a few files run alone, 2026-11-26)
    added = [name for name in ('tool_c393ba5c6fa14f66', 'tool_c393ba5c6fa14f66.api') if name not in sys.modules]
    for name in added:
        sys.modules[name] = types.ModuleType(name)
    saved = sys.modules.get('tool_c393ba5c6fa14f66.api.common_release')
    sys.modules['tool_c393ba5c6fa14f66.api.common_release'] = release
    try:
        return load('common_pyvenv_under_test', REPO_ROOT / 'category' / 'tool' / 'api' / 'common_pyvenv.py')
    finally:
        if saved is None:
            sys.modules.pop('tool_c393ba5c6fa14f66.api.common_release', None)
        else:
            sys.modules['tool_c393ba5c6fa14f66.api.common_release'] = saved
        for name in added:
            sys.modules.pop(name, None)


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
    assert "each = f'{nsys} stats{force} --report cuda_gpu_kern_sum'" in src and "x = f'{each} cuda_profile.nsys-rep'" in src


@pytest.fixture(scope = 'module')
def capture_range():
    """setup-run's capture_range: the module's text between its imports and its class (the class needs cMeta)."""
    src = (REPO_ROOT / 'task' / 'setup-run' / 'api_v1.py').read_text(encoding = 'utf-8')
    ns = {}
    exec(compile('import re\n' + src[src.index('# What "nsys profile --capture-range-end" takes'):src.index('class CTask(InitCTask)')],
                 'setup-run capture_range', 'exec'), ns)
    return ns['capture_range']


def test_no_range_asked_no_words(capture_range):
    assert capture_range(None) == ([], '')
    assert capture_range('', '') == ([], '')

    # what the end of a range does, without a range: said, never passed over
    words, why = capture_range(None, 'repeat')
    assert words == [] and 'needs --profile_cuda_range' in why


def test_the_range_of_the_cuda_profiler_calls(capture_range):
    # the end is always said: nsys's own (stop-shutdown) ends the program with the first range - what it writes
    # after its range was lost (seen with Nsight Systems 2026.2 on Windows, 2026-11-26)
    assert capture_range('cudaProfilerApi') == (['--capture-range=cudaProfilerApi', '--capture-range-end=stop'], '')
    assert capture_range('CUDAPROFILERAPI')[0][0] == '--capture-range=cudaProfilerApi'
    assert capture_range('cudaProfilerApi', 'repeat')[0][1] == '--capture-range-end=repeat'
    assert capture_range('cudaProfilerApi', 'repeat:2')[0][1] == '--capture-range-end=repeat:2'
    assert capture_range('cudaProfilerApi', 'repeat:2:sync')[0][1] == '--capture-range-end=repeat:2:sync'
    assert capture_range('cudaProfilerApi', 'repeat-shutdown:3')[0][1] == '--capture-range-end=repeat-shutdown:3'
    assert capture_range('cudaProfilerApi', 'stop-shutdown')[0][1] == '--capture-range-end=stop-shutdown'
    assert capture_range('cudaProfilerApi', 'none')[0][1] == '--capture-range-end=none'


def test_an_nvtx_range_with_or_without_its_domain(capture_range):
    # nsys compares a range's name with registered NVTX strings only: one pushed with a plain string
    # (torch.cuda.nvtx.range_push) started no recording until the program was told to compare them all
    assert capture_range('nvtx:decode') == (['--capture-range=nvtx', '--nvtx-capture=decode',
                                             '--env-var=NSYS_NVTX_PROFILER_REGISTER_ONLY=0', '--capture-range-end=stop'], '')
    assert capture_range('nvtx:decode@vllm')[0][1] == '--nvtx-capture=decode@vllm'
    assert capture_range('NVTX: a step @*')[0][1] == '--nvtx-capture=a step @*'


@pytest.mark.parametrize('asked, end, word', [('hotkey', None, 'hotkey'), ('nvtx:', None, 'nvtx:'), ('yes', None, 'yes'),
                                              ('cudaProfilerApi', 'again', 'again'), ('cudaProfilerApi', 'repeat-shutdown', 'repeat-shutdown'),
                                              ('cudaProfilerApi', 'repeat:x', 'repeat:x'), ('cudaProfilerApi', 'stop;rm', 'stop;rm'),
                                              ('nvtx:a&b', None, 'a shell reads'), ('nvtx:a;b', None, 'a shell reads'), ('nvtx:$(x)', None, 'a shell reads')])
def test_what_nsys_does_not_take_is_an_error(capture_range, asked, end, word):
    words, why = capture_range(asked, end)
    assert words == [] and word in why


def test_setup_run_asks_this_nsys_for_the_range_options_and_the_template_hands_them_on():
    src = (REPO_ROOT / 'task' / 'setup-run' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "capture_range(params.get('profile_cuda_range'), params.get('profile_cuda_range_end'))" in src
    assert "supported_options(nsys_path, ['profile', '--help'], needed)" in src
    # the summaries of a ranged run: its helper (one report, or one per range with "repeat"; words when there is none)
    assert "helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nsys_range_reports.py')" in src
    template = (REPO_ROOT / 'program' / 'template-c-cpu' / '_desc.yaml').read_text(encoding = 'utf-8')
    assert "profile_cuda_range: '{{params.profile_cuda_range|$None}}'" in template
    assert "profile_cuda_range_end: '{{params.profile_cuda_range_end|$None}}'" in template


@pytest.fixture(scope = 'module')
def range_reports():
    spec = importlib.util.spec_from_file_location('nsys_range_reports_under_test',
                                                  REPO_ROOT / 'task' / 'setup-run' / 'nsys_range_reports.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_reports_of_a_ranged_run(range_reports, tmp_path, monkeypatch, capfd):
    monkeypatch.chdir(tmp_path)
    stats = [sys.executable, '-c', 'import sys; print("summary of", sys.argv[-1])', 'stats', '--report', 'cuda_gpu_kern_sum']

    # a program that never met its range: no report - said, exit 1, nothing run
    assert range_reports.main(['x', 'nvtx:decode'] + stats) == 1
    assert 'recorded nothing - the program never met the range nvtx:decode' in capfd.readouterr().err

    # one report (the end of the range is "stop")
    (tmp_path / 'cuda_profile.nsys-rep').write_text('')
    assert range_reports.main(['x', 'cudaProfilerApi'] + stats) == 0
    assert capfd.readouterr().out.split() == ['summary', 'of', 'cuda_profile.nsys-rep']

    # a report per range ("repeat"), in their order - 10 after 9, and the plain name of a run before is not theirs
    for n in (10, 2, 1):
        (tmp_path / f'cuda_profile.{n}.nsys-rep').write_text('')
    (tmp_path / 'cuda_profile.1.sqlite').write_text('')
    assert range_reports.reports(str(tmp_path)) == ['cuda_profile.1.nsys-rep', 'cuda_profile.2.nsys-rep', 'cuda_profile.10.nsys-rep']
    assert range_reports.main(['x', 'cudaProfilerApi'] + stats) == 0
    out = capfd.readouterr().out
    assert out.count('summary of') == 3 and out.index('cuda_profile.2.nsys-rep') < out.index('cuda_profile.10.nsys-rep')

    # a summary that fails stops the rest with its exit code
    failing = [sys.executable, '-c', 'import sys; sys.exit(3)']
    assert range_reports.main(['x', 'cudaProfilerApi'] + failing) == 3


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
    assert "older = f' --exclude-newer {day}' if day else ''" in src and "{uv} pip install{older}{source} --python" in src
    pip = (REPO_ROOT / 'tool' / 'pip' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "supported_options(python, ['-m', 'pip', 'install', '--help'], ['--uploaded-prior-to'])" in pip
    assert "--uploaded-prior-to={day}T00:00:00Z" in pip and "'exclude_newer'," in pip
    assert 'has no ' in pip and 'or drop the option' in pip             # refused, never dropped silently


# ---------------------------------------------------------------- a vendor's own package index
class FakeEngine:
    """Records the commands run; runs nothing."""

    def __init__(self):
        self.runs = []
        me = self

        class Sys:
            @staticmethod
            def run(command, **kw):
                me.runs.append(command)
                return {'return': 0, 'returncode': 0}

        class Utils:
            sys = Sys

        self.utils = Utils

    def access(self, ii):
        return {'return': 0, 'tool_path': 'uv'}

    def catch_error(self, r, fail16 = False):
        return r['return'] > 0 and (r['return'] != 16 or fail16)

    def error(self, text, *a, **kw):
        return {'return': 1, 'error': text}


def environment(tmp_path, command):
    """An environment made already, with this command in it; the tool and the context of an install."""
    bindir = tmp_path / 'venv' / ('Scripts' if sys.platform == 'win32' else 'bin')
    bindir.mkdir(parents = True, exist_ok = True)
    uname = 'windows' if sys.platform == 'win32' else 'linux'
    exe = '.exe' if uname == 'windows' else ''
    for name in ('python', command):
        (bindir / (name + exe)).write_text('')
    tool = type('T', (), {})()
    tool.cm = FakeEngine()
    ctx = {'tasks': {'nested_call': 0, 'global': {'host': {'os': {'uname': uname}, 'vars': {'file_ext_exe': exe}}, 'uv': {'qpath': 'uv'}}}}
    return tool, ctx


def test_the_words_of_an_index(pyvenv):
    words = pyvenv.index_words
    assert words(None) == '' and words('') == '' and words('  ') == ''
    assert words(' https://stable.repo.example/rocm/whl-next/ ') == ' --index-url https://stable.repo.example/rocm/whl-next/'
    for wrong in ('stable.repo.example/simple', 'file:///tmp/wheels', 'https://a.example/simple --extra-index-url https://b.example',
                  'https://a.example/simple; rm -rf x', 'https://a.example/"simple"'):
        with pytest.raises(ValueError, match = 'no plain http'):
            words(wrong)


def test_an_environment_is_filled_from_the_index_of_its_spec(pyvenv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool, ctx = environment(tmp_path, 'vendor-tool')
    spec = {'name': 'vendor-tool', 'package': 'vendor[profiler]', 'python': '3.12', 'index': 'https://wheels.example/simple/'}

    r = pyvenv.install_pyvenv(tool, ctx, {'control': {}, 'version': '10.2.0', 'version_simple': '10.2.0'}, None, spec)
    assert r['return'] == 0 and r['found_path'].replace('.exe', '').endswith('vendor-tool')
    installs = [c for c in tool.cm.runs if ' pip install ' in c]
    assert len(installs) == 1 and ' --index-url https://wheels.example/simple/ ' in installs[0]
    assert installs[0].endswith('"vendor[profiler]==10.2.0"')

    # with a day: both; without an index: PyPI, as before
    tool.cm = FakeEngine()
    pyvenv.install_pyvenv(tool, ctx, {'control': {}, 'version': '10.2.0', 'version_simple': '10.2.0', 'with': {'exclude_newer': '2026-11-01'}},
                          None, spec)
    assert ' --exclude-newer 2026-11-01 --index-url https://wheels.example/simple/ ' in tool.cm.runs[-1]
    tool.cm = FakeEngine()
    pyvenv.install_pyvenv(tool, ctx, {'control': {}, 'version': '1.0', 'version_simple': '1.0'}, None, {'name': 'vendor-tool', 'python': '3.12'})
    assert '--index-url' not in tool.cm.runs[-1]


def test_the_python_of_an_environment_is_a_version_or_a_path(pyvenv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool, ctx = environment(tmp_path, 'vendor-tool')
    params = {'control': {}, 'version': '1.0', 'version_simple': '1.0'}

    # (no environment yet: it is made first)
    for name in ('python', 'python.exe'):
        for folder in ('bin', 'Scripts'):
            made = tmp_path / 'venv' / folder / name
            if made.is_file():
                made.unlink()

    pyvenv.install_pyvenv(tool, ctx, params, None, {'name': 'vendor-tool', 'python': '3.12'})
    assert tool.cm.runs[0].startswith('uv venv --python "3.12" ')
    tool.cm = FakeEngine()
    pyvenv.install_pyvenv(tool, ctx, params, None, {'name': 'vendor-tool', 'python': '/usr/bin/python3'})
    assert tool.cm.runs[0].startswith('uv venv --python "/usr/bin/python3" ')


def test_what_an_index_cannot_do_is_said(pyvenv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool, ctx = environment(tmp_path, 'vendor-tool')
    spec = {'name': 'vendor-tool', 'python': '3.12', 'index': 'https://wheels.example/simple/'}
    params = {'control': {}, 'version': '1.0', 'version_simple': '1.0'}

    # the release day is PyPI's: not known for a package of another index
    r = pyvenv.install_pyvenv(tool, ctx, dict(params, **{'with': {'exclude_newer': 'release'}}), None, spec)
    assert r['return'] == 1 and 'give the day' in r['error'] and tool.cm.runs == []

    # an index that is no address installs nothing
    r = pyvenv.install_pyvenv(tool, ctx, params, None, dict(spec, index = 'wheels.example --pre'))
    assert r['return'] == 1 and 'no plain http' in r['error'] and tool.cm.runs == []

