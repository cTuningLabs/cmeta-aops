"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of the OpenMP runtime of tool/llvm: a release is looked at, not its number; the sources of a release
without the runtime are found in the layouts _desc.yaml declares and checked against a pinned or published sha256;
an LLVM the tool did not unpack is never written; what was built is put where a release with OpenMP keeps it.
"""

import io
import json
import os
import pathlib
import py_compile
import tarfile

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / 'tool' / 'llvm' / 'api_v1.py'

IMPORTS = {
    'from tool_c393ba5c6fa14f66.api.ctool import InitCTool': 'class InitCTool: pass',
    'from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256': '_download = _sha256 = None',
}


@pytest.fixture(scope = 'module')
def llvm():
    src = HOOK.read_text(encoding = 'utf-8')
    for line, stub in IMPORTS.items():
        assert line in src
        src = src.replace(line, stub)
    ns = {'__name__': 'llvm_under_test', '__file__': str(HOOK)}
    exec(compile(src, str(HOOK), 'exec'), ns)
    return ns


@pytest.fixture(scope = 'module')
def spec():
    return yaml.safe_load((REPO_ROOT / 'tool' / 'llvm' / '_desc.yaml').read_text(encoding = 'utf-8'))['openmp_runtime']


def test_the_whole_hook_file_compiles(tmp_path):
    py_compile.compile(str(HOOK), cfile = str(tmp_path / 'llvm.pyc'), doraise = True)


def test_a_release_is_looked_at_not_its_number(llvm, tmp_path):
    home = tmp_path / 'content'
    (home / 'lib' / 'clang' / '21' / 'include').mkdir(parents = True)
    assert not llvm['has_openmp'](str(home))
    (home / 'lib' / 'clang' / '21' / 'include' / 'omp.h').write_text('')
    assert llvm['has_openmp'](str(home))
    assert not llvm['has_openmp']('')


def test_the_sources_of_a_release_and_their_sha256(llvm, spec):
    sources = llvm['openmp_sources']
    sha = lambda c: c * 64

    # 21.1.8: pinned in _desc.yaml - nothing asked of GitHub
    r = sources(spec, '21.1.8', None)
    assert r['files'] == {'openmp': 'openmp-21.1.8.src.tar.xz', 'cmake': 'cmake-21.1.8.src.tar.xz'} and r['folders'] == []
    assert r['sha256']['openmp-21.1.8.src.tar.xz'] == '856b023748b41ac7b2c83fd8e9f765ff48a4df2fe6777d2811ef7c7ed8f2f977'

    # 20.1.8: not pinned, GitHub publishes the digests; offline, nothing can be checked
    assets = {'openmp-20.1.8.src.tar.xz': sha('a'), 'cmake-20.1.8.src.tar.xz': sha('b'), 'llvm-project-20.1.8.src.tar.xz': sha('c')}
    r = sources(spec, '20.1.8', assets)
    assert r['files']['openmp'] == 'openmp-20.1.8.src.tar.xz' and r['sha256']['cmake-20.1.8.src.tar.xz'] == sha('b')
    assert sources(spec, '20.1.8', None)['files'] is None

    # 22.x publishes the whole llvm-project only: the second layout, two folders of it
    r = sources(spec, '22.1.8', {'llvm-project-22.1.8.src.tar.xz': sha('d'), 'LLVM-22.1.8-Linux-X64.tar.xz': sha('e')})
    assert r['files'] == {'llvm-project': 'llvm-project-22.1.8.src.tar.xz'} and r['folders'] == ['openmp', 'cmake']

    # 19.x: published before GitHub gave digests - nothing unchecked is built; pinning them is the fix
    r = sources(spec, '19.1.7', {'openmp-19.1.7.src.tar.xz': None, 'cmake-19.1.7.src.tar.xz': None,
                                  'llvm-project-19.1.7.src.tar.xz': None})
    assert r['files'] is None and 'no sha256 pinned or published' in r['why']
    pinned = dict(spec, sha256 = {'19.1.7': {'openmp-19.1.7.src.tar.xz': sha('1'), 'cmake-19.1.7.src.tar.xz': sha('2')}})
    assert sources(pinned, '19.1.7', None)['files']['openmp'] == 'openmp-19.1.7.src.tar.xz'


def make_source_tar(path, top, files):
    with tarfile.open(path, 'w:xz') as t:
        for name, data in files.items():
            info = tarfile.TarInfo(f'{top}/{name}')
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo(f'{top}/openmp/link')
        link.type = tarfile.SYMTYPE
        link.linkname = '/etc/passwd'
        t.addfile(link)


def test_the_folders_of_the_whole_source_are_taken_without_its_top_folder(llvm, tmp_path):
    archive = tmp_path / 'llvm-project-22.1.8.src.tar.xz'
    make_source_tar(archive, 'llvm-project-22.1.8.src', {'openmp/CMakeLists.txt': b'x', 'cmake/Modules/a.cmake': b'y',
                                                         'clang/huge.cpp': b'z'})
    with tarfile.open(archive) as t:
        names = [m.name for m in llvm['safe_members'](t, ['openmp', 'cmake'])]
    assert sorted(names) == ['cmake/Modules/a.cmake', 'openmp/CMakeLists.txt']       # no clang/, no link
    with tarfile.open(archive) as t:
        assert sorted(m.name for m in llvm['safe_members'](t)) == ['clang/huge.cpp', 'cmake/Modules/a.cmake', 'openmp/CMakeLists.txt']


def test_the_runtime_goes_where_a_release_with_openmp_keeps_it(llvm, tmp_path):
    stage = tmp_path / 'stage'
    for name in ('include/omp.h', 'include/ompx.h', 'lib/libomp.so', 'lib/libarcher_static.a', 'lib/cmake/openmp/FindOpenMPTarget.cmake'):
        (stage / name).parent.mkdir(parents = True, exist_ok = True)
        (stage / name).write_text(name)
    resource, lib = tmp_path / 'content' / 'lib' / 'clang' / '21', tmp_path / 'content' / 'lib' / 'x86_64-unknown-linux-gnu'
    placed = llvm['place_openmp'](str(stage), str(resource), str(lib))
    assert sorted(os.path.relpath(p, tmp_path / 'content').replace(os.sep, '/') for p in placed) == [
        'lib/clang/21/include/omp.h', 'lib/clang/21/include/ompx.h',
        'lib/x86_64-unknown-linux-gnu/libarcher_static.a', 'lib/x86_64-unknown-linux-gnu/libomp.so']
    assert llvm['has_openmp'](str(tmp_path / 'content'))


class _CM:
    def access(self, i):
        raise AssertionError(f'nothing is set up or downloaded here: {i}')


def tool_object(llvm, spec):
    tool = object.__new__(llvm['CTool'])
    tool.cm = _CM()
    tool.cdesc = {'openmp_runtime': spec}
    return tool


def ctx(uname = 'linux'):
    return {'control': {}, 'tasks': {'global': {'host': {'os': {'uname': uname}}}, 'nested_call': 0}}


def llvm_entry(tmp_path, with_openmp = False):
    entry = tmp_path / 'task--setup--llvm--x'
    home = entry / 'content'
    (home / 'bin').mkdir(parents = True)
    (home / 'bin' / 'clang').write_text('')
    if with_openmp:
        (home / 'lib' / 'clang' / '23' / 'include').mkdir(parents = True)
        (home / 'lib' / 'clang' / '23' / 'include' / 'omp.h').write_text('')
    return entry, home, {'path': str(home / 'bin' / 'clang'), 'path_cmeta_cache': str(entry),
                         'features': {'paths': {'home': str(home)}}}


def test_an_llvm_with_the_runtime_or_not_of_this_tool_is_left_as_it_is(llvm, spec, tmp_path):
    tool = tool_object(llvm, spec)

    entry, home, result = llvm_entry(tmp_path / 'a', with_openmp = True)
    result['version'] = '23.1.6'
    assert tool.complete_openmp(ctx(), result)['return'] == 0 and result['features']['openmp'] is True

    # the system's LLVM (or another installer's): never written, whatever it lacks
    system = tmp_path / 'usr' / 'lib' / 'llvm-21'
    (system / 'bin').mkdir(parents = True)
    result = {'path': str(system / 'bin' / 'clang'), 'version': '21.1.8', 'features': {'paths': {'home': str(system)}}}
    assert tool.complete_openmp(ctx(), result)['return'] == 0 and result['features']['openmp'] is False
    assert not os.listdir(system / 'bin')

    # a system openmp_runtime does not name: used as it is
    entry, home, result = llvm_entry(tmp_path / 'b')
    result['version'] = '21.1.8'
    assert tool.complete_openmp(ctx('windows'), result)['return'] == 0 and not (home / llvm['OPENMP_MARKER']).exists()


def test_a_release_without_sources_to_check_is_said_and_remembered_until_the_data_changes(llvm, spec, tmp_path, monkeypatch):
    tool = tool_object(llvm, spec)
    entry, home, result = llvm_entry(tmp_path)
    result['version'] = '19.1.7'
    asked = []
    monkeypatch.setitem(tool.complete_openmp.__globals__, 'release_assets',
                        lambda version: asked.append(version) or {'openmp-19.1.7.src.tar.xz': None, 'cmake-19.1.7.src.tar.xz': None})

    r = tool.complete_openmp(ctx(), result)
    assert r['return'] == 1 and 'pin their sha256' in r['error'] and asked == ['19.1.7']
    marker = json.loads((home / llvm['OPENMP_MARKER']).read_text(encoding = 'utf-8'))
    assert marker['status'] == 'unavailable' and marker['version'] == '19.1.7'

    # the next use asks GitHub nothing
    assert tool.complete_openmp(ctx(), result)['return'] == 1 and asked == ['19.1.7']

    # a pin added to _desc.yaml is a new decision: the build is tried (here it would set up cmake - stopped by the stub)
    tool.cdesc = {'openmp_runtime': dict(spec, sha256 = {'19.1.7': {'openmp-19.1.7.src.tar.xz': 'a' * 64,
                                                                    'cmake-19.1.7.src.tar.xz': 'b' * 64}})}
    monkeypatch.setitem(tool.complete_openmp.__globals__, 'subprocess',
                        type('S', (), {'run': staticmethod(lambda *a, **k: type('P', (), {'returncode': 0, 'stdout': 'x', 'stderr': ''})()),
                                       'DEVNULL': None}))
    (home / 'bin' / 'clang++').write_text('')
    with pytest.raises(AssertionError, match = 'nothing is set up'):
        tool.complete_openmp(ctx(), result)


def test_an_llvm_of_an_unknown_release_is_not_completed(llvm, spec, tmp_path):
    tool = tool_object(llvm, spec)
    entry, home, result = llvm_entry(tmp_path)
    result['version'] = 'default'
    r = tool.complete_openmp(ctx(), result)
    assert r['return'] == 1 and 'not known' in r['error']
