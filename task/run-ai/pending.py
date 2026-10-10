"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

run-ai: the memory and skills of the artifacts a project uses (its `ai_uses`, --context) stay read-only for a run -
whatever the harness, the platform or the permission mode - and are changed only on the user's word. Two mechanisms,
both plain files and the standard library, so they behave the same for whoever runs the project on any machine:

1. Proposals. A session that wants to change something in a used artifact writes the new version under the
   project's OWN folder, !AI/pending/<artifact>/, with the path the file has under that artifact's !AI:

       !AI/pending/<artifact>/memory/<name>.md           the whole file: a new one, or the replacement of one
       !AI/pending/<artifact>/memory/MEMORY.md.append    lines to add to an existing file (lines it already has are skipped)
       !AI/pending/<artifact>/memory/<name>.md.delete    remove that file (the marker's own content is not read)
       !AI/pending/<artifact>/skills/<skill>/SKILL.md    the same three forms for the files of a skill
       !AI/pending/<artifact>/_note.md                   why - shown before applying, never applied

   <artifact> is "<alias>--<artifact UID>" (stage_key). Only memory/ and skills/ can be proposed.
   "cxt run-ai --pending" lists the proposals; "cxt run-ai --apply_pending" shows each difference and applies it on
   the user's word, leaving <artifact>/!AI/log/<stamp>.applied.json as the record.

2. The guard. Before a run the memory/ and skills/ of every used artifact are snapshotted. After it, for whatever
   changed there without the user's word, the user is asked (--context_guard=ask, the default): keep it - recorded
   like an applied proposal - or not: then it is turned into a proposal (as above) and the file is put back. With
   nobody to ask (-q, --yes, no terminal, an API call) it is turned into a proposal and put back; "restore" does that
   without asking, "report" only reports, "off" does not look. A run the user gave write access everywhere
   (--write=all) has the user's word beforehand: "keep" leaves the changes, records them in the artifact like an
   applied proposal and saves the version each file had before the run in the project's !AI/log/<stamp>.before/.
   A run cannot tell who changed a file - a pull, a sync
   or the user's own edit during a long session looks like the session's - hence the question. Not a direct change:
   what "--apply_pending" wrote in the meantime (its record says so), and the changes of an artifact that was itself
   run as a project during that time - its own session writes its own memory.

   "In the meantime" is told by the records themselves, the way the changes are: the snapshot remembers the
   artifact's "applied" records and the runs of its conversation records, and the guard compares them with the ones
   it finds afterwards. No file time and no recorded time is compared with this machine's clock for it - the files
   of a project can be stamped by another clock (a Windows drive inside WSL2, a network share, a container), in
   another time zone, or to the whole second only.
"""

import datetime
import difflib
import glob
import hashlib
import json
import os
import re
import shutil
import time

PENDING_DIR = 'pending'
GUARDED_DIRS = ('memory', 'skills')         # what a run is given from a used artifact, and what can be proposed
NOTE_FILE = '_note.md'
APPEND, DELETE = '.append', '.delete'
DIRECT_DIR = '_direct'                      # direct changes kept aside when a proposal for the same file is staged
APPLIED_SUFFIX = '.applied.json'
LOG_DIR = 'log'
SKIP_DIRS = ('__pycache__',)
MAX_KEEP = 8 * 2 ** 20                      # a larger file is fingerprinted but not kept, so it cannot be put back
UNFINISHED_RUN_HOURS = 48                   # a run without an end counts as running this long (a crash leaves none)
CLOCK_SLACK = 0.1                           # seconds a file time may lag behind time.time() (the system clock tick):
                                            # only for a snapshot that did not keep the records (see applied_since)
READ_TRIES, READ_PAUSE = 3, 0.05            # a record caught while it is being written is read again after a moment


# ---------------------------------------------------------------------------------------------- names and files
def _glob(directory, *pattern):
    """glob.glob in a directory whose own name is taken as it is: a folder called "notes [draft]" is not a pattern."""
    return glob.glob(os.path.join(glob.escape(directory), *pattern))


def stage_key(label, root=''):
    """The folder name of a used artifact under !AI/pending: "<alias>--<artifact UID>" from its cRef
    "category,UID::alias,UID" - the same on every machine; without a UID the alias, else the folder name."""
    alias, uid = '', ''
    if '::' in (label or ''):
        art = label.split('::', 1)[1]
        alias, _, uid = art.rpartition(',') if ',' in art else (art, '', '')
    alias = alias or os.path.basename(os.path.normpath(root or '')) or 'artifact'
    alias = re.sub(r'[^A-Za-z0-9._-]+', '-', alias.strip()).strip('-.') or 'artifact'
    uid = re.sub(r'[^A-Za-z0-9]+', '', uid.strip())
    return ('%s--%s' % (alias, uid)) if uid else alias


def _sha(data):
    return hashlib.sha1(data).hexdigest()


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def _join(base, rel):
    return os.path.join(base, *rel.split('/'))


def _prune(path, stop):
    """Remove the empty folders from `path` up to, not including, `stop`."""
    path, stop = os.path.normpath(path), os.path.normpath(stop)
    while path != stop and path.startswith(stop + os.sep):
        try:
            os.rmdir(path)
        except OSError:
            return
        path = os.path.dirname(path)


def _walk(ai_dir):
    """(relative path with "/", full path) of every file under memory/ and skills/ of an !AI folder, sorted."""
    for top in GUARDED_DIRS:
        for d, dirs, files in os.walk(os.path.join(ai_dir, top)):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for fn in sorted(files):
                full = os.path.join(d, fn)
                yield os.path.relpath(full, ai_dir).replace(os.sep, '/'), full


def _ts(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso)).timestamp()
    except Exception:
        return None


def _json(path):
    """(the bytes, what they say) of a JSON record; (the bytes, None) when it cannot be read as one. The records are
    small files written in one go, not replaced in one step: one caught while it is being written is read again."""
    data = b''
    for attempt in range(READ_TRIES):
        if attempt:
            time.sleep(READ_PAUSE)
        try:
            data = _read(path)
            return data, json.loads(data.decode('utf-8'))
        except (OSError, ValueError):
            continue
    return data, None


def _runs(conv):
    """The runs of a conversation record -> [(key, started, finished)]. key names a run within its record: its stamp
    and its start (its place in the list for a record that has no stamps); finished is '' while the run has no end."""
    runs = conv.get('runs') if isinstance(conv, dict) else None
    out = []
    for n, r in enumerate(runs if isinstance(runs, list) else []):
        if isinstance(r, dict):
            out.append(('%s %s' % (r.get('stamp') or '#%d' % n, r.get('started') or ''), r.get('started'), str(r.get('finished') or '')))
    return out


# ---------------------------------------------------------------------------------------------- the guard
class Snapshot(dict):
    """{relative path: (sha1, the bytes, or None above MAX_KEEP)} of memory/ and skills/ of an !AI folder, and what
    the artifact's own records said at that moment:
        applied   {file name: sha1} of its "applied" records (applied_records)
        runs      {file name: {run: its end, '' while it has none}} of its conversation records (own_runs)
    The guard compares both with the records it finds after the run (applied_since, own_session_ran)."""
    applied = None
    runs = None


def snapshot(ai_dir):
    """The memory/ and skills/ of an !AI folder and its records as they are now -> Snapshot.
    The records are read first: an "applied" record is written after the files it names, and a session records its
    start before it writes and its end after - so a record the snapshot knows has its files in the snapshot too. The
    other order would leave a moment in which files written just after they were read came with a record that is
    already known, and they would count as a direct change."""
    snap = Snapshot()
    snap.applied = applied_records(ai_dir)
    snap.runs = own_runs(ai_dir)
    for rel, full in _walk(ai_dir):
        try:
            data = _read(full)
        except OSError:
            continue
        snap[rel] = (_sha(data), data if len(data) <= MAX_KEEP else None)
    return snap


def changes(snap, ai_dir):
    """What differs from the snapshot now -> [(relative path, "changed" | "added" | "deleted", sha1 now or "")]."""
    now = {}
    for rel, full in _walk(ai_dir):
        try:
            now[rel] = _sha(_read(full))
        except OSError:
            pass
    out = []
    for rel in sorted(set(snap) | set(now)):
        if rel not in now:
            out.append((rel, 'deleted', ''))
        elif rel not in snap:
            out.append((rel, 'added', now[rel]))
        elif snap[rel][0] != now[rel]:
            out.append((rel, 'changed', now[rel]))
    return out


def applied_records(ai_dir):
    """{file name: sha1} of the "applied" records in an artifact's !AI/log as they are now - kept by the snapshot."""
    out = {}
    for fp in _glob(ai_dir, LOG_DIR, '*' + APPLIED_SUFFIX):
        try:
            out[os.path.basename(fp)] = _sha(_read(fp))
        except OSError:
            pass
    return out


def applied_since(ai_dir, t0, known=None):
    """{(relative path, sha1 or "deleted")} of what "--apply_pending" wrote into this artifact since the snapshot
    (its records in !AI/log) - the changes the user has given their word for.
    known: the records the snapshot saw (applied_records). A record that is not among them, or that reads
    differently now, was written since; one that is among them describes what the snapshot already holds - if the
    same change is made again later, that is a new change. Without `known` (a snapshot that did not keep the
    records) the record's file time is compared with t0, this machine's clock at the snapshot: right on the
    machine's own disk, a guess where the files are stamped by another clock or to the whole second."""
    out = set()
    for fp in _glob(ai_dir, LOG_DIR, '*' + APPLIED_SUFFIX):
        if known is None:
            try:
                if os.path.getmtime(fp) < t0 - CLOCK_SLACK:     # written before the snapshot: already part of it
                    continue
            except OSError:
                continue
        data, d = _json(fp)
        if known is not None and known.get(os.path.basename(fp)) == _sha(data):
            continue
        for e in (d.get('applied') or []) if isinstance(d, dict) else []:
            if isinstance(e, dict) and e.get('rel'):
                out.add((e['rel'], e.get('sha1') or 'deleted'))
    return out


def own_runs(ai_dir):
    """{file name: {run: its end, '' while it has none}} of the artifact's own conversation records - the runs in
    which it was the project - as they are now; kept by the snapshot."""
    out = {}
    for fp in _glob(ai_dir, LOG_DIR, '*.conversation.json'):
        data, conv = _json(fp)
        if conv is not None:
            out[os.path.basename(fp)] = {key: finished for key, started, finished in _runs(conv)}
    return out


def own_session_ran(ai_dir, t0, t1, before=None):
    """True when the artifact was itself run as a run-ai project while our run lasted (the runs of its conversation
    records): its own session writes its own memory, and that is no direct change of ours.
    before: its runs as the snapshot saw them (own_runs). The answer then comes from the records: a run that is not
    among them was started since, and one that had no end then and has one now ended since. A run that still has no
    end counts as running for UNFINISHED_RUN_HOURS from its start (a crash leaves none) - the one place where a
    recorded time meets this machine's clock, with two days to spare. A run that had its end at the snapshot was
    over before ours began, whatever its times say on this machine.
    Without `before` (a snapshot that did not keep the records) the recorded times are compared with t0 and t1,
    this machine's clock at the snapshot and now."""
    for fp in _glob(ai_dir, LOG_DIR, '*.conversation.json'):
        data, conv = _json(fp)
        known = None if before is None else before.get(os.path.basename(fp), {})
        for key, started, finished in _runs(conv):
            a = _ts(started)
            if known is None:
                if a is None:
                    continue
                b = _ts(finished) if finished else None
                if b is None:
                    b = a + UNFINISHED_RUN_HOURS * 3600
                if a <= t1 and b >= t0:
                    return True
            elif key not in known:
                return True                 # recorded since the snapshot: it started while our run lasted
            elif not finished:
                if a is not None and a + UNFINISHED_RUN_HOURS * 3600 >= t0:
                    return True             # still without an end: running, or crashed not long ago
            elif not known[key]:
                return True                 # it had no end at the snapshot and has one now
    return False


def guard(sources, snaps, t0, t1, mode, pending_root, stamp, ask=None, project='', keep_root=''):
    """After a run: the direct changes in the used artifacts. sources: [{label, key, ai}] ("ai" = the artifact's
    !AI folder), snaps: {ai: snapshot}. mode "restore": every direct change becomes a proposal under
    pending_root/<key>/ and the file is put back; "report": listed only; "ask": ask(source, changes) -> True keeps
    them (the user's word, recorded like an applied proposal) and False does what "restore" does - as does "ask"
    with nobody to ask (ask=None). A run cannot tell who changed a file: a pull, a sync or the user's own edit
    during a long session looks the same as the session's, which is why the user is asked when there is one.
    mode "keep" (a run the user gave write access everywhere, --write=all): the changes stay, are recorded in the
    artifact like an applied proposal, and the version each changed or deleted file had before the run is saved
    under keep_root/<key>/ (when keep_root is given), so that a change can be taken back.
    t0, t1: this machine's clock at the snapshot and now. With the snapshots of snapshot() they only bound how long
    a run without an end counts as running; what was applied, and which runs of the artifact started or ended, in
    the meantime is read from the records the snapshot kept (see applied_since and own_session_ran).
    -> (lines for the user, [{label, rel, what, outcome, staged}])."""
    notes, records = [], []
    for s in sources:
        snap = snaps.get(s['ai'])
        if snap is None:
            continue
        ch = changes(snap, s['ai'])
        if not ch:
            continue
        approved = applied_since(s['ai'], t0, getattr(snap, 'applied', None))
        ch = [c for c in ch if (c[0], c[2] or 'deleted') not in approved]
        if not ch:
            continue
        if own_session_ran(s['ai'], t0, t1, getattr(snap, 'runs', None)):
            for rel, what, sha in ch:
                records.append({'label': s['label'], 'rel': rel, 'what': what, 'outcome': 'left: the artifact ran its own session meanwhile', 'staged': ''})
            notes.append('context guard: %d file(s) of %s changed during the run - left as they are, that artifact was run as a '
                         'project itself in the meantime: %s' % (len(ch), s['label'], ', '.join(c[0] for c in ch[:8])))
            continue
        if mode == 'report':
            for rel, what, sha in ch:
                records.append({'label': s['label'], 'rel': rel, 'what': what, 'outcome': 'reported', 'staged': ''})
            notes.append('context guard: %d file(s) of %s were changed directly during the run (reported only, --context_guard=report): %s' % (
                len(ch), s['label'], ', '.join('%s (%s)' % (c[0], c[1]) for c in ch[:8])))
            continue
        if mode == 'keep':
            before_dir, saved, unsaved = os.path.join(keep_root, s['key']) if keep_root else '', 0, []
            for rel, what, sha in ch:
                before = ''
                if what != 'added':
                    old = snap[rel][1]
                    if before_dir and old is not None:
                        try:
                            before = _join(before_dir, rel)
                            _write(before, old)
                            saved += 1
                        except OSError:
                            before = ''
                    if not before:
                        unsaved.append(rel)
                records.append({'label': s['label'], 'rel': rel, 'what': what, 'outcome': 'kept (write access to the used artifacts)',
                                'staged': '', 'before': before})
            fp = record_applied(s['ai'], stamp, project, [{'rel': rel, 'action': 'kept (%s during a run with write access)' % what, 'sha1': sha}
                                                           for rel, what, sha in ch], by='run-ai --write=all: direct changes allowed for the run')
            notes.append('context guard: %d file(s) of %s were changed directly during the run, as --write=all allows: %s' % (
                len(ch), s['label'], ', '.join('%s (%s)' % (c[0], c[1]) for c in ch[:8])))
            notes.append('               the record: %s; %s' % (fp, ('the versions before the run: %s' % before_dir) if saved else
                                                                'no earlier version to keep (new files only)' if not unsaved else
                                                                'the versions before the run were not kept'))
            if unsaved and saved:
                notes.append('               not kept (too large, or --no_log): %s' % ', '.join(unsaved[:8]))
            continue
        if mode == 'ask' and ask is not None and ask(s, ch):
            for rel, what, sha in ch:
                records.append({'label': s['label'], 'rel': rel, 'what': what, 'outcome': 'kept on the user\'s word', 'staged': ''})
            fp = record_applied(s['ai'], stamp, project, [{'rel': rel, 'action': 'kept (%s during a run)' % what, 'sha1': sha} for rel, what, sha in ch],
                                by='run-ai context guard: kept on the user\'s word')
            notes.append('context guard: %d change(s) in %s kept on your word (the record: %s)' % (len(ch), s['label'], fp))
            continue
        key_dir = os.path.join(pending_root, s['key'])
        done = []
        for rel, what, sha in ch:
            target = _join(s['ai'], rel)
            stage = _join(key_dir, rel)
            outcome = ''
            try:
                # 1. what was written is kept as a proposal - nothing is lost
                if what == 'deleted':
                    if not os.path.exists(stage + DELETE):
                        _write(stage + DELETE, b'')
                    kept = stage + DELETE
                else:
                    data = _read(target)
                    if os.path.exists(stage) and _sha(_read(stage)) != _sha(data):
                        stage = _join(os.path.join(key_dir, '%s-%s' % (DIRECT_DIR, stamp)), rel)   # a proposal for it is staged already
                    _write(stage, data)
                    kept = stage
                # 2. the file is put back as it was before the run
                if what == 'added':
                    os.remove(target)
                    _prune(os.path.dirname(target), s['ai'])
                    outcome = 'removed again; kept as a proposal'
                else:
                    old = snap[rel][1]
                    if old is None:
                        outcome = 'NOT put back (the original was too large to keep); the new version is copied to the proposals'
                    else:
                        _write(target, old)
                        outcome = 'put back; the %s kept as a proposal' % ('removal' if what == 'deleted' else 'new version')
                if DIRECT_DIR + '-' in kept.replace(os.sep, '/'):
                    outcome += ' aside (%s: a proposal for this file was staged already)' % os.path.relpath(os.path.dirname(kept), pending_root).replace(os.sep, '/')
            except OSError as e:
                kept, outcome = '', 'could not be handled: %s' % e
            records.append({'label': s['label'], 'rel': rel, 'what': what, 'outcome': outcome, 'staged': kept})
            done.append('%s (%s: %s)' % (rel, what, outcome))
        notes.append('context guard: %d direct change(s) in %s, which is read-only for a run: %s' % (len(ch), s['label'], '; '.join(done[:8])))
        notes.append('               they wait in %s - "cxt run-ai --apply_pending" shows and applies them' % key_dir)
    return notes, records


# ---------------------------------------------------------------------------------------------- the proposals
def staged(pending_root, sources):
    """The proposals under <project>/!AI/pending -> (targets, unknown).
    targets: [{key, label, ai, dir, note, items: [{rel, action, staged, target, problem, lines}]}] for the used
    artifacts that have a folder there; action is "new", "change", "append", "delete" or "same" (nothing to do).
    unknown: folder names that match no artifact this project uses (never applied)."""
    targets, unknown = [], []
    if not os.path.isdir(pending_root):
        return targets, unknown
    by_key = {s['key']: s for s in sources}
    for key in sorted(os.listdir(pending_root)):
        key_dir = os.path.join(pending_root, key)
        if not os.path.isdir(key_dir) or key.startswith('_'):
            continue
        s = by_key.get(key)
        if s is None:
            unknown.append(key)
            continue
        note = ''
        try:
            note = _read(os.path.join(key_dir, NOTE_FILE)).decode('utf-8', 'replace').strip()
        except OSError:
            pass
        items = []
        for d, dirs, files in os.walk(key_dir):
            dirs[:] = sorted(x for x in dirs if not x.startswith('_') and x not in SKIP_DIRS)
            for fn in sorted(files):
                full = os.path.join(d, fn)
                rel = os.path.relpath(full, key_dir).replace(os.sep, '/')
                if rel == NOTE_FILE:
                    continue
                kind = 'append' if rel.endswith(APPEND) else ('delete' if rel.endswith(DELETE) else 'file')
                trel = rel[:-len(APPEND)] if kind == 'append' else (rel[:-len(DELETE)] if kind == 'delete' else rel)
                item = {'rel': trel, 'action': '', 'staged': full, 'target': _join(s['ai'], trel), 'problem': '', 'lines': []}
                parts = trel.split('/')
                if parts[0] not in GUARDED_DIRS or len(parts) < 2 or any(p in ('', '.', '..') for p in parts):
                    item['problem'] = 'only files under %s can be proposed' % ' and '.join(x + '/' for x in GUARDED_DIRS)
                    items.append(item)
                    continue
                exists = os.path.isfile(item['target'])
                if kind == 'delete':
                    item['action'] = 'delete' if exists else 'same'
                elif kind == 'append':
                    have = set(_text(_read(item['target'])).splitlines()) if exists else set()
                    item['lines'] = [x for x in _text(_read(full)).splitlines() if x.strip() and x not in have]
                    item['action'] = ('append' if exists else 'new') if item['lines'] else 'same'
                else:
                    item['action'] = 'new' if not exists else ('same' if _sha(_read(full)) == _sha(_read(item['target'])) else 'change')
                items.append(item)
        targets.append({'key': key, 'label': s['label'], 'ai': s['ai'], 'dir': key_dir, 'note': note, 'items': items})
    return targets, unknown


def count(pending_root, sources):
    """How many proposals would change something."""
    targets, unknown = staged(pending_root, sources)
    return sum(1 for t in targets for i in t['items'] if i['action'] not in ('', 'same'))


def _text(data):
    return data.decode('utf-8', 'replace')


def _is_text(data):
    if b'\0' in data[:8192]:
        return False
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        return False
    return True


def diff(item, limit=160):
    """The difference a proposal would make, as lines for the terminal."""
    action = item['action']
    if item['problem']:
        return ['    ! %s' % item['problem']]
    if action == 'same':
        return ['    (nothing to do: the artifact has it already)']
    if action == 'delete':
        return ['    - the file is removed (%d bytes)' % os.path.getsize(item['target'])]
    if action == 'append' or (action == 'new' and item['lines']):
        return ['    + %s' % x for x in item['lines'][:limit]]
    new = _read(item['staged'])
    old = _read(item['target']) if action == 'change' else b''
    if not _is_text(new) or not _is_text(old):
        return ['    binary file: %d -> %d bytes' % (len(old), len(new))]
    if action == 'new':
        lines = ['+ ' + x for x in _text(new).splitlines()]
    else:
        lines = list(difflib.unified_diff(_text(old).splitlines(), _text(new).splitlines(), 'now', 'proposed', lineterm='', n=2))
    out = ['    ' + x for x in lines[:limit]]
    if len(lines) > limit:
        out.append('    ... %d more line(s)' % (len(lines) - limit))
    return out


def apply(item):
    """Carry out one proposal -> {rel, action, sha1 ('' for a removal)}; "same" and refused ones return None."""
    action, target = item['action'], item['target']
    if item['problem'] or action in ('', 'same'):
        return None
    if action == 'delete':
        os.remove(target)
        _prune(os.path.dirname(target), _top(target, item['rel']))
        return {'rel': item['rel'], 'action': action, 'sha1': ''}
    if item['lines']:                            # lines to add; the file's own line ends are kept
        old = _read(target) if os.path.isfile(target) else b''
        nl = b'\r\n' if b'\r\n' in old else b'\n'
        data = old + (b'' if (not old or old.endswith(b'\n')) else nl) + nl.join(x.encode('utf-8') for x in item['lines']) + nl
    else:
        data = _read(item['staged'])
    _write(target, data)
    return {'rel': item['rel'], 'action': action, 'sha1': _sha(data)}


def _top(target, rel):
    """The !AI folder a target belongs to (the target path minus its relative part)."""
    p = os.path.normpath(target)
    for _ in rel.split('/'):
        p = os.path.dirname(p)
    return p


def clear(item, key_dir):
    """Take an applied (or needless) proposal out of the staging folder."""
    try:
        os.remove(item['staged'])
    except OSError:
        return
    _prune(os.path.dirname(item['staged']), key_dir)


def finish_target(key_dir, pending_root):
    """Drop the note and the folder of an artifact when no proposal is left in it, then the pending folder itself."""
    left = [os.path.join(d, fn) for d, dirs, files in os.walk(key_dir) for fn in files]
    if left and all(os.path.basename(x) == NOTE_FILE and os.path.dirname(x) == key_dir for x in left):
        os.remove(left[0])
        left = []
    if not left:
        shutil.rmtree(key_dir, ignore_errors=True)
    try:
        os.rmdir(pending_root)
    except OSError:
        pass


def record_applied(ai_dir, stamp, project, records, by='cxt run-ai --apply_pending'):
    """<artifact>/!AI/log/<stamp>.applied.json: what was applied (or kept), when and from which project - the
    user's word on record, which also tells the guard of a run in progress that these changes are no direct ones."""
    os.makedirs(os.path.join(ai_dir, LOG_DIR), exist_ok=True)
    n = 1
    while True:
        # one record per decision. The name is taken by creating the file, which looking for it first is not: two
        # projects started within the same second carry the same stamp and may record in one artifact at once
        fp = os.path.join(ai_dir, LOG_DIR, '%s%s%s' % (stamp, '' if n == 1 else '-%d' % n, APPLIED_SUFFIX))
        n += 1
        try:
            f = open(fp, 'x', encoding='utf-8', newline='\n')
        except FileExistsError:
            continue
        break
    with f:
        json.dump({'applied_on': datetime.datetime.now().isoformat(timespec='seconds'), 'by': by,
                   'from_project': project, 'applied': records}, f, indent=1)
        f.write('\n')
    return fp
