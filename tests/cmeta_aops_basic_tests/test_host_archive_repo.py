"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A host kept in an archive repository ("archive: true" in its _cmr.yaml) is out of every fleet selection, listing and
page, and still found when named exactly (2026-11-02).
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def host_module():
    spec = importlib.util.spec_from_file_location('archive_host_test', ROOT / 'category/host/api/v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(tmp_path, name, archive):
    root = tmp_path / name
    (root / 'host' / ('vm-' + name)).mkdir(parents=True)
    (root / '_cmr.yaml').write_text('artifact: %s,0000000000000000\n' % name + ('archive: true\n' if archive else ''),
                                    encoding='utf-8')
    return {'path': str(root / 'host' / ('vm-' + name)), 'cmeta': {}}


def _category(module, artifacts):
    category = module.Category.__new__(module.Category)
    category._host_cache = {}
    category._prepare_input_from_ctx = lambda ctx, base=True: {'category': 'host,uid'}
    category.cm = SimpleNamespace(access=lambda p: {'return': 0, 'artifacts': artifacts})
    category._load_host = lambda a: {'alias': Path(a['path']).name, 'machine': None, 'type': 'ssh'}
    category._read_yaml = lambda path: {'archive': True} if 'archive: true' in Path(path).read_text(encoding='utf-8') else {}
    return category


def test_a_listing_skips_the_hosts_of_an_archive_repository(tmp_path):
    module = host_module()
    category = _category(module, [_repo(tmp_path, 'live', False), _repo(tmp_path, 'arc', True)])
    r = category._select({}, None)
    assert r['return'] == 0 and [h['alias'] for h in r['hosts']] == ['vm-live']
    r = category._select({}, 'vm-*')
    assert [h['alias'] for h in r['hosts']] == ['vm-live']


def test_an_archived_host_named_exactly_is_still_found(tmp_path):
    module = host_module()
    category = _category(module, [_repo(tmp_path, 'arc', True)])
    r = category._select({}, 'vm-arc')
    assert r['return'] == 0 and [h['alias'] for h in r['hosts']] == ['vm-arc']


def test_a_repository_without_the_flag_changes_nothing(tmp_path):
    module = host_module()
    category = _category(module, [_repo(tmp_path, 'one', False), _repo(tmp_path, 'two', False)])
    assert [h['alias'] for h in category._select({}, None)['hosts']] == ['vm-one', 'vm-two']
