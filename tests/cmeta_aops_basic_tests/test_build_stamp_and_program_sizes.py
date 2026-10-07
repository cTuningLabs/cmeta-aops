"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The stamp of a program's build folder (category/task/api/build_stamp.py): what a build was made for
(targets, host, compiler, compile parameters, Android device), the differences a run has from it, the
message that refuses a stale folder; where compile-and-run-program and setup-compile apply it. And the
_desc_sizes.yaml of programs: the files of the large build programs parse and have a default rule, the
rules select by targets with the engine's matching. Offline.
"""

import importlib.util
import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD_PROGRAMS = ['build-pytorch', 'build-vllm', 'build-llama-cpp', 'build-executorch-android', 'build-torch-cpp',
                  'build-pytorchvision']


def load(rel):
    path = REPO_ROOT / rel
    spec = importlib.util.spec_from_file_location(path.stem + '_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope = 'module')
def stamp():
    return load('category/task/api/build_stamp.py')


@pytest.fixture(scope = 'module')
def sizes():
    return load('category/tool/api/common_sizes.py')


# The stamp

def test_normalize_compile(stamp):
    assert stamp.normalize_compile(None) == {}
    assert stamp.normalize_compile({'static': False, 'debug_info': 'False', 'fastest': None, 'flags': '-O3'}) == {}
    assert stamp.normalize_compile({'static': True, 'openmp': 'True', 'profile': 1}) == {'static': 'true', 'openmp': 'true', 'profile': '1'}


def test_compiler_identity(stamp):
    assert stamp.compiler_identity(None) is None
    assert stamp.compiler_identity({'tool': {'name': 'clang'}, 'version': '20.1.0', 'path': '/usr/bin/clang'}) == \
           {'name': 'clang', 'version': '20.1.0', 'path': '/usr/bin/clang'}
    assert stamp.compiler_identity({'features': {}}) is None


def test_stamp_round_trip(stamp, tmp_path):
    assert stamp.read_stamp(str(tmp_path)) is None
    made = stamp.make_stamp('test-nmm-c-cpu', 'abc', ['cuda', 'cpu'], 'linux',
                            compiler = {'name': 'clang', 'version': '20.1.0', 'path': '/x/clang'},
                            compile_params = {'static': True}, android = {'serial': None, 'abi': None})
    assert made['compute'] == ['cpu', 'cuda'] and made['compile'] == {'static': 'true'} and made['android'] is None
    assert stamp.write_stamp(str(tmp_path), made) is None
    back = stamp.read_stamp(str(tmp_path))
    assert back == made
    (tmp_path / stamp.STAMP_FILE).write_text('not json')
    assert stamp.read_stamp(str(tmp_path)) is None


def test_differences(stamp):
    s = stamp.make_stamp('p', 'u', ['cpu'], 'darwin', compiler = {'name': 'clang', 'version': '17.0.0', 'path': '/usr/bin/cc'},
                         compile_params = {}, android = None)
    assert stamp.differences(s, compute = ['cpu'], host = 'darwin', compiler = None, compile_params = {}) == []
    assert stamp.differences(s, compute = ['android-cpu']) == [('targets', 'cpu', 'android-cpu')]
    assert stamp.differences(s, host = 'linux') == [('host', 'darwin', 'linux')]
    assert stamp.differences(s, compiler = {'name': 'gcc', 'version': '13.3.0'}) == [('compiler name', 'clang', 'gcc')]
    assert stamp.differences(s, compiler = {'name': 'clang', 'version': '20.1.0'}) == [('compiler version', '17.0.0', '20.1.0')]
    assert stamp.differences(s, compiler = {'name': 'clang', 'version': None}) == []          # only what is asked
    assert stamp.differences(s, compiler = {'name': None, 'version': None}) == []
    assert stamp.differences(s, compile_params = {'static': True}) == [('compile parameters', 'defaults', 'static=true')]
    assert stamp.differences(s, compile_params = {'static': 'False'}) == []
    # Optimization, debug, OpenMP and profiling flags are recorded but never refused for
    for flags in ({'fastest': True}, {'debug_info': True}, {'openmp': True}, {'profile': True}, {'fastest': True, 'openmp': True}):
        assert stamp.differences(s, compile_params = flags) == [], flags
    f = stamp.make_stamp('p', 'u', ['cpu'], 'linux', compile_params = {'fastest': True, 'openmp': True})
    assert f['compile'] == {'fastest': 'true', 'openmp': 'true'}                     # in the stamp
    assert stamp.differences(f, compile_params = {}) == []                            # a plain run after --compile.fastest
    assert stamp.differences(f, compile_params = {'openmp': True, 'static': True}) == [('compile parameters', 'defaults', 'static=true')]
    # Android: a stamp without a device compares nothing; one with a device compares the ABI and serial
    assert stamp.differences(s, android = {'serial': 'X', 'abi': 'arm64-v8a'}) == []
    a = stamp.make_stamp('p', 'u', ['android-cpu'], 'linux', android = {'serial': 'A1', 'abi': 'arm64-v8a'})
    assert stamp.differences(a, compute = ['android-cpu'], android = {'serial': 'B2', 'abi': 'arm64-v8a'}) == [('android serial', 'A1', 'B2')]
    assert stamp.differences(a, android = {'serial': None, 'abi': None}) == []


def test_same_plain_run_is_never_refused(stamp):
    """The stamp made for a run and the check of the identical run (the program's default compile
    parameters filled in both, or in neither) differ in nothing: a plain run after a plain run reuses."""
    for params in ({}, {'openmp': True}, {'openmp': True, 'd': {'X': 1}}, {'static': True, 'fastest': True}):
        s = stamp.make_stamp('p', 'u', ['cpu'], 'windows', compiler = {'name': 'clang', 'version': '22.1.1', 'path': 'c'},
                             compile_params = params)
        assert stamp.differences(s, compute = ['cpu'], host = 'windows', compiler = {'name': 'clang', 'version': '22.1.1'},
                                 compile_params = params) == []
    # A stamp made for an old folder without the defaults (the saved origin parameters) and the live
    # request with them: not a difference either, since the defaults are not compared keys
    old = stamp.make_stamp('p', 'u', ['cpu'], 'windows', compile_params = {})
    assert stamp.differences(old, compile_params = {'openmp': True}) == []


def test_refusal_message(stamp):
    s = stamp.make_stamp('build-llama-cpp', 'u', ['cpu'], 'darwin', compiler = {'name': 'clang', 'version': '17.0.0', 'path': '/usr/bin/cc'},
                         compile_params = {'static': True})
    assert stamp.built_for(s) == 'cpu with clang 17.0.0 (static=true)'
    noisy = stamp.make_stamp('p', 'u', ['cpu'], 'linux', compile_params = {'openmp': True, 'fastest': True})
    assert stamp.built_for(noisy) == 'cpu'                                            # recorded flags are not shown
    m = stamp.refusal_message('/cache/task--program--build-llama-cpp/tmp', s, stamp.differences(s, compute = ['android-cpu']))
    assert m.startswith('"/cache/task--program--build-llama-cpp/tmp" was built for cpu with clang 17.0.0 (static=true); '
                        'this run asks for android-cpu (targets): ')
    for option in ('--target_tmp=<name>', '--recompile', '--clean'):
        assert option in m


def test_where_the_guard_runs():
    """compile-and-run-program: the reuse path refuses or stamps a stamp-less folder; the recompile
    path refuses an implied recompile, checks the disk, opens the deadline, writes the stamp after a
    successful compile; setup-compile compares the resolved compiler."""
    src = (REPO_ROOT / 'task' / 'compile-and-run-program' / 'api_v1.py').read_text(encoding = 'utf-8')
    i_reuse = src.index("r = self.refuse_stale_build(ctx, target_path, _facts)")
    i_stampless = src.index("# A folder made before the stamps", i_reuse)
    i_implied = src.index("if not params.get('recompile'):\n                        r = self.refuse_stale_build", i_stampless)
    i_disk = src.index("r = self.check_program_disk_space(", i_implied)
    i_deadline = src.index("compile_deadline = deadlines.open_deadline(", i_disk)
    i_access = src.index("r = self.cm.access(p)", i_deadline)
    i_record = src.index("_impact['disk_gb'] = round(sizes.folder_gb(target_path), 6)", i_access)
    i_save = src.index("write_file(path_repro_compile", i_record)
    i_stamp = src.index("self.write_build_stamp(ctx, target_path, artifact_alias, artifact_uid,\n", i_save)
    assert i_reuse < i_stampless < i_implied < i_disk < i_deadline < i_access < i_record < i_save < i_stamp
    i_push = src.index("ctx['tasks'].setdefault('build_stamps', []).append({'target_path': target_path, 'rebuild': bool(params.get('recompile'))})", i_disk)
    i_pop = src.index("ctx['tasks']['build_stamps'].pop()", i_access)
    assert i_disk < i_push < i_deadline and i_access < i_pop < i_record       # pushed before, popped in the finally
    setup_compile = (REPO_ROOT / 'task' / 'setup-compile' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "guard = (ctx['tasks'].get('build_stamps') or [None])[-1]" in setup_compile
    assert "if guard and not guard.get('rebuild'):" in setup_compile
    assert "build_stamp.differences(stamp, compiler = build_stamp.compiler_identity(_global[global_compiler_key]))" in setup_compile


# The sizes of programs

@pytest.mark.parametrize('program', BUILD_PROGRAMS)
def test_program_sizes_files(sizes, program):
    rules = sizes.load_sizes(str(REPO_ROOT / 'program' / program))
    assert rules, f'{program} has no _desc_sizes.yaml rules'
    defaults = [r for r in rules if not r.get('if')]
    assert len(defaults) == 1 and defaults[0] is rules[-1], 'exactly one default rule, last'
    for r in rules:
        assert isinstance(r.get('peak'), (int, float)) and r['peak'] > 0
        assert 'kept' not in r or (isinstance(r['kept'], (int, float)) and r['kept'] <= r['peak'])
        for key in (r.get('if') or {}):
            assert key in ('compute', 'os', 'arch', 'version', 'with', 'method')


def test_program_rule_selection(sizes):
    from cmeta.utils.common import matches_query
    rules = sizes.load_sizes(str(REPO_ROOT / 'program' / 'build-pytorch'))
    cuda = sizes.select_rule(rules, sizes.request_facts(os_name = 'linux', arch = 'amd64', method = 'build', compute = ['cpu', 'cuda']), matches_query)
    cpu = sizes.select_rule(rules, sizes.request_facts(os_name = 'linux', arch = 'amd64', method = 'build', compute = ['cpu']), matches_query)
    assert cuda['peak'] > cpu['peak'] and cuda is rules[0] and cpu is rules[-1]
    llama = sizes.load_sizes(str(REPO_ROOT / 'program' / 'build-llama-cpp'))
    assert sizes.select_rule(llama, sizes.request_facts(os_name = 'windows', method = 'build', compute = ['vulkan']), matches_query) is llama[-1]


def test_no_measurements_in_public_size_files():
    """The public files carry rounded rules only: whole numbers of GB, no decimals of a measurement."""
    for program in BUILD_PROGRAMS:
        text = (REPO_ROOT / 'program' / program / '_desc_sizes.yaml').read_text(encoding = 'utf-8')
        for line in text.splitlines():
            if 'peak:' in line or 'kept:' in line:
                value = line.split(':', 1)[1].split('#')[0].strip()
                assert value.isdigit(), f'{program}: {line.strip()}'


def test_source_digests_follow_the_code_files_and_the_stamp_sees_a_change(stamp, tmp_path):
    """The declared source and the headers next to it are tracked; data files and tmp folders are not; an
    edited or added file is named; a stamp without digests (before 0.43.3) compares nothing."""
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'main.c').write_text('int main(void) { return 0; }\n')
    (src / 'util.h').write_text('#define X 1\n')
    (src / 'data.bin').write_bytes(b'\x00' * 16)
    (src / 'tmp-out').mkdir()
    (src / 'tmp-out' / 'left.c').write_text('ignored\n')
    (src / '.hidden').mkdir()
    (src / '.hidden' / 'also.c').write_text('ignored\n')

    digests = stamp.source_digests(str(src), ['main.c'])
    assert set(digests) == {'main.c', 'util.h'}
    assert all(len(v) == 64 for v in digests.values())

    s = stamp.make_stamp('p', 'u', ['cpu'], 'linux', sources = digests)
    assert s['sources'] == digests
    assert stamp.sources_changed(s, digests) == []

    (src / 'util.h').write_text('#define X 2\n')
    assert stamp.sources_changed(s, stamp.source_digests(str(src), ['main.c'])) == ['util.h']

    (src / 'more.cpp').write_text('\n')
    (src / 'util.h').write_text('#define X 1\n')
    assert stamp.sources_changed(s, stamp.source_digests(str(src), ['main.c'])) == ['more.cpp']

    (src / 'main.c').unlink()
    assert 'main.c' in stamp.sources_changed(s, stamp.source_digests(str(src), ['main.c']))

    assert stamp.sources_changed({'version': 1, 'compute': ['cpu']}, digests) is None
    assert stamp.sources_changed(s, None) is None
    assert stamp.source_digests(str(tmp_path / 'nowhere'), ['main.c']) is None
    assert stamp.make_stamp('p', 'u', ['cpu'], 'linux')['sources'] is None
