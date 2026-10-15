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
cx task run get-host--docker ubuntu --new_host                  # another instance of the same place (-2, -3 ...)
cx task run get-host--docker ubuntu --engine=podman

cx host ls --tags=made-by-cmeta
cx host run <instance> "cx --version"
cx host ssh <instance>
cx host down <instance>  /  cx host up <instance>               # the container keeps its cache across stop and start
cx host destroy <instance> [--image]                                 # the container, the artifact, the image
```

What happens:

1. The instance is named after the place: `<this host>-<engine>-<template>-<os_version>[-<compute>][-<arch>]`,
   this host being its fleet alias when this machine has a host artifact, else its hostname. The same request
   finds the same instance: running, it is returned; stopped, it is started; gone, it is made again.
2. The template's image is built through the container category when missing (`cx container build`).
3. The container runs detached with `sleep infinity`, the labels `cmeta.container=1` and `cmeta.host=<instance>`,
   the repositories asked for mounted at `<home>/repos/<alias>` (the entrypoint plugs them and reindexes; the
   local repository and a repository flagged `secrets: true` are never mounted), the GPU run flags of the compute
   overlay when asked for, `--platform` for another architecture.
4. `<home>/readme-cmeta.md` inside says what it is, how it was made, how to reach it and how to rebuild it.
5. The host artifact in the local repository: `type: docker`, `access` (container, image, run_args, so that
   `cx host up` can make the container again), `via` = this machine's host artifact, `made_from` (template,
   parameters, compute, architecture, engine, image, time, cMeta version), `mounts`, the tag `made-by-cmeta`.

The cMeta home inside is the instance's own: its cache is never shared with the machine (stability); the
repositories mounted are the machine's (live). Everything runs through the engine's own commands (`docker run`,
`inspect`, `start`, `exec`, `cp`), printed with `-v`.
