# Manage a standalone cMeta project

This task provides reusable project setup and launch automation. A website describes
its application task, repositories and optional container recipe. A standalone
project owns its repositories and data; the invoking cMeta supplies the automation.
No service, synchronization job or scheduled restart is installed.

## Bootstrap or adopt a project

```sh
cx task run manage-cmeta-project bootstrap \
    --definition=website::my-site \
    --project-home="$HOME/CMETA-MY-SITE"
```

`bootstrap` creates missing declared repositories and a local repository. A repository
can declare `source` (an existing directory), `url` (Git), or `zip_file` (a repository
archive). Private repositories without a source must be supplied under `repos/` first.
Existing repositories and the project's saved `project.yaml` are preserved.
`adopt` registers repositories already inside a project without downloading them.

The project home can also be a cRef with a contained subdirectory, resolved by the
invoking orchestrator:

```sh
cx task run manage-cmeta-project info \
    --project-home=website::my-site/CMETA-MY-SITE
```

Use this form for links between artifacts instead of machine-specific absolute
paths. The owning artifact must already exist; bootstrap can create its project
subdirectory. Parent traversal (`..`) and paths escaping the artifact are rejected.
An existing deployment can be moved with its data, then adopted/reindexed at its
new home. Venv launchers and application configuration containing absolute paths
may need repair or recreation after a move; reindexing only repairs cMeta registrations.

Setup **reuses the invoking Python and cMeta by default**. It does not create a venv
or select a newer Python/cMeta release automatically. To create an optional venv:

```sh
cx task run manage-cmeta-project setup \
    --project-home="$HOME/CMETA-MY-SITE" \
    --venv
```

A new venv uses the invoking Python interpreter and cMeta version. If the invoking
cMeta is an editable development checkout, setup installs a **non-editable copy** of
that checkout, so the project does not retain an editable dependency on its source.
An existing project venv keeps its Python and cMeta unless you request a change.

Explicit overrides use the usual task customization syntax:

```sh
cx task run manage-cmeta-project setup \
    --project-home="$HOME/CMETA-MY-SITE" \
    --venv \
    --use.python.version=3.14 \
    --use.cmeta.version=0.37.1
```

Explicit Python selection uses `tool::uv` and stores managed Python under
`.setup/tools/python`. `--use.cmeta.version=latest` explicitly requests the newest
cMeta from the package index. `--python` and `--cmeta` are aliases for version
selection. A definition may supply explicit `python`/`cmeta` defaults, but neither
is required. `requirements` selects an optional application requirements file;
`--latest-deps` selects `requirements_latest` instead. Requirements may be artifact
references with contained subpaths, rather than fixed repository paths.

An incompatible existing Python venv is never deleted automatically: preserve or
rename `.venv`, then create another. A venv is OS-specific and should be recreated
after moving between Windows and Linux. The resolved package list is recorded at
`.setup/runtime/requirements-resolved.txt`.

## Use the project

Bootstrap/adopt generates these thin adapters in the project root:

| Scripts (`.bat` / `.sh`) | Purpose |
|---|---|
| `__setup_venv` | Optional venv, with inherited or explicit versions |
| `__setup_config` | Merge declared configuration into this project's local repo |
| `__reindex` | Discover/register valid repositories directly inside `repos/` |
| `__info` | Show the actual selected Python, cMeta and home |
| `__update_git_repos` | Update clean Git repositories, then reindex |
| `__run_server` | Run the application task natively in the foreground |
| `__run_server_in_docker` | Run the declared container recipe |
| `__cx` | Run any cMeta command in the project |
| `__source` | Select the project in the current shell; also available as `.ps1` |

Scripts accept additional CLI flags and use the shared tasks; there is no per-project
Python manager. Regenerate them with action `scripts`. Generation refuses to overwrite
unknown or user-modified scripts; archive such scripts first. Definitions use alias/UID
references and do not require artifacts to stay in particular repositories.

```sh
./__info.sh

./__run_server.sh \
    --params.port=8118

# In another session, select the project's CLI:
source ./__source.sh
cx --version
```

Windows: use `__run_server.bat`; select a cmd session with `call __source.bat`, or
PowerShell with `. .\__source.ps1`. Normal runs prefer the project's venv when present.
`--current-env` on a management/run script deliberately uses its invoking Python/cMeta.
`__cx` always prefers the project venv. Application dependency resolution may install
missing packages into whichever interpreter you select.

Git updates default to each remote's current default branch and fast-forward only.
`--repo`, `--branch`, `--release` or `--checkout` narrow the update. `--status` previews
it. Dirty or diverged repositories are refused; local changes are never reset.

Native startup stays in the foreground; stop it with Ctrl+C. For a simple Linux
background run, use ordinary `nohup ./__run_server.sh >server-console.log 2>&1 &`.
Native process supervision, automatic restart and native stop/log commands are not
provided by this prototype. Existing host URL checks can monitor its endpoint.

## Run in the current cMeta home

```sh
cx task run run-website website::my-site \
    --current \
    --mode=native \
    --params.port=8118
```

This uses the current Python and current registered repositories, including their
local repository. It creates no standalone directory, venv or root scripts. The
application task performs its usual dependency setup. A website with a `project`
definition defaults to this mode when no project home is supplied. The equivalent
manager call is `manage-cmeta-project run --definition=website::my-site --current`.

## Docker with a standalone project

```sh
./__run_server_in_docker.sh \
    --params.port=8118

./__run_server_in_docker.sh --status
./__run_server_in_docker.sh --logs
./__run_server_in_docker.sh --stop
```

The container recipe controls its stable software and application entrypoint. Image
versions remain explicitly declared in `docker.template`; optional native-venv setup
does not silently change those image pins. Numeric `--use.python.version` and
`--use.cmeta.version` overrides can be passed to the Docker launcher too.

On first launch, `repos/local` is copied to `docker/repos/local`, excluding only its
top-level `cache` and `tmp`. A completion marker protects this initial seed. Subsequent
launches reuse the Docker local repo and never merge/overwrite it from native local.
All other valid immediate repositories are mounted read-only; Docker local and console
logs are writable host directories. Container CMETA registrations/indexes are recreated
inside the container. A host `docker/CMETA` directory is unnecessary.

Stopping/recreating the container preserves host data. Native and Docker local repositories
become independent after the seed. Back up the data itself, not just the image. Application
database files need their own consistent export/backup procedure. Legacy Linux databases
on Windows still use the older `run-website` state/volume workflow; this standalone
prototype does not convert those deployments. `--current --mode=docker` is not a supported
combination in the new project workflow.

## Definition and extension points

Generated Linux project scripts also include `__run_server_nohup.sh` for a manual
background start. It writes `.setup/runtime/server.log` and `server.pid`, uses a
short start lock, and avoids starting a second matching live launcher. It does
not install a service or arrange boot startup. A host artifact can call this
script in `commands.after_restart`; declaring the project's root, venv and
health URL lets the host commands select and check that environment.

```sh
./__run_server_nohup.sh
tail -f .setup/runtime/server.log
```

The website's `_desc.yaml` has `project.name`, `project.task`, optional `repositories`,
`requirements`, `params`, `os_params.windows/linux`, `runtime_config` and `docker`.
Bootstrap saves this block as `project.yaml`; edit that file for deployment-specific
choices. Repeated bootstrap does not replace it. Runtime overrides use `--params.KEY`;
`--use.*` dependency overrides pass through to the application task. `config`, `host`,
`port`, `env-file` and `public-url` also have direct CLI aliases.

The cMeta website frontend can forward through `automation.run` / `automation.bootstrap`
to these tasks. Older engines can use `cx task run` and the generated scripts directly.
This keeps the existing static website builder and historical runner behavior compatible.

A remote machine needs Python/cMeta/cmeta-aops and access to the required project
repositories. The same bootstrap command can run there without a laptop or synchronization.
Existing host transport/setup and protected sync/result state can be connected later.
This implementation does not change host descriptions, create sync artifacts or deploy
remote services. Large website captures remain portable result artifacts consumed by
their application recipes; the manager does not invent another backup format.
