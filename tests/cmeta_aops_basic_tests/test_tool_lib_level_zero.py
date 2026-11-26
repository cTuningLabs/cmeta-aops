"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/lib-level-zero: Intel's Level Zero SDK for Windows (the headers, ze_loader.lib), what the launcher of Triton's Intel
backend links on Windows (2026-11-26: "ze_loader.lib" missing on a laptop's Intel GPU). Offline: the pin of the default
version, the unpacking of a zip that keeps every file inside, an installation's features.
"""

import json
import os
import pathlib
import zipfile

import pytest
import yaml

TOOL = pathlib.Path(__file__).resolve().parents[2] / 'tool' / 'lib-level-zero'


@pytest.fixture(scope = 'module')
def mod():
    src = (TOOL / 'api_v1.py').read_text(encoding = 'utf-8')
    for line, replacement in {'from tool_c393ba5c6fa14f66.api.ctool import InitCTool': 'class InitCTool: pass',
                              'from tool_c393ba5c6fa14f66.api.common_release import _sha256, default_version': '_sha256 = default_version = None',
                              'from tool_c393ba5c6fa14f66.api.common_static_lib import download': 'download = None'}.items():
        assert line in src
        src = src.replace(line, replacement)
    ns = {'__name__': 'lib_level_zero_under_test', '__file__': str(TOOL / 'api_v1.py')}
    exec(compile(src, str(TOOL / 'api_v1.py'), 'exec'), ns)
    return ns


def test_the_default_version_is_pinned(mod):
    desc = yaml.safe_load((TOOL / '_desc.yaml').read_text(encoding = 'utf-8'))
    version = desc['default_version']
    sha = mod['SDK']['sha256'].get(version, '')
    assert len(sha) == 64 and all(c in '0123456789abcdef' for c in sha)
    assert mod['SDK']['url'].format(version = version).endswith(f'/v{version}/level-zero-win-sdk-{version}.zip')


def test_unpack_keeps_every_file_inside(mod, tmp_path):
    archive = tmp_path / 'sdk.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('include/level_zero/ze_api.h', '/* ze */')
        z.writestr('lib/ze_loader.lib', 'lib')
        z.writestr('../outside.txt', 'no')
        z.writestr('/absolute.txt', 'no')
    dest = tmp_path / 'install'
    dest.mkdir()
    mod['unpack'](str(archive), str(dest))
    assert (dest / 'include' / 'level_zero' / 'ze_api.h').is_file()
    assert (dest / 'lib' / 'ze_loader.lib').is_file()
    assert not (tmp_path / 'outside.txt').exists() and not (dest / 'absolute.txt').exists()


def test_the_features_of_an_installation(mod, tmp_path):
    install = tmp_path / 'install'
    header = install / 'include' / 'level_zero' / 'ze_api.h'
    header.parent.mkdir(parents = True)
    header.write_text('/* ze */')
    (install / 'lib').mkdir()
    (install / '_source.json').write_text(json.dumps({'version': '1.36.0'}))

    class Cm:
        @staticmethod
        def q(path):
            return '"' + path + '"'

    tool = mod['CTool'].__new__(mod['CTool'])
    tool.cm = Cm()
    r = tool.detect_versions({}, [str(header)])
    found = r['found_paths_with_versions'][str(header)]
    assert found['output'] == '1.36.0'
    assert found['features']['paths']['root'] == str(install)       # what LEVEL_ZERO_V1_SDK_PATH names
    assert found['features']['paths']['lib'] == os.path.join(str(install), 'lib')
    assert found['features']['lib_names'] == ['ze_loader']
