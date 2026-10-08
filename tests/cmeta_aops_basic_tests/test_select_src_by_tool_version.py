"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of task/select-src-by-tool-version (one program, sources for several versions of a
tool): the version rules, the first-match order, what the step puts into the local context, its
errors, and that the Mojo test program has both generations of its sources.
"""

import pathlib
import types

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def compare(a, b):
    """A stand-in for cMeta's compare_versions: numeric parts, shorter padded with zeros."""
    pa, pb = ([int(x) for x in v.split('.')] for v in (a, b))
    n = max(len(pa), len(pb))
    pa, pb = pa + [0] * (n - len(pa)), pb + [0] * (n - len(pb))
    return '<' if pa < pb else '>' if pa > pb else '='


@pytest.fixture(scope = "module")
def mod():
    path = REPO_ROOT / "task" / "select-src-by-tool-version" / "api_v1.py"
    src = path.read_text(encoding = "utf-8")
    src = src.replace("from task_c36be4b9314a45e0.api.ctask import InitCTask",
                      "class InitCTask:\n    def __init__(self, *args, **kwargs):\n        pass")
    ns = {"__name__": "select_src", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def task(mod):
    t = mod["CTask"]()
    t.cm = types.SimpleNamespace(
        error = lambda text: {'return': 1, 'error': text},
        utils = types.SimpleNamespace(common = types.SimpleNamespace(
            compare_versions = lambda a, b: {'return': 0, 'comparison': compare(a, b)})))
    return t


def ctx(tool_version = None):
    g = {'mojo': {'version': tool_version}} if tool_version else {}
    return {'control': {}, 'tasks': {'nested_call': 0, 'global': g, 'local': {}}}


@pytest.mark.parametrize("version, spec, expected", [
    ("1.1.0", ">=1.0.0", True), ("1.0.0", ">=1.0.0", True), ("0.26.2.0", ">=1.0.0", False),
    ("0.26.2.0", ">=0.26.2,<1.0.0", True), ("1.0.0", ">=0.26.2,<1.0.0", False), ("0.26.1.0", ">=0.26.2,<1.0.0", False),
    ("1.1.0", "1.1.0", True), ("1.1", "==1.1.0", True), ("1.1.0", "!=1.1.0", False), ("1.0.0", "<=1.0.0", True),
    ("0.26.10", ">0.26.9", True),          # numbers, not text: 10 is more than 9
    ("3.2.1", "", True), ("3.2.1", None, True),
])
def test_version_rules(mod, version, spec, expected):
    assert mod["version_matches"](version, spec, compare) is expected


def test_a_rule_that_is_not_a_comparison_is_refused(mod):
    with pytest.raises(ValueError):
        mod["version_matches"]("1.0.0", "newest", compare)


def test_the_first_matching_rule_wins(mod):
    rules = [{'version': '>=2.0', 'src_dir': 'src-v3'}, {'version': '>=1.0.0', 'src_dir': 'src-v2'}, {'src_dir': 'src-old'}]
    assert mod["select_rule"]("2.1", rules, compare)['src_dir'] == 'src-v3'
    assert mod["select_rule"]("1.1.0", rules, compare)['src_dir'] == 'src-v2'
    assert mod["select_rule"]("0.25.7.0", rules, compare)['src_dir'] == 'src-old'
    assert mod["select_rule"]("0.25.7.0", rules[:2], compare) is None


def test_the_step_selects_the_folder_and_its_files(mod, tmp_path):
    for d in ('src', 'src-v2'):
        (tmp_path / d).mkdir()
        (tmp_path / d / 'program.mojo').write_text(d)
    rules = [{'version': '>=1.0.0', 'src_dir': 'src-v2'}]

    r = task(mod).run(ctx('1.1.0'), tool = 'mojo', rules = rules, program_path = str(tmp_path), src_file_names = ['program.mojo'])
    assert r['return'] == 0 and r['src_dir'] == 'src-v2' and r['tool_version'] == '1.1.0'
    local = r['add_to_local']
    assert local['src_path'] == str(tmp_path / 'src-v2')
    assert local['src_file_names_str_with_path'] == str(tmp_path / 'src-v2' / 'program.mojo')
    assert local['src_file_names_list'] == ['program.mojo']

    # An older tool: no rule matches, nothing changes, the program keeps its default sources
    r = task(mod).run(ctx('0.26.1.0'), tool = 'mojo', rules = rules, program_path = str(tmp_path), src_file_names = ['program.mojo'])
    assert r['return'] == 0 and 'add_to_local' not in r and 'src_dir' not in r


def test_the_step_fails_clearly(mod, tmp_path):
    rules = [{'version': '>=1.0.0', 'src_dir': 'src-v2'}]
    # before the setup of the tool
    assert 'not known' in task(mod).run(ctx(), tool = 'mojo', rules = rules, program_path = str(tmp_path))['error']
    # a folder that is not there
    assert 'does not exist' in task(mod).run(ctx('1.1.0'), tool = 'mojo', rules = rules, program_path = str(tmp_path))['error']
    # a source file that is not in the selected folder
    (tmp_path / 'src-v2').mkdir()
    r = task(mod).run(ctx('1.1.0'), tool = 'mojo', rules = rules, program_path = str(tmp_path), src_file_names = ['program.mojo'])
    assert 'is not in' in r['error']


def test_the_mojo_program_has_both_generations():
    program = REPO_ROOT / "program" / "test-nmm-mojo-cpu"
    desc = yaml.safe_load((program / "_desc.yaml").read_text(encoding = "utf-8"))
    steps = [s for u in desc['updates']['run']['uses'] for s in u.get('prepend', [])]
    select = [s for s in steps if str(s.get('task', '')).startswith('select-src-by-tool-version,')]
    assert len(select) == 1 and select[0]['tool'] == 'mojo'
    # the selection comes after the setup of mojo
    names = [str(s.get('name', s.get('task'))) for s in steps]
    assert names.index('mojo,666e926f670a4dbc') < [i for i, s in enumerate(steps) if s is select[0]][0]
    for rule in select[0]['rules']:
        for name in desc['local_vars']['src_file_names']:
            assert (program / rule['src_dir'] / name).is_file()
    for name in desc['local_vars']['src_file_names']:
        assert (program / 'src' / name).is_file()
    old = (program / 'src' / 'program.mojo').read_text(encoding = 'utf-8')
    new = (program / 'src-v2' / 'program.mojo').read_text(encoding = 'utf-8')
    assert '\nfn main()' in old and '\ndef main()' in new and '\nfn ' not in new
