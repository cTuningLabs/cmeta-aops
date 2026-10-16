"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/gcc and tool/gcc-cpp take a compiler only with its binutils next to it (ar): one without them builds nothing.
Before 2026-10-17 such a gcc stopped the run ("library sub-tool not found"), so the setup never installed the
toolchain that was missing (Azure Linux 3.0, whose gcc package came alone into an older instance); now it is not a
candidate, and with no candidate left the setup installs gcc with binutils.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class FakeCM:
    def q(self, path):
        return f'"{path}"'

    def error(self, text, code=1):
        return {'return': code, 'error': text}


def tool(name):
    path = REPO_ROOT / 'tool' / name / 'api_v1.py'
    src = path.read_text(encoding='utf-8').replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                                                   'class InitCTool: pass')
    ns = {'__name__': f'tool_{name}_under_test', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    t = ns['CTool'].__new__(ns['CTool'])
    t.cm = FakeCM()
    return t


@pytest.mark.parametrize('name, exe', [('gcc', 'gcc'), ('gcc-cpp', 'g++')])
def test_a_compiler_without_binutils_is_not_a_candidate(tmp_path, capsys, name, exe):
    alone = tmp_path / 'alone' / 'bin'
    full = tmp_path / 'full' / 'bin'
    for folder in (alone, full):
        folder.mkdir(parents=True)
        (folder / exe).write_text('')
    (full / 'ar').write_text('')

    ctx = {'control': {'con': True}}
    r = tool(name).check_features(ctx, [{'path': str(alone / exe)}, {'path': str(full / exe)}], {})

    assert r['return'] == 0
    assert [p['path'] for p in r['paths']] == [str(full / exe)]
    assert r['paths'][0]['features']['paths']['tool_lib'] == str(full / 'ar')
    assert 'has no "ar" next to it' in capsys.readouterr().out


def test_no_candidate_left_is_an_empty_list_not_an_error(tmp_path):
    alone = tmp_path / 'bin'
    alone.mkdir()
    (alone / 'gcc').write_text('')

    r = tool('gcc').check_features({'control': {'con': False}}, [{'path': str(alone / 'gcc')}], {})
    assert r == {'return': 0, 'paths': []}           # the setup's detection then says "not found" (16): install
