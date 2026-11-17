"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The command task/rclone-to-ssh gives rclone (offline: the command is built and handed to a stand-in for task/cmd):

- a two-way sync says which copy keeps the name when both sides changed a file: --conflict-resolve newer
  --conflict-loser num. rclone's own default renames BOTH copies (<name>.conflict1, <name>.conflict2) and the name is
  gone on both sides - a run that aborted after such renames left four files without their names on two machines
  (2026-11-17). With a winner the name stays and the other copy is kept beside it;
- rules_first: filter rules of the caller put before the blacklist and the whitelist, as they are - a file kept in a
  folder that is left out ("+ /work/x/!AI/log/*.running" before "- /work/x/**").
"""
import logging
import types

import pytest


class FakeCM:
    def __init__(self):
        self.calls = []
        self.utils = types.SimpleNamespace(files=types.SimpleNamespace(
            quote_path=lambda p: '"%s"' % p if ' ' in str(p) else str(p)))

    def error(self, text, code=1):
        return {'return': code, 'error': text}

    def catch_error(self, r, fail16=False):
        return r['return'] > 0

    def access(self, ii):
        self.calls.append(ii)
        return {'return': 0, 'returncode': 0, 'stdout': '', 'stderr': ''}


@pytest.fixture()
def run(task_namespace, tmp_path):
    cls = task_namespace('rclone-to-ssh')['CTask']

    def go(command, **params):
        task = cls.__new__(cls)
        task.cm = FakeCM()
        task.logger = logging.getLogger('rclone-to-ssh-under-test')
        task.category_alias, task.category_uid = 'task', 'c36be4b9314a45e0'
        ctx = {'control': {'con': False, 'quiet': True, 'verbose': False},
               'tasks': {'nested_call': 0, 'global': {'rclone': {'qpath': 'rclone'}, 'open-ssh': {}}}}
        r = task.run(ctx, rclone_command=command, local_dir=str(tmp_path), remote='me@nas:/data/repo', progress=False,
                     **params)
        cmds = [c['cmd'] for c in task.cm.calls if 'cmd' in c]
        return r, (cmds[-1] if cmds else '')

    return go


def test_a_two_way_sync_names_the_copy_that_keeps_the_name(run):
    r, cmd = run('bisync')
    assert r['return'] == 0 and ' --resilient --recover' in cmd
    assert cmd.endswith('--conflict-resolve newer --conflict-loser num')

    # rclone's own default (both copies renamed) only when asked for; another rule by its name
    assert '--conflict-resolve' not in run('bisync', conflict_resolve='none')[1]
    assert '--conflict-resolve path1 --conflict-loser num' in run('bisync', conflict_resolve='path1')[1]
    r, cmd = run('bisync', conflict_resolve='sometimes')
    assert r['return'] > 0 and 'conflict_resolve must be' in r['error']

    # a rule given after "--" is the caller's own: no second one
    assert '--conflict-resolve' not in run('bisync', unparsed=['--conflict-resolve', 'larger'])[1]
    # a resync has its own --resync-mode, a one-way command no conflicts
    assert '--conflict-resolve' not in run('bisync', resync=True)[1]
    assert '--conflict-resolve' not in run('copy')[1] and '--conflict-resolve' not in run('check')[1]


def test_the_rules_of_the_caller_come_first(run):
    first = ['+ /work/2026 item/!AI/log/*.running', '- /work/2026 item/**']
    r, cmd = run('bisync', rules_first=first, blacklist=['tmp*/', '*.sqlite-wal'], whitelist=['/work/*/**'])
    assert r['return'] == 0
    rules = [part.split('"')[1] for part in cmd.split('--filter ')[1:]]
    assert rules == first + ['- tmp*/**', '- *.sqlite-wal', '+ /work/*/**', '- **']

    # without them the two lists as before
    r, cmd = run('bisync', blacklist=['tmp*/'])
    assert [part.split('"')[1] for part in cmd.split('--filter ')[1:]] == ['- tmp*/**']
    # one rule as a string; something that is no rule is refused
    assert '--filter "- /a/**"' in run('copy', rules_first='- /a/**')[1]
    for wrong in (['/a/**'], ['+ /a/"b"/**']):
        r, cmd = run('copy', rules_first=wrong)
        assert r['return'] > 0 and 'is not a filter rule' in r['error'] and cmd == ''
