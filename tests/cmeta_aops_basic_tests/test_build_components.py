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
    assert s['distributed'] == 'off' and s['tensorpipe'] == 'off' and s['rocm-kernels'] == 'off'
    assert s['kineto'] == 'auto'                     # PyTorch's own default (on) on Windows too since 2026-11-26
    assert s['mkldnn'] == 'off' and s['mslk'] == 'off' and s['fbgemm'] == 'auto' and s['tests'] == 'off'
    assert r['parts']['tensorpipe']['why'].startswith('not for windows') and r['parts']['rocm-kernels']['applies'] is False
    # every submodule with deep submodules of its own is fetched without them
    assert set(r['not_recursive']) == {'third_party/tensorpipe', 'third_party/flash-attention',
                                       'third_party/aiter', 'third_party/mslk', 'third_party/ideep'}
    # the build variables are the ones this program always set on Windows; a part that cannot be built sets none
    assert r['flags'] == {'USE_DISTRIBUTED': 'OFF', 'USE_MKLDNN': 'OFF', 'USE_XNNPACK': 'OFF', 'BUILD_TEST': '0'}
    assert r['lines'][0] == 'The parts of this build (variation lean; windows, cpu):'
    assert any('tensorpipe' in l and 'without its own submodules' in l for l in r['lines'])


def test_kineto_on_windows_says_what_differs_from_the_build_it_was_proven_with(build, pytorch):
    # the versions it was built with here, per target (round lapxpu3, 2026-11-25/26), as data of the part
    proven = pytorch['components']['kineto']['proven']['windows']
    assert proven['xpu'] == {'pytorch': '2.15', 'msvc': '19.50', 'oneapi': '2026.1'}
    assert proven['cpu'] == {'pytorch': '2.15', 'msvc': '19.50'}                      # round lapkin1, 2026-11-26

    notes = build_pytorch_class(build).kineto_proven.__globals__['kineto_notes']
    assert notes(proven, ['xpu'], {'pytorch': '2.15.0a0', 'msvc': '19.50.35726', 'oneapi': '2026.1.1'}) == []
    assert notes(proven, ['xpu'], {'pytorch': '2.14.1', 'msvc': '19.44.35211', 'oneapi': None}) == [
        'pytorch 2.14.1 is older than the 2.15 it was built with', 'msvc 19.44.35211 is older than the 19.50 it was built with',
        'the version of oneapi is not known (it was built with 2026.1)']

    # a CPU build with what it was built with says nothing; with an older compiler it says so
    assert notes(proven, ['cpu'], {'pytorch': '2.15.0a0', 'msvc': '19.50.35726', 'oneapi': None}) == []
    assert notes(proven, ['cpu'], {'pytorch': '2.15.0', 'msvc': '19.44.35211'}) == ['msvc 19.44.35211 is older than the 19.50 it was built with']

    # a target it was not built for here yet
    assert notes(proven, ['cuda'], {}) == ['it was not built here for cuda yet (only for cpu, xpu)']
    assert notes({}, ['cpu'], {}) == ['it was not built here for cpu yet']


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


def test_a_part_a_target_cannot_do_without_is_on_for_it(build, pytorch):
    # PyTorch 2.15 compiles its oneDNN sources for XPU always and builds oneDNN for the GPU only with USE_MKLDNN: on
    # Windows (where this program turns oneDNN off) an xpu build stopped after 2.5 h on oneapi/dnnl/dnnl.hpp
    assert 'xpu' in pytorch['components']['mkldnn']['required_for']
    for variation in ('lean', 'minimal'):
        r = resolve(build, pytorch, 'windows', ['xpu'], variation)
        assert r['return'] == 0, r
        assert states(r)['mkldnn'] == 'on' and r['parts']['mkldnn']['why'] == 'needed by the target xpu'
        assert r['flags']['USE_MKLDNN'] == 'ON' and 'third_party/ideep' not in r['not_recursive']
    # other targets keep the default and the variation
    assert states(resolve(build, pytorch, 'windows', ['cpu'], 'lean'))['mkldnn'] == 'off'

    # asked off, or its build variable set off: an error, before anything is built
    r = resolve(build, pytorch, 'windows', ['xpu'], None, asked = {'mkldnn': False})
    assert r['return'] == 1 and 'mkldnn-' in r['error'] and 'target xpu cannot be built without the part mkldnn' in r['error']
    r = resolve(build, pytorch, 'linux', ['xpu'], 'lean', given = {'USE_MKLDNN': 'OFF'})
    assert r['return'] == 1 and '--compile.d.USE_MKLDNN=OFF' in r['error']
    assert resolve(build, pytorch, 'linux', ['xpu'], 'lean', given = {'USE_MKLDNN': '1'})['return'] == 0

    # a part a target needs that cannot be built here: an error, not a silent "off"
    components = {'gpu-dnn': {'flags': {'USE_X': ['ON', 'OFF']}, 'os': ['linux'], 'required_for': ['xpu']}}
    r = build.resolve_components(components, {}, None, None, {'os': 'windows', 'targets': ['xpu']})
    assert r['return'] == 1 and 'the target xpu needs the part gpu-dnn' in r['error']


def test_a_run_without_parts_asked_still_gets_the_parts_its_targets_need(build, pytorch):
    # the build of before the parts were declared - with oneDNN on for xpu, over the defaults of customize_pytorch
    r = build.required_flags(pytorch['components'], ['xpu'])
    assert r['return'] == 0 and r['flags'] == {'USE_MKLDNN': 'ON'} and r['reasons'][0][:2] == ('mkldnn', 'xpu')
    assert build.required_flags(pytorch['components'], ['cpu', 'cuda']) == {'return': 0, 'flags': {}, 'reasons': []}
    # the request's own word: on is left to it, off is an error
    assert build.required_flags(pytorch['components'], ['xpu'], {'USE_MKLDNN': 'ON'})['flags'] == {}
    r = build.required_flags(pytorch['components'], ['xpu'], {'USE_MKLDNN': 0})
    assert r['return'] == 1 and 'cannot be built without the part mkldnn' in r['error']
    # required_for may be a list of targets
    assert build.required_by({'required_for': ['XPU']}, ['cpu', 'xpu']) == [('xpu', 'it needs this part')]


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

    # (the variation minimal: kineto is off there - its own default is on, Windows too since 2026-11-26)
    r = build.resolve_components(pytorch['components'], pytorch['variations'], 'minimal', None,
                                 {'os': 'windows', 'targets': ['cpu'], 'submodules': have}, None)
    assert set(r['not_recursive']) == {'third_party/tensorpipe', 'third_party/ideep'}
    assert 'third_party/kineto' in r['not_in_source'] and 'third_party/mslk' in r['not_in_source']
    assert states(r)['kineto'] == 'off' and r['flags']['USE_KINETO'] == 'OFF'          # the part itself is still off
    assert any('kineto' in l and 'third_party/kineto: no submodule of this source' in l for l in r['lines'])
    # without the fact, nothing is known of the source: every declared one is named
    assert resolve(build, pytorch, 'windows', ['cpu'], 'minimal')['not_in_source'] == []


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


def build_pytorch_class(build):
    """program/build-pytorch's CProgram, its base class a stand-in (no cMeta) and common_build the module under test."""
    path = REPO_ROOT / 'program' / 'build-pytorch' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8')
    src = src.replace('from program_22788f3c30d04e6d.api.cprogram import InitCProgram', 'class InitCProgram: pass')
    src = src.replace('from program_22788f3c30d04e6d.api import common_build', '')
    ns = {'__name__': 'build_pytorch_under_test', '__file__': str(path), 'common_build': build}
    exec(compile(src, str(path), 'exec'), ns)
    return ns['CProgram']


class _Packages:
    def match_version(self, spec, version):
        return {'return': 0, 'matched': in_range(spec, version)}


class _CM:
    packages = _Packages()

    def error(self, text):
        return {'return': 1, 'error': text}


@pytest.mark.parametrize('use, msvc, vs', [
    ({}, '19.44.35211', '19.44.35211'),                                                  # the run's pin, both
    ({'msvc': {'version': '19.50.35726'}}, '19.50.35726', '19.50.35726'),               # asked for: both
    ({'microsoft-visual-studio': {'version': '19.44.35211'}}, '19.44.35211', '19.44.35211'),
    ({'msvc': {'version': '19.50.35726'}, 'microsoft-visual-studio': {'version': '19.50.35726'}}, '19.50.35726', '19.50.35726'),
])
def test_build_pytorch_pins_the_visual_studio_of_its_msvc(build, monkeypatch, use, msvc, vs):
    # A step that sets Visual Studio up before msvc (oneAPI for xpu, asking for no version) took the newest
    # installation and msvc then found its version taken (2026-11-25): the installation follows the msvc of the run
    monkeypatch.setattr(build, 'msvc_installed', lambda: [('19.51.36260', 'vs18 build tools'), ('19.44.35211', 'vs2022')])
    program = object.__new__(build_pytorch_class(build))
    program.cm = _CM()
    ctx = {'control': {}, 'tasks': {'global': {'host': {'os': {'uname': 'windows'}}}, 'local': {}, 'use': use}}
    assert program.customize(ctx)['return'] == 0
    assert ctx['tasks']['use']['msvc']['version'] == msvc
    assert ctx['tasks']['use']['microsoft-visual-studio']['version'] == vs

    # Linux: nothing pinned
    ctx = {'control': {}, 'tasks': {'global': {'host': {'os': {'uname': 'linux'}}}, 'local': {}, 'use': {}}}
    assert program.customize(ctx)['return'] == 0 and ctx['tasks']['use'] == {}


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


def test_build_pytorch_asks_for_the_cuda_libraries_and_names_its_nvcc_to_cmake(pytorch):
    # a toolkit cMeta installed from NVIDIA's archives has the compiler alone until a program asks for its libraries
    text = (REPO_ROOT / 'program' / 'build-pytorch' / '_desc.yaml').read_text(encoding = 'utf-8')
    block = text[text.index('name: lib-cuda,ac9daedec465409e'):text.index('# Clone PyTorch source')]
    for lib in ('$cublas', '$cudart', '$cufft', '$curand', '$cusparse', '$cusolver', '$nvrtc', '$nvml', '$cufile'):
        assert ('- ' + lib) in block, lib
    assert '"cuda" in {{global.target.compute|$[]}}' in text[text.index('# CUDA libs: what PyTorch links'):text.index('name: lib-cuda,ac9daedec465409e')]
    src = (REPO_ROOT / 'program' / 'build-pytorch' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "env.setdefault('CUDACXX', nvcc_path)" in src


def _version_matches(spec, version):
    """The engine's version match, enough of it for these tests: ranges with commas, and a plain version as a prefix."""
    def key(v):
        return tuple(int(p) for p in str(v).split('.') if p.isdigit())
    for part in str(spec).split(','):
        part = part.strip()
        for op in ('>=', '<=', '==', '>', '<'):
            if part.startswith(op):
                want, have = key(part[len(op):]), key(version)
                n = max(len(want), len(have))
                want, have = want + (0,) * (n - len(want)), have + (0,) * (n - len(have))
                if not {'>=': have >= want, '<=': have <= want, '==': have == want, '>': have > want, '<': have < want}[op]:
                    return False
                break
        else:
            if key(version)[:len(key(part))] != key(part):
                return False
    return True


@pytest.mark.parametrize('built, asked, version, outside', [
    ('2.15.0', '', '2026.1', False),            # nothing asked: the release Intel names for 2.15
    ('2.14.1', '', '2026.1', False),
    ('2.13.0', '', '2026.0', False),
    ('2.12.0', '', '2025.3', False),
    ('2.11.0', '', None, False),                # a version no rule names asks nothing
    ('2.16.0', '', None, False),
    ('', '', None, False),                      # a branch: no version to look up
    ('2.15.0', '2026.0', None, False),          # asked, and inside what is seen to work
    ('2.15.0', '2026.2.0', None, False),
    ('2.15.0', '2025.3', None, True),           # asked, and known not to compile
    ('2.15.0', '==2025.3.3', None, True),
    ('2.13.0', '2026.1', None, True),           # no works_with: outside the one release Intel names
    ('2.15.0', '>=2025.3', None, False),        # a range is the request's own business
])
def test_the_toolkit_release_a_pytorch_version_is_built_with(build, pytorch, built, asked, version, outside):
    rules = pytorch['toolkits']['xpu']['oneapi']
    r = build.toolkit_request(rules, built, asked, _version_matches)
    assert (r['version'], r['outside']) == (version, outside)
    assert (r['rule'] is None) == (built in ('', '2.11.0', '2.16.0'))


def test_build_pytorch_declares_the_oneapi_release_of_each_pytorch_and_asks_it_before_the_compiler(pytorch):
    rules = pytorch['toolkits']['xpu']['oneapi']
    assert {r['program_version']: r['version'] for r in rules} == {
        '>=2.15,<2.16': '2026.1', '>=2.14,<2.15': '2026.1', '>=2.13,<2.14': '2026.0', '>=2.12,<2.13': '2025.3'}
    assert all(r['source'].startswith('https://www.intel.com/') for r in rules)

    # every named line is a release the oneapi tool can install, on both systems
    with open(REPO_ROOT / 'tool' / 'oneapi' / '_desc.yaml', encoding = 'utf-8') as f:
        releases = yaml.safe_load(f)['releases']
    for r in rules:
        names = [n for n in releases if _version_matches(r['version'], n)]
        assert names and all(set(releases[n]) == {'linux', 'windows'} for n in names), r

    # customize1 runs after the target task and before the compiler task of the template: there the release is asked
    src = (REPO_ROOT / 'program' / 'build-pytorch' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "return self.toolkits_of_targets(ctx, compute, params.get('params') or {})" in src
    assert "use.setdefault(tool, {})['version'] = r['version']" in src


@pytest.mark.parametrize('built, versions, older', [
    ('2.15.0', ['32.0.101.8804'], ['32.0.101.8804']),                       # older than the one Intel names
    ('2.15.0', ['32.0.101.9033'], []),                                      # the named one itself
    ('2.15.0', ['32.0.102.1', '32.0.101.8804'], ['32.0.101.8804']),         # two adapters, one of them older
    ('2.15.0', ['unknown', ''], []),                                        # what cannot be compared is not judged
    ('2.14.0', ['32.0.101.8804'], []),                                      # a version no rule names
    ('', ['32.0.101.8804'], []),                                            # a branch
])
def test_a_driver_older_than_the_one_its_vendor_names_is_said(build, pytorch, built, versions, older):
    rules = pytorch['drivers']['xpu']['windows']
    rule, found = build.drivers_older_than_named(rules, built, versions, _version_matches)
    assert found == older
    assert (rule is not None) == (built == '2.15.0')
    assert 'linux' not in pytorch['drivers']['xpu']        # Intel's page names no driver version for Linux


@pytest.mark.parametrize('compute, system, host', [
    (['xpu'], 'linux', ['cpu']),                      # PyTorch for an Intel GPU: the machine's compiler, icpx for SYCL
    (['cpu', 'xpu'], 'linux', ['cpu']),
    (['cpu', 'cuda', 'xpu'], 'linux', ['cpu', 'cuda']),
    (['cpu', 'cuda'], 'linux', ['cpu', 'cuda']),      # no xpu: the targets as they are
    (['xpu'], 'windows', ['xpu']),                    # Windows: MSVC builds, and the build names icx itself
    (['cpu'], 'darwin', ['cpu']),
])
def test_the_host_compilers_of_a_build_are_asked_for_the_targets_they_build(build, compute, system, host):
    assert build.host_compute(compute, system) == host


def test_build_pytorch_asks_its_host_compilers_for_the_targets_they_build(pytorch):
    uses = pytorch['updates']['compile']['uses']

    # the template's compiler step, and the C compiler the build adds, read the targets customize1 leaves them
    update = next(u for u in uses if u.get('match') == {'task': 'compiler,f3925b201c704bde'})
    assert update['update'] == {'compute': '{{local.pytorch_host_compute}}'}
    added = next(u for u in uses if u.get('match') == {'internal_func': 'customize2'})['append']
    c = next(a for a in added if a.get('task') == 'compiler,f3925b201c704bde')
    assert c['lang'] == 'c' and c['compute'] == '{{local.pytorch_host_compute}}'

    # oneAPI is set up for xpu itself (no longer through the compiler of the run), after the host compilers
    steps = [a.get('name') or a.get('task') for a in added]
    oneapi = next(a for a in added if str(a.get('name', '')).startswith('oneapi,'))
    assert '"xpu" in' in oneapi['if'] and steps.index(oneapi['name']) > steps.index('compiler,f3925b201c704bde')

    src = (REPO_ROOT / 'program' / 'build-pytorch' / 'api_v1.py').read_text(encoding = 'utf-8')
    hook = src[src.index('    def customize1('):src.index('    def toolkits_of_targets(')]
    assert "_local['pytorch_host_compute'] = common_build.host_compute(compute, system)" in hook


@pytest.mark.parametrize('system, compute, d, flags', [
    ('windows', ['xpu'], {}, {'USE_MKLDNN': 'ON'}),               # oneDNN, which this program turns off on Windows
    ('linux', ['xpu'], {}, {'USE_MKLDNN': 'ON'}),
    ('windows', ['xpu'], {'USE_MKLDNN': 'ON'}, None),            # the request's own word
    ('windows', ['cpu'], {}, None),                              # the build of before the parts were declared
    ('linux', ['cpu', 'cuda'], {}, None),
])
def test_build_pytorch_without_parts_asked_sets_only_what_its_targets_need(build, system, compute, d, flags):
    program = object.__new__(build_pytorch_class(build))
    program.cm = _CM()
    ctx = {'control': {}, 'tasks': {'global': {'host': {'os': {'uname': system}}, 'target': {'compute': compute}},
                                    'local': {}}}
    assert program.plan_components(ctx, params = {'compile': {'d': d}})['return'] == 0
    assert ctx['tasks']['local'].get('pytorch_component_flags') == flags
    assert 'pytorch_submodules_depth' not in ctx['tasks']['local']          # the clone of before: every submodule whole


def test_build_pytorch_refuses_a_request_its_targets_cannot_be_built_with(build):
    program = object.__new__(build_pytorch_class(build))
    program.cm = _CM()
    ctx = {'control': {}, 'tasks': {'global': {'host': {'os': {'uname': 'windows'}}, 'target': {'compute': ['xpu']}},
                                    'local': {}}}
    r = program.plan_components(ctx, params = {'compile': {'d': {'USE_MKLDNN': 'OFF'}}})
    assert r['return'] == 1 and 'cannot be built without the part mkldnn' in r['error']


def test_build_pytorch_asks_the_parts_only_when_the_request_names_one():
    src = (REPO_ROOT / 'program' / 'build-pytorch' / 'api_v1.py').read_text(encoding = 'utf-8')
    assert "if variation in (None, '', False) and not asked:" in src
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


@pytest.mark.parametrize('compile_params, depth', [
    ({'variation': 'minimal'}, 1),
    ({'components': {'kineto': 'on'}}, 1),
    ({}, None),                                                  # the build of before: the superproject whole
    ({'variation': ''}, None),
])
def test_build_pytorch_clones_the_superproject_shallow_for_a_variation_or_named_parts(build, compile_params, depth):
    """plan_clone, the step before the clone (2026-11-25): a build of a variation or of named parts reads one commit of
    the superproject - its tag alone (clone-git takes it with --branch); any other build clones it whole."""
    program = object.__new__(build_pytorch_class(build))
    ctx = {'control': {}, 'tasks': {'global': {}, 'local': {}}}
    assert program.plan_clone(ctx, params = {'compile': compile_params})['return'] == 0
    assert ctx['tasks']['local'].get('pytorch_superproject_depth') == depth
