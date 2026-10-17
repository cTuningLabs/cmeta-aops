"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/compiler's choice among cached compilers (filter_cache_artifacts, called by the task engine before it
offers the matching cache entries or takes the first in quiet mode): a cached compiler whose version is
outside the limit the run sets for its tool (tool/nvcc's host-compiler limits, --use.<tool>.version) or whose
tool lacks the request's extra_tags or fails its extra_match is dropped; of the rest, the preferred compiler
of the OS (task/compiler/_desc.yaml: msvc on Windows, gcc on Linux, clang on macOS) wins, then the tool the
repository ranks first, then the newest version, with no prompt - for the host compiler of nvcc and for any
other request alike; run() chooses among the compiler tools of a machine without cached compilers the same
way. The tool metas come from this repository, plugged into the isolated CMETA_HOME.
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


def test_the_compiler_set_up_in_this_run_wins(compiler, capsys):
    """The cuda target set up nvcc 13.3 in this run: the lang=cuda compiler entry of 12.9 is not offered."""
    capsys_out = lambda: capsys.readouterr().out
    c = ctx()
    c['tasks']['global']['nvcc'] = {'version': '13.3.73', 'tool': {'name': 'nvcc'}}
    entries = [entry('nvcc', '12.9.86', lang = 'cuda'), entry('nvcc', '13.3.73', lang = 'cuda')]
    r = compiler.filter_cache_artifacts(c, entries, [], {'lang': 'cuda', 'compute': 'cuda'})
    assert chosen(r) == ['nvcc 13.3.73']

    # nothing set up yet: the newest toolkit, said in an INFO line
    r = compiler.filter_cache_artifacts(ctx(con = True), entries, [], {'lang': 'cuda', 'compute': 'cuda'})
    assert chosen(r) == ['nvcc 13.3.73']
    out = capsys_out()
    assert 'cached versions of nvcc: taking 13.3.73' in out and '--use.compiler-cuda.version' in out

    # a version named in the request is matched by the cache query (the limits are not applied here);
    # of several entries within it the newest is taken
    c['tasks']['global']['nvcc'] = {'version': '13.3.73'}
    r = compiler.filter_cache_artifacts(c, entries, [], {'lang': 'cuda', 'compute': 'cuda', 'version': '12.9'})
    assert chosen(r) == ['nvcc 13.3.73']


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


def test_a_cpu_request_takes_the_compiler_of_the_os(compiler, capsys):
    """No nvcc constraint, two different compilers cached: the preferred one of the OS, not the newest."""
    cpu = [entry('gcc-cpp', '13.3.0', 'cpu'), entry('clang-cpp', '18.1.3', 'cpu')]
    r = compiler.filter_cache_artifacts(ctx(con = True), cpu, [], {'lang': 'cpp', 'compute': 'cpu'})
    assert chosen(r) == ['gcc-cpp 13.3.0']
    out = capsys.readouterr().out
    assert 'suit this run: taking gcc-cpp 13.3.0' in out and 'clang-cpp 18.1.3' in out and '--use.compiler-cpp.name' in out

    # Windows: MSVC before a newer clang; macOS: clang before gcc although the repository ranks gcc first
    r = compiler.filter_cache_artifacts(ctx('windows'), [entry('clang', '22.1.7', 'cpu', 'c'), entry('msvc', '19.50.35726', 'cpu', 'c')], [],
                                        {'lang': 'c', 'compute': 'cpu'})
    assert chosen(r) == ['msvc 19.50.35726']
    r = compiler.filter_cache_artifacts(ctx('darwin'), [entry('gcc-cpp', '15.2.0', 'cpu'), entry('clang-cpp', '21.0.0', 'cpu')], [],
                                        {'lang': 'cpp', 'compute': 'cpu'})
    assert chosen(r) == ['clang-cpp 21.0.0']

    # a limit of the run still applies (--use.clang-cpp.version=<18 asks for another clang)
    r = compiler.filter_cache_artifacts(ctx(use = {'clang-cpp': {'version': '<18'}}), cpu, [], {'lang': 'cpp', 'compute': 'cpu'})
    assert chosen(r) == ['gcc-cpp 13.3.0']


def test_several_versions_of_one_compiler_take_the_newest(compiler, capsys):
    r = compiler.filter_cache_artifacts(ctx(con = True), [entry('gcc-cpp', '13.3.0', 'cpu'), entry('gcc-cpp', '14.2.0', 'cpu')], [],
                                        {'lang': 'cpp', 'compute': 'cpu', 'name': 'gcc-cpp'})
    assert chosen(r) == ['gcc-cpp 14.2.0']
    out = capsys.readouterr().out
    assert 'cached versions of gcc-cpp: taking 14.2.0' in out and 'gcc-cpp 13.3.0' in out and '--use.compiler-cpp.version' in out


def test_preferred_compilers_agree_with_the_tools_rank():
    """The per-OS order of _desc.yaml and the sort keys of the tools (the order of a fresh selection) agree."""
    import yaml
    desc = yaml.safe_load((REPO_ROOT / 'task' / 'compiler' / '_desc.yaml').read_text(encoding = 'utf-8'))
    table = desc['preferred_compilers']
    assert set(table) == {'windows', 'linux', 'darwin'}
    for uname, families in table.items():
        sorts = []
        for family in families:
            meta = yaml.safe_load((REPO_ROOT / 'tool' / family / '_cmeta.yaml').read_text(encoding = 'utf-8'))
            if uname in meta.get('constraints', {}).get('supports_os', []):
                sorts.append(meta['sort'])
        assert sorts == sorted(sorts), (uname, families, sorts)

    # the system compiler of each OS comes first
    assert table['windows'][0] == 'msvc' and table['linux'][0] == 'gcc' and table['darwin'][0] == 'clang'


def test_run_takes_the_preferred_tool_without_a_question(compiler, cm, capsys):
    """Two compiler tools suit a request on a machine without cached compilers: run() takes the OS one."""
    calls = []

    def tool(alias, sort):
        return {'cmeta_ref_parts': {'artifact_alias': alias}, 'cmeta': {'sort': sort}, 'path': '/tool/' + alias}

    class FakeCM:
        repos = cm.repos
        utils = cm.utils
        found = []

        def access(self, p):
            calls.append(p)
            if p.get('command') == 'find':
                return {'return': 0, 'artifacts': list(self.found)} if self.found else {'return': 16, 'error': 'not found'}
            return {'return': 0, 'version': '1.0', 'constraints': {'supports_compute': ['cpu']}}

        def catch_error(self, r, fail16 = False):
            return r['return'] > 0 and (r['return'] != 16 or fail16)

        def error(self, text, code = 1):
            return {'return': code, 'error': text}

    t = object.__new__(type(compiler))
    t.cm, t.cmeta, t.category_alias, t.category_uid = FakeCM(), compiler.cmeta, 'task', 'c36be4b9314a45e0'

    def run(uname, found):
        FakeCM.found = found
        c = ctx(uname, con = True)
        c['tasks']['nested_call'] = 0
        return t.run(c, lang = 'cpp', compute = 'cpu')

    r = run('linux', [tool('clang-cpp', 3000), tool('gcc-cpp', 2000)])
    assert r['return'] == 0 and r['tool']['name'] == 'gcc-cpp' and calls[-1]['name'] == 'gcc-cpp'
    out = capsys.readouterr().out
    assert 'compiler tools suit this run: taking gcc-cpp' in out and 'clang-cpp' in out and '--use.compiler-cpp.name' in out

    r = run('darwin', [tool('gcc-cpp', 2000), tool('clang-cpp', 3000)])
    assert r['tool']['name'] == 'clang-cpp' and 'taking clang-cpp' in capsys.readouterr().out

    r = run('linux', [tool('gcc-cpp', 2000)])
    assert r['tool']['name'] == 'gcc-cpp' and 'suit this run' not in capsys.readouterr().out   # one tool: nothing to say

    r = run('linux', [])
    assert r['return'] == 99 and 'constraints' in r['error']


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


###################################################################################################
# One build, one compiler (2026-10-17): a compiler asked for by name is not the default of later runs, and a request
# that names none follows the family of the other language's compiler of the same run

def auto(e):
    e['cmeta']['params']['selected'] = 'auto'
    return e


def with_partner(c, lang, name):
    """A run whose compiler of `lang` (c or cpp) is set up already."""
    c['tasks']['global']['compiler-' + lang] = {'tool': {'name': name}, 'version': '1.0'}
    return c


def test_a_request_without_a_name_is_cached_as_auto(compiler):
    from cmeta.utils.common import check_params
    import types
    compiler.cm, saved = types.SimpleNamespace(check_params = lambda p, a, n: check_params(p, a, 'cmeta.utils.common'),
                                               catch_error = lambda r: r['return'] > 0), compiler.cm
    try:
        p = {'lang': 'c'}
        assert compiler.init({}, p)['return'] == 0 and p['selected'] == 'auto'
        p = {'lang': 'c', 'name': 'clang', 'selected': 'auto'}
        assert compiler.init({}, p)['return'] == 0 and 'selected' not in p
    finally:
        compiler.cm = saved


def test_a_default_request_never_takes_an_entry_made_by_name(cm):
    """The cache query of a request without a name carries selected=auto; an entry made by name (or before
    2026-10-17) has none and does not match: --use.compiler-c.name=clang once does not make clang the default."""
    import yaml
    desc = yaml.safe_load((REPO_ROOT / 'task' / 'compiler' / '_desc.yaml').read_text(encoding = 'utf-8'))
    assert 'selected' in desc['cache_params']
    match = lambda data, query: cm.utils.common.matches_query(data, query, match_version_func = cm.repos.match_version_func,
                                                             match_empty_version = True)
    by_name = {'lang': 'c', 'name': 'clang', 'version': '23.1.3'}
    chosen = {'lang': 'c', 'name': 'msvc', 'version': '19.51', 'selected': 'auto'}
    assert not match(by_name, {'lang': 'c', 'selected': 'auto'})
    assert match(chosen, {'lang': 'c', 'selected': 'auto'})
    assert match(by_name, {'lang': 'c', 'name': 'clang'}) and match(chosen, {'lang': 'c', 'name': 'msvc'})   # named: either


def test_the_cpp_compiler_follows_the_family_of_the_runs_c_compiler(compiler, capsys):
    """Windows prefers MSVC, but the C compiler of this run is clang: the C++ entry of clang is taken."""
    entries = [auto(entry('msvc', '19.51.36231', 'cpu')), auto(entry('clang-cpp', '23.1.3', 'cpu'))]
    c = with_partner(ctx('windows', con = True), 'c', 'clang')
    r = compiler.filter_cache_artifacts(c, entries, [], {'lang': 'cpp', 'compute': 'cpu', 'selected': 'auto'})
    assert chosen(r) == ['clang-cpp 23.1.3']
    assert 'the C compiler of this run is clang: taking the C++ compiler of its family' in capsys.readouterr().out

    # the reverse: a C request after a C++ compiler (icpx: the family icx)
    entries = [auto(entry('msvc', '19.51.36231', 'cpu', 'c')), auto(entry('icx', '2025.3.0', 'cpu', 'c'))]
    r = compiler.filter_cache_artifacts(with_partner(ctx('windows'), 'cpp', 'icpx'), entries, [], {'lang': 'c', 'compute': 'cpu'})
    assert chosen(r) == ['icx 2025.3.0']

    # none of that family cached: none kept, so that run() chooses among the tools, the family first
    r = compiler.filter_cache_artifacts(with_partner(ctx('windows'), 'c', 'clang'), [auto(entry('msvc', '19.51.36231', 'cpu'))], [],
                                        {'lang': 'cpp', 'compute': 'cpu'})
    assert r['artifacts'] == []

    # a request that names its compiler is taken as it is
    r = compiler.filter_cache_artifacts(with_partner(ctx('windows'), 'c', 'clang'), [entry('msvc', '19.51.36231', 'cpu')], [],
                                        {'lang': 'cpp', 'compute': 'cpu', 'name': 'msvc'})
    assert chosen(r) == ['msvc 19.51.36231']

    # no partner yet: the preference of the OS, as before
    r = compiler.filter_cache_artifacts(ctx('windows'), [auto(entry('clang-cpp', '23.1.3', 'cpu')), auto(entry('msvc', '19.51.36231', 'cpu'))], [],
                                        {'lang': 'cpp', 'compute': 'cpu'})
    assert chosen(r) == ['msvc 19.51.36231']


def test_run_takes_the_family_of_the_runs_other_compiler(compiler, cm, capsys):
    """Without cached compilers: the tool of the partner's family first, else the preferred one with an INFO line."""
    class FakeCM:
        repos = cm.repos
        utils = cm.utils
        found = []

        def access(self, p):
            if p.get('command') == 'find':
                return {'return': 0, 'artifacts': list(self.found)}
            return {'return': 0, 'version': '1.0', 'constraints': {'supports_compute': ['cpu']}}

        def catch_error(self, r, fail16 = False):
            return r['return'] > 0 and (r['return'] != 16 or fail16)

    def tool(alias, sort):
        return {'cmeta_ref_parts': {'artifact_alias': alias}, 'cmeta': {'sort': sort}, 'path': '/tool/' + alias}

    t = object.__new__(type(compiler))
    t.cm, t.cmeta, t.category_alias, t.category_uid = FakeCM(), compiler.cmeta, 'task', 'c36be4b9314a45e0'

    def run(uname, found, partner):
        FakeCM.found = found
        c = with_partner(ctx(uname, con = True), 'c', partner)
        c['tasks']['nested_call'] = 0
        return t.run(c, lang = 'cpp', compute = 'cpu')

    r = run('windows', [tool('msvc', 1000), tool('clang-cpp', 3000)], 'clang')
    assert r['tool']['name'] == 'clang-cpp'
    assert 'the C compiler of this run is clang: taking clang-cpp, the C++ compiler of its family' in capsys.readouterr().out

    r = run('linux', [tool('gcc-cpp', 2000), tool('clang-cpp', 3000)], 'gcc')
    assert r['tool']['name'] == 'gcc-cpp'

    # nvcc's host compiler on Windows is MSVC alone: no clang-cpp suits the request - the preferred one, said
    r = run('windows', [tool('msvc', 1000)], 'clang')
    assert r['tool']['name'] == 'msvc'
    assert 'the C compiler of this run is clang, but no C++ compiler of its family suits this request' in capsys.readouterr().out


def test_every_c_and_cpp_compiler_tool_has_its_family():
    """compiler_families in task/compiler/_desc.yaml lists every tool tagged lang-c or lang-cpp, each in one family."""
    import yaml
    desc = yaml.safe_load((REPO_ROOT / 'task' / 'compiler' / '_desc.yaml').read_text(encoding = 'utf-8'))
    listed = [str(t) for tools in desc['compiler_families'].values() for t in tools.values()]
    tools = set()
    for meta in (REPO_ROOT / 'tool').glob('*/_cmeta.yaml'):
        tags = (yaml.safe_load(meta.read_text(encoding = 'utf-8')) or {}).get('tags') or []
        if 'lang-c' in tags or 'lang-cpp' in tags:
            tools.add(meta.parent.name)
    assert tools and tools <= set(listed), sorted(tools - set(listed))
    assert all(f in desc['compiler_families'] for f in ('gcc', 'clang', 'msvc'))
    assert set(desc['preferred_compilers']['windows']) <= set(desc['compiler_families'])


def test_a_compiler_asked_for_by_name_leads_even_before_it_is_set_up(compiler, capsys):
    """build-llama-cpp sets up its C++ compiler first: with --use.compiler-c.name=clang the C++ request (no name)
    follows the C compiler asked for, not the preference of the OS (Windows: C by clang, C++ by MSVC - CMake failed,
    the round of 2026-10-17)."""
    entries = [auto(entry('msvc', '19.51.36231', 'cpu')), auto(entry('clang-cpp', '23.1.3', 'cpu'))]
    c = ctx('windows', con = True, use = {'compiler-c': {'name': 'clang'}})
    r = compiler.filter_cache_artifacts(c, entries, [], {'lang': 'cpp', 'compute': 'cpu'})
    assert chosen(r) == ['clang-cpp 23.1.3']
    assert 'the C compiler asked for is clang: taking the C++ compiler of its family' in capsys.readouterr().out

    # a compiler set up in the run leads over one only asked for (the run's facts first)
    c = with_partner(ctx('windows', use = {'compiler-c': {'name': 'clang'}}), 'c', 'msvc')
    r = compiler.filter_cache_artifacts(c, entries, [], {'lang': 'cpp', 'compute': 'cpu'})
    assert chosen(r) == ['msvc 19.51.36231']
