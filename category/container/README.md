# container: docker and podman containers from cMeta templates

A `container` artifact is a template: an OS base with cMeta installed (`ubuntu`, `debian`, `fedora`,
`rockylinux`, `amazonlinux`, `azurelinux`, `opensuse`), or an app on top of one (`cmeta-test`, the smoke tests; `cmeta-cserver`, the cMeta
web front-end with the AOps repository baked in). Every string of a template may use `{{cmeta.<key>}}` (the
merged parameters) and `{{host.<key>}}`; the rendered Containerfile, entrypoint and build/run commands are plain
files anyone can reuse without cMeta. The same words work with docker and podman, on Windows, Linux and macOS.

```
cx container render <template> [--distro=debian] [--template.os_version=26.04] [--compute=cuda] [--out=<dir>]
cx container build  <template> [...] [--rebuild] [--pull] [--platform=linux/arm64]
cx container run    <template> [...] [--port=8010[:8004]] [--repo=<alias>] [--copy_repo=<alias>] [--input.<name>=<path>] [-- <cmd>]
cx container start  <template> [...] [--open]          # build + run detached + wait for open_url
cx container test   <template> [...]                   # build, run the template's tests, a PASS/FAIL table
cx container shell  <template or container name>       # an interactive shell
cx container ps | logs <name> | stop <name> | clean <template or name> [--images]
```

## Templates

| Template | Kind | What it is |
|---|---|---|
| `ubuntu` | base | Ubuntu (26.04 by default, `--template.os_version=24.04`) + tools + uv + cMeta, the user `cmeta` with sudo. `--compute=cuda` swaps in `nvidia/cuda:<version>-<flavour>-ubuntu<os>` and adds the GPU run flags. |
| `debian`, `fedora`, `rockylinux`, `amazonlinux`, `azurelinux`, `opensuse` | base | The same recipe on Debian 12, Fedora 44 (dnf), Rocky Linux 9 (dnf), Amazon Linux 2023 (dnf), Azure Linux 3.0 (tdnf), openSUSE Leap 16.0 (zypper; Tumbleweed with `--template.os_version=tumbleweed --template.from=opensuse/tumbleweed`). |
| `cmeta-test` | app | A base image plus a shell: the smoke tests (`cx --version`, `cx repo find`, `cx category find`, `/etc/os-release`, `nvidia-smi` on CUDA). |
| `cmeta-cserver` | app | The cMeta internal web server with `cmeta-aops` baked in; a repository mounted with `--repo=<alias>` is plugged in at start. Port 8004. |

A template's `_desc.yaml` starts with its own examples. Two kinds, told apart by `kind:`:

- `kind: base`: `template:` defaults (`os_version`, `cmeta_source` pypi | git | local, `cmeta_version`, `user`,
  ...), `package_manager:` and `packages:`, optional `compute:` overlays (`cuda`: another `FROM` plus run flags),
  the `image:` tag template, `tests:`.
- `kind: app`: the `bases:` it accepts, `template:` defaults (`port`, ...), `clone_repos:` baked into the image
  (an alias, or `{url, secret, checkout}` for a private repository cloned with a token passed as a BuildKit
  secret mount, never written into a layer), `app_lines:` (Containerfile lines after the clones), `ports:`,
  `volumes:`, `env:`, `secrets:` (names only), `config_from_env:`, `cmd:`, `open_url:`, `tests:`; `inherits:`
  another app. A private template lives in a private repository next to what it serves.

Image tags carry the parameters: `cmeta/ubuntu:26.04-cmeta-0.37.1`, `cmeta/cmeta-cserver:ubuntu-24.04`; a compute overlay
may name its own (`cmeta/ubuntu:24.04-cuda13.3.1-base-cmeta-latest`: the CUDA version and flavour). An app's compute
overlay sets the keys its base declares (llama-cpp's CUDA builds on the devel image).

## Engines, repositories, secrets

- `--engine=docker|podman`; the default is the config `container.engine`, else docker, else podman. Docker
  Desktop or the docker service must be running; podman on Windows and macOS needs `podman machine init` and
  `podman machine start` first.
- `--repo=<alias>` mounts a repository plugged on this machine into `/home/cmeta/repos/<alias>` (live edits
  show on reload; slow for file-heavy pages through a Docker Desktop or podman machine bind mount);
  `--copy_repo=<alias>` copies it into the image (fast; rebuilt when the repository changes).
- `--secret=<config alias>`: a config artifact whose values are secrets or `env:NAME` references; build-time
  secrets become BuildKit secret mounts, run-time ones a temporary `--env-file`. Nothing goes into a layer.
- `--input.<name>=<path>` mounts a folder at `/home/cmeta/inputs/<name>`; `{{inputs.<name>}}` names it in `cmd`.

The tasks `container-build` and `container-run` do the work and keep the records: every build is a cache
entry with the rendered Containerfile, the build script and `record.json`.

## Where this goes

The templates are the foundation of the "run on any host" design of cMeta: `--on=docker` on any `cx` run makes
an instance of a template (a persistent container recorded as a `host` artifact) and runs the same words inside.
