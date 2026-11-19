# prometheus

Prometheus from its official release archive on GitHub, checked against the release's `sha256sums.txt`; the whole
distribution is kept, so `promtool` (checks configurations, imports history) is beside `prometheus`. Windows, Linux
and macOS on amd64 and arm64. Nothing is started: a server is the task `run-prometheus-server`.

```bash
cx tool setup prometheus
cx tool run prometheus -- --version
cx tool setup prometheus --version=3.16.0
```
