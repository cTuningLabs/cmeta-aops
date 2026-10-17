# run-openshell-gateway

A local [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) gateway of this user. The gateway is the control
plane the `openshell` CLI talks to: it creates the sandboxes (Docker or Podman containers, or micro-VMs) and applies
their policies. Upstream's installer runs it as a service: a systemd user unit from a deb or rpm package, or `brew
services`. This task runs the binaries of [`tool/openshell`](../../tool/openshell/README.md) instead, as a background
process of this user, with no package, no service and no root rights.

```sh
cx task run run-openshell-gateway                      # start (or find) the gateway "cmeta", then its status
cx task run run-openshell-gateway status
cx task run run-openshell-gateway test                 # a sandbox that runs one command, then is deleted
cx task run run-openshell-gateway stop                 # the process; its registration and folder stay
cx task run run-openshell-gateway remove               # stop, unregister, delete its folder

cx tool run openshell -- -g cmeta sandbox create --name demo     # the CLI itself, afterwards
cx task run run-openshell-gateway test --on=wsl        # Windows: in WSL2
```

| Option | Default | What it does |
|---|---|---|
| `--name` | `cmeta` | the gateway's name: its registration with the CLI and its work folder |
| `--port` | `17691` | its port on 127.0.0.1 (upstream's packaged gateway uses 17670) |
| `--driver` | Docker when its daemon answers, else Podman 5+, else the gateway's detection | `docker`, `podman` or `vm` |
| `--workdir` | `~/.local/state/openshell/cmeta-<name>` | its keys, `gateway.toml`, database, `gateway.log` and `gateway.pid` |
| `--config_home` | the CLI's own (`~/.config`) | where the CLI keeps its registrations: a folder of a throwaway run |
| `--wait` | `120` | seconds to wait for the gateway to listen |
| `--image`, `--timeout` | the gateway's, `900` | the test sandbox's image (`--from`) and its time limit |

## What start does

1. The keys of the gateway with `openshell-gateway generate-certs` (once): the sandbox JWT keys are the ones it uses.
2. `gateway.toml`: 127.0.0.1 only, plaintext, local users let in without a login (as upstream's own Docker compose
   setup), the driver when asked. Then `openshell-gateway config preflight`.
3. The gateway in a session of its own, so that it outlives the shell and an ssh connection that started it, with
   its database in the work folder and its telemetry off (`OPENSHELL_TELEMETRY_ENABLED=false`).
4. A wait until it listens, then `openshell gateway add http://127.0.0.1:<port> --local --name <name>`.

A gateway that already runs is found again: `start` then only checks its registration. `stop` ends its process
group. The sandboxes are containers of the driver, labelled by OpenShell; a stopped gateway leaves them to it.

## Limits

- Windows has no OpenShell build: run the task in WSL2 (`--on=wsl`), where Docker Desktop's WSL integration or a
  Docker Engine inside the distribution is the driver.
- The gateway needs glibc 2.28 or newer on Linux, and a running Docker Engine 28+ or Podman 5 (rootless, its user
  socket active) for its sandboxes. `cx tool run openshell -- doctor check` tells.
- Docker Desktop (macOS, and WSL2 through its integration): the sandbox's supervisor reaches the gateway through
  Docker's host networking, which Docker Desktop has off by default - switch it on in Settings > Resources > Network
  > Enable host networking (not with Enhanced Container Isolation). Without it the test sandbox fails, and the task
  says so. Docker Engine on Linux and Podman 5 on Linux need nothing.
- The first sandbox pulls three images (`nvcr.io/nvidia/base/ubuntu:24.04` and OpenShell's sandbox and supervisor
  images from ghcr.io).
