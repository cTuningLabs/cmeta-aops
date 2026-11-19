# run-prometheus-server

A Prometheus server on this machine. It reads the `/metrics` of the servers it is given every few seconds and keeps
the readings, so that Grafana (`run-grafana-server`) can draw them over time. By default it reads the AI gateway
server (8401), llama.cpp (8686) and vLLM (8868) of this machine; a server that is not running is shown down, nothing
else.

```bash
cx task run run-prometheus-server                          # 127.0.0.1:9090, detached
cx task run run-prometheus-server --action=status          # the server and every target: up, or down and why
cx task run run-prometheus-server --action=stop
cx task run run-prometheus-server --targets=ai-gateway=127.0.0.1:8401,other-machine=100.64.0.7:8686
cx task run run-prometheus-server --foreground             # in this console (a host keeps it so: server: run)
```

What a start takes when its command line does not say - the targets, how often it reads them, how long it keeps
them - is the config `task-run-prometheus-server` (its `configs:` block in `_desc.yaml`):

```bash
cx config set task-run-prometheus-server --meta.retention=90d
```

Its configuration (`prometheus.yml`, written at every start and checked with `promtool`), its data, its record and
its log are in the state artifact `local:prometheus-server-<port>`. It listens on 127.0.0.1 only by default:
Prometheus has no sign-in, so whoever reaches its port reads every series.

## What it can and cannot know

A server's `/metrics` holds its totals since it started, no history. Prometheus records what it reads from the moment
it runs; a total it finds at its first reading cannot be spread back over the time before. Keep it running when the
numbers over time matter. The AI gateway server keeps a line per request as well, which is its full record whatever
Prometheus did.

## Importing the time before it ran

`--action=import --file=<OpenMetrics with timestamps>` adds samples of the past: promtool makes blocks of them, the
server stops, the blocks join its data, it starts again (one its host keeps is started again by its supervisor); each
import is recorded in `imports.json` of the state artifact. The time it began to read live (`scraped-since.txt`,
written at the first start of an empty data folder, or found once from its blocks and its head) is in `--action=status`:
an import must end there, or a series would hold two counters at once. The AI gateway server of cmeta-aops-ext2 uses it
for its history (`cx task run run-ai-gateway-server --action=to-prometheus`: its lines replayed into the series its
`/metrics` shows, from the end of the last import to that time).

The tool: `tool/prometheus` (the official release archive, checked against its `sha256sums.txt`).
