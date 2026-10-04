"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/lib-cudnn: the redistributable archive chosen per OS, CPU and CUDA major version
(the pinned table and a redistrib index), the cases that fall back to the declarative install (16),
the install flow with a fake download (SHA-256 check, unpacking, found_path), and the detection of an
unpacked archive (include/lib/bin folders, the CUDA major version it was built for).
"""

import hashlib
import io
import os
import pathlib
import re
import tarfile
import zipfile

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = 'module')
def ns():
    path = REPO_ROOT / 'tool' / 'lib-cudnn' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8')
    src = src.replace('from tool_c393ba5c6fa14f66.api.ctool import InitCTool', 'class InitCTool: pass')
    src = src.replace('from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256',
                      'import hashlib\n'
                      'def _download(tool, ctx, params, url, directory, filename):\n'
                      '    return tool.fake_download(url, directory, filename)\n'
                      'def _sha256(path):\n'
                      "    return hashlib.sha256(open(path, 'rb').read()).hexdigest()\n")
    space = {'__name__': 'tool_lib_cudnn', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), space)
    return space


def test_assets_table(ns):
    assets = ns['ASSETS']
    assert set(assets) == {'linux-x86_64', 'linux-sbsa', 'windows-x86_64', 'windows-arm64'}
    for platform, per_major in assets.items():
        for major, (rel, sha) in per_major.items():
            assert major in (12, 13) and re.fullmatch(r'[0-9a-f]{64}', sha)
            assert rel.startswith(f'cudnn/{platform}/cudnn-{platform}-{ns["VERSION"]}_cuda{major}-archive.')
            assert rel.endswith('.zip' if platform.startswith('windows') else '.tar.xz')
    assert 12 not in assets['windows-arm64']


def test_asset_for(ns):
    asset_for, VERSION = ns['asset_for'], ns['VERSION']
    assert asset_for('linux-x86_64', 13)[0].endswith('_cuda13-archive.tar.xz')
    assert asset_for('windows-x86_64', 12)[0].endswith('_cuda12-archive.zip')
    assert asset_for('windows-arm64', 12) is None
    assert asset_for('darwin', 13) is None
    index = {'cudnn': {'version': '9.26.0.5', 'linux-x86_64': {
        'cuda13': {'relative_path': 'cudnn/linux-x86_64/x_cuda13-archive.tar.xz', 'sha256': 'ab' * 32},
        'cuda12': {'relative_path': 'cudnn/linux-x86_64/x_cuda12-archive.tar.xz'}}}}      # no digest: unusable
    assert asset_for('linux-x86_64', 13, '9.26.0.5', index) == ('cudnn/linux-x86_64/x_cuda13-archive.tar.xz', 'ab' * 32)
    assert asset_for('linux-x86_64', 12, '9.26.0.5', index) is None
    assert ns['index_name']('9.26.0.5') == 'redistrib_9.26.0.json' and ns['index_name']('9.26.0') == 'redistrib_9.26.0.json'
    assert ns['detected_version']('9.27.0.42') == '9.27.0' and ns['detected_version']('9.0.0') == '9.0.0'


def test_cuda_majors(ns):
    assert ns['cuda_major']('13.3.73') == 13 and ns['cuda_major']('12.9.86') == 12 and ns['cuda_major'](None) is None
    assert ns['archive_cuda_major']('/x/content/cudnn-linux-x86_64-9.27.0.42_cuda13-archive') == 13
    assert ns['archive_cuda_major']('C:\\Program Files\\NVIDIA\\CUDNN\\v9.21') is None


def fake_archive(tmp_path, name, platform):
    """A tiny cuDNN-like archive: include/cudnn.h, include/cudnn_version.h, lib/ (lib/x64 on Windows), bin/."""
    root = f'cudnn-{platform}-9.27.0.42_cuda13-archive'
    files = {f'{root}/include/cudnn.h': b'// cudnn\n',
             f'{root}/include/cudnn_version.h': b'#define CUDNN_MAJOR 9\n#define CUDNN_MINOR 27\n#define CUDNN_PATCHLEVEL 0\n',
             f'{root}/LICENSE.txt': b'NVIDIA cuDNN license\n'}
    if platform.startswith('windows'):
        files[f'{root}/bin/cudnn64_9.dll'] = b'MZ'
        files[f'{root}/lib/x64/cudnn.lib'] = b'!<arch>'
    else:
        files[f'{root}/lib/libcudnn.so.9'] = b'\x7fELF'
    path = tmp_path / name
    if name.endswith('.zip'):
        with zipfile.ZipFile(path, 'w') as z:
            for n, data in files.items():
                z.writestr(n, data)
    else:
        with tarfile.open(path, 'w:xz') as t:
            for n, data in files.items():
                info = tarfile.TarInfo(n)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    return path, root


class FakeCM:
    def error(self, text):
        return {'return': 1, 'error': text}


def make_tool(ns, tmp_path, archive = None, sha_ok = True):
    tool = object.__new__(ns['CTool'])
    tool.cm = FakeCM()
    tool.downloads = []

    def fake_download(url, directory, filename):
        tool.downloads.append(url)
        if archive is None:
            return {'return': 1, 'error': 'no download in this test'}
        dest = tmp_path / directory / filename
        dest.parent.mkdir(parents = True, exist_ok = True)
        dest.write_bytes(archive.read_bytes() if sha_ok else b'corrupt')
        return {'return': 0, 'path': str(dest)}
    tool.fake_download = fake_download
    return tool


def ctx_for(uname, uarch, nvcc_version):
    return {'tasks': {'global': {'host': {'os': {'uname': uname, 'uarch': uarch}}, 'nvcc': {'version': nvcc_version}}}}


def test_install_falls_back_where_nvidia_publishes_nothing(ns, tmp_path):
    tool = make_tool(ns, tmp_path)
    for uname, uarch, nvcc, words in [('darwin', 'arm64', '13.3.73', 'not for darwin'),
                                      ('linux', 'amd64', '11.8.89', 'CUDA 12 and 13'),
                                      ('windows', 'arm64', '12.9.86', 'no archive for windows-arm64 and CUDA 12')]:
        r = tool.install(ctx_for(uname, uarch, nvcc), {'control': {}}, 'apt-get install libcudnn')
        assert r['return'] == 16 and r['install_cmd'] == 'apt-get install libcudnn' and words in r['error'], r
    r = tool.install(ctx_for('linux', 'amd64', '13.3.73'), {'control': {}, 'version': '>=9', 'version_simple': None}, None)
    assert r['return'] == 16 and 'exact version' in r['error']
    assert tool.downloads == []


def test_install_unpacks_and_checks(ns, tmp_path, monkeypatch):
    archive, root = fake_archive(tmp_path, 'cudnn-linux-x86_64-9.27.0.42_cuda13-archive.tar.xz', 'linux-x86_64')
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setitem(ns['ASSETS']['linux-x86_64'], 13, (ns['ASSETS']['linux-x86_64'][13][0], sha))
    work = tmp_path / 'entry'
    work.mkdir()
    monkeypatch.chdir(work)
    tool = make_tool(ns, tmp_path, archive)
    r = tool.install(ctx_for('linux', 'amd64', '13.3.73'), {'control': {}}, None)
    assert r['return'] == 0 and r['install_cmd'] is None
    assert os.path.normcase(r['found_path']) == os.path.normcase(str(work / 'content' / root / 'include' / 'cudnn.h'))
    assert (work / 'content' / root / 'lib' / 'libcudnn.so.9').is_file()
    assert not list((tmp_path / 'download').glob('*.tar.xz'))                     # the archive is removed
    assert tool.downloads == [ns['REDIST'] + ns['ASSETS']['linux-x86_64'][13][0]]

    # A corrupt download is refused and removed
    tool = make_tool(ns, tmp_path, archive, sha_ok = False)
    r = tool.install(ctx_for('linux', 'amd64', '13.3.73'), {'control': {}}, None)
    assert r['return'] == 1 and 'SHA-256 mismatch' in r['error']


def test_install_windows_zip_and_other_version(ns, tmp_path, monkeypatch):
    archive, root = fake_archive(tmp_path, 'cudnn-windows-x86_64-9.26.0.5_cuda13-archive.zip', 'windows-x86_64')
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    index = {'cudnn': {'version': '9.26.0.5', 'windows-x86_64': {
        'cuda13': {'relative_path': 'cudnn/windows-x86_64/cudnn-windows-x86_64-9.26.0.5_cuda13-archive.zip', 'sha256': sha}}}}
    work = tmp_path / 'entry'
    work.mkdir()
    monkeypatch.chdir(work)
    tool = make_tool(ns, tmp_path, archive)
    real = tool.fake_download

    def download(url, directory, filename):
        if filename.endswith('.json'):
            dest = tmp_path / directory / filename
            dest.parent.mkdir(parents = True, exist_ok = True)
            dest.write_text(__import__('json').dumps(index))
            tool.downloads.append(url)
            return {'return': 0, 'path': str(dest)}
        return real(url, directory, filename)
    tool.fake_download = download
    r = tool.install(ctx_for('windows', 'amd64', '13.2.0'), {'control': {}, 'version': '9.26.0', 'version_simple': '9.26.0'}, None)
    assert r['return'] == 0 and r['found_path'].endswith(os.path.join('include', 'cudnn.h'))
    assert tool.downloads[0].endswith('redistrib_9.26.0.json')
    assert tool.downloads[1].endswith('cudnn-windows-x86_64-9.26.0.5_cuda13-archive.zip')
    assert (work / 'content' / root / 'bin' / 'cudnn64_9.dll').is_file()


class FakeFiles:
    def read_file(self, path):
        return {'return': 0, 'data': open(path, encoding = 'utf-8').read()}


class FakeCMDetect:
    debug = False
    utils = type('U', (), {'files': FakeFiles()})()

    def q(self, s):
        return f'"{s}"'

    def catch_error(self, r):
        return r['return'] > 0


def unpacked(tmp_path, platform, major = 13):
    root = tmp_path / 'content' / f'cudnn-{platform}-9.27.0.42_cuda{major}-archive'
    (root / 'include').mkdir(parents = True)
    (root / 'include' / 'cudnn.h').write_text('// cudnn\n')
    (root / 'include' / 'cudnn_version.h').write_text('#define CUDNN_MAJOR 9\n#define CUDNN_MINOR 27\n#define CUDNN_PATCHLEVEL 0\n')
    if platform.startswith('windows'):
        (root / 'bin').mkdir()
        (root / 'lib' / 'x64').mkdir(parents = True)
    else:
        (root / 'lib').mkdir()
    return root


def detect(ns, uname, uarch, nvcc_version, header):
    tool = object.__new__(ns['CTool'])
    tool.cm = FakeCMDetect()
    ctx = {'tasks': {'global': {'host': {'os': {'uname': uname, 'uarch': uarch}}, 'nvcc': {'version': nvcc_version}}}}
    return tool.detect_versions(ctx, [str(header)], {})['found_paths_with_versions']


def test_detect_unpacked_archive_linux(ns, tmp_path):
    root = unpacked(tmp_path, 'linux-x86_64')
    found = detect(ns, 'linux', 'amd64', '13.3.73', root / 'include' / 'cudnn.h')
    assert len(found) == 1
    f = next(iter(found.values()))
    paths = f['features']['paths']
    assert f['output'] == '9.27.0' and f['features']['lib_names'] == ['$cudnn'] and f['features']['cuda_version'] == '13.3.73'
    assert paths['lib'] == str(root / 'lib') and paths['dynamic_lib'] == str(root / 'lib')
    assert paths['include'] == str(root / 'include') and paths['home'] == str(root)


def test_detect_unpacked_archive_windows(ns, tmp_path):
    root = unpacked(tmp_path, 'windows-x86_64')
    f = next(iter(detect(ns, 'windows', 'amd64', '13.2.0', root / 'include' / 'cudnn.h').values()))
    paths = f['features']['paths']
    assert paths['lib'] == str(root / 'lib' / 'x64') and paths['dynamic_lib'] == str(root / 'bin')


def test_detect_skips_an_archive_of_another_cuda_major(ns, tmp_path):
    root = unpacked(tmp_path, 'linux-x86_64', major = 12)
    assert detect(ns, 'linux', 'amd64', '13.3.73', root / 'include' / 'cudnn.h') == {}
    assert len(detect(ns, 'linux', 'amd64', '12.9.86', root / 'include' / 'cudnn.h')) == 1


def test_installer_layout_still_detected(ns, tmp_path):
    """NVIDIA's Windows installer: CUDNN\\v9.21\\include\\13.2\\cudnn.h, lib\\13.2\\x64, bin\\13.2\\x64."""
    home = tmp_path / 'CUDNN' / 'v9.21'
    (home / 'include' / '13.2').mkdir(parents = True)
    (home / 'include' / '13.2' / 'cudnn.h').write_text('')
    (home / 'include' / '13.2' / 'cudnn_version.h').write_text('#define CUDNN_MAJOR 9\n#define CUDNN_MINOR 21\n#define CUDNN_PATCHLEVEL 0\n')
    (home / 'lib' / '13.2' / 'x64').mkdir(parents = True)
    (home / 'bin' / '13.2' / 'x64').mkdir(parents = True)
    found = detect(ns, 'windows', 'amd64', '13.3.73', home / 'include' / '13.2' / 'cudnn.h')
    f = next(iter(found.values()))
    assert f['output'] == '9.21.0'
    assert f['features']['paths']['lib'] == str(home / 'lib' / '13.2' / 'x64')
    assert f['features']['paths']['dynamic_lib'] == str(home / 'bin' / '13.2' / 'x64')
    # built for a newer CUDA minor than the toolkit: not taken
    assert detect(ns, 'windows', 'amd64', '13.1.0', home / 'include' / '13.2' / 'cudnn.h') == {}


def test_desc_and_sizes():
    desc = yaml.safe_load((REPO_ROOT / 'tool' / 'lib-cudnn' / '_desc.yaml').read_text(encoding = 'utf-8'))
    assert desc['names'] == ['cudnn.h'] and 'developer.nvidia.com/cudnn' in desc['install_help_text']
    sizes = yaml.safe_load((REPO_ROOT / 'tool' / 'lib-cudnn' / '_desc_sizes.yaml').read_text(encoding = 'utf-8'))['sizes']
    assert sizes[-1].get('if') is None and all(rule['peak'] >= rule.get('kept', 0) for rule in sizes)


def test_gpu_arch_min_for(ns):
    f = ns['gpu_arch_min_for']
    assert f('9.0.0') == 50 and f('9.5.1') == 50 and f('9.10.2') == 50            # Maxwell kernels still shipped
    assert f('9.27.0') == 75 and f('9.27.0.42') == 75                             # Turing and newer
    assert ns['MAXWELL_DROPPED'] == (9, 11) and f('9.11.1') == 75 and f('9.12.0') == 75   # the first releases without them
    assert f('8.9.7') is None and f(None) is None and f('') is None


def test_gpu_too_old(ns):
    gpu_too_old = ns['gpu_too_old']
    why = gpu_too_old(50, '9.27.0')
    assert why and 'compute capability 7.5' in why and 'this GPU is 5.0' in why and '--version=9.10.2' in why
    assert gpu_too_old(61, '9.27.0') is not None                      # Pascal: too old for the recent releases
    assert gpu_too_old(50, '9.10.2') is None and gpu_too_old(50, '9.0.0') is None   # early 9.x run on Maxwell
    assert gpu_too_old(35, '9.0.0') is not None                       # Kepler: below cuDNN 9's minimum
    assert gpu_too_old(75, '9.27.0') is None and gpu_too_old(86, '9.27.0') is None and gpu_too_old(120, '9.27.0') is None
    assert gpu_too_old(None, '9.27.0') is None and gpu_too_old('', '9.27.0') is None     # no GPU known: no verdict
    assert gpu_too_old(50, '8.9.7') is None                           # cuDNN 8: not described


def test_finish_checks_the_gpu(ns):
    tool = object.__new__(ns['CTool'])
    tool.cm = FakeCM()
    result = {'return': 0, 'version': '9.27.0', 'features': {'paths': {'dynamic_lib': '/nonexistent'}}}
    old = {'tasks': {'global': {'cuda': {'features': {'compute_cap_int_min': 50}}}}}
    new = {'tasks': {'global': {'cuda': {'features': {'compute_cap_int_min': 86}}}}}
    r = tool.finish_dynamic_result(old, dict(result, features = {'paths': {'dynamic_lib': '/nonexistent'}}), {})
    assert r['return'] == 1 and 'this GPU is 5.0' in r['error']
    r = tool.finish_dynamic_result(old, dict(result, features = {'paths': {'dynamic_lib': '/nonexistent'}}), {'with': {'any_gpu': True}})
    assert r['return'] == 0
    res = dict(result, features = {'paths': {'dynamic_lib': '/nonexistent'}})
    assert tool.finish_dynamic_result(new, res, {})['return'] == 0 and res['features']['gpu_arch_min'] == 75
    early = dict(result, version = '9.10.2', features = {'paths': {'dynamic_lib': '/nonexistent'}})
    assert tool.finish_dynamic_result(old, early, {})['return'] == 0 and early['features']['gpu_arch_min'] == 50
    # a version check (the cache re-check of an entry) never judges the GPU
    assert tool.finish_dynamic_result(old, dict(result, features = {'paths': {'dynamic_lib': '/x'}}), {'version_check': True})['return'] == 0


def test_install_pinned_version_asked_in_detected_form(ns, tmp_path, monkeypatch):
    """--version=9.27.0 (what cudnn_version.h reports) is the pinned release: no index download."""
    archive, root = fake_archive(tmp_path, 'cudnn-linux-x86_64-9.27.0.42_cuda13-archive.tar.xz', 'linux-x86_64')
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setitem(ns['ASSETS']['linux-x86_64'], 13, (ns['ASSETS']['linux-x86_64'][13][0], sha))
    work = tmp_path / 'entry'
    work.mkdir()
    monkeypatch.chdir(work)
    tool = make_tool(ns, tmp_path, archive)
    r = tool.install(ctx_for('linux', 'amd64', '13.3.73'), {'control': {}, 'version': '9.27.0', 'version_simple': '9.27.0'}, None)
    assert r['return'] == 0 and len(tool.downloads) == 1 and tool.downloads[0].endswith('_cuda13-archive.tar.xz')
