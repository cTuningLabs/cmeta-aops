"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-ai's conversations, newest activity first, when the times (kept to the second) are equal: the order of the ids'
stamps, then their -N counters. An id's stamp is taken a moment before its "started" is written, so a second boundary
between them gave 20261016-230237-2 the times of 20261016-230238, and the id's length put the older one first (CI,
2026-10-17).
"""

import importlib.util
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location('run_ai_conversations_under_test',
                                                  str(REPO_ROOT / 'task' / 'run-ai' / 'conversations.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def write(folder, cid, started, updated):
    (folder / (cid + '.conversation.json')).write_text(json.dumps({'id': cid, 'started': started, 'updated': updated}))


def test_a_second_boundary_between_the_stamp_and_started(tmp_path):
    m = module()
    write(tmp_path, '20261016-230237', '2026-10-16T23:02:37', '2026-10-16T23:02:37')
    write(tmp_path, '20261016-230237-2', '2026-10-16T23:02:38', '2026-10-16T23:02:38')     # its stamp was taken in second 37
    write(tmp_path, '20261016-230238', '2026-10-16T23:02:38', '2026-10-16T23:02:38')
    assert [c['id'] for c in m.list_conversations(str(tmp_path))] == ['20261016-230238', '20261016-230237-2', '20261016-230237']


def test_counters_of_one_second_and_later_activity(tmp_path):
    m = module()
    for cid in ('20261016-230237', '20261016-230237-2', '20261016-230237-10'):
        write(tmp_path, cid, '2026-10-16T23:02:37', '2026-10-16T23:02:37')
    assert [c['id'] for c in m.list_conversations(str(tmp_path))] == ['20261016-230237-10', '20261016-230237-2', '20261016-230237']

    # activity later than everything else comes first, whatever its id
    write(tmp_path, '20261016-230237', '2026-10-16T23:02:37', '2026-10-16T23:05:00')
    assert m.list_conversations(str(tmp_path))[0]['id'] == '20261016-230237'
