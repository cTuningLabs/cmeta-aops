"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/compiler's choice among cached compilers (filter_cache_artifacts, called by the task engine before it
offers the matching cache entries or takes the first in quiet mode): a cached compiler whose version is
outside the limit the run sets for its tool (tool/nvcc's host-compiler limits, --use.<tool>.version) or whose
tool lacks the request's extra_tags or fails its extra_match is dropped; for the host compiler of nvcc the
tool the repository ranks first (msvc, gcc, clang) wins, then the newest version, with no prompt; other
requests keep the engine's choice among the remaining entries. The tool metas come from this repository,
plugged into the isolated CMETA_HOME.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = 'tool,c393ba5c6fa14f66'
NVCC_LINUX = {'constraints': {'supports_nvcc_os': ['linux']}}
NVCC_WINDOWS = {'constraints': {'supports_nvcc_os': ['windows']}}
LIMITS_12_9 = {'clang-cpp': {'version': '<20'}, 'gcc-cpp': {'version': '<15'}}   # CUDA 12.9: clang below 20, GCC up to 14


@pytest.fixture(scope = 'module')
def compiler(cm):
    path = REPO_ROOT / 'task' / 'compiler' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8').replace('from task_c36be4b9314a45e0.api.ctask import InitCTask',
                                                     'class InitCTask: pass')
    ns = {'__name__': 'task_compiler', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    task = object.__new__(ns['CTask'])
    task.cm = cm
    task.cmeta = {'uses_categories': {'tool': TOOL, 'utils': 'utils,234ce5e3262e4d52'}}
    return task


def entry(name, version, compute = 'cuda', lang = 'cpp'):
    return {'path': f'/cache/{name}-{version}',
            'cmeta': {'params': {'lang': lang, 'name': name, 'version': version, 'compute': [compute]}}}


def ctx(uname = 'linux', use = None, con = False):
    return {'control': {'con': con},
            'tasks': {'global': {'host': {'os': {'uname': uname}}}, 'use': use or {}}}


def chosen(r, key = 'artifacts'):
    return [a['cmeta']['params']['name'] + ' ' + a['cmeta']['params']['version'] for a in r[key]]


def test_the_toolkits_limit_drops_a_compiler_it_rejects(compiler):
    r = compiler.filter_cache_artifacts(ctx(use = LIMITS_12_9),
                                        [entry('clang-cpp', '21.0.0'), entry('gcc-cpp', '13.3.0')], [],
                                        {'lang': 'cpp', 'compute': 'cuda', 'extra_match': NVCC_LINUX})
    assert r['return'] == 0 and chosen(r) == ['gcc-cpp 13.3.0']


def test_nvcc_takes_the_compiler_of_the_os_then_the_newest(compiler, capsys):
    r = compiler.filter_cache_artifacts(ctx(use = LIMITS_12_9, con = True),
                                        [entry('clang-cpp', '18.1.3'), entry('gcc-cpp', '13.3.0'), entry('gcc-cpp', '14.2.0')], [],
                                        {'lang': 'cpp', 'compute': 'cuda', 'extra_match': NVCC_LINUX})
    assert chosen(r) == ['gcc-cpp 14.2.0']
    out = capsys.readouterr().out
    assert 'taking gcc-cpp 14.2.0' in out and 'clang-cpp 18.1.3' in out and '--use.compiler-cpp.name' in out


def test_nvcc_with_a_named_tool_takes_its_newest_version(compiler, capsys):
    r = compiler.filter_cache_artifacts(ctx(use = LIMITS_12_9),
                                        [entry('clang-cpp', '18.1.3'), entry('clang-cpp', '19.1.7')], [],
                                        {'lang': 'cpp', 'compute': 'cuda', 'name': 'clang-cpp', 'extra_match': NVCC_LINUX})
    assert chosen(r) == ['clang-cpp 19.1.7']
    assert capsys.readouterr().out == ''      # nothing printed without the console


def test_msvc_limit(compiler):
    use = {'msvc': {'version': '>=19.10,<19.50'}}   # CUDA 12.8: Visual Studio 2017 to 2022
    r = compiler.filter_cache_artifacts(ctx('windows', use),
                                        [entry('msvc', '19.50.35726'), entry('msvc', '19.44.35207')], [],
                                        {'lang': 'cpp', 'compute': 'cuda', 'extra_match': NVCC_WINDOWS})
    assert chosen(r) == ['msvc 19.44.35207']


def test_an_explicit_version_is_left_to_the_toolkits_check(compiler):
    """--use.compiler-cpp.version=21 with a toolkit that rejects clang 21: the entry stays, tool/nvcc reports it."""
    r = compiler.filter_cache_artifacts(ctx(use = LIMITS_12_9), [entry('clang-cpp', '21.0.0')], [],
                                        {'lang': 'cpp', 'compute': 'cuda', 'version': '21', 'extra_match': NVCC_LINUX})
    assert chosen(r) == ['clang-cpp 21.0.0']


def test_extra_tags_and_extra_match_check_the_tool_of_a_cached_compiler(compiler):
    r = compiler.filter_cache_artifacts(ctx(), [entry('gcc-cpp', '13.3.0'), entry('clang-cpp', '18.1.3')], [],
                                        {'lang': 'cpp', 'compute': 'cuda', 'extra_tags': 'clang-cpp', 'extra_match': NVCC_LINUX})
    assert chosen(r) == ['clang-cpp 18.1.3']
    # a Windows request: the cached gcc-cpp (a Linux tool) fails the match, msvc stays
    r = compiler.filter_cache_artifacts(ctx('windows'), [entry('gcc-cpp', '13.3.0'), entry('msvc', '19.44.35207')], [],
                                        {'lang': 'cpp', 'compute': 'cuda', 'extra_match': NVCC_WINDOWS})
    assert chosen(r) == ['msvc 19.44.35207']


def test_the_compiler_set_up_in_this_run_wins(compiler):
    """The cuda target set up nvcc 13.3 in this run: the lang=cuda compiler entry of 12.9 is not offered."""
    c = ctx()
    c['tasks']['global']['nvcc'] = {'version': '13.3.73', 'tool': {'name': 'nvcc'}}
    entries = [entry('nvcc', '12.9.86', lang = 'cuda'), entry('nvcc', '13.3.73', lang = 'cuda')]
    r = compiler.filter_cache_artifacts(c, entries, [], {'lang': 'cuda', 'compute': 'cuda'})
    assert chosen(r) == ['nvcc 13.3.73']
    # nothing set up yet: both stay (the engine asks, or takes the newest in quiet mode)
    r = compiler.filter_cache_artifacts(ctx(), entries, [], {'lang': 'cuda', 'compute': 'cuda'})
    assert len(r['artifacts']) == 2
    # a version named in the request is matched by the cache query, not overruled here
    c['tasks']['global']['nvcc'] = {'version': '13.3.73'}
    r = compiler.filter_cache_artifacts(c, entries, [], {'lang': 'cuda', 'compute': 'cuda', 'version': '12.9'})
    assert len(r['artifacts']) == 2


def test_entries_of_one_compiler_are_one_choice(compiler, capsys):
    """Two entries of gcc-cpp 15.2.0, made for cuda and for cuda+vulkan, are the same compiler: no question."""
    a, b = entry('gcc-cpp', '15.2.0'), entry('gcc-cpp', '15.2.0')
    b['cmeta']['params']['compute'] = ['cuda', 'vulkan']
    b['path'] = '/cache/gcc-cpp-15.2.0-cuda-vulkan'
    r = compiler.filter_cache_artifacts(ctx(con = True), [b, a], [], {'lang': 'cpp', 'compute': 'cuda', 'extra_match': NVCC_LINUX})
    assert [x['path'] for x in r['artifacts']] == [a['path']]           # the one made for this compute
    assert capsys.readouterr().out == ''                               # same compiler: nothing to say
    r = compiler.filter_cache_artifacts(ctx(), [a, b], [], {'lang': 'cpp', 'compute': 'cuda,vulkan'})
    assert [x['path'] for x in r['artifacts']] == [b['path']]
    r = compiler.filter_cache_artifacts(ctx(), [b, a], [], {'lang': 'cpp', 'compute': 'vulkan'})
    assert [x['path'] for x in r['artifacts']] == [a['path']]           # neither fits exactly: the more specific one
    # the same for nvcc itself (lang cuda) and for a CPU compiler
    n1, n2 = entry('nvcc', '13.3.73', lang = 'cuda'), entry('nvcc', '13.3.73', lang = 'cuda')
    n2['cmeta']['params']['compute'] = ['cuda', 'vulkan']
    assert len(compiler.filter_cache_artifacts(ctx(), [n1, n2], [], {'lang': 'cuda', 'compute': 'cuda'})['artifacts']) == 1
    g1, g2 = entry('gcc', '15.2.0', 'cpu', 'c'), entry('gcc', '15.2.0', 'cpu', 'c')
    assert len(compiler.filter_cache_artifacts(ctx(), [g1, g2], [], {'lang': 'c', 'compute': 'cpu'})['artifacts']) == 1


def test_other_requests_keep_the_engines_choice(compiler):
    """No nvcc constraint: both suitable compilers stay (the engine asks, or takes the newest in quiet mode)."""
    r = compiler.filter_cache_artifacts(ctx(), [entry('gcc-cpp', '13.3.0', 'cpu'), entry('clang-cpp', '18.1.3', 'cpu')], [],
                                        {'lang': 'cpp', 'compute': 'cpu'})
    assert chosen(r) == ['gcc-cpp 13.3.0', 'clang-cpp 18.1.3']
    # a limit of the run still applies (--use.clang-cpp.version=<18 asks for another clang)
    r = compiler.filter_cache_artifacts(ctx(use = {'clang-cpp': {'version': '<18'}}),
                                        [entry('gcc-cpp', '13.3.0', 'cpu'), entry('clang-cpp', '18.1.3', 'cpu')], [],
                                        {'lang': 'cpp', 'compute': 'cpu'})
    assert chosen(r) == ['gcc-cpp 13.3.0']


def test_unfinished_entries_follow_the_limits_not_the_preference(compiler):
    r = compiler.filter_cache_artifacts(ctx(use = LIMITS_12_9),
                                        [entry('gcc-cpp', '13.3.0'), entry('gcc-cpp', '14.2.0')],
                                        [entry('clang-cpp', '21.0.0'), entry('gcc-cpp', '12.4.0'), entry('clang-cpp', '18.1.3')],
                                        {'lang': 'cpp', 'compute': 'cuda', 'extra_match': NVCC_LINUX})
    assert chosen(r) == ['gcc-cpp 14.2.0']
    assert chosen(r, 'tmp_artifacts') == ['gcc-cpp 12.4.0', 'clang-cpp 18.1.3']


def test_run_and_the_filter_share_the_tool_query(compiler):
    extra_match = {'constraints': {'supports_nvcc_os': ['linux']}}
    tags, match = compiler._tool_query({'lang': 'cpp', 'compute': 'cuda', 'extra_tags': 'gcc-cpp,lang-cpp',
                                        'extra_match': extra_match}, 'linux')
    assert tags == ['lang-cpp', 'gcc-cpp']
    assert match == {'constraints': {'supports_nvcc_os': ['linux'], 'supports_os': ['linux'], 'supports_compute': ['cuda']}}
    assert extra_match == {'constraints': {'supports_nvcc_os': ['linux']}}     # the request is not changed
    tags, match = compiler._tool_query({'lang': 'c'}, 'windows')
    assert tags == ['lang-c'] and match['constraints']['supports_compute'] == ['cpu']


def test_the_decided_compiler_narrows_the_range_set_for_its_tool(compiler, cm):
    """finish_dynamic_result sets the compiler up again by its exact version: a range in ctx use (nvcc's limit) follows it."""
    calls = []

    class FakeCM:
        repos = cm.repos
        utils = cm.utils

        def access(self, p):
            calls.append(p)
            return {'return': 0, 'version': p.get('version'), 'features': {'flags': {'dynamic_build': '/MD'}}}

        def catch_error(self, r, fail16 = False):
            return r['return'] > 0 and (r['return'] != 16 or fail16)

        def error(self, text, code = 1):
            return {'return': code, 'error': text}

    t = object.__new__(type(compiler))
    t.cm, t.cmeta, t.category_alias, t.category_uid = FakeCM(), compiler.cmeta, 'task', 'c36be4b9314a45e0'

    c = ctx(use = {'msvc': {'version': '>=19.20,<19.60'}, 'gcc-cpp': {'version': '<16'}})
    result = {'tool': {'name': 'msvc'}, 'version': '19.50.35726', 'features': {'flags': {}}}
    r = t.finish_dynamic_result(c, dict(result), {'with': {}})
    assert r['return'] == 0 and calls[-1]['version'] == '19.50.35726'
    assert c['tasks']['use']['msvc']['version'] == '19.50.35726'       # narrowed to the decided compiler
    assert c['tasks']['use']['gcc-cpp']['version'] == '<16'            # another tool: untouched

    # a range the decided version does not satisfy is left as it is (its owner reports the conflict)
    c = ctx(use = {'msvc': {'version': '>=19.10,<19.50'}})
    t.finish_dynamic_result(c, dict(result), {'with': {}})
    assert c['tasks']['use']['msvc']['version'] == '>=19.10,<19.50'

    # no range: nothing to narrow
    c = ctx()
    t.finish_dynamic_result(c, dict(result), {'with': {}})
    assert c['tasks']['use'] == {}


def test_msvc_passes_its_version_to_the_visual_studio_it_uses():
    """As gcc-cpp and clang-cpp do: a request for one MSVC version picks the installation that has it, no question."""
    import yaml
    for tool, dep in (('msvc', 'microsoft.visual-studio'), ('gcc-cpp', 'gcc'), ('clang-cpp', 'clang')):
        desc = yaml.safe_load((REPO_ROOT / 'tool' / tool / '_desc.yaml').read_text(encoding = 'utf-8'))
        uses = [u for u in desc['uses'] if str(u.get('name', '')).startswith(dep)]
        assert uses and uses[0].get('version') == '{{params.version|$None}}', tool


def test_the_hook_is_wired():
    src = (REPO_ROOT / 'task' / 'compiler' / 'api_v1.py').read_text(encoding = 'utf-8')
    engine = (REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py').read_text(encoding = 'utf-8')
    assert 'def filter_cache_artifacts(' in src and 'task_api_code.filter_cache_artifacts(' in engine
