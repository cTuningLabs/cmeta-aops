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
```

What happens:

1. The instance is named after the place: `<this host>-<engine>-<template>-<os_version>[-<compute>][-<arch>]`,
   this host being its fleet alias when this machine has a host artifact, else its hostname. The same request
   finds the same instance: running, it is returned; stopped, it is started; gone, it is made again; `this host`
   is found by `cx host whoami` (the system_id its probe recorded, then the hostname).
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
   time, cMeta version), `mounts`, the tag `made-by-cmeta`.
6. The instance is probed (`cx host probe`): `cx host ls` shows its OS and the cMeta and AOPS versions inside.

The cMeta home inside is the instance's own: its cache is never shared with the machine (stability); the
repositories mounted are the machine's (live). Everything runs through the engine's own commands (`docker run`,
`inspect`, `start`, `exec`, `cp`), printed with `-v`.

The instance is what `--on=docker` / `--on=podman` of any `cx task run`, `cx program run`, `cx tool setup` or
`cx app run` makes and uses (`docs/cmeta-aops/task-engine.md`, "Running the same words elsewhere").
