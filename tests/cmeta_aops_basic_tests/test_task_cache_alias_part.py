"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The extra part of a cache entry's alias is one name (2026-11-26). A task names its entries after its parameters
(cache_extra_alias: "{{params.name}}--{{params.checkout}}" of clone-git-to-cache), and a checkout such as
"max/v26.7.0" or "release/2.12" made the entry a NESTED folder (task--clone-git-to-cache--<name>--max/v26.7.0--<UID>).
What would split the alias into folders, or is refused in a file name on some system, becomes "-": the helper on its
own, and end to end with a synthetic task in the throwaway home - the entry is one folder of the cache, found again
by the same request, and removed.
"""

import importlib.util
import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TASK = 'test-cache-alias-part'

TASK_DESC = '''authors: cMeta tests
cache: True
cache_params:
  - name
  - checkout
cache_extra_alias: '{{params.name}}--{{params.checkout}}'
'''

TASK_API = '''"""A synthetic task for the test of a cache entry's alias (cmeta-aops tests): it writes one file."""
import os

from task_c36be4b9314a45e0.api.ctask import InitCTask


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def run(self, ctx: dict, name: str = 'thing', checkout: str = None, **kwargs):
        with open(os.path.join(os.getcwd(), 'made.txt'), 'w') as f:
            f.write(f'{name} {checkout}')
        return {'return': 0, 'where': os.getcwd()}
'''


@pytest.mark.parametrize('engine', ['v2.py', 'v1.py'])
def test_what_splits_a_name_becomes_a_dash(engine):
    spec = importlib.util.spec_from_file_location('task_engine_alias_' + engine[:2], REPO_ROOT / 'category' / 'task' / 'api' / engine)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    part = module.alias_part

    assert part('src-modular--max/v26.7.0') == 'src-modular--max-v26.7.0'
    assert part('src-pytorch--release/2.12') == 'src-pytorch--release-2.12'
    assert part('org\\name:tag') == 'org-name-tag' and part('a//b') == 'a-b' and part('what?<x>|"y"*') == 'what-x-y-'

    # a name without such characters is as it was
    for same in ('src-pytorch--v2.15.0', 'llama-3.2-1b_q4', 'a.b+c@d', ''):
        assert part(same) == same
    assert part(None) == 'None'

    # where the alias of a new entry is put together
    src = (REPO_ROOT / 'category' / 'task' / 'api' / engine).read_text(encoding = 'utf-8')
    assert 'cache_sep + alias_part(cache_extra_alias)' in src


@pytest.fixture(scope = 'module')
def task(cm):
    """The synthetic task in the throwaway home of the session (the conftest made it and plugged this repo)."""
    r = cm.access({'category': 'task', 'command': 'find', 'arg1': TASK, 'con': False})
    if r['return'] == 16:
        r = cm.access({'category': 'task', 'command': 'create', 'arg1': f'local:{TASK}',
                       'meta': {'desc': 'a synthetic task for the test of the alias of a cache entry'}, 'con': False})
        assert r['return'] == 0, r.get('error')
        folder = pathlib.Path(r['path'])
        (folder / '_desc.yaml').write_text(TASK_DESC, encoding = 'utf-8')
        (folder / 'api_v1.py').write_text(TASK_API, encoding = 'utf-8')
    yield TASK
    for a in entries(cm):
        cm.access({'category': 'cache', 'command': 'delete', 'arg1': '*:' + a['cmeta_ref_parts']['artifact_uid'],
                   'force': True, 'con': False})


def entries(cm):
    r = cm.access({'category': 'cache', 'command': 'find', 'tags': TASK, 'con': False})
    assert r['return'] in (0, 16), r.get('error')
    return r.get('artifacts', []) if r['return'] == 0 else []


def test_a_checkout_with_a_slash_is_one_folder_of_the_cache(cm, task):
    r = cm.access({'category': 'task', 'command': 'run', 'arg1': task, 'name': 'src-x', 'checkout': 'max/v26.7.0',
                   'con': False, 'quiet': True})
    assert r['return'] == 0, r.get('error')

    found = entries(cm)
    assert len(found) == 1
    entry = pathlib.Path(found[0]['path'])
    alias = found[0]['cmeta_ref_parts']['artifact_alias']

    # one name: no folder inside a folder, the slash a dash
    assert '/' not in alias and '\\' not in alias and 'src-x--max-v26.7.0' in alias
    assert entry.name.startswith('task--' + task + '--src-x--max-v26.7.0--') and (entry / 'made.txt').is_file()
    assert entry.parent.name == 'cache'

    # the same request finds the same entry; another checkout gets its own
    again = cm.access({'category': 'task', 'command': 'run', 'arg1': task, 'name': 'src-x', 'checkout': 'max/v26.7.0',
                       'con': False, 'quiet': True})
    assert again['return'] == 0 and len(entries(cm)) == 1
    other = cm.access({'category': 'task', 'command': 'run', 'arg1': task, 'name': 'src-x', 'checkout': 'release/2.12',
                       'con': False, 'quiet': True})
    assert other['return'] == 0
    names = sorted(pathlib.Path(a['path']).name.rsplit('--', 1)[0] for a in entries(cm))
    assert names == ['task--' + task + '--src-x--max-v26.7.0', 'task--' + task + '--src-x--release-2.12']

    # and each is removed as one artifact
    for a in entries(cm):
        r = cm.access({'category': 'cache', 'command': 'delete', 'arg1': '*:' + a['cmeta_ref_parts']['artifact_uid'],
                       'force': True, 'con': False})
        assert r['return'] == 0, r.get('error')
        assert not os.path.isdir(a['path'])
    assert entries(cm) == []
