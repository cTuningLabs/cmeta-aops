# get-host--docker: a docker instance of a container template, as a host

The first resolver of the "run on any host" design: an instance of a container template is a host like any
other. The task makes it (or finds it), and every `cx host` command works on it afterwards.

```
cx task run get-host--docker                                    # this machine's docker, the template ubuntu
cx task run get-host--docker ubuntu --template.os_version=26.04
cx task run get-host--docker ubuntu --compute=cuda              # the template's CUDA overlay and its GPU run flags
cx task run get-host--docker ubuntu --arch=arm64                # --platform linux/arm64 (emulated on an x86 engine)
cx task run get-host--docker ubuntu --instance=my-test          # a name of your own
cx task run get-host--docker ubuntu --repos=ctuninglabs@cmeta-aops,fgg-hosts
cx task run get-host--docker ubuntu --data=models               # the data repositories (config::task cache_repos) mounted under ~/data: all by default, a subset, key=alias, or none
cx task run get-host--docker ubuntu --new_host                  # another instance of the same place (-2, -3 ...)
cx task run get-host--docker ubuntu --engine=podman

cx host ls --tags=made-by-cmeta
cx host run <instance> "cx --version"
cx host ssh <instance>
cx host down <instance>  /  cx host up <instance>               # the container keeps its cache across stop and start
cx host destroy <instance> [--image]                                 # the container, the artifact, the image
cx task run get-host--docker ubuntu --instance=web --ports=8080       # ports published on 127.0.0.1 (a server; --on_detach)
cx task run get-host--docker ubuntu --refresh_cmeta                  # the image's uv and cMeta built again (a newer release; --on_refresh_cmeta)
```

What happens:

1. The instance is named after the place: `<this host>-<engine>-<template>-<os_version>[-<compute>][-<arch>]`,
   this host being its fleet alias when this machine has a host artifact, else its hostname, and `-t<hash>` when
   other template keys are given (`--template.cuda_version=12.9.1`, another `from`): they make another image, so
   another instance. The same request finds the same instance: running, it is returned; stopped, it is started;
   gone, it is made again; `this host` is found by `cx host whoami` (the system_id its probe recorded, then the
   hostname).
   A CUDA instance on a Linux engine needs the NVIDIA Container Toolkit (docker's `nvidia` runtime, podman's CDI
   file): without it the task stops with the cure, `cx tool setup nvidia-container-toolkit --install`.
2. The template's image is built through the container category when missing (`cx container build`).
3. The container runs detached with `sleep infinity`, the labels `cmeta.container=1` and `cmeta.host=<instance>`,
   the repositories asked for mounted at `<home>/repos/<alias>` (the entrypoint plugs them and reindexes; the
   local repository and a repository flagged `secrets: true` are never mounted), the data repositories of this
   machine (`config::task cache_repos`: models, datasets) mounted at `<home>/data/<alias>` with the same config
   keys set inside, the GPU run flags of the compute overlay when asked for, `--platform` for another
   architecture. On a Linux engine the user inside gets this user's uid and gid, so the mounted repositories are
   writable (rootless podman: `--userns=keep-id`). The task waits for the entrypoint to plug and index them (a
   bind mount through Docker Desktop reads thousands of files slowly: minutes for the first index).
4. `<home>/readme-cmeta.md` inside says what it is, how it was made, how to reach it and how to rebuild it.
5. The host artifact in the local repository: `type: docker`, `access` (container, engine, image, run_args, so
   that `cx host up` can make the container again - every `cx host` command speaks podman to a podman instance),
   `via` = this machine's host artifact, `made_from` (template, parameters, compute, architecture, engine, image,
   time, cMeta version here, `cmeta_inside` - the cMeta of the image), `mounts`, the tag `made-by-cmeta`. An
   existing instance keeps the image it was made from: after `--refresh_cmeta`, `--new_host` (or `cx host destroy`
   first) makes one from the refreshed image.
6. The instance is probed (`cx host probe`): `cx host ls` shows its OS and the cMeta and AOPS versions inside.

The cMeta home inside is the instance's own: its cache is never shared with the machine (stability); the
repositories mounted are the machine's (live). Their files are live, but the index inside knows only what it saw: when
an instance is reused, each mounted repository whose first-level folders changed here since it was indexed (an
artifact added, moved or removed) is reindexed inside first, that repository only (`cx repo reindex <alias>`; the
signatures are in `mounted-signatures.json` next to the instance's artifact). get-host--wsl does the same. Everything runs through the engine's own commands (`docker run`,
`inspect`, `start`, `exec`, `cp`), printed with `-v`.

A container template can optionally preserve directories in Docker named volumes:

```yaml
instance_volumes:
  - name: '{instance}-cmeta'
    target: '{home}/CMETA'
```

The placeholders are the instance name and its Linux home. Only named volumes and absolute container
subdirectories are accepted. Existing templates behave as before. A volume belongs to this instance, keeps
its own CMETA and Linux filesystem, and survives container deletion/recreation; `cx host up` retains its mount
in the saved `access.run_args`. The orchestrator's `local` repository remains separate. Volumes are not deleted
by stopping or destroying an instance. Back up durable application data before explicitly removing a volume.

The instance is what `--on=docker` / `--on=podman` of any `cx task run`, `cx program run`, `cx tool setup` or
`cx app run` makes and uses (`docs/cmeta-aops/task-engine.md`, "Running the same words elsewhere").

## Bind individual host artifacts

Protected state subdirectories can alternatively use artifact-owned Linux named volumes:

~~~yaml
instance_artifacts:
  state:
    cref: state::local:my-application/volumes/app
    storage: volume
    mode: rw
~~~

The resolver records the engine, volume name and state UID in
`volumes/app/.cmeta-volume.json` inside the host state entry. The placeholder directory must be empty
on first use; changing a populated bind directory to volume storage requires explicit migration.
The actual application data stays in the engine's Linux filesystem. This enables a Windows
orchestrator to own Linux application storage without putting legacy files on NTFS.
Volume names are stable for the artifact UID/subpath; labels verify ownership, and loss of a
registered volume is refused. Stopping/destroying a container never removes these volumes.

For general task/program/tool delegation, pass the same selection as
`--on_artifacts.state.cref=state::local:my-application/volumes/app --on_artifacts.state.storage=volume`.
`CMETA_ARTIFACT_MOUNTS` includes `storage`, `volume`, `engine` and `filesystem: linux` for this case,
alongside the controller's `source_os`. Applications must check the physical storage type instead of
rejecting Linux volumes solely because their controller runs Windows. Existing string declarations
and `storage: bind` keep their previous behavior. Completed archives can bind to separate host results.

Use this for host-owned application state without mounting the orchestrator's entire local repository:

```yaml
instance_artifacts:
  state:
    cref: result::local:my-application-state
    mode: rw
```

Or pass `--artifacts.state=result::local:my-application-state` to this resolver;
task execution forwards `--on_artifacts.state=result::local:my-application-state`.
Mappings can use `{cref: ..., mode: ro}` for read-only inputs. Cache/result references accept root artifacts.
Protected state artifacts also accept ordinary contained subpaths, such as
`state::local:my-application/volumes/app`; parent traversal and escaping symlinks are rejected.
A writable artifact is created when missing (results and state are permanent);
a read-only artifact must already exist. Symlinks resolve to the actual host directory before mounting.

The mount is `<home>/artifacts/<key>`. `CMETA_ARTIFACT_MOUNTS` is a JSON object keyed by that name,
containing `cref`, `path` (inside), `host_path`, `mode` and `source_os`. Application tasks can use it to
find the same state they use natively and print a host-accessible backup path. They still need to validate
their filesystem/platform requirements. The generic resolver supports Windows paths; a legacy Linux
database/application may require a Linux filesystem.

Mount descriptions are retained in the host artifact and recreation arguments. An existing artifact-mounted
instance refuses changed selections: use another instance or deliberately recreate it. Existing instances
without this feature, including named-volume instances, keep their previous mounts despite newer template
defaults. Removing a container does not remove its separately owned host result.
