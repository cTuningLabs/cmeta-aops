"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Which usable cache entry a request takes when several match. The order is the one it always was - the highest
version, then the priority, then the path (or the `sort_keys` of the task) - and what is new comes after it:
among the entries that are still equal, the one made last is first, on every machine. Before, such a tie fell
to the alias, which ends in a random UID, so one machine took the older entry and another the newer one.

The entries are made with chosen aliases, so that every test tells the new rule from the old one for certain:
the entry the alias would have put first is the one that must NOT be taken. A quiet run says in one line when
the time of creation decided; a run that asks says that equal entries are listed newest first; `--con-` stays
silent.
"""

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

TASK = 'test-cache-order'              # the default order: version, priority, path
TASK_KEYS = 'test-cache-order-keys'    # a task with `sort_keys` of its own, as clone-git has them

RESULT = 'cmeta-task-cached-result.json'
CONST = {'compute': ['cpu']}           # the constant match parameter the synthetic tasks add

TASK_DESC = '''authors: Grigori Fursin

cache: True

cache_params:
  - name
  - "@version"
'''

TASK_KEYS_DESC = '''authors: Grigori Fursin

cache: True

cache_params:
  - name
  - "@version"
  - tag

sort_keys:
  - 'cmeta.params.name'
  - '@cmeta.params.version-'
  - 'cmeta.params.tag-'
'''

TASK_API = '''"""A synthetic cached task for the tests of the selection among cache entries (cmeta-aops tests)."""

from task_c36be4b9314a45e0.api.ctask import InitCTask


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def customize_cache_artifact(self, ctx, cache_alias_template, cache_extra_alias, cache_meta, cache_tags, cache_params, uparams, cache_features = None):
        cache_meta['params'].setdefault('with', {})['compute'] = ['cpu']

        return {'return': 0}

    def run(self, ctx: dict, name: str = 'thing', version: str = None, tag: str = None, **kwargs):
        resolved = version if version else '9.9'

        return {'return': 0, 'made': 'by a run', '_update_params': {'version': resolved}}
'''


@pytest.fixture(scope='module')
def home(cm):
    """The throwaway home of the session (the conftest made it and plugged this repo), with the two synthetic tasks."""
    for task, desc in ((TASK, TASK_DESC), (TASK_KEYS, TASK_KEYS_DESC)):
        r = cm.access({'category': 'task', 'command': 'find', 'arg1': task, 'con': False})

        if r['return'] == 16:
            r = cm.access({'category': 'task', 'command': 'create', 'arg1': f'local:{task}',
                           'meta': {'desc': 'a synthetic task for the cache selection tests'}, 'con': False})
            assert r['return'] == 0, r.get('error')

            folder = pathlib.Path(r['path'])
            (folder / '_desc.yaml').write_text(desc, encoding='utf-8')
            (folder / 'api_v1.py').write_text(TASK_API, encoding='utf-8')

    return pathlib.Path(os.environ['CMETA_HOME'])


@pytest.fixture(autouse=True)
def clean_entries(cm, home):
    """Every test starts without entries of the synthetic tasks and leaves none."""
    remove_entries(cm)
    yield
    remove_entries(cm)


def entries(cm, task=TASK):
    r = cm.access({'category': 'cache', 'command': 'find', 'tags': task, 'con': False})
    assert r['return'] in (0, 16), r.get('error')

    return r.get('artifacts', []) if r['return'] == 0 else []


def remove_entries(cm):
    for task in (TASK, TASK_KEYS):
        for a in entries(cm, task):
            r = cm.access({'category': 'cache', 'command': 'delete', 'arg1': '*:' + a['cmeta_ref_parts']['artifact_uid'],
                           'force': True, 'con': False})
            assert r['return'] == 0, r.get('error')


def usable_entry(cm, suffix, made, task=TASK, **params):
    """
    A usable entry of the task with a chosen alias (`task--<task>--<suffix>`; the aliases the task engine makes
    end in a random UID) and a result that says which entry it is (`made`). A pause follows, so that the next
    entry is newer on every clock (Windows before Python 3.13 ticks every 15 ms).
    """
    r = cm.access({'category': 'task', 'command': 'find', 'arg1': task, 'con': False})
    assert r['return'] == 0 and len(r['artifacts']) == 1, r.get('error')

    parts = r['artifacts'][0]['cmeta_ref_parts']
    cref = {'category_alias': 'task', 'category_uid': parts['category_uid'],
            'artifact_alias': parts['artifact_alias'], 'artifact_uid': parts['artifact_uid']}

    entry_params = dict(params)
    entry_params.setdefault('with', CONST)

    r = cm.access({'category': 'cache', 'command': 'create', 'arg1': f'local:task--{task}--{suffix}',
                   'tags': ['task', parts['category_uid'], parts['artifact_alias'], parts['artifact_uid']],
                   'meta': {'cref': cref, 'params': entry_params}, 'con': False})
    assert r['return'] == 0, r.get('error')

    with open(os.path.join(r['path'], RESULT), 'w', encoding='utf-8') as f:
        json.dump({'return': 0, 'made': made}, f)

    time.sleep(0.05)

    return r


def run(cm, task=TASK, **params):
    """The synthetic task through the engine, in this process, quietly."""
    ii = {'category': 'task', 'command': 'run', 'arg1': task, 'con': False, 'quiet': True}
    ii.update(params)

    return cm.access(ii)


def cli(args, task=TASK):
    """`cx task run <task> <args>` in another process on the same home, without a terminal."""
    env = {k: v for k, v in os.environ.items() if k not in ('CMETA_LOCK_TIMEOUT', 'CMETA_CACHE_WAIT_TIMEOUT')}
    env['PYTHONIOENCODING'] = 'utf-8'

    p = subprocess.run([sys.executable, '-m', 'cmeta', 'task', 'run', task] + list(args), env=env,
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)

    return p.returncode, p.stdout.decode('utf-8', 'replace')


def without_time_of_creation(cm, entry):
    """The entry as an artifact that never recorded when it was made (its meta file rewritten, the index refreshed)."""
    meta_file = pathlib.Path(entry['path']) / '_cmeta.json'

    meta = json.loads(meta_file.read_text(encoding='utf-8'))
    meta.pop('creation_timestamp', None)
    meta_file.write_text(json.dumps(meta, indent=2), encoding='utf-8')

    r = cm.access({'category': 'cache', 'command': 'reindex', 'con': False})
    assert r['return'] in (0, 16), r.get('error')


def test_of_equal_entries_the_one_made_last_is_taken_whatever_their_aliases(cm, home):
    # The older entry has the alias that sorts first: the rule before took it
    usable_entry(cm, 'aaaa', 'older', name='kappa', version='11')
    usable_entry(cm, 'zzzz', 'newer', name='kappa', version='11')

    r = run(cm, name='kappa', version='11')
    assert r['return'] == 0 and r['made'] == 'newer', r

    # The other way round: the newer entry is also the first by alias
    remove_entries(cm)
    usable_entry(cm, 'zzzz', 'older', name='kappa', version='11')
    usable_entry(cm, 'aaaa', 'newer', name='kappa', version='11')

    r = run(cm, name='kappa', version='11')
    assert r['return'] == 0 and r['made'] == 'newer', r

    # The selection changed nothing: both entries are there, with their results
    found = entries(cm)
    assert sorted(json.loads((pathlib.Path(a['path']) / RESULT).read_text())['made'] for a in found) == ['newer', 'older']


def test_after_a_run_with_new_the_next_request_takes_the_new_entry(cm, home):
    """The entries as the task engine makes them: `--new` leaves a second one of the same configuration."""
    for trial in range(4):
        remove_entries(cm)

        assert run(cm, name='lambda', version='12')['return'] == 0
        time.sleep(0.05)
        assert run(cm, name='lambda', version='12', new=True)['return'] == 0

        found = sorted(entries(cm), key=lambda a: a['cmeta']['creation_timestamp'])
        assert len(found) == 2, [a['path'] for a in found]

        # Each result says which of the two it is
        for a, made in zip(found, ('older', 'newer')):
            result_file = pathlib.Path(a['path']) / RESULT
            result = json.loads(result_file.read_text(encoding='utf-8'))
            result['made'] = made
            result_file.write_text(json.dumps(result), encoding='utf-8')

        r = run(cm, name='lambda', version='12')
        assert r['return'] == 0 and r['made'] == 'newer', (trial, r, [a['path'] for a in found])


def test_version_priority_and_path_come_before_the_time_of_creation(cm, home):
    # The highest version, although its entry is the oldest and the last by alias
    usable_entry(cm, 'zz-v3', 'version 3', name='mu', version='3')
    usable_entry(cm, 'aa-v2', 'version 2', name='mu', version='2')

    r = run(cm, name='mu')
    assert r['return'] == 0 and r['made'] == 'version 3', r

    # The same version: an entry with a priority comes before the ones without, although it is older
    remove_entries(cm)
    usable_entry(cm, 'zz-priority', 'with a priority', name='mu', version='3', priority=1)
    usable_entry(cm, 'aa-plain', 'plain', name='mu', version='3')

    r = run(cm, name='mu')
    assert r['return'] == 0 and r['made'] == 'with a priority', r

    # The same version and no priority: the path decides (the first in the alphabet), although its entry is older
    remove_entries(cm)
    usable_entry(cm, 'zz-path-a', 'path a', name='mu', version='3', path='a')
    usable_entry(cm, 'aa-path-b', 'path b', name='mu', version='3', path='b')

    r = run(cm, name='mu')
    assert r['return'] == 0 and r['made'] == 'path a', r


def test_the_sort_keys_of_a_task_are_kept_and_the_time_decides_after_them(cm, home):
    # `cmeta.params.tag-`: the last tag in the alphabet first, although its entry is older and last by alias
    usable_entry(cm, 'zz-tag-y', 'tag y', task=TASK_KEYS, name='nu', version='1', tag='y')
    usable_entry(cm, 'aa-tag-x', 'tag x', task=TASK_KEYS, name='nu', version='1', tag='x')

    r = run(cm, task=TASK_KEYS, name='nu')
    assert r['return'] == 0 and r['made'] == 'tag y', r

    # Equal on the task's keys: the one made last
    remove_entries(cm)
    usable_entry(cm, 'aaaa', 'older', task=TASK_KEYS, name='nu', version='1', tag='x')
    usable_entry(cm, 'zzzz', 'newer', task=TASK_KEYS, name='nu', version='1', tag='x')

    r = run(cm, task=TASK_KEYS, name='nu')
    assert r['return'] == 0 and r['made'] == 'newer', r


def test_a_quiet_selection_that_the_time_decided_says_so_in_one_line(cm, home):
    usable_entry(cm, 'aaaa', 'older', name='xi', version='5')
    usable_entry(cm, 'zzzz', 'newer', name='xi', version='5')

    rc, out = cli(['--name=xi', '--version=5', '--quiet'])
    assert rc == 0, out

    notes = [line.strip() for line in out.splitlines() if line.strip().startswith('NOTE:')]
    assert len(notes) == 1, out
    assert notes[0].startswith(f'NOTE: 2 cache entries have the same version, priority, path: '
                               f'the newest is used - task--{TASK}--zzzz, made 20'), notes[0]
    assert 'Quietly selected: 0' in out

    # Without the console nothing is printed, and the same entry is taken
    rc, out = cli(['--name=xi', '--version=5', '--quiet', '--con-'])
    assert rc == 0 and 'NOTE:' not in out, out

    r = run(cm, name='xi', version='5')
    assert r['return'] == 0 and r['made'] == 'newer', r

    # Entries that differ in their version are not equal: the highest is taken, without the line
    remove_entries(cm)
    usable_entry(cm, 'aaaa', 'version 5', name='xi', version='5')
    usable_entry(cm, 'zzzz', 'version 6', name='xi', version='6')

    rc, out = cli(['--name=xi', '--quiet'])
    assert rc == 0 and 'NOTE:' not in out and 'Quietly selected: 0' in out, out


def test_a_run_that_asks_says_that_equal_entries_are_listed_newest_first(cm, home):
    usable_entry(cm, 'aaaa', 'older', name='omicron', version='7')
    usable_entry(cm, 'zzzz', 'newer', name='omicron', version='7')

    # Nobody answers (no terminal): the list is printed, the newer entry is number 0, the run ends with the notice
    rc, out = cli(['--name=omicron', '--version=7'])
    assert rc != 0, out
    assert 'entries with the same version, priority, path are listed newest first' in out, out
    assert out.index(f'0) task--{TASK}--zzzz') < out.index(f'1) task--{TASK}--aaaa'), out

    # No equal entries, no such words
    remove_entries(cm)
    usable_entry(cm, 'aaaa', 'version 7', name='omicron', version='7')
    usable_entry(cm, 'zzzz', 'version 8', name='omicron', version='8')

    rc, out = cli(['--name=omicron'])
    assert rc != 0 and 'listed newest first' not in out, out


def test_entries_without_a_time_of_creation_come_last_in_the_order_of_their_names(cm, home):
    first = usable_entry(cm, 'aaaa', 'no time, first by name', name='pi', version='9')
    second = usable_entry(cm, 'mmmm', 'no time, second by name', name='pi', version='9')

    without_time_of_creation(cm, first)
    without_time_of_creation(cm, second)

    # Both without a time: the first by name, as before - and the line of a quiet run says so
    r = run(cm, name='pi', version='9')
    assert r['return'] == 0 and r['made'] == 'no time, first by name', r

    rc, out = cli(['--name=pi', '--version=9', '--quiet'])
    assert rc == 0, out
    assert f'no time of creation on record: the first by name is used - task--{TASK}--aaaa' in out, out

    # An entry that has a time comes before them, whatever its name
    usable_entry(cm, 'zzzz', 'with a time', name='pi', version='9')

    r = run(cm, name='pi', version='9')
    assert r['return'] == 0 and r['made'] == 'with a time', r
