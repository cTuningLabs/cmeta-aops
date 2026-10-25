"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""
from pathlib import Path
import io
import threading
import uuid

import pytest


def definition(cm, tmp_path, **extra):
    name = 'test-sync-' + uuid.uuid4().hex[:8]
    r = cm.access({'category': 'sync', 'command': 'get', 'arg1': 'local:' + name})
    assert r['return'] == 0, r
    desc = {'source': {'path': str(tmp_path / 'a')},
            'destination': {'path': str(tmp_path / 'b')}, **extra}
    r = cm.utils.files.safe_write_file(str(Path(r['artifact']['path']) / '_desc.yaml'), desc)
    assert r['return'] == 0
    return name


def run(cm, name, **extra):
    return cm.access({'category': 'task', 'command': 'run', 'arg1': 'sync',
                      'name': name, 'plan': True, 'quiet': True, **extra})


def test_list_and_category_wrapper(cm, tmp_path):
    name = definition(cm, tmp_path)
    listed = cm.access({'category': 'task', 'command': 'run', 'arg1': 'sync', 'con': True})
    assert listed['return'] == 0
    assert any(a['cmeta_ref_parts']['artifact_alias'] == name for a in listed['syncs'])
    r = cm.access({'category': 'sync', 'command': 'run', 'arg1': name, 'plan': True})
    assert r['return'] == 0, r
    assert r['plans'][0]['mode'] == 'bisync'
    assert not Path(tmp_path / 'b').exists()


@pytest.mark.parametrize('extra,message', [
    ({'mode': 'bisycn'}, 'mode must be'),
    ({'repo': ['local']}, 'unknown sync'),
    ({'repos': []}, 'nonempty list'),
    ({'dirs': ['../escape']}, 'without ..'),
    ({'repos': ['local'], 'dirs': ['src']}, 'not both'),
    ({'exclude': '*.tmp'}, 'exclude must be'),
    ({'repos': ['local'], 'exclude_categories': 'log'}, 'exclude_categories must be'),
    ({'exclude_categories': ['log']}, 'exclude_categories requires repos'),
    ({'repos': ['local'], 'exclude_categories': ['../log']}, 'literal category'),
    ({'repos': ['local'], 'exclude_categories': ['config/default']}, 'literal category'),
    ({'repos': ['local'], 'exclude_categories': ['lo*']}, 'literal category'),
    ({'repos': ['local'], 'exclude_categories': [None]}, 'literal category'),
    ({'max_delete': 101}, 'max_delete'),
    ({'resync_mode': 'newst'}, 'resync_mode'),
    ({'initial_mode': 'miror'}, 'initial_mode'),
    ({'mode': 'copy', 'initial_mode': 'mirror'}, 'requires bisync'),
    ({'initial_max_delete': -1}, 'initial_max_delete'),
    ({'remove_empty_dirs': 'yes'}, 'must be a boolean'),
    ({'mode': 'copy', 'remove_empty_dirs': True}, 'only for bisync'),
])
def test_bad_definitions_fail_before_effects(cm, tmp_path, extra, message):
    r = run(cm, definition(cm, tmp_path, **extra))
    assert r['return'] != 0
    assert message in r['error']
    assert not (tmp_path / 'b').exists()


def test_overlap_and_filtered_nested_home(cm, tmp_path):
    nested = tmp_path / 'a/repos/fgg/project/CMETA'
    name = definition(cm, tmp_path, destination={'path': str(nested)})
    assert run(cm, name)['return'] != 0
    name = definition(cm, tmp_path, destination={'path': str(nested)}, repos=['local'])
    r = run(cm, name)
    assert r['return'] == 0, r
    assert r['plans'][0]['filters'][-2:] == ['+ /local/**', '- **']


def test_sequence_preserves_duplicates(cm, tmp_path):
    name = definition(cm, tmp_path)
    r = run(cm, None, names=[name, name])
    assert r['return'] == 0, r
    assert [p['alias'] for p in r['plans']] == [name, name]


def test_empty_directory_policy_is_opt_in_and_overridable(cm, tmp_path):
    name = definition(cm, tmp_path)
    assert run(cm, name)['plans'][0]['remove_empty_dirs'] is False
    assert run(cm, name, remove_empty_dirs=True)['plans'][0]['remove_empty_dirs'] is True
    name = definition(cm, tmp_path, remove_empty_dirs=True)
    assert run(cm, name)['plans'][0]['remove_empty_dirs'] is True
    assert run(cm, name, remove_empty_dirs=False)['plans'][0]['remove_empty_dirs'] is False
    name = definition(cm, tmp_path, mode='mirror')
    assert 'only for bisync' in run(cm, name, remove_empty_dirs=True)['error']


@pytest.mark.parametrize('repos,prefixes', [(['local', 'team'], ['local', 'team']), ('*', ['*'])])
def test_category_selection_and_display(cm, tmp_path, repos, prefixes, capsys):
    name = definition(cm, tmp_path, repos=repos, exclude_categories=['log', 'ctuning.user'])
    result = run(cm, name, con=True)
    assert result['return'] == 0, result
    plan = result['plans'][0]
    for prefix in prefixes:
        for category in ('log', 'ctuning.user'):
            assert '- /' + prefix + '/' + category + '/**' in plan['filters']
    paths = [str(tmp_path / 'a/repos' / p) for p in repos] if isinstance(repos, list) else [str(tmp_path / 'a/repos')]
    assert plan['source']['selected_paths'] == paths
    output = capsys.readouterr().out
    assert all(path in output for path in paths)


def test_linked_definitions_order_and_uid_rename(cm, tmp_path):
    child = definition(cm, tmp_path)
    found = cm.access({'category': 'sync', 'command': 'find', 'arg1': child})['artifacts'][0]
    uid = found['cmeta_ref_parts']['artifact_uid']
    parent = definition(cm, tmp_path, also=[child + ',' + uid, child + ',' + uid])
    renamed = child + '-renamed'
    moved = cm.access({'category': 'sync', 'command': 'move', 'arg1': child, 'arg2': renamed})
    assert moved['return'] == 0, moved
    result = run(cm, parent)
    assert result['return'] == 0, result
    assert [p['alias'] for p in result['plans']] == [parent, renamed, renamed]


@pytest.mark.parametrize('also', ['other', [None], ['']])
def test_invalid_linked_definitions(cm, tmp_path, also):
    result = run(cm, definition(cm, tmp_path, also=also))
    assert result['return'] != 0
    assert 'also must be a list' in result['error']


@pytest.mark.parametrize('indirect', [False, True])
def test_linked_cycle_fails_before_transfer(cm, tmp_path, indirect):
    parent = definition(cm, tmp_path)
    child = definition(cm, tmp_path, also=[parent]) if indirect else parent
    found = cm.access({'category': 'sync', 'command': 'find', 'arg1': parent})['artifacts'][0]
    desc = Path(found['path']) / '_desc.yaml'
    data = cm.utils.files.safe_read_file(str(desc))['data']
    data['also'] = [child]
    assert cm.utils.files.safe_write_file(str(desc), data)['return'] == 0
    result = run(cm, parent, plan=False)
    assert result['return'] != 0
    assert 'cycle in linked sync definitions' in result['error']
    assert not (tmp_path / 'b').exists()


def test_missing_link_fails_before_transfer(cm, tmp_path):
    parent = definition(cm, tmp_path, also=['missing-' + uuid.uuid4().hex])
    result = run(cm, parent, plan=False)
    assert result['return'] != 0
    assert not (tmp_path / 'b').exists()


def test_linked_execution_stops_after_failed_pair(cm, tmp_path, task_namespace, monkeypatch):
    first = definition(cm, tmp_path)
    second = definition(cm, tmp_path)
    parent = definition(cm, tmp_path, also=[first, second])
    calls = []

    def execute(self, ctx, plan, *args, **kwargs):
        calls.append(plan['alias'])
        if plan['alias'] == first:
            raise ValueError('first child failed')
        return {'status': 'ok'}

    cls = task_namespace('sync')['CTask']
    task = cls.__new__(cls)
    task.cm = cm
    task.definition = lambda ctx, ref: dict(alias=ref, uid=ref, also=[first, second] if ref == parent else [])
    monkeypatch.setattr(cls, 'execute', execute)
    result = task.run({'control': {}}, name=parent)
    assert result['return'] != 0 and 'first child failed' in result['error']
    assert calls == [parent, first]


def test_empty_category_exclusions_keep_original_filters(cm, tmp_path):
    old = run(cm, definition(cm, tmp_path, repos=['local']))['plans'][0]
    new = run(cm, definition(cm, tmp_path, repos=['local'], exclude_categories=[]))['plans'][0]
    assert new['filters'] == old['filters']
    assert not any('/log/' in f for f in new['filters'])


def test_source_bootstrap_plan_and_default(cm, tmp_path):
    old = run(cm, definition(cm, tmp_path))['plans'][0]
    assert old['initial_mode'] == 'merge'
    new = run(cm, definition(cm, tmp_path, initial_mode='mirror', initial_max_delete=12))['plans'][0]
    assert new['initial_mode'] == 'mirror'
    assert new['initial_max_delete'] == 12


def test_reference_path_traversal(cm, tmp_path):
    name = definition(cm, tmp_path, source={'cref': 'sync::x/../escape'})
    r = run(cm, name)
    assert r['return'] != 0


@pytest.mark.parametrize('flags', [dict(initialize=True, require_initialized=True),
                                  dict(migrate_state=True, initialize=True)])
def test_incompatible_state_actions(cm, tmp_path, flags):
    result = run(cm, definition(cm, tmp_path), **flags)
    assert result['return'] != 0


def test_regular_bisync_requires_success_without_creating_destination(cm, tmp_path):
    name = definition(cm, tmp_path, initial_mode='mirror')
    result = run(cm, name, plan=False, require_initialized=True)
    assert result['return'] != 0
    assert 'successful bisync state is missing' in result['error']
    assert not (tmp_path / 'b').exists()


@pytest.mark.parametrize('fail', [False, True])
def test_live_log_arrives_before_command_finishes_and_drains_on_exit(task_namespace, tmp_path, monkeypatch, fail):
    follow_log = task_namespace('sync')['follow_log']
    log = tmp_path / 'run.log'
    log.write_bytes(b'previous stage\n')
    arrived = threading.Event()
    partial = threading.Event()

    class Terminal(io.StringIO):
        def write(self, text):
            result = super().write(text)
            if 'Copied: caf' in self.getvalue():
                partial.set()
            if 'Copied: caf\u00e9.txt\n' in self.getvalue():
                arrived.set()
            return result

    output = Terminal()
    monkeypatch.setattr('sys.stdout', output)
    message = 'Copied: caf\u00e9.txt\n'.encode('utf-8')
    try:
        with follow_log(log):
            with log.open('ab', buffering=0) as writer:
                # A file name can straddle two reads, even inside a UTF-8 character.
                split = message.index(b'\xc3') + 1
                writer.write(message[:split])
                assert partial.wait(5), 'no partial output while the command is active'
                writer.write(message[split:])
                assert arrived.wait(5), 'no output until command completion'
                writer.write(b'final action without newline')
                if fail:
                    raise ValueError('command failed')
    except ValueError as exc:
        assert fail and str(exc) == 'command failed'
    expected = message.decode('utf-8') + 'final action without newline'
    assert output.getvalue() == expected
    assert log.read_bytes() == b'previous stage\n' + expected.encode('utf-8')
    # Joining on both success and failure prevents output leaking into later stages.
    with log.open('ab') as writer:
        writer.write(b'\nafter command')
    assert output.getvalue() == expected


def test_identity_ignores_the_built_in_filters(cm, tmp_path, task_namespace):
    """A pair's identity is its mode, endpoints and the definition's own filters; a built-in state filter added by a
    release changes neither the identity nor the acceptance of a state digested before (0.55.0.1 broke every pair)."""
    name = definition(cm, tmp_path, repos=['local'])
    plan = run(cm, name)['plans'][0]
    ns = task_namespace('sync')
    built_in = len(plan['filters']) - len(plan['own_filters'])
    assert built_in >= 4 and plan['own_filters'] == plan['filters'][built_in:]
    assert '- **/result/sync-backup--*/**' in plan['filters'] and '- **/result/sync-backup--*/**' not in plan['own_filters']
    identity, digest, legacy = ns['identity_digests'](plan)
    assert identity['filters'] == plan['own_filters'] and digest != legacy
    # the digest a state of 0.55.0 carried: the three built-ins of that time in front of the definition's own filters
    old = dict(identity, filters=ns['LEGACY_STATE_FILTERS'] + plan['own_filters'])
    import hashlib, json
    assert legacy == hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
    # a plan without own_filters (an older caller) digests its whole list
    _, whole, _ = ns['identity_digests'](dict(plan, own_filters=None) if False else {k: v for k, v in plan.items() if k != 'own_filters'})
    assert whole != digest


def test_a_backup_artifact_never_claims_the_pair(cm, tmp_path, task_namespace):
    """The backup result artifact of a pair carries backup_of, not sync_uid: find_state must see one state only."""
    name = definition(cm, tmp_path, repos=['local'])
    plan = run(cm, name)['plans'][0]
    uid = plan['uid']
    for alias, meta in (('sync--' + name + '--' + uid, {'permanent': True, 'tags': ['sync-state'], 'sync_uid': uid}),
                        ('sync-backup--' + name + '--' + uid, {'permanent': True, 'tags': ['sync-backup'], 'backup_of': uid})):
        r = cm.access({'category': 'result', 'command': 'get', 'arg1': 'local:' + alias, 'meta': meta, 'con': False})
        assert r['return'] == 0, r
    ns = task_namespace('sync')
    task = ns['CTask'].__new__(ns['CTask'])
    task.cm = cm
    task.cmeta = {'uses_categories': {'result': 'result,6567e4df4d04488a', 'cache': 'cache,1ebdcc1cc30c4022'}}
    found = task.find_state('result', uid)
    assert found and found['cmeta_ref_parts']['artifact_alias'] == 'sync--' + name + '--' + uid
