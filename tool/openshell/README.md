# openshell: NVIDIA OpenShell, the sandbox runtime for AI agents

[OpenShell](https://github.com/NVIDIA/OpenShell) (Apache-2.0) runs AI agents in sandboxes, Docker or Podman
containers or micro-VMs, under a YAML policy that limits their files, processes, network and credentials. It has two
binaries: the CLI `openshell` and the gateway `openshell-gateway`, the control plane that creates the sandboxes.

```sh
cx tool setup openshell                        # detect, else install the pinned release (0.1.4)
cx tool setup openshell --versions             # the released versions
cx tool run openshell -- --help
cx task run run-openshell-gateway start        # a local gateway of this user (Docker or Podman), registered with the CLI
cx task run run-openshell-gateway test         # a sandbox that runs one command and is deleted
```

## How it is installed

An installation on the PATH is used first: the deb, rpm or snap of upstream's `install.sh`, or Homebrew. Otherwise
the pinned release is downloaded into the cMeta cache, with no package, no service and no root rights:

| OS | CLI | Gateway |
|---|---|---|
| Linux x86_64, aarch64 | `openshell-<cpu>-unknown-linux-musl.tar.gz` (static) | `openshell-gateway-<cpu>-unknown-linux-gnu.tar.gz` (glibc 2.28 or newer) |
| macOS on Apple Silicon | `openshell-aarch64-apple-darwin.tar.gz` | `openshell-gateway-aarch64-apple-darwin.tar.gz` |
| Windows | none: run it in WSL2 (`--on=wsl`) | none |

Both files are checked against the SHA-256 lists of the release (`openshell-checksums-sha256.txt`,
`openshell-gateway-checksums-sha256.txt`). The gateway's path is in the result: `features.paths.gateway`.

## The gateway

Upstream's installer runs the gateway as a service: a systemd user unit on Linux, `brew services` on macOS. The task
[`run-openshell-gateway`](../../task/run-openshell-gateway/README.md) runs it as a background process of this user
instead, with its keys, configuration, database and log in a folder of its own, plaintext on 127.0.0.1 only, and the
gateway's telemetry off. It registers the gateway with the CLI under a name, so `cx tool run openshell -- sandbox
list` works afterwards.
