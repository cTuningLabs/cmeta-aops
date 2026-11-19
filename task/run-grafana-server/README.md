# run-grafana-server

A Grafana server on this machine, with the Prometheus of `run-prometheus-server` as its data source and three boards
in its folder **cMeta**: the AI gateway server (requests, tokens, the provider's cache, times, by route and model),
llama.cpp (tokens, speeds, its cache, requests) and vLLM (tokens, requests, its caches, times).

```bash
cx task run run-grafana-server                       # 127.0.0.1:3000/grafana/ui, detached; the boards at /grafana/ui/dashboards/f/cmeta
cx task run run-grafana-server --action=status
cx task run run-grafana-server --action=stop
cx task run run-grafana-server --foreground          # in this console (a host keeps it so: server: run)
cx task run run-grafana-server --action=reload       # the data sources and boards read again by the running server
```

Grafana stores no measurements: it draws from Prometheus, so it can run only when someone looks.

- **Boards**: written again at every start from the panels in `api_v1.py` (provisioned: a change made in Grafana's
  editor cannot be saved over them - save a copy).
- **Sign-in**: on 127.0.0.1 anyone on this machine may look at the boards without signing in (a viewer); on any other
  address only after signing in (`--anonymous=yes|no` decides otherwise). The admin is `admin`; the password is made
  once and kept in the state artifact (`admin-password.txt`), never printed.
- **Lean**: only the Prometheus data source is loaded (each built-in data source is a program of its own - `plugins:
  all` in the config loads them all), no plugin is fetched at a start, nothing is reported home (no usage report, no
  update checks, no news).
- **On Windows** it starts without a window and so do the programs it starts.
- **Embedding**: allowed, so that a cMeta page can show a board.
- **Data sources**: the Prometheus of `prometheus` (the default) and the others named in `datasources`
  (`<name>=<URL>,...`); every board has a "Prometheus" selector over them.
- **A sub-path**: served under `sub_path` (`/grafana/ui` by default), so that a cMeta server passes it through behind
  its sign-in (cMeta 0.45's `cserver_proxy`, the page cserver.grafana); its live updates (websockets) are off.
- **vLLM's boards**: those vLLM publishes for its release, declared in `_desc.yaml` (`upstream_boards`: URL and
  SHA-256), downloaded once into the state artifact, checked, in a folder vLLM (`vllm_boards: yes|no`).

Its settings (`grafana.ini`, written at every start), data, provisioning, record and log are in the state artifact
`local:grafana-server-<port>`; what a start takes when its command line does not say is the config
`task-run-grafana-server`.

The tool: `tool/grafana` (the open-source edition from dl.grafana.com, checked against the archive's `.sha256`).
