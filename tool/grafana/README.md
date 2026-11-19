# grafana

Grafana, the open-source edition (AGPL-3.0), from its official archive at dl.grafana.com, checked against the
archive's `.sha256`; the whole distribution is kept (`bin/`, `conf/`, `public/`: the server needs them all). Windows,
Linux and macOS on amd64 and arm64. Its folder was `grafana-v<version>/` in older releases and is `grafana-<version>/`
in newer ones: both are found. Nothing is started: a server is the task `run-grafana-server`.

```bash
cx tool setup grafana
cx tool run grafana -- --version
cx tool setup grafana --version=13.3.1
```
