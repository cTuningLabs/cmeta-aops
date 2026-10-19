"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Checked complete distributions retain libraries and reject escaping archive paths/links.
"""

import hashlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import tarfile
import zipfile

import pytest


@pytest.fixture
def release():
    path = Path(__file__).resolve().parents[2] / 'category/tool/api/common_release.py'
    spec = importlib.util.spec_from_file_location('release_tree_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tree_retains_runtime_and_checks_sha512(release, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('search-1.0.0/bin/search.bat', 'echo Version: 1.0.0')
        archive.writestr('search-1.0.0/jdk/bin/java.exe', b'jdk')
        archive.writestr('search-1.0.0/lib/search.jar', b'library')
        archive.writestr('search-1.0.0/config/search.yml', b'configuration')
    data = buf.getvalue()
    sums = hashlib.sha512(data).hexdigest()

    def download(tool, ctx, params, url, directory, name):
        path = tmp_path / directory / name
        path.write_bytes((sums + '  search.zip').encode() if url.endswith('.sha512') else data)
        return {'return': 0, 'path': str(path)}

    monkeypatch.setattr(release, '_download', download)
    tool = SimpleNamespace(cdesc={'default_version': '1.0.0'}, cm=SimpleNamespace(
        error=lambda message: {'return': 1, 'error': message}))
    context = {'tasks': {'global': {'host': {'os': {'uname': 'windows', 'uarch': 'amd64'},
                                              'vars': {'file_ext_exe': '.exe'}}}}}
    spec = dict(name='search', url='https://example.invalid/search.zip', ext='zip', exe='.bat',
                member='search-{version}/bin/search.bat', tree=True,
                checksum={'file': '{url}.sha512', 'algorithm': 'sha512'})
    result = release.install_release(tool, context, {}, None, spec)
    assert result['return'] == 0
    assert Path(result['found_path']).read_text() == 'echo Version: 1.0.0'
    assert (tmp_path / 'content/search-1.0.0/jdk/bin/java.exe').read_bytes() == b'jdk'
    assert (tmp_path / 'content/search-1.0.0/lib/search.jar').read_bytes() == b'library'
    assert not (tmp_path / 'content/search.zip').exists()

    # A damaged next download must fail before it extracts anything, and is removed for retry.
    sums = '0' * 128
    result = release.install_release(tool, context, {}, None, spec)
    assert result['return'] != 0 and 'SHA-512 mismatch' in result['error']
    assert not (tmp_path / 'content/search.zip').exists()


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'search-1/../../outside', 'C:/outside'])
def test_tree_rejects_escaping_zip_members(release, tmp_path, name):
    path = tmp_path / 'bad.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('search-1/bin/search', b'launcher')
        archive.writestr(name, b'escape')
    with pytest.raises(ValueError):
        release._unpack_tree(str(path), 'search-1/bin/search', str(tmp_path))
    assert not (tmp_path / 'search-1').exists()


def test_tree_preserves_internal_links_and_rejects_escape(release, tmp_path):
    for target, valid in [('java', True), ('../../../outside', False)]:
        path = tmp_path / ('good.tar.gz' if valid else 'bad.tar.gz')
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in [('search-1/bin/search', b'launcher'), ('search-1/jdk/bin/java', b'jdk')]:
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o755
                archive.addfile(info, io.BytesIO(data))
            info = tarfile.TarInfo('search-1/jdk/bin/java-link')
            info.type, info.linkname = tarfile.SYMTYPE, target
            archive.addfile(info)
        destination = tmp_path / ('good' if valid else 'bad')
        destination.mkdir()
        if valid:
            if not hasattr(tarfile, 'data_filter'):
                pytest.skip('link fixture requires data_filter')
            try:
                release._unpack_tree(str(path), 'search-1/bin/search', str(destination))
            except OSError as error:
                if getattr(error, 'winerror', None) == 1314:
                    pytest.skip('Windows account cannot create symbolic links')
                raise
            assert (destination / 'search-1/jdk/bin/java-link').read_bytes() == b'jdk'
        else:
            with pytest.raises(ValueError):
                release._unpack_tree(str(path), 'search-1/bin/search', str(destination))
