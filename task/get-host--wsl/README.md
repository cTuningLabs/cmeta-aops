# get-host--wsl: a WSL distribution of a container template, as a host

The WSL resolver of the "run on any host" design (Windows only): the same template that makes a docker or podman
instance makes a WSL 2 distribution, recorded as a host artifact that every `cx host` command works on afterwards.
`--on=wsl` of any `cx task run`, `cx program run`, `cx tool setup` or `cx app run` makes and uses it.

```
cx task run get-host--wsl                                     # the template ubuntu, this machine's docker builds the image
cx task run get-host--wsl ubuntu --template.os_version=24.04
cx task run get-host--wsl ubuntu --instance=my-test           # a name of your own
cx task run get-host--wsl ubuntu --repos=ctuninglabs@cmeta-aops,my-repo
cx task run get-host--wsl ubuntu --location=X:\WSL\cmeta      # where the distribution's disk goes
cx task run get-host--wsl ubuntu --engine=podman              # the image built and exported with podman

cx program run test-nmm-c-cpu cpu -q --on=wsl                 # the same instance, made on first use

cx host ls --made
cx host run <instance> "cx --version"
cx host ssh <instance>
cx host down <instance>                                       # wsl --terminate; the next command starts it again
cx host destroy <instance>                                    # wsl --unregister: the distribution and its disk
```

What happens:

1. The instance is named after the place: `<this host>-wsl-<template>-<os_version>`, this host being its fleet
   alias when this machine has a host artifact, else its hostname. The same request finds the same instance:
   registered, it is returned (WSL starts it on the next command); gone, it is made again.
2. The template's image is built through the container category when missing (`cx container build`), then a
   container of it is exported as a root file system (`docker create` / `export` / `rm`) and imported with
   `wsl --import <name> <location>\<name> rootfs.tar --version 2`. The location is `--location`, else the key
   `location` of the config artifact `task-get-host--wsl`, else `%LOCALAPPDATA%\cmeta\wsl`.
3. Inside, as root: `/etc/wsl.conf` makes the template's user the default user and keeps the Windows PATH out of the
   Linux one (every missed program lookup would cost about 100 ms over the drive bridge); `~/.profile` sets
   `CMETA_HOME` and the user's PATH, since an image's `ENV` lines do not survive the export. Then, as the user, the
   repositories of this machine are plugged from their `/mnt/<drive>` paths (nothing is copied: a WSL distribution
   sees every drive), the index is built and `~/readme-cmeta.md` says how it was made and how to reach it.
4. The host artifact in the local repository: `type: wsl`, `access` (distro, user, shell), `via` = this machine's
   host artifact, `made_from` (template, parameters, engine, image, location, time, cMeta version), `mounts` (the
   `/mnt` paths), the tags `made-by-cmeta` and `wsl`; the instance is probed, so `cx host ls` shows its OS and the
   cMeta and AOPS versions inside.

The cMeta home inside is the instance's own: its cache is never shared with the machine (stability); the
repositories plugged are the machine's, live. A GPU inside WSL comes with the Windows driver, not with an image:
the template's compute overlays (docker images) do not apply here, the instance is `cpu`.
