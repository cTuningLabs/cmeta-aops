# Reusable synchronization definitions

`sync` artifacts describe **what** to synchronize. Host artifacts describe
**how to connect**. `task::sync` resolves both and runs rclone through the existing
`setup` and `cmd` tasks. The default mode is bidirectional synchronization.

```text
cxt sync                              # list definitions; transfers nothing
cxt sync my-pair --plan                # endpoints, selection, policies; no connection
cxt sync my-pair --dry-run             # rclone preview, without changing either tree
cxt sync my-pair --initialize          # first run only; refuses an existing success
cxt sync my-pair --require-initialized # regular bisync; refuses missing success state
cxt sync my-pair                       # preview, then Proceed (Y/n)?
cxt sync my-pair -q                    # run without preview/questions
cxt sync my-pair --live                # show file operations while syncing
cxt sync my-pair --live -q             # live output without preview/questions
cx sync run my-pair                    # same task through the category
cxt sync --names,=first,second,first -q # ordered sequence; repeats are intentional
cxt sync --names,=first,second --passes=2 -q
```

The task runs on an **orchestrator** that can access both endpoints. This prototype
supports local/local and local/SSH in either direction. It stops on the first
failure or declined confirmation. No argument lists definitions; it never means
“run everything”. `--names` accepts a list, so UID-qualified references can be
passed from a YAML pipeline or the Python API without splitting their commas.

An individual definition can include an ordered `also` list of other sync
artifacts, allowing one named command to synchronize several independent pairs:

```yaml
also:
  - my-orchestrator-repo,0123456789abcdef
  - my-private-runtime-repo,fedcba9876543210
```

The definition's own pair runs first, followed by its linked definitions and
their links. Each pair keeps its own endpoints, filters, backups and result
baseline. `--plan` shows the complete sequence. All definitions are resolved
before transfers; missing references, invalid lists and cycles fail beforehand.
UID-qualified links survive a definition rename. Repeated references preserve
their order, as with `--names`. CLI options apply to every pair in the sequence.
Initialize a newly added mirror pair separately with `--initialize` before using
an established chain with `--require-initialized`. Adding links alone does not
change the original pair's endpoint/filter identity or reset its baseline.
Definitions without `also` keep their existing behavior.

## Definition

Create a category artifact, then write `_desc.yaml` beside its `_cmeta.yaml`:

```text
cx sync add my-repo:my-pair --yaml
```

```yaml
authors: Your name
description: Workstation project repositories and the server copy.

mode: bisync
source:
  host: local
  path: /home/me/project/CMETA

destination:
  host: host::my-server,0123456789abcdef
  path: ~/CMETA-PROJECT

repos: [local, my-project-repo]

exclude_categories: [cache, tmp]

exclude:
  - /local/_cmr.*
  - /local/config/default/**
  - '**/.git/**'
  - '**/.venv/**'
  - '**/__pycache__/**'

resync_mode: newer
max_delete: 50
transfers: 4
# bwlimit: 10M
```

* `host: local` means the machine running the command, not a fleet artifact named
  local. A different value resolves a registered host. The fleet plugin must expose
  `cx host sync_endpoint <host>` (a read-only SSH transport resolver). Its existing
  address, port, key artifact and SSH options are reused. Local/local sync needs no
  fleet plugin. No SSH credentials belong in a public sync definition.
* Exactly one of `path` or `cref` identifies each endpoint. A local endpoint may use
  `cref: project::my-project,0123456789abcdef/CMETA`. Subpaths cannot contain `..`
  or escape through symlinks. Local paths expand environment variables and `~`.
* On an SSH endpoint, `~/directory` means a directory under the SSH login home.
  Absolute POSIX paths also work. Remote artifact references and shell variables
  are not resolved by this prototype.
* With `repos`, endpoint paths denote **CMETA homes**, and the transfer roots are
  their `repos/` directories. Use directory names in a list or `repos: '*'` for all
  repositories. Home-level indexes and `repos.json` are not transferred.
  The plan prints the full selected paths, e.g. `/home/me/project/CMETA/repos/local`.
* Without `repos`, paths are ordinary directories. Optional `dirs: [src, docs]`
  selects relative subdirectories. Omit `dirs` to select the whole tree. Do not
  combine `dirs` and `repos`.
* `exclude` contains rclone filter patterns relative to the transfer roots.
  A leading `/` anchors a pattern; exclusions precede the selected repositories
  or directories. Directories need `/**`. Keep the same selection across runs.
* `exclude_categories: [log]` omits the `log` category directory in every selected
  repository, on both endpoints. It requires `repos` and takes literal directory
  names, including names with dots; it does not resolve aliases/UIDs. It also works
  with `repos: '*'`. It only matches categories immediately inside each repository,
  so an artifact's nested `doc/example/log/` directory remains included.
  Omit it or use `[]` to add no category exclusions. For just one repository, use
  `exclude: ['/local/log/**']`; for part of a category, use a pattern such as
  `/local/config/default/**` instead.
* Endpoint selections must not overlap. A nested CMETA home is supported when
  the selected directories are disjoint, e.g. only the parent home's `local`
  repository and a project home beneath its unselected `fgg` repository.

The task always excludes its reserved `sync--*` state directories and
`.cmeta-sync*` locks/backups. Other exclusions are explicit in the definition;
there is no hidden rule to omit user/config records. Defaults live in the task's
own `_desc.yaml`.

Excluded files already present on either endpoint are left in place, including
in mirror mode; they are not copied, updated or deleted. To exclude `log` later,
edit `exclude_categories` in each affected definition. If a bisync baseline already
exists, review `--plan`, then run `--resync --dry-run` and `--resync` to establish
the new selection. Adding or removing exclusions never silently resets a baseline.

## Modes and first run

Bisync can remove included empty directories on both endpoints after a successful
run. Enable it in the sync definition with `remove_empty_dirs: true`, or override
it for a run with `--remove-empty-dirs` (`--remove-empty-dirs=no` disables it).
The compatible default is false. Transfer roots, excluded directories, nonempty
directories and files are preserved. It also removes empty ancestor directories
left by deleted artifacts; categories with metadata are nonempty and remain.
Dry runs only preview the removals. This uses rclone bisync's existing
`--remove-empty-dirs` behavior and does not change the file selection or require
a resync of an established baseline. It is a bisync option, not a copy/mirror one.

| Mode | Behavior |
|---|---|
| `bisync` (default) | Changes and deletions propagate both ways relative to the last successful baseline. |
| `copy` or `oneway` | Source → destination; extra destination files remain. |
| `mirror` | Source → destination; selected destination files absent from source are deleted. |

On its first real invocation, bisync creates a missing **destination** and runs
`--resync`. A missing source is an error. During initialization, the union of both
trees is kept; when the same filename differs, `resync_mode` chooses the winner:
`newer` (default), `older`, `path1` (source), `path2` (destination), `larger`, or
`smaller`. Overwritten versions are backed up. `--resync-mode=path1` overrides the
definition's initial policy. On later runs this parameter does not trigger a
resync by itself.

For a source-authoritative first copy, a bisync definition may instead specify:

```yaml
initial_mode: mirror
initial_max_delete: 100
```

Run it with `--initialize`. Before its first successful baseline, this mirrors the selected source tree to
the destination, including replacing files even with identical size/timestamps.
Overwritten and destination-only files go to the destination backup tree; excluded
files stay untouched. It then initializes bisync with source preference and records
success only after both steps complete. The preview shows the initial mirror.
Repeating `--initialize` after success is refused. For daily runs, use
`--require-initialized`: even if the entire result disappears, it stops before
transferring data. A plain invocation of a mirror-initialized definition also
refuses to initialize silently when state is missing.
`initial_max_delete` is a destination-only file count limit (default 100), separate
from the later bisync percentage. An interrupted initialization requires explicit
review/retry with `--initialize --resync`; the initial mirror may have partially completed.

After the first success, ordinary runs bisync automatically. Even an explicit
later `--resync` merges to rebuild the baseline rather than repeating the initial
mirror. Keep writers quiet during initialization: the copy and baseline are
sequential operations, not an atomic snapshot. Omitting `initial_mode` preserves
the original `merge` behavior described above.

Normal bisync conflicts preserve both versions with rclone's numbered conflict
names. This is a file sync, not a merge of JSON records or Git branches. Inspect
conflict files before using them as application data. Quiet mode skips questions,
but retains conflicts, backups and rclone's deletion/error checks.

Overwritten/deleted data is retained on the **same endpoint filesystem** in:

```text
<parent-of-transfer-root>/.cmeta-sync-backups/<sync-UID>/<run-id>/
```

Backups have no automatic expiry in this prototype. Monitor their space usage.
`max_delete` is a percentage for bisync (default 50) and a file count for mirror
(default 100). Empty or unexpectedly missing established roots fail rather than
being recreated. Rclone's other integrity checks stay enabled.

`--plan` works before a destination exists. `--dry-run` is an actual rclone preview;
for bisync, both roots must already exist. The ordinary first invocation prepares
the destination before previewing and asking, so declining can leave empty
directories but copies no files. Subsequent runs use the baseline automatically.

## State, recovery and concurrency

Each definition owns a persistent **result** artifact in the orchestrator's current home:

```text
result::local:sync--<alias>--<UID>/
  _cmeta.json            # permanent, tagged sync-state
  state.json            # endpoint/filter identity and initialization status
  bisync/               # rclone listings, recovery listings and lock
  runs/<run-id>.log      # actions and rclone statistics
  last-result.json      # last real transfer outcome and duration
```

The UID avoids collisions between definitions with the same alias in different
repositories. State is found by UID, so a renamed definition keeps its original
result and baseline (the result alias retains the original friendly name).
The task itself has `cache: false`; state storage never suppresses the next sync.
State is outside the cache category, so `cx cache rm -f` cannot select it.
`permanent: true` also blocks ordinary deletion through `cx result rm` until the
owner deliberately removes that protection. Back up the result directory: a manual
filesystem deletion or disk failure still loses the baseline.

Earlier versions stored `cache::sync--...`. On first use, the task copies any such
state and listings unchanged into result under the old sync lock. The legacy cache
is retained as an archive with `migrated-to-result.json`; future runs only update
result. A missing migrated result never silently falls back to that stale archive.
An interrupted migration leaves `migration-pending.json` and stops for inspection.
You can migrate/prepare state without connecting to either endpoint:

```text
cxt sync my-pair --migrate-state
```

This does not migrate older `cx host sync` workdirs, which remain separate.

By default the terminal shows the last 60 log lines after each stage and the full
log's path. Add `--live` to show rclone's INFO output as it arrives: copied files,
deletions/backups, conflicts/errors and transfer statistics every 10 seconds
while work is in progress. File completion messages appear after each copy;
this is not a percentage display for each individual file. Previews are marked
separately, and the complete log is still saved in `runs/<run-id>.log`.
`--live` works with `--dry-run`, `--initialize`, `--require-initialized`, and `-q`;
quiet mode skips questions, not the requested live output. Omitting `--live`
retains the shorter end-of-stage display. Programmatic `con=False` suppresses
the task's terminal log display even when `live=True`.

Deep paths can exceed rclone's combined baseline-filename component limit;
use shorter endpoint paths if rclone reports that filename error. Changing an
established path requires reviewing/reinitializing the baseline.

Dry runs copy listings to scratch directories inside that result entry, leaving
the real baseline unchanged. `--require-initialized` protects against complete
state loss; existing baselines and changed definitions have additional guards.
Rclone uses `--resilient --recover` for
recoverable interruptions. If recovery fails, inspect the run log and backups,
then explicitly review and rebuild:

```text
cxt sync my-pair --resync --dry-run
cxt sync my-pair --resync                 # preview and confirmation
```

Resync is a merge, so it can restore a file deleted on one side. Never put
`--resync` into an everyday launcher. Stale rclone locks are not automatically
removed: first confirm no prior process is running, then follow the exact lock
path in rclone's diagnostic. An orchestrator-wide cMeta lock serializes these sync
tasks; rclone also locks individual pairs. Use **one orchestrator/state owner per
pair**, and do not run the old fleet sync and a new artifact on overlapping data
concurrently. Do not distribute this result to another machine as active state.

If all state is lost, preserve both data trees and inspect them before recovery.
Do not use `--initialize` to recover an established pair: that explicitly permits
the first source mirror again. Restore a consistent state backup, or rebuild via
a reviewed `--resync` merge without `--initialize` (same-name conflicts still need
a winner and backups). The old default merge behavior remains available for
definitions that omit `initial_mode`, for backward compatibility.

## Multiple locations and running servers

For A ↔ B ↔ C, an ordered `first,second,first` run propagates C's changes to A in
one batch, assuming no concurrent edits. It is not continuous replication or a
distributed transaction. Conflicting concurrent writes can need manual resolution
and another run. Run scheduled invocations on the designated orchestrator when
ready; the task does not install a scheduler.

File transfer does not install Python, activate a virtual environment, restart
servers, register new repositories or rebuild their indexes. Existing repository
registrations remain valid. After adding repositories, run `cx repo plug <path>`
in the **receiving runtime's CMETA home**, then `cx repo reindex <repo>` for changed
artifact metadata. A restart may be needed for a running server's in-memory state.
Do not copy home-level indexes or absolute-path registration files between hosts.

For cMeta applications, select persistent user data and shared application config;
keep machine-specific paths/URLs in separately prepared config. Quiesce writers
when taking a consistent multi-file user/account snapshot. `.env` files and other
secrets are transferred if they are in the selected tree and not excluded.

## Tests and existing syncs

The repository's CLI/metadata tests cover the wrapper and definition validation.
Real rclone integration checks run inside a cMeta test session:

```text
cxt test-session --start --type=sync-artifacts --title=Sync-checks -q
python task/sync/tests/check_sync.py <printed-sandbox-path>
```

The script uses its own CMETA home and disposable files. It checks initialization,
backups, edits/deletes/conflicts, ordered chains, copy/mirror, selection, preview
isolation and baseline guards. It expects rclone discoverable by `tool::rclone`.

Existing `rclone-to-ssh` and fleet `host sync` behavior is unchanged. Their rclone
workdirs remain where their existing definitions put them (often rclone's cache).
This prototype does not import fleet/host baselines: when migrating an established pair,
retire the old invocation, review both trees, and explicitly initialize this new
owner. See [rclone's bisync manual](https://rclone.org/bisync/) for its conflict,
resync, filtering and recovery semantics.
