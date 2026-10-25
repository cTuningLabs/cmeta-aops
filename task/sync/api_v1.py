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
import shlex
import shutil
import tempfile
import threading
import time
import uuid

from task_c36be4b9314a45e0.api.ctask import InitCTask


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


@contextmanager
def follow_log(path):
    """Relay newly appended rclone output, keeping the log as the source of truth."""
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
            try:
                while True:
                    data = stream.read(65536)
                    if data:
                        print(decoder.decode(data), end='', flush=True)
                    elif stopped.is_set():
                        print(decoder.decode(b'', final=True), end='', flush=True)
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
                    target=transport.get('target', ''), ssh=transport.get('cmd', ''))

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
                   'remove_empty_dirs'}
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
        return dict(alias=alias, uid=uid, cache='local:sync--' + alias + '--' + uid,
                    state_ref='local:sync--' + alias + '--' + uid,
                    source=sides[0], destination=sides[1], mode=mode, filters=filters,
                    # the definition's own filters, after the task's built-in state_filters: what the identity of a
                    # pair is made of (a built-in filter added by a release is not a change of the definition)
                    own_filters=filters[len(defaults['state_filters']):],
                    resync_mode=initial, max_delete=max_delete,
                    initial_mode=initial_mode, initial_max_delete=initial_max_delete,
                    transfers=transfers, bwlimit=str(d.get('bwlimit', '')), also=also,
                    remove_empty_dirs=remove_empty_dirs)

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
                remote_art = posixpath.join(posixpath.dirname(path[6:]), 'local', 'result', backup_alias)
                backup = ':sftp:' + posixpath.join(remote_art, run_id)
            else:
                backup = str(Path(local_art['path']) / run_id)
            argv += ['--backup-dir' + (str(num) if plan['mode'] == 'bisync' else ''), backup]
        show_live = live and ctx['control'].get('con')
        if show_live:
            print(('Preview (no files changed)' if dry else 'Syncing files') +
                  '; live log: ' + str(log), flush=True)
        with follow_log(log) if show_live else nullcontext():
            r = self.command(ctx, argv, env)
        if log.exists() and ctx['control'].get('con'):
            # Rclone logs contain paths/actions, never file bodies.
            # A first server sync can list hundreds of thousands of log files.
            # Keep the terminal useful; the complete plan stays in the run log.
            if not show_live:
                with log.open(encoding='utf-8', errors='replace') as stream:
                    tail = deque(stream, maxlen=60)
                print(''.join(tail))
            print('Full transfer log: ' + str(log))
        if r.get('returncode', 0):
            raise ValueError('rclone failed (exit ' + str(r['returncode']) + '). See ' + str(log))
        if remote_art and not dry:
            self.mark_backup(ctx, setup['path'], env, local_art, remote_art, run_id)

    def mark_backup(self, ctx, rclone, env, local_art, remote_art, run_id):
        """The remote copy of the backup artifact gets the local one's _cmeta when this run put files there (rclone
        made the run folder), so the host's index can know it after its next reindex; nothing otherwise."""
        def rc(argv):
            return self.task(ctx, 'cmd,c9ba0a88df394d7f', cmd=' '.join(quote(x) for x in argv), env=env,
                             capture_output=True, fail_if_nonzero_return_code=False, print_extra_line=False)
        if rc([rclone, 'lsd', ':sftp:' + posixpath.join(remote_art, run_id)]).get('returncode', 1):
            return
        name = next((n for n in ('_cmeta.yaml', '_cmeta.json') if (Path(local_art['path']) / n).exists()), None)
        if not name or not rc([rclone, 'lsf', ':sftp:' + posixpath.join(remote_art, name)]).get('returncode', 1):
            return
        rc([rclone, 'copyto', str(Path(local_art['path']) / name), ':sftp:' + posixpath.join(remote_art, name)])

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
                    return dict(return_code=0, preview=True, state=str(root), log=str(log))
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
            result = dict(status='ok', state=str(root), log=str(log), initial=initial,
                          elapsed=round(time.monotonic() - started, 3))
            self.write(root / 'last-result.json', result)
            return result
        finally:
            self.cm.utils.files.unlock_path(lockpath, locked['file_lock'])

    def run(self, ctx: dict, name: str = None, names: list = None,
            plan: bool = False, dry_run: bool = False, resync: bool = False,
            resync_mode: str = None, passes: int = 1, initialize: bool = False,
            require_initialized: bool = False, migrate_state: bool = False, live: bool = False,
            remove_empty_dirs: bool = None):
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
            return {'return': 0, 'results': results}
        except (ValueError, OSError, TypeError, KeyError) as exc:
            return self.cm.error(str(exc))
