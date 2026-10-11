"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The cache entry of a run, end to end, with a synthetic task written into the throwaway home ("test-cache-retry":
its run "downloads" once, "builds", fails on demand, counts its attempts): a retry of the same configuration
resumes the same entry without a second download; the request's parameters replace the entry's; a different
configuration gets its own entry while the failed one stays; a failed, crashed or broken entry is never served
as a result; identical requests at once make one entry (the second waits and uses the result); `--new`,
`--update`, `--clean` as before; `cx cache show --state` / `clean --failed|--crashed|--broken`; a delete of a
running entry is refused - and after every step the invariants: the index equals the disk, one entry per
configuration, no lock or temporary files left, the results and parameters of usable entries untouched.
"""

import json
import os
import pathlib
import pickle
import shutil
import subprocess
import sys
import time

import pytest

TASK = 'test-cache-retry'
RESULT = 'cmeta-task-cached-result.json'
RUNNING = 'cmeta-task-running.json'
CONST = {'compute': ['cpu']}      # the constant match parameter the synthetic task adds (customize_cache_artifact)

TASK_DESC = '''authors: Grigori Fursin
cache: True
cache_params:
  - name
  - "@version"     # fuzzy, as task/setup asks for a tool's version: the requested version must still be part of the request record
  - flavor
'''

TASK_API = '''"""A synthetic task for the tests of the cache entry of a run (cmeta-aops tests): it "downloads" once (a 1 MB
file, counted), "builds" (a file), sleeps when asked (a kill from outside lands here), fails on demand for the
first N attempts, counts its attempts in the entry, and reports what it resumed."""
import os
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def customize_cache_artifact(self, ctx, cache_alias_template, cache_extra_alias, cache_meta, cache_tags, cache_params, uparams, cache_features = None):
        # a constant match parameter, as tool/llama-cpp adds through cache_meta_const: part of what the find of
        # the next request matches, not of the identity (cache_params) - it must survive in the entry's params
        cache_meta['params'].setdefault('with', {})['compute'] = ['cpu']
        return {'return': 0}

    def run(self,
            ctx: dict,
            name: str = 'thing',
            version: str = None,
            flavor: str = None,
            fail_at: str = 'never',      # download | build | never
            fail_times: int = 0,         # the first N attempts fail (at fail_at)
            sleep: float = 0.0,          # seconds of "build"
            payload_kb: int = 1024,
            **kwargs):

        work = os.getcwd()

        def count(fname):
            p = os.path.join(work, fname)
            n = int(open(p).read().strip()) + 1 if os.path.isfile(p) else 1
            with open(p, 'w') as f:
                f.write(str(n))
            return n

        attempt = count('attempts.txt')
        fail_times = int(fail_times or 0)
        resumed = ctx['tasks']['run_control'].get('cache_resumed')

        marker = os.path.join(work, 'downloaded.bin')
        if not os.path.isfile(marker):
            tmp = marker + '.part'
            with open(tmp, 'wb') as f:
                f.write(b'x' * (int(payload_kb) * 1024))
            os.replace(tmp, marker)
            count('downloads.txt')

        if fail_at == 'download' and attempt <= fail_times:
            return {'return': 1, 'error': f'download failed on purpose (attempt {attempt})'}

        if float(sleep or 0) > 0:
            with open(os.path.join(work, 'building.txt'), 'w') as f:
                f.write(str(os.getpid()))
            time.sleep(float(sleep))

        if fail_at == 'build' and attempt <= fail_times:
            return {'return': 1, 'error': f'build failed on purpose (attempt {attempt})'}

        with open(os.path.join(work, 'built.txt'), 'w') as f:
            f.write(f'{name} {version} {flavor} attempt {attempt}')

        # the version it ends up with is recorded in the entry, as a tool setup records the detected version
        # (an entry without a version would satisfy every fuzzy version request); "9.9" stands for the latest
        resolved = version if version else '9.9'
        return {'return': 0, 'attempt': attempt, 'resumed': resumed, 'built_version': resolved,
                '_update_params': {'built_version': resolved, 'version': resolved}}
'''


@pytest.fixture(scope='module')
def home(cm):
    """The throwaway home of the session (the conftest made it and plugged this repo), with the synthetic task."""
    home = pathlib.Path(os.environ['CMETA_HOME'])
    r = cm.access({'category': 'task', 'command': 'find', 'arg1': TASK, 'con': False})
    if r['return'] == 16:
        r = cm.access({'category': 'task', 'command': 'create', 'arg1': f'local:{TASK}',
                       'meta': {'desc': 'a synthetic task for the cache tests'}, 'con': False})
        assert r['return'] == 0, r.get('error')
        folder = pathlib.Path(r['path'])
        (folder / '_desc.yaml').write_text(TASK_DESC, encoding='utf-8')
        (folder / 'api_v1.py').write_text(TASK_API, encoding='utf-8')
    return home


@pytest.fixture(autouse=True)
def clean_entries(cm, home):
    """Every test starts without entries of the synthetic task and leaves none."""
    remove_entries(cm)
    yield
    remove_entries(cm)


def remove_entries(cm):
    for a in entries(cm):
        r = cm.access({'category': 'cache', 'command': 'delete', 'arg1': '*:' + a['cmeta_ref_parts']['artifact_uid'],
                       'force': True, 'con': False})
        assert r['return'] == 0, r.get('error')
        assert not os.path.isdir(a['path']), a['path']


def entries(cm):
    r = cm.access({'category': 'cache', 'command': 'find', 'tags': TASK, 'con': False})
    assert r['return'] in (0, 16), r.get('error')
    return r.get('artifacts', []) if r['return'] == 0 else []


def states(cm):
    r = cm.access({'category': 'cache', 'command': 'classify', 'tags': TASK, 'con': False})
    assert r['return'] == 0, r.get('error')
    return {uid: s['state'] for uid, s in r['states'].items()}


def legacy_entry(cm, suffix, params):
    """An unfinished entry as the task engine wrote it before the request record existed: the task's cref and
    tags, the parameters, the `tmp` tag and no `request_params`."""
    r = cm.access({'category': 'task', 'command': 'find', 'arg1': TASK, 'con': False})
    assert r['return'] == 0 and len(r['artifacts']) == 1, r.get('error')
    parts = r['artifacts'][0]['cmeta_ref_parts']
    cref = {'category_alias': 'task', 'category_uid': parts['category_uid'],
            'artifact_alias': parts['artifact_alias'], 'artifact_uid': parts['artifact_uid']}
    r = cm.access({'category': 'cache', 'command': 'create', 'arg1': f'local:task--{TASK}--{suffix}',
                   'tags': ['task', parts['category_uid'], parts['artifact_alias'], parts['artifact_uid'], 'tmp'],
                   'meta': {'cref': cref, 'params': params}, 'con': False})
    assert r['return'] == 0, r.get('error')
    return r


def run(cm, **params):
    """The synthetic task through the engine, in this process."""
    ii = {'category': 'task', 'command': 'run', 'arg1': TASK, 'con': False, 'quiet': True}
    ii.update(params)
    return cm.access(ii)


def env_for(**extra):
    env = {k: v for k, v in os.environ.items() if k not in ('CMETA_LOCK_TIMEOUT', 'CMETA_CACHE_WAIT_TIMEOUT')}
    env['PYTHONIOENCODING'] = 'utf-8'
    env.update(extra)
    return env


def start(args, **extra):
    """`cx task run test-cache-retry <args>` in another process on the same home."""
    return subprocess.Popen([sys.executable, '-m', 'cmeta', 'task', 'run', TASK, '--quiet'] + list(args),
                            env=env_for(**extra), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def finish(proc, timeout=600):
    out, _ = proc.communicate(timeout=timeout)
    return proc.returncode, out.decode('utf-8', 'replace')


def count_in(folder, fname):
    p = pathlib.Path(folder) / fname
    return int(p.read_text().strip()) if p.is_file() else 0


def wait_for(predicate, seconds=60, what='the condition'):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f'{what} did not happen in {seconds} s')


class Invariants:
    """I1 index == disk, I2 the number of entries, I3 no lock/tmp/running leftovers, I4 ok entries untouched."""

    def __init__(self, cm, home):
        self.cm = cm
        self.home = home
        self.cache_dir = home / 'repos' / 'local' / 'cache'
        self.snapshot = {}

    def remember_ok(self):
        self.snapshot = {}
        st = states(self.cm)
        for a in entries(self.cm):
            uid = a['cmeta_ref_parts']['artifact_uid']
            if st.get(uid) == 'ok':
                result_file = pathlib.Path(a['cmeta'].get('path') or a['path']) / RESULT
                self.snapshot[uid] = (result_file.read_bytes(), json.dumps(a['cmeta'].get('params', {}), sort_keys=True))

    def check(self, expected_entries=None, allow_crashed=False):
        # I1: every folder of the task has its record and every record its folder; a reindex changes nothing
        index_file = self.home / 'index' / 'cache.pkl'
        before = index_file.read_bytes() if index_file.is_file() else b''
        r = self.cm.access({'category': 'cache', 'command': 'reindex', 'con': False})
        assert r['return'] in (0, 16), r.get('error')
        after = index_file.read_bytes() if index_file.is_file() else b''
        if before:
            data_before = pickle.loads(before)
            data_after = pickle.loads(after)
            assert data_before['uids'].keys() == data_after['uids'].keys(), 'a reindex found other entries than the index had'
        found = entries(self.cm)
        folders = {p.name.lower() for p in self.cache_dir.iterdir() if p.is_dir() and p.name.startswith(f'task--{TASK}--')} if self.cache_dir.is_dir() else set()
        assert {os.path.basename(a['path']).lower() for a in found} == folders, (found, folders)
        # I2
        if expected_entries is not None:
            assert len(found) == expected_entries, [a['path'] for a in found]
        # I3: no lock files, no temporaries, no running file of a dead attempt
        leftovers = []
        if self.cache_dir.is_dir():
            for p in self.cache_dir.rglob('*'):
                if p.name.endswith('.lock') or p.name.endswith('.tmp') or p.name.endswith('.part'):
                    leftovers.append(str(p))
        assert leftovers == [], leftovers
        st = states(self.cm)
        for a in found:
            uid = a['cmeta_ref_parts']['artifact_uid']
            assert st[uid] != 'running', f'{a["path"]} is still running'
            if not allow_crashed:
                assert st[uid] != 'crashed', f'{a["path"]} is crashed'
                assert not (pathlib.Path(a['path']) / RUNNING).exists(), f'{a["path"]} keeps a running file'
        # I4: the usable entries of the snapshot are byte-identical
        for a in found:
            uid = a['cmeta_ref_parts']['artifact_uid']
            if uid in self.snapshot and st.get(uid) == 'ok':
                result_file = pathlib.Path(a['cmeta'].get('path') or a['path']) / RESULT
                assert (result_file.read_bytes(), json.dumps(a['cmeta'].get('params', {}), sort_keys=True)) == self.snapshot[uid], f'{a["path"]} changed'
        return found, st


@pytest.fixture()
def inv(cm, home):
    return Invariants(cm, home)


def test_a_retry_of_the_same_configuration_resumes_the_entry_without_a_second_download(cm, home, inv):
    r = run(cm, name='alpha', version='1', fail_at='build', fail_times=1)
    assert r['return'] == 1 and 'build failed on purpose' in r['error'], r
    found, st = inv.check(expected_entries=1)
    e = found[0]
    assert st[e['cmeta_ref_parts']['artifact_uid']] == 'failed'
    assert 'failed' in e['cmeta']['tags'] and 'tmp' not in e['cmeta']['tags']
    assert e['cmeta']['request_params'] == {'name': 'alpha', 'version': '1', 'with': CONST}
    assert count_in(e['path'], 'downloads.txt') == 1 and count_in(e['path'], 'attempts.txt') == 1

    # The same request again: resumed in place, no second download, the entry usable afterwards
    r = run(cm, name='alpha', version='1', fail_at='build', fail_times=1)
    assert r['return'] == 0, r.get('error')
    assert r['attempt'] == 2 and r['resumed']['state'] == 'failed', r
    found, st = inv.check(expected_entries=1)
    e = found[0]
    assert st[e['cmeta_ref_parts']['artifact_uid']] == 'ok'
    assert count_in(e['path'], 'downloads.txt') == 1 and count_in(e['path'], 'attempts.txt') == 2
    # the identity, the task's additions AND the constant match parameter (the find of the next request needs it)
    assert e['cmeta']['params'] == {'name': 'alpha', 'version': '1', 'built_version': '1', 'with': CONST}, e['cmeta']['params']
    assert e['cmeta']['tags'][-1:] != ['tmp'] and 'failed' not in e['cmeta']['tags']

    # A third request: the cached result, the task does not run
    inv.remember_ok()
    r = run(cm, name='alpha', version='1')
    assert r['return'] == 0 and r['attempt'] == 2, r
    found, st = inv.check(expected_entries=1)
    assert count_in(found[0]['path'], 'attempts.txt') == 2


def test_a_different_configuration_gets_its_own_entry_and_the_failed_one_stays(cm, home, inv):
    """The torchvision case: a failed attempt with an explicit version must not be the entry of a request
    without one, and its version must not leak into that request."""
    r = run(cm, name='beta', version='1', fail_at='download', fail_times=99)
    assert r['return'] == 1, r
    found, st = inv.check(expected_entries=1)
    failed_uid = found[0]['cmeta_ref_parts']['artifact_uid']
    assert st[failed_uid] == 'failed'

    r = run(cm, name='beta')             # no version: another configuration
    assert r['return'] == 0, r.get('error')
    assert r['built_version'] == '9.9' and r['attempt'] == 1 and r['resumed'] is None, r
    found, st = inv.check(expected_entries=2)
    by_uid = {a['cmeta_ref_parts']['artifact_uid']: a for a in found}
    assert st[failed_uid] == 'failed'
    new_uid = next(u for u in by_uid if u != failed_uid)
    assert st[new_uid] == 'ok'
    # the version of the failed attempt did not leak: the new entry carries the one it resolved itself
    assert by_uid[new_uid]['cmeta']['params']['version'] == '9.9', by_uid[new_uid]['cmeta']['params']
    assert by_uid[new_uid]['cmeta']['request_params'] == {'name': 'beta', 'with': CONST}
    assert by_uid[failed_uid]['cmeta']['request_params'] == {'name': 'beta', 'version': '1', 'with': CONST}

    # The explicit version resumes its own failed entry (and fails again as asked)
    r = run(cm, name='beta', version='1', fail_at='download', fail_times=99)
    assert r['return'] == 1 and 'attempt 2' in r['error'], r
    found, st = inv.check(expected_entries=2)
    assert st[failed_uid] == 'failed' and count_in(by_uid[failed_uid]['path'], 'downloads.txt') == 1

    # A failed entry is never served: a request for it runs the task
    r = run(cm, name='beta', version='1')
    assert r['return'] == 0 and r['attempt'] == 3 and r['resumed']['state'] == 'failed', r
    inv.check(expected_entries=2)


def test_a_legacy_unfinished_entry_without_the_record_is_resumed_by_the_subset_rule(cm, home, inv):
    # as the old engine wrote it: the request's params with the constant match parameter, plus a stale one
    legacy_entry(cm, 'legacy', {'name': 'gamma', 'version': '2', 'stale': 'x', 'with': CONST})
    found, st = inv.check(expected_entries=1, allow_crashed=True)
    assert list(st.values()) == ['crashed']

    r = run(cm, name='gamma', version='2')
    assert r['return'] == 0 and r['resumed']['state'] == 'crashed', r
    found, st = inv.check(expected_entries=1)
    e = found[0]
    assert st[e['cmeta_ref_parts']['artifact_uid']] == 'ok'
    assert 'stale' not in e['cmeta']['params'], 'the old parameters are replaced, not merged'
    assert e['cmeta']['params'] == {'name': 'gamma', 'version': '2', 'built_version': '2', 'with': CONST}


def test_broken_entries_are_resumed_not_served(cm, home, inv):
    r = run(cm, name='delta', version='3')
    assert r['return'] == 0 and r['attempt'] == 1, r
    found, st = inv.check(expected_entries=1)
    e = found[0]

    # The result file gone: broken -> the task runs again in the same entry
    os.remove(os.path.join(e['path'], RESULT))
    assert states(cm)[e['cmeta_ref_parts']['artifact_uid']] == 'broken'
    r = run(cm, name='delta', version='3')
    assert r['return'] == 0 and r['attempt'] == 2 and r['resumed']['state'] == 'broken', r
    found, st = inv.check(expected_entries=1)

    # A recorded tool path that is gone: broken -> resumed too
    r = cm.access({'category': 'cache', 'command': 'update', 'arg1': found[0]['cmeta_ref_parts']['artifact_uid'],
                   'meta': {'params': {'tool_path': str(home / 'no-such-tool')}}, 'con': False})
    assert r['return'] == 0, r.get('error')
    assert states(cm)[found[0]['cmeta_ref_parts']['artifact_uid']] == 'broken'
    r = run(cm, name='delta', version='3')
    assert r['return'] == 0 and r['attempt'] == 3 and r['resumed']['state'] == 'broken', r
    found, st = inv.check(expected_entries=1)
    assert 'tool_path' not in found[0]['cmeta']['params'], 'the replaced params carry no stale tool path'


def test_a_crashed_attempt_is_resumed(cm, home, inv):
    proc = start(['--name=eps', '--version=4', '--sleep=120'])
    try:
        wait_for(lambda: any((pathlib.Path(a['path']) / 'building.txt').is_file() for a in entries(cm)), 90, 'the build to start')
        found = entries(cm)
        assert len(found) == 1
        e = found[0]
        assert states(cm)[e['cmeta_ref_parts']['artifact_uid']] == 'running'
        assert (pathlib.Path(e['path']) / RUNNING).is_file()
    finally:
        proc.kill()
        proc.communicate()

    # Crashed: the running file of the dead process stays as evidence, the lock died with it
    wait_for(lambda: states(cm)[e['cmeta_ref_parts']['artifact_uid']] == 'crashed', 30, 'the entry to be crashed')
    found, st = inv.check(expected_entries=1, allow_crashed=True)
    running = json.loads((pathlib.Path(e['path']) / RUNNING).read_text())
    assert running['pid'] == proc.pid and running['task'] == TASK

    r = run(cm, name='eps', version='4')
    assert r['return'] == 0 and r['attempt'] == 2 and r['resumed']['state'] == 'crashed', r
    found, st = inv.check(expected_entries=1)
    assert count_in(found[0]['path'], 'downloads.txt') == 1
    assert not (pathlib.Path(found[0]['path']) / RUNNING).exists()


def test_identical_requests_at_once_make_one_entry_and_the_second_waits(cm, home, inv):
    first = start(['--name=zeta', '--version=5', '--sleep=6'])
    try:
        wait_for(lambda: any((pathlib.Path(a['path']) / 'building.txt').is_file() for a in entries(cm)), 90, 'the first build to start')
        second = start(['--name=zeta', '--version=5', '--sleep=6'])
        other = start(['--name=zeta', '--version=6'])          # another configuration: its own entry at once
        rc_other, out_other = finish(other, 120)
        assert rc_other == 0, out_other
        rc1, out1 = finish(first, 120)
        rc2, out2 = finish(second, 120)
    finally:
        for p in (first,):
            if p.poll() is None:
                p.kill(); p.communicate()
    assert rc1 == 0, out1
    assert rc2 == 0, out2
    assert 'waiting for it' in out2 or 'is locked by another process' in out2, out2

    found, st = inv.check(expected_entries=2)
    by_version = {a['cmeta']['params'].get('version'): a for a in found}
    assert set(by_version) == {'5', '6'}
    assert count_in(by_version['5']['path'], 'attempts.txt') == 1, 'the waiter used the result, it did not build'
    assert count_in(by_version['5']['path'], 'downloads.txt') == 1
    assert all(s == 'ok' for s in st.values())


def test_new_update_and_clean_as_before(cm, home, inv):
    r = run(cm, name='eta', version='7')
    assert r['return'] == 0 and r['attempt'] == 1
    found, st = inv.check(expected_entries=1)
    first_uid = found[0]['cmeta_ref_parts']['artifact_uid']

    # --update: the same entry rebuilt (an attempt in it), still one entry
    r = run(cm, name='eta', version='7', update=True)
    assert r['return'] == 0 and r['attempt'] == 2 and r['resumed']['state'] == 'ok', r
    found, st = inv.check(expected_entries=1)
    assert found[0]['cmeta_ref_parts']['artifact_uid'] == first_uid and st[first_uid] == 'ok'

    # --new: a second entry for the same configuration
    r = run(cm, name='eta', version='7', new=True)
    assert r['return'] == 0 and r['attempt'] == 1, r
    found, st = inv.check(expected_entries=2)
    assert all(s == 'ok' for s in st.values())


def test_show_and_clean_by_state(cm, home, inv):
    assert run(cm, name='theta', version='8')['return'] == 0
    assert run(cm, name='theta', version='9', fail_at='download', fail_times=99)['return'] == 1
    found, st = inv.check(expected_entries=2)
    failed_uid = next(u for u, s in st.items() if s == 'failed')
    ok_uid = next(u for u, s in st.items() if s == 'ok')

    r = cm.access({'category': 'cache', 'command': 'show', 'tags': TASK, 'state': 'failed', 'con': False})
    assert r['return'] == 0 and [a['cmeta_ref_parts']['artifact_uid'] for a in r['artifacts']] == [failed_uid]

    r = cm.access({'category': 'cache', 'command': 'clean', 'tags': TASK, 'con': False})     # crashed only: nothing
    assert r['return'] == 0 and r['removed'] == []
    r = cm.access({'category': 'cache', 'command': 'clean', 'tags': TASK, 'failed': True, 'con': False})
    assert r['return'] == 0 and r['removed'] == [failed_uid]
    found, st = inv.check(expected_entries=1)
    assert st == {ok_uid: 'ok'}


def test_a_running_entry_is_not_deleted_and_a_full_reindex_during_a_build_changes_nothing(cm, home, inv, monkeypatch):
    proc = start(['--name=iota', '--version=10', '--sleep=12'])
    try:
        wait_for(lambda: any((pathlib.Path(a['path']) / 'building.txt').is_file() for a in entries(cm)), 90, 'the build to start')
        e = entries(cm)[0]
        uid = e['cmeta_ref_parts']['artifact_uid']
        # A delete waits for the attempt (CMETA_LOCK_TIMEOUT, 30 s by default) and fails as a whole while it
        # goes on: record and folder stay (2 s here so that the 12 s build is still running)
        monkeypatch.setenv('CMETA_LOCK_TIMEOUT', '2')
        r = cm.access({'category': 'cache', 'command': 'delete', 'arg1': uid, 'force': True, 'con': False},
                      )
        monkeypatch.delenv('CMETA_LOCK_TIMEOUT', raising=False)
        assert r['return'] > 0 and 'locked by another process' in r['error'], r
        assert os.path.isdir(e['path'])
        r = cm.access({'category': 'cache', 'command': 'clean', 'tags': TASK, 'unfinished': True, 'con': False})
        assert r['return'] == 0 and r['removed'] == [] and uid in r['skipped']
        # A full reindex of the home while the build runs: the entry keeps its record
        r = cm.repos.reindex()
        assert r['return'] == 0, r.get('error')
        rc, out = finish(proc, 120)
    finally:
        if proc.poll() is None:
            proc.kill(); proc.communicate()
    assert rc == 0, out
    found, st = inv.check(expected_entries=1)
    assert st[uid] == 'ok'
