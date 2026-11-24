"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the optional parts of a build (2026-11-24): common_build.resolve_components with the parts and the
variations program/build-pytorch declares - which parts are on for a system and its targets and why, the build
variables that follow, the submodules fetched without their own; what a request cannot ask.
"""

import importlib.util
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = 'module')
def build():
    spec = importlib.util.spec_from_file_location('common_build_under_test', str(REPO_ROOT / 'category' / 'program' / 'api' / 'common_build.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope = 'module')
def pytorch():
    with open(REPO_ROOT / 'program' / 'build-pytorch' / '_desc.yaml', encoding = 'utf-8') as f:
        return yaml.safe_load(f)


def resolve(build, pytorch, system, targets, variation = None, asked = None, given = None):
    return build.resolve_components(pytorch['components'], pytorch['variations'], variation, asked,
                                    {'os': system, 'targets': targets}, given)


def states(r):
    return {k: v['state'] for k, v in r['parts'].items()}


# ---------------------------------------------------------------- PyTorch's parts
def test_lean_on_windows_for_the_cpu_fetches_no_part_that_is_off(build, pytorch):
    r = resolve(build, pytorch, 'windows', ['cpu'], 'lean')
    assert r['return'] == 0, r
    s = states(r)
    assert s['distributed'] == 'off' and s['tensorpipe'] == 'off' and s['kineto'] == 'off' and s['rocm-kernels'] == 'off'
    assert s['mkldnn'] == 'off' and s['mslk'] == 'off' and s['fbgemm'] == 'auto' and s['tests'] == 'off'
    assert r['parts']['tensorpipe']['why'].startswith('not for windows') and r['parts']['rocm-kernels']['applies'] is False
    # every submodule with deep submodules of its own is fetched without them
    assert set(r['not_recursive']) == {'third_party/tensorpipe', 'third_party/kineto', 'third_party/flash-attention',
                                       'third_party/aiter', 'third_party/mslk', 'third_party/ideep'}
    # the build variables are the ones this program always set on Windows; a part that cannot be built sets none
    assert r['flags'] == {'USE_DISTRIBUTED': 'OFF', 'USE_KINETO': 'OFF', 'USE_MKLDNN': 'OFF', 'USE_XNNPACK': 'OFF', 'BUILD_TEST': '0'}
    assert r['lines'][0] == 'The parts of this build (variation lean; windows, cpu):'
    assert any('tensorpipe' in l and 'without its own submodules' in l for l in r['lines'])


def test_lean_on_linux_for_cuda_keeps_what_the_build_chooses_itself(build, pytorch):
    r = resolve(build, pytorch, 'linux', ['cpu', 'cuda'], 'lean')
    s = states(r)
    assert s['kineto'] == 'auto' and s['mslk'] == 'auto' and s['mkldnn'] == 'auto' and s['flash-attention'] == 'auto'
    assert s['tensorpipe'] == 'off' and r['parts']['tensorpipe']['why'] == 'needs distributed, which is off'
    assert s['rocm-kernels'] == 'off'
    assert set(r['not_recursive']) == {'third_party/tensorpipe', 'third_party/flash-attention', 'third_party/aiter'}
    assert r['flags'] == {'USE_DISTRIBUTED': 'OFF', 'USE_TENSORPIPE': 'OFF', 'BUILD_TEST': '0'}      # nothing for an "auto" part


def test_rocm_gets_its_kernels_and_their_submodules(build, pytorch):
    r = resolve(build, pytorch, 'linux', ['rocm'], 'lean')
    assert states(r)['rocm-kernels'] == 'on'
    assert 'third_party/flash-attention' not in r['not_recursive'] and 'third_party/aiter' not in r['not_recursive']
    assert r['flags']['USE_ROCM_CK_SDPA'] == 'ON' and r['flags']['USE_ROCM_CK_GEMM'] == 'ON'


def test_minimal_turns_the_optional_kernels_off_for_any_target(build, pytorch):
    r = resolve(build, pytorch, 'linux', ['cuda'], 'minimal')
    s = states(r)
    assert all(s[k] == 'off' for k in ('distributed', 'kineto', 'mkldnn', 'fbgemm', 'xnnpack', 'nnpack', 'qnnpack', 'mslk', 'flash-attention', 'tests'))
    assert r['flags']['USE_FLASH_ATTENTION'] == 'OFF' and r['flags']['USE_FBGEMM'] == 'OFF' and r['flags']['USE_KINETO'] == 'OFF'
    assert 'third_party/kineto' in r['not_recursive'] and 'third_party/mslk' in r['not_recursive'] and 'third_party/ideep' in r['not_recursive']
    cpu = resolve(build, pytorch, 'windows', ['cpu'], 'minimal')
    assert 'USE_FLASH_ATTENTION' not in cpu['flags']                         # a GPU part sets nothing in a CPU build
    assert cpu['parts']['flash-attention']['why'] == 'only for the targets cuda, rocm'


def test_a_part_can_be_asked_on_or_off_over_the_variation(build, pytorch):
    r = resolve(build, pytorch, 'linux', ['cpu'], 'minimal', asked = {'kineto': True, 'distributed': 'on'})
    s = states(r)
    assert s['kineto'] == 'on' and r['parts']['kineto']['why'] == 'asked' and r['flags']['USE_KINETO'] == 'ON'
    assert s['distributed'] == 'on' and s['tensorpipe'] == 'on'               # its default, now that distributed is on
    assert 'third_party/kineto' not in r['not_recursive'] and 'third_party/tensorpipe' not in r['not_recursive']
    r = resolve(build, pytorch, 'linux', ['cpu'], None, asked = {'fbgemm': False})
    assert states(r)['fbgemm'] == 'off' and r['flags']['USE_FBGEMM'] == 'OFF' and r['variation'] == ''


def test_a_build_variable_of_the_request_is_its_word_for_the_part(build, pytorch):
    r = resolve(build, pytorch, 'windows', ['cpu'], 'lean', given = {'USE_KINETO': 'ON'})
    assert states(r)['kineto'] == 'on' and r['parts']['kineto']['why'] == 'by --compile.d.USE_KINETO=ON'
    assert 'USE_KINETO' not in r['flags'] and 'third_party/kineto' not in r['not_recursive']       # the request's value stays its own
    r = resolve(build, pytorch, 'linux', ['cpu'], 'lean', given = {'BUILD_TEST': '1'})
    assert states(r)['tests'] == 'on'


@pytest.mark.parametrize('kwargs, words', [
    ({'variation': 'smallest'}, 'no such variation'),
    ({'asked': {'kinetto': True}}, 'no such part'),
    ({'asked': {'tensorpipe': True}}, 'cannot be built here'),                           # on Windows
    ({'asked': {'rocm-kernels': True}}, 'cannot be built here'),                         # for the cpu
    ({'asked': {'kineto': 'maybe'}}, 'on or off'),
    ({'asked': {'kineto': False}, 'given': {'USE_KINETO': 'ON'}}, 'one of them'),
])
def test_what_cannot_be_honoured_is_an_error(build, pytorch, kwargs, words):
    r = resolve(build, pytorch, 'windows', ['cpu'], **kwargs)
    assert r['return'] == 1 and words in r['error'], r


def test_a_part_asked_on_without_the_part_it_needs_is_an_error(build, pytorch):
    r = resolve(build, pytorch, 'linux', ['cpu'], 'lean', asked = {'tensorpipe': True})
    assert r['return'] == 1 and 'needs distributed' in r['error'] and '--compile.components.distributed' in r['error']


# ---------------------------------------------------------------- the rule itself
def test_the_rule_with_parts_of_its_own(build):
    parts = {'a': {'flags': {'USE_A': ['ON', 'OFF']}, 'submodules': ['x', 'shared'], 'default': 'off'},
             'b': {'flags': {'USE_B': ['1', '0']}, 'submodules': ['shared'], 'default': {'linux': 'on', '*': 'off'}},
             'c': {'default': True, 'requires': ['a']},                       # an unquoted YAML on / off is a bool
             'd': {}}                                                         # no default: the build's own choice
    r = build.resolve_components(parts, {}, None, None, {'os': 'linux', 'targets': ['cpu']}, None)
    assert states(r) == {'a': 'off', 'b': 'on', 'c': 'off', 'd': 'auto'}
    assert r['not_recursive'] == ['x']                                        # "shared" is read by b, which is on
    assert r['flags'] == {'USE_A': 'OFF', 'USE_B': '1'}
    assert r['parts']['b']['why'] == 'default on linux' and r['parts']['d']['why'] == "the build's own choice"
    r = build.resolve_components(parts, {}, None, None, {'os': 'darwin', 'targets': []}, None)
    assert states(r)['b'] == 'off' and set(r['not_recursive']) == {'x', 'shared'}
    assert build.resolve_components({}, {}, None, None, None, None)['parts'] == {}


def test_a_submodule_this_version_of_the_source_does_not_have_is_nothing_to_leave_out(build, pytorch, tmp_path):
    # the source says which submodules it has: its .gitmodules, as Git writes it
    (tmp_path / '.gitmodules').write_text('[submodule "third_party/tensorpipe"]' + chr(10) + chr(9) + 'ignore = dirty' + chr(10) +
                                          chr(9) + 'path = third_party/tensorpipe' + chr(10) + chr(9) + 'url = https://example.org/t.git' + chr(10) +
                                          '[submodule "third_party/ideep"]' + chr(10) + chr(9) + 'path = third_party/ideep' + chr(10), encoding = 'utf-8')
    have = build.source_submodules(str(tmp_path))
    assert have == ['third_party/tensorpipe', 'third_party/ideep']
    assert build.source_submodules(str(tmp_path / 'nothing-here')) == []

    r = build.resolve_components(pytorch['components'], pytorch['variations'], 'lean', None,
                                 {'os': 'windows', 'targets': ['cpu'], 'submodules': have}, None)
    assert set(r['not_recursive']) == {'third_party/tensorpipe', 'third_party/ideep'}
    assert 'third_party/kineto' in r['not_in_source'] and 'third_party/mslk' in r['not_in_source']
    assert states(r)['kineto'] == 'off' and r['flags']['USE_KINETO'] == 'OFF'          # the part itself is still off
    assert any('kineto' in l and 'third_party/kineto: no submodule of this source' in l for l in r['lines'])
    # without the fact, nothing is known of the source: every declared one is named
    assert resolve(build, pytorch, 'windows', ['cpu'], 'lean')['not_in_source'] == []


# ---------------------------------------------------------------- a build's own limits on its host compiler
LIMITS = [{'exclude': '>=19.51,<19.52', 'reason': 'crashes on a probe', 'since': '2026-11-24'}]


def in_range(spec, version):
    """A stand-in for cMeta's version match: comma-joined >=, <, == parts."""
    key = lambda v: tuple(int(p) for p in v.split('.'))
    ok = True
    for part in spec.split(','):
        for op in ('>=', '==', '<'):
            if part.startswith(op):
                a, b = key(version), key(part[len(op):])
                ok = ok and {'>=': a[:len(b)] >= b, '<': a[:len(b)] < b, '==': a == b}[op]
                break
    return ok


@pytest.mark.parametrize('installed, choice, none_left, excluded', [
    ([('19.51.36260', 'vs18'), ('19.44.35211', 'vs2022'), ('19.29.30159', 'vs2019')], ('19.44.35211', 'vs2022'), False, ['19.51.36260']),
    ([('19.29.30159', 'vs2019'), ('19.51.36260', 'vs18')], ('19.29.30159', 'vs2019'), False, ['19.51.36260']),     # any order given
    ([('19.52.1', 'vs18'), ('19.51.36260', 'old'), ('19.44.35211', 'vs2022')], None, False, ['19.51.36260']),     # the newest is fine
    ([('19.44.35211', 'vs2022')], None, False, []),
    ([('19.51.36260', 'vs18')], None, True, ['19.51.36260']),                                                    # no other one
    ([], None, False, []),                                                                                       # none listed
])
def test_the_newest_compiler_no_limit_excludes(build, installed, choice, none_left, excluded):
    r = build.compiler_outside_limits(installed, LIMITS, in_range)
    assert r['choice'] == choice and r['none_left'] is none_left and [x[0] for x in r['excluded']] == excluded
    assert all(x[2] == 'crashes on a probe' for x in r['excluded'])
    assert build.compiler_outside_limits(installed, [], in_range)['choice'] is None      # no limits: nothing changes


def test_the_msvc_compilers_of_a_machine_are_listed_from_its_installations(build, tmp_path):
    base = tmp_path / 'pf86'
    (base / 'Microsoft Visual Studio' / 'Installer').mkdir(parents = True)
    (base / 'Microsoft Visual Studio' / 'Installer' / 'vswhere.exe').write_text('')
    banners = {}

    def installation(name, toolset, version, cpp = True):
        folder = tmp_path / name
        if cpp:
            (folder / 'VC' / 'Auxiliary' / 'Build').mkdir(parents = True)
            (folder / 'VC' / 'Auxiliary' / 'Build' / 'Microsoft.VCToolsVersion.default.txt').write_text(toolset + chr(10))
            cl = folder / 'VC' / 'Tools' / 'MSVC' / toolset / 'bin' / 'Hostx64' / 'x64'
            cl.mkdir(parents = True)
            (cl / 'cl.exe').write_text('')
            banners[str(cl / 'cl.exe')] = f'Microsoft (R) C/C++ Optimizing Compiler Version {version} for x64'
        else:
            folder.mkdir()
        return str(folder)

    folders = [installation('vs2022-community', '14.44.35207', '19.44.35211'), installation('vs18-buildtools', '14.51.36231', '19.51.36260'),
               installation('vs18-community', '', '', cpp = False), installation('vs2022-buildtools', '14.44.35207', '19.44.35211')]

    class Said:
        def __init__(self, out = '', err = ''):
            self.stdout, self.stderr = out.encode(), err.encode()

    def run(cmd, **kwargs):
        if cmd[0].endswith('vswhere.exe'):
            assert cmd[1:] == ['-all', '-products', '*', '-property', 'installationPath', '-utf8']
            return Said(chr(10).join(folders))
        return Said(err = banners[cmd[0]])                               # cl.exe prints its banner on stderr

    found = build.msvc_installed(run = run, environ = {'ProgramFiles(x86)': str(base)})
    assert found == [('19.51.36260', folders[1]), ('19.44.35211', folders[0])]       # the newest first; one entry a version
    assert build.msvc_installed(run = run, environ = {}) == []                        # no Visual Studio Installer: nothing asked
    assert build.msvc_installed(run = run, environ = {'ProgramFiles(x86)': str(tmp_path / 'nowhere')}) == []


def test_build_pytorch_declares_its_limit_and_applies_it_first():
    desc = yaml.safe_load((REPO_ROOT / 'program' / 'build-pytorch' / '_desc.yaml').read_text(encoding = 'utf-8'))
    limit = desc['compiler_limits']['windows']['msvc'][0]
    assert limit['exclude'] == '>=19.51,<19.52' and limit['reason'] and limit['since'] == '2026-11-24'
    assert in_range(limit['exclude'], '19.51.36260') and not in_range(limit['exclude'], '19.44.35211') and not in_range(limit['exclude'], '19.52.0')
    src = (REPO_ROOT / 'program' / 'build-pytorch' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert 'def customize(self,' in src and "use.setdefault('msvc', {})['version'] = version" in src
    # the template calls the program's customize before it sets the compiler up
    template = (REPO_ROOT / 'program' / 'template-c-cpu' / '_desc.yaml').read_text(encoding = 'utf-8')
    assert template.index('internal_func: customize' + chr(10)) < template.index('task: compiler,')


def test_the_licence_files_a_python_project_lists(build, tmp_path):
    assert build.declared_license_files(str(tmp_path)) == []                               # no pyproject.toml
    (tmp_path / 'pyproject.toml').write_text('[project]' + chr(10) + 'name = "x"' + chr(10), encoding = 'utf-8')
    try:
        import tomllib                                                                     # noqa: F401 (Python 3.11 and newer)
    except ImportError:
        # a Python that cannot read TOML says so for any pyproject.toml: the caller then leaves nothing out
        assert build.declared_license_files(str(tmp_path)) is None
        return
    assert build.declared_license_files(str(tmp_path)) == []                               # none listed
    (tmp_path / 'pyproject.toml').write_text('[project]' + chr(10) + 'name = "x"' + chr(10) + 'license-files = [' + chr(10) +
                                             '    "LICENSE",  # its own' + chr(10) + '    "third_party/a/b/LICENSE*",' + chr(10) + ']' + chr(10),
                                             encoding = 'utf-8')
    assert build.declared_license_files(str(tmp_path)) == ['LICENSE', 'third_party/a/b/LICENSE*']
    (tmp_path / 'pyproject.toml').write_text('[project' + chr(10), encoding = 'utf-8')
    assert build.declared_license_files(str(tmp_path)) is None                             # unreadable: nothing is left out


def test_build_pytorch_asks_the_parts_only_when_the_request_names_one():
    src = (REPO_ROOT / 'program' / 'build-pytorch' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "if variation in (None, '', False) and not asked:\n            return {'return': 0}" in src
    assert "d = dict(d, **(_local.get('pytorch_component_flags') or {}))" in src
    desc = (REPO_ROOT / 'program' / 'build-pytorch' / '_desc.yaml').read_text(encoding = 'utf-8')
    assert "repo: '{{global.clone-git-to-cache-src-pytorch.path_to_git_repo}}'" in desc
    assert "submodules_not_recursive: '{{local.pytorch_submodules_not_recursive|$[]}}'" in desc
    assert "submodules_files: '{{local.pytorch_submodules_files|$[]}}'" in desc
    assert "listed = common_build.declared_license_files(git_repo)" in src
    assert 'submodule update --init --recursive' not in desc              # the bare command is gone: clone-git fetches them


def test_the_pytorch_tool_hands_a_variation_and_parts_to_the_build_and_keeps_them_in_its_identity():
    with open(REPO_ROOT / 'tool' / 'pytorch' / '_desc.yaml', encoding = 'utf-8') as f:
        tool = yaml.safe_load(f)
    build = [u for u in tool['build_uses']['all'] if str(u.get('name', '')).startswith('build-pytorch,')]
    assert len(build) == 1
    for key in ('variation', 'components'):
        # an empty value is None, which neither the build's identity nor the cache entry's keeps: a request without
        # them is the request of before
        assert build[0]['compile'][key] == '{{params.with.' + key + '|$None}}'
        assert tool['cache_meta_const']['params']['with'][key] == '{{params.with.' + key + '|$None}}'
