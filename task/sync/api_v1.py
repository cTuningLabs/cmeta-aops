"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""
import codecs
from contextlib import contextmanager, nullcontext
import hashlib
from collections import deque
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from task_c36be4b9314a45e0.api.ctask import InitCTask


def duration_text(seconds):
    """Seconds for a person (2026-11-12, the user: "2h34m20s"): 7.4s, 45s, 10m32s, 2h34m20s."""
    x = max(float(seconds or 0), 0.0)
    if x < 10:
        return f'{x:.1f}s'
    s = int(round(x))
    if s < 60:
        return f'{s}s'
    if s < 3600:
        return f'{s // 60}m{s % 60:02d}s'
    return f'{s // 3600}h{(s % 3600) // 60:02d}m{s % 60:02d}s'


def safe_relative(value):
    value = str(value).replace('\\', '/')
    if not value or any(p in ('', '.', '..') or ':' in p for p in value.split('/')):
        raise ValueError('expected a relative path without ..: ' + value)
    return value


def quote(value):
    value = str(value)
    if os.name != 'nt':
        return shlex.quote(value)
    # cmd.exe expands percent variables even inside quotes. These are command
    # arguments, not the filenames rclone discovers inside the selected trees.
    if any(c in value for c in ('"', '%', '\r', '\n')):
        raise ValueError('unsupported character in Windows command argument: ' + value)
    return '"' + value + '"'


def size_text(n):
    """Bytes for a person, 1000-based (2026-11-12, the user: "GB with 1000-based numbers everywhere to be consistent (Win, MacOS, Linux)"): 812 B, 3.4 GB, 7.3 TB."""
    n = float(n or 0)
    for unit in ('B', 'kB', 'MB', 'GB', 'TB'):
        if n < 1000 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit in ('B', 'kB') else f'{n:.1f} {unit}'
        n /= 1000
    return f'{n:.1f} TB'


# rclone's sizes are 1024-based (1.721 MiB, 12.0 KiB/s): the same figures in the units of _size_text
_BINARY = {'B': 1, 'KiB': 1024, 'MiB': 1024 ** 2, 'GiB': 1024 ** 3, 'TiB': 1024 ** 4, 'PiB': 1024 ** 5}
_BINARY_RE = re.compile(r'(\d+(?:\.\d+)?)\s?(PiB|TiB|GiB|MiB|KiB|B)\b')


def _si(text):
    return _BINARY_RE.sub(lambda m: size_text(float(m.group(1)) * _BINARY[m.group(2)]), str(text or ''))


def stats_text(block):
    """One line from one of rclone's statistics blocks (the 10 s statistics of the run log): what has moved of what is
    to move, %, speed and time left - or, while the sides are still listed, how far the listing is (--progress,
    2026-11-11; the host category reads the same blocks for cx host sync --progress)."""
    got = {}
    for line in block:
        key, _, value = line.partition(':')
        key, value = key.strip(), value.strip()
        if key == 'Transferred' and 'ETA' in value:
            got['bytes'] = value
        elif key == 'Transferred':
            got['files'] = value.split(',')[0]
        elif key in ('Checks', 'Errors', 'Deleted', 'Elapsed time'):
            got[key] = value
    parts = []
    m = re.match(r'(.+?) / (.+?), (\S+), (.+?), ETA (.+)$', got.get('bytes', ''))
    files = got.get('files', '')
    if m and files and not files.endswith('/ 0'):
        parts.append(f'{files} files, {m.group(1).strip()} of {m.group(2).strip()} ({m.group(3)}), {m.group(4)}, ETA {m.group(5)}')
    else:
        parts.append('comparing the two sides')
    listed = re.search(r'Listed (\d+)', got.get('Checks', ''))
    if listed:
        parts.append(f'{int(listed.group(1)):,} listed')
    checks = re.match(r'(\d+) / (\d+)', got.get('Checks', ''))
    if checks and checks.group(2) != '0':
        parts.append(f'{int(checks.group(1)):,} of {int(checks.group(2)):,} compared')
    if got.get('Deleted'):
        parts.append(got['Deleted'].split(',')[0] + ' deleted')
    if got.get('Errors') and not got['Errors'].startswith('0'):
        parts.append('errors: ' + got['Errors'])
    return _si((got.get('Elapsed time') or '?') + ': ' + ' | '.join(parts))


STATS_START = re.compile(r'^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d (?:INFO|NOTICE)\s*:\s*$')

# bisync's lines for a file changed on both sides (rclone 1.66+, --conflict-resolve none --conflict-loser num):
#   - WARNING   New or changed in both paths   - <name>                  (every such file, real and dry runs)
#   <name>: Files are equal but will copy anyway ...  |  Files are equal! Skipping: <name>     (the same bytes: no conflict)
#   - Path1   Renaming Path1 copy   - <absolute name>.conflict1          (real runs)
#   <name>: Moved (server-side) to: <name>.conflict1                      (real runs)
#   - Path1   Queue copy to Path2   - <absolute name>.conflict1          (real and dry runs: the copy for the other side)
BOTH_CHANGED = re.compile(r'New or changed in both paths\s+- (.+?)\s*$')
FILES_EQUAL = (re.compile(r'^(.+?): Files are equal'), re.compile(r'Files are equal! Skipping: (.+?)\s*$'))
CONFLICT_RENAME = re.compile(r'(?:Renaming Path\d copy|Queue copy to Path\d)\s+- (.+?\.conflict\d+)\s*$')
CONFLICT_MOVE = re.compile(r'^(.+?): Moved \(server-side\) to: (.+?\.conflict\d+)\s*$')
LOG_PREFIX = re.compile(r'^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d [A-Z]+\s*: ')


def _relative(name, roots):
    """A name rclone printed, relative to the side it is on (roots: the two sides' paths; a remote one as
    :sftp:<path>, printed by rclone as :sftp{<connection>}:<path>)."""
    n = name.replace('\\', '/')
    if n.startswith(':'):
        n = n.split(':', 2)[-1]
    for r in roots:
        r = r.replace('\\', '/')
        if r.startswith(':'):
            r = r.split(':', 2)[-1]
        r = r.rstrip('/')
        if r and n.startswith(r + '/'):
            return n[len(r) + 1:]
    return n


def run_summary(text, roots=()):
    """What a run did, read from its rclone log (2026-11-11, after a conflict reached a production site unnoticed):
    the last statistics block - files moved, bytes, deleted (put aside in the sync backups), errors - and the files
    changed on BOTH sides since the last run, which bisync keeps as <file>.conflict1 (Path1's) and <file>.conflict2
    (Path2's) while the name itself disappears on both sides - a page served from such a file breaks, so a run with
    conflicts is reported as one. -> {files, bytes, deleted, errors, conflicts: [{file, copies}]}."""
    out = {'files': 0, 'bytes': '', 'deleted': 0, 'errors': 0, 'conflicts': []}
    block, seen, both, equal = None, {}, [], set()
    for line in text.splitlines():
        line = line.rstrip('\r')
        if STATS_START.match(line):
            block = {}
            continue
        if block is not None:
            key, _, value = line.partition(':')
            key, value = key.strip(), value.strip()
            if key == 'Transferred' and 'ETA' in value:
                block['bytes'] = value.split('/', 1)[0].strip()
            elif key == 'Transferred':
                block['files'] = value.split('/', 1)[0].strip()
            elif key in ('Deleted', 'Errors'):
                block[key] = value.split(' ', 1)[0]
            elif key == 'Elapsed time':
                # the last block of the log is the run's total
                out['files'] = int(block['files']) if block.get('files', '').isdigit() else 0
                out['bytes'] = _si(block.get('bytes', ''))
                out['deleted'] = int(block['Deleted']) if block.get('Deleted', '').isdigit() else 0
                out['errors'] = int(block['Errors']) if block.get('Errors', '').isdigit() else 0
                block = None
            elif not line.strip():
                block = None
            continue
        bare = LOG_PREFIX.sub('', line)
        m = BOTH_CHANGED.search(bare)
        if m:
            name = _relative(m.group(1), roots)
            if name not in both:
                both.append(name)
            continue
        m = FILES_EQUAL[0].search(bare) or FILES_EQUAL[1].search(bare)
        if m:
            equal.add(_relative(m.group(1), roots))
            continue
        m = CONFLICT_MOVE.search(bare)
        if m:
            name, copy = _relative(m.group(1), roots), _relative(m.group(2), roots)
        else:
            m = CONFLICT_RENAME.search(bare)
            if not m:
                continue
            copy = _relative(m.group(1), roots)
            name = re.sub(r'\.conflict\d+$', '', copy)
        copies = seen.setdefault(name, [])
        if copy not in copies:
            copies.append(copy)
    # a conflict: changed on both sides and not to the same bytes (an older .conflict copy carried on is none)
    out['conflicts'] = [{'file': n, 'copies': sorted(seen.get(n) or [n + '.conflict1', n + '.conflict2'])}
                        for n in both if n not in equal]
    return out


# the per-file lines of an rclone log, bisync and sync alike: what a run changed, by the name relative to its root
FILE_CHANGE = re.compile(r'^(.+?): (?:Copied|Deleted|Moved|Updated modification time|Removing directory)\b')


def changed_tops(text):
    """The first path components of what a run changed - copied, deleted, moved aside, renamed - read from its log
    (2026-11-11): for a sync of a home's repositories (repos:) the repositories it touched."""
    tops = set()
    for line in text.splitlines():
        m = FILE_CHANGE.match(LOG_PREFIX.sub('', line.rstrip('\r')))
        if not m or m.group(1).startswith('- '):
            continue
        name = m.group(1).replace('\\', '/').strip('/')
        if name and ':' not in name:
            tops.add(name.split('/', 1)[0])
    return tops


def reindex_targets(plan, tops):
    """Where a run that changed something must reindex (2026-11-11: artifacts arrive by sync, and a home whose index
    does not know them fails - "artifact already exists" - or shows what is gone): per side that can have changed
    (both for bisync, the destination otherwise) the cMeta home and its repositories. A side that is a home's repos
    folder (repos:) gives the listed repositories that changed; a side that is one repository of a home
    (<home>/repos/<repo>) gives that repository. A local home is known by its repos.json, a remote one is checked
    there. -> [{side, remote, host, home, repos}]"""
    if not tops or plan.get('reindex') is False:
        return []
    out = []
    for key in (('source', 'destination') if plan['mode'] == 'bisync' else ('destination',)):
        side = plan[key]
        path = str(side['path'])
        parts = [p for p in path.split(':', 2)[-1].split('/')] if side['remote'] else list(Path(path).parts)
        while parts and parts[-1] in ('', '.'):
            parts.pop()
        listed = plan.get('repos')
        if listed is not None:
            if not parts or parts[-1] != 'repos':
                continue
            repos = sorted(t for t in tops if listed == '*' or t in listed)
            home = parts[:-1]
        else:
            if len(parts) < 3 or parts[-2] != 'repos':
                continue
            repos, home = [parts[-1]], parts[:-2]
        if not repos or not home:
            continue
        if side['remote']:
            home = '/'.join(home) or '/'
        else:
            home = str(Path(*home))
            if not (Path(home) / 'repos.json').is_file():
                continue
        out.append({'side': key, 'remote': side['remote'], 'host': side.get('host', 'local'), 'home': home,
                    'repos': repos})
    return out


def banner(word, summary):
    """The verdict in large letters (as cx host sync prints it), the summary under it, a part per line."""
    font = {'S': (' ###', '#   ', ' ## ', '   #', '### '), 'U': ('#  #', '#  #', '#  #', '#  #', ' ## '),
            'C': (' ###', '#   ', '#   ', '#   ', ' ###'), 'E': ('####', '#   ', '### ', '#   ', '####'),
            'F': ('####', '#   ', '### ', '#   ', '#   '), 'A': (' ## ', '#  #', '####', '#  #', '#  #'),
            'I': ('###', ' # ', ' # ', ' # ', '###'), 'L': ('#   ', '#   ', '#   ', '#   ', '####'),
            'D': ('### ', '#  #', '#  #', '#  #', '### '), 'O': (' ## ', '#  #', '#  #', '#  #', ' ## '),
            'N': ('#  #', '## #', '# ##', '#  #', '#  #'), 'T': ('###', ' # ', ' # ', ' # ', ' # '),
            '!': ('#', '#', '#', ' ', '#')}
    rows = ['  '.join(font[c][i] for c in word if c in font) for i in range(5)]
    line = '=' * 100
    return '\n'.join([line] + rows + [''] + ['  ' + p for p in summary.split(' | ')] + [line])


def conflicts_text(summary, sides):
    """What the conflicts of a run are and what to do, a part per ' | ' (sides: the two sides' names)."""
    n = len(summary['conflicts'])
    parts = [f'CONFLICTS: {n} file{"s" if n > 1 else ""} changed on BOTH sides since the last run - kept as .conflict1 '
             f'({sides[0]}) and .conflict2 ({sides[1]}); the name itself is gone on both sides until one is put back']
    parts += ['    ' + c['file'] for c in summary['conflicts'][:20]]
    if n > 20:
        parts.append(f'    ... and {n - 20} more (the run log names them all)')
    parts.append('resolve: on ONE side copy the right version back under its name and delete the conflict copies, '
                 'then run the sync again (it carries the name to the other side and puts the copies aside)')
    return ' | '.join(parts)


def progress_lines(text, state):
    """Of newly appended log text, the lines --progress shows: each statistics block as one line (stats_text) and the
    errors; state carries a partial line and an open block between calls."""
    out = []
    *lines, state['pending'] = (state.get('pending', '') + text).split('\n')
    for line in lines:
        line = line.rstrip('\r')
        if STATS_START.match(line):
            state['block'] = []
        elif state.get('block') is not None:
            if line.startswith('Elapsed time:'):
                out.append('    ' + state['label'] + ' ' + stats_text(state['block'] + [line]))
                state['block'] = None
            elif line.strip():
                state['block'].append(line)
        elif ' ERROR : ' in line:
            out.append('    ' + line)
    return out


@contextmanager
def follow_log(path, label=None):
    """Relay newly appended rclone output, keeping the log as the source of truth; with a label (--progress) only
    the statistics, one line each, and the errors."""
    # Preview, initial mirror and baseline may append to the same run log.
    # Start at its current end so a later stage never replays earlier output.
    with path.open('ab'):
        pass
    with path.open('rb') as stream:
        stream.seek(0, os.SEEK_END)
        stopped = threading.Event()
        errors = []

        def relay():
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            state = {'label': label}

            def show(text):
                if label is None:
                    print(text, end='', flush=True)
                else:
                    for line in progress_lines(text, state):
                        print(line, flush=True)

            try:
                while True:
                    data = stream.read(65536)
                    if data:
                        show(decoder.decode(data))
                    elif stopped.is_set():
                        show(decoder.decode(b'', final=True))
                        break
                    else:
                        stopped.wait(0.1)
            except (OSError, UnicodeError) as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=relay, name='cmeta-sync-log', daemon=True)
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join()
            if errors:
                print('Live display stopped: ' + errors[0] + '; full log: ' + str(path))


# The task's built-in state filters as they were up to 0.55.0: a pair's state made then carries a digest of them with
# the definition's own filters. Such a digest is still accepted (and rewritten at the next success), so that a built-in
# filter added by a release never demands a --resync of every pair (0.55.0.1 added one and every named sync stopped).
LEGACY_STATE_FILTERS = ['- **/sync--*/**', '- **/.cmeta-sync*', '- **/.cmeta-sync-backups/**']


def identity_digests(plan):
    """
    What a pair is: its mode, the definition's own filters (not the task's built-in ones) and both endpoints.
    Returns (identity, its digest, the digest a state of 0.55.0 or before carries for the same pair).
    """
    identity = {'mode': plan['mode'], 'filters': list(plan.get('own_filters', plan['filters'])), 'format': 2}
    for key in ('source', 'destination'):
        identity[key] = {k: plan[key][k] for k in ('path', 'identity', 'target')}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    legacy = dict(identity, filters=LEGACY_STATE_FILTERS + identity['filters'])
    legacy_digest = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    return identity, digest, legacy_digest


class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def access(self, category, command, **params):
        r = self.cm.access(dict(category=self.cmeta['uses_categories'][category],
                                command=command, con=False, **params))
        if r['return']:
            raise ValueError(r.get('error', str(r['return'])))
        return r

    def read(self, path):
        r = self.cm.utils.files.safe_read_file(str(path))
        if r['return']:
            raise ValueError(r['error'])
        return r['data']

    def write(self, path, data):
        r = self.cm.utils.files.safe_write_file(str(path), data, atomic=True)
        if r['return']:
            raise ValueError(r['error'])

    def task(self, ctx, task_ref, **params):
        r = self.cm.access(dict(category=self.category_alias + ',' + self.category_uid,
                                command='run', arg1=task_ref, ctx=ctx, con=False,
                                quiet=ctx['control'].get('quiet', False), **params))
        if r['return']:
            raise ValueError(r.get('error', str(r['return'])))
        return r

    def endpoint(self, ctx, spec, repos):
        if not isinstance(spec, dict) or set(spec) - {'host', 'path', 'cref'}:
            raise ValueError('endpoint must contain host and exactly one of path/cref')
        host = spec.get('host', 'local')
        remote = host != 'local'
        path, cref = spec.get('path'), spec.get('cref')
        if bool(path) == bool(cref):
            raise ValueError('endpoint needs exactly one of path/cref')
        transport = {}
        if remote:
            if cref:
                raise ValueError('remote endpoints use path; cref resolves on the orchestrator only')
            transport = self.access('host', 'sync_endpoint', arg1=str(host).split('::')[-1])
            path = str(path).replace('\\', '/')
            # SFTP interprets a relative path against the SSH login home.
            if path.startswith('~/'):
                path = path[2:]
            if not path or path == '/' or '..' in path.split('/') or '$' in path or '~' in path:
                raise ValueError('use an explicit remote directory or ~/directory, without .. or variables')
            if repos is not None:
                path = posixpath.join(path, 'repos')
            resolved = ':sftp:' + path
        else:
            if cref:
                reference, _, suffix = str(cref).replace('\\', '/').partition('/')
                category, sep, name = reference.partition('::')
                if not sep:
                    raise ValueError('cref must be category::artifact[/subpath]')
                r = self.cm.access(dict(category=category, command='find', arg1=name, con=False))
                if r['return'] or len(r.get('artifacts', [])) != 1:
                    raise ValueError('cref must resolve to exactly one artifact: ' + str(cref))
                base = Path(r['artifacts'][0]['path']).resolve()
                path = base / safe_relative(suffix) if suffix else base
                Path(path).resolve().relative_to(base)
            path = Path(os.path.expandvars(str(path))).expanduser().resolve()
            if repos is not None:
                path /= 'repos'
            if path == Path(path.anchor):
                raise ValueError('select a directory below the filesystem root')
            resolved = str(path)
        return dict(path=resolved, remote=remote, host=host,
                    identity=transport.get('host_uid', 'local'),
                    target=transport.get('target', ''), ssh=transport.get('cmd', ''),
                    host_repos=transport.get('repos', ''))

    def definition(self, ctx, ref):
        ref = str(ref).split('::')[-1]
        r = self.access('sync', 'find', arg1=ref)
        if len(r['artifacts']) != 1:
            raise ValueError('name exactly one sync artifact: ' + ref)
        a = r['artifacts'][0]
        d = self.read(Path(a['path']) / '_desc.yaml')
        allowed = {'authors', 'description', 'mode', 'source', 'destination', 'repos',
                   'dirs', 'exclude', 'exclude_categories', 'resync_mode', 'max_delete',
                   'initial_mode', 'initial_max_delete', 'transfers', 'bwlimit', 'also',
                   'remove_empty_dirs', 'reindex'}
        if not isinstance(d, dict) or set(d) - allowed:
            raise ValueError('unknown sync description fields: ' + str(set(d) - allowed))
        also = d.get('also', [])
        if not isinstance(also, list) or not all(isinstance(ref, str) and ref.strip() for ref in also):
            raise ValueError('also must be a list of sync artifact references')
        defaults = self.cdesc['defaults']
        mode = d.get('mode', defaults['mode'])
        if mode not in ('bisync', 'copy', 'oneway', 'mirror'):
            raise ValueError('mode must be bisync, copy/oneway, or mirror')
        mode = 'copy' if mode == 'oneway' else mode
        remove_empty_dirs = d.get('remove_empty_dirs', defaults.get('remove_empty_dirs', False))
        if not isinstance(remove_empty_dirs, bool):
            raise ValueError('remove_empty_dirs must be a boolean')
        if remove_empty_dirs and mode != 'bisync':
            raise ValueError('remove_empty_dirs is supported only for bisync')
        repos = d.get('repos')
        if repos is not None and repos != '*' and (not isinstance(repos, list) or not repos):
            raise ValueError('repos must be a nonempty list of directory names or "*"')
        if repos is not None and d.get('dirs'):
            raise ValueError('use repos or dirs, not both')
        includes = repos if isinstance(repos, list) else d.get('dirs', [])
        if not isinstance(includes, list):
            raise ValueError('dirs must be a list of relative directories')
        includes = [safe_relative(p) for p in includes]
        sides = [self.endpoint(ctx, d.get(k), repos) for k in ('source', 'destination')]
        if sum(s['remote'] for s in sides) > 1:
            raise ValueError('this prototype supports local/local or local/SSH; run it on one endpoint')
        if not any(s['remote'] for s in sides):
            selected = [[os.path.normcase(os.path.realpath(os.path.join(s['path'], p)))
                         for p in (includes or [''])] for s in sides]
            for p1 in selected[0]:
                for p2 in selected[1]:
                    if os.path.splitdrive(p1)[0] == os.path.splitdrive(p2)[0] and os.path.commonpath([p1, p2]) in (p1, p2):
                        raise ValueError('selected sync directories must not overlap')
        excludes = d.get('exclude', [])
        if not isinstance(excludes, list):
            raise ValueError('exclude must be a list of rclone patterns')
        categories = d.get('exclude_categories', [])
        if not isinstance(categories, list):
            raise ValueError('exclude_categories must be a list of category directory names')
        if categories and repos is None:
            raise ValueError('exclude_categories requires repos; use exclude for ordinary directories')
        for category in categories:
            if (not isinstance(category, str) or not category or category in ('.', '..') or
                    any(c in category for c in '/\\:*?[]{}\r\n')):
                raise ValueError('exclude_categories needs literal category directory names, without paths or globs')
        # Never distribute orchestrator state, logs or backup data, even when
        # someone opts into copying other cache contents.
        filters = list(defaults['state_filters'])
        filters += ['- ' + str(p) for p in excludes]
        for repo in (includes if isinstance(repos, list) else ['*']):
            filters += ['- /' + repo + '/' + category + '/**' for category in categories]
        if includes:
            for p in includes:
                p = safe_relative(p)
                if any(c in p for c in '*?[]{}'):
                    raise ValueError('repo/dir selections are literal names, not globs')
                filters.append('+ /' + p + '/**')
            filters.append('- **')
        for side in sides:
            join = posixpath.join if side['remote'] else os.path.join
            side['selected_paths'] = [join(side['path'], p) for p in includes] if includes else [side['path']]
        parts = a['cmeta_ref_parts']
        uid = parts['artifact_uid']
        alias = parts['artifact_alias']
        initial = d.get('resync_mode', defaults['resync_mode'])
        if initial not in ('newer', 'older', 'path1', 'path2', 'larger', 'smaller'):
            raise ValueError('invalid resync_mode')
        initial_mode = d.get('initial_mode', defaults['initial_mode'])
        if initial_mode not in ('merge', 'mirror') or (initial_mode == 'mirror' and mode != 'bisync'):
            raise ValueError('initial_mode must be merge or mirror; mirror initialization requires bisync')
        initial_max_delete = int(d.get('initial_max_delete', defaults['initial_max_delete']))
        if initial_max_delete < 0:
            raise ValueError('initial_max_delete must be a nonnegative file count')
        max_delete = int(d.get('max_delete', defaults['max_delete_bisync' if mode == 'bisync' else 'max_delete_mirror']))
        if max_delete < 0 or (mode == 'bisync' and max_delete > 100):
            raise ValueError('invalid max_delete (percentage for bisync, count for mirror)')
        transfers = int(d.get('transfers', defaults['transfers']))
        if transfers < 1:
            raise ValueError('transfers must be a positive integer')
        # after a run that changed something, the cMeta repositories it changed are reindexed on each side
        # (2026-11-11); reindex: false for a pair whose homes must not be touched
        reindex = d.get('reindex', True)
        if not isinstance(reindex, bool):
            raise ValueError('reindex must be true or false')
        return dict(alias=alias, uid=uid, cache='local:sync--' + alias + '--' + uid,
                    state_ref='local:sync--' + alias + '--' + uid,
                    source=sides[0], destination=sides[1], mode=mode, filters=filters,
                    # the definition's own filters, after the task's built-in state_filters: what the identity of a
                    # pair is made of (a built-in filter added by a release is not a change of the definition)
                    own_filters=filters[len(defaults['state_filters']):],
                    resync_mode=initial, max_delete=max_delete,
                    initial_mode=initial_mode, initial_max_delete=initial_max_delete,
                    transfers=transfers, bwlimit=str(d.get('bwlimit', '')), also=also,
                    remove_empty_dirs=remove_empty_dirs, reindex=reindex, repos=repos)

    def expanded_plans(self, ctx, refs, ancestors=()):
        # Resolve every linked definition before any transfer or state update.
        plans = []
        for ref in refs:
            plan = self.definition(ctx, ref)
            if plan['uid'] in ancestors:
                raise ValueError('cycle in linked sync definitions: ' + plan['alias'])
            if len(ancestors) >= 32:
                raise ValueError('linked sync definitions exceed 32 levels')
            plans.append(plan)
            plans.extend(self.expanded_plans(ctx, plan['also'], ancestors + (plan['uid'],)))
        return plans

    def command(self, ctx, argv, env):
        return self.task(ctx, 'cmd,c9ba0a88df394d7f', cmd=' '.join(quote(x) for x in argv),
                         env=env, capture_output=False, fail_if_nonzero_return_code=False,
                         print_extra_line=False)

    def transfer(self, ctx, plan, workdir, log, initial, dry, run_id, overwrite_all=False, live=False):
        setup = self.task(ctx, 'setup,a2f9b61079ce4333', name='rclone,e8cb2f6227de4121')
        source, dest = plan['source'], plan['destination']
        remote = next((s for s in (source, dest) if s['remote']), None)
        env = {'RCLONE_SFTP_SSH': remote['ssh']} if remote else {}
        argv = [setup['path'], 'bisync' if plan['mode'] == 'bisync' else
                ('sync' if plan['mode'] == 'mirror' else 'copy'), source['path'], dest['path']]
        argv += ['--log-level', 'INFO', '--log-file', str(log), '--stats', '10s',
                 '--transfers', str(plan['transfers']), '--retries', '1']
        if remote:
            argv += ['--sftp-disable-hashcheck']
        if dry:
            argv += ['--dry-run']
        if overwrite_all:
            argv += ['--ignore-times']
        if plan['bwlimit']:
            argv += ['--bwlimit', plan['bwlimit']]
        for rule in plan['filters']:
            argv += ['--filter', rule]
        if plan['mode'] == 'bisync':
            argv += ['--workdir', str(workdir), '--max-delete', str(plan['max_delete']),
                     '--resilient', '--recover', '--conflict-resolve', 'none', '--conflict-loser', 'num']
            if plan.get('remove_empty_dirs', False):
                argv += ['--remove-empty-dirs']
            if initial:
                argv += ['--resync', '--resync-mode', plan['resync_mode']]
        elif plan['mode'] == 'mirror':
            argv += ['--max-delete', str(plan['max_delete'])]
        # What a run overwrites or deletes: the result artifact sync-backup--<alias>--<uid> of each side's local
        # repository, under <run id>/ - an artifact the index knows (before 2026-10-25: .cmeta-sync-backups beside the
        # synced folder). The local artifact is made now; the remote one gets its _cmeta after the run (mark_backup).
        backup_alias = 'sync-backup--' + plan['state_ref'].split(':', 1)[1].split('--', 1)[1]
        # not "sync_uid": that key is how find_state finds the pair's state artifact, and a second entry with it stops
        # every run ("multiple result entries claim this sync UID")
        local_art = self.access('result', 'get', arg1='local:' + backup_alias,
                                meta={'permanent': True, 'tags': ['sync-backup'], 'backup_of': plan['uid']})['artifact']
        remote_art = None
        for num, side in enumerate((source, dest), 1):
            if plan['mode'] != 'bisync' and num == 1:
                continue
            path = side['path']
            if side['remote']:
                # the local repository of the host's cMeta home (its repositories folder, as the host category
                # knows it: the declared sync.repos_path, else the probed home), whatever folder is synced - the
                # parent of a web root belongs to root (2026-10-25). rclone MOVES the replaced files there, so the
                # synced folder and the host's cMeta home must be on one filesystem.
                base = side.get('host_repos') or '~/CMETA/repos'
                # SFTP interprets a relative path against the SSH login home
                remote_art = posixpath.join(base[2:] if base.startswith('~/') else base, 'local', 'result', backup_alias)
                backup = ':sftp:' + posixpath.join(remote_art, run_id)
            else:
                backup = str(Path(local_art['path']) / run_id)
            argv += ['--backup-dir' + (str(num) if plan['mode'] == 'bisync' else ''), backup]
        # live: every line of the log as it comes; 'progress' (--progress): only its statistics, one line every 10 s
        show_live = live and ctx['control'].get('con')
        if show_live:
            print(('Preview (no files changed)' if dry else 'Syncing files') +
                  (', ' + str(plan['transfers']) + ' files at a time' if live == 'progress' else '') +
                  '; live log: ' + str(log), flush=True)
        with follow_log(log, plan['alias'] if live == 'progress' else None) if show_live else nullcontext():
            r = self.command(ctx, argv, env)
        if log.exists() and ctx['control'].get('con'):
            # Rclone logs contain paths/actions, never file bodies.
            # A first server sync can list hundreds of thousands of log files.
            # Keep the terminal useful; the complete plan stays in the run log.
            if live is not True or not show_live:
                with log.open(encoding='utf-8', errors='replace') as stream:
                    tail = deque(stream, maxlen=60)
                print(''.join(tail))
            print('Full transfer log: ' + str(log))
        if r.get('returncode', 0):
            raise ValueError('rclone failed (exit ' + str(r['returncode']) + '). See ' + str(log))
        if remote_art and not dry:
            self.mark_backup(ctx, setup['path'], env, local_art, remote_art, run_id)

    def mark_backup(self, ctx, rclone, env, local_art, remote_art, run_id):
        """The remote copy of the backup artifact gets the local one's _cmeta once its folder exists there (a run
        put files in it) and has none, so the host's index can know it after its next reindex; nothing otherwise. A
        courtesy after a transfer that succeeded: a failure is a warning, never an error of the sync."""
        def rc(argv):
            # the hash check of rclone's sftp backend runs a command through the external ssh and never returns (an
            # lsf hung a finished sync for ever, 2026-10-25): off, as in the transfer; and a limit, whatever happens
            r = self.task(ctx, 'cmd,c9ba0a88df394d7f', cmd=' '.join(quote(x) for x in argv + ['--sftp-disable-hashcheck']),
                          env=env, capture_output=True, fail_if_nonzero_return_code=False, print_extra_line=False,
                          timeout=120)
            return r.get('returncode', 1) or (1 if r.get('timed_out') else 0)
        try:
            if rc([rclone, 'lsd', ':sftp:' + remote_art]):
                return
            name = next((n for n in ('_cmeta.yaml', '_cmeta.json') if (Path(local_art['path']) / n).exists()), None)
            if not name or not rc([rclone, 'lsf', ':sftp:' + posixpath.join(remote_art, name)]):
                return
            if rc([rclone, 'copyto', str(Path(local_art['path']) / name), ':sftp:' + posixpath.join(remote_art, name)]):
                raise ValueError('rclone copyto failed')
        except Exception as exc:
            print('cMeta warning: the backup artifact on the host is not marked (' + str(exc) +
                  '); its files are there, the next run that adds to it marks it', flush=True)

    def find_state(self, category, uid):
        found = self.cm.access(dict(category=self.cmeta['uses_categories'][category],
                                    command='find', arg1='local:*',
                                    match={'sync_uid': uid}, con=False))
        if found['return'] not in (0, 16):
            raise ValueError(found.get('error', 'cannot find sync state'))
        artifacts = found.get('artifacts', [])
        if len(artifacts) > 1:
            raise ValueError('multiple ' + category + ' entries claim this sync UID; resolve duplicate state first')
        return artifacts[0] if artifacts else None

    def state_artifact(self, plan):
        # The UID owns the state. Renaming a definition must not look like a
        # brand new pair just because its friendly result alias changed.
        artifact = self.find_state('result', plan['uid'])
        legacy = None if artifact else self.find_state('cache', plan['uid'])
        oldroot = Path(legacy['path']) if legacy else None
        if oldroot and (oldroot / 'migrated-to-result.json').exists():
            raise ValueError('migrated result state is missing; restore it, do not reuse the stale cache archive')
        oldlock = str(oldroot.parent / '.cmeta-sync') if oldroot else None
        locked = self.cm.utils.files.lock_path(oldlock, timeout=1) if oldlock else None
        if locked and locked['return']:
            raise ValueError('legacy cache sync is running; migration must wait')
        try:
            if oldroot and list((oldroot / 'bisync').glob('*.lck')):
                raise ValueError('legacy bisync lock exists; inspect it before migrating state')
            artifact = artifact or self.access(
                'result', 'get', arg1=plan['state_ref'],
                meta={'permanent': True, 'tags': ['sync-state'], 'sync_uid': plan['uid']})['artifact']
            root = Path(artifact['path'])
            if artifact['cmeta'].get('sync_uid') != plan['uid']:
                raise ValueError('sync result belongs to another artifact')
            pending = root / 'migration-pending.json'
            if pending.exists():
                raise ValueError('state migration was interrupted; inspect the result and retained cache archive')
            if oldroot:
                self.write(pending, dict(source=str(oldroot)))
                for name in ('state.json', 'bisync', 'runs', 'last-result.json'):
                    source = oldroot / name
                    if source.is_dir():
                        shutil.copytree(source, root / name)
                    elif source.exists():
                        shutil.copy2(source, root / name)
                self.write(oldroot / 'migrated-to-result.json', dict(result=str(root), sync_uid=plan['uid']))
                pending.unlink()
            return artifact
        finally:
            if oldlock:
                self.cm.utils.files.unlock_path(oldlock, locked['file_lock'])

    def execute(self, ctx, plan, dry_run, resync, initialize=False, require_initialized=False,
                migrate_state=False, live=False):
        artifact = self.state_artifact(plan)
        root = Path(artifact['path'])
        if migrate_state:
            return dict(status='state-ready', state=str(root))
        # Serialize sync tasks in this orchestrator, including overlapping chains.
        # Rclone also locks each baseline. Other orchestrators must not own this pair.
        lockpath = str(root.parent / '.cmeta-sync')
        locked = self.cm.utils.files.lock_path(lockpath, timeout=1)
        if locked['return']:
            raise ValueError('another sync is running in this cMeta home')
        try:
            statefile = root / 'state.json'
            identity, digest, legacy_digest = identity_digests(plan)
            state = self.read(statefile) if statefile.exists() else {}
            if initialize and state.get('last_success'):
                raise ValueError('already initialized; use the regular bisync command instead of --initialize')
            if require_initialized and not state.get('last_success'):
                raise ValueError('successful bisync state is missing; restore it or explicitly initialize a new pair')
            if plan['mode'] == 'bisync' and plan['initial_mode'] == 'mirror' and not state.get('last_success'):
                if not initialize and (state or not resync):
                    raise ValueError('first source mirror requires --initialize; after lost state use reviewed merge recovery')
            if state and state.get('identity') not in (digest, legacy_digest) and not resync:
                raise ValueError('endpoints/filters changed; review --plan, then explicitly use --resync')
            if plan['mode'] == 'bisync' and state and state.get('status') == 'initializing' and not resync:
                raise ValueError('initialization was interrupted; inspect logs, then use --resync explicitly')
            workdir = root / 'bisync'
            if not state and workdir.exists() and any(workdir.iterdir()) and not resync:
                raise ValueError('state.json is missing but listings exist; inspect before explicit --resync')
            initial = not state or resync
            # A source-authoritative bootstrap happens only before the first
            # successful baseline. Explicit recovery later must never repeat it.
            bootstrap = (initial and plan['mode'] == 'bisync' and
                         plan['initial_mode'] == 'mirror' and initialize and not state.get('last_success'))
            preview_plan = dict(plan, mode='mirror', max_delete=plan['initial_max_delete']) if bootstrap else plan
            if not initial and plan['mode'] == 'bisync' and not workdir.exists():
                raise ValueError('bisync baseline missing; restore it or explicitly review --resync')
            root.joinpath('runs').mkdir(exist_ok=True)
            run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
            log = root / 'runs' / (run_id + '.log')
            print(plan['alias'] + ': ' + ('initialize' if initial else plan['mode']) +
                  '; state: ' + str(root)) if ctx['control'].get('con') else None
            # Only the initial real run creates a destination. Missing established
            # roots must fail, rather than look like an intentional mass deletion.
            if initial and not dry_run:
                source, dest = plan['source'], plan['destination']
                if not source['remote'] and not Path(source['path']).is_dir():
                    raise ValueError('source directory does not exist: ' + source['path'])
                if not dest['remote']:
                    Path(dest['path']).mkdir(parents=True, exist_ok=True)
                else:
                    setup = self.task(ctx, 'setup,a2f9b61079ce4333', name='rclone,e8cb2f6227de4121')
                    r = self.command(ctx, [setup['path'], 'mkdir', dest['path'], '--sftp-disable-hashcheck'],
                                     {'RCLONE_SFTP_SSH': dest['ssh']})
                    if r.get('returncode', 0):
                        raise ValueError('cannot prepare remote destination')
            if dry_run or not ctx['control'].get('quiet', False):
                # --dry-run writes scratch listings. Never let these overwrite
                # the only baseline of an established pair.
                with tempfile.TemporaryDirectory(prefix='preview-', dir=root) as temp:
                    preview = Path(temp) / 'bisync'
                    if workdir.exists():
                        shutil.copytree(workdir, preview)
                    self.transfer(ctx, preview_plan, preview, log, initial, True, run_id,
                                  overwrite_all=bootstrap, live=live)
                if dry_run:
                    # what the run would do, from the preview's log; a conflict is said now, before any real run
                    summary = run_summary(log.read_text(encoding='utf-8', errors='replace') if log.exists() else '',
                                          (plan['source']['path'], plan['destination']['path']))
                    if ctx['control'].get('con'):
                        print(f'DRY RUN {plan["alias"]}: {summary["files"]} files would move'
                              + (f' ({summary["bytes"]})' if summary['bytes'] else '')
                              + f', {summary["deleted"]} deleted (put aside in the sync backups)')
                        if summary['conflicts']:
                            print('WOULD ' + conflicts_text(summary, self._sides(plan)).replace(' | ', '\n'))
                    return dict(return_code=0, preview=True, state=str(root), log=str(log), summary=summary)
                try:
                    answer = input('Proceed with these copies/deletions (Y/n)? ').strip().lower()
                except EOFError:
                    raise ValueError('no interactive input; use -q to accept the displayed definition')
                if answer not in ('', 'y', 'yes'):
                    return dict(cancelled=True, state=str(root), log=str(log))
            self.write(statefile, dict(identity=digest, definition=identity,
                                       status='initializing' if initial else 'running',
                                       last_success=state.get('last_success')))
            started = time.monotonic()
            try:
                if bootstrap:
                    self.transfer(ctx, preview_plan, workdir, log, True, False, run_id,
                                  overwrite_all=True, live=live)
                baseline_plan = dict(plan, resync_mode='path1') if bootstrap else plan
                self.transfer(ctx, baseline_plan, workdir, log, initial, False, run_id, live=live)
            except Exception as exc:
                self.write(root / 'last-result.json', dict(status='failed', error=str(exc), log=str(log)))
                raise
            self.write(statefile, dict(identity=digest, definition=identity, status='ok', last_success=run_id))
            # the verdict (2026-11-11): what moved, and the files both sides changed - a run with conflicts is no
            # success, however well rclone did: the names are gone on both sides until someone puts one back
            text = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
            summary = run_summary(text, (plan['source']['path'], plan['destination']['path']))
            elapsed = round(time.monotonic() - started, 3)
            result = dict(status='conflicts' if summary['conflicts'] else 'ok', state=str(root), log=str(log),
                          initial=initial, elapsed=elapsed, summary=summary)
            # the homes learn what came: the changed repositories reindexed on each side (a failure is a warning)
            targets = reindex_targets(plan, changed_tops(text))
            if targets:
                result['reindexed'] = self.reindex(ctx, targets)
            text = (f'{plan["alias"]}: {summary["files"]} files moved' + (f' ({summary["bytes"]})' if summary['bytes'] else '')
                    + f', {summary["deleted"]} deleted (put aside in the sync backups), {duration_text(elapsed)}')
            if summary['errors']:
                text += f' | errors: {summary["errors"]} - see the run log {log}'
            if summary['conflicts']:
                result['error'] = conflicts_text(summary, self._sides(plan))
                text += ' | ' + result['error']
            result['verdict'] = {'word': 'CONFLICTS' if summary['conflicts'] else 'SUCCESS', 'text': text}
            self.write(root / 'last-result.json', result)
            if ctx['control'].get('con'):
                print(banner(result['verdict']['word'] + '!', 'STATUS: ' + result['verdict']['word'] + ' - ' + text), flush=True)
            return result
        finally:
            self.cm.utils.files.unlock_path(lockpath, locked['file_lock'])

    def reindex(self, ctx, targets):
        """The repositories of each target reindexed where they live: this home in this process, another home on this
        machine by the same engine (python -m cmeta with its CMETA_HOME), a home on a host through cx host run (the
        home's own .venv cx, else cx). A reindex is incremental - a second or two when little changed. A failure is a
        warning, never the sync's: the files are there, a later reindex finds them. -> [{side, home, host, ok, failed}]"""
        con = ctx['control'].get('con')
        here = os.path.normcase(os.path.realpath(str(self.cm.home_path)))
        done = []
        for t in targets:
            began = time.monotonic()
            ok, error = [], ''
            if t['remote']:
                home = t['home'] if t['home'].startswith('/') else '$HOME/' + shlex.quote(t['home'])
                script = ('H=' + home + '; test -f $H/repos.json || { echo NOHOME; exit 0; }; CX=$H/.venv/bin/cx; '
                          'test -x $CX || CX=cx; for r in ' + ' '.join(shlex.quote(r) for r in t['repos']) +
                          '; do if CMETA_HOME=$H $CX repo reindex $r -q </dev/null >/dev/null 2>&1; '
                          'then echo REINDEXED $r; else echo FAILED $r; fi; done')
                r = self.cm.access({'category': self.cmeta['uses_categories']['host'], 'command': 'run',
                                    'arg1': str(t['host']).split('::')[-1], 'arg2': script, 'capture': True,
                                    'timeout': 900, 'con': False, 'quiet': True})
                out = '' if r.get('return') else ''.join(str(o.get('stdout', '')) for o in (r.get('outputs') or {}).values())
                ok = [x.split(' ', 1)[1].strip() for x in out.splitlines() if x.startswith('REINDEXED ')]
                error = r.get('error', '') if r.get('return') else ('no cMeta home there' if 'NOHOME' in out else '')
            elif os.path.normcase(os.path.realpath(t['home'])) == here:
                for repo in t['repos']:
                    r = self.cm.access({'category': 'repo', 'command': 'reindex', 'arg1': repo, 'con': False, 'quiet': True})
                    if r.get('return'):
                        error = r.get('error', '')
                    else:
                        ok.append(repo)
            else:
                env = dict(os.environ, CMETA_HOME=t['home'])
                for k in ('CMETA_HOME2', 'CMETA_INTERNAL_REPO_PATH', 'CMETA_TOOL_EXTRA_PATHS'):
                    env.pop(k, None)
                for repo in t['repos']:
                    try:
                        p = subprocess.run([sys.executable, '-m', 'cmeta', 'repo', 'reindex', repo, '-q'], env=env,
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           timeout=900)
                        if p.returncode == 0:
                            ok.append(repo)
                        else:
                            error = p.stderr.decode('utf-8', 'replace').strip()[-300:] or 'exit %d' % p.returncode
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        error = str(exc)
            failed = [r for r in t['repos'] if r not in ok]
            where = (str(t['host']).split('::')[-1].split(',')[0] + ':' if t['remote'] else '') + t['home']
            done.append({'side': t['side'], 'home': t['home'], 'host': t['host'], 'ok': ok, 'failed': failed,
                         'error': error, 'elapsed': round(time.monotonic() - began, 1)})
            if con:
                if ok:
                    print('reindexed ' + ', '.join(ok) + ' in ' + where + ' (%.1f s)' % (time.monotonic() - began), flush=True)
                if failed or error:
                    print('cMeta warning: could not reindex ' + (', '.join(failed) or 'there') + ' in ' + where +
                          (' - ' + error if error else '') + ' - the files are there; reindex that home by hand', flush=True)
        return done

    @staticmethod
    def _sides(plan):
        """The two sides of a plan as a person reads them: the source / the destination, and where it is - a remote
        side by its host, a local one by the end of its folder."""
        out = []
        for word, s in (('the source', plan['source']), ('the destination', plan['destination'])):
            if s.get('remote'):
                out.append(f'{word} on {s.get("host") or "the remote side"}')
            else:
                parts = [p for p in re.split(r'[\\/]', str(s.get('path') or '')) if p]
                out.append(f'{word} ...{"/".join(parts[-3:])}' if len(parts) > 3 else f'{word} {s.get("path")}')
        return tuple(out)

    def run(self, ctx: dict, name: str = None, names: list = None,
            plan: bool = False, dry_run: bool = False, resync: bool = False,
            resync_mode: str = None, passes: int = 1, initialize: bool = False,
            require_initialized: bool = False, migrate_state: bool = False, live: bool = False,
            remove_empty_dirs: bool = None, progress: bool = False, transfers: int = None):
        """Run reusable sync artifacts; omit name to list them.

        cxt sync NAME [--plan | --dry-run] [-q]
        cxt sync --names,=FIRST,SECOND,FIRST [-q]
        Names are an ordered list (duplicates intentional); alias,UID refs work
        with --names as a JSON list. --passes repeats the sequence, default 1.
        A definition's also list runs linked syncs afterwards, each with its own state.
        --plan resolves definitions without connecting or writing sync state.
        --dry-run uses rclone with scratch listings; both bisync roots must exist.
        --initialize explicitly starts a new pair and refuses an existing success.
        --require-initialized refuses missing success state, including after deletion.
        initial_mode: mirror requires --initialize; default merge remains compatible.
        --migrate-state imports legacy cache state into result without transferring data.
        --resync is explicit recovery after reviewing changed filters or lost state.
        --live shows file operations and periodic statistics while rclone runs;
        the complete log is still saved. Works with -q and --dry-run.
        --remove-empty-dirs opts bisync into cleaning included empty directories
        on both sides; excluded directories and the transfer roots are preserved.
        The default remains unchanged unless enabled in a definition or on the CLI.
        --progress shows one line every 10 s while rclone runs (files and bytes
        moved of those to move, %, speed, time left) and the errors; --live wins.
        --transfers=N copies N files at once in this run (each definition's
        "transfers", 4 by default): 8-16 for many small files.
        """
        try:
            if initialize and require_initialized:
                raise ValueError('choose --initialize or --require-initialized, not both')
            if migrate_state and (initialize or require_initialized or resync or dry_run):
                raise ValueError('--migrate-state cannot be combined with transfer/recovery options')
            refs = names if names is not None else ([name] if name else [])
            if isinstance(refs, str):
                refs = [refs]
            if not refs:
                r = self.cm.access(dict(category=self.cmeta['uses_categories']['sync'],
                                        command='find', con=False))
                if r['return'] not in (0, 16):
                    return r
                found = r.get('artifacts', [])
                if ctx['control'].get('con'):
                    print('Available syncs:')
                    for a in found:
                        p = a['cmeta_ref_parts']
                        print('  ' + p['artifact_alias'] + ',' + p['artifact_uid'])
                return {'return': 0, 'syncs': found}
            if not isinstance(refs, list) or not all(isinstance(n, str) for n in refs):
                raise ValueError('names must be a list of sync artifact references')
            if not 1 <= int(passes) <= 10:
                raise ValueError('passes must be between 1 and 10')
            plans = self.expanded_plans(ctx, refs)
            if transfers not in (None, '', True):
                try:
                    transfers = int(transfers)
                except (TypeError, ValueError):
                    transfers = 0
                if not 1 <= transfers <= 64:
                    raise ValueError('transfers is how many files are copied at once: 1 to 64 (4 by default; 8-16 for many small files)')
                for p in plans:
                    p['transfers'] = transfers
            if progress and not live:
                live = 'progress'           # the statistics only, one line every 10 s (--live shows every line)
            if remove_empty_dirs is not None:
                for p in plans:
                    p['remove_empty_dirs'] = bool(remove_empty_dirs)
                    if p['remove_empty_dirs'] and p['mode'] != 'bisync':
                        raise ValueError('remove_empty_dirs is supported only for bisync')
            if resync_mode:
                if resync_mode not in ('newer', 'older', 'path1', 'path2', 'larger', 'smaller'):
                    raise ValueError('invalid resync_mode')
                for p in plans:
                    p['resync_mode'] = resync_mode
            if ctx['control'].get('con'):
                for p in plans:
                    print(p['alias'] + ' [' + p['mode'] + ']')
                    for key in ('source', 'destination'):
                        print('  ' + key + ' (' + str(p[key]['host']) + '):')
                        for path in p[key]['selected_paths']:
                            print('    ' + path)
                    if p['mode'] == 'bisync' and p['initial_mode'] == 'mirror':
                        print('  before first success: mirror source to destination, then establish bisync')
                        print('  destination-only/overwritten files backed up; initial delete limit: ' +
                              str(p['initial_max_delete']))
                    else:
                        print('  initial winner: ' + p['resync_mode'] + '; overwritten files backed up')
                    print('  filters: ' + ', '.join(p['filters']))
                    if p.get('remove_empty_dirs'):
                        print('  remove included empty directories on both sides after successful bisync')
                    print('  state: result::' + p['state_ref'])
            if plan:
                return {'return': 0, 'plans': plans}
            results = []
            seen = set()
            for _ in range(int(passes)):
                for p in plans:
                    result = self.execute(ctx, p, dry_run, resync and p['uid'] not in seen,
                                          initialize and p['uid'] not in seen, require_initialized, migrate_state,
                                          live=live)
                    seen.add(p['uid'])
                    results.append(dict(name=p['alias'], **result))
                    if result.get('cancelled'):
                        return {'return': 0, 'cancelled': True, 'results': results}
                    # a conflict stops the sequence: the next syncs (a chain's step to a production site) would
                    # carry the renamed copies on and the missing name with them
                    if result.get('status') == 'conflicts':
                        return {'return': 1, 'error': result['error'], 'results': results}
            return {'return': 0, 'results': results}
        except (ValueError, OSError, TypeError, KeyError) as exc:
            return self.cm.error(str(exc))
