# Run a website with cMeta

## Standalone project or current home

Websites with a `project` definition can use the shared `manage-cmeta-project` task:

```sh
cx task run run-website \
    --project-home="$HOME/CMETA-MY-SITE" \
    --mode=native

cx task run run-website website::my-site \
    --current \
    --mode=native
```

The first command uses the existing project's `project.yaml`, repositories and
optional venv. The second uses the invoking Python and current cMeta home directly.
`--params.*` and `--use.*` customize the application. With a project home,
`--mode=docker` uses its declared container recipe and persistent Docker local repo.
The new project workflow requires a project home for Docker; its `--current` mode
is native. Status/stop/logs are available for its Docker execution; native servers
stay in the foreground. No service manager is installed.

See [manage-cmeta-project](../manage-cmeta-project/README.md) for bootstrap, optional
venv version inheritance, generated scripts and data ownership. Existing deployments
using the state/volume workflow below keep their previous behavior.

## Windows orchestrator with Linux Docker storage

On Windows, Docker mode now defaults to `--storage=volume`. The protected state artifact is created
in the active Windows orchestrator's local repository. Portable source, input archives, private cMeta
repositories and diagnostics stay in that entry. `volumes/app/.cmeta-volume.json` identifies its
artifact-owned Linux volume; the application's live files and databases are in that volume.

~~~bat
cxt run-website task::my-website ^
      --deployment=windows-docker ^
      --mode=docker ^
      --repositories=isolated ^
      --storage=volume ^
      --params.port=8148 ^
      --detach ^
      -q
~~~

There is no `--on` in this command: the current orchestrator creates the state, then launches its
worker in Docker. General `--on=docker:...` instead delegates the complete command to a container's
orchestrator. Linux deployments keep their existing `bind` default; newer applications with
Windows-compatible data may explicitly use `--storage=bind` in Docker mode.

Volume names derive from the state UID and subpath; labels verify ownership. Container removal and
recreation preserve the volume. A missing registered volume causes an error instead of creating an
empty replacement. Moving/copying the Windows state directory alone does not transfer that volume.
Use `stop`, then `backup`; completed tar/SQL snapshots are written into the Windows `result` history.
Transfer those completed snapshots and restore on the destination. Docker image/container snapshots
do not include mounted volume contents.

For a fresh restore that reuses an existing deployment's backup history, keep `--deployment` the same
and select a new `--state-cref` plus a free port. The new state gets its own volume and restores the
latest compatible completed snapshot. Switching storage in place is refused; use a separate state.
Native Windows execution of Linux-only recipes remains unsupported.

The general `state` category and cMeta engine need no storage-specific API. The volume registration
is ordinary state payload; `get-host--docker` implements the storage mapping.

The orchestrator selects a recipe; the deployed website keeps its own source, private repositories and
working volumes in a protected `state` artifact. Re-running preparation preserves deployed changes.
Native and Docker execution use the same application task and files. Completed backups go to a separate
protected `result` history.

~~~sh
cxt run-website task::my-website plan --deployment=production
cxt run-website task::my-website --deployment=production --mode=docker --params.port=8138 --detach -q
cxt run-website task::my-website status --deployment=production -q
cxt run-website task::my-website stop --deployment=production -q
cxt run-website task::my-website backup --deployment=production -q
~~~

A website artifact can provide `deployment.task` and be passed instead of the task. Task and container
references use aliases/UIDs; their containing repository can change. The owning task-category repository
is resolved as the tooling source rather than requiring a particular repository name.

Default state: `state::local:website-<deployment.name>-<deployment argument>`. Select another existing or
new root using `--state-cref=state::<repo>:<name>`. Deployment names distinguish simultaneous instances.
`status`, `stop` and `backup` reuse the last execution parameters. Different running instances need
different ports and service-specific ports in native mode.

~~~text
state entry/
  _cmeta.yaml               permanent: true
  _desc.yaml                declared recipe, layout and links
  deployment.json           portable deployment manifest
  execution.json            last execution mode and parameters
  src/                      private recipe/source repository
  inputs/                   private repository of checked result histories
  CMETA/                    private cMeta home; repositories/indexes
  volumes/app/              writable application files and service data
  tools/native/             optional captured native software
  diagnostics/              launch requests and logs
  .venv/                    optional native runner environment
result entry/
  ck/<dated-snapshot>/       completed backup written by the application task
~~~

The first preparation copies declared recipes, input histories and the orchestrator's tooling owner
repository. It excludes the tooling repository's top-level cache/result/state/log/tmp and development
directories. The source and input repositories receive new repository identities; artifact UIDs remain
stable. Subsequent preparation does not refresh sources or restore over live data. This prototype does
not provide an automatic source-upgrade/merge operation. Choose a new deployment or edit deployed source
deliberately. Container-image recipes are resolved by the orchestrator; changing a staged Containerfile
alone does not rebuild the software image.

`--repositories=isolated` is the default. `--repositories=global --mode=native` selects the orchestrator's
repositories for a development run; Docker uses isolated repositories. Only the child process changes
CMETA_HOME. The caller's environment stays in effect. `--venv --mode=native` creates a runner venv inside
the state and installs cMeta through the standard setup task, without installing into the orchestrator's
Python. The application recipe still owns its own software/dependency setup.

Stop before switching modes:

~~~sh
cxt run-website task::my-website stop --deployment=production -q
cxt run-website task::my-website --deployment=production --mode=native --detach -q
~~~

Native execution requires the application's native libraries. A Linux recipe may declare
`deployment.native_export`: `export-native` captures its declared image binaries and shared libraries
under `tools/native`, then native runs reuse them without installing host services. This is an optional
Linux x86_64 migration aid, not a cross-OS binary translator. Use a Linux/WSL filesystem for legacy sites
with case-sensitive names. Linux/WSL execution can be selected from Windows with `--on=<host>`.

Docker binds the whole workspace plus its `volumes/app` subdirectory and separate backup result. It
publishes the application port on host loopback. Stopping Docker execution also stops its container,
releasing that port for native execution. Detached startup reports the launch log; use `status` to check
readiness, especially while restoring/indexing. These recipes do not install boot autostart.

Moving stopped state between Linux hosts or between host/container paths preserves data. The worker
rebases registered paths inside its private home and rebuilds its derived index, preserving old index
files in diagnostics. It refuses relocation if that private home includes repositories outside the
state. Keep private repositories inside the entry. Rebuild `.venv` for another host. Application-level
derived indexes may also need rebuilding after path changes. Never bisync live database/Elasticsearch
directories: stop the deployment, or transfer completed backups and restore a separate deployment.

The application task declares `_desc.yaml`:

~~~yaml
deployment:
  name: example
  platform: linux
  mode: docker
  container: container::example,<uid>
  params:
    port: 8138
  inputs:
    - result::example-snapshots,<uid>
~~~

It accepts `action` and `state_cref`, and `backup_cref` for backup. `CMETA_ARTIFACT_MOUNTS` describes
workspace/state/backups paths. Private legacy examples live in the separately movable website recipes.
`--params.<name>=<value>` passes their own options without adding them to this generic launcher.
