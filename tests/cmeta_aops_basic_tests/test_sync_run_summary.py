"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The verdict of a named sync (task/sync, 2026-11-11): what a run did, read from its rclone log - the last statistics
block (files moved, bytes, deleted, errors) and the files changed on both sides that bisync keeps as .conflict1 /
.conflict2 while the name itself disappears; the banner; the words of the conflicts. Offline, on log text.
"""
import types

import pytest

ROOTS = (r'D:\work\repos\personal', r'D:\work\sites\copy\repos\personal')

# a real run of 2026-11-11 (the names made generic): the first statistics block during the run, the conflict lines,
# the final block
REAL_RUN = r"""
2026/11/11 20:03:08 INFO  : Path1:  180 changes:  147 new,   33 modified,    0 deleted
2026/11/11 20:03:08 INFO  : Path2:  106 changes:   10 new,   22 modified,   74 deleted
2026/11/11 20:03:08 INFO  : Checking potential conflicts...
2026/11/11 20:03:08 INFO  : Finished checking the potential conflicts. %!s(<nil>)
2026/11/11 20:03:08 NOTICE: - WARNING           New or changed in both paths                - category/cserver.track-food/api/v1.py
2026/11/11 20:03:08 INFO  : category/cserver.track-food/api/v1.py: Files are equal but will copy anyway to update modtime (will not rename)
2026/11/11 20:03:08 NOTICE: - WARNING           New or changed in both paths                - category/cserver.track-food/files/js/food.js
2026/11/11 20:03:08 INFO  : - Path1             Renaming Path1 copy                         - D:\work\repos\personal\category/cserver.track-food/files/js/food.js.conflict1
2026/11/11 20:03:08 INFO  : category/cserver.track-food/files/js/food.js: Moved (server-side) to: category/cserver.track-food/files/js/food.js.conflict1
2026/11/11 20:03:08 INFO  : - Path2             Renaming Path2 copy                         - D:\work\sites\copy\repos\personal\category/cserver.track-food/files/js/food.js.conflict2
2026/11/11 20:03:08 INFO  : category/cserver.track-food/files/js/food.js: Moved (server-side) to: category/cserver.track-food/files/js/food.js.conflict2
2026/11/11 20:03:08 INFO  : category/cserver.track-food/files/js/food.js.conflict2: Copied (new)
2026/11/11 20:03:08 INFO  : category/cserver.track-food/files/js/food.js.conflict1: Copied (new)
2026/11/11 20:03:08 INFO  : team.link/Search: Removing directory
2026/11/11 20:03:08 INFO  :
Transferred:   	    1.000 MiB / 1.559 MiB, 64%, 0 B/s, ETA -
Checks:              2363 / 2363, 100%
Deleted:               70 (files), 30 (dirs), 20.000 KiB (freed)
Transferred:          120 / 186, 64%
Elapsed time:         0.5s

2026/11/11 20:03:09 INFO  : Validating listings for Path1 "D:\work\repos\personal\" vs Path2 "D:\work\sites\copy\repos\personal\"
2026/11/11 20:03:09 INFO  : Bisync successful
2026/11/11 20:03:09 INFO  :
Transferred:   	    1.559 MiB / 1.559 MiB, 100%, 0 B/s, ETA -
Checks:              2363 / 2363, 100%
Deleted:               74 (files), 37 (dirs), 21.200 KiB (freed)
Renamed:              105
Transferred:          186 / 186, 100%
Elapsed time:         0.8s
"""


@pytest.fixture(scope='module')
def sync(task_namespace):
    """The sync task's module-level helpers (the task loaded the way the other task tests load one)."""
    return types.SimpleNamespace(**task_namespace('sync'))


def test_the_summary_of_a_real_run_with_a_conflict(sync):
    s = sync.run_summary(REAL_RUN, ROOTS)
    assert s['files'] == 186 and s['bytes'] == '1.6 MB' and s['deleted'] == 74 and s['errors'] == 0   # 1000-based (2026-11-12)
    assert s['conflicts'] == [{'file': 'category/cserver.track-food/files/js/food.js',
                               'copies': ['category/cserver.track-food/files/js/food.js.conflict1',
                                          'category/cserver.track-food/files/js/food.js.conflict2']}]


def test_a_dry_run_names_the_conflict_and_skips_equal_files(sync):
    text = ("2026/11/11 20:47:03 NOTICE: - WARNING           New or changed in both paths                - a/b.txt\n"
            "2026/11/11 20:47:03 NOTICE: - WARNING           New or changed in both paths                - same.txt\n"
            "2026/11/11 20:47:03 INFO  : Files are equal! Skipping: same.txt\n"
            "2026/11/11 20:47:03 NOTICE: a/b.txt: Skipped rename as --dry-run is set\n"
            r"2026/11/11 20:30:20 INFO  : - Path1             Queue copy to Path2                         - D:\work\repos\personal\a/b.txt.conflict1" + '\n'
            r"2026/11/11 20:30:20 INFO  : - Path2             Queue copy to Path1                         - :sftp{puAlO}:HOME/repos/a/b.txt.conflict2" + '\n'
            "2026/11/11 20:30:20 INFO  : a/b.txt.conflict1: Skipped move as --dry-run is set (size 1Ki)\n")
    s = sync.run_summary(text, (r'D:\work\repos\personal', ':sftp:HOME/repos'))
    assert s['conflicts'] == [{'file': 'a/b.txt', 'copies': ['a/b.txt.conflict1', 'a/b.txt.conflict2']}]
    assert s['files'] == 0 and s['deleted'] == 0


def test_a_clean_run_and_errors(sync):
    text = ("2026/11/11 20:11:05 INFO  : Bisync successful\n2026/11/11 20:11:05 INFO  :\n"
            "Transferred:   	  146.292 KiB / 146.292 KiB, 100%, 0 B/s, ETA -\nErrors:                 2 (retrying may help)\n"
            "Checks:              2363 / 2363, 100%\nDeleted:                2 (files), 0 (dirs), 292.059 KiB (freed)\n"
            "Transferred:            1 / 1, 100%\nElapsed time:         1.2s\n")
    s = sync.run_summary(text, ROOTS)
    assert s == {'files': 1, 'bytes': '150 kB', 'deleted': 2, 'errors': 2, 'conflicts': []}
    assert sync.run_summary('', ROOTS) == {'files': 0, 'bytes': '', 'deleted': 0, 'errors': 0, 'conflicts': []}


def test_the_banner_and_the_words_of_the_conflicts(sync):
    b = sync.banner('CONFLICTS!', 'STATUS: CONFLICTS - one | two')
    lines = b.splitlines()
    assert lines[0] == '=' * 100 and lines[-1] == '=' * 100 and len(lines) == 10
    assert '#' in lines[1] and lines[-3] == '  STATUS: CONFLICTS - one' and lines[-2] == '  two'
    assert len(sync.banner('SUCCESS!', 'x').splitlines()) == 9
    s = sync.run_summary(REAL_RUN, ROOTS)
    t = sync.conflicts_text(s, ('the source ...work/repos/personal', 'the destination on my-vm'))
    assert t.startswith('CONFLICTS: 1 file changed on BOTH sides') and '.conflict1 (the source ...work/repos/personal)' in t
    assert '    category/cserver.track-food/files/js/food.js' in t.split(' | ') and 'run the sync again' in t


def test_a_carried_conflict_copy_alone_is_no_new_conflict(sync):
    """An older .conflict copy carried to the next pair (a run of the next step) is no conflict of this run."""
    text = (r"2026/11/11 20:03:39 INFO  : - Path1             Queue copy to Path2                         - :sftp{x}:HOME/repos/a/b.txt.conflict1" + "\n"
            "2026/11/11 20:03:39 INFO  : a/b.txt.conflict1: Copied (new)\n")
    assert sync.run_summary(text, ('D:/x', ':sftp:HOME/repos'))['conflicts'] == []


# ---- the reindex after a run (2026-11-11): what changed, and where the homes learn it

CHANGES = '\n'.join([
    '2026/11/11 20:03:08 INFO  : team-notes/team.link/New link/_cmeta.yaml: Copied (new)',
    '2026/11/11 20:03:08 INFO  : team-notes/team.link/Old link/_desc.yaml: Moved into backup dir',
    '2026/11/11 20:03:08 INFO  : team-notes/team.link/Old link: Removing directory',
    '2026/11/11 20:03:08 INFO  : local/state/team-links/_cmeta.yaml: Copied (replaced existing)',
    '2026/11/11 20:03:08 INFO  : - Path1             Queue copy to Path2                         - D:/x/repos/team/team.event/a/_cmeta.yaml',
    '2026/11/11 20:03:08 INFO  : Path1:    3 changes:    1 new,    1 modified,    1 deleted',
    '2026/11/11 20:03:08 INFO  : Bisync successful',
    'Deleted:                1 (files), 1 (dirs), 1.000 KiB (freed)',
])


def test_what_a_run_changed_by_its_first_path_component(sync):
    assert sync.changed_tops(CHANGES) == {'team-notes', 'local'}
    assert sync.changed_tops('2026/11/11 20:03:08 INFO  : There was nothing to transfer\n') == set()


def side(path, remote=False, host='local'):
    return {'path': path, 'remote': remote, 'host': host}


def home(tmp_path, name):
    h = tmp_path / name
    (h / 'repos').mkdir(parents=True)
    (h / 'repos.json').write_text('{}', encoding='utf-8')
    return h


def test_the_homes_and_repositories_to_reindex(sync, tmp_path):
    a, b = home(tmp_path, 'home-a'), home(tmp_path, 'home-b')
    vm = 'host,e4e49c251c814f6d::my-vm,f074914e5be0408b'
    # a home's repositories (repos:) with a host: the listed ones that changed, on both sides of a bisync
    plan = {'mode': 'bisync', 'repos': ['team-notes', 'team'], 'reindex': True,
            'source': side(str(a / 'repos')), 'destination': side(':sftp:CMETA-X/repos', True, vm)}
    assert sync.reindex_targets(plan, {'team-notes', 'local'}) == [
        {'side': 'source', 'remote': False, 'host': 'local', 'home': str(a), 'repos': ['team-notes']},
        {'side': 'destination', 'remote': True, 'host': vm, 'home': 'CMETA-X', 'repos': ['team-notes']}]
    # one repository of each of two homes: that repository on both
    plan = {'mode': 'bisync', 'repos': None, 'source': side(str(a / 'repos' / 'r1')),
            'destination': side(str(b / 'repos' / 'r1'))}
    assert [(t['home'], t['repos']) for t in sync.reindex_targets(plan, {'x'})] == [(str(a), ['r1']), (str(b), ['r1'])]
    # a mirror changes its destination only; a folder outside any home is left alone
    plan = {'mode': 'mirror', 'repos': None, 'source': side(str(a / 'repos' / 'r1')),
            'destination': side(str(tmp_path / 'plain' / 'repos' / 'r9'))}
    assert sync.reindex_targets(plan, {'x'}) == []
    plan['destination'] = side(str(b / 'repos' / 'r2'))
    assert [(t['side'], t['repos']) for t in sync.reindex_targets(plan, {'x'})] == [('destination', ['r2'])]
    # an absolute remote home; nothing changed; reindex: false
    plan = {'mode': 'copy', 'repos': '*', 'source': side(str(a / 'repos')),
            'destination': side(':sftp:/srv/home-x/repos', True, vm)}
    assert sync.reindex_targets(plan, {'local'})[0]['home'] == '/srv/home-x'
    assert sync.reindex_targets(plan, set()) == []
    assert sync.reindex_targets(dict(plan, reindex=False), {'local'}) == []


# a real run of 2026-11-17 with --conflict-resolve newer (the names made generic): one file whose newer copy is the
# source's, one whose newer copy is the destination's
NEWER_RUN = r"""2026/11/17 17:09:54 NOTICE: - WARNING           New or changed in both paths                - notes/n1.md
2026/11/17 17:09:54 INFO  : notes/n1.md: Path1 is newer. Path1: 2026-11-17 17:05:26 +0100 CET, Path2: 2026-11-17 16:43:26 +0100 CET, Difference: 22m0s
2026/11/17 17:09:54 INFO  : notes/n1.md: The winner is: Path1
2026/11/17 17:09:54 NOTICE: - Path1             Not renaming Path1 copy, as it was determined the winner - D:\work\repos\personal\notes/n1.md
2026/11/17 17:09:54 NOTICE: - Path1             Queue copy to Path2                         - :sftp{-4u0A}:HOME/repos/personal/notes/n1.md
2026/11/17 17:09:54 NOTICE: - Path2             Renaming Path2 copy                         - :sftp{-4u0A}:HOME/repos/personal/notes/n1.md.conflict1
2026/11/17 17:09:54 INFO  : notes/n1.md: Moved (server-side) to: notes/n1.md.conflict1
2026/11/17 17:09:54 NOTICE: - Path2             Queue copy to Path1                         - D:\work\repos\personal\notes/n1.md.conflict1
2026/11/17 17:09:54 NOTICE: - WARNING           New or changed in both paths                - notes/n2.md
2026/11/17 17:09:54 INFO  : notes/n2.md: Path2 is newer. Path1: 2026-11-17 16:38:26 +0100 CET, Path2: 2026-11-17 17:06:26 +0100 CET, Difference: 28m0s
2026/11/17 17:09:54 INFO  : notes/n2.md: The winner is: Path2
2026/11/17 17:09:54 NOTICE: - Path1             Renaming Path1 copy                         - D:\work\repos\personal\notes/n2.md.conflict1
2026/11/17 17:09:54 INFO  : notes/n2.md: Moved (server-side) to: notes/n2.md.conflict1
2026/11/17 17:09:54 NOTICE: - Path1             Queue copy to Path2                         - :sftp{-4u0A}:HOME/repos/personal/notes/n2.md.conflict1
2026/11/17 17:09:54 NOTICE: - Path2             Not renaming Path2 copy, as it was determined the winner - :sftp{-4u0A}:HOME/repos/personal/notes/n2.md
2026/11/17 17:09:55 INFO  : notes/n1.md.conflict1: Copied (new)
2026/11/17 17:09:55 INFO  : notes/n1.md: Copied (new)
2026/11/17 17:09:55 INFO  : notes/n2.md.conflict1: Copied (new)
2026/11/17 17:09:55 INFO  : notes/n2.md: Copied (replaced existing)
"""


def test_the_newer_copy_keeps_the_name_and_the_verdict_says_whose_it_is(sync):
    """Since 2026-11-17 a two-way sync tells rclone that the newer copy keeps the name: the file is there on both
    sides, the other copy beside it - still a conflict for a person to look at, no longer a missing file."""
    s = sync.run_summary(NEWER_RUN, ROOTS)
    assert s['conflicts'] == [{'file': 'notes/n1.md', 'copies': ['notes/n1.md.conflict1'], 'kept': 'source'},
                              {'file': 'notes/n2.md', 'copies': ['notes/n2.md.conflict1'], 'kept': 'destination'}]
    t = sync.conflicts_text(s, ('the source ...work/repos/personal', 'the destination on my-vm')).split(' | ')
    assert t[0] == ('CONFLICTS: 2 files changed on BOTH sides since the last run - the newer copy keeps the name on both '
                    'sides, the other is kept beside it as <name>.conflict1')
    assert t[1] == '    notes/n1.md  (kept: the copy of the source ...work/repos/personal)'
    assert t[2] == '    notes/n2.md  (kept: the copy of the destination on my-vm)'
    assert t[3].startswith('look at each kept copy') and 'the name itself is gone' not in ' | '.join(t)

    # the same time on both sides: no newer copy, both renamed as before - said apart when a run has both kinds
    both = sync.run_summary(NEWER_RUN + REAL_RUN, ROOTS)
    t = sync.conflicts_text(both, ('here', 'there'))
    assert t.startswith('CONFLICTS: 3 files changed on BOTH sides since the last run | 2 with a newer copy')
    assert '1 with the same time on both sides, no newer copy - kept as .conflict1 (here) and .conflict2 (there)' in t
    assert 'look at each kept copy' in t and 'resolve: on ONE side copy the right version back' in t
